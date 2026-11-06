"""Synthetic case-to-report tests; all providers are mocked and no model is called."""
import csv
import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from modules.investigation.case_research import run_case
from modules.investigation.contract_validate import verify_digest

ADDR = '0x' + '12' * 20
POOL = '0x' + '34' * 20
CANDIDATE = '1:' + ADDR


def source_payloads():
    today = datetime.now(timezone.utc).date()
    rows = [[int(datetime.combine(today - timedelta(days=i), datetime.min.time(), timezone.utc).timestamp()),
             1, 2, 0.9, 1 + (3-i) * .1, 100] for i in (3, 2, 1)]
    return {
        'market': [{'chainId': 'ethereum', 'pairAddress': POOL, 'baseToken': {'address': ADDR, 'symbol': 'SYNTH'},
                    'liquidity': {'usd': 700}, 'volume': {'h24': 1200}}],
        'security': {'result': {ADDR: {'is_open_source': '1', 'is_honeypot': '0'}}},
        'source': {'chainId': '1', 'address': ADDR, 'runtimeMatch': 'match'},
        'pools': {'data': [{'attributes': {'address': POOL}, 'relationships': {
            'base_token': {'data': {'id': 'eth_' + ADDR}}, 'quote_token': {'data': {'id': 'eth_0x' + '56' * 20}}}}]},
        'daily': {'data': {'attributes': {'ohlcv_list': rows}}},
    }


def mock_provider(payloads, calls):
    def send(request):
        calls.append(request)
        path = request.url.path
        if 'dexscreener' in request.url.host: name = 'market'
        elif 'gopluslabs' in request.url.host: name = 'security'
        elif 'sourcify' in request.url.host: name = 'source'
        elif '/ohlcv/day' in path: name = 'daily'
        else: name = 'pools'
        return httpx.Response(200, content=json.dumps(payloads[name]).encode(), headers={'content-type': 'application/json'})
    return httpx.MockTransport(send)


def case(route, suffix='1'):
    return {'case_id': 'case' + suffix, 'run_id': 'run' + suffix, 'candidate_id': CANDIDATE,
            'mode': 'synthetic_demo', 'authorization': {'route': route, 'reference_id': 'auth' + suffix}}


@pytest.mark.parametrize('route', ['automatic_policy', 'world_confirmed'])
def test_both_authorized_routes_produce_valid_pillar_bundle(tmp_path, route):
    calls = []; output = tmp_path / route
    result = run_case(case(route), output, max_source_requests=5, transport=mock_provider(source_payloads(), calls))
    assert len(calls) == 5 and result['state'] == 'partial'
    assert result['pillar_status']['microstructure'] == result['pillar_status']['onchain'] == 'partial'
    assert result['pillar_status']['fundamentals'] == result['pillar_status']['technical_health'] == 'partial'
    assert result['pillar_status']['statistical_risk'] == 'unavailable'
    report = verify_digest(output, result['report_sha256'])
    assert report['candidate_id'] == CANDIDATE and report['mode'] == 'synthetic_demo'
    series = {x['id']: x for x in report['pillars']['technical_health']['series']}
    assert len(series['observed_daily_closes']['points']) == 3
    assert len(series['observed_daily_returns']['points']) == 2
    assert report['review']['status'] == 'pending' and report['assessment']['status'] == 'not_assessed'
    reader_path = Path(__file__).resolve().parents[1] / 'vendor' / 'reader' / 'build.py'
    spec = importlib.util.spec_from_file_location('case_research_reader', reader_path)
    reader = importlib.util.module_from_spec(spec); spec.loader.exec_module(reader)
    reader.build(output / 'report.json', tmp_path / ('html-' + route))
    assert (tmp_path / ('html-' + route) / 'index.html').is_file()
    lineage = json.loads((output / 'case-lineage.json').read_text())
    assert lineage['authorization_route'] == route and lineage['case_id'] == 'case1'
    with pytest.raises(ValueError, match='already exists'):
        run_case(case(route), output, max_source_requests=0)


