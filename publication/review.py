"""Checkpoint 2: World-confirmed admin sign-off of a generated report version, off chain.

Every installed report version (generated, partial, automatic-lane or imported reference) is in the admin
review queue; generation and draft rendering need no prior sign-off. A review target binds the exact
immutable version: report SHA-256, candidate and run/case lineage (explicitly null when absent), the
evidence manifest whose files are re-hashed, and the rendered artifact manifest when a render exists.

Each decision attempt binds the target digest, decision, reason, audience/resource, scope, nonce,
issue/expiry and the initiating admin, then starts a fresh World device grant. Only that admin, still an
enabled reviewer holding report_review and still signed in, can complete it, and only while the target is
unchanged. The result is an append-only receipt for that one decision and target.

Recording a decision starts no research, signs nothing for the chain and publishes nothing. Changed report
bytes, evidence or rendered artifacts produce a new target that needs a fresh sign-off, so an older
approval never approves a revision. Local /reports/{id}/{version}/review records are never consulted.
"""
from __future__ import annotations
import json
import logging
import secrets
from pathlib import Path

from store import DATA, db, digest, dumps, ident, now
from . import admin, service
from . import canonical as cn
from .config import AdminConfig
from .world import Denied, Error, Expired, SlowDown, TokenInvalid, Tokens, VERIFIER_VERSION, WorldClient, WorldError

log = logging.getLogger('publication.review')
TARGET_SCHEMA = 'scooby.report-review-target/1'
BINDING_SCHEMA = 'scooby.report-review-binding/1'
STATUS_SCHEMA = 'scooby.report-review-status/1'
QUEUE_SCHEMA = 'scooby.admin-review-queue/1'
DETAIL_SCHEMA = 'scooby.admin-review/1'
ATTEMPT_SCHEMA = 'scooby.admin-review-attempt/1'
POLICY_VERSION = 'scooby.report-review-policy/1'
SCOPE = 'report_review'
DECISION_STATE = {'approve': 'approved', 'reject': 'rejected', 'revise': 'revision_requested'}


def _audit(c, target_id: str | None, kind: str, actor: str, detail: dict | None = None) -> None:
    """Append-only. Never pass tokens, device codes or subjects in detail."""
    c.execute('INSERT INTO rev_events(target_id,kind,actor,detail_json,created) VALUES(?,?,?,?,?)',
              (target_id, kind, actor, json.dumps(detail or {}, sort_keys=True), now()))


# ---------------------------------------------------------------------------- targets
def _report_row(c, report_id: str, version: str):
    rep = c.execute('SELECT * FROM reports WHERE id=? AND version=?', (report_id, version)).fetchone()
    if not rep:
        raise service.NotFound('report version not found')
    return rep


def _report_bytes(rep) -> bytes:
    path = Path(rep['path']) / 'report.json'
    if path.is_symlink() or not path.is_file():
        raise service.Conflict('report bytes are missing on disk')
    raw = path.read_bytes()
    if digest(raw) != rep['sha256']:
        raise service.Conflict('report bytes changed since import; a new immutable version and review are required')
    return raw


def _check_file(base: Path, rel: str, expected: str) -> None:
    """Re-hash one bundle file. Missing, linked, escaping or changed files fail closed."""
    path = base
    for part in rel.split('/'):
        if part in ('', '.', '..') or '\\' in part:
            raise service.Conflict(f'evidence path {rel!r} is not a plain bundle path')
        path = path / part
        if path.is_symlink():
            raise service.Conflict(f'evidence path {rel!r} is a link')
    if not path.is_file() or digest(path.read_bytes()) != expected:
        raise service.Conflict(f'evidence file {rel} is missing or changed; the report needs a fresh review target')


