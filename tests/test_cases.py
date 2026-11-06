import copy,json,os,sqlite3,tempfile,hashlib,datetime
from pathlib import Path
import pytest
from jsonschema.exceptions import ValidationError
os.environ.setdefault('SCOOBY_DATA',tempfile.mkdtemp(prefix='scooby-cases-test-'))
from fastapi.testclient import TestClient
from app import app
from store import db,now
import store
import case_engine,worker
client=TestClient(app)
BASE=Path(__file__).parent

@pytest.fixture(autouse=True)
def isolated_state(tmp_path,monkeypatch):
 monkeypatch.delenv('SCOOBY_SOCIAL_CONTEXT_FILE',raising=False);monkeypatch.delenv('SCOOBY_SOCIAL_CONTEXT_FILES',raising=False);monkeypatch.delenv('SCOOBY_SOCIAL_CANDIDATE_STATUS_FILE',raising=False);monkeypatch.setattr(store,'DB',tmp_path/'case-state.sqlite3');store.init()

def record(n):
 d=json.loads((BASE/'candidate.json').read_text(encoding='utf-8-sig'));d['mode']='live';d['identity']['address']='0x'+format(n,'040x');d['candidate_id']='1:'+d['identity']['address'];d['identity']['symbol']='SYNTHETIC';d['selection']={'status':'not_selected','selected_by':None,'selected_at':None,'reason':None};d['state']='monitoring';d['evidence']=[];return d

def with_sources(d,root):
 folder=root/'snapshots';folder.mkdir(exist_ok=True);stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
 for i in range(4):
  raw=('synthetic-source-'+str(i)).encode();sha=hashlib.sha256(raw).hexdigest();(folder/(sha+'.json')).write_bytes(raw)
  d['evidence'].append({'id':sha,'source':'snapshots/'+sha+'.json','sha256':sha,'observed_at':stamp,'fetched_at':stamp,'block_number':None,'kind':'live_observation','limitations':['SYNTHETIC TEST ONLY']})
 return d

def result(n,record):
 ev=record.get('evidence',[])
 groups=[{'id':'G%02d'%i,'status':'triggered' if i<=n else 'unknown','votes':1 if i<=n else 0,'detail':'Synthetic mock only','measurements':[],'evidence':[{'id':ev[i-1]['id'],'source':ev[i-1]['source'],'sha256':ev[i-1]['sha256'],'observed_at':ev[i-1]['observed_at']}] if i<=n and len(ev)>=i else []} for i in range(1,13)]
 return {'eligible':n>=4,'triggered_count':n,'groups':groups}

def test_discovery_reconcile_is_bounded_and_human_fails_closed(tmp_path,monkeypatch):
 path=tmp_path/'discovery.sqlite';con=sqlite3.connect(path);con.execute('CREATE TABLE candidates(id TEXT PRIMARY KEY,record TEXT NOT NULL)');d=with_sources(record(701),tmp_path);con.execute('INSERT INTO candidates VALUES(?,?)',(d['candidate_id'],json.dumps(d)));con.commit();con.close()
 monkeypatch.setenv('SCOOBY_DISCOVERY_DB',str(path));monkeypatch.setenv('SCOOBY_DISCOVERY_ROOT',str(tmp_path));monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(1,r))
 res=client.post('/scouting/cases/refresh',json={'limit':1},headers={'Idempotency-Key':'scan-701'});assert res.status_code==200
 assert worker.work_one();status=client.get('/jobs/'+res.json()['job_id']).json();assert status['state']=='done'
 body=client.get('/scouting/cases').json();assert body['schema_version']=='scouting-case-list/2';x=next(a for a in body['cases'] if a['candidate_id']==d['candidate_id']);assert x['lane']=='human_review_required' and x['continuation']['availability']=='unavailable'
 request={'expected_revision':x['snapshot_digest'],'action':'diagnostic_research'};a=client.post('/scouting/cases/'+x['case_id']+'/challenge',json=request,headers={'Idempotency-Key':'challenge-701'});assert a.status_code==200,a.text
 q=a.json();assert q['snapshot_digest']==x['snapshot_digest'] and q['candidate_id']==d['candidate_id'];assert client.post('/scouting/challenges/'+q['challenge_id']+'/continue').status_code==503
 with db() as c:c.execute('UPDATE case_challenges SET expires=? WHERE id=?',(now()-1,q['challenge_id']))
 assert client.post('/scouting/challenges/'+q['challenge_id']+'/continue').status_code==409
 # Old, caller-labeled live diagnostic selection cannot start a research run.
 assert client.post('/candidates',json={'payload':d}).status_code==200
 s=client.post('/candidates/'+d['candidate_id']+'/selection',headers={'Idempotency-Key':'legacy-701'},json={'kind':'diagnostic_exception','actor':'not authenticated','reason':'test'}).json()
 assert client.post('/investigations',headers={'Idempotency-Key':'legacy-run-701'},json={'candidate_id':d['candidate_id'],'selection_id':s['id']}).status_code==403

