"""Publication boundary + World ID Agent Pass tests. No network: World is tests/fake_world.py,
the chain is a fake sender (anvil tests live in test_publication_anvil.py)."""
import hashlib
import json
import logging
import os
import secrets
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

os.environ.setdefault('SCOOBY_DATA', tempfile.mkdtemp(prefix='scooby-pub-test-'))
os.environ.setdefault('SCOOBY_FRONTEND_DIR', str(Path(__file__).resolve().parent.parent / 'vendor' / 'reader'))

from fastapi.testclient import TestClient

from app import app
from store import DATA, db, now as real_now
from publication import chain, deps, publisher, service
from publication.config import chain_config, world_config
from publication.world import WorldClient, ASSERTION_TYPE
from fake_world import CLIENT_ID, ISSUER, Clock, FakeWorld, new_rsa, pem

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(__file__).parent / 'historical-bundle'
PUBLISHER_KEY = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'  # anvil #0
ATTESTOR_KEY = '0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d'   # anvil #1
REGISTRY = '0x805d681383f580403b979bf1d017cff045dc7ebd'
RESOLVER = '0x70997970C51812dc3A010C7d01b50e0d17dc79C8'
ADJUDICATOR = '0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC'
OP = {'Authorization': 'Bearer op-token'}
client = TestClient(app)


class FakeSender:
    """Stands in for Web3Sender; models usedNonce and counts broadcasts."""

    def __init__(self):
        self.used: set = set()
        self.pending: dict = {}
        self.known: set = set()
        self.broadcasts: list = []
        self.crash_on_wait = False

    def nonce_used(self, reviewer, nonce):
        return (reviewer.lower(), int(nonce)) in self.used

    def build_signed(self, target, reviewer, nonce, expiry, signature):
        h = '0x' + secrets.token_hex(32)
        self.pending[h] = (reviewer.lower(), int(nonce))
        return h, '0xraw' + h[2:]

    def broadcast(self, raw):
        h = '0x' + raw[5:]
        self.broadcasts.append(h)
        self.used.add(self.pending[h])
        self.known.add(h)
        return h

    def wait(self, h):
        if self.crash_on_wait:
            raise RuntimeError('simulated crash after broadcast')
        return chain.TxReceipt(1, 100, '7')

    def tx_known(self, h):
        return h in self.known

    def find_published(self, h):
        return '7' if h in self.known else None


@pytest.fixture
def env(monkeypatch, tmp_path):
    # Each publication test gets its own database; its temporary bundles must not
    # pollute the existing workflow tests after pytest removes their directories.
    import store
    from publication import db as publication_db
    monkeypatch.setattr(store, 'DB', tmp_path / 'state.sqlite3')
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setitem(globals(), 'DATA', tmp_path)
    store.init()
    publication_db.init()
    clock = Clock(real_now())
    monkeypatch.setattr(service, 'now', clock)
    monkeypatch.setattr(publisher, 'now', clock)
    client_key = new_rsa()
    key_path = tmp_path / 'world_client_key.pem'
    key_path.write_bytes(pem(client_key))
    for k, v in {
        'WORLD_ISSUER': ISSUER, 'WORLD_CLIENT_ID': CLIENT_ID, 'WORLD_CLIENT_KEY_PATH': str(key_path),
        'WORLD_CLIENT_KEY_ID': 'scooby-test-1', 'WORLD_ASSERTION_AUD': 'endpoint',
        'SCOOBY_PUBLISH_ENABLED': 'true', 'SCOOBY_CHAIN_ID': '11155111', 'SCOOBY_REPORT_REGISTRY': REGISTRY,
        'SCOOBY_RESOLVER': RESOLVER, 'SCOOBY_ADJUDICATOR': ADJUDICATOR, 'SCOOBY_PUBLISHER_KEY': PUBLISHER_KEY,
        'SCOOBY_ATTESTOR_KEY': ATTESTOR_KEY, 'SCOOBY_OPERATOR_TOKEN': 'op-token', 'SCOOBY_APPROVAL_TTL': '600',
        'SCOOBY_DEMO_AUTOPUBLISH': 'false', 'SCOOBY_RPC_URL': 'http://127.0.0.1:1',
    }.items():
        monkeypatch.setenv(k, v)
    fw = FakeWorld(clock, client_key)
    world = WorldClient(world_config(), transport=fw.transport(), clock=clock)
    app.dependency_overrides[deps.get_world] = lambda: world
    app.dependency_overrides[deps.get_world_optional] = lambda: world
    app.dependency_overrides[deps.get_gate] = lambda: service.make_gate(chain_config(), preflight=lambda: None)
    with db() as c:
        c.execute('INSERT OR REPLACE INTO pub_reviewers(iss,sub,label,enabled,created) VALUES(?,?,?,?,?)',
                  (ISSUER, fw.default_sub, 'reviewer-1', 1, clock()))
        # Tests share one SQLite file; park other tests' unfinished outbox rows so publishers only see ours.
        c.execute("UPDATE pub_outbox SET state='failed', error='test isolation' WHERE state NOT IN ('confirmed','failed')")

    class NS:
        pass
    ns = NS()
    ns.clock, ns.fw, ns.world, ns.client_key, ns.tmp = clock, fw, world, client_key, tmp_path
    yield ns
    app.dependency_overrides.clear()


