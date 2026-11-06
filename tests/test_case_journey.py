"""End-to-end case journeys with synthetic verifier and mock-only source transport."""
import json
from types import SimpleNamespace
import httpx,pytest
from fastapi.testclient import TestClient
import app as app_module
from app import app
from publication.deps import get_world_optional
from publication.world import DeviceStart,Tokens
from store import db
import store,worker,case_jobs,case_engine,case_world
from test_cases import record,with_sources,result
from test_case_research import source_payloads,mock_provider,ADDR
from modules.investigation.case_research import run_case as real_producer

@pytest.fixture(autouse=True)
def state(tmp_path,monkeypatch):
 monkeypatch.setattr(store,'DB',tmp_path/'state.sqlite3');monkeypatch.setattr(case_jobs,'DATA',tmp_path);monkeypatch.setattr(worker,'DATA',tmp_path);monkeypatch.setattr(app_module,'DATA',tmp_path);store.init()
 yield
 app.dependency_overrides.pop(get_world_optional,None);case_world._codes.clear()

@pytest.mark.parametrize('route',['automatic','world'])
def test_both_routes_generate_and_link_report_using_synthetic_dependencies(tmp_path,monkeypatch,route):
 # Only this synthetic test replaces the decision's zero-source producer input with
 # MockTransport captures. No real provider or model is contacted.
 original=case_jobs.run_case;calls=[];transport=mock_provider(source_payloads(),calls)
 def synthetic_runner(run_id):
  def invoke(case,out,**kwargs):return real_producer(case,out,max_source_requests=5,transport=transport,cancelled=kwargs['cancelled'])
  return original(run_id,producer=invoke)
 monkeypatch.setattr(case_jobs,'run_case',synthetic_runner)
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(4 if route=='automatic' else 1,r))
 d=with_sources(record(int(ADDR[2:],16)),tmp_path);case=case_engine.ingest_record(d,tmp_path);client=TestClient(app)
 if route=='world':
  class FakeWorld:
   config=SimpleNamespace(accepted_acr=('synthetic',))
   def start_device(self,_):return DeviceStart(device_code='synthetic',user_code='TEST',verification_uri='https://world.example',expires_in=100,interval=0)
   def poll(self,_):return Tokens('synthetic')
   def validate_id_token(self,*a,**kw):return SimpleNamespace(iss='synthetic',sub='synthetic')
  app.dependency_overrides[get_world_optional]=lambda:FakeWorld()
  rev=client.get('/scouting/cases/'+case).json()['snapshot_digest'];ch=client.post('/scouting/cases/'+case+'/challenge',json={'expected_revision':rev},headers={'Idempotency-Key':'synthetic-challenge'}).json();aid=client.post('/scouting/challenges/'+ch['challenge_id']+'/world-attempt').json()['attempt_id'];assert client.get('/scouting/world-attempts/'+aid).json()['state']=='approved'
 # Process both queued admission and investigation, then render the generated draft.
 for _ in range(8):
  if not worker.work_one():break
 case_view=client.get('/scouting/cases/'+case).json();research=case_view['research'];assert research['status']=='partial' and research['report_id'] and research['report_version'];assert case_view['lane']=='research_partial'
 reports=client.get('/reports').json();assert len(reports)==1 and reports[0]['case_id']==case and reports[0]['candidate_id']==d['candidate_id'];assert reports[0]['review']['status']=='pending'
 artifact=client.get('/reports/'+research['report_id']+'/'+research['report_version']+'/artifacts').json();assert artifact.get('artifacts',{}).get('html',{}).get('availability')=='available',artifact;assert len(calls)==5
 with db() as c:assert c.execute('SELECT count(*) FROM investigations').fetchone()[0]==1 and c.execute('SELECT count(*) FROM reports').fetchone()[0]==1


def test_real_producer_at_zero_budget_blocks_without_fabricated_report(tmp_path,monkeypatch):
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(4,r))
 d=with_sources(record(int(ADDR[2:],16)),tmp_path);case=case_engine.ingest_record(d,tmp_path)
 with db() as c:decision=c.execute('SELECT id FROM case_decisions WHERE case_id=?',(case,)).fetchone()['id']
 run=case_engine.start_decision(decision);assert case_jobs.run_case(run)=='blocked'
 with db() as c:
  assert c.execute('SELECT status FROM investigations WHERE id=?',(run,)).fetchone()[0]=='blocked'
  assert c.execute('SELECT count(*) FROM reports').fetchone()[0]==0
  assert {r[0] for r in c.execute('SELECT status FROM pillars WHERE run_id=?',(run,))}=={'unavailable'}
