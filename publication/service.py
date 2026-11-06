"""Publication state machine. Every function is fail-closed.

Nothing here publishes from a GET, a poll or a successful World proof. Publication needs an
explicit request_publication call that consumes a fresh, unrevoked, allowlisted approve
receipt for the exact target, and queues an outbox row for the separate fenced publisher.
"""
from __future__ import annotations
import json
import logging
import threading
from pathlib import Path
from typing import Callable

from store import db, digest, dumps, ident, now
from . import canonical as cn
from . import chain
from .config import ChainConfig, Settings
from .db import audit
from .world import Denied, Error, Expired, Pending, SlowDown, TokenInvalid, Tokens, VERIFIER_VERSION, WorldClient, WorldError

log = logging.getLogger('publication.service')
APPROVAL_VALIDITY = 15 * 60
ACTIVE_OUTBOX = ('queued', 'signing', 'submitted', 'reconcile', 'confirmed')


class PubError(Exception):
    status = 400


class NotFound(PubError):
    status = 404


class Conflict(PubError):
    status = 409


class Unprocessable(PubError):
    status = 422


class Unavailable(PubError):
    status = 503


# Device codes live only in process memory, keyed by attempt id. A restart loses them and the
# attempt then expires. Only sha256(device_code) is persisted.
_device_codes: dict[str, str] = {}
_device_lock = threading.Lock()


def _remember(attempt_id: str, device_code: str) -> None:
    with _device_lock:
        _device_codes[attempt_id] = device_code


def _device_code(attempt_id: str) -> str | None:
    with _device_lock:
        return _device_codes.get(attempt_id)


def _forget(attempt_id: str) -> None:
    with _device_lock:
        _device_codes.pop(attempt_id, None)


def request_hash(payload: dict) -> str:
    return digest(dumps(payload).encode('utf-8'))


def _idem_get(c, scope: str, key: str, rh: str):
    old = c.execute('SELECT * FROM pub_idem WHERE scope=? AND idem=?', (scope, key)).fetchone()
    if not old:
        return None
    if old['request_hash'] != rh:
        raise Conflict('Idempotency-Key reused with a different request')
    return json.loads(old['result_json'])


def _idem_put(c, scope: str, key: str, rh: str, result: dict) -> None:
    c.execute('INSERT INTO pub_idem(scope,idem,request_hash,result_json,created) VALUES(?,?,?,?,?)',
              (scope, key, rh, dumps(result), now()))


# ---------------------------------------------------------------------------- targets
def _report_bytes(rep) -> bytes:
    p = Path(rep['path']) / 'report.json'
    try:
        return p.read_bytes()
    except OSError:
        raise Conflict('report bytes are missing on disk') from None


def _check_target_integrity(c, t) -> dict:
    """The stored target, its manifest and the report bytes on disk must still hash to what was approved."""
    rep = c.execute('SELECT * FROM reports WHERE id=? AND version=?', (t['report_id'], t['report_version'])).fetchone()
    if not rep:
        raise Conflict('report version no longer exists')
    raw = _report_bytes(rep)
    if digest(raw) != rep['sha256'] or rep['sha256'] != t['report_sha256']:
        raise Conflict('report bytes changed since the target was prepared; a fresh target and review are required')
    target = json.loads(t['target_json'])
    if cn.target_digest(target) != t['target_digest']:
        raise Conflict('target record does not match its digest')
    manifest = json.loads(t['claim_manifest_json'])
    if cn.claim_hash(manifest, target['claimHashAlg']) != t['claim_hash'] or target['claimHash'] != t['claim_hash']:
        raise Conflict('claim manifest does not match its hash')
    return target


def _require_report_approval(c, report_id: str, version: str) -> None:
    """Release policy: publication follows a current World-confirmed admin approval of the exact report
    version (checkpoint 2, publication/review.py). That approval is a precondition only; publication still
    needs its own chain-bound sign-off and an explicit publish request."""
    from . import review
    from .config import ConfigError, admin_config
    try:
        required = admin_config().publication_requires_review
    except ConfigError as e:
        raise Unavailable(str(e)) from None
    if required and not review.approved(c, report_id, version):
        raise Conflict('this report version has no current World-confirmed admin approval (checkpoint 2); '
                       'approve it in the admin review queue before publication')