# ------------------------------------------------------------------ helpers
def make_report(tmp: Path) -> tuple[str, str, Path]:
    """A fresh immutable report version (unique bytes) registered like /reports/import does."""
    rid = f'shib-pub-{uuid.uuid4().hex[:8]}'
    version = 'v1'
    bundle = tmp / f'bundle-{rid}'
    shutil.copytree(BUNDLE, bundle)
    rep = json.loads((bundle / 'report.json').read_text(encoding='utf-8'))
    rep['report_id'], rep['report_version'] = rid, version
    raw = json.dumps(rep, indent=2, ensure_ascii=False).encode('utf-8')
    (bundle / 'report.json').write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    cand, sel, run = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
    with db() as c:
        c.execute('INSERT INTO candidates VALUES(?,?,?)', (cand, '{}', real_now()))
        c.execute('INSERT INTO selections VALUES(?,?,?,?,?,?,?)', (sel, cand, 'diagnostic_exception', 't', 't', real_now(), sel))
        c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?)', (run, cand, sel, 'incomplete', real_now(), run))
        c.execute('INSERT INTO reports VALUES(?,?,?,?,?,?)', (rid, version, run, sha, str(bundle), real_now()))
    return rid, version, bundle


def timing(ns, **over):
    t = int(ns.clock())
    p = {'lock_time': t + 7200, 'cross_chain_cutoff': t + 3600, 'result_deadline': t + 7200 + 31 * 86400,
         'challenge_period': 86400}
    p.update(over)
    return p


def make_target(ns, **params) -> dict:
    rid, ver, bundle = make_report(ns.tmp)
    r = client.post('/publication/v1/targets', json={'report_id': rid, 'version': ver, 'params': timing(ns, **params)},
                    headers={**OP, 'Idempotency-Key': uuid.uuid4().hex})
    assert r.status_code == 200, r.text
    t = r.json()
    t['_bundle'] = bundle
    return t


def start(ns, target_id, decision='approve', *steps, key=None):
    if steps:
        ns.fw.script(*steps)
    r = client.post(f'/publication/v1/targets/{target_id}/attempts', json={'decision': decision, 'reason': 'test'},
                    headers={**OP, 'Idempotency-Key': key or uuid.uuid4().hex})
    assert r.status_code == 200, r.text
    return r.json()


def poll(ns, attempt_id, times=1, advance=None):
    out = None
    for _ in range(times):
        a = client.get(f'/publication/v1/attempts/{attempt_id}').json()
        ns.clock.advance(advance if advance is not None else max(a['interval'], 1))
        out = client.get(f'/publication/v1/attempts/{attempt_id}').json()
    return out


def poll_until_done(ns, attempt_id, limit=20):
    a = None
    for _ in range(limit):
        a = poll(ns, attempt_id)
        if a['status'] != 'pending':
            return a
    return a


def publish(target_id, key=None):
    return client.post(f'/publication/v1/targets/{target_id}/publish', headers={**OP, 'Idempotency-Key': key or uuid.uuid4().hex})


def approved_target(ns):
    t = make_target(ns)
    a = start(ns, t['id'], 'approve', 'pending', ('success', {}))
    a = poll_until_done(ns, a['id'])
    assert a['status'] == 'approved', a
    return t, a


def outbox_rows(target_id):
    with db() as c:
        return [dict(r) for r in c.execute('SELECT * FROM pub_outbox WHERE target_id=?', (target_id,))]


