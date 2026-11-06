"""Admin World ID checkpoints (docs/scouting-qualification/WORLD-AGENT-BUILD-CHARTER.md).

Sessions, checkpoint-2 report sign-off, the checkpoint-1 hook and route guard for the case bridge,
cross-action separation, consumer separation and secret handling. No network: World is
tests/fake_world.py and renders are recorded the way worker.py records them. Identities are synthetic,
so these tests prove the integration, not a live World verification.
"""
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault('SCOOBY_DATA', tempfile.mkdtemp(prefix='scooby-admin-test-'))
os.environ.setdefault('SCOOBY_FRONTEND_DIR', str(Path(__file__).resolve().parent.parent / 'vendor' / 'reader'))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app import app
from store import db, dumps, now as real_now
from publication import admin, deps, review, service
from publication.config import chain_config, world_config
from publication.world import Identity
from fake_world import CLIENT_ID, ISSUER, ORB, Clock, FakeWorld, new_rsa, pem
from admin_support import enroll, login

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(__file__).parent / 'historical-bundle'
SCHEMA = json.loads((ROOT / 'schemas' / 'runtime' / 'admin-checkpoints-v1.schema.json').read_text(encoding='utf-8'))
OP = {'Authorization': 'Bearer op-token'}
ADMIN_SUB = 'pairwise-sub-admin-1'
OTHER_SUB = 'pairwise-sub-admin-2'
CHAIN_ENV = {
    'SCOOBY_PUBLISH_ENABLED': 'true', 'SCOOBY_CHAIN_ID': '11155111',
    'SCOOBY_REPORT_REGISTRY': '0xfb2c164ddb3676d03e1e443f3f2934b8d0df88e5',
    'SCOOBY_RESOLVER': '0x70997970C51812dc3A010C7d01b50e0d17dc79C8',
    'SCOOBY_ADJUDICATOR': '0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC',
    'SCOOBY_PUBLISHER_KEY': '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80',
    'SCOOBY_ATTESTOR_KEY': '0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d',
    'SCOOBY_RPC_URL': 'http://127.0.0.1:1', 'SCOOBY_DEMO_AUTOPUBLISH': 'false',
}
client = TestClient(app)


@pytest.fixture
def env(monkeypatch, tmp_path):
    import store
    from publication import db as publication_db
    monkeypatch.setattr(store, 'DB', tmp_path / 'state.sqlite3')
    store.init()
    publication_db.init()
    clock = Clock(real_now())
    for module in (service, admin, review):
        monkeypatch.setattr(module, 'now', clock)
    key = new_rsa()
    key_path = tmp_path / 'world_client_key.pem'
    key_path.write_bytes(pem(key))
    for k, v in {'WORLD_ISSUER': ISSUER, 'WORLD_CLIENT_ID': CLIENT_ID, 'WORLD_CLIENT_KEY_PATH': str(key_path),
                 'WORLD_ASSERTION_AUD': 'endpoint', 'SCOOBY_OPERATOR_TOKEN': 'op-token', **CHAIN_ENV}.items():
        monkeypatch.setenv(k, v)
    for k in ('SCOOBY_ADMIN_AUDIENCE', 'SCOOBY_REPORT_RELEASE', 'SCOOBY_PUBLICATION_REQUIRES_REVIEW',
              'SCOOBY_ADMIN_MAX_PENDING_LOGINS', 'SCOOBY_ADMIN_SESSION_TTL', 'SCOOBY_ADMIN_ATTEMPT_TTL', 'WORLD_ACCEPTED_ACR'):
        monkeypatch.delenv(k, raising=False)
    fw = FakeWorld(clock, key)
    fw.default_sub = ADMIN_SUB
    world = admin.AdminWorldClient(world_config(), transport=fw.transport(), clock=clock)
    app.dependency_overrides[deps.get_world] = lambda: world
    app.dependency_overrides[deps.get_world_optional] = lambda: world
    app.dependency_overrides[deps.get_gate] = lambda: service.make_gate(chain_config(), preflight=lambda: None)
    enroll(ISSUER, ADMIN_SUB, 'report_review', label='admin-1')
    service._device_codes.clear()
    yield SimpleNamespace(clock=clock, fw=fw, world=world, tmp=tmp_path)
    app.dependency_overrides.clear()
    service._device_codes.clear()


# ------------------------------------------------------------------ helpers
def valid(definition: str, value: dict) -> dict:
    errors = [e.message for e in Draft202012Validator({'$ref': f'#/$defs/{definition}', '$defs': SCHEMA['$defs']}).iter_errors(value)]
    assert not errors, errors
    return value


