"""Synthetic OpenAI-client tests; never send a live model request."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.investigation.case_research import run_case
from modules.investigation.contract_validate import verify_digest
from modules.investigation.model_reasoning import MODEL, SCHEMA, StagePersistenceError, _validate, _context
from modules.investigation.reasoning_v2.validator import validate_bundle
from test_case_research import case, captured_snapshot, mock_provider, source_payloads


def generated(context):
    sections = []
    cited = []
    for name, p in context['pillars'].items():
        items = p['claims'] + p['measurements'] + p['series']
        if p['status'] in ('partial', 'complete') and items:
            item = items[0]
            evidence = item.get('evidence_ids', item.get('supporting_evidence_ids', []))
            para = {'text': 'SYNTHETIC: The observed source supports a limited scoped finding.',
                    'evidence_ids': [evidence[0]], 'input_ids': [item['id']]}
            cited.append((name, item, evidence[0]))
        else:
            para = {'text': 'SYNTHETIC: No source evidence is available.', 'evidence_ids': [], 'input_ids': []}
        sections.append({'name': name, 'summary': 'SYNTHETIC: A source observation requires contextual review.',
                         'analysis': [para], 'limitations': ['SYNTHETIC: The source has limited coverage.'],
                         'questions': ['SYNTHETIC: What independent evidence would change this view?']})
    _, item, evidence_id = cited[0]
    paragraph = {'text': 'SYNTHETIC: The cited observation supports a scoped review.', 'evidence_ids': [evidence_id], 'input_ids': [item['id']]}
    _, other, other_evidence = cited[1] if len(cited) > 1 else cited[0]
    second = {'text': 'SYNTHETIC: Another pillar adds separate source context.', 'evidence_ids': [other_evidence], 'input_ids': [other['id']]}
    claims = [x['id'] for p in context['pillars'].values() for x in p['claims']]
    return {'pillars': sections, 'conclusion': {'label': 'SYNTHETIC research judgment',
        'summary': 'SYNTHETIC: Review the observed exposure before proceeding.', 'analysis': [copy.deepcopy(paragraph), second],
        'unknowns': ['SYNTHETIC: Current execution and controller state require verification.'],
        'supporting_claim_ids': claims[:1], 'counterevidence_claim_ids': [],
        'recommendation': {'action': 'SYNTHETIC: Defer interaction pending targeted verification.',
            'rationale': copy.deepcopy(paragraph), 'counterevidence': [copy.deepcopy(paragraph)],
            'reversal_conditions': ['SYNTHETIC: Independent evidence resolves the material exposure.']}}}


class FakeClient:
    def __init__(self, mutate=None, finish='stop', refusal=None, after=None, response_model=MODEL):
        self.calls = []; self.mutate = mutate; self.finish = finish; self.refusal = refusal; self.after = after
        self.response_model = response_model
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = generated(json.loads(kwargs['messages'][1]['content']))
        if self.mutate:
            self.mutate(payload)
        if self.after:
            self.after()
        return SimpleNamespace(model=self.response_model, usage=SimpleNamespace(prompt_tokens=400, completion_tokens=250, total_tokens=650),
            choices=[SimpleNamespace(finish_reason=self.finish, message=SimpleNamespace(content=json.dumps(payload), refusal=self.refusal))])


def bundle(tmp_path, client, events, **kwargs):
    return run_case(case('automatic_policy'), tmp_path, max_source_requests=0,
                    captured_snapshot=captured_snapshot(source_payloads()), max_model_calls=1,
                    model_client=client, stage_callback=events.append, **kwargs)


def test_terra_call_produces_valid_reasoning_tldr_irc_and_reader_html(tmp_path):
    client = FakeClient(); events = []
    result = bundle(tmp_path / 'report', client, events)
    assert result['state'] == 'partial' and result['model_status'] == 'completed' and result['model_calls'] == 1
    assert result['model_usage'] == {'prompt_tokens': 400, 'completion_tokens': 250, 'total_tokens': 650}
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call['model'] == 'gpt-6.1-terra' and call['max_completion_tokens'] == 4096
    assert call['response_format']['json_schema']['strict'] is True
    assert call['response_format']['json_schema']['schema'] == SCHEMA and 'tools' not in call
    assert 'untrusted data' in call['messages'][0]['content'].lower()
    report = verify_digest(tmp_path / 'report', result['report_sha256'])
    _, reasoning = validate_bundle(tmp_path / 'report')
    assert report['assessment']['status'] == 'proposed' and len(reasoning['pillars']) == 5
    assert report['pillars']['statistical_risk']['status'] == 'unavailable'
    risk = next(p for p in reasoning['pillars'] if p['name'] == 'statistical_risk')
    assert risk['summary'] == report['pillars']['statistical_risk']['summary']
    assert risk['analysis'][0]['evidence_ids'] == []
    assert any(m['value'] == 700 for m in report['pillars']['microstructure']['measurements'])
    assert {'reasoning', 'pillar_irc', 'pillar_tldr'} <= {a['kind'] for a in report['artifacts']}
    tldr = json.loads((tmp_path / 'report' / 'pillar-tldr.json').read_text(encoding='utf-8'))
    micro = tldr['pillars']['microstructure']
    assert next(x['text'] for x in micro if x['role'] == 'finding') == report['pillars']['microstructure']['claims'][0]['statement']
    assert all('SYNTHETIC:' not in x['text'] for x in micro if x['role'] == 'finding')
    assert any(x['role'] == 'interpretation' and 'SYNTHETIC:' in x['text'] for x in micro)
    assert any(e['stage'] == 'reasoning' and e['state'] == 'completed' and 'checkpoint' in e for e in events)
    assert len([e for e in events if e['stage'] == 'pillar']) == 5
    text = (tmp_path / 'report' / 'report.md').read_text(encoding='utf-8')
    assert 'Proposed conclusion' in text and 'Proposed analysis' in text
    reader_path = Path(__file__).resolve().parents[1] / 'vendor' / 'reader' / 'build.py'
    spec = importlib.util.spec_from_file_location('model_case_reader', reader_path)
    reader = importlib.util.module_from_spec(spec); spec.loader.exec_module(reader)
    reader.build(tmp_path / 'report' / 'report.json', tmp_path / 'html')
    assert (tmp_path / 'html' / 'index.html').is_file()


@pytest.mark.parametrize('failure', ['bad_ref', 'bad_number', 'wrong_pillar', 'single_pillar', 'schema', 'refusal', 'truncated', 'wrong_model'])
def test_invalid_or_refused_model_never_becomes_proposed_assessment(tmp_path, failure):
    def mutate(p):
        if failure == 'bad_ref': p['conclusion']['recommendation']['rationale']['evidence_ids'] = ['invented']
        if failure == 'bad_number': p['conclusion']['summary'] = 'The token has 987654321 unique holders.'
        if failure == 'wrong_pillar':
            p['pillars'][0]['analysis'][0]['input_ids'] = ['provider-is_open_source']
            p['pillars'][0]['analysis'][0]['evidence_ids'] = ['security']
        if failure == 'single_pillar': p['conclusion']['analysis'] = [copy.deepcopy(p['conclusion']['recommendation']['rationale'])]
        if failure == 'schema': p['conclusion'].pop('recommendation')
    client = FakeClient(mutate=mutate, refusal='refused' if failure == 'refusal' else None,
                        finish='length' if failure == 'truncated' else 'stop',
                        response_model='gpt-6.1-terra-resolved-unknown' if failure == 'wrong_model' else MODEL)
    events = []; result = bundle(tmp_path / failure, client, events)
    expected = {'refusal': 'failed_refused', 'truncated': 'failed_incomplete_output',
                'wrong_model': 'failed_model_identifier_mismatch'}.get(failure, 'failed_invalid_or_unlinked_output')
    assert result['model_status'] == expected and result['model_calls'] == 1
    assert result['model_usage']['total_tokens'] == 650
    assert next(e for e in events if e['stage'] == 'reasoning' and e['state'] == 'failed')['usage']['total_tokens'] == 650
    report = verify_digest(tmp_path / failure, result['report_sha256'])
    assert report['assessment']['status'] == 'not_assessed'
    assert not any(a['kind'] == 'reasoning' for a in report['artifacts'])
    assert len(client.calls) == 1


def test_known_counterevidence_must_be_cited():
    path = Path(__file__).parent / 'fixtures' / 'reasoning_v2' / 'v1' / 'report.json'
    report = json.loads(path.read_text(encoding='utf-8'))
    payload = generated({'pillars': report['pillars']})
    with pytest.raises(ValueError, match='known counterevidence'):
        _validate(report, payload, {}, '')
    payload['conclusion']['recommendation']['counterevidence'] = [{'text': 'SYNTHETIC: Contrary evidence is present.',
        'evidence_ids': ['test-b'], 'input_ids': ['microstructure-claim']}]
    assert _validate(report, payload, {}, '')['profile'] == 'scooby.reasoning/2'


def test_context_budget_fairly_includes_escaped_sources(tmp_path):
    path = Path(__file__).parent / 'fixtures' / 'reasoning_v2' / 'v1' / 'report.json'
    report = json.loads(path.read_text(encoding='utf-8')); template = report['evidence'][0]
    records = []
    for name, raw in [('a', ('"\\\n' * 10000).encode()), ('b', ('z' * 30000).encode())]:
        target = tmp_path / (name + '.json'); target.write_bytes(raw)
        e = copy.deepcopy(template); e.update(id=name, path=target.name, sha256=hashlib.sha256(raw).hexdigest())
        records.append(e)
    report['evidence'] = records
    context = _context(report, tmp_path, 18000)
    assert len(json.dumps(context, sort_keys=True, ensure_ascii=False, separators=(',', ':'))) <= 18000
    assert all(e['excerpt'] and e['excerpt_truncated'] for e in context['evidence'])


def test_unavailable_pillar_never_adopts_invented_vae_findings(tmp_path):
    def invent(p):
        target = next(x for x in p['pillars'] if x['name'] == 'statistical_risk')
        target['summary'] = 'Invented VaR 99999 and a low risk score.'
        target['analysis'] = [{'text': 'Invented VAE result 99999.', 'evidence_ids': [], 'input_ids': []}]
    result = bundle(tmp_path / 'unavailable', FakeClient(mutate=invent), [])
    assert result['model_status'] == 'completed'
    report, reasoning = validate_bundle(tmp_path / 'unavailable')
    risk = next(x for x in reasoning['pillars'] if x['name'] == 'statistical_risk')
    assert risk['summary'] == report['pillars']['statistical_risk']['summary']
    assert '99999' not in json.dumps(risk)
    assert report['pillars']['statistical_risk']['measurements'] == []


def test_zero_budget_missing_key_and_context_limit_make_no_model_calls(tmp_path, monkeypatch):
    client = FakeClient(); snapshot = captured_snapshot(source_payloads())
    result = run_case(case('automatic_policy'), tmp_path / 'zero', captured_snapshot=snapshot,
                      max_model_calls=0, model_client=client)
    assert result['model_status'] == 'skipped_budget' and result['model_calls'] == 0 and not client.calls
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    result = run_case(case('automatic_policy'), tmp_path / 'no-key', captured_snapshot=snapshot,
                      max_model_calls=1, stage_callback=lambda event: None)
    assert result['model_status'] == 'unavailable_credentials' and result['model_calls'] == 0
    result = run_case(case('automatic_policy'), tmp_path / 'small', captured_snapshot=snapshot,
                      max_model_calls=1, model_client=client, max_model_context_chars=1000, stage_callback=lambda event: None)
    assert result['model_status'] == 'failed_context' and result['model_calls'] == 0 and not client.calls
    result = run_case(case('automatic_policy'), tmp_path / 'no-evidence', max_source_requests=0,
                      max_model_calls=1, model_client=client, stage_callback=lambda event: None)
    assert result['state'] == 'blocked' and not client.calls
    with pytest.raises(ValueError, match='model call budget'):
        run_case(case('automatic_policy'), tmp_path / 'over-budget', max_model_calls=2, model_client=client)
    client.max_retries = 2
    result = run_case(case('automatic_policy'), tmp_path / 'retry-policy', captured_snapshot=snapshot,
                      max_model_calls=1, model_client=client, stage_callback=lambda event: None)
    assert result['model_status'] == 'failed_client_retry_policy' and result['model_calls'] == 0 and not client.calls


def test_checkpoint_resume_requires_matching_context_and_makes_no_second_call(tmp_path):
    client = FakeClient(); events = []; snapshot = captured_snapshot(source_payloads())
    first = run_case(case('world_confirmed'), tmp_path / 'first', captured_snapshot=snapshot,
                     max_model_calls=1, model_client=client, stage_callback=events.append)
    checkpoint = next(e['checkpoint'] for e in events if e['stage'] == 'reasoning' and e['state'] == 'completed')
    second = run_case(case('world_confirmed'), tmp_path / 'second', captured_snapshot=snapshot,
                      max_model_calls=0, model_client=client, stage_callback=lambda event: None, reasoning_checkpoint=checkpoint)
    assert first['model_status'] == 'completed' and second['model_status'] == 'resumed'
    assert second['model_calls'] == 0 and len(client.calls) == 1
    assert first['model_usage'] == second['model_usage'] == checkpoint['usage']
    bad = copy.deepcopy(checkpoint); bad['input_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='checkpoint does not match'):
        run_case(case('world_confirmed'), tmp_path / 'bad', captured_snapshot=snapshot, reasoning_checkpoint=bad)
    assert not (tmp_path / 'bad').exists()


def test_cancellation_or_stage_persistence_failure_never_installs_bundle(tmp_path):
    state = {'cancelled': False}
    client = FakeClient(after=lambda: state.update(cancelled=True))
    events = []; result = bundle(tmp_path / 'cancelled', client, events, cancelled=lambda: state['cancelled'])
    assert result['state'] == 'cancelled' and result['model_calls'] == 1 and not (tmp_path / 'cancelled').exists()
    assert result['model_usage']['total_tokens'] == 650
    assert next(e for e in events if e['stage'] == 'reasoning' and e['state'] == 'cancelled')['usage']['total_tokens'] == 650
    def fail(event):
        if event['stage'] == 'reasoning' and event['state'] == 'completed':
            raise OSError('synthetic persistence failure')
    client = FakeClient()
    with pytest.raises(StagePersistenceError):
        run_case(case('automatic_policy'), tmp_path / 'persistence', captured_snapshot=captured_snapshot(source_payloads()),
                 max_model_calls=1, model_client=client, stage_callback=fail)
    assert len(client.calls) == 1 and not (tmp_path / 'persistence').exists()
    def fail_start(event):
        if event['stage'] == 'reasoning' and event['state'] == 'started':
            raise OSError('synthetic reservation failure')
    client = FakeClient()
    with pytest.raises(StagePersistenceError):
        run_case(case('automatic_policy'), tmp_path / 'reservation', captured_snapshot=captured_snapshot(source_payloads()),
                 max_model_calls=1, model_client=client, stage_callback=fail_start)
    assert not client.calls and not (tmp_path / 'reservation').exists()