def test_mocked_auto_gate_dedup_and_tamper_fail_closed(tmp_path,monkeypatch):
 import case_jobs
 original=case_jobs.run_case
 monkeypatch.setattr(case_jobs,'run_case',lambda run_id:original(run_id,producer=lambda *a,**kw:{'state':'blocked','bundle_path':None}))
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(4,r));d=with_sources(record(702),tmp_path);case=case_engine.ingest_record(d,tmp_path)
 with db() as c: decision=c.execute('SELECT * FROM case_decisions WHERE case_id=?',(case,)).fetchone();did=decision['id']
 run=case_engine.start_decision(did);assert case_engine.start_decision(did)==run
 assert worker.work_one() # duplicate actor message cannot create a second run
 assert worker.work_one() # bounded investigation task records unavailable producers
 assert client.get('/investigations/'+run).json()['status']=='blocked'
 detail=client.get('/scouting/cases/'+case).json();assert detail['lane']=='unavailable' and detail['research']['status']=='blocked'
 assert len(detail['research']['pillars'])==5 and {x['status'] for x in detail['research']['pillars']}=={'unavailable'} and detail['research']['reason']
 with db() as c:
  assert c.execute('SELECT count(*) FROM investigations WHERE id=?',(run,)).fetchone()[0]==1
  assert c.execute('SELECT count(*) FROM pillars WHERE run_id=?',(run,)).fetchone()[0]==5
  assert c.execute('SELECT kind FROM selections WHERE id=(SELECT selection_id FROM investigations WHERE id=?)',(run,)).fetchone()[0]=='qualified'
 d2=with_sources(record(703),tmp_path);case2=case_engine.ingest_record(d2,tmp_path)
 with db() as c:
  decision=c.execute('SELECT * FROM case_decisions WHERE case_id=?',(case2,)).fetchone();did2=decision['id'];c.execute("UPDATE case_snapshots SET record='{}' WHERE id=?",(decision['snapshot_id'],))
 with pytest.raises(ValueError,match='tampered'):case_engine.start_decision(did2)
 with db() as c:c.execute('DELETE FROM case_decisions WHERE id=?',(did2,));c.execute('DELETE FROM cases WHERE id=?',(case2,));c.execute('DELETE FROM case_snapshots WHERE id=?',(decision['snapshot_id'],))

def test_expired_or_changed_policy_cannot_start(tmp_path,monkeypatch):
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(4,r));case=case_engine.ingest_record(with_sources(record(704),tmp_path),tmp_path)
 with db() as c:
  decision=c.execute('SELECT * FROM case_decisions WHERE case_id=?',(case,)).fetchone();c.execute('UPDATE case_snapshots SET expires=? WHERE id=?',(now()-1,decision['snapshot_id']))
 with pytest.raises(ValueError,match='stale'):case_engine.start_decision(decision['id'])
 case2=case_engine.ingest_record(with_sources(record(705),tmp_path),tmp_path)
 with db() as c: decision2=c.execute('SELECT * FROM case_decisions WHERE case_id=?',(case2,)).fetchone()
 monkeypatch.setattr(case_engine,'policy_digest',lambda:'different')
 with pytest.raises(ValueError,match='stale'):case_engine.start_decision(decision2['id'])


def test_reddit_is_explicitly_unavailable_without_retention():
 sources=client.get('/scouting/sources').json();reddit=next(x for x in sources['sources'] if x['id']=='reddit');assert reddit['status']=='unavailable'
 assert client.get('/scouting/leads').json()['leads']==[]