def _case_decision(c, run_id: str):
    """Case lineage from the case bridge, when its tables exist; None for imports and references."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='case_decisions'").fetchone():
        return None
    return c.execute('SELECT case_id, action FROM case_decisions WHERE run_id=?', (run_id,)).fetchone()


def _render_manifest(c, report_id: str, version: str, sha: str) -> str | None:
    """SHA-256 of the newest completed render manifest for exactly these report bytes, re-checked on disk."""
    want = {'id': report_id, 'version': version, 'sha256': sha}
    rows = c.execute('''SELECT j.id, j.ref, m.sha256 FROM jobs j JOIN render_manifests m ON m.job_id=j.id
                        WHERE j.kind='render' AND j.state='done' ORDER BY j.created DESC''').fetchall()
    for j in rows:
        if json.loads(j['ref']) != want:
            continue
        path = DATA / 'artifacts' / j['id'] / 'manifest.json'
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != j['sha256']:
            raise service.Conflict('rendered artifact manifest changed on disk')
        return j['sha256']
    return None


def current_target(c, report_id: str, version: str) -> dict:
    """The review target for what is on disk now. Raises Conflict when any covered byte fails its check."""
    rep = _report_row(c, report_id, version)
    try:
        doc = json.loads(_report_bytes(rep))
    except ValueError:
        raise service.Unprocessable('report.json is not valid JSON') from None
    evidence = []
    for e in doc.get('evidence') or []:
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) for k in ('id', 'path', 'sha256')):
            raise service.Conflict('an evidence entry lacks an id, path or digest')
        evidence.append({'id': e['id'], 'path': e['path'], 'sha256': e['sha256']})
    evidence.sort(key=lambda e: (e['id'], e['path']))
    for e in evidence:
        _check_file(Path(rep['path']), e['path'], e['sha256'])
    run = c.execute('SELECT candidate_id, selection_id FROM investigations WHERE id=?', (rep['run_id'],)).fetchone()
    selection = c.execute('SELECT kind FROM selections WHERE id=?', (run['selection_id'],)).fetchone() if run else None
    case = _case_decision(c, rep['run_id'])
    return {
        'schema': TARGET_SCHEMA,
        'policyVersion': POLICY_VERSION,
        'reportId': report_id,
        'reportVersion': version,
        'reportSha256': rep['sha256'],
        'candidateId': run['candidate_id'] if run else doc.get('candidate_id'),
        'lineage': {'runId': rep['run_id'], 'selectionKind': selection['kind'] if selection else None,
                    'caseId': case['case_id'] if case else None, 'caseAction': case['action'] if case else None},
        'evidence': {'manifestSha256': digest(dumps(evidence).encode()), 'count': len(evidence)},
        'artifacts': {'renderManifestSha256': _render_manifest(c, report_id, version, rep['sha256'])},
    }


def target_digest(target: dict) -> str:
    return cn.sha256_hex(cn.canonical(target))


def _ensure_target(c, target: dict):
    td = target_digest(target)
    t = c.execute('SELECT * FROM rev_targets WHERE target_digest=?', (td,)).fetchone()
    if t:
        return t
    tid = ident()
    c.execute('INSERT INTO rev_targets(id,report_id,report_version,report_sha256,target_json,target_digest,created) VALUES(?,?,?,?,?,?,?)',
              (tid, target['reportId'], target['reportVersion'], target['reportSha256'], dumps(target), td, now()))
    _audit(c, tid, 'target_prepared', 'service', {'target_digest': td})
    return c.execute('SELECT * FROM rev_targets WHERE id=?', (tid,)).fetchone()


def _latest_receipt(c, target_id: str):
    return c.execute('''SELECT * FROM rev_receipts WHERE target_id=? AND revoked_at IS NULL
                        ORDER BY verified_at DESC, rowid DESC LIMIT 1''', (target_id,)).fetchone()


def _current(c, report_id: str, version: str):
    """(target record, digest, stored target row or None, latest unrevoked receipt or None)."""
    target = current_target(c, report_id, version)
    td = target_digest(target)
    t = c.execute('SELECT * FROM rev_targets WHERE target_digest=?', (td,)).fetchone()
    return target, td, t, (_latest_receipt(c, t['id']) if t else None)


def approved(c, report_id: str, version: str) -> bool:
    """True only while the exact current target carries an unrevoked World-confirmed approve receipt."""
    try:
        _, _, _, receipt = _current(c, report_id, version)
    except service.PubError:
        return False
    return bool(receipt and receipt['decision'] == 'approve')


def consumer_visible(c, report_id: str, version: str) -> bool:
    """Release policy for the consumer report library (SCOOBY_REPORT_RELEASE). 'all' lists every version
    with its review state; 'approved' lists only versions whose current target is approved."""
    from .config import ConfigError, admin_config
    # Seeded private drafts remain private even if a later process forgets the
    # approved-only deployment setting; an exact-version approval is required.
    if c.execute('SELECT 1 FROM seed_imports WHERE report_id=? AND version=?',(report_id,version)).fetchone():
        return approved(c, report_id, version)
    try:
        policy = admin_config().report_release
    except ConfigError:
        return False  # an invalid release policy hides reports rather than releasing them
    return policy == 'all' or approved(c, report_id, version)


def public_status(c, report_id: str, version: str) -> dict:
    """Consumer-safe review state: no reviewer identity, reason, attempt or proof material."""
    try:
        target, td, _, receipt = _current(c, report_id, version)
    except service.PubError:
        return {'schema': STATUS_SCHEMA, 'state': 'unavailable', 'method': None, 'decided_at': None,
                'target_digest': None, 'covers': None, 'detail': 'Report, evidence or rendered bytes failed an integrity check.'}
    return {'schema': STATUS_SCHEMA, 'state': DECISION_STATE[receipt['decision']] if receipt else 'pending_review',
            'method': 'world_id_admin_signoff' if receipt else None,
            'decided_at': int(receipt['verified_at']) if receipt else None, 'target_digest': td,
            'covers': {'report_sha256': target['reportSha256'],
                       'evidence_manifest_sha256': target['evidence']['manifestSha256'],
                       'render_manifest_sha256': target['artifacts']['renderManifestSha256']}}


# ---------------------------------------------------------------------------- admin read model
def _method(amr_json: str) -> str:
    # World documents ["pop","user","mfa"] as a user-verified passkey, which asserts no fresh World proof.
    return 'passkey' if 'mfa' in json.loads(amr_json) else 'world_proof'


def _pending_attempt(c, target_id: str):
    return c.execute("SELECT * FROM rev_attempts WHERE target_id=? AND status='pending' AND expires_at>? ORDER BY created DESC LIMIT 1",
                     (target_id, now())).fetchone()


def _queue_item(c, rep) -> dict:
    item = {'report_id': rep['id'], 'report_version': rep['version'], 'report_sha256': rep['sha256'],
            'created': int(rep['created']), 'target_digest': None, 'candidate_id': None, 'case_id': None,
            'state': 'unavailable', 'decision': None, 'decided_at': None, 'detail': None}
    try:
        target, td, t, receipt = _current(c, rep['id'], rep['version'])
    except service.PubError as e:
        item['detail'] = str(e)
        return item
    item.update(target_digest=td, candidate_id=target['candidateId'], case_id=target['lineage']['caseId'])
    if receipt:
        item.update(state=DECISION_STATE[receipt['decision']], decision=receipt['decision'], decided_at=int(receipt['verified_at']))
    elif t and _pending_attempt(c, t['id']):
        item['state'] = 'awaiting_confirmation'
    else:
        item['state'] = 'pending_review'
    return item


def queue(c) -> dict:
    """Every installed report version. Versions without a current decision come first, newest first."""
    rows = c.execute('SELECT id, version, sha256, created FROM reports ORDER BY created DESC').fetchall()
    items = [_queue_item(c, r) for r in rows]
    items.sort(key=lambda i: i['state'] not in ('pending_review', 'awaiting_confirmation', 'unavailable'))
    return {'schema': QUEUE_SCHEMA, 'generated_at': int(now()), 'items': items}


def detail(c, report_id: str, version: str, principal: admin.Principal) -> dict:
    """Full review context for an admin: exact target, recommendation, pillar TL;DRs, limitations, evidence, history."""
    rep = _report_row(c, report_id, version)
    out = {'schema': DETAIL_SCHEMA, 'report_id': report_id, 'report_version': version, 'report_sha256': rep['sha256'],
           'state': 'unavailable', 'target': None, 'target_digest': None, 'integrity': 'ok', 'summary': None,
           'decisions': [], 'pending_attempt': None,
           'links': {'artifacts': f'/web/v1/admin/reviews/{report_id}/{version}/artifacts',
                     'public_artifacts': f'/reports/{report_id}/{version}/artifacts'}}
    try:
        target, td, t, receipt = _current(c, report_id, version)
    except service.PubError as e:
        out['integrity'] = str(e)
        target, td, t, receipt = None, None, None, None
    if target:
        doc = json.loads(_report_bytes(rep))
        assessment = doc.get('assessment') or {}
        out.update(target=target, target_digest=td, summary={
            'identity': doc.get('identity'), 'mode': doc.get('mode'),
            'assessment': {k: assessment.get(k) for k in ('status', 'label', 'summary', 'unknowns')},
            'pillars': [{'pillar': name, 'status': (p or {}).get('status'), 'summary': (p or {}).get('summary'),
                         'quality_issues': (p or {}).get('quality_issues') or []}
                        for name, p in (doc.get('pillars') or {}).items()],
            'limitations': doc.get('limitations') or [],
            'evidence': [{k: e.get(k) for k in ('id', 'kind', 'coverage', 'path', 'sha256', 'limitations')}
                         for e in doc.get('evidence') or [] if isinstance(e, dict)],
            'report_review_snapshot': {**(doc.get('review') or {}), 'authentication_note': 'frozen report assertion, not a sign-off'},
        })
        pending = _pending_attempt(c, t['id']) if t else None
        out['state'] = DECISION_STATE[receipt['decision']] if receipt else 'awaiting_confirmation' if pending else 'pending_review'
        if pending and (pending['initiator_iss'], pending['initiator_sub']) == (principal.iss, principal.sub):
            out['pending_attempt'] = public_attempt(c, pending)
    for r in c.execute('''SELECT r.*, t.target_digest AS t_digest, p.label FROM rev_receipts r JOIN rev_targets t ON t.id=r.target_id
                          LEFT JOIN pub_reviewers p ON p.iss=r.reviewer_iss AND p.sub=r.reviewer_sub
                          WHERE t.report_id=? AND t.report_version=? ORDER BY r.verified_at DESC, r.rowid DESC''',
                       (report_id, version)).fetchall():
        out['decisions'].append({'receipt_id': r['id'], 'decision': r['decision'], 'reason': r['reason'],
                                 'decided_at': int(r['verified_at']), 'reviewer': r['label'], 'acr': r['acr'],
                                 'method': _method(r['amr_json']), 'target_digest': r['t_digest'],
                                 'current_target': r['t_digest'] == td, 'revoked_at': r['revoked_at'],
                                 'revoke_reason': r['revoke_reason']})
    return out


# ---------------------------------------------------------------------------- attempts
def public_attempt(c, a) -> dict:
    """Initiator-only view. The user code is shown while pending; tokens and device codes never are."""
    t = c.execute('SELECT * FROM rev_targets WHERE id=?', (a['target_id'],)).fetchone()
    binding = json.loads(a['binding_json'])
    out = {'schema': ATTEMPT_SCHEMA, 'id': a['id'], 'report_id': t['report_id'], 'report_version': t['report_version'],
           'target_digest': t['target_digest'], 'decision': a['decision'], 'reason': a['reason'], 'status': a['status'],
           'expires_at': a['expires_at'], 'binding_digest': a['binding_digest'],
           'binding': {k: binding[k] for k in ('audience', 'resource', 'scope', 'nonce', 'issuedAt', 'expiresAt')}}
    if a['status'] == 'pending':
        out.update(user_code=a['user_code'], verification_uri=a['verification_uri_complete'] or a['verification_uri'],
                   interval=a['interval'])
    if a['error']:
        out['detail'] = a['error']
    receipt = c.execute('SELECT id, decision, verified_at FROM rev_receipts WHERE attempt_id=?', (a['id'],)).fetchone()
    if receipt:
        out['receipt'] = {'id': receipt['id'], 'decision': receipt['decision'], 'decided_at': int(receipt['verified_at'])}
    return out


def _attempt(c, attempt_id: str):
    return c.execute('SELECT * FROM rev_attempts WHERE id=?', (attempt_id,)).fetchone()


def _own_attempt(c, attempt_id: str, principal: admin.Principal):
    a = _attempt(c, attempt_id)
    if not a or (a['initiator_iss'], a['initiator_sub']) != (principal.iss, principal.sub):
        raise service.NotFound('sign-off attempt not found')  # other admins cannot read its user code
    return a


def _finish(c, a, status: str, why: str | None, actor: str = 'service') -> dict:
    c.execute('UPDATE rev_attempts SET status=?, error=? WHERE id=? AND status=?', (status, why, a['id'], 'pending'))
    _audit(c, a['target_id'], f'attempt_{status}', actor, {'attempt_id': a['id'], 'why': why})
    service._forget(a['id'])
    return public_attempt(c, _attempt(c, a['id']))


def _expire_stale(c, target_id: str) -> None:
    for a in c.execute("SELECT * FROM rev_attempts WHERE target_id=? AND status='pending' AND expires_at<=?", (target_id, now())).fetchall():
        _finish(c, a, 'expired', 'confirmation window ended')


def create_attempt(report_id: str, version: str, *, decision: str, reason: str, expected_target_digest: str, idem: str,
                   principal: admin.Principal, world: WorldClient, cfg: AdminConfig) -> dict:
    """Bind one decision on the exact current target to this admin and start a fresh World confirmation."""
    if decision not in DECISION_STATE:
        raise service.Unprocessable('decision must be approve, reject or revise')
    rh = service.request_hash({'report_id': report_id, 'version': version, 'decision': decision, 'reason': reason,
                               'expected_target_digest': expected_target_digest,
                               'admin': admin.subject_hash(principal.iss, principal.sub)})
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT * FROM rev_attempts WHERE idem=?', (idem,)).fetchone()
        if old:
            if old['request_hash'] != rh:
                raise service.Conflict('Idempotency-Key reused with a different request')
            return public_attempt(c, old)
        target = current_target(c, report_id, version)
        td = target_digest(target)
        if expected_target_digest != td:
            raise service.Conflict('the review target changed since it was displayed; reload and confirm the current target')
        t = _ensure_target(c, target)
        _expire_stale(c, t['id'])
        if _latest_receipt(c, t['id']):
            raise service.Conflict('a decision is already recorded for this exact version; revoke it before recording another')
        if c.execute("SELECT 1 FROM rev_attempts WHERE target_id=? AND status='pending'", (t['id'],)).fetchone():
            raise service.Conflict('a sign-off confirmation is already pending for this version')
        target_id = t['id']
    started = now()
    try:
        dev = world.start_device(world.config.accepted_acr)
    except WorldError as e:
        raise service.Unavailable(f'World issuer unavailable: {e}') from None
    expires = int(min(started + dev.expires_in, started + cfg.attempt_ttl))
    binding = {'schema': BINDING_SCHEMA, 'targetDigest': td, 'decision': decision, 'reason': reason,
               'audience': cfg.audience, 'resource': f"report/{report_id}/{version}/{target['reportSha256']}",
               'scope': SCOPE, 'nonce': secrets.token_hex(32), 'issuedAt': int(started), 'expiresAt': expires,
               'initiator': admin.subject_hash(principal.iss, principal.sub)}
    bd = cn.sha256_hex(cn.canonical(binding))
    aid = ident()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT * FROM rev_attempts WHERE idem=?', (idem,)).fetchone()
        if old:  # a concurrent identical request won; this device grant is simply abandoned
            if old['request_hash'] != rh:
                raise service.Conflict('Idempotency-Key reused with a different request')
            return public_attempt(c, old)
        if _latest_receipt(c, target_id) or c.execute("SELECT 1 FROM rev_attempts WHERE target_id=? AND status='pending'", (target_id,)).fetchone():
            raise service.Conflict('a sign-off confirmation is already pending or recorded for this version')
        c.execute('''INSERT INTO rev_attempts(id,target_id,decision,reason,binding_json,binding_digest,initiator_iss,initiator_sub,
                     session_id,accepted_acr,device_code_hash,user_code,verification_uri,verification_uri_complete,interval,
                     next_poll_at,started_at,expires_at,status,idem,request_hash,created)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (aid, target_id, decision, reason, dumps(binding), bd, principal.iss, principal.sub, principal.session_id,
                   json.dumps(list(world.config.accepted_acr)), digest(dev.device_code.encode()), dev.user_code,
                   dev.verification_uri, dev.verification_uri_complete, dev.interval, started + dev.interval, started,
                   expires, 'pending', idem, rh, now()))
        _audit(c, target_id, 'attempt_started', principal.label, {'attempt_id': aid, 'decision': decision, 'binding_digest': bd})
        service._remember(aid, dev.device_code)
        return public_attempt(c, _attempt(c, aid))


def poll_attempt(attempt_id: str, principal: admin.Principal, world: WorldClient | None, cfg: AdminConfig) -> dict:
    """Poll-on-read for the initiating admin; World is polled at most once per interval."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        a = _own_attempt(c, attempt_id, principal)
        if a['status'] != 'pending':
            return public_attempt(c, a)
        if a['expires_at'] <= now():
            return _finish(c, a, 'expired', 'confirmation window ended')
        device_code = service._device_code(attempt_id)
        if device_code is None:
            return _finish(c, a, 'expired', 'device code lost (service restarted)')
        if world is None or now() < a['next_poll_at']:
            return public_attempt(c, a)
        c.execute('UPDATE rev_attempts SET next_poll_at=? WHERE id=?', (now() + a['interval'], attempt_id))
        interval = a['interval']
    try:
        result = world.poll(device_code)
    except WorldError as e:
        result = Error(str(e), terminal=False)
    if isinstance(result, Tokens):
        return _confirm(attempt_id, result.id_token, world, cfg)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        a = _attempt(c, attempt_id)
        if a['status'] != 'pending':
            _audit(c, a['target_id'], 'late_world_result_ignored', 'service', {'attempt_id': attempt_id, 'status': a['status']})
            return public_attempt(c, a)
        if isinstance(result, SlowDown):
            interval += 5
            c.execute('UPDATE rev_attempts SET interval=?, next_poll_at=? WHERE id=?', (interval, now() + interval, attempt_id))
        elif isinstance(result, Denied):
            return _finish(c, a, 'denied', 'Denied in World App. No decision was recorded.', 'world')
        elif isinstance(result, Expired):
            return _finish(c, a, 'expired', 'The World code expired. No decision was recorded.', 'world')
        elif isinstance(result, Error):
            if result.terminal:
                return _finish(c, a, 'failed', f'issuer error: {result.code}', 'world')
            c.execute('UPDATE rev_attempts SET next_poll_at=? WHERE id=?', (now() + min(60, interval * 2), attempt_id))
        return public_attempt(c, _attempt(c, attempt_id))


