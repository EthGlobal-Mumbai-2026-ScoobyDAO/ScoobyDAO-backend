"""scooby.reference-display/1: public case items, admin reads, case-action refusal, display-only mode, startup status.

Uses the admin checkpoint fixtures (fake World issuer, synthetic identities, real session machinery) and the
synthetic six-reference archive. No network.
"""
import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator

import reference_seed
import reference_seed_fixture as fx
from admin_support import enroll, login, session_headers
from fake_world import ISSUER
from test_admin_checkpoints import ADMIN_SUB, client, decide, env, poll  # noqa: F401 (env is a fixture)
from test_per_report_read import read_login

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / 'schemas/runtime/scouting-case-list-v2.schema.json').read_text(encoding='utf-8-sig'))
REFERENCE = {'kind': 'historical_reference', 'label': 'Historical reference — unreviewed'}


@pytest.fixture
def refs(env, monkeypatch):
    for k in ('SCOOBY_DISPLAY_ONLY', 'SCOOBY_REVIEW_PER_REPORT'):
        monkeypatch.delenv(k, raising=False)
    data, sha, pins = fx.build()
    monkeypatch.setattr(reference_seed, 'PINNED_ZIP_SHA256', sha)
    monkeypatch.setattr(reference_seed, 'PINNED_PAIRS', pins)
    reference_seed.restore(data, sha)
    env.pins = pins
    env.zip, env.sha = data, sha
    return env


def plain_case(n=7):
    """A non-reference case with a fresh, digest-valid snapshot."""
    from store import db, dumps, now
    address = '0x' + f'{n:040x}'
    cid = '1:' + address
    record = {'candidate_id': cid, 'identity': {'chain_id': 1, 'address': address, 'symbol': None}, 'mode': 'live', 'evidence': [],
              'triggers': [], 'screening': {'quality_issues': []}}
    assessment = {'groups': []}
    policy = __import__('case_engine').policy_digest()
    sid = hashlib.sha256(dumps({'record': record, 'evidence': {}, 'policy': policy, 'assessment': assessment}).encode()).hexdigest()
    case_id = hashlib.sha256(cid.encode()).hexdigest()
    with db() as c:
        c.execute('INSERT INTO case_snapshots VALUES(?,?,?,?,?,?,?,?)', (sid, cid, dumps(record), '{}', policy, dumps(assessment), now(), now() + 3600))
        c.execute("INSERT INTO cases VALUES(?,?,?,'monitoring',?)", (case_id, cid, sid, now()))
    return case_id


def report_session(env, pins, sym):
    _, _, rid, ver, _ = pins[sym]
    h, _ = read_login(env, rid, ver)
    return h


# ---------------------------------------------------------------------------- public reads
def test_case_list_carries_reference_objects_and_validates(refs):
    other = plain_case()
    body = client.get('/scouting/cases').json()
    Draft202012Validator(SCHEMA).validate(body)          # every item, reference and non-reference
    items = {x['case_id']: x for x in body['cases']}
    assert items[other]['reference'] is None
    for sym, (cid, case_id, rid, ver, sha) in refs.pins.items():
        x = items[case_id]
        assert x['candidate_id'] == cid and x['lane'] == 'unavailable' and x['research'] is None
        assert x['continuation']['availability'] == 'unavailable' and x['continuation']['action_url'] is None
        assert x['human_action_required'] is False
        assert x['reference'] == {**REFERENCE, 'reports': [{'report_id': rid, 'report_version': ver, 'report_sha256': sha,
                                  'association': 'historical_reference', 'review_state': 'pending_review',
                                  'world_verified': False, 'gate_effect': 'none'}]}
        assert '/4' not in x['routing_rationale']
        single = client.get(f'/scouting/cases/{case_id}').json()
        assert single['reference'] == x['reference'] and single['lane'] == 'unavailable'