def make_report(ns, version: str = 'v1', rid: str | None = None):
    """An installed immutable report version, registered the way /reports/import does."""
    rid = rid or f'admin-review-{uuid.uuid4().hex[:8]}'
    bundle = ns.tmp / f'bundle-{rid}-{version}'
    shutil.copytree(BUNDLE, bundle)
    rep = json.loads((bundle / 'report.json').read_text(encoding='utf-8'))
    rep['report_id'], rep['report_version'] = rid, version
    raw = json.dumps(rep, indent=2, ensure_ascii=False).encode('utf-8')
    (bundle / 'report.json').write_bytes(raw)
    cand, sel, run = (uuid.uuid4().hex for _ in range(3))
    with db() as c:
        c.execute('INSERT INTO candidates VALUES(?,?,?)', (cand, '{}', real_now()))
        c.execute('INSERT INTO selections VALUES(?,?,?,?,?,?,?)', (sel, cand, 'diagnostic_exception', 'test', 'test', real_now(), sel))
        c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?)', (run, cand, sel, 'partial', real_now(), run))
        c.execute('INSERT INTO reports VALUES(?,?,?,?,?,?)', (rid, version, run, hashlib.sha256(raw).hexdigest(), str(bundle), real_now()))
    return rid, version, bundle


def record_render(rid: str, version: str) -> None:
    """A completed render as worker.py records it: done job, locked manifest hash, manifest bytes on disk."""
    with db() as c:
        sha = c.execute('SELECT sha256 FROM reports WHERE id=? AND version=?', (rid, version)).fetchone()[0]
    job = uuid.uuid4().hex
    manifest = json.dumps({'report_id': rid, 'report_version': version, 'report_sha256': sha}).encode()
    out = review.DATA / 'artifacts' / job
    out.mkdir(parents=True)
    (out / 'manifest.json').write_bytes(manifest)
    with db() as c:
        c.execute('INSERT INTO jobs(id,kind,ref,state,available,idem,created) VALUES(?,?,?,?,?,?,?)',
                  (job, 'render', dumps({'id': rid, 'version': version, 'sha256': sha}), 'done', 0, 'render:' + job, real_now()))
        c.execute('INSERT INTO render_manifests VALUES(?,?)', (job, hashlib.sha256(manifest).hexdigest()))


def detail(h, rid, ver) -> dict:
    r = client.get(f'/web/v1/admin/reviews/{rid}/{ver}', headers=h)
    assert r.status_code == 200, r.text
    return valid('reviewDetail', r.json())


def decide(ns, h, rid, ver, decision='approve', *steps, key=None, digest=None, reason='checked the evidence'):
    if steps:
        ns.fw.script(*steps)
    target = digest or detail(h, rid, ver)['target_digest']
    return client.post(f'/web/v1/admin/reviews/{rid}/{ver}/attempts',
                       json={'decision': decision, 'reason': reason, 'expected_target_digest': target},
                       headers={**h, 'Idempotency-Key': key or uuid.uuid4().hex})


def poll(ns, h, attempt_id, limit=10) -> dict:
    a = None
    for _ in range(limit):
        ns.clock.advance(6)
        a = client.get(f'/web/v1/admin/review-attempts/{attempt_id}', headers=h).json()
        if a['status'] != 'pending':
            break
    return valid('reviewAttempt', a)


def approve(ns, h, rid, ver, decision='approve') -> dict:
    r = decide(ns, h, rid, ver, decision, ('success', {}))
    assert r.status_code == 200, r.text
    out = poll(ns, h, r.json()['id'])
    assert out['status'] == 'confirmed', out
    return out


def consumer_item(rid, ver):
    return next((x for x in client.get('/reports').json() if (x['report_id'], x['report_version']) == (rid, ver)), None)


def status(rid, ver) -> dict:
    return valid('reviewStatus', consumer_item(rid, ver)['admin_review'])


def counts() -> dict:
    with db() as c:
        return {t: c.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
                for t in ('candidates', 'selections', 'investigations', 'jobs', 'pub_targets', 'pub_attempts', 'pub_receipts', 'pub_outbox')}


def timing(ns) -> dict:
    t = int(ns.clock())
    return {'lock_time': t + 7200, 'cross_chain_cutoff': t + 3600, 'result_deadline': t + 7200 + 31 * 86400, 'challenge_period': 86400}