def _confirm(attempt_id: str, id_token: str, world: WorldClient, cfg: AdminConfig) -> dict:
    with db() as c:
        a = _attempt(c, attempt_id)
    service._forget(attempt_id)
    try:
        identity = world.validate_id_token(id_token, started_at=a['started_at'], accepted_acr=tuple(json.loads(a['accepted_acr'])))
        problem = None
    except TokenInvalid as e:
        identity, problem = None, f'id_token rejected: {e}'
    except WorldError as e:
        identity, problem = None, f'verifier unavailable: {e}'
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        a = _attempt(c, attempt_id)
        if a['status'] != 'pending':
            _audit(c, a['target_id'], 'late_world_result_ignored', 'service', {'attempt_id': attempt_id, 'status': a['status']})
            return public_attempt(c, a)
        if problem:
            return _finish(c, a, 'failed', problem)
        if a['expires_at'] <= now():
            return _finish(c, a, 'expired', 'confirmation window ended')
        if (identity.iss, identity.sub) != (a['initiator_iss'], a['initiator_sub']):
            _audit(c, a['target_id'], 'confirmer_mismatch', 'world', {'attempt_id': attempt_id,
                                                                      'subject_sha256': admin.subject_hash(identity.iss, identity.sub)})
            return _finish(c, a, 'not_permitted', 'Confirmed with a different World ID than the admin who requested it.')
        if not admin.permitted(c, identity.iss, identity.sub, SCOPE) or not admin.session_active(c, a['session_id'], identity.iss, identity.sub):
            return _finish(c, a, 'not_permitted', 'Admin permission or session changed before confirmation.')
        binding = json.loads(a['binding_json'])
        if binding['audience'] != cfg.audience:
            return _finish(c, a, 'superseded', 'The service audience changed; start a new confirmation.')
        t = c.execute('SELECT * FROM rev_targets WHERE id=?', (a['target_id'],)).fetchone()
        try:
            now_digest = target_digest(current_target(c, t['report_id'], t['report_version']))
        except service.PubError as e:
            return _finish(c, a, 'superseded', f'The report changed: {e}')
        if now_digest != t['target_digest'] or binding['targetDigest'] != t['target_digest']:
            return _finish(c, a, 'superseded', 'Report, evidence or rendered artifacts changed; review the new target.')
        if _latest_receipt(c, t['id']):
            return _finish(c, a, 'superseded', 'Another decision was recorded for this target first.')
        token_sha = digest(id_token.encode())
        if c.execute('SELECT 1 FROM rev_receipts WHERE id_token_sha256=?', (token_sha,)).fetchone():
            return _finish(c, a, 'failed', 'This World token was already used.')
        rid = ident()
        c.execute('''INSERT INTO rev_receipts(id,attempt_id,target_id,target_digest,binding_digest,decision,reason,reviewer_iss,
                     reviewer_sub,acr,amr_json,auth_time,id_token_sha256,verified_at,verifier_version)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (rid, attempt_id, t['id'], t['target_digest'], a['binding_digest'], a['decision'], a['reason'], identity.iss,
                   identity.sub, identity.acr, json.dumps(list(identity.amr)), identity.auth_time, token_sha, now(), VERIFIER_VERSION))
        c.execute("UPDATE rev_attempts SET status='confirmed' WHERE id=?", (attempt_id,))
        label = c.execute('SELECT label FROM pub_reviewers WHERE iss=? AND sub=?', (identity.iss, identity.sub)).fetchone()['label']
        _audit(c, t['id'], 'receipt_recorded', label, {'attempt_id': attempt_id, 'receipt_id': rid, 'decision': a['decision'],
                                                       'acr': identity.acr, 'method': _method(json.dumps(list(identity.amr)))})
        return public_attempt(c, _attempt(c, attempt_id))


def cancel_attempt(attempt_id: str, principal: admin.Principal) -> dict:
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        a = _own_attempt(c, attempt_id, principal)
        if a['status'] == 'pending':
            return _finish(c, a, 'cancelled', 'Cancelled by the admin. No decision was recorded.', principal.label)
        return public_attempt(c, a)


def revoke(report_id: str, version: str, principal: admin.Principal, reason: str) -> dict:
    """Withdraw every recorded decision for this version. The receipts stay; the version returns to pending review."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        _report_row(c, report_id, version)
        rows = c.execute('''SELECT r.id, r.target_id FROM rev_receipts r JOIN rev_targets t ON t.id=r.target_id
                            WHERE t.report_id=? AND t.report_version=? AND r.revoked_at IS NULL''', (report_id, version)).fetchall()
        if not rows:
            raise service.Conflict('no recorded decision to revoke for this version')
        for r in rows:
            c.execute('UPDATE rev_receipts SET revoked_at=?, revoke_reason=? WHERE id=? AND revoked_at IS NULL', (now(), reason, r['id']))
            _audit(c, r['target_id'], 'receipt_revoked', principal.label, {'receipt_id': r['id']})
        return {'report_id': report_id, 'report_version': version, 'revoked': len(rows),
                'state': public_status(c, report_id, version)['state']}