# ------------------------------------------------------------------ required cases
def test_happy_path_approve_then_publish_signature_recovers(env):
    t = make_target(env)
    a = start(env, t['id'], 'approve', 'pending', 'pending', 'slow_down', ('success', {}))
    assert a['status'] == 'pending' and a['user_code'] and 'device_code' not in a
    assert poll(env, a['id'])['status'] == 'pending'
    assert poll(env, a['id'])['status'] == 'pending'
    slowed = poll(env, a['id'])
    assert slowed['status'] == 'pending' and slowed['interval'] == 10  # slow_down adds 5s
    done = poll(env, a['id'], advance=10)
    assert done['status'] == 'approved'
    # The device request carried an essential acr claim (World step-up guide).
    claims = json.loads(env.fw.device_requests[-1]['claims'])
    assert claims['id_token']['acr']['essential'] is True
    r = publish(t['id'])
    assert r.status_code == 200, r.text
    out = r.json()
    row = outbox_rows(t['id'])[0]
    assert row['state'] == 'queued' and row['id'] == out['outbox_id']
    target = t['target']
    report = chain.report_tuple(target, row['reviewer_addr'])
    signer = chain.recover_approval(row['signature'], target['chainId'], target['registry'], report,
                                    int(row['nonce']), row['approval_expiry'])
    assert signer == chain.address_of(ATTESTOR_KEY) == row['reviewer_addr']
    sender = FakeSender()
    assert publisher.run_once(sender) == 'confirmed'
    assert len(sender.broadcasts) == 1
    assert client.get(f"/publication/v1/targets/{t['id']}").json()['status']['state'] == 'published'


def test_access_denied_no_receipt_publish_409(env):
    t = make_target(env)
    a = start(env, t['id'], 'approve', 'denied')
    assert poll(env, a['id'])['status'] == 'denied'
    with db() as c:
        assert c.execute('SELECT count(*) FROM pub_receipts WHERE target_id=?', (t['id'],)).fetchone()[0] == 0
    assert publish(t['id']).status_code == 409


def test_cli_enroll_reports_issuer_error_description(env, capsys):
    from publication import cli
    env.fw.script('denied_detail')
    with pytest.raises(SystemExit) as e:
        cli.enroll('x', env.world, sleep=lambda s: env.clock.advance(s))
    assert str(e.value) == 'Enrollment denied (account does not meet the requested acr); reviewer not added.'


def test_cli_world_check_and_environment_label(env):
    from publication import cli
    lines = cli.world_check(env.world)
    assert any(l.startswith('Issuer:') and ISSUER in l for l in lines)
    assert env.fw.token_requests == 0 and not env.fw.device_requests  # no login started
    assert cli.environment_label('https://sandbox.auth.world.org').startswith('SANDBOX')
    assert cli.environment_label('https://auth.world.org') == 'PRODUCTION'


def test_cli_enroll_without_acr_request_still_validates_acr(env):
    from publication import cli
    env.fw.script(('success', {'acr': 'https://world.org/oidc/acr/selfie'}))
    with pytest.raises(SystemExit) as e:
        cli.enroll('x', env.world, sleep=lambda s: env.clock.advance(s), request_acr=False)
    assert 'claims' not in env.fw.device_requests[-1]
    assert 'acr not accepted' in str(e.value)


def test_expired_token_and_local_deadline(env):
    t = make_target(env)
    a = start(env, t['id'], 'approve', 'expired')
    assert poll(env, a['id'])['status'] == 'expired'
    b = start(env, t['id'], 'approve', 'pending', 'pending', 'pending')
    assert poll(env, b['id'], advance=env.fw.expires_in + 1)['status'] == 'expired'
    assert publish(t['id']).status_code == 409


def test_cancelled_attempt_late_success_ignored(env, monkeypatch):
    t = make_target(env)
    a = start(env, t['id'], 'approve', ('success', {}))
    real_poll = env.world.poll

    def cancel_then_succeed(device_code):
        result = real_poll(device_code)
        assert client.post(f"/publication/v1/attempts/{a['id']}/cancel", headers=OP).json()['status'] == 'cancelled'
        return result
    monkeypatch.setattr(env.world, 'poll', cancel_then_succeed)
    assert poll(env, a['id'])['status'] == 'cancelled'
    with db() as c:
        assert c.execute('SELECT count(*) FROM pub_receipts WHERE target_id=?', (t['id'],)).fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM pub_events WHERE target_id=? AND kind='late_world_result_ignored'", (t['id'],)).fetchone()[0] == 1
    assert publish(t['id']).status_code == 409