# ------------------------------------------------------------------ admin sessions
def test_admin_session_needs_an_enrolled_reviewer_with_a_scope(env):
    assert client.get('/web/v1/admin/reviews').status_code == 401
    assert client.get('/web/v1/admin/reviews', headers={'Authorization': 'Bearer sas_forged-token-value-000000'}).status_code == 401
    started = valid('session', client.post('/web/v1/admin/session').json())
    h = {'Authorization': 'Bearer ' + started['session_token']}
    assert started['state'] == 'pending' and started['user_code']
    assert client.get('/web/v1/admin/reviews', headers=h).status_code == 401          # pending is not signed in
    env.clock.advance(started['interval'])
    active = valid('session', client.get('/web/v1/admin/session', headers=h).json())
    assert active['state'] == 'active' and active['label'] == 'admin-1' and active['scopes'] == ['report_review']
    assert 'user_code' not in active and 'session_token' not in active
    assert client.get('/web/v1/admin/reviews', headers=h).status_code == 200
    # A World-verified stranger and an enrolled reviewer without any scope never get a session.
    enroll(ISSUER, 'pairwise-sub-no-scope', label='no-scope')
    for sub in ('pairwise-sub-stranger', 'pairwise-sub-no-scope'):
        other = login(client, env.fw, env.clock, sub=sub, expect='not_permitted')
        assert client.get('/web/v1/admin/reviews', headers=other).status_code == 401
    assert client.delete('/web/v1/admin/session', headers=h).json()['state'] == 'revoked'
    assert client.get('/web/v1/admin/reviews', headers=h).status_code == 401


@pytest.mark.parametrize('step,state', [
    ('denied', 'denied'), ('expired', 'expired'), ('http500', 'failed'), ('invalid_grant', 'failed'),
    (('success', {'aud': 'another-client'}), 'failed'),
    (('success', {'act': {'sub': 'agent-1'}}), 'failed'),          # a delegate cannot sign in as the human
])
def test_admin_login_failures_never_activate(env, step, state):
    env.fw.script(step)
    s = client.post('/web/v1/admin/session').json()
    h = {'Authorization': 'Bearer ' + s['session_token']}
    env.clock.advance(s['interval'])
    assert valid('session', client.get('/web/v1/admin/session', headers=h).json())['state'] == state
    assert client.get('/web/v1/admin/reviews', headers=h).status_code == 401


def test_session_restart_cap_permission_changes_and_expiry(env, monkeypatch):
    s = client.post('/web/v1/admin/session').json()
    h = {'Authorization': 'Bearer ' + s['session_token']}
    service._device_codes.clear()                                       # API restart loses the device code
    env.clock.advance(6)
    assert client.get('/web/v1/admin/session', headers=h).json()['state'] == 'expired'
    monkeypatch.setenv('SCOOBY_ADMIN_MAX_PENDING_LOGINS', '2')
    assert [client.post('/web/v1/admin/session').status_code for _ in range(3)] == [200, 200, 429]
    monkeypatch.delenv('SCOOBY_ADMIN_MAX_PENDING_LOGINS')
    h = login(client, env.fw, env.clock)
    with db() as c:
        c.execute('UPDATE pub_reviewers SET enabled=0 WHERE sub=?', (ADMIN_SUB,))
    assert client.get('/web/v1/admin/reviews', headers=h).status_code == 401
    with db() as c:
        c.execute('UPDATE pub_reviewers SET enabled=1 WHERE sub=?', (ADMIN_SUB,))
        admin.revoke_scope(c, ISSUER, ADMIN_SUB, 'report_review', 'test')
    assert client.get('/web/v1/admin/reviews', headers=h).status_code == 403
    with db() as c:
        admin.grant(c, ISSUER, ADMIN_SUB, 'report_review', 'test')
    assert client.get('/web/v1/admin/reviews', headers=h).status_code == 200
    env.clock.advance(4 * 3600 + 1)
    assert client.get('/web/v1/admin/reviews', headers=h).status_code == 401
    assert client.get('/web/v1/admin/session', headers=h).json()['state'] == 'expired'


# ------------------------------------------------------------------ checkpoint 2: report sign-off
def test_report_signoff_records_one_world_confirmed_decision_and_nothing_else(env):
    rid, ver, _ = make_report(env)
    h = login(client, env.fw, env.clock)
    queue = valid('reviewQueue', client.get('/web/v1/admin/reviews', headers=h).json())
    item = next(i for i in queue['items'] if i['report_id'] == rid)
    assert item['state'] == 'pending_review' and item['case_id'] is None     # imported: no case lineage invented
    d = detail(h, rid, ver)
    assert d['target']['reportSha256'] == d['report_sha256'] and d['target']['lineage']['caseId'] is None
    assert d['target']['evidence']['count'] == 6 and d['target']['artifacts']['renderManifestSha256'] is None
    assert d['summary']['pillars'] and d['summary']['limitations'] and d['summary']['evidence']
    assert status(rid, ver)['state'] == 'pending_review'
    before = counts()
    key = uuid.uuid4().hex
    started = decide(env, h, rid, ver, 'approve', 'pending', ('success', {}), key=key)
    assert started.status_code == 200, started.text
    a = valid('reviewAttempt', started.json())
    assert a['status'] == 'pending' and a['user_code'] and a['binding']['scope'] == 'report_review'
    assert a['binding']['resource'] == f"report/{rid}/{ver}/{d['report_sha256']}" and a['binding']['audience'] == 'scooby-admin'
    devices = len(env.fw.issued_device_codes)
    again = decide(env, h, rid, ver, 'approve', key=key, digest=d['target_digest'])
    assert again.json()['id'] == a['id'] and len(env.fw.issued_device_codes) == devices   # identical retry, no second grant
    assert decide(env, h, rid, ver, 'reject', key=key, digest=d['target_digest']).status_code == 409
    assert decide(env, h, rid, ver, 'reject').status_code == 409                         # one pending per version
    assert detail(h, rid, ver)['state'] == 'awaiting_confirmation'
    done = poll(env, h, a['id'])
    assert done['status'] == 'confirmed' and done['receipt']['decision'] == 'approve'
    s = status(rid, ver)
    assert s['state'] == 'approved' and s['method'] == 'world_id_admin_signoff' and s['target_digest'] == d['target_digest']
    decided = detail(h, rid, ver)['decisions']
    assert [(x['decision'], x['reviewer'], x['method'], x['current_target']) for x in decided] == [('approve', 'admin-1', 'world_proof', True)]
    assert decide(env, h, rid, ver, 'reject').status_code == 409                         # decided: revoke first
    assert counts() == before        # no research, publication target, sign-off, outbox or job was created


