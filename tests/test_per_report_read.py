"""Per-report review sessions (the review desk "Read" button) and SCOOBY_REVIEW_PER_REPORT.

Reuses the admin checkpoint fixtures (fake World issuer, synthetic identities). No network.
"""
import json

from fake_world import ISSUER
from publication import admin
from publication.world import Identity
from admin_support import login
from test_admin_checkpoints import ADMIN_SUB, client, env, make_report, poll, valid  # noqa: F401 (env is a fixture)
from test_sme_review_release import render_with_html


def read_login(env, rid, ver, expect='active'):
    """Read button: a World login limited to one report version."""
    env.fw.script(('success', {}))
    r = client.post('/web/v1/admin/session', json={'report_id': rid, 'version': ver})
    assert r.status_code == 200, r.text
    h = {'Authorization': 'Bearer ' + r.json()['session_token']}
    env.clock.advance(r.json()['interval'])
    s = client.get('/web/v1/admin/session', headers=h).json()
    assert s['state'] == expect, s
    return h, s


def test_read_session_opens_only_its_report(env):
    a, va, _ = make_report(env)
    b, vb, _ = make_report(env)
    render_with_html(a, va)
    h, s = read_login(env, a, va)
    valid('session', s)                     # the versioned session contract is unchanged
    assert client.get(f'/web/v1/admin/reviews/{a}/{va}', headers=h).status_code == 200
    assert client.get(f'/web/v1/admin/reviews/{a}/{va}/files/index.html', headers=h).status_code == 200
    for path in (f'/web/v1/admin/reviews/{b}/{vb}', f'/web/v1/admin/reviews/{b}/{vb}/artifacts', '/web/v1/admin/reviews'):
        r = client.get(path, headers=h)
        assert r.status_code == 403 and 'limited to another report' in r.json()['detail'], path


def test_read_session_can_decide_on_its_report_only(env):
    a, va, _ = make_report(env)
    b, vb, _ = make_report(env)
    h, _ = read_login(env, a, va)
    target = client.get(f'/web/v1/admin/reviews/{a}/{va}', headers=h).json()['target_digest']
    env.fw.script(('success', {}))
    r = client.post(f'/web/v1/admin/reviews/{a}/{va}/attempts', headers={**h, 'Idempotency-Key': 'k1'},
                    json={'decision': 'approve', 'reason': 'checked', 'expected_target_digest': target})
    assert r.status_code == 200, r.text
    assert poll(env, h, r.json()['id'])['status'] == 'confirmed'
    other = client.post(f'/web/v1/admin/reviews/{b}/{vb}/attempts', headers={**h, 'Idempotency-Key': 'k2'},
                        json={'decision': 'approve', 'reason': 'x', 'expected_target_digest': target})
    assert other.status_code == 403


def test_per_report_setting_blocks_the_generic_session_from_reports(env, monkeypatch):
    a, va, _ = make_report(env)
    h = login(client, env.fw, env.clock)
    assert client.get(f'/web/v1/admin/reviews/{a}/{va}', headers=h).status_code == 200   # default: generic session reads
    monkeypatch.setenv('SCOOBY_REVIEW_PER_REPORT', 'true')
    r = client.get(f'/web/v1/admin/reviews/{a}/{va}', headers=h)
    assert r.status_code == 403 and 'use Read on this report' in r.json()['detail']
    assert client.get('/web/v1/admin/reviews', headers=h).status_code == 200              # the list stays available
    hr, _ = read_login(env, a, va)
    assert client.get(f'/web/v1/admin/reviews/{a}/{va}', headers=hr).status_code == 200


def test_read_session_never_authorizes_investigations(env):
    a, va, _ = make_report(env)
    from store import db
    with db() as c:
        admin.grant(c, ISSUER, ADMIN_SUB, 'case_investigation', 'test')
    h, _ = read_login(env, a, va)
    assert client.get('/investigations/run-x/events', headers=h).status_code == 403
    ident = Identity(iss=ISSUER, sub=ADMIN_SUB, acr='https://world.org/oidc/acr/orb', amr=('pop',), auth_time=0)
    assert admin.authorize_case_admin(ident, {'action': 'diagnostic_research', 'case_id': 'c'}) is False
    login(client, env.fw, env.clock)                                                      # a full admin session does
    assert admin.authorize_case_admin(ident, {'action': 'diagnostic_research', 'case_id': 'c'}) is True


def test_read_login_for_an_unknown_report_starts_nothing(env):
    before = len(env.fw.device_requests)
    r = client.post('/web/v1/admin/session', json={'report_id': 'missing', 'version': 'v1'})
    assert r.status_code == 404 and len(env.fw.device_requests) == before


def test_public_review_queue_lists_reports_without_private_fields(env):
    a, va, _ = make_report(env)
    r = client.get('/web/v1/review-queue')
    assert r.status_code == 200
    item = next(i for i in r.json()['items'] if i['report_id'] == a)
    assert set(item) == {'report_id', 'report_version', 'report_sha256', 'created', 'state'}
    assert item['state'] == 'pending_review'
    assert ADMIN_SUB not in json.dumps(r.json())