def public_target(t) -> dict:
    target = json.loads(t['target_json'])
    return {'id': t['id'], 'report_id': t['report_id'], 'report_version': t['report_version'],
            'report_sha256': t['report_sha256'], 'claim_hash': t['claim_hash'], 'target_digest': t['target_digest'],
            'claim_manifest': json.loads(t['claim_manifest_json']), 'target': target, 'created': t['created']}


def prepare_target(report_id: str, version: str, params: dict, *, idem: str, actor: str,
                   settings: Settings, chain_cfg: ChainConfig) -> dict:
    rh = request_hash({'report_id': report_id, 'version': version, 'params': params})
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        prior = _idem_get(c, 'target', idem, rh)
        if prior:
            return prior
        rep = c.execute('SELECT * FROM reports WHERE id=? AND version=?', (report_id, version)).fetchone()
        if not rep:
            raise NotFound('report version not found')
        raw = _report_bytes(rep)
        if digest(raw) != rep['sha256']:
            raise Conflict('report bytes on disk do not match the imported digest')
        try:
            report = json.loads(raw)
        except ValueError:
            raise Unprocessable('report.json is not valid JSON') from None
        _require_report_approval(c, report_id, version)
        if not chain_cfg.registry:
            raise Unavailable('SCOOBY_REPORT_REGISTRY is not configured')
        p = dict(params)
        p.setdefault('resolver', chain_cfg.resolver)
        p.setdefault('adjudicator', chain_cfg.adjudicator)
        excluded = p.pop('excluded_wallets', []) or []
        if not isinstance(excluded, list) or not all(isinstance(w, str) for w in excluded):
            raise Unprocessable('excluded_wallets must be a list of addresses')
        try:
            lock_time = p.get('lock_time')
            manifest = cn.build_claim_manifest(report, rep['sha256'], int(rep['created']),
                                               lock_time if isinstance(lock_time, int) else 0, excluded)
            ch = cn.claim_hash(manifest, settings.claim_hash_alg)
            target = cn.build_target(report_id=report_id, report_version=version, report_sha256=rep['sha256'],
                                     claim_hash_hex=ch, claim_hash_alg=settings.claim_hash_alg,
                                     chain_id=chain_cfg.chain_id, registry=chain_cfg.registry, params=p,
                                     now=now(), lock_margin=settings.lock_margin)
        except cn.TargetError as e:
            raise Unprocessable(str(e)) from None
        td = cn.target_digest(target)
        existing = c.execute('SELECT * FROM pub_targets WHERE report_id=? AND report_version=? AND target_digest=?',
                             (report_id, version, td)).fetchone()
        if existing:
            result = public_target(existing)
        else:
            tid = ident()
            c.execute('''INSERT INTO pub_targets(id,report_id,report_version,report_sha256,claim_manifest_json,claim_hash,
                         chain_id,registry,resolver,adjudicator,lock_time,cross_chain_cutoff,result_deadline,challenge_period,
                         target_json,target_digest,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (tid, report_id, version, rep['sha256'], dumps(manifest), ch, target['chainId'], target['registry'],
                       target['resolver'], target['adjudicator'], target['lockTime'], target['crossChainCutoff'],
                       target['resultDeadline'], target['challengePeriod'], dumps(target), td, now()))
            audit(c, tid, 'target_prepared', actor, {'target_digest': td, 'claim_hash': ch})
            result = public_target(c.execute('SELECT * FROM pub_targets WHERE id=?', (tid,)).fetchone())
        _idem_put(c, 'target', idem, rh, result)
        return result


def get_target(target_id: str) -> dict:
    with db() as c:
        t = c.execute('SELECT * FROM pub_targets WHERE id=?', (target_id,)).fetchone()
        if not t:
            raise NotFound('target not found')
        out = public_target(t)
        out['status'] = _status(c, t)
        return out


# ---------------------------------------------------------------------------- attempts
def public_attempt(a) -> dict:
    return {k: a[k] for k in ('id', 'target_id', 'decision_intent', 'status', 'user_code', 'verification_uri',
                              'verification_uri_complete', 'interval', 'started_at', 'expires_at', 'error')}


def _expire_stale(c, target_id: str | None = None, attempt_id: str | None = None) -> None:
    t = now()
    if attempt_id:
        rows = c.execute("SELECT id FROM pub_attempts WHERE id=? AND status='pending' AND expires_at<=?", (attempt_id, t)).fetchall()
    else:
        rows = c.execute("SELECT id FROM pub_attempts WHERE target_id=? AND status='pending' AND expires_at<=?", (target_id, t)).fetchall()
    for r in rows:
        c.execute("UPDATE pub_attempts SET status='expired' WHERE id=? AND status='pending'", (r['id'],))
        _forget(r['id'])


def create_attempt(target_id: str, decision: str, reason: str, *, idem: str, actor: str, world: WorldClient,
                   initiator: tuple[str, str] | None = None) -> dict:
    """initiator: (iss, sub) of the admin session that asked for this sign-off. When set, only that
    admin, still holding the publication scope, can complete it. Operator-started attempts pass None."""
    if decision not in ('approve', 'reject', 'revise'):
        raise Unprocessable('decision must be approve, reject or revise')
    rh = request_hash({'target_id': target_id, 'decision': decision, 'reason': reason})
    with db() as c:
        old = c.execute('SELECT * FROM pub_attempts WHERE idem=?', (idem,)).fetchone()
        if old:
            if old['request_hash'] != rh:
                raise Conflict('Idempotency-Key reused with a different request')
            return public_attempt(old)
        t = c.execute('SELECT * FROM pub_targets WHERE id=?', (target_id,)).fetchone()
        if not t:
            raise NotFound('target not found')
        _check_target_integrity(c, t)
        _expire_stale(c, target_id=target_id)
        if c.execute("SELECT 1 FROM pub_attempts WHERE target_id=? AND status='pending'", (target_id,)).fetchone():
            raise Conflict('a sign-off attempt is already pending for this target')
    started_at = now()
    accepted = world.config.accepted_acr
    try:
        dev = world.start_device(accepted)
    except WorldError as e:
        raise Unavailable(f'World issuer unavailable: {e}') from None
    aid = ident()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM pub_attempts WHERE target_id=? AND status='pending'", (target_id,)).fetchone():
            raise Conflict('a sign-off attempt is already pending for this target')
        c.execute('''INSERT INTO pub_attempts(id,target_id,decision_intent,reason,policy_version,accepted_acr,device_code_hash,
                     user_code,verification_uri,verification_uri_complete,interval,next_poll_at,started_at,expires_at,status,
                     idem,request_hash,created,initiator_iss,initiator_sub) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (aid, target_id, decision, reason, cn.POLICY_VERSION, json.dumps(list(accepted)),
                   digest(dev.device_code.encode()), dev.user_code, dev.verification_uri, dev.verification_uri_complete,
                   dev.interval, started_at + dev.interval, started_at, started_at + dev.expires_in, 'pending',
                   idem, rh, now(), *(initiator or (None, None))))
        audit(c, target_id, 'attempt_started', actor, {'attempt_id': aid, 'decision_intent': decision})
        _remember(aid, dev.device_code)
        return public_attempt(c.execute('SELECT * FROM pub_attempts WHERE id=?', (aid,)).fetchone())