def test_reference_reports_are_pending_in_queue_and_never_consumer_visible(refs, monkeypatch):
    items = {(i['report_id'], i['report_version']): i for i in client.get('/web/v1/review-queue').json()['items']}
    for _, _, rid, ver, _ in refs.pins.values():
        assert items[(rid, ver)]['state'] == 'pending_review'
    for policy in ('all', 'approved'):
        monkeypatch.setenv('SCOOBY_REPORT_RELEASE', policy)
        listed = {r['report_id'] for r in client.get('/reports').json()}
        assert not listed & {p[2] for p in refs.pins.values()}


# ---------------------------------------------------------------------------- admin reads
def test_metadata_auth_errors_and_shape(refs):
    _, case_id, rid, ver, sha = refs.pins['FET']
    url = f'/web/v1/admin/reference-reports/{rid}/{ver}'
    assert client.get(url).status_code == 401
    other = session_headers(ISSUER, 'pairwise-sub-case-only', 'case_investigation', label='case-only')
    assert client.get(url, headers=other).status_code == 403
    h = login(client, refs.fw, refs.clock)
    assert client.get('/web/v1/admin/reference-reports/missing/v1', headers=h).status_code == 404
    r = client.get(url, headers=h)
    assert r.status_code == 200, r.text
    m = r.json()
    assert set(m) == {'schema', 'report_id', 'report_version', 'report_sha256', 'case_id', 'candidate_id', 'symbol', 'identity', 'mode',
                      'review_state', 'world_verified', 'gate_effect', 'association', 'labels', 'description', 'pillars', 'files', 'file_base'}
    assert (m['schema'], m['report_sha256'], m['case_id'], m['symbol'], m['mode']) == ('scooby.reference-display/1', sha, case_id, 'FET', 'historical_replay')
    assert (m['review_state'], m['world_verified'], m['gate_effect'], m['association']) == ('pending_review', False, 'none', 'historical_reference')
    assert m['labels'] == ['historical', 'unreviewed', 'synthetic_lineage', 'uncalibrated_var', 'snapshot_expired']
    assert m['description'].startswith('Synthetic FET historical reference') and set(m['pillars']) == set(__import__('store').PILLARS)
    doc = json.loads(client.get(m['file_base'] + 'report.json', headers=h).content)
    expected = {'report.json': sha, **{e['path']: e['sha256'] for e in doc['evidence'] + doc['artifacts'] if e.get('path')}}
    assert m['files'] == expected
    assert m['file_base'] == f'/web/v1/admin/reference-reports/{rid}/{ver}/files/'


def test_per_report_session_is_honoured(refs, monkeypatch):
    _, _, a, va, _ = refs.pins['SHIB']
    _, _, b, vb, _ = refs.pins['GRT']
    h = report_session(refs, refs.pins, 'SHIB')
    assert client.get(f'/web/v1/admin/reference-reports/{a}/{va}', headers=h).status_code == 200
    assert client.get(f'/web/v1/admin/reference-reports/{a}/{va}/files/report.json', headers=h).status_code == 200
    for path in (f'/web/v1/admin/reference-reports/{b}/{vb}', f'/web/v1/admin/reference-reports/{b}/{vb}/files/report.json'):
        r = client.get(path, headers=h)
        assert r.status_code == 403 and 'limited to another report' in r.json()['detail']
    general = login(client, refs.fw, refs.clock)
    monkeypatch.setenv('SCOOBY_REVIEW_PER_REPORT', 'true')
    assert client.get(f'/web/v1/admin/reference-reports/{a}/{va}', headers=general).status_code == 403
    assert client.get(f'/web/v1/admin/reference-reports/{a}/{va}', headers=h).status_code == 200