def test_unknown_reviewer_rejected_not_reviewer(env):
    t = make_target(env)
    a = start(env, t['id'], 'approve', ('success', {'sub': 'someone-else'}))
    assert poll(env, a['id'])['status'] == 'rejected_not_reviewer'
    assert publish(t['id']).status_code == 409


def test_reviewer_disabled_before_publish_409(env):
    t, _ = approved_target(env)
    with db() as c:
        c.execute('UPDATE pub_reviewers SET enabled=0 WHERE sub=?', (env.fw.default_sub,))
    r = publish(t['id'])
    assert r.status_code == 409 and 'no longer enabled' in r.json()['detail']


@pytest.mark.parametrize('case,overrides', [
    ('wrong_iss', {'iss': 'https://evil.example'}),
    ('wrong_aud', {'aud': 'some-other-client'}),
    ('expired', {'exp': 'PAST', 'iat': 'PAST'}),
    ('auth_time_before_attempt', {'auth_time': 'BEFORE'}),
    ('acr_not_accepted', {'acr': 'https://world.org/oidc/acr/selfie'}),
    ('alg_none', {'_alg': 'none'}),
    ('hs256', {'_alg': 'HS256'}),
    ('unknown_kid', {'_kid': 'not-in-jwks', '_key': 'NEWKEY'}),
    ('bad_signature', {'_key': 'NEWKEY'}),
    ('missing_amr', {'amr': None}),
])
def test_id_token_validation_rejects(env, case, overrides):
    t = make_target(env)
    o = dict(overrides)
    past = int(env.clock()) - 4000
    for k, v in list(o.items()):
        if v == 'PAST':
            o[k] = past
        elif v == 'BEFORE':
            o[k] = int(env.clock()) - 3600
        elif v == 'NEWKEY':
            o[k] = new_rsa()
    a = start(env, t['id'], 'approve', ('success', o))
    done = poll(env, a['id'])
    assert done['status'] == 'error' and 'id_token rejected' in done['error'], (case, done)
    assert publish(t['id']).status_code == 409


def test_replay_and_idempotency(env):
    t, _ = approved_target(env)
    first = publish(t['id'], key='pub-1')
    assert first.status_code == 200
    assert publish(t['id'], key='pub-1').json() == first.json()          # same key + same body
    assert publish(t['id'], key='pub-2').status_code == 409              # receipt already consumed
    other, _ = approved_target(env)
    assert publish(other['id'], key='pub-1').status_code == 409          # same key, different body
    # Same idempotency rule for targets.
    rid, ver, _ = make_report(env.tmp)
    body = {'report_id': rid, 'version': ver, 'params': timing(env)}
    h = {**OP, 'Idempotency-Key': 'tgt-1'}
    a = client.post('/publication/v1/targets', json=body, headers=h)
    assert client.post('/publication/v1/targets', json=body, headers=h).json() == a.json()
    body2 = dict(body, params=timing(env, challenge_period=1))
    assert client.post('/publication/v1/targets', json=body2, headers=h).status_code == 409


def test_report_byte_change_after_approval_fails_closed(env):
    t, _ = approved_target(env)
    p = t['_bundle'] / 'report.json'
    raw = bytearray(p.read_bytes())
    raw[-2] = ord(' ') if raw[-2] != ord(' ') else ord('\n')
    p.write_bytes(bytes(raw))
    r = publish(t['id'])
    assert r.status_code == 409 and 'changed' in r.json()['detail']
    assert outbox_rows(t['id']) == []


def test_reject_and_revise_never_publish_newer_reject_overrides(env):
    t = make_target(env)
    for decision in ('reject', 'revise'):
        a = start(env, t['id'], decision, ('success', {}))
        assert poll(env, a['id'])['status'] == 'approved'  # World auth ok; receipt decision is the intent
        assert publish(t['id']).status_code == 409
    t2 = make_target(env)
    a = start(env, t2['id'], 'approve', ('success', {}))
    assert poll(env, a['id'])['status'] == 'approved'
    env.clock.advance(1)
    b = start(env, t2['id'], 'reject', ('success', {}))
    assert poll(env, b['id'])['status'] == 'approved'
    r = publish(t2['id'])
    assert r.status_code == 409 and 'reject' in r.json()['detail']


