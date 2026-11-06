"""SCOOBY_OPEN_REVIEW: any validated World ID may review reports and sign off publication, without a reviewer list.

Reuses the admin checkpoint fixtures (fake World issuer, synthetic identities). No network.
"""
from store import db
from publication import admin
from fake_world import ISSUER
from admin_support import enroll, login
from test_admin_checkpoints import approve, client, env, make_report, status  # noqa: F401 (env is a fixture)

STRANGER = 'pairwise-sub-stranger-1'


def test_off_by_default_a_stranger_is_not_permitted(env):
    login(client, env.fw, env.clock, sub=STRANGER, expect='not_permitted')
    with db() as c:
        assert c.execute('SELECT count(*) FROM pub_reviewers WHERE sub=?', (STRANGER,)).fetchone()[0] == 0


def test_open_review_lets_any_world_id_review_and_approve(env, monkeypatch):
    monkeypatch.setenv('SCOOBY_OPEN_REVIEW', 'true')
    rid, ver, _ = make_report(env)
    env.fw.default_sub = STRANGER                       # the stranger signs in and confirms the decision
    h = login(client, env.fw, env.clock)
    assert client.get('/web/v1/admin/session', headers=h).json()['scopes'] == ['publication', 'report_review']
    assert client.get('/web/v1/admin/reviews', headers=h).status_code == 200
    approve(env, h, rid, ver)
    assert status(rid, ver)['state'] == 'approved'
    revoke = client.post(f'/web/v1/admin/reviews/{rid}/{ver}/revoke', json={'reason': 'removing'}, headers=h)
    assert revoke.status_code == 200, revoke.text
    assert status(rid, ver)['state'] == 'pending_review'
    with db() as c:
        row = c.execute('SELECT label, enabled FROM pub_reviewers WHERE sub=?', (STRANGER,)).fetchone()
        assert row['label'].startswith(admin.OPEN_LABEL_PREFIX) and row['enabled'] == 1
        assert 'case_investigation' not in admin.scopes_of(c, ISSUER, STRANGER)


def test_open_review_never_overrides_an_operator_disable(env, monkeypatch):
    monkeypatch.setenv('SCOOBY_OPEN_REVIEW', 'true')
    enroll(ISSUER, STRANGER, label='banned', enabled=False)
    login(client, env.fw, env.clock, sub=STRANGER, expect='not_permitted')


def test_turning_open_review_off_withdraws_its_grants(env, monkeypatch):
    monkeypatch.setenv('SCOOBY_OPEN_REVIEW', 'true')
    h = login(client, env.fw, env.clock, sub=STRANGER)
    monkeypatch.setenv('SCOOBY_OPEN_REVIEW', 'false')
    # A live session loses the open scopes on its next request.
    assert client.get('/web/v1/admin/reviews', headers=h).status_code == 403
    # At startup the reviewers it added are disabled, so the publication allowlist no longer accepts them either.
    assert admin.apply_open_review_mode() == 1
    with db() as c:
        assert c.execute('SELECT enabled FROM pub_reviewers WHERE sub=?', (STRANGER,)).fetchone()[0] == 0
    login(client, env.fw, env.clock, sub=STRANGER, expect='not_permitted')
    # Turning it back on re-enables that reviewer on its next login.
    monkeypatch.setenv('SCOOBY_OPEN_REVIEW', 'true')
    login(client, env.fw, env.clock, sub=STRANGER)


def test_explicit_reviewer_keeps_its_own_grants_when_open_review_ends(env, monkeypatch):
    sub = 'pairwise-sub-explicit-1'
    enroll(ISSUER, sub, 'report_review', label='named-sme')
    monkeypatch.setenv('SCOOBY_OPEN_REVIEW', 'true')
    login(client, env.fw, env.clock, sub=sub)
    with db() as c:
        assert admin.scopes_of(c, ISSUER, sub) == {'report_review', 'publication'}
    monkeypatch.setenv('SCOOBY_OPEN_REVIEW', 'false')
    assert admin.apply_open_review_mode() == 0          # named reviewer is not disabled
    with db() as c:
        assert admin.scopes_of(c, ISSUER, sub) == {'report_review'}
        assert c.execute('SELECT label FROM pub_reviewers WHERE sub=?', (sub,)).fetchone()[0] == 'named-sme'