def test_case_route_with_general_and_per_report_sessions(refs, monkeypatch):
    shib_case, grt_case = refs.pins['SHIB'][1], refs.pins['GRT'][1]
    general = login(client, refs.fw, refs.clock)
    assert client.get(f'/web/v1/admin/cases/{shib_case}/reference-reports').status_code == 401
    r = client.get(f'/web/v1/admin/cases/{shib_case}/reference-reports', headers=general)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body['case_id'], body['candidate_id'], body['association'], body['gate_effect']) == (shib_case, refs.pins['SHIB'][0], 'historical_reference', 'none')
    assert [x['report_sha256'] for x in body['reports']] == [refs.pins['SHIB'][4]]
    assert client.get(f'/web/v1/admin/cases/{plain_case(8)}/reference-reports', headers=general).status_code == 404
    assert client.get(f'/web/v1/admin/cases/{"0" * 64}/reference-reports', headers=general).status_code == 404
    h = report_session(refs, refs.pins, 'SHIB')
    assert client.get(f'/web/v1/admin/cases/{shib_case}/reference-reports', headers=h).json()['reports'][0]['report_id'] == refs.pins['SHIB'][2]
    assert client.get(f'/web/v1/admin/cases/{grt_case}/reference-reports', headers=h).status_code == 403
    monkeypatch.setenv('SCOOBY_REVIEW_PER_REPORT', 'true')
    assert client.get(f'/web/v1/admin/cases/{shib_case}/reference-reports', headers=general).status_code == 403
    assert client.get(f'/web/v1/admin/cases/{shib_case}/reference-reports', headers=h).status_code == 200


def test_file_route_types_headers_and_containment(refs):
    _, _, rid, ver, sha = refs.pins['YFI']
    h = login(client, refs.fw, refs.clock)
    m = client.get(f'/web/v1/admin/reference-reports/{rid}/{ver}', headers=h).json()
    seen = set()
    for path, want in m['files'].items():
        r = client.get(m['file_base'] + path, headers=h)
        assert r.status_code == 200, path
        assert hashlib.sha256(r.content).hexdigest() == want == r.headers['x-file-sha256']
        assert r.headers['x-report-sha256'] == sha
        assert r.headers['x-content-type-options'] == 'nosniff' and r.headers['cache-control'] == 'no-store'
        assert r.headers['content-security-policy'] == "default-src 'none'; sandbox"
        suffix = Path(path).suffix
        assert r.headers['content-type'] == {'.json': 'application/json', '.csv': 'text/csv; charset=utf-8', '.md': 'text/plain; charset=utf-8'}[suffix]
        seen.add(suffix)
    assert {'.json', '.md'} <= seen
    for bad in ('missing.json', 'evidence/..%2F..%2Freport.json', '..%2Freport.json', 'mapping-manifest.json/x'):
        assert client.get(m['file_base'] + bad, headers=h).status_code == 404, bad
    with __import__('store').db() as c:
        path = Path(c.execute('SELECT path FROM reports WHERE id=? AND version=?', (rid, ver)).fetchone()[0])
    victim = next(p for p in m['files'] if p != 'report.json')
    original = (path / victim).read_bytes()
    try:
        (path / victim).write_bytes(original + b' ')
        r = client.get(m['file_base'] + victim, headers=h)
        assert r.status_code == 409 and r.json() == {'detail': 'integrity unavailable'}
        assert client.get(f'/web/v1/admin/reference-reports/{rid}/{ver}', headers=h).status_code == 409
    finally:
        (path / victim).write_bytes(original)


def test_csv_content_type(refs, monkeypatch):
    def with_csv(manifest, members):
        doc = json.loads(members['bundles/spx/report.json'])
        members['bundles/spx/evidence/series.csv'] = b'date,close\n2026-01-01,1.0\n'
        doc['evidence'].append({**doc['evidence'][0], 'id': 'series_csv', 'path': 'evidence/series.csv',
                                'sha256': hashlib.sha256(members['bundles/spx/evidence/series.csv']).hexdigest()})
        raw = json.dumps(doc).encode()
        members['bundles/spx/report.json'] = raw
        manifest['pairs'][2]['report_sha256'] = hashlib.sha256(raw).hexdigest()
    import store
    monkeypatch.setattr(store, 'DB', refs.tmp / 'csv.sqlite3')
    store.init()
    __import__('publication.db', fromlist=['init']).init()
    enroll(ISSUER, ADMIN_SUB, 'report_review', label='admin-1')
    data, sha, pins = fx.build(mutate=with_csv)
    monkeypatch.setattr(reference_seed, 'PINNED_ZIP_SHA256', sha)
    monkeypatch.setattr(reference_seed, 'PINNED_PAIRS', pins)
    reference_seed.restore(data, sha)
    h = login(client, refs.fw, refs.clock)
    _, _, rid, ver, _ = pins['SPX']
    r = client.get(f'/web/v1/admin/reference-reports/{rid}/{ver}/files/evidence/series.csv', headers=h)
    assert r.status_code == 200 and r.headers['content-type'] == 'text/csv; charset=utf-8' and r.content.startswith(b'date,close')