def test_no_budget_failed_sources_and_cancellation_do_not_fake_completed_report(tmp_path):
    result = run_case(case('automatic_policy'), tmp_path / 'none', max_source_requests=0,
                      transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError('no request allowed'))))
    assert result['state'] == 'blocked' and result['reason'] == 'no_identity_bound_source_evidence'
    assert not (tmp_path / 'none').exists()
    result = run_case(case('automatic_policy'), tmp_path / 'fail', max_source_requests=2,
                      transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    assert result['state'] == 'blocked' and len(result['source_attempts']) == 2
    result = run_case(case('world_confirmed'), tmp_path / 'cancel', max_source_requests=5,
                      cancelled=lambda: True, transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    assert result['state'] == 'cancelled' and not (tmp_path / 'cancel').exists()


def test_one_source_failure_preserves_other_pillars_and_retry_isolated(tmp_path):
    payloads = source_payloads(); calls = []; base = mock_provider(payloads, calls)
    def failing_security(request):
        if 'gopluslabs' in request.url.host:
            calls.append(request); return httpx.Response(503)
        return base.handle_request(request)
    first = run_case(case('automatic_policy'), tmp_path / 'attempt1', max_source_requests=5,
                     transport=httpx.MockTransport(failing_security))
    report = verify_digest(tmp_path / 'attempt1', first['report_sha256'])
    assert first['state'] == 'partial' and report['pillars']['technical_health']['status'] == 'partial'
    assert any(x['name'] == 'security' and x['status'] == 'unavailable' for x in first['source_attempts'])
    assert 'security' not in {x['id'] for x in report['evidence']}
    retry = run_case(case('automatic_policy', '2'), tmp_path / 'attempt2', max_source_requests=5,
                     transport=mock_provider(payloads, []))
    assert retry['report_id'] != first['report_id'] and retry['state'] == 'partial'
    assert verify_digest(tmp_path / 'attempt1', first['report_sha256'])['report_version'] == first['report_version']


def test_malformed_provider_fields_do_not_erase_other_evidence(tmp_path):
    payloads = source_payloads()
    payloads['market'] = [{'chainId': 'ethereum', 'baseToken': None}]
    payloads['pools'] = {'data': [{'relationships': None}]}
    result = run_case(case('automatic_policy'), tmp_path / 'partial', max_source_requests=5,
                      transport=mock_provider(payloads, []))
    assert result['state'] == 'partial' and result['pillar_status']['onchain'] == 'partial'
    assert result['pillar_status']['microstructure'] == 'unavailable'
    assert 'no_identity_matched_pool' in result['limitations']
    with pytest.raises(ValueError, match='requires injected source transport'):
        run_case(case('automatic_policy', '2'), tmp_path / 'bad', max_source_requests=1)


def test_wrong_identity_and_missing_authorization_are_rejected_before_network(tmp_path):
    with pytest.raises(ValueError, match='authorization'):
        run_case({**case('automatic_policy'), 'authorization': {}}, tmp_path / 'a', max_source_requests=5)
    with pytest.raises(ValueError, match='canonical'):
        run_case({**case('automatic_policy'), 'candidate_id': '1:' + ADDR.upper()}, tmp_path / 'b')
    payloads = source_payloads(); payloads['market'][0]['baseToken']['address'] = '0x' + 'ab' * 20
    payloads['security'] = {'result': {}}; payloads['source']['address'] = '0x' + 'ab' * 20
    payloads['pools'] = {'data': []}; calls = []
    result = run_case(case('automatic_policy'), tmp_path / 'c', max_source_requests=5, transport=mock_provider(payloads, calls))
    assert result['state'] == 'blocked' and not (tmp_path / 'c').exists()


def test_legacy_metrics_require_exact_candidate_candles_and_50_reconstructions(tmp_path):
    payloads = source_payloads(); daily_sha = hashlib.sha256(json.dumps(payloads['daily']).encode()).hexdigest()
    model = tmp_path / 'model'; (model / 'output' / 'vae').mkdir(parents=True)
    metrics = {'identity': CANDIDATE, 'risk_assessment': {'var_95': 0.12, 'label': 'legacy risk'},
               'technical_health': {'score': 70}, 'technical_series': {'dates': [], 'score': []}}
    metric_bytes = json.dumps(metrics).encode(); (model / 'legacy-metrics.json').write_bytes(metric_bytes)
    series = model / 'output' / 'vae' / 'VAE_TOKEN.csv'
    with series.open('w', newline='') as f:
        writer = csv.writer(f); writer.writerow(['datetime'] + ['sample' + str(i) for i in range(50)])
        writer.writerow(['2020-01-01'] + [0.1] * 50)
    manifest = {'candidate_id': CANDIDATE, 'source_candles_sha256': daily_sha, 'reconstructions': 50,
                'metrics_sha256': hashlib.sha256(metric_bytes).hexdigest(), 'reconstructions_sha256': hashlib.sha256(series.read_bytes()).hexdigest()}
    (model / 'run-manifest.json').write_text(json.dumps(manifest))
    result = run_case(case('automatic_policy'), tmp_path / 'valid', max_source_requests=5,
                      transport=mock_provider(payloads, []), legacy_model_dir=model)
    report = verify_digest(tmp_path / 'valid', result['report_sha256'])
    assert result['pillar_status']['statistical_risk'] == 'partial'
    assert any(m['value'] == .12 for m in report['pillars']['statistical_risk']['measurements'])
    assert any(e['id'] == 'legacy_reconstructions' for e in report['evidence'])
    manifest['reconstructions'] = 49; (model / 'run-manifest.json').write_text(json.dumps(manifest))
    rejected = run_case(case('automatic_policy', '2'), tmp_path / 'invalid', max_source_requests=5,
                        transport=mock_provider(payloads, []), legacy_model_dir=model)
    assert rejected['pillar_status']['statistical_risk'] == 'unavailable'
    assert 'legacy_50_reconstruction_evidence_rejected' in rejected['limitations']


def test_original_legacy_pillar_scores_keep_exact_values_and_cited_inputs(tmp_path):
    fixture_dir = Path(__file__).resolve().parents[1] / 'modules' / 'investigation' / 'legacy_source_port' / 'fixtures'
    captures = tmp_path / 'captures'; captures.mkdir(); records = {}
    for name, filename in [('microstructure', 'market.json'), ('onchain', 'onchain.json')]:
        doc = json.loads((fixture_dir / filename).read_text())
        if name == 'microstructure': doc['pair']['base'] = ADDR
        else: doc['token'] = ADDR
        raw = json.dumps(doc).encode(); (captures / filename).write_bytes(raw)
        records[name] = {'id': 'fixture-' + name, 'path': filename, 'candidate_id': CANDIDATE, 'sha256': hashlib.sha256(raw).hexdigest()}
    result = run_case(case('automatic_policy'), tmp_path / 'with-legacy', max_source_requests=0,
                      legacy_capture_root=captures, legacy_records=records)
    assert result['state'] == 'partial'
    report = verify_digest(tmp_path / 'with-legacy', result['report_sha256'])
    vals = {x['id']: x['value'] for p in report['pillars'].values() for x in p['measurements']}
    assert vals['legacy_microstructure_score'] == 7 and vals['legacy_fundamentals_score'] == 85
    assert {'legacy_microstructure_input', 'legacy_onchain_input'} <= {e['id'] for e in report['evidence']}
    (captures / 'onchain.json').write_text('{}')
    blocked = run_case(case('automatic_policy', '2'), tmp_path / 'tampered', max_source_requests=0,
                       legacy_capture_root=captures, legacy_records=records)
    assert blocked['state'] == 'blocked' and not (tmp_path / 'tampered').exists()


def test_configured_vae_runner_receives_bound_history_and_explicit_horizon(tmp_path):
    invoked = []
    def fake_vae(source_dir, output_dir, days, legacy_repo):
        invoked.append((days, str(legacy_repo)))
        status = json.loads((source_dir / 'source-status.json').read_bytes())
        assert status['candidate_id'] == CANDIDATE
        data = json.loads((source_dir / 'returns.json').read_bytes())
        assert len(data['returns']) == 2 and not data['gaps']
        output_dir.mkdir(); (output_dir / 'output' / 'vae').mkdir(parents=True)
        metrics = {'identity': CANDIDATE, 'risk_assessment': {'var_95': .2},
                   'technical_health': {'score': 66}, 'technical_series': {'dates': [], 'score': []}}
        raw = json.dumps(metrics).encode(); (output_dir / 'legacy-metrics.json').write_bytes(raw)
        series = output_dir / 'output' / 'vae' / 'VAE_TOKEN.csv'
        with series.open('w', newline='') as f:
            writer = csv.writer(f); writer.writerow(['datetime'] + [f's{i}' for i in range(50)])
            writer.writerow(['2020-01-01'] + [.1] * 50)
        manifest = {'candidate_id': CANDIDATE, 'reconstructions': 50,
                    'source_candles_sha256': hashlib.sha256((source_dir / 'daily.json').read_bytes()).hexdigest(),
                    'metrics_sha256': hashlib.sha256(raw).hexdigest(), 'reconstructions_sha256': hashlib.sha256(series.read_bytes()).hexdigest()}
        (output_dir / 'run-manifest.json').write_text(json.dumps(manifest))
    result = run_case(case('world_confirmed'), tmp_path / 'from-runner', max_source_requests=5,
                      transport=mock_provider(source_payloads(), []), vae_config={'legacy_repo': tmp_path, 'days': 4}, vae_runner=fake_vae)
    assert invoked == [(4, str(tmp_path))] and result['pillar_status']['statistical_risk'] == 'partial'
    report = verify_digest(tmp_path / 'from-runner', result['report_sha256'])
    assert any(x['value'] == .2 for x in report['pillars']['statistical_risk']['measurements'])
    with pytest.raises(ValueError, match='explicit positive horizon'):
        run_case(case('automatic_policy'), tmp_path / 'bad', vae_config={'legacy_repo': tmp_path})


def test_gapped_history_does_not_invoke_vae_or_fabricate_risk(tmp_path):
    payloads = source_payloads(); payloads['daily']['data']['attributes']['ohlcv_list'].pop(1)
    result = run_case(case('automatic_policy'), tmp_path / 'gapped', max_source_requests=5,
                      transport=mock_provider(payloads, []), vae_config={'legacy_repo': tmp_path, 'days': 4},
                      vae_runner=lambda *_: (_ for _ in ()).throw(AssertionError('must not run')))
    assert result['pillar_status']['statistical_risk'] == 'unavailable'
    assert 'legacy_vae_pending_insufficient_or_gapped_history' in result['limitations']


@pytest.mark.parametrize('route', ['automatic_policy', 'world_confirmed'])
def test_generated_bundle_imports_into_existing_report_library_and_renders(tmp_path, route):
    # This exercises the current backend importer/worker with a synthetic diagnostic
    # selection. It does not pretend that the backend already implements case policy
    # or verifies a real World confirmation.
    from fastapi.testclient import TestClient
    from app import app
    from worker import work_one
    client = TestClient(app)
    fixture = json.loads((Path(__file__).parent / 'candidate.json').read_text(encoding='utf-8-sig'))
    fixture['candidate_id'] = CANDIDATE
    fixture['identity'].update(chain_id=1, address=ADDR, symbol='SYNTH')
    fixture['mode'] = 'synthetic_demo'
    assert client.post('/candidates', json={'payload': fixture}).status_code == 200
    selected = client.post('/candidates/' + CANDIDATE + '/selection',
        json={'kind': 'diagnostic_exception', 'actor': 'synthetic test', 'reason': 'component integration only'},
        headers={'Idempotency-Key': 'case-producer-selection-' + route})
    assert selected.status_code == 200
    response = client.post('/investigations', json={'candidate_id': CANDIDATE, 'selection_id': selected.json()['id']},
                           headers={'Idempotency-Key': 'case-producer-run-' + route})
    assert response.status_code == 200
    run_id = response.json()['id']
    request_case = {'case_id': 'integration_' + route, 'run_id': run_id, 'candidate_id': CANDIDATE,
                    'mode': 'synthetic_demo', 'authorization': {'route': route, 'reference_id': 'synthetic_not_world'}}
    produced = run_case(request_case, tmp_path / route, max_source_requests=5,
                        transport=mock_provider(source_payloads(), []))
    imported = client.post('/reports/import', json={'run_id': run_id, 'bundle_path': produced['bundle_path']})
    assert imported.status_code == 200, imported.text
    assert imported.json()['sha256'] == produced['report_sha256']
    path = '/reports/' + produced['report_id'] + '/' + produced['report_version']
    rendered = client.post(path + '/render', json={}, headers={'Idempotency-Key': 'case-producer-render-' + route})
    assert rendered.status_code == 200
    job_id = rendered.json()['job_id']
    for _ in range(6):
        if client.get('/jobs/' + job_id).json()['state'] == 'done':
            break
        assert work_one()
    assert client.get('/jobs/' + job_id).json()['state'] == 'done'
    assert client.get('/artifacts/' + job_id + '/index.html').status_code == 200
    assert any(x['report_sha256'] == produced['report_sha256'] for x in client.get('/reports').json())
