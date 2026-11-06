"""Composed case/Terra tests with synthetic sources, World and OpenAI client only."""
import base64,datetime,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
import app as app_module
from app import app
from publication.deps import get_world_optional
from publication.world import DeviceStart,Tokens
import store,worker,case_jobs,case_engine,case_world
from store import db
from test_cases import result
from test_case_research import captured_snapshot,source_payloads
from test_case_terra_reasoning import FakeClient

@pytest.fixture(autouse=True)
def state(tmp_path,monkeypatch):
 monkeypatch.setenv('SCOOBY_REPORT_RELEASE','all')
 monkeypatch.setenv('SCOOBY_CASE_MODEL_MAX_CALLS','1');monkeypatch.setattr(store,'DB',tmp_path/'state.sqlite3');monkeypatch.setattr(case_jobs,'DATA',tmp_path);monkeypatch.setattr(worker,'DATA',tmp_path);monkeypatch.setattr(app_module,'DATA',tmp_path);store.init()
 yield
 app.dependency_overrides.pop(get_world_optional,None);case_world._codes.clear()

def seed(tmp_path,monkeypatch,route):
 snap=captured_snapshot(source_payloads());record=snap['record'];record['mode']='live';stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
 for e in record['evidence']:
  e.update(kind='live_observation',observed_at=stamp,fetched_at=stamp);path=tmp_path/e['source'];path.parent.mkdir(exist_ok=True);path.write_bytes(base64.b64decode(snap['evidence'][e['source']]))
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(4 if route=='automatic' else 1,r));case=case_engine.ingest_record(record,tmp_path);client=TestClient(app)
 from admin_support import session_headers
 client.headers.update(session_headers('synthetic','synthetic-admin','case_investigation'))
 if route=='world':
  class FakeWorld:
   config=SimpleNamespace(accepted_acr=('synthetic',))
   def start_device(self,_):return DeviceStart(device_code='synthetic',user_code='TEST',verification_uri='https://auth.world.org/device',expires_in=100,interval=0)
   def authorize_case_admin(self,identity,binding):return True
   def poll(self,_):return Tokens('synthetic')
   def validate_id_token(self,*a,**kw):return SimpleNamespace(iss='synthetic',sub='synthetic-admin')
  app.dependency_overrides[get_world_optional]=lambda:FakeWorld();revision=client.get('/scouting/cases/'+case).json()['snapshot_digest'];challenge=client.post('/scouting/cases/'+case+'/challenge',json={'expected_revision':revision},headers={'Idempotency-Key':'synthetic-admin'}).json();aid=client.post('/scouting/challenges/'+challenge['challenge_id']+'/world-attempt').json()['attempt_id'];assert client.get('/scouting/world-attempts/'+aid).json()['state']=='approved'
 return case,client

@pytest.mark.parametrize('route',['automatic','world'])
def test_one_shared_terra_call_flows_from_case_to_rendered_report(tmp_path,monkeypatch,route):
 case,client=seed(tmp_path,monkeypatch,route);fake=FakeClient();actual=case_jobs.run_case;monkeypatch.setattr(case_jobs,'run_case',lambda rid:actual(rid,model_client=fake))
 for _ in range(8):
  if not worker.work_one():break
 view=client.get('/scouting/cases/'+case).json();run=view['research'];assert run['status']=='partial' and run['budget']['max_model_calls']==1;assert len(fake.calls)==1
 report=client.get('/reports').json()[0];assert report['case_id']==case and report['review']['status']=='pending'
 artifacts=client.get('/reports/'+run['report_id']+'/'+run['report_version']+'/artifacts').json();html=client.get(artifacts['artifacts']['html']['url']).text;assert 'SYNTHETIC' in html
 events=client.get('/investigations/'+run['run_id']+'/events').json();model=[e for e in events if e['kind'].startswith('model_stage_')];assert sum(e['kind']=='model_stage_started' for e in model)==1
 done=next(json.loads(e['detail']) for e in model if e['kind']=='model_stage_completed');assert done['usage']['total_tokens']==650
 assert len([e for e in model if json.loads(e['detail']).get('stage')=='pillar'])==5
 with db() as c:
  stage=c.execute('SELECT * FROM case_model_stages').fetchone();assert stage['state']=='completed' and json.loads(stage['checkpoint'])['model']=='gpt-6.1-terra'