def test_proof_success_alone_creates_no_outbox(env):
    t, a = approved_target(env)
    for _ in range(3):
        client.get(f"/publication/v1/attempts/{a['id']}")
        client.get(f"/web/v1/approvals/{a['id']}")
    assert outbox_rows(t['id']) == []


def test_verifier_unavailable_never_approves(env):
    t = make_target(env)
    a = start(env, t['id'], 'approve', 'http500')
    done = poll(env, a['id'])
    assert done['status'] == 'error'
    b = start(env, t['id'], 'approve', 'timeout')
    assert poll(env, b['id'])['status'] == 'pending'   # timeout: back off, never approve
    assert publish(t['id']).status_code == 409
    # Discovery down on a cold client: nothing starts (503).
    env.fw.down = True
    cold = WorldClient(world_config(), transport=env.fw.transport(), clock=env.clock)
    app.dependency_overrides[deps.get_world] = lambda: cold
    t2 = make_target(env)
    r = client.post(f"/publication/v1/targets/{t2['id']}/attempts", json={'decision': 'approve', 'reason': 'x'},
                    headers={**OP, 'Idempotency-Key': uuid.uuid4().hex})
    assert r.status_code == 503


def test_two_publishers_one_broadcast_and_stale_fence_rejected(env):
    t, _ = approved_target(env)
    assert publish(t['id']).status_code == 200
    sender = FakeSender()
    row_a = publisher.claim('A')
    assert row_a and publisher.claim('B') is None          # lease held: B gets nothing
    with db() as c:                                        # A stalls past its lease
        c.execute('UPDATE pub_outbox SET lease=? WHERE id=?', (env.clock() - 1, row_a['id']))
    row_b = publisher.claim('B')
    assert row_b and row_b['fence'] == row_a['fence'] + 1
    assert publisher.process(row_a, sender) == 'lost_lease'   # stale fence: no broadcast
    assert sender.broadcasts == []
    assert publisher.process(row_b, sender) == 'confirmed'
    assert len(sender.broadcasts) == 1
    with pytest.raises(publisher.LostLease):
        publisher._write(row_a['id'], row_a['fence'], error='stale write')


def test_crash_after_broadcast_reconciles_without_second_broadcast(env):
    t, _ = approved_target(env)
    assert publish(t['id']).status_code == 200
    sender = FakeSender()
    sender.crash_on_wait = True
    row = publisher.claim()
    with pytest.raises(RuntimeError):
        publisher.process(row, sender)
    stored = outbox_rows(t['id'])[0]
    assert stored['state'] == 'submitted' and stored['tx_hash']
    sender.crash_on_wait = False
    with db() as c:
        c.execute('UPDATE pub_outbox SET lease=? WHERE id=?', (env.clock() - 1, stored['id']))
    assert publisher.run_once(sender) == 'confirmed'
    assert len(sender.broadcasts) == 1
    assert outbox_rows(t['id'])[0]['onchain_report_id'] == '7'


def test_revoke_before_and_after_confirm(env):
    t, _ = approved_target(env)
    assert publish(t['id']).status_code == 200
    r = client.post(f"/publication/v1/targets/{t['id']}/revoke", json={'reason': 'wrong token'}, headers=OP).json()
    assert r['phase'] == 'before_publication'
    sender = FakeSender()
    assert publisher.run_once(sender) is None             # nothing left to publish
    assert sender.broadcasts == [] and outbox_rows(t['id'])[0]['state'] == 'failed'
    t2, _ = approved_target(env)
    assert publish(t2['id']).status_code == 200
    assert publisher.run_once(sender) == 'confirmed'
    r2 = client.post(f"/publication/v1/targets/{t2['id']}/revoke", json={'reason': 'later doubt'}, headers=OP).json()
    assert r2['phase'] == 'after_confirmation'
    st = client.get(f"/publication/v1/targets/{t2['id']}").json()['status']
    assert st['state'] == 'revoked' and st['published_onchain'] is True