@pytest.mark.parametrize('steps,expected', [
    (('denied',), 'denied'),
    (('expired',), 'expired'),
    (('invalid_grant',), 'failed'),
    ((('success', {'aud': 'another-client'}),), 'failed'),
    ((('success', {'acr': 'https://world.org/oidc/acr/selfie'}),), 'failed'),
    ((('success', {'act': {'sub': 'agent-1'}}),), 'failed'),
    ((('success', {'sub': OTHER_SUB}),), 'not_permitted'),    # another enabled reviewer cannot finish this admin's code
])
def test_unsuccessful_confirmations_record_no_decision(env, steps, expected):
    rid, ver, _ = make_report(env)
    enroll(ISSUER, OTHER_SUB, 'report_review', label='admin-2')
    h = login(client, env.fw, env.clock)
    a = decide(env, h, rid, ver, 'approve', *steps).json()
    assert poll(env, h, a['id'])['status'] == expected
    assert status(rid, ver)['state'] == 'pending_review'
    with db() as c:
        assert c.execute('SELECT count(*) FROM rev_receipts').fetchone()[0] == 0


def test_cancel_restart_window_and_session_change_record_no_decision(env, monkeypatch):
    rid, ver, _ = make_report(env)
    enroll(ISSUER, OTHER_SUB, 'report_review', label='admin-2')
    h = login(client, env.fw, env.clock)
    a = decide(env, h, rid, ver, 'approve', 'pending', ('success', {})).json()
    other = login(client, env.fw, env.clock, sub=OTHER_SUB)
    assert client.get(f"/web/v1/admin/review-attempts/{a['id']}", headers=other).status_code == 404   # not theirs to see
    assert client.post(f"/web/v1/admin/review-attempts/{a['id']}/cancel", headers=h).json()['status'] == 'cancelled'
    assert poll(env, h, a['id'])['status'] == 'cancelled'                       # a late World success is ignored
    a = decide(env, h, rid, ver, 'approve', 'pending', ('success', {})).json()
    service._device_codes.clear()                                                # API restart
    assert poll(env, h, a['id'])['status'] == 'expired'
    monkeypatch.setenv('SCOOBY_ADMIN_ATTEMPT_TTL', '60')
    a = decide(env, h, rid, ver, 'approve', 'pending', ('success', {})).json()
    env.clock.advance(61)
    assert client.get(f"/web/v1/admin/review-attempts/{a['id']}", headers=h).json()['status'] == 'expired'
    monkeypatch.delenv('SCOOBY_ADMIN_ATTEMPT_TTL')
    a = decide(env, h, rid, ver, 'approve', 'pending', ('success', {})).json()
    client.delete('/web/v1/admin/session', headers=h)                            # signed out mid-confirmation
    h = login(client, env.fw, env.clock)
    assert poll(env, h, a['id'])['status'] == 'not_permitted'
    a = decide(env, h, rid, ver, 'approve', 'pending', ('success', {})).json()
    monkeypatch.setenv('SCOOBY_ADMIN_AUDIENCE', 'another-deployment')
    assert poll(env, h, a['id'])['status'] == 'superseded'
    monkeypatch.delenv('SCOOBY_ADMIN_AUDIENCE')
    devices = len(env.fw.issued_device_codes)
    assert decide(env, h, rid, ver, 'approve', digest='0' * 64).status_code == 409    # stale target, World not contacted
    assert len(env.fw.issued_device_codes) == devices
    assert status(rid, ver)['state'] == 'pending_review'
    with db() as c:
        assert c.execute('SELECT count(*) FROM rev_receipts').fetchone()[0] == 0