def test_missing_evidence_never_qualifies(tmp_path,monkeypatch):
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(4,r))
 case=case_engine.ingest_record(record(706),tmp_path)
 with db() as c:assert c.execute('SELECT count(*) FROM case_decisions WHERE case_id=?',(case,)).fetchone()[0]==0

def test_unsupported_chain_rejected(tmp_path):
 d=record(707);d['identity']['chain_id']=56;d['candidate_id']='56:'+d['identity']['address']
 with pytest.raises((ValueError,ValidationError)):case_engine.ingest_record(d,tmp_path)

def test_snapshot_change_supersedes_human_challenge(tmp_path,monkeypatch):
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(1,r));d=with_sources(record(708),tmp_path);case=case_engine.ingest_record(d,tmp_path)
 snap=client.get('/scouting/cases/'+case).json()['snapshot_digest'];h={'Idempotency-Key':'challenge-708'};r=client.post('/scouting/cases/'+case+'/challenge',headers=h,json={'expected_revision':snap});assert r.status_code==200
 changed=copy.deepcopy(d);changed['screening']['quality_issues'].append('Synthetic changed coverage');case_engine.ingest_record(changed,tmp_path)
 assert client.post('/scouting/challenges/'+r.json()['challenge_id']+'/continue').status_code==409
 assert client.post('/scouting/cases/'+case+'/challenge',headers={'Idempotency-Key':'stale-708'},json={'expected_revision':snap}).status_code==409

def test_assessment_tamper_fails_read_and_dispatch(tmp_path,monkeypatch):
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(4,r));case=case_engine.ingest_record(with_sources(record(709),tmp_path),tmp_path)
 with db() as c:
  dec=c.execute('SELECT * FROM case_decisions WHERE case_id=?',(case,)).fetchone();c.execute("UPDATE case_snapshots SET assessment='{}' WHERE id=?",(dec['snapshot_id'],))
 assert client.get('/scouting/cases/'+case).status_code==409
 with pytest.raises(ValueError,match='tampered'):case_engine.start_decision(dec['id'])
 with db() as c:c.execute('DELETE FROM case_decisions WHERE id=?',(dec['id'],));c.execute('DELETE FROM cases WHERE id=?',(case,));c.execute('DELETE FROM case_snapshots WHERE id=?',(dec['snapshot_id'],))

def test_actual_discovery_adapter_cannot_qualify_unknowns(tmp_path):
 d=record(710);case=case_engine.ingest_record(d,tmp_path)
 with db() as c:
  assert c.execute('SELECT count(*) FROM case_decisions WHERE case_id=?',(case,)).fetchone()[0]==0
  saved=c.execute('SELECT state FROM cases WHERE id=?',(case,)).fetchone()[0];assert saved in ('awaiting_human','monitoring')

def test_periodic_sync_opt_in_and_backpressure(monkeypatch):
 monkeypatch.delenv('SCOOBY_CASE_SYNC_ENABLED',raising=False);assert worker.enqueue_periodic_case_sync() is None
 monkeypatch.setenv('SCOOBY_CASE_SYNC_ENABLED','true');monkeypatch.setenv('SCOOBY_CASE_SYNC_LIMIT','500');jid=worker.enqueue_periodic_case_sync()
 if jid:
  with db() as c: assert c.execute('SELECT ref FROM jobs WHERE id=?',(jid,)).fetchone()[0]=='25'
 assert worker.enqueue_periodic_case_sync() is None

def test_case_list_matches_runtime_schema(tmp_path,monkeypatch):
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(1,r));case_engine.ingest_record(with_sources(record(1909),tmp_path),tmp_path)
 from jsonschema import Draft202012Validator
 schema=json.loads((BASE.parent/'schemas/runtime/scouting-case-list-v2.schema.json').read_text(encoding='utf-8-sig'))
 Draft202012Validator(schema).validate(client.get('/scouting/cases').json())

def test_human_attention_order_uses_verified_count_not_score(tmp_path,monkeypatch):
 def fake(r,_): return result({'711':1,'712':3,'713':4}[str(int(r['identity']['address'],16))],r)
 monkeypatch.setattr(case_engine,'evaluate',fake)
 for n in (711,712,713):case_engine.ingest_record(with_sources(record(n),tmp_path),tmp_path)
 rows=[x for x in client.get('/scouting/cases').json()['cases'] if int(x['identity']['address'],16) in (711,712,713)]
 assert [int(x['identity']['address'],16) for x in rows]==[713,712,711]
 assert [x['verified_triggered_count'] for x in rows]==[4,3,1]
 assert [x['lane'] for x in rows]==['auto_qualified','human_review_required','human_review_required']