@pytest.mark.parametrize('route',['automatic','world'])
def test_checkpoint_survives_crash_and_never_reissues_model_call(tmp_path,monkeypatch,route):
 case,client=seed(tmp_path,monkeypatch,route)
 if route=='automatic':
  with db() as c:did=c.execute('SELECT id FROM case_decisions WHERE case_id=?',(case,)).fetchone()['id']
  run=case_engine.start_decision(did)
 else:run=client.get('/scouting/cases/'+case).json()['research']['run_id']
 from modules.investigation.case_research import run_case as real_producer
 fake=FakeClient()
 def crash_after_checkpoint(case,out,**kwargs):
  callback=kwargs['stage_callback']
  def interrupt(ev):
   callback(ev)
   if ev.get('stage')=='reasoning' and ev.get('state')=='completed':raise RuntimeError('synthetic crash after checkpoint')
  kwargs['stage_callback']=interrupt
  return real_producer(case,out,**kwargs)
 with pytest.raises(Exception):case_jobs.run_case(run,producer=crash_after_checkpoint,model_client=fake)
 assert len(fake.calls)==1
 assert case_jobs.run_case(run,model_client=fake)=='partial report generated' and len(fake.calls)==1
 with db() as c:assert c.execute('SELECT count(*) FROM reports').fetchone()[0]==1


def test_incomplete_model_output_is_consumed_and_never_retried(tmp_path,monkeypatch):
 case,client=seed(tmp_path,monkeypatch,'automatic')
 with db() as c:did=c.execute('SELECT id FROM case_decisions WHERE case_id=?',(case,)).fetchone()['id']
 run=case_engine.start_decision(did);fake=FakeClient(finish='length')
 assert case_jobs.run_case(run,model_client=fake)=='partial report generated' and len(fake.calls)==1
 with db() as c:
  assert c.execute('SELECT state FROM case_model_stages').fetchone()[0]=='failed';report=Path(c.execute('SELECT path FROM reports').fetchone()[0]);doc=json.loads((report/'report.json').read_text());assert doc['assessment']['status']=='not_assessed';assert not any(a['kind']=='reasoning' for a in doc['artifacts'])
  failed=[json.loads(r[0]) for r in c.execute("SELECT detail FROM events WHERE kind='model_stage_failed'")];assert failed[-1]['reason']=='incomplete_output'
 assert case_jobs.run_case(run,model_client=fake)=='partial report generated' and len(fake.calls)==1

def test_cancel_during_model_call_consumes_attempt_and_installs_no_report(tmp_path,monkeypatch):
 case,_=seed(tmp_path,monkeypatch,'automatic')
 with db() as c:did=c.execute('SELECT id FROM case_decisions WHERE case_id=?',(case,)).fetchone()['id']
 run=case_engine.start_decision(did)
 def cancel():
  with db() as c:c.execute("UPDATE investigations SET status='cancelled' WHERE id=?",(run,))
 fake=FakeClient(after=cancel);assert case_jobs.run_case(run,model_client=fake)=='cancelled' and len(fake.calls)==1
 with db() as c:assert c.execute('SELECT state FROM case_model_stages').fetchone()[0]=='cancelled' and c.execute('SELECT count(*) FROM reports').fetchone()[0]==0


def test_worker_blocks_ambiguous_prior_reservation_without_retry(tmp_path,monkeypatch):
 import case_model
 from test_case_model import start_event
 case,_=seed(tmp_path,monkeypatch,'automatic')
 with db() as c:decision=c.execute('SELECT * FROM case_decisions WHERE case_id=?',(case,)).fetchone()
 run=case_engine.start_decision(decision['id']);case_model.Ledger(run,decision['id'],decision['snapshot_id'])(start_event())
 for _ in range(4):
  if not worker.work_one():break
 with db() as c:
  assert c.execute('SELECT status FROM investigations WHERE id=?',(run,)).fetchone()[0]=='blocked'
  assert c.execute("SELECT state FROM jobs WHERE kind='investigate' AND ref=?",(run,)).fetchone()[0]=='failed'
  data=[json.loads(x[0]) for x in c.execute("SELECT detail FROM events WHERE run_id=? AND kind='model_stage_blocked'",(run,))];assert data[-1]['reason']=='attempt_consumed_or_authorization_changed'