def test_changed_bytes_supersede_and_old_approvals_never_carry_over(env):
    rid, ver, bundle = make_report(env)
    h = login(client, env.fw, env.clock)
    a = decide(env, h, rid, ver, 'approve', 'pending', ('success', {})).json()
    evidence = bundle / 'evidence' / 'ma_shib.json'
    original = evidence.read_bytes()
    evidence.write_bytes(original + b' ')
    assert poll(env, h, a['id'])['status'] == 'superseded'
    assert status(rid, ver)['state'] == 'unavailable'
    assert next(i for i in client.get('/web/v1/admin/reviews', headers=h).json()['items'] if i['report_id'] == rid)['state'] == 'unavailable'
    evidence.write_bytes(original)
    approve(env, h, rid, ver)
    assert status(rid, ver)['state'] == 'approved'
    record_render(rid, ver)                       # rendered artifacts after approval: not covered by it
    s = status(rid, ver)
    assert s['state'] == 'pending_review' and s['covers']['render_manifest_sha256']
    assert detail(h, rid, ver)['decisions'][0]['current_target'] is False
    make_report(env, version='v2', rid=rid)       # a revision is a new immutable version and target
    assert status(rid, 'v2')['state'] == 'pending_review'
    raw = (bundle / 'report.json').read_bytes()
    (bundle / 'report.json').write_bytes(raw + b'\n')
    assert any(x.get('integrity')=='unavailable' for x in client.get('/reports').json())  # isolate corrupt item without exposing bytes
    queue = client.get('/web/v1/admin/reviews', headers=h).json()['items']
    assert next(i for i in queue if (i['report_id'], i['report_version']) == (rid, ver))['state'] == 'unavailable'
    assert decide(env, h, rid, ver, 'approve', digest='a' * 64).status_code == 409


def test_revoke_reject_and_revise_keep_an_append_only_history(env):
    rid, ver, _ = make_report(env)
    h = login(client, env.fw, env.clock)
    assert client.post(f'/web/v1/admin/reviews/{rid}/{ver}/revoke', json={'reason': 'x'}, headers=h).status_code == 409
    approve(env, h, rid, ver)
    r = client.post(f'/web/v1/admin/reviews/{rid}/{ver}/revoke', json={'reason': 'second look'}, headers=h).json()
    assert r == {'report_id': rid, 'report_version': ver, 'revoked': 1, 'state': 'pending_review'}
    first = detail(h, rid, ver)['decisions'][0]
    assert first['revoked_at'] and first['revoke_reason'] == 'second look'
    approve(env, h, rid, ver, 'reject')
    assert status(rid, ver)['state'] == 'rejected'
    client.post(f'/web/v1/admin/reviews/{rid}/{ver}/revoke', json={'reason': 'needs changes instead'}, headers=h)
    approve(env, h, rid, ver, 'revise')
    assert status(rid, ver)['state'] == 'revision_requested'
    assert [x['decision'] for x in detail(h, rid, ver)['decisions']] == ['revise', 'reject', 'approve']
    with db() as c:
        with pytest.raises(sqlite3.DatabaseError):
            c.execute("UPDATE rev_receipts SET decision='approve'")
        with pytest.raises(sqlite3.DatabaseError):
            c.execute('DELETE FROM rev_receipts')
        with pytest.raises(sqlite3.DatabaseError):
            c.execute("UPDATE rev_receipts SET revoked_at=NULL WHERE revoked_at IS NOT NULL")


# ------------------------------------------------------------------ consumers and other actions
def test_consumers_see_only_released_reports_and_a_safe_status(env, monkeypatch):
    rid, ver, _ = make_report(env)
    h = login(client, env.fw, env.clock)
    item = consumer_item(rid, ver)
    assert item['admin_review']['state'] == 'pending_review' and item['review']['authentication'] == 'unverified local operator'
    monkeypatch.setenv('SCOOBY_REPORT_RELEASE', 'approved')
    assert consumer_item(rid, ver) is None
    assert client.get(f'/reports/{rid}/{ver}/artifacts').status_code == 404
    approve(env, h, rid, ver)
    assert status(rid, ver)['state'] == 'approved'
    assert client.get(f'/reports/{rid}/{ver}/artifacts').json()['admin_review']['state'] == 'approved'
    body = client.get('/reports').text + client.get(f'/reports/{rid}/{ver}/artifacts').text
    for private in ('admin-1', ADMIN_SUB, 'checked the evidence', 'user_code', 'binding'):
        assert private not in body
    monkeypatch.setenv('SCOOBY_REPORT_RELEASE', 'everything')          # invalid policy hides rather than releases
    assert consumer_item(rid, ver) is None


