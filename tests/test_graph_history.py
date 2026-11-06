"""Offline Graph token-day integration, provenance and rejection tests."""
import copy
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from modules.investigation import graph_history
from modules.investigation.case_research import run_case
from modules.investigation.contract_validate import verify_digest
from modules.investigation.model_reasoning import _context

ADDRESS = '0x' + '12' * 20
CANDIDATE = '1:' + ADDRESS

def encoded(data): return (json.dumps(data, indent=2) + '\n').encode()
def put(path, raw): path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw); return hashlib.sha256(raw).hexdigest()
def ts(day): return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp())

def build(tmp_path):
    source=tmp_path/'source'; model=tmp_path/'model'; source.mkdir(); model.mkdir()
    rows=[{'date':ts(day),'token':{'id':ADDRESS,'symbol':'TEST'},'priceUSD':str(value),'close':str(value)}
          for day,value in [('2020-01-01',1),('2020-01-02',2),('2020-01-03',3)]]
    page=encoded({'data':{'tokenDayDatas':rows}}); page_sha=put(source/'graph-response-0001.json',page)
    normalized=encoded(rows); normalized_sha=put(source/'token_daily.json',normalized)
    capture={'source':'The Graph tokenDayDatas','chain':'ethereum','subgraph_id':graph_history.SUBGRAPH,
        'token_address':ADDRESS,'start_inclusive_utc':'2020-01-01','end_exclusive_utc':'2020-01-04',
        'fetched_at_utc':'2020-01-04T12:00:00+00:00','row_count':3,'missing_utc_dates':[],
        'raw_sha256':normalized_sha,'query':graph_history.QUERY,'price_field':'priceUSD','price_units':'USD per token',
        'requests':[{'path':'graph-response-0001.json','sha256':page_sha,'variables':{'token':ADDRESS,'start':ts('2020-01-01'),'end':ts('2020-01-04'),'batch_size':1000}}]}
    put(source/'manifest.json',encoded(capture))
    returns=b'datetime,TOKEN\r\n2020-01-02,1.0\r\n2020-01-03,0.5\r\n';returns_sha=put(model/'output/crypto_returns.csv',returns)
    recon=('datetime,'+','.join(f'VAE_{i}' for i in range(50))+'\n'+'2020-01-02,'+','.join(['0.1']*50)+'\n'+'2020-01-03,'+','.join(['0.2']*50)+'\n').encode()
    recon_sha=put(model/'output/vae/VAE_TOKEN.csv',recon)
    risk=encoded({'var_metrics':{'var_95':1.234,'time_horizon_days':4},'risk_assessment':{'risk_level':'Low'}});risk_sha=put(model/'risk-metrics.json',risk)
    run={'candidate_id':CANDIDATE,'source':'The Graph tokenDayDatas token-level USD','source_manifest':capture,'graph_rows_sha256':normalized_sha,
         'returns_sha256':returns_sha,'metrics_sha256':risk_sha,'reconstructions_sha256':recon_sha,'returns':2,'reconstructions':50,
         'legacy_precompute_sha256':'a'*64,'days':4}
    run_raw=encoded(run);run_sha=put(model/'run-manifest.json',run_raw)
    technical=encoded({'technical_health':{'overall_health':{'score':73}},'technical_series':{'dates':['2020-01-02','2020-01-03'],'rsi':[1,2]}})
    technical_sha=put(model/'technical-metrics.json',technical)
    put(model/'technical-manifest.json',encoded({'candidate_id':CANDIDATE,'technical_metrics_sha256':technical_sha,
        'reconstructions_sha256':recon_sha,'legacy_precompute_sha256':'a'*64,'source_manifest_sha256':run_sha}))
    return source,model,technical_sha

def case(): return {'case_id':'graph_test','run_id':'run_graph','candidate_id':CANDIDATE,'mode':'historical_replay',
                    'authorization':{'route':'automatic_policy','reference_id':'synthetic_test_reference'}}

def test_graph_case_keeps_exact_pages_and_original_model_and_renders_legacy_inputs(tmp_path):
    source,model,tech_hash=build(tmp_path);out=tmp_path/'out'
    result=run_case(case(),out,max_source_requests=0,graph_capture_dir=source,graph_model_dir=model,graph_technical_sha256=tech_hash)
    assert result['state']=='partial' and result['model_calls']==0 and result['source_attempts']==[]
    report=verify_digest(out,result['report_sha256'])
    assert report['mode']=='historical_replay' and report['pillars']['statistical_risk']['status']=='partial'
    assert (out/'evidence/graph/graph-response-0001.json').read_bytes()==(source/'graph-response-0001.json').read_bytes()
    assert (out/'evidence/graph_model/risk-metrics.json').read_bytes()==(model/'risk-metrics.json').read_bytes()
    assert (out/'evidence/legacy_reconstructions.csv').read_bytes()==(model/'output/vae/VAE_TOKEN.csv').read_bytes()
    assert _context(report,out,120000)['verified_legacy_math'] is True
    series=report['pillars']['technical_health']['series']
    assert any(x['id']=='graph_token_daily_price_usd' and 'not selected-pool' in x['method'] for x in series)
    assert report['pillars']['microstructure']['status']=='unavailable'