def test_new_snapshot_cannot_duplicate_existing_candidate_research(tmp_path,monkeypatch):
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(4,r));d=with_sources(record(714),tmp_path);case=case_engine.ingest_record(d,tmp_path)
 with db() as c:first=c.execute('SELECT id FROM case_decisions WHERE case_id=?',(case,)).fetchone()['id']
 run=case_engine.start_decision(first)
 changed=copy.deepcopy(d);changed['screening']['quality_issues'].append('new synthetic snapshot')
 case_engine.ingest_record(changed,tmp_path)
 with db() as c:
  assert c.execute('SELECT count(*) FROM case_decisions WHERE case_id=?',(case,)).fetchone()[0]==1
  assert c.execute('SELECT count(*) FROM investigations WHERE id=?',(run,)).fetchone()[0]==1

def test_older_urgent_case_not_lost_before_truncation(tmp_path,monkeypatch):
 monkeypatch.setattr(case_engine,'policy_digest',lambda:'f'*64)
 template=with_sources(record(1800),tmp_path)
 def fake(r,_): return result(3 if int(r['identity']['address'],16)==1800 else 0,r)
 monkeypatch.setattr(case_engine,'evaluate',fake)
 for n in range(1800,1905):
  d=record(n);d['evidence']=copy.deepcopy(template['evidence']);case_engine.ingest_record(d,tmp_path)
 urgent=case_engine.digest(template['candidate_id'].encode())
 with db() as c:c.execute('UPDATE cases SET updated=1 WHERE id=?',(urgent,))
 result_list=client.get('/scouting/cases').json();assert result_list['truncated'] is True and len(result_list['cases'])==100
 assert result_list['cases'][0]['candidate_id']==template['candidate_id'] and result_list['cases'][0]['human_action_required'] is True

def test_reddit_derived_content_not_persisted(tmp_path):
 d=record(1906);d['triggers'][0]['description']='Synthetic reddit mention only'
 with pytest.raises(ValueError,match='Reddit-derived'):case_engine.ingest_record(d,tmp_path)
 d=record(1907);folder=tmp_path/'snapshots';folder.mkdir(exist_ok=True);raw=b'{"synthetic_source":"reddit"}';sha=hashlib.sha256(raw).hexdigest();(folder/(sha+'.json')).write_bytes(raw);stamp=datetime.datetime.now(datetime.timezone.utc).isoformat();d['evidence']=[{'id':sha,'source':'snapshots/'+sha+'.json','sha256':sha,'observed_at':stamp,'fetched_at':stamp,'block_number':None,'kind':'live_observation','limitations':['synthetic test only']}]
 with pytest.raises(ValueError,match='Reddit-derived'):case_engine.ingest_record(d,tmp_path)

def test_reference_lane_creates_no_research_job(tmp_path):
 d=record(1908);assert client.post('/candidates',json={'payload':d}).status_code==200
 sel=client.post('/candidates/'+d['candidate_id']+'/selection',headers={'Idempotency-Key':'ref-selection-1908'},json={'kind':'diagnostic_exception','actor':'local operator','reason':'separately authorized reference import only'}).json()
 payload={'candidate_id':d['candidate_id'],'selection_id':sel['id']};r=client.post('/reference-runs',headers={'Idempotency-Key':'ref-run-1908'},json=payload);assert r.status_code==200 and r.json()['status']=='reference_only'
 with db() as c:assert c.execute('SELECT count(*) FROM jobs WHERE kind=\'investigate\' AND ref=?',(r.json()['id'],)).fetchone()[0]==0
 assert client.post('/investigations/'+r.json()['id']+'/resume',headers={'Idempotency-Key':'resume-ref-1908'}).status_code==403