def test_checkpoints_cannot_stand_in_for_each_other(env, monkeypatch):
    rid, ver, _ = make_report(env)
    with db() as c:
        sha = c.execute('SELECT sha256 FROM reports WHERE id=?', (rid,)).fetchone()[0]
    local = client.post(f'/reports/{rid}/{ver}/review', json={'decision': 'approve', 'actor': 'local operator', 'reason': 'x', 'sha256': sha},
                        headers={'Idempotency-Key': uuid.uuid4().hex})
    assert local.status_code == 200 and status(rid, ver)['state'] == 'pending_review'   # unauthenticated record never counts
    monkeypatch.setenv('SCOOBY_PUBLICATION_REQUIRES_REVIEW', 'false')
    t = client.post('/publication/v1/targets', json={'report_id': rid, 'version': ver, 'params': timing(env)},
                    headers={**OP, 'Idempotency-Key': uuid.uuid4().hex}).json()
    pa = client.post(f"/publication/v1/targets/{t['id']}/attempts", json={'decision': 'approve', 'reason': 'publish'},
                     headers={**OP, 'Idempotency-Key': uuid.uuid4().hex}).json()
    env.clock.advance(6)
    assert client.get(f"/publication/v1/attempts/{pa['id']}", headers=OP).json()['status'] == 'approved'
    assert status(rid, ver)['state'] == 'pending_review'              # a publication sign-off is not a report sign-off
    enroll(ISSUER, OTHER_SUB, 'case_investigation', label='case-admin')
    case_h = login(client, env.fw, env.clock, sub=OTHER_SUB)
    assert client.get('/web/v1/admin/reviews', headers=case_h).status_code == 403
    h = login(client, env.fw, env.clock)
    assert client.post(f'/web/v1/reports/{rid}@{ver}/approve', headers=h).status_code == 403   # needs the publication scope
    assert client.post('/scouting/challenges/c1/world-attempt', headers=h).status_code == 403  # needs case_investigation
    before = counts()
    approve(env, h, rid, ver)
    assert counts() == before                                           # report approval starts no research and publishes nothing


def test_publication_needs_a_current_report_approval_and_its_own_signoff(env):
    rid, ver, _ = make_report(env)
    body = {'report_id': rid, 'version': ver, 'params': timing(env)}
    r = client.post('/publication/v1/targets', json=body, headers={**OP, 'Idempotency-Key': uuid.uuid4().hex})
    assert r.status_code == 409 and 'checkpoint 2' in r.json()['detail']
    h = login(client, env.fw, env.clock)
    approve(env, h, rid, ver)
    t = client.post('/publication/v1/targets', json=body, headers={**OP, 'Idempotency-Key': uuid.uuid4().hex}).json()
    publish = lambda: client.post(f"/publication/v1/targets/{t['id']}/publish", headers={**OP, 'Idempotency-Key': uuid.uuid4().hex})
    r = publish()
    assert r.status_code == 409 and 'no authenticated review receipt' in r.json()['detail']   # report approval is not publication
    pa = client.post(f"/publication/v1/targets/{t['id']}/attempts", json={'decision': 'approve', 'reason': 'publish'},
                     headers={**OP, 'Idempotency-Key': uuid.uuid4().hex}).json()
    env.clock.advance(6)
    assert client.get(f"/publication/v1/attempts/{pa['id']}", headers=OP).json()['status'] == 'approved'
    client.post(f'/web/v1/admin/reviews/{rid}/{ver}/revoke', json={'reason': 'doubt'}, headers=h)
    r = publish()
    assert r.status_code == 409 and 'checkpoint 2' in r.json()['detail']
    with db() as c:
        assert c.execute('SELECT count(*) FROM pub_outbox').fetchone()[0] == 0


def test_web_publication_signoff_is_bound_to_the_requesting_admin(env, monkeypatch):
    monkeypatch.setenv('SCOOBY_PUBLICATION_REQUIRES_REVIEW', 'false')
    enroll(ISSUER, ADMIN_SUB, 'report_review', 'publication', label='admin-1')
    enroll(ISSUER, OTHER_SUB, 'publication', label='admin-2')
    rid, ver, _ = make_report(env)
    client.post('/publication/v1/targets', json={'report_id': rid, 'version': ver, 'params': timing(env)},
                headers={**OP, 'Idempotency-Key': uuid.uuid4().hex})
    h1 = login(client, env.fw, env.clock)
    h2 = login(client, env.fw, env.clock, sub=OTHER_SUB)
    assert client.post(f'/web/v1/reports/{rid}@{ver}/approve').status_code == 401
    env.fw.script(('success', {'sub': OTHER_SUB}))                     # someone else completes admin-1's code
    a = client.post(f'/web/v1/reports/{rid}@{ver}/approve', headers=h1).json()
    assert client.get(f"/web/v1/approvals/{a['id']}", headers=h2).status_code == 404
    assert client.post(f'/web/v1/reports/{rid}@{ver}/approve', headers=h2).status_code == 409
    env.clock.advance(6)
    assert client.get(f"/web/v1/approvals/{a['id']}", headers=h1).json()['status'] == 'rejected_not_reviewer'
    with db() as c:
        assert c.execute('SELECT count(*) FROM pub_receipts').fetchone()[0] == 0


