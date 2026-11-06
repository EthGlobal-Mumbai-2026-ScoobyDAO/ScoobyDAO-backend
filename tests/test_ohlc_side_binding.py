"""Reject present OHLC metadata that contradicts selected pool-side identity."""
import copy
import pytest
from modules.investigation import history
from modules.investigation.case_research import run_case
from modules.investigation.contract_validate import verify_digest
from test_case_research import ADDR, case, captured_snapshot, source_payloads

OTHER='0x'+'56'*20

def payloads():
 p=source_payloads();rel=p['pools']['data'][0]['relationships']
 rel['base_token']['data']['id']='eth_'+OTHER;rel['quote_token']['data']['id']='eth_'+ADDR
 p['daily']['meta']={'base':{'address':ADDR},'quote':{'address':OTHER}}
 return p

def quote_snapshot():
 s=captured_snapshot(payloads())
 for e in s['record']['evidence']:
  if '/ohlcv/day?' in e['limitations'][0]:e['limitations'][0]=e['limitations'][0].replace('token=base','token=quote')
 return s

def test_metadata_must_match_selected_side_but_absence_is_distinct():
 p=payloads()
 with pytest.raises(ValueError,match='disagrees'):history.validate_candle_identity(p['daily'],1,ADDR,'quote')
 assert history.validate_candle_identity({'data':{}},1,ADDR,'quote') is False
 assert history.validate_candle_identity(p['daily'],1,ADDR,'base') is True

def test_replay_rejects_ohlc_side_contradiction_before_model(tmp_path):
 r=run_case(case('automatic_policy'),tmp_path/'case',captured_snapshot=quote_snapshot())
 report=verify_digest(tmp_path/'case',r['report_sha256'])
 assert 'ohlc_token_side_mismatch' in r['limitations']
 assert report['pillars']['technical_health']['status']=='unavailable'
 assert 'daily' not in {e['id'] for e in report['evidence']}

def test_standalone_fetch_reports_conflicting_metadata_unavailable(tmp_path,monkeypatch):
 p=payloads();calls=[]
 def fake_get(url,out,name):calls.append(name);return p['pools' if name=='pools' else 'daily'],{'status':'captured'}
 monkeypatch.setattr(history,'get',fake_get)
 r=history.fetch(1,ADDR,tmp_path/'source')
 assert r['state']=='unavailable' and r['history'] is None and 'invalid' in r['error']
 assert r['reason']=='ohlc_token_side_mismatch'
 assert calls==['pools','daily']

def test_vae_runner_rejects_side_conflict_before_creating_model(tmp_path):
 import hashlib,json
 from modules.investigation import legacy_vae
 p=payloads();source=tmp_path/'source';source.mkdir()
 records=[]
 for name,doc in [('pools',p['pools']),('daily',p['daily'])]:
  raw=json.dumps(doc).encode();(source/(name+'.json')).write_bytes(raw)
  records.append({'path':name+'.json','sha256':hashlib.sha256(raw).hexdigest()})
 status={'candidate_id':'1:'+ADDR,'pool':{'address':p['pools']['data'][0]['attributes']['address'],'side':'quote'},
         'requests':records,'history':{'cutoff_utc_date':'2026-11-06'}}
 (source/'source-status.json').write_text(json.dumps(status),encoding='utf-8')
 with pytest.raises(ValueError,match='disagrees'): legacy_vae.run(source,tmp_path/'model',4,tmp_path/'legacy')
 assert not (tmp_path/'model').exists()

def test_missing_ohlc_side_metadata_is_disclosed_not_verified(tmp_path):
 p=source_payloads();r=run_case(case('automatic_policy'),tmp_path/'case',captured_snapshot=captured_snapshot(p))
 report=verify_digest(tmp_path/'case',r['report_sha256'])
 assert report['pillars']['technical_health']['status']=='partial'
 assert any('metadata was absent' in x for x in report['pillars']['technical_health']['quality_issues'])
