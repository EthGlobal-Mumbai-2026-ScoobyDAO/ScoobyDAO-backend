import json, os, tempfile
from pathlib import Path
from types import SimpleNamespace
import pytest
os.environ['SCOOBY_DATA']=tempfile.mkdtemp(prefix='scooby-test-')
os.environ['SCOOBY_WEB_ORIGIN']='http://localhost:5173'
os.environ['SCOOBY_FRONTEND_DIR']=str(Path(__file__).resolve().parent.parent/'vendor'/'reader')
from fastapi.testclient import TestClient
from app import app
from worker import work_one
from store import db
import provider
client=TestClient(app)
BASE=Path(__file__).parent
candidate=json.loads((BASE/'candidate.json').read_text(encoding='utf-8-sig'))
cid=candidate['candidate_id']
def post(url, body=None, key=None): return client.post(url,json=body,headers={'Idempotency-Key':key} if key else {})
def test_lifecycle(monkeypatch):
 assert post('/candidates',{'payload':candidate}).status_code==200
 assert client.get('/candidates/'+cid).json()['gate']=='unknown'
 assert post('/investigations',{'candidate_id':cid,'selection_id':'missing'},'before').status_code==404
 assert post('/candidates/'+cid+'/selection',{'kind':'qualified','actor':'operator','reason':'test'},'qualified').status_code==409
 x={'kind':'diagnostic_exception','actor':'test operator','reason':'historical fixture only'}
 a=post('/candidates/'+cid+'/selection',x,'selection'); assert a.status_code==200
 assert post('/candidates/'+cid+'/selection',x,'selection').json()['id']==a.json()['id']
 run={'candidate_id':cid,'selection_id':a.json()['id']}
 b=post('/investigations',run,'run'); assert b.status_code==200; rid=b.json()['id']
 assert post('/investigations',run,'run').json()['id']==rid
 assert work_one()
 assert client.get('/investigations/'+rid).json()['status']=='incomplete'
 assert {p['status'] for p in client.get('/investigations/'+rid).json()['pillars']}=={'unavailable'}
 # Restart is simulated by reopening the persistent database, not by recreating state.
 with db() as c: assert c.execute('SELECT count(*) FROM investigations WHERE id=?',(rid,)).fetchone()[0]==1
 imported=post('/reports/import',{'run_id':rid,'bundle_path':str(BASE/'historical-bundle')})
 assert imported.status_code==200, imported.text
 report=imported.json(); path='/reports/'+report['report_id']+'/'+report['version']
 listed=client.get('/reports').json(); assert any(x['report_sha256']==report['sha256'] and x['selection']['admission_qualified'] is False for x in listed)
 assert client.get(path+'/artifacts').json()['render_status']=='not_rendered'
 draft=post(path+'/render',{},'render-before'); assert draft.status_code==200
 assert work_one(); assert client.get('/jobs/'+draft.json()['job_id']).json()['state']=='done'
 assert 'PENDING REVIEW' in client.get('/artifacts/'+draft.json()['job_id']+'/index.html').text
 review={'decision':'approve','actor':'local tester','reason':'fixture test only','sha256':report['sha256']}
 assert post(path+'/review',dict(review,sha256='0'*64),'bad').status_code==409
 assert post(path+'/review',review,'approval').status_code==200
 out=post(path+'/render',{},'render'); assert out.status_code==200
 assert work_one(); j=client.get('/jobs/'+out.json()['job_id']).json(); assert j['state']=='done',j
 html=client.get('/artifacts/'+out.json()['job_id']+'/index.html'); assert html.status_code==200
 listing=client.get(path+'/artifacts').json(); assert listing['report_sha256']==report['sha256']
 assert listing['artifacts']['html']['availability']=='available' and listing['artifacts']['html']['report_sha256']==report['sha256']
 manifest=client.get('/artifacts/'+out.json()['job_id']+'/manifest.json').json()
 assert manifest['report_sha256']==report['sha256'] and manifest['markdown_sha256']
 assert client.get('/artifacts/'+out.json()['job_id']+'/report.md').content==(BASE/'historical-bundle'/'report.md').read_bytes()
 rendered=Path(os.environ['SCOOBY_DATA'])/'artifacts'/out.json()['job_id']/'index.html'; original=rendered.read_bytes(); rendered.write_bytes(original+b'tamper')
 assert client.get(path+'/artifacts').status_code==409 and client.get('/artifacts/'+out.json()['job_id']+'/index.html').status_code==409
 rendered.write_bytes(original)
 manifest_file=rendered.parent/'manifest.json'; original_manifest=manifest_file.read_bytes(); manifest_file.write_bytes(original_manifest+b' ')
 assert client.get(path+'/artifacts').status_code==409 and client.get('/artifacts/'+out.json()['job_id']+'/manifest.json').status_code==409
 manifest_file.write_bytes(original_manifest)
 if not os.environ.get('SCOOBY_BROWSER'): assert client.get('/artifacts/'+out.json()['job_id']+'/report.pdf').status_code==404
 os.environ['SCOOBY_MODEL_CALL_BUDGET']='1'
 monkeypatch.setattr(provider,'reason',lambda evidence: {'output':{'summary':'mock','evidence_ids':[evidence[0]['id']],'limitations':['fixture']},'model':'gpt-6.1-terra','transport':'chat.completions','usage':None})
 reasoning=post('/investigations/'+rid+'/reason',{'pillar':'microstructure','evidence':[{'id':'fixture-1','text':'synthetic evidence'}]},'reason-1')
 assert reasoning.status_code==200; assert work_one()
 assert client.get('/reasoning/'+reasoning.json()['input_id']).json()['output']['model']=='gpt-6.1-terra'
 if os.environ.get('SCOOBY_BROWSER'):
  pdf=client.get('/artifacts/'+out.json()['job_id']+'/report.pdf'); assert pdf.status_code==200 and pdf.content.startswith(b'%PDF-')
  assert manifest['pdf_content']=='expanded reader and bound full Markdown'
  print('PDF_TEST_PATH='+str(Path(os.environ['SCOOBY_DATA'])/'artifacts'/out.json()['job_id']/'report.pdf'))
 assert post(path+'/review',dict(review,decision='revise'),'revise').status_code==200
 assert post(path+'/render',{},'render-after-revision').status_code==200

