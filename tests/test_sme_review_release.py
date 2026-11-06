"""Subject-matter-expert review access, approved-only public release and SCOOBY_REVIEWERS.

Reuses the admin checkpoint fixtures (fake World issuer, synthetic identities). No network.
"""
import hashlib
import json
import uuid
from pathlib import Path

import pytest

from store import db, dumps, now as real_now
from publication import admin, review, reviewers
from fake_world import ISSUER
from admin_support import enroll, login
from test_admin_checkpoints import ADMIN_SUB, OTHER_SUB, approve, client, env, make_report  # noqa: F401 (env is a fixture)

HTML = b'<!doctype html><title>report</title><p>full report</p>'


def render_with_html(rid: str, version: str) -> str:
    """A completed render whose manifest locks an index.html, as worker.py records it."""
    with db() as c:
        sha, path = c.execute('SELECT sha256, path FROM reports WHERE id=? AND version=?', (rid, version)).fetchone()
    job = uuid.uuid4().hex
    manifest = json.dumps({'report_id': rid, 'report_version': version, 'report_sha256': sha,
                           'html_sha256': hashlib.sha256(HTML).hexdigest()}).encode()
    out = review.DATA / 'artifacts' / job
    out.mkdir(parents=True)
    (out / 'manifest.json').write_bytes(manifest)
    (out / 'index.html').write_bytes(HTML)
    (out / 'report.json').write_bytes((Path(path) / 'report.json').read_bytes())   # worker copies the exact report bytes
    with db() as c:
        c.execute('INSERT INTO jobs(id,kind,ref,state,available,idem,created) VALUES(?,?,?,?,?,?,?)',
                  (job, 'render', dumps({'id': rid, 'version': version, 'sha256': sha}), 'done', 0, 'render:' + job, real_now()))
        c.execute('INSERT INTO render_manifests VALUES(?,?)', (job, hashlib.sha256(manifest).hexdigest()))
    return job


def test_sme_views_unreleased_report_that_the_public_cannot(env, monkeypatch):
    monkeypatch.setenv('SCOOBY_REPORT_RELEASE', 'approved')
    rid, ver, _ = make_report(env)
    job = render_with_html(rid, ver)
    with db() as c:
        package = c.execute('SELECT sha256 FROM render_manifests WHERE job_id=?', (job,)).fetchone()[0]

    # Public: the list, artifacts, rendered files and package are all hidden until approval.
    assert all(r['report_id'] != rid for r in client.get('/reports').json())
    for path in (f'/reports/{rid}/{ver}/artifacts', f'/artifacts/{job}/index.html', f'/artifacts/{job}/manifest.json',
                 f'/packages/{package}', f'/packages/{package}/report.json'):
        assert client.get(path).status_code == 404, path

    # SME with report_review: listing points at the admin file routes and serves the exact bytes.
    h = login(client, env.fw, env.clock)
    d = client.get(f'/web/v1/admin/reviews/{rid}/{ver}', headers=h).json()
    assert d['links']['artifacts'] == f'/web/v1/admin/reviews/{rid}/{ver}/artifacts'
    listing = client.get(d['links']['artifacts'], headers=h)
    assert listing.status_code == 200, listing.text
    html_url = listing.json()['artifacts']['html']['url']
    assert html_url == f'/web/v1/admin/reviews/{rid}/{ver}/files/index.html'
    assert listing.json()['package']['url'] is None
    page = client.get(html_url, headers=h)
    assert page.status_code == 200 and page.content == HTML
    assert page.headers['content-security-policy'].startswith("default-src 'none'")
    assert client.get(f'/web/v1/admin/reviews/{rid}/{ver}/files/report.json', headers=h).status_code == 200

    # After a World-confirmed approval the public sees it too.
    approve(env, h, rid, ver)
    assert any(r['report_id'] == rid for r in client.get('/reports').json())
    assert client.get(f'/artifacts/{job}/index.html').content == HTML
    assert client.get(f'/packages/{package}').status_code == 200


def test_sme_routes_need_a_report_review_session(env):
    rid, ver, _ = make_report(env)
    render_with_html(rid, ver)
    base = f'/web/v1/admin/reviews/{rid}/{ver}'
    for path in (base + '/artifacts', base + '/files/index.html', base + '/files/assets/x.json'):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers={'Authorization': 'Bearer op-token'}).status_code == 401, path
    enroll(ISSUER, OTHER_SUB, 'publication', label='publisher-only')
    h = login(client, env.fw, env.clock, sub=OTHER_SUB)
    assert client.get(base + '/files/index.html', headers=h).status_code == 403
    h = login(client, env.fw, env.clock)
    assert client.get(base + '/files/secrets.txt', headers=h).status_code == 404
    assert client.get(f'/web/v1/admin/reviews/{rid}/missing/artifacts', headers=h).status_code == 404