def test_evidence_bytes_tamper_blocks_auto_dispatch(tmp_path,monkeypatch):
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(4,r));case=case_engine.ingest_record(with_sources(record(1910),tmp_path),tmp_path)
 with db() as c:
  dec=c.execute('SELECT * FROM case_decisions WHERE case_id=?',(case,)).fetchone();snapshot=c.execute('SELECT evidence FROM case_snapshots WHERE id=?',(dec['snapshot_id'],)).fetchone();evidence=json.loads(snapshot['evidence']);evidence[next(iter(evidence))]='dGFtcGVyZWQ=';c.execute('UPDATE case_snapshots SET evidence=? WHERE id=?',(json.dumps(evidence),dec['snapshot_id']))
 with pytest.raises(ValueError,match='tampered'):case_engine.start_decision(dec['id'])

def test_existing_nonreference_run_blocks_new_auto_run(tmp_path,monkeypatch):
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(4,r));d=with_sources(record(1911),tmp_path)
 with db() as c:
  c.execute('INSERT INTO candidates VALUES(?,?,?)',(d['candidate_id'],json.dumps(d),now()))
  c.execute('INSERT INTO selections VALUES(?,?,?,?,?,?,?)',('legacy-sel-1911',d['candidate_id'],'diagnostic_exception','unverified','legacy',now(),'legacy-sel-key-1911'))
  c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?)',('legacy-run-1911',d['candidate_id'],'legacy-sel-1911','running',now(),'legacy-run-key-1911'))
 case=case_engine.ingest_record(d,tmp_path)
 with db() as c: assert c.execute('SELECT count(*) FROM case_decisions WHERE case_id=?',(case,)).fetchone()[0]==0
 view=client.get('/scouting/cases/'+case).json();assert view['lane']=='research_running' and view['research']['authorization']=='unverified_legacy' and view['research']['budget'] is None

def test_policy_file_change_requires_process_restart(monkeypatch):
 monkeypatch.setattr(case_engine,'_LOADED_POLICY_SOURCES',{'synthetic':'stale'})
 with pytest.raises(RuntimeError,match='restart'):case_engine.policy_digest()
 assert client.get('/scouting/cases').status_code==503


def test_social_context_is_transient_unresolved_and_expires(tmp_path,monkeypatch):
 stamp=datetime.datetime.now(datetime.timezone.utc);source=tmp_path/'metadata.json'
 item={'id':'t3_synthetic','url':'https://www.reddit.com/r/CryptoScams/comments/synthetic/example/','subreddit':'CryptoScams','observed_at':(stamp-datetime.timedelta(days=200)).isoformat(),'fetched_at':stamp.isoformat(),'attribution':'fabricated','verified_concern_votes':99,'author':'MUST NOT LEAK','excerpt':'MUST NOT LEAK'}
 source.write_text(json.dumps({'profile':'scooby.reddit-leads/1','provider':'searchapi.io','observations':[item]}));monkeypatch.setenv('SCOOBY_SOCIAL_CONTEXT_FILE',str(source))
 result=client.get('/scouting/leads').json();assert result['status']=='partial' and len(result['leads'])==1
 lead=result['leads'][0];assert lead['attribution']=='unresolved' and lead['verified_concern_votes']==0 and lead['age_days']>=200 and 'author' not in lead and 'excerpt' not in lead
 assert next(x for x in client.get('/scouting/sources').json()['sources'] if x['id']=='reddit')['status']=='partial'
 with db() as c:assert c.execute('SELECT count(*) FROM cases').fetchone()[0]==0
 item['fetched_at']=(stamp-datetime.timedelta(days=2)).isoformat();source.write_text(json.dumps({'profile':'scooby.reddit-leads/1','provider':'searchapi.io','observations':[item]}));assert client.get('/scouting/leads').json()['leads']==[]
 source.unlink();assert client.get('/scouting/leads').json()['status']=='unavailable'