def test_provider_transport_and_failure():
 calls=[]
 def create(**kw):
  calls.append(kw)
  msg=SimpleNamespace(refusal=None,content=json.dumps({'summary':'test','evidence_ids':['e1'],'limitations':['synthetic']}))
  return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=msg)],usage=None)
 fake=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
 result=provider.reason([{'id':'e1','text':'fixture'}],fake)
 assert result['model']=='gpt-6.1-terra' and calls[0]['response_format']['type']=='json_schema'
 assert 'tools' not in calls[0]
 with pytest.raises(ValueError): provider.reason([{'id':'different'}],fake)


def test_honeypot_readiness_is_honest():
 data=client.get('/readiness/honeypot').json()
 assert data['kind']=='static_integration_inventory'
 assert data['normal_gate']=={'required_distinct_verified_groups':4,'wired_verifiers':0,'qualified_selection_enabled':False}
 assert data['paid_model_budget_default']==0 and data['checkpoint_case_status']=='no_selection_recorded_in_this_checkpoint'
 assert 'not implemented' in data['publication']

def test_cors_restricts_origin():
 good=client.get('/reports',headers={'Origin':'http://localhost:5173'})
 bad=client.get('/reports',headers={'Origin':'http://untrusted.invalid'})
 assert good.headers.get('access-control-allow-origin')=='http://localhost:5173'
 assert 'access-control-allow-origin' not in bad.headers