def test_sme_file_requires_a_render_of_the_exact_bytes(env):
    rid, ver, _ = make_report(env)
    h = login(client, env.fw, env.clock)
    assert client.get(f'/web/v1/admin/reviews/{rid}/{ver}/files/index.html', headers=h).status_code == 404
    listing = client.get(f'/web/v1/admin/reviews/{rid}/{ver}/artifacts', headers=h).json()
    assert listing['render_status'] == 'not_rendered'


def test_public_gate_opens_only_the_library_reads(env, monkeypatch):
    monkeypatch.setenv('SCOOBY_PUBLIC_GATE', 'true')
    monkeypatch.setenv('SCOOBY_REPORT_RELEASE', 'approved')
    rid, ver, _ = make_report(env)
    job = render_with_html(rid, ver)
    assert client.get('/reports').status_code == 200
    assert client.get(f'/reports/{rid}/{ver}/artifacts').status_code == 404       # reachable, but not released
    h = login(client, env.fw, env.clock)
    approve(env, h, rid, ver)
    assert client.get(f'/reports/{rid}/{ver}/artifacts').status_code == 200
    assert client.get(f'/artifacts/{job}/index.html').status_code == 200
    # Still private: report detail with local review rows, writes, and operator routes.
    assert client.get(f'/reports/{rid}/{ver}').status_code == 404
    assert client.post('/reports/import', json={'run_id': 'x', 'bundle_path': '/etc'}).status_code == 404
    assert client.post(f'/reports/{rid}/{ver}/render', headers={'Idempotency-Key': 'k'}).status_code == 404
    assert client.get('/candidates').status_code == 404


# ------------------------------------------------------------------ SCOOBY_REVIEWERS
def entry(sub, scopes, label='sme-1', **kw):
    return {'label': label, 'iss': ISSUER, 'sub': sub, 'scopes': scopes, **kw}


def test_env_reviewers_are_authoritative_for_listed_subjects(env, monkeypatch):
    sub = 'pairwise-sub-env-1'
    monkeypatch.setenv('SCOOBY_REVIEWERS', json.dumps([entry(sub, ['report_review', 'publication'])]))
    assert reviewers.load_from_env() == 1
    with db() as c:
        assert admin.scopes_of(c, ISSUER, sub) == {'report_review', 'publication'}
    monkeypatch.setenv('SCOOBY_REVIEWERS', json.dumps([entry(sub, ['report_review'])]))
    reviewers.load_from_env()
    with db() as c:
        assert admin.scopes_of(c, ISSUER, sub) == {'report_review'}
        assert admin.scopes_of(c, ISSUER, ADMIN_SUB) == {'report_review'}   # unlisted reviewer untouched
    monkeypatch.setenv('SCOOBY_REVIEWERS', json.dumps([entry(sub, ['report_review'], enabled=False)]))
    reviewers.load_from_env()
    with db() as c:
        assert admin.scopes_of(c, ISSUER, sub) == frozenset()                 # disabled reviewer holds nothing


def test_env_reviewer_can_sign_in_and_review(env, monkeypatch):
    sub = 'pairwise-sub-env-2'
    monkeypatch.setenv('SCOOBY_REVIEWERS', json.dumps([entry(sub, ['report_review'])]))
    reviewers.load_from_env()
    h = login(client, env.fw, env.clock, sub=sub)
    assert client.get('/web/v1/admin/reviews', headers=h).status_code == 200


@pytest.mark.parametrize('raw', [
    'not json', '{}', json.dumps([{'label': 'x', 'iss': 'http://auth.world.org', 'sub': 's', 'scopes': []}]),
    json.dumps([{'label': 'x', 'iss': ISSUER, 'sub': '', 'scopes': []}]),
    json.dumps([{'label': 'x', 'iss': ISSUER, 'sub': 's', 'scopes': ['root']}]),
    json.dumps([{'label': 'x', 'iss': ISSUER, 'sub': 's', 'scopes': [], 'extra': 1}]),
    json.dumps([{'label': 'x', 'iss': ISSUER, 'sub': 's', 'scopes': []}] * 2),
])
def test_invalid_env_reviewers_load_nobody_and_never_log_subjects(env, monkeypatch, caplog, raw):
    monkeypatch.setenv('SCOOBY_REVIEWERS', raw)
    with db() as c:
        before = c.execute('SELECT count(*) FROM pub_reviewers').fetchone()[0]
    assert reviewers.load_from_env() == 0
    with db() as c:
        assert c.execute('SELECT count(*) FROM pub_reviewers').fetchone()[0] == before
    assert 'pairwise' not in caplog.text


def test_export_round_trips_through_load(env, monkeypatch):
    out = reviewers.export('admin-1')
    assert out == [{'label': 'admin-1', 'iss': ISSUER, 'sub': ADMIN_SUB, 'scopes': ['report_review'], 'enabled': True}]
    assert reviewers.parse(json.dumps(out)) == out