# ---------------------------------------------------------------------------- refusals and display-only
def test_reference_cases_refuse_case_challenges(refs):
    from publication import admin
    with __import__('store').db() as c:
        admin.grant(c, ISSUER, ADMIN_SUB, 'case_investigation', 'test')
    h = login(client, refs.fw, refs.clock)
    for sym in refs.pins:
        case_id = refs.pins[sym][1]
        revision = client.get(f'/scouting/cases/{case_id}').json()['snapshot_digest']
        r = client.post(f'/scouting/cases/{case_id}/challenge', headers={**h, 'Idempotency-Key': 'ref-' + sym},
                        json={'action': 'diagnostic_research', 'expected_revision': revision})
        assert r.status_code == 409 and 'Historical reference' in r.json()['detail']
    with __import__('store').db() as c:
        assert c.execute('SELECT count(*) FROM case_challenges').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0


BLOCKED = [('/investigations', {'candidate_id': 'x', 'selection_id': 'y'}), ('/reference-runs', {'candidate_id': 'x', 'selection_id': 'y'}),
           ('/scans', None), ('/scouting/cases/refresh', {'limit': 1}), ('/reports/a/b/render', None), ('/reports/import', {'run_id': 'r', 'bundle_path': '/x'}),
           ('/investigations/r/resume', None), ('/investigations/r/reason', {'pillar': 'onchain', 'evidence': [{'id': 'e'}]}),
           ('/scouting/cases/' + '0' * 64 + '/challenge', {'expected_revision': '0' * 64}), ('/scouting/challenges/c/continue', None),
           ('/scouting/challenges/c/world-attempt', None)]


def test_display_only_blocks_agent_routes_and_keeps_review(refs, monkeypatch):
    monkeypatch.setenv('SCOOBY_DISPLAY_ONLY', 'true')
    for path, body in BLOCKED:
        r = client.post(path, json=body, headers={'Idempotency-Key': 'k'})
        assert r.status_code == 503 and 'Display-only' in r.json()['detail'], path
    assert client.get('/scouting/world-attempts/a').status_code == 503
    with __import__('store').db() as c:
        assert c.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
    assert client.get('/health').json()['display_only'] is True
    assert client.get('/scouting/cases').status_code == 200 and client.get('/web/v1/review-queue').status_code == 200
    # review desk: per-report session, reads and a World-confirmed sign-off still work and enqueue nothing
    _, case_id, rid, ver, _ = refs.pins['METIS']
    h = report_session(refs, refs.pins, 'METIS')
    assert client.get(f'/web/v1/admin/reference-reports/{rid}/{ver}', headers=h).status_code == 200
    r = decide(refs, h, rid, ver, 'approve', ('success', {}))
    assert r.status_code == 200, r.text
    assert poll(refs, h, r.json()['id'])['status'] == 'confirmed'
    with __import__('store').db() as c:
        assert c.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
    report = client.get(f'/scouting/cases/{case_id}').json()['reference']['reports'][0]
    assert (report['review_state'], report['world_verified']) == ('approved', True)   # a genuine approval shows