def test_social_feeds_and_candidate_failure_are_independent(tmp_path,monkeypatch):
 stamp=datetime.datetime.now(datetime.timezone.utc).isoformat();paths=[]
 for name in ('first','second'):
  item={'id':'t3_'+name,'url':'https://www.reddit.com/r/Test/comments/'+name+'/post/','subreddit':'Test','observed_at':stamp,'fetched_at':stamp};p=tmp_path/(name+'.json');p.write_text(json.dumps({'profile':'scooby.reddit-leads/1','provider':'searchapi.io','observations':[item]}));paths.append(str(p))
 monkeypatch.setenv('SCOOBY_SOCIAL_CONTEXT_FILES',os.pathsep.join(paths));p=tmp_path/'candidate.json';candidate='1:0x'+'a'*40
 p.write_text(json.dumps({'profile':'scooby.reddit-evidence/1','provider':'searchapi.io','candidate_id':candidate,'window':{'end':stamp},'coverage':{'reason':'provider_error'},'observations':[]}));monkeypatch.setenv('SCOOBY_SOCIAL_CANDIDATE_STATUS_FILE',str(p))
 feeds=client.get('/scouting/leads').json();assert feeds['status']=='partial' and len(feeds['leads'])==2 and feeds['coverage']['available_feeds']==2
 status=client.get('/scouting/social-candidate-status').json()['candidate_queries'];assert status==[{'candidate_id':candidate,'status':'unavailable','reason':'provider_error','interpretation':'unavailable','observation_count':0}]
 Path(paths[1]).unlink();feeds=client.get('/scouting/leads').json();assert feeds['status']=='partial' and len(feeds['leads'])==1 and feeds['coverage']['available_feeds']==1


def test_source_clues_are_separate_from_verified_gate(tmp_path,monkeypatch):
 import base64
 from app import scouting_clues
 d=record(1910);stamp=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=3)).isoformat();raw=json.dumps({'result':{d['identity']['address']:{'creator_percent':'1.000000','honeypot_with_same_creator':'11','is_proxy':'1'}}}).encode();sha=hashlib.sha256(raw).hexdigest();source='snapshots/'+sha+'.json'
 d['triggers']=[{'reason_code':'new_pool_lead','description':'Provider reported a new pool.','evidence_ids':[sha]}];d['evidence']=[{'id':sha,'source':source,'sha256':sha,'fetched_at':stamp,'observed_at':None,'block_number':None,'kind':'live_observation','limitations':['Request URL: https://api.gopluslabs.io/api/v1/token_security/1']}]
 clues=scouting_clues(d,{source:base64.b64encode(raw).decode()});assert len(clues)==4 and all(x['verification'].startswith('unverified_') for x in clues);assert '100%' in clues[1]['description'] and '11' in clues[2]['description']
 assert len(scouting_clues(d,{}))==1
 folder=tmp_path/'snapshots';folder.mkdir();(folder/(sha+'.json')).write_bytes(raw);case=case_engine.ingest_record(d,tmp_path);view=client.get('/scouting/cases/'+case).json()
 assert view['verified_triggered_count']==0 and view['evidence_freshness']=='stale' and '0/4 fresh groups' in view['routing_rationale'] and '100%' in view['summary'];assert all('measurements' in r and 'name' in r for r in view['reasons'])


def test_world_confirmation_atomically_starts_one_case_run(tmp_path,monkeypatch):
 from types import SimpleNamespace
 from publication.deps import get_world_optional
 from publication.world import DeviceStart,Tokens,Denied
 import case_world
 class FakeWorld:
  config=SimpleNamespace(accepted_acr=('synthetic-test-acr',))
  outcome=Tokens('synthetic-token')
  def start_device(self,_):return DeviceStart(device_code='synthetic-device',user_code='TEST',verification_uri='https://world.example/verify',expires_in=100,interval=0)
  def poll(self,_):return self.outcome
  def validate_id_token(self,*a,**kw):return SimpleNamespace(iss='synthetic-issuer',sub='synthetic-human')
 world=FakeWorld();app.dependency_overrides[get_world_optional]=lambda:world
 try:
  case=case_engine.ingest_record(with_sources(record(1911),tmp_path),tmp_path);revision=client.get('/scouting/cases/'+case).json()['snapshot_digest'];ch=client.post('/scouting/cases/'+case+'/challenge',json={'expected_revision':revision},headers={'Idempotency-Key':'human-test'}).json();start=client.post('/scouting/challenges/'+ch['challenge_id']+'/world-attempt');assert start.status_code==200,start.text;aid=start.json()['attempt_id']
  poll=client.get('/scouting/world-attempts/'+aid).json();assert poll['state']=='approved' and poll['run_id'];assert client.get('/scouting/world-attempts/'+aid).json()['run_id']==poll['run_id']
  with db() as c:assert c.execute('SELECT count(*) FROM investigations').fetchone()[0]==1 and c.execute("SELECT count(*) FROM jobs WHERE kind='investigate'").fetchone()[0]==1
  import case_jobs
  assert case_jobs.run_case(poll['run_id'],producer=lambda *a,**kw:{'state':'blocked','bundle_path':None})=='blocked'
  retry=client.post('/investigations/'+poll['run_id']+'/resume',headers={'Idempotency-Key':'retry-human'});assert retry.status_code==200;assert client.post('/investigations/'+poll['run_id']+'/resume',headers={'Idempotency-Key':'retry-human'}).json()==retry.json()
  case2=case_engine.ingest_record(with_sources(record(1912),tmp_path),tmp_path);rev=client.get('/scouting/cases/'+case2).json()['snapshot_digest'];ch2=client.post('/scouting/cases/'+case2+'/challenge',json={'expected_revision':rev},headers={'Idempotency-Key':'denied-test'}).json();aid2=client.post('/scouting/challenges/'+ch2['challenge_id']+'/world-attempt').json()['attempt_id'];world.outcome=Denied();assert client.get('/scouting/world-attempts/'+aid2).json()['state']=='denied'
  with db() as c:assert c.execute('SELECT count(*) FROM investigations').fetchone()[0]==1
 finally:app.dependency_overrides.pop(get_world_optional,None);case_world._codes.clear()