def test_revoke_racing_publisher_before_broadcast(env, monkeypatch):
    t, _ = approved_target(env)
    assert publish(t['id']).status_code == 200
    sender = FakeSender()
    real_build = sender.build_signed

    def build_then_revoke(*a, **kw):
        out = real_build(*a, **kw)
        client.post(f"/publication/v1/targets/{t['id']}/revoke", json={'reason': 'race'}, headers=OP)
        return out
    monkeypatch.setattr(sender, 'build_signed', build_then_revoke)
    row = publisher.claim()
    assert publisher.process(row, sender) in ('failed', 'lost_lease')
    assert sender.broadcasts == []


def test_frozen_schemas_match_handoff_digests():
    handoff = (ROOT / 'HANDOFF.md').read_text(encoding='utf-8')
    for name, label in (('candidate.schema.json', 'candidate'), ('report.schema.json', 'report')):
        d = hashlib.sha256((ROOT / 'schemas' / name).read_bytes()).hexdigest()
        assert f'{label} `{d}`' in handoff, name


def test_web_approval_never_leaks_secrets(env):
    t = make_target(env)
    web_id = f"{t['report_id']}@{t['report_version']}"
    a = client.post(f'/web/v1/reports/{web_id}/approve')
    assert a.status_code == 200, a.text
    bodies = [a.text]
    for _ in range(5):
        env.clock.advance(6)
        bodies.append(client.get(f"/web/v1/approvals/{a.json()['id']}").text)
    bodies.append(client.get(f'/web/v1/reports/{web_id}').text)
    blob = '\n'.join(bodies)
    assert '"status":"approved"' in bodies[-2].replace(' ', '')
    for secret in env.fw.issued_device_codes + env.fw.issued_id_tokens + [ATTESTOR_KEY[2:], PUBLISHER_KEY[2:]]:
        assert secret not in blob
    for word in ('device_code', 'id_token', 'access_token', 'PRIVATE KEY', 'client_assertion'):
        assert word not in blob


def test_logs_and_db_never_contain_tokens_or_device_codes(env, caplog):
    caplog.set_level(logging.DEBUG)
    t, a = approved_target(env)
    publish(t['id'])
    db_bytes = b''.join(p.read_bytes() for p in DATA.glob('state.sqlite3*'))
    for secret in env.fw.issued_device_codes + env.fw.issued_id_tokens:
        assert secret not in caplog.text
        assert secret.encode() not in db_bytes
    with db() as c:
        h = c.execute('SELECT device_code_hash FROM pub_attempts WHERE id=?', (a['id'],)).fetchone()[0]
    assert h == hashlib.sha256(env.fw.issued_device_codes[-1].encode()).hexdigest()
    assert 'world_timing' in caplog.text


# ------------------------------------------------------------------ extra guards
def test_publish_disabled_or_unready_is_503(env, monkeypatch):
    t, _ = approved_target(env)
    app.dependency_overrides.pop(deps.get_gate)
    monkeypatch.setenv('SCOOBY_PUBLISH_ENABLED', 'false')
    assert publish(t['id']).status_code == 503
    monkeypatch.setenv('SCOOBY_PUBLISH_ENABLED', 'true')
    assert publish(t['id']).status_code == 503       # real preflight cannot reach the RPC: fail closed
    assert outbox_rows(t['id']) == []
    app.dependency_overrides[deps.get_gate] = lambda: service.make_gate(chain_config(), preflight=lambda: None)
    monkeypatch.setenv('SCOOBY_ATTESTOR_KEY', PUBLISHER_KEY)
    assert publish(t['id']).status_code == 503       # attestor must differ from publisher


def test_operator_token_required(env, monkeypatch):
    rid, ver, _ = make_report(env.tmp)
    body = {'report_id': rid, 'version': ver, 'params': timing(env)}
    assert client.post('/publication/v1/targets', json=body, headers={'Idempotency-Key': 'x'}).status_code == 401
    assert client.post('/publication/v1/targets', json=body, headers={'Authorization': 'Bearer wrong', 'Idempotency-Key': 'x'}).status_code == 401
    monkeypatch.delenv('SCOOBY_OPERATOR_TOKEN')
    assert client.post('/publication/v1/targets', json=body, headers={**OP, 'Idempotency-Key': 'x'}).status_code == 503