def test_display_only_worker_consumes_nothing(refs, monkeypatch):
    import worker
    from store import db, job
    with db() as c:
        job(c, 'scan', 'bounded-empty', 'display-only-scan')
    monkeypatch.setenv('SCOOBY_DISPLAY_ONLY', 'true')
    monkeypatch.setenv('SCOOBY_SCOUT_ENABLED', 'true')
    monkeypatch.setenv('SCOOBY_CASE_SYNC_ENABLED', 'true')
    assert worker.work_one() is False
    assert worker.enqueue_periodic_scout() is None and worker.enqueue_periodic_case_sync() is None
    with db() as c:
        assert [r[0] for r in c.execute('SELECT state FROM jobs')] == ['queued']


def test_start_script_never_starts_worker_in_display_only(tmp_path):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    log = tmp_path / 'calls.log'
    (bindir / 'python').write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    (bindir / 'python').chmod(0o755)
    base = {'PATH': f'{bindir}:/usr/bin:/bin', 'SCOOBY_EMBEDDED_WORKER': 'true'}
    subprocess.run(['sh', str(ROOT / 'ops/start.sh')], env={**base, 'SCOOBY_DISPLAY_ONLY': 'true'}, capture_output=True, timeout=30)
    calls = log.read_text()
    assert 'huey' not in calls and 'uvicorn' in calls and 'seed_on_start' in calls
    log.unlink()
    subprocess.run(['sh', str(ROOT / 'ops/start.sh')], env=base, capture_output=True, timeout=30)
    assert 'huey' in log.read_text()


# ---------------------------------------------------------------------------- startup and /health
def load_seed_on_start():
    import importlib.util
    spec = importlib.util.spec_from_file_location('seed_on_start_ref', ROOT / 'ops' / 'seed_on_start.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_startup_status_is_recorded_and_failures_never_block(refs, monkeypatch, capsys):
    sos = load_seed_on_start()
    for k in ('SCOOBY_SEED_ARCHIVE', 'SCOOBY_REFERENCE_SEED_ARCHIVE', 'SCOOBY_REFERENCE_SEED_URL'):
        monkeypatch.delenv(k, raising=False)
    assert sos.run_reference() == 'not_configured'
    assert client.get('/health').json()['reference_seed'] == {'status': 'not_configured', 'pairs': 0}
    path = refs.tmp / 'reference.zip.b64'
    path.write_bytes(base64.encodebytes(refs.zip))
    monkeypatch.setenv('SCOOBY_REFERENCE_SEED_ARCHIVE', str(path))
    monkeypatch.setenv('SCOOBY_REFERENCE_SEED_SHA256', refs.sha)
    assert sos.run_reference() == 'already_present'          # the fixture already restored it
    assert client.get('/health').json()['reference_seed'] == {'status': 'already_present', 'pairs': 6}
    monkeypatch.setenv('SCOOBY_REFERENCE_SEED_SHA256', 'a' * 64)
    assert sos.main() == 0                                    # a failed reference seed never fails startup
    assert 'reference seed: not imported, nothing written' in capsys.readouterr().out
    health = client.get('/health').json()['reference_seed']
    assert health == {'status': 'failed', 'pairs': 0} and str(path) not in json.dumps(health)


def test_startup_fresh_import_reports_imported(env, monkeypatch, tmp_path):
    import store
    monkeypatch.setattr(store, 'DATA', tmp_path)
    data, sha, pins = fx.build()
    monkeypatch.setattr(reference_seed, 'PINNED_ZIP_SHA256', sha)
    monkeypatch.setattr(reference_seed, 'PINNED_PAIRS', pins)
    path = tmp_path / 'reference.zip'
    path.write_bytes(data)
    monkeypatch.delenv('SCOOBY_REFERENCE_SEED_URL', raising=False)
    monkeypatch.setenv('SCOOBY_REFERENCE_SEED_ARCHIVE', str(path))
    monkeypatch.setenv('SCOOBY_REFERENCE_SEED_SHA256', sha)
    assert load_seed_on_start().run_reference() == 'imported'
    assert client.get('/health').json()['reference_seed'] == {'status': 'imported', 'pairs': 6}


# ---------------------------------------------------------------------------- URL input
def url_env(monkeypatch, sha, url='https://storage.example/seed.zip', header=None):
    monkeypatch.delenv('SCOOBY_REFERENCE_SEED_ARCHIVE', raising=False)
    monkeypatch.setenv('SCOOBY_REFERENCE_SEED_URL', url)
    monkeypatch.setenv('SCOOBY_REFERENCE_SEED_SHA256', sha)
    if header:
        monkeypatch.setenv('SCOOBY_REFERENCE_SEED_AUTH_HEADER', header)
    else:
        monkeypatch.delenv('SCOOBY_REFERENCE_SEED_AUTH_HEADER', raising=False)


def test_url_fetch_single_get_with_auth_then_pinned_check(env, monkeypatch, tmp_path):
    import store
    monkeypatch.setattr(store, 'DATA', tmp_path)
    data, sha, pins = fx.build()
    monkeypatch.setattr(reference_seed, 'PINNED_ZIP_SHA256', sha)
    monkeypatch.setattr(reference_seed, 'PINNED_PAIRS', pins)
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url), request.headers.get('authorization')))
        return httpx.Response(200, content=data)
    url_env(monkeypatch, sha, header='Authorization: Bearer test-token')
    assert reference_seed.run_from_env(transport=httpx.MockTransport(handler))['pairs'] == 6
    assert seen == [('GET', 'https://storage.example/seed.zip', 'Bearer test-token')]
    assert not [p for p in tmp_path.iterdir() if p.name.startswith('reference-seed-fetch-')]