def test_private_reads_need_credentials(env):
    rid, ver, _ = make_report(env)
    for path in ('/web/v1/admin/reviews', f'/web/v1/admin/reviews/{rid}/{ver}', '/web/v1/admin/review-attempts/x',
                 '/publication/v1/attempts/x', '/publication/v1/targets/x', '/web/v1/approvals/x'):
        assert client.get(path).status_code == 401, path
    assert client.get('/web/v1/admin/session').status_code == 401
    assert client.post(f'/web/v1/admin/reviews/{rid}/{ver}/revoke', json={'reason': 'x'}).status_code == 401
    assert client.post(f'/web/v1/admin/reviews/{rid}/{ver}/attempts', json={}).status_code == 401   # auth before validation


def test_admin_cors_allows_the_bearer_header_for_the_web_origin_only(env):
    pre = {'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST',
           'Access-Control-Request-Headers': 'authorization,content-type,idempotency-key'}
    ok = client.options('/web/v1/admin/reviews/r/v/attempts', headers=pre)
    assert ok.status_code == 200 and ok.headers['access-control-allow-origin'] == 'http://localhost:5173'
    assert client.options('/web/v1/reports/r@v/approve', headers=pre).status_code == 200
    assert client.options('/web/v1/admin/session', headers={**pre, 'Origin': 'http://untrusted.invalid'}).status_code == 400
    assert client.options('/web/v1/reports', headers=pre).status_code == 400    # plain web adapter keeps its narrow policy


# ------------------------------------------------------------------ checkpoint 1: case bridge hook and guard
def test_case_checkpoint_routes_need_a_case_admin_session(env):
    guarded = FastAPI()
    for method, path in (('post', '/scouting/cases/{x}/challenge'), ('get', '/scouting/challenges/{x}'),
                         ('post', '/scouting/challenges/{x}/world-attempt'), ('post', '/scouting/challenges/{x}/deny'),
                         ('get', '/scouting/world-attempts/{x}'), ('post', '/scouting/world-attempts/{x}/cancel'),
                         ('post', '/investigations/{x}/resume'), ('get', '/scouting/cases')):
        getattr(guarded, method)(path)(lambda x='': {'reached': True})
    guarded.add_middleware(admin.AdminRouteGuard)
    gc = TestClient(guarded)
    enroll(ISSUER, OTHER_SUB, 'case_investigation', label='case-admin')
    review_h = login(client, env.fw, env.clock)
    case_h = login(client, env.fw, env.clock, sub=OTHER_SUB)
    for method, path in (('post', '/scouting/cases/c1/challenge'), ('get', '/scouting/challenges/ch1'),
                         ('post', '/scouting/challenges/ch1/world-attempt'), ('post', '/scouting/challenges/ch1/deny'),
                         ('get', '/scouting/world-attempts/a1'), ('post', '/scouting/world-attempts/a1/cancel'),
                         ('post', '/investigations/r1/resume'), ('post', '/scouting/cases/c1/challenge/')):
        call = getattr(gc, method)
        assert call(path).status_code == 401, path
        assert call(path, headers=review_h).status_code == 403, path
        assert call(path, headers=case_h).status_code in (200, 307), path
    assert gc.get('/scouting/cases').json() == {'reached': True}         # the case list read model stays public
    assert client.post('/scouting/challenges/ch1/world-attempt').status_code == 401   # same policy on this API


def test_case_authorizer_hook_for_the_case_bridge(env, monkeypatch):
    enroll(ISSUER, OTHER_SUB, 'case_investigation', label='case-admin')
    who = Identity(iss=ISSUER, sub=OTHER_SUB, acr=ORB, amr=('pop',), auth_time=int(env.clock()))
    binding = {'case_id': 'case-1', 'candidate_id': 'cand-1', 'snapshot_digest': 'a' * 64, 'policy_digest': 'b' * 64,
               'action': 'diagnostic_research'}
    world = env.world
    assert callable(getattr(world, 'authorize_case_admin', None))          # what the case bridge checks
    assert world.authorize_case_admin(who, binding) is False               # not signed in to the admin app
    h = login(client, env.fw, env.clock, sub=OTHER_SUB)
    assert world.authorize_case_admin(who, binding) is True
    import store
    holder = sqlite3.connect(store.DB, timeout=1)
    holder.execute('BEGIN IMMEDIATE')                                      # the bridge holds a write transaction
    try:
        assert world.authorize_case_admin(who, binding) is True
    finally:
        holder.rollback()
        holder.close()
    assert world.authorize_case_admin(who, {**binding, 'action': 'publish'}) is False
    assert world.authorize_case_admin(who, 'not-a-binding') is False
    login(client, env.fw, env.clock)
    reviewer = Identity(iss=ISSUER, sub=ADMIN_SUB, acr=ORB, amr=('pop',), auth_time=int(env.clock()))
    assert world.authorize_case_admin(reviewer, binding) is False          # report_review does not cover cases
    with db() as c:
        c.execute('UPDATE pub_reviewers SET enabled=0 WHERE sub=?', (OTHER_SUB,))
    assert world.authorize_case_admin(who, binding) is False
    with db() as c:
        c.execute('UPDATE pub_reviewers SET enabled=1 WHERE sub=?', (OTHER_SUB,))
    client.delete('/web/v1/admin/session', headers=h)
    assert world.authorize_case_admin(who, binding) is False               # signed out
    login(client, env.fw, env.clock, sub=OTHER_SUB)
    monkeypatch.setattr(admin, 'permitted', lambda *a: (_ for _ in ()).throw(RuntimeError('database unavailable')))
    assert world.authorize_case_admin(who, binding) is False               # an authorizer error never approves