def get_attempt(attempt_id: str) -> dict:
    with db() as c:
        a = c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone()
        if not a:
            raise NotFound('attempt not found')
        return public_attempt(a)


def poll_attempt(attempt_id: str, world: WorldClient | None) -> dict:
    """Poll-on-read. Cheap and safe to call repeatedly; World is polled at most once per interval."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        a = c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone()
        if not a:
            raise NotFound('attempt not found')
        if a['status'] != 'pending':
            return public_attempt(a)
        _expire_stale(c, attempt_id=attempt_id)
        a = c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone()
        if a['status'] != 'pending' or now() < a['next_poll_at']:
            return public_attempt(a)
        device_code = _device_code(attempt_id)
        if device_code is None:
            c.execute("UPDATE pub_attempts SET status='expired', error=? WHERE id=?", ('device code lost (service restarted)', attempt_id))
            audit(c, a['target_id'], 'attempt_expired', 'service', {'attempt_id': attempt_id, 'why': 'device code lost'})
            return public_attempt(c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone())
        if world is None:
            return public_attempt(a)
        # Claim this poll slot so concurrent readers don't poll World twice.
        c.execute('UPDATE pub_attempts SET next_poll_at=? WHERE id=?', (now() + a['interval'], attempt_id))
        interval = a['interval']
    try:
        result = world.poll(device_code)
    except WorldError as e:
        result = Error(str(e), terminal=False)
    if isinstance(result, Tokens):
        return _finish_tokens(attempt_id, result.id_token, world)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        a = c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone()
        if a['status'] != 'pending':
            audit(c, a['target_id'], 'late_world_result_ignored', 'service', {'attempt_id': attempt_id, 'status': a['status']})
            return public_attempt(a)
        if isinstance(result, Pending):
            pass
        elif isinstance(result, SlowDown):
            interval += 5
            c.execute('UPDATE pub_attempts SET interval=?, next_poll_at=? WHERE id=?', (interval, now() + interval, attempt_id))
        elif isinstance(result, Denied):
            c.execute("UPDATE pub_attempts SET status='denied' WHERE id=?", (attempt_id,))
            audit(c, a['target_id'], 'attempt_denied', 'world', {'attempt_id': attempt_id})
            _forget(attempt_id)
        elif isinstance(result, Expired):
            c.execute("UPDATE pub_attempts SET status='expired' WHERE id=?", (attempt_id,))
            audit(c, a['target_id'], 'attempt_expired', 'world', {'attempt_id': attempt_id})
            _forget(attempt_id)
        elif isinstance(result, Error):
            if result.terminal:
                c.execute("UPDATE pub_attempts SET status='error', error=? WHERE id=?", (f'issuer error: {result.code}', attempt_id))
                audit(c, a['target_id'], 'attempt_error', 'world', {'attempt_id': attempt_id, 'code': result.code})
                _forget(attempt_id)
            else:
                backoff = min(60, interval * 2)
                c.execute('UPDATE pub_attempts SET next_poll_at=? WHERE id=?', (now() + backoff, attempt_id))
                log.warning('world poll transient failure (%s); backing off', result.code)
        return public_attempt(c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone())


def _finish_tokens(attempt_id: str, id_token: str, world: WorldClient) -> dict:
    with db() as c:
        a = c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone()
    accepted = tuple(json.loads(a['accepted_acr']))
    try:
        ident_ = world.validate_id_token(id_token, started_at=a['started_at'], accepted_acr=accepted)
        problem = None
    except TokenInvalid as e:
        ident_, problem = None, str(e)
    except WorldError as e:
        ident_, problem = None, f'verifier unavailable: {e}'
    _forget(attempt_id)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        a = c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone()
        if a['status'] != 'pending':
            audit(c, a['target_id'], 'late_world_result_ignored', 'service', {'attempt_id': attempt_id, 'status': a['status']})
            return public_attempt(a)
        if problem:
            c.execute("UPDATE pub_attempts SET status='error', error=? WHERE id=?", (f'id_token rejected: {problem}', attempt_id))
            audit(c, a['target_id'], 'id_token_rejected', 'service', {'attempt_id': attempt_id, 'why': problem})
            return public_attempt(c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone())
        reviewer = c.execute('SELECT * FROM pub_reviewers WHERE iss=? AND sub=? AND enabled=1', (ident_.iss, ident_.sub)).fetchone()
        if not reviewer:
            c.execute("UPDATE pub_attempts SET status='rejected_not_reviewer' WHERE id=?", (attempt_id,))
            audit(c, a['target_id'], 'rejected_not_reviewer', 'world', {'attempt_id': attempt_id, 'sub_sha256': digest(ident_.sub.encode())})
            return public_attempt(c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone())
        if a['initiator_iss'] is not None:
            from .admin import permitted
            if (ident_.iss, ident_.sub) != (a['initiator_iss'], a['initiator_sub']) or not permitted(c, ident_.iss, ident_.sub, 'publication'):
                c.execute("UPDATE pub_attempts SET status='rejected_not_reviewer', error=? WHERE id=?",
                          ('confirmed by a different World ID than the requesting admin, or the admin lost the publication scope', attempt_id))
                audit(c, a['target_id'], 'rejected_not_initiator', 'world', {'attempt_id': attempt_id, 'sub_sha256': digest(ident_.sub.encode())})
                return public_attempt(c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone())
        t = c.execute('SELECT target_digest FROM pub_targets WHERE id=?', (a['target_id'],)).fetchone()
        rid = ident()
        c.execute('''INSERT INTO pub_receipts(id,attempt_id,target_id,target_digest,decision,reason,reviewer_iss,reviewer_sub,acr,
                     amr_json,auth_time,verified_at,verifier_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (rid, attempt_id, a['target_id'], t['target_digest'], a['decision_intent'], a['reason'], ident_.iss,
                   ident_.sub, ident_.acr, json.dumps(list(ident_.amr)), ident_.auth_time, now(), VERIFIER_VERSION))
        c.execute("UPDATE pub_attempts SET status='approved' WHERE id=?", (attempt_id,))
        audit(c, a['target_id'], 'receipt_recorded', reviewer['label'], {'attempt_id': attempt_id, 'receipt_id': rid,
                                                                          'decision': a['decision_intent'], 'acr': ident_.acr})
        return public_attempt(c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone())


def cancel_attempt(attempt_id: str, actor: str) -> dict:
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        a = c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone()
        if not a:
            raise NotFound('attempt not found')
        if a['status'] == 'pending':
            c.execute("UPDATE pub_attempts SET status='cancelled' WHERE id=?", (attempt_id,))
            audit(c, a['target_id'], 'attempt_cancelled', actor, {'attempt_id': attempt_id})
            _forget(attempt_id)
        return public_attempt(c.execute('SELECT * FROM pub_attempts WHERE id=?', (attempt_id,)).fetchone())


# ---------------------------------------------------------------------------- publication
PublishGate = Callable[[], None]  # raises Unavailable when publishing must not happen


def make_gate(chain_cfg: ChainConfig, preflight: Callable[[], None] | None = None) -> PublishGate:
    def gate() -> None:
        if not chain_cfg.enabled:
            raise Unavailable('publishing is disabled (SCOOBY_PUBLISH_ENABLED is not true)')
        if not (chain_cfg.registry and chain_cfg.attestor_key and chain_cfg.publisher_key):
            raise Unavailable('publishing keys or registry are not configured')
        if chain.address_of(chain_cfg.attestor_key).lower() == chain.address_of(chain_cfg.publisher_key).lower():
            raise Unavailable('attestor and publisher keys must differ')
        if preflight is None:
            raise Unavailable('publisher preflight has not run')
        try:
            preflight()
        except chain.ChainError as e:
            raise Unavailable(f'publisher preflight failed: {e}') from None
    return gate


def request_publication(target_id: str, *, idem: str, actor: str, gate: PublishGate, settings: Settings,
                        chain_cfg: ChainConfig) -> dict:
    gate()
    rh = request_hash({'target_id': target_id})
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        prior = _idem_get(c, 'publish', idem, rh)
        if prior:
            return prior
        t = c.execute('SELECT * FROM pub_targets WHERE id=?', (target_id,)).fetchone()
        if not t:
            raise NotFound('target not found')
        target = _check_target_integrity(c, t)
        _require_report_approval(c, t['report_id'], t['report_version'])
        if target['chainId'] != chain_cfg.chain_id or target['registry'].lower() != (chain_cfg.registry or '').lower():
            raise Conflict('target chain/registry differs from the configured publisher')
        latest = c.execute('SELECT * FROM pub_receipts WHERE target_id=? ORDER BY verified_at DESC, rowid DESC LIMIT 1',
                           (target_id,)).fetchone()
        if not latest:
            raise Conflict('no authenticated review receipt for this target')
        if latest['decision'] != 'approve':
            raise Conflict(f"latest review decision is {latest['decision']}; it cannot publish")
        if latest['revoked_at'] is not None:
            raise Conflict('approval was revoked')
        if latest['consumed_at'] is not None:
            raise Conflict('approval already used; a fresh approval is required')
        if latest['target_digest'] != t['target_digest']:
            raise Conflict('approval is for a different target digest')
        if now() - latest['verified_at'] > settings.approval_ttl:
            raise Conflict('approval is older than SCOOBY_APPROVAL_TTL; a fresh approval is required')
        reviewer = c.execute('SELECT enabled FROM pub_reviewers WHERE iss=? AND sub=?',
                             (latest['reviewer_iss'], latest['reviewer_sub'])).fetchone()
        if not reviewer or not reviewer['enabled']:
            raise Conflict('reviewer is no longer enabled')
        active = c.execute(f"SELECT state FROM pub_outbox WHERE target_id=? AND state IN ({','.join('?' * len(ACTIVE_OUTBOX))})",
                           (target_id, *ACTIVE_OUTBOX)).fetchone()
        if active:
            raise Conflict(f"publication already {active['state']} for this target")
        c.execute('UPDATE pub_receipts SET consumed_at=? WHERE id=? AND consumed_at IS NULL', (now(), latest['id']))
        attestor = chain.address_of(chain_cfg.attestor_key)
        nonce = chain.new_nonce()
        expiry = int(now()) + APPROVAL_VALIDITY
        report = chain.report_tuple(target, attestor)
        sig = chain.sign_approval(chain_cfg.attestor_key, target['chainId'], target['registry'], report, nonce, expiry)
        oid = ident()
        c.execute('''INSERT INTO pub_outbox(id,target_id,receipt_id,reviewer_addr,nonce,approval_expiry,signature,state,fence,
                     idem,request_hash,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (oid, target_id, latest['id'], attestor, str(nonce), expiry, sig, 'queued', 0, idem, rh, now()))
        audit(c, target_id, 'publication_requested', actor, {'outbox_id': oid, 'receipt_id': latest['id']})
        result = {'outbox_id': oid, 'state': 'queued', 'reviewer': attestor, 'nonce': str(nonce), 'approval_expiry': expiry}
        _idem_put(c, 'publish', idem, rh, result)
        return result


def revoke(target_id: str, actor: str, reason: str) -> dict:
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        t = c.execute('SELECT * FROM pub_targets WHERE id=?', (target_id,)).fetchone()
        if not t:
            raise NotFound('target not found')
        c.execute('UPDATE pub_receipts SET revoked_at=? WHERE target_id=? AND revoked_at IS NULL', (now(), target_id))
        # 'signing' is always pre-broadcast (the publisher flips to 'submitted' before sending).
        stopped = c.execute("""UPDATE pub_outbox SET state='failed', error='revoked'
                               WHERE target_id=? AND (state IN ('queued','signing') OR (state='reconcile' AND tx_hash IS NULL))""",
                            (target_id,)).rowcount
        confirmed = c.execute("SELECT 1 FROM pub_outbox WHERE target_id=? AND state='confirmed'", (target_id,)).fetchone()
        in_flight = c.execute("SELECT 1 FROM pub_outbox WHERE target_id=? AND tx_hash IS NOT NULL AND state NOT IN ('confirmed','failed')", (target_id,)).fetchone()
        phase = 'after_confirmation' if confirmed else ('after_broadcast' if in_flight else 'before_publication')
        audit(c, target_id, 'revoked', actor, {'reason': reason, 'phase': phase, 'outbox_stopped': stopped})
        return {'target_id': target_id, 'revoked': True, 'phase': phase,
                'note': 'Onchain publication cannot be undone; status now shows revoked.' if phase != 'before_publication' else 'Publication stopped before broadcast.'}


def _status(c, t) -> dict:
    tid = t['id']
    revoked = c.execute("SELECT detail_json, created FROM pub_events WHERE target_id=? AND kind='revoked' ORDER BY seq DESC LIMIT 1", (tid,)).fetchone()
    outbox = c.execute('SELECT * FROM pub_outbox WHERE target_id=? ORDER BY created DESC LIMIT 1', (tid,)).fetchone()
    receipt = c.execute('SELECT * FROM pub_receipts WHERE target_id=? ORDER BY verified_at DESC, rowid DESC LIMIT 1', (tid,)).fetchone()
    attempt = c.execute('SELECT * FROM pub_attempts WHERE target_id=? ORDER BY created DESC LIMIT 1', (tid,)).fetchone()
    if revoked:
        state = 'revoked'
    elif outbox and outbox['state'] == 'confirmed':
        state = 'published'
    elif outbox and outbox['state'] in ('queued', 'signing', 'submitted', 'reconcile'):
        state = 'publishing'
    elif receipt and receipt['decision'] == 'approve' and receipt['consumed_at'] is None and receipt['revoked_at'] is None:
        state = 'approved'
    elif receipt and receipt['decision'] in ('reject', 'revise') and (not attempt or attempt['status'] != 'pending'):
        state = 'rejected' if receipt['decision'] == 'reject' else 'revision_requested'
    elif attempt:
        state = {'pending': 'awaiting_approval'}.get(attempt['status'], attempt['status'])
    else:
        state = 'draft'
    return {
        'state': state,
        'published_onchain': bool(outbox and outbox['state'] == 'confirmed'),
        'revoked': bool(revoked),
        'latest_attempt': public_attempt(attempt) if attempt else None,
        'latest_receipt': {k: receipt[k] for k in ('id', 'decision', 'acr', 'verified_at', 'consumed_at', 'revoked_at')} if receipt else None,
        'outbox': {k: outbox[k] for k in ('id', 'state', 'tx_hash', 'onchain_report_id', 'error')} if outbox else None,
    }


def target_status(target_id: str) -> dict:
    with db() as c:
        t = c.execute('SELECT * FROM pub_targets WHERE id=?', (target_id,)).fetchone()
        if not t:
            raise NotFound('target not found')
        return _status(c, t)