@pytest.mark.parametrize('response, match', [
    (httpx.Response(302, headers={'location': 'https://elsewhere.example/seed.zip'}), 'HTTP 302'),
    (httpx.Response(403), 'HTTP 403'),
    (httpx.Response(200, content=b'PK\x03\x04' + b'0' * 100), 'SHA-256'),
    (httpx.Response(200, content=b'x' * (reference_seed.FETCH_MAX + 1)), 'size limit'),
])
def test_url_fetch_failures_write_nothing(env, monkeypatch, tmp_path, response, match):
    import store
    monkeypatch.setattr(store, 'DATA', tmp_path)
    data, sha, pins = fx.build()
    monkeypatch.setattr(reference_seed, 'PINNED_ZIP_SHA256', sha)
    monkeypatch.setattr(reference_seed, 'PINNED_PAIRS', pins)
    url_env(monkeypatch, sha)
    calls = []

    def handler(request):
        calls.append(request)
        return response
    with pytest.raises(reference_seed.ReferenceSeedError, match=match):
        reference_seed.run_from_env(transport=httpx.MockTransport(handler))
    assert len(calls) == 1
    with store.db() as c:
        assert c.execute('SELECT count(*) FROM reports').fetchone()[0] == 0


@pytest.mark.parametrize('settings, match', [
    ({'SCOOBY_REFERENCE_SEED_URL': 'http://storage.example/seed.zip'}, 'https'),
    ({'SCOOBY_REFERENCE_SEED_URL': 'https://user:pw@storage.example/seed.zip'}, 'https'),
    ({'SCOOBY_REFERENCE_SEED_URL': 'https://s.example/x', 'SCOOBY_REFERENCE_SEED_ARCHIVE': '/x'}, 'not both'),
    ({'SCOOBY_REFERENCE_SEED_URL': 'https://s.example/x', 'SCOOBY_REFERENCE_SEED_AUTH_HEADER': 'no colon'}, 'Name: value'),
    ({'SCOOBY_REFERENCE_SEED_ARCHIVE': '/x', 'SCOOBY_REFERENCE_SEED_AUTH_HEADER': 'A: b'}, 'needs SCOOBY_REFERENCE_SEED_URL'),
])
def test_url_settings_are_validated(monkeypatch, settings, match):
    for k in ('SCOOBY_REFERENCE_SEED_URL', 'SCOOBY_REFERENCE_SEED_ARCHIVE', 'SCOOBY_REFERENCE_SEED_AUTH_HEADER'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv('SCOOBY_REFERENCE_SEED_SHA256', 'a' * 64)
    for k, v in settings.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(reference_seed.ReferenceSeedError, match=match):
        reference_seed.settings()