def test_api_world_client_carries_the_case_hook(env, monkeypatch):
    app.dependency_overrides.pop(deps.get_world, None)
    monkeypatch.setattr(deps, '_world', None)
    try:
        assert isinstance(deps.get_world(), admin.AdminWorldClient)
    finally:
        monkeypatch.setattr(deps, '_world', None)


# ------------------------------------------------------------------ secrets
def test_no_tokens_codes_or_subjects_leak(env, caplog):
    caplog.set_level(logging.DEBUG)
    rid, ver, _ = make_report(env)
    started = client.post('/web/v1/admin/session').json()
    token = started['session_token']
    h = {'Authorization': 'Bearer ' + token}
    env.clock.advance(started['interval'])
    client.get('/web/v1/admin/session', headers=h)
    attempt = approve(env, h, rid, ver)
    db_bytes = b''.join(p.read_bytes() for p in env.tmp.glob('state.sqlite3*'))
    for secret in env.fw.issued_device_codes + env.fw.issued_id_tokens + [token]:
        assert secret not in caplog.text and secret.encode() not in db_bytes
    admin_body = json.dumps(attempt) + json.dumps(detail(h, rid, ver))
    for secret in env.fw.issued_device_codes + env.fw.issued_id_tokens + [ADMIN_SUB]:
        assert secret not in admin_body
    consumer = client.get('/reports').text + client.get(f'/reports/{rid}/{ver}/artifacts').text
    for private in [ADMIN_SUB, 'admin-1', token] + env.fw.issued_device_codes:
        assert private not in consumer

def test_open_review_upgrade_quarantines_auto_authority_and_approval(env,monkeypatch):
    monkeypatch.setenv('SCOOBY_REPORT_RELEASE','approved')
    rid,ver,_=make_report(env)
    h=login(client,env.fw,env.clock)
    with db() as c:
        c.execute("UPDATE admin_scopes SET granted_by='open-review',created=? WHERE iss=? AND sub=? AND scope='report_review'",(env.clock()-10,ISSUER,ADMIN_SUB))
    approve(env,h,rid,ver)
    assert consumer_item(rid,ver) is not None
    admin.retire_open_review_grants()
    assert consumer_item(rid,ver) is None
    assert client.get('/web/v1/admin/reviews',headers=h).status_code in (401,403)
    with db() as c:
        receipt=c.execute('SELECT revoked_at,revoke_reason FROM rev_receipts').fetchone()
        assert receipt['revoked_at'] is not None and 'named-admin' in receipt['revoke_reason']
        assert c.execute("SELECT count(*) FROM rev_events WHERE kind='open_review_receipt_quarantined'").fetchone()[0]==1
        admin.grant(c,ISSUER,ADMIN_SUB,'report_review','explicit-admin')
    admin.retire_open_review_grants()
    assert client.get('/web/v1/admin/reviews',headers=h).status_code==200
    assert consumer_item(rid,ver) is None  # regrant does not resurrect the old approval


def test_open_review_history_survives_explicit_grant_overwrite(env,monkeypatch):
    monkeypatch.setenv('SCOOBY_REPORT_RELEASE','approved')
    rid,ver,_=make_report(env)
    with db() as c:admin.grant(c,ISSUER,ADMIN_SUB,'report_review','open-review')
    h=login(client,env.fw,env.clock);approve(env,h,rid,ver)
    env.clock.advance(10)
    with db() as c:admin.grant(c,ISSUER,ADMIN_SUB,'report_review','named-admin')
    from publication import db as publication_db
    publication_db.init();publication_db.init()  # CLI/publisher initialization, no web import
    assert client.get('/web/v1/admin/reviews',headers=h).status_code==200
    assert consumer_item(rid,ver) is None
    with db() as c:
        assert c.execute('SELECT revoked_at FROM rev_receipts').fetchone()[0] is not None
        assert c.execute("SELECT count(*) FROM rev_events WHERE kind='open_review_receipt_quarantined'").fetchone()[0]==1
