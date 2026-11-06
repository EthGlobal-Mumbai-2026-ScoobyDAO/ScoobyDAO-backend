"""Offline regressions for grounding problems observed in a real SHIB completion."""
import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from modules.investigation.case_research import run_case
from modules.investigation.model_reasoning import GroundingError, _context, _numbers, _validate, _verified_legacy_math
from test_case_research import ADDR, case, captured_snapshot, source_payloads
from test_case_terra_reasoning import FakeClient, generated


def test_provider_facts_are_projected_with_attribution_and_exact_decimal_strings(tmp_path):
    payloads = source_payloads()
    payloads['source']['verifiedAt'] = '2025-06-23T09:01:15Z'
    payloads['market'][0].update(priceUsd='0.000004574', txns={'h24': {'buys': 126, 'sells': 102}}, priceChange={'h24': -3.34})
    payloads['security']['result'][ADDR].update(
        dex=[{'pair': '0x' + 'ab' * 32, 'pool_fee': '0.99', 'liquidity': '81.544750880256000000000000000000'}],
        holders=[{'address': '0x' + 'cd' * 20, 'percent': '0.410444370884330485', 'tag': 'Dead', 'is_locked': 1}])
    output = tmp_path / 'out'
    run_case(case('automatic_policy'), output, captured_snapshot=captured_snapshot(payloads), max_source_requests=0)
    report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    micro = report['pillars']['microstructure']; chain = report['pillars']['onchain']
    pool = next(x for x in micro['claims'] if x['id'] == 'provider-pool-1')
    holder = next(x for x in chain['claims'] if x['id'] == 'provider-holder-1')
    assert '0.99' in pool['statement'] and '81.544750880256000000000000000000' in pool['statement']
    assert pool['supporting_evidence_ids'] == ['security'] and 'independent' in pool['uncertainties'][0]
    assert '0.410444370884330485' in holder['statement'] and 'ownership' in holder['uncertainties'][0]
    assert any(x['id'] == 'source-verified-at' and '2025-06-23' in x['statement'] for x in chain['claims'])
    assert {'price_usd', 'provider_24h_buys', 'provider_24h_sells', 'provider_price_change_24h'} <= {x['id'] for x in micro['measurements']}


def test_cross_pillar_context_must_have_a_local_anchor_and_linked_evidence(tmp_path):
    output = tmp_path / 'out'
    run_case(case('automatic_policy'), output, captured_snapshot=captured_snapshot(source_payloads()), max_source_requests=0)
    report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    payload = generated({'pillars': report['pillars']})
    para = next(x for x in payload['pillars'] if x['name'] == 'microstructure')['analysis'][0]
    para['input_ids'].append('provider-is_open_source'); para['evidence_ids'].append('security')
    _validate(report, copy.deepcopy(payload), {}, '')
    para['input_ids'] = ['provider-is_open_source']; para['evidence_ids'] = ['security']
    with pytest.raises(GroundingError, match='at least one local'):
        _validate(report, copy.deepcopy(payload), {}, '')
    para['input_ids'] = ['market-pool']; para['evidence_ids'] = ['market', 'security']
    with pytest.raises(GroundingError, match='evidence lacks a cited input: security'):
        _validate(report, copy.deepcopy(payload), {}, '')
    para['input_ids'] = []
    with pytest.raises(GroundingError, match='cite structured input'):
        _validate(report, copy.deepcopy(payload), {}, '')


def test_formatted_numbers_and_confidence_labels_but_not_invented_values(tmp_path):
    assert _numbers('liquidity $2,531,199.99') == _numbers('2531199.99')
    assert _numbers('2025-06-23') <= _numbers('2025-06-23T09:01:15Z')
    output = tmp_path / 'out'
    run_case(case('automatic_policy'), output, captured_snapshot=captured_snapshot(source_payloads()), max_source_requests=0)
    report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    micro = report['pillars']['microstructure']
    micro['measurements'][0]['value'] = 2531199.99
    measurement = copy.deepcopy(micro['measurements'][0]); measurement.update(id='legacy_var_metrics_var_90', value=0.9515)
    micro['measurements'].append(measurement)
    payload = generated({'pillars': report['pillars']})
    para = next(x for x in payload['pillars'] if x['name'] == 'microstructure')['analysis'][0]
    para['text'] = 'SYNTHETIC: Liquidity 2,531,199.99 and legacy VaR 0.9515 at level 90.'
    _validate(report, copy.deepcopy(payload), {}, '')
    para['text'] += ' Invented amount 87654321.'
    with pytest.raises(GroundingError, match='87654321'):
        _validate(report, copy.deepcopy(payload), {}, '')


def test_legacy_math_requires_bound_manifest_and_exactly_fifty_series(tmp_path):
    def save(name, content):
        path = tmp_path / name; path.write_bytes(content)
        return {'id': name, 'path': name, 'sha256': hashlib.sha256(content).hexdigest()}
    candidate = '1:0x' + '12' * 20
    candles = save('candles', b'{}')
    metrics = save('vae_metrics', json.dumps({'identity': candidate}).encode())
    rows = ','.join(['date'] + [f'recon{i}' for i in range(50)]) + '\n' + ','.join(['2026-01-01'] + ['0.1'] * 50) + '\n'
    series = save('vae_reconstructions', rows.encode())
    manifest = save('vae_manifest', json.dumps({'candidate_id': candidate, 'reconstructions': 50, 'return_rows': 1,
        'source_candles_sha256': candles['sha256'], 'metrics_sha256': metrics['sha256'], 'reconstructions_sha256': series['sha256']}).encode())
    report = {'candidate_id': candidate, 'evidence': [candles, metrics, series, manifest]}
    assert _verified_legacy_math(report, tmp_path)
    report['candidate_id'] = '1:0x' + '34' * 20
    assert not _verified_legacy_math(report, tmp_path)
    report['candidate_id'] = candidate
    (tmp_path / 'vae_reconstructions').write_text('date,x\n2026-01-01,1\n', encoding='utf-8')
    assert not _verified_legacy_math(report, tmp_path)


def test_invalid_numeric_response_reports_actionable_bounded_detail(tmp_path):
    def mutate(payload):
        payload['conclusion']['summary'] = 'Unsupported amount 987654321.'
    events = []
    result = run_case(case('automatic_policy'), tmp_path / 'out', captured_snapshot=captured_snapshot(source_payloads()),
                      max_model_calls=1, model_client=FakeClient(mutate=mutate), stage_callback=events.append)
    assert result['model_status'] == 'failed_invalid_or_unlinked_output'
    assert '987654321' in result['model_detail']
    failure = next(e for e in events if e['stage'] == 'reasoning' and e['state'] == 'failed')
    assert failure['detail'] == result['model_detail'] and len(failure['detail']) <= 500