def test_target_timing_rules_422(env):
    rid, ver, _ = make_report(env.tmp)
    t = int(env.clock())
    bad = [
        {'cross_chain_cutoff': t + 9000},                      # cutoff after lock
        {'lock_time': t + 60, 'cross_chain_cutoff': t + 10},   # lock too soon
        {'result_deadline': t + 7200 + 10 * 86400},            # < lock + 30 days
        {'challenge_period': 0},
        {'resolver': '0x' + '0' * 40},
    ]
    for over in bad:
        r = client.post('/publication/v1/targets', json={'report_id': rid, 'version': ver, 'params': timing(env, **over)},
                        headers={**OP, 'Idempotency-Key': uuid.uuid4().hex})
        assert r.status_code == 422, (over, r.text)


def test_one_pending_attempt_per_target(env):
    t = make_target(env)
    start(env, t['id'], 'approve', 'pending')
    r = client.post(f"/publication/v1/targets/{t['id']}/attempts", json={'decision': 'approve', 'reason': 'x'},
                    headers={**OP, 'Idempotency-Key': uuid.uuid4().hex})
    assert r.status_code == 409


def test_client_assertion_enforced_by_issuer(env):
    other = new_rsa()
    p = env.tmp / 'wrong.pem'
    p.write_bytes(pem(other))
    os.environ['WORLD_CLIENT_KEY_PATH'] = str(p)
    bad = WorldClient(world_config(), transport=env.fw.transport(), clock=env.clock)
    app.dependency_overrides[deps.get_world] = lambda: bad
    t = make_target(env)
    r = client.post(f"/publication/v1/targets/{t['id']}/attempts", json={'decision': 'approve', 'reason': 'x'},
                    headers={**OP, 'Idempotency-Key': uuid.uuid4().hex})
    assert r.status_code == 503 and env.fw.rejected_assertions >= 1
    # Every request gets a fresh assertion; a replayed jti is refused by the issuer.
    assertion = env.world.client_assertion(f'{ISSUER}/api/v1/token')
    import httpx
    form = {'client_id': CLIENT_ID, 'client_assertion_type': ASSERTION_TYPE, 'client_assertion': assertion,
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code', 'device_code': 'nope'}
    tr = env.fw.transport()
    for expected in ('invalid_grant', 'invalid_client'):
        resp = httpx.Client(transport=tr).post(f'{ISSUER}/api/v1/token', data=form)
        assert resp.json()['error'] == expected


def test_default_manifest_hash_matches_web_recompute(env, monkeypatch):
    """The web "Recompute hash" button computes keccak256(utf8(canonicalJSON(manifest))) with sorted
    keys and no whitespace (ScoobyDAO-web src/lib/canonical.ts). The default must match it."""
    from eth_utils import keccak
    monkeypatch.delenv('SCOOBY_CLAIM_HASH_ALG', raising=False)
    t = make_target(env)
    rep = client.get(f"/web/v1/reports/{t['report_id']}@{t['report_version']}").json()
    canon = json.dumps(rep['manifest'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    assert rep['manifestHash'] == '0x' + keccak(canon).hex().removeprefix('0x')


def test_web_adapter_shapes(env):
    t = make_target(env)
    web_id = f"{t['report_id']}@{t['report_version']}"
    rep = client.get(f'/web/v1/reports/{web_id}').json()
    for k in ('id', 'token', 'chainId', 'status', 'manifest', 'manifestHash', 'createdAt'):
        assert k in rep
    assert rep['status'] == 'draft' and rep['manifestHash'] == '0x' + t['claim_hash']
    m = rep['manifest']
    for k in ('version', 'chainId', 'token', 'claims', 'evidence', 'summary', 'excludedWallets', 'windowSeconds', 'createdAt'):
        assert k in m
    assert m['schema'] == 'scooby.claim-manifest/1' and m['reportSha256'] == t['report_sha256']
    assert client.get('/web/v1/health').json() == {'ok': True}
    raw = client.get(f'/web/v1/reports/{web_id}/raw')
    assert hashlib.sha256(raw.content).hexdigest() == t['report_sha256']
    appr = client.post(f'/web/v1/reports/{web_id}/approve').json()
    for k in ('id', 'reportId', 'manifestHash', 'status', 'expiresAt', 'userCode', 'verificationUri'):
        assert k in appr
    assert client.post(f'/web/v1/reports/{web_id}/approve').json()['id'] == appr['id']   # reuse pending
    assert client.get(f'/web/v1/reports/{web_id}').json()['status'] == 'awaiting_approval'
