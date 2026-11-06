"""Captured, selected-pool-bound Honeypot.is provider replay; no live calls."""
import base64, copy, hashlib, json
from pathlib import Path
import pytest
from modules.investigation.case_research import run_case
from modules.investigation.contract_validate import verify_digest
from test_case_research import ADDR, POOL, case, captured_snapshot, source_payloads

def scan():
 return {'token':{'address':ADDR},'chain':{'id':'1'},'pair':{'pair':{'address':POOL}},
  'honeypotResult':{'isHoneypot':True},'simulationSuccess':True,
  'simulationResult':{'buyTax':0,'sellTax':0},'holderAnalysis':{'holders':'544','successful':'524','failed':'20'},
  'summary':{'flags':[{'flag':'medium_fail_rate'}]}}

def snapshot(doc=None, url=None):
 s=captured_snapshot(source_payloads());raw=json.dumps(scan() if doc is None else doc).encode();sha=hashlib.sha256(raw).hexdigest();path='snapshots/'+sha+'.json'
 s['record']['evidence'].append({'id':sha,'source':path,'sha256':sha,'observed_at':None,'fetched_at':'2020-01-01T00:00:00+00:00',
  'block_number':None,'kind':'synthetic','limitations':['Request URL: '+(url or 'https://api.honeypot.is/v2/IsHoneypot?address='+ADDR+'&chainID=1')]})
 s['evidence'][path]=base64.b64encode(raw).decode();return s

def test_conflicting_provider_reports_are_attributed_and_counterlinked(tmp_path):
 r=run_case(case('automatic_policy'),tmp_path/'case',captured_snapshot=snapshot(),max_source_requests=0)
 report=verify_digest(tmp_path/'case',r['report_sha256']);p=report['pillars']['onchain']
 claims={x['id']:x for x in p['claims']};values={x['id']:x['value'] for x in p['measurements']}
 assert claims['honeypot-provider-flag-1']['statement'].endswith('medium_fail_rate for the selected pool.')
 assert claims['honeypot-provider-verdict']['supporting_evidence_ids']==['honeypot_is']
 assert claims['honeypot-provider-verdict']['counterevidence_ids']==['security']
 assert claims['provider-is_honeypot']['counterevidence_ids']==['honeypot_is']
 assert values['honeypot_holder_holders']==544 and values['honeypot_holder_successful']==524 and values['honeypot_holder_failed']==20
 assert values['honeypot_simulation_buyTax']==0 and values['honeypot_simulation_sellTax']==0
 assert any('verdicts conflict' in issue for issue in p['quality_issues'])
 assert report['assessment']['status']=='not_assessed' and r['source_attempts']==[]

@pytest.mark.parametrize('problem',['token','chain','pool','pair_tokens','missing_pool','wrong_url','provider_shape'])
def test_unbound_or_mismatched_honeypot_capture_is_never_mapped(tmp_path,problem):
 doc=scan();url=None
 if problem=='token':doc['token']['address']='0x'+'ab'*20
 if problem=='chain':doc['chain']['id']='8453'
 if problem=='pool':doc['pair']['pair']['address']='0x'+'ab'*20
 if problem=='pair_tokens':doc['pair']['pair'].update(token0=ADDR,token1='0x'+'ff'*20)
 if problem=='missing_pool':doc.pop('pair')
 if problem=='provider_shape':doc['honeypotResult']['isHoneypot']='true'
 if problem=='wrong_url':url='https://api.honeypot.is/v2/IsHoneypot?address='+ADDR+'&chainID=8453'
 r=run_case(case('automatic_policy'),tmp_path/problem,captured_snapshot=snapshot(doc,url),max_source_requests=0)
 report=verify_digest(tmp_path/problem,r['report_sha256'])
 assert 'honeypot_is' not in {x['id'] for x in report['evidence']}
 assert all(not x['id'].startswith('honeypot-') for x in report['pillars']['onchain']['claims'])

def test_unreconciled_holder_counts_do_not_become_measurements(tmp_path):
 doc=scan();doc['holderAnalysis']['failed']='21'
 r=run_case(case('automatic_policy'),tmp_path/'bad-count',captured_snapshot=snapshot(doc))
 p=verify_digest(tmp_path/'bad-count',r['report_sha256'])['pillars']['onchain']
 assert not any(x['id'].startswith('honeypot_holder_') for x in p['measurements'])
 assert any(x['id']=='honeypot-provider-verdict' for x in p['claims'])