def test_graph_rejects_candidate_query_and_page_tampering(tmp_path):
    source,model,tech_hash=build(tmp_path)
    with pytest.raises(ValueError,match='identity mismatch'):
        graph_history.verify_capture(source,'1:0x'+'34'*20)
    manifest=json.loads((source/'manifest.json').read_text());manifest['requests'][0]['variables']['start']+=86400
    put(source/'manifest.json',encoded(manifest))
    with pytest.raises(ValueError,match='page/query binding mismatch'):
        graph_history.verify_capture(source,CANDIDATE)
    manifest['requests'][0]['variables']['start']-=86400;put(source/'manifest.json',encoded(manifest))
    (source/'graph-response-0001.json').write_bytes(b'{}')
    with pytest.raises(ValueError,match='page digest mismatch'):
        graph_history.verify_capture(source,CANDIDATE)

def test_graph_rejects_model_and_supplemental_mismatch(tmp_path):
    source,model,tech_hash=build(tmp_path);capture=graph_history.verify_capture(source,CANDIDATE)
    assert graph_history.verify_model(model,capture,tech_hash)['technical'] is not None
    (model/'technical-manifest.json').write_bytes(encoded({'candidate_id':CANDIDATE}))
    with pytest.raises(ValueError,match='technical provenance mismatch'):
        graph_history.verify_model(model,capture,tech_hash)
    (model/'output/vae/VAE_TOKEN.csv').write_bytes(b'bad')
    with pytest.raises(ValueError,match='provenance or hash mismatch'):
        graph_history.verify_model(model,capture,tech_hash)

def test_graph_empty_history_blocks_source_only_report(tmp_path):
    source,model,tech_hash=build(tmp_path);manifest=json.loads((source/'manifest.json').read_text())
    page=encoded({'data':{'tokenDayDatas':[]}});manifest['requests'][0]['sha256']=put(source/'graph-response-0001.json',page)
    manifest['raw_sha256']=put(source/'token_daily.json',encoded([]));manifest['row_count']=0
    manifest['missing_utc_dates']=['2020-01-01','2020-01-02','2020-01-03'];put(source/'manifest.json',encoded(manifest))
    result=run_case(case(),tmp_path/'out',max_source_requests=0,graph_capture_dir=source)
    assert result['state']=='blocked' and not (tmp_path/'out').exists()
    assert result['graph_capture']['rows']==0 and result['graph_capture']['missing_days']==3
    assert 'not selected-pool' in result['graph_capture']['limitation']

@pytest.mark.parametrize('issue', ['duplicate', 'open_day', 'wrong_token', 'credential_url', 'wrong_model_returns', 'wrong_technical_hash'])
def test_graph_rejects_untrusted_or_mismatched_provenance(tmp_path, issue):
    source,model,tech_hash=build(tmp_path)
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    page=json.loads((source/'graph-response-0001.json').read_text(encoding='utf-8'))
    if issue in ('duplicate','open_day','wrong_token','credential_url'):
        rows=page['data']['tokenDayDatas']
        if issue=='duplicate': rows[1]['date']=rows[0]['date']
        if issue=='open_day': rows[-1]['date']=ts('2020-01-04')
        if issue=='wrong_token': rows[0]['token']['id']='0x'+'34'*20
        if issue=='credential_url': rows[0]['url']='https://gateway.thegraph.com/api/SECRETKEY123/subgraphs/id/example'
        manifest['requests'][0]['sha256']=put(source/'graph-response-0001.json',encoded(page))
        manifest['raw_sha256']=put(source/'token_daily.json',encoded(rows));put(source/'manifest.json',encoded(manifest))
        with pytest.raises(ValueError):graph_history.verify_capture(source,CANDIDATE)
    else:
        capture=graph_history.verify_capture(source,CANDIDATE)
        if issue=='wrong_model_returns': (model/'output/crypto_returns.csv').write_bytes(b'datetime,TOKEN\n')
        with pytest.raises(ValueError): graph_history.verify_model(model,capture,'0'*64 if issue=='wrong_technical_hash' else tech_hash)

def test_graph_rejects_rehashed_wrong_reconstruction_shape(tmp_path):
    source,model,tech_hash=build(tmp_path);capture=graph_history.verify_capture(source,CANDIDATE)
    path=model/'output/vae/VAE_TOKEN.csv'; raw=b'datetime,one\n2020-01-02,0.1\n'
    manifest=json.loads((model/'run-manifest.json').read_text(encoding='utf-8'))
    manifest['reconstructions_sha256']=put(path,raw);put(model/'run-manifest.json',encoded(manifest))
    with pytest.raises(ValueError,match='50 distinct'):
        graph_history.verify_model(model,capture)


def test_graph_rejects_rehashed_returns_not_derived_from_prices(tmp_path):
    source,model,tech_hash=build(tmp_path);capture=graph_history.verify_capture(source,CANDIDATE)
    manifest=json.loads((model/'run-manifest.json').read_text(encoding='utf-8'))
    manifest['returns_sha256']=put(model/'output/crypto_returns.csv',b'datetime,TOKEN\r\n2020-01-02,0.9\r\n2020-01-03,0.5\r\n')
    put(model/'run-manifest.json',encoded(manifest))
    with pytest.raises(ValueError,match='do not match captured prices'):
        graph_history.verify_model(model,capture)