def test_world_attempt_cancel_expiry_and_supersession_never_start_work(tmp_path,monkeypatch):
 from types import SimpleNamespace
 from publication.deps import get_world_optional
 from publication.world import DeviceStart,Tokens
 import case_world
 class FakeWorld:
  config=SimpleNamespace(accepted_acr=('synthetic',))
  def start_device(self,_):return DeviceStart(device_code='synthetic',user_code='TEST',verification_uri='https://world.example',expires_in=100,interval=0)
  def poll(self,_):return Tokens('synthetic')
  def validate_id_token(self,*a,**kw):return SimpleNamespace(iss='synthetic',sub='synthetic')
 app.dependency_overrides[get_world_optional]=lambda:FakeWorld()
 try:
  for n,how in ((1920,'cancel'),(1921,'expire'),(1922,'supersede')):
   case=case_engine.ingest_record(with_sources(record(n),tmp_path),tmp_path);revision=client.get('/scouting/cases/'+case).json()['snapshot_digest'];ch=client.post('/scouting/cases/'+case+'/challenge',json={'expected_revision':revision},headers={'Idempotency-Key':'neg-'+str(n)}).json();aid=client.post('/scouting/challenges/'+ch['challenge_id']+'/world-attempt').json()['attempt_id']
   if how=='cancel':assert client.post('/scouting/world-attempts/'+aid+'/cancel').json()['state']=='cancelled'
   elif how=='expire':
    with db() as c:c.execute('UPDATE case_world_attempts SET expires=? WHERE id=?',(now()-1,aid))
    assert client.get('/scouting/world-attempts/'+aid).json()['state']=='expired'
   else:
    with db() as c:c.execute("UPDATE case_challenges SET state='superseded' WHERE id=?",(ch['challenge_id'],))
    assert client.get('/scouting/world-attempts/'+aid).json()['state']=='superseded'
   assert client.get('/scouting/world-attempts/'+aid).json()['state']!='approved'
  with db() as c:assert c.execute('SELECT count(*) FROM investigations').fetchone()[0]==0
 finally:app.dependency_overrides.pop(get_world_optional,None);case_world._codes.clear()


def test_concrete_provider_clue_prioritizes_review_without_gate_vote(tmp_path):
 d=record(1931);stamp=datetime.datetime.now(datetime.timezone.utc).isoformat();raw=json.dumps({'result':{d['identity']['address']:{'creator_percent':'1.000000'}}}).encode();sha=hashlib.sha256(raw).hexdigest();folder=tmp_path/'snapshots';folder.mkdir();(folder/(sha+'.json')).write_bytes(raw)
 d['evidence']=[{'id':sha,'source':'snapshots/'+sha+'.json','sha256':sha,'fetched_at':stamp,'observed_at':None,'block_number':None,'kind':'live_observation','limitations':['Request URL: https://api.gopluslabs.io/api/v1/token_security/1']}];case_engine.ingest_record(d,tmp_path);case_engine.ingest_record(record(1930),tmp_path)
 rows=client.get('/scouting/cases').json()['cases'];assert [x['candidate_id'] for x in rows]==[d['candidate_id'],record(1930)['candidate_id']];assert all(x['verified_triggered_count']==0 for x in rows)
