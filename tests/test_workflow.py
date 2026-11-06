import json, os, tempfile
from pathlib import Path
from types import SimpleNamespace
import pytest
os.environ.setdefault('SCOOBY_DATA', tempfile.mkdtemp(prefix='scooby-test-'))
os.environ['SCOOBY_WEB_ORIGIN']='http://localhost:5173'
os.environ['SCOOBY_FRONTEND_DIR']=str(Path(__file__).resolve().parent.parent/'vendor'/'reader')
from fastapi.testclient import TestClient
from app import app
from worker import work_one
import worker
import hashlib
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
 # Simulate an at-least-once redelivery after atomic installation: never rebuild or replace bytes.
 first_path=Path(os.environ['SCOOBY_DATA'])/'artifacts'/draft.json()['job_id']/'index.html'; first=first_path.read_bytes()
 with db() as c: c.execute("UPDATE jobs SET state='queued' WHERE id=?",(draft.json()['job_id'],))
 with monkeypatch.context() as patch:
  patch.setattr(worker.subprocess,'run',lambda *a,**k: (_ for _ in ()).throw(AssertionError('must not rebuild installed package')))
  assert work_one()
 assert first_path.read_bytes()==first and client.get('/jobs/'+draft.json()['job_id']).json()['state']=='done'
 # Collision with tampered installed output must fail closed, never overwrite it.
 first_path.write_bytes(first+b'tampered')
 with db() as c: c.execute("UPDATE jobs SET state='queued' WHERE id=?",(draft.json()['job_id'],))
 assert work_one(); assert first_path.read_bytes()==first+b'tampered'
 assert client.get('/jobs/'+draft.json()['job_id']).json()['state'] in ('queued','failed')
 first_path.write_bytes(first)
 with db() as c: c.execute("UPDATE jobs SET state='queued',available=0 WHERE id=?",(draft.json()['job_id'],))
 assert work_one() and client.get('/jobs/'+draft.json()['job_id']).json()['state']=='done'
 review={'decision':'approve','actor':'local tester','reason':'fixture test only','sha256':report['sha256']}
 assert post(path+'/review',dict(review,sha256='0'*64),'bad').status_code==409
 assert post(path+'/review',review,'approval').status_code==200
 out=post(path+'/render',{},'render'); assert out.status_code==200
 assert work_one(); j=client.get('/jobs/'+out.json()['job_id']).json(); assert j['state']=='done',j
 html=client.get('/artifacts/'+out.json()['job_id']+'/index.html'); assert html.status_code==200
 listing=client.get(path+'/artifacts').json(); assert listing['report_sha256']==report['sha256']
 package=listing['package']; assert package['availability']=='available'
 descriptor=client.get(package['url']).json(); assert descriptor['report_sha256']==report['sha256']
 root_bytes=client.get(descriptor['manifest']['url']).content; assert hashlib.sha256(root_bytes).hexdigest()==package['package_sha256']
 report_bytes=client.get(descriptor['report']['url']).content; assert hashlib.sha256(report_bytes).hexdigest()==report['sha256']
 report_doc=json.loads(report_bytes); assert {x['path'] for x in descriptor['evidence']}=={x['path'] for x in report_doc['evidence']}
 assert [(x['kind'],x['path'],x['sha256']) for x in descriptor['artifacts']]==[(x['kind'],x['path'],x['sha256']) for x in report_doc['artifacts']]
 evidence=descriptor['evidence'][0]; source=client.get(evidence['url']); assert source.status_code==200 and hashlib.sha256(source.content).hexdigest()==evidence['sha256']
 unknown=client.get('/packages/'+package['package_sha256']+'/assets/not-a-declared-asset'); assert unknown.status_code==404
 with db() as c: package_job=c.execute("SELECT jobs.id FROM jobs JOIN render_manifests ON jobs.id=render_manifests.job_id WHERE render_manifests.sha256=? AND jobs.state='done' LIMIT 1",(package['package_sha256'],)).fetchone()[0]
 ev_path=Path(os.environ['SCOOBY_DATA'])/'artifacts'/package_job/'assets'/evidence['path']; ev_orig=ev_path.read_bytes(); ev_path.write_bytes(ev_orig+b'x'); assert client.get(evidence['url']).status_code==409; ev_path.write_bytes(ev_orig)
 assert descriptor['report_review_snapshot']['authentication']=='unverified report assertion'
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
 assert client.get(package['url']).json()==descriptor # frozen report snapshot does not follow live review
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
 assert data['paid_model_budget_default']==0 and data['checkpoint_case_status']=='no_fresh_milestone_selection_recorded_in_this_checkpoint'
 assert 'disabled by default' in data['publication'] and 'not live-verified' in data['publication']

def test_cors_restricts_origin():
 good=client.get('/reports',headers={'Origin':'http://localhost:5173'})
 bad=client.get('/reports',headers={'Origin':'http://untrusted.invalid'})
 assert good.headers.get('access-control-allow-origin')=='http://localhost:5173'
 assert 'access-control-allow-origin' not in bad.headers


def test_publication_cors_does_not_widen_operator_routes():
 headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'}
 assert client.options('/web/v1/reports/example/approve',headers=headers).status_code == 200
 assert client.options('/publication/v1/targets',headers=headers).status_code == 400
 assert client.options('/investigations',headers=headers).status_code == 400
