"""Six distinct synthetic cases: report multiplicity and honest partial coverage."""
import base64,datetime,json
from pathlib import Path
import pytest,httpx
from fastapi.testclient import TestClient
import app as app_module
from app import app
import case_engine,case_jobs,case_graph,worker,store
from store import db
from test_cases import result
import test_case_research as fixture

@pytest.fixture(autouse=True)
def state(tmp_path,monkeypatch):
 monkeypatch.delenv('SCOOBY_CASE_MODEL_MAX_CALLS',raising=False);monkeypatch.setattr(store,'DB',tmp_path/'state.sqlite3');monkeypatch.setattr(case_jobs,'DATA',tmp_path);monkeypatch.setattr(case_graph,'DATA',tmp_path);monkeypatch.setattr(worker,'DATA',tmp_path);monkeypatch.setattr(app_module,'DATA',tmp_path);store.init();__import__('publication.db',fromlist=['init']).init()

def test_six_distinct_synthetic_cases_create_separate_partial_drafts(tmp_path,monkeypatch):
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(4,r));created=[]
 for n in range(1,7):
  address='0x'+format(n,'02x')*20;monkeypatch.setattr(fixture,'ADDR',address);monkeypatch.setattr(fixture,'CANDIDATE','1:'+address);snap=fixture.captured_snapshot(fixture.source_payloads());record=snap['record'];record['mode']='live';record['identity']['symbol']='SYNTH-'+str(n);stamp=datetime.datetime.now(datetime.timezone.utc).isoformat();root=tmp_path/('source-'+str(n));root.mkdir()
  for e in record['evidence']:
   e.update(kind='live_observation',observed_at=stamp,fetched_at=stamp);path=root/e['source'];path.parent.mkdir(exist_ok=True);path.write_bytes(base64.b64decode(snap['evidence'][e['source']]))
  created.append(case_engine.ingest_record(record,root))
 client=TestClient(app);monkeypatch.setattr(httpx,'Client',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('network forbidden')))
 for _ in range(30):
  if not worker.work_one():break
 reports=client.get('/reports').json();assert len(reports)==6 and len({r['candidate_id'] for r in reports})==6 and len({r['report_id'] for r in reports})==6 and {r['case_id'] for r in reports}==set(created)
 assert all(r['run_status']=='partial' and r['mode']=='historical_replay' and r['review']['status']=='pending' and r['release']['status']=='unavailable' for r in reports)
 assert all(len(r['pillars'])==5 and r['pillars']['statistical_risk']['status']=='unavailable' for r in reports)
 with db() as c:assert c.execute('SELECT count(*) FROM investigations').fetchone()[0]==6 and c.execute('SELECT count(*) FROM reports').fetchone()[0]==6
 with db() as c:broken=Path(c.execute('SELECT path FROM reports LIMIT 1').fetchone()[0])/'report.json'
 broken.write_bytes(b'corrupt synthetic report')
 listed=client.get('/reports').json();assert len(listed)==6 and sum(x['metadata_status']=='unavailable' for x in listed)==1 and sum(x['metadata_status']=='available' for x in listed)==5
 bad=next(x for x in listed if x['metadata_status']=='unavailable');assert bad['identity'] is None and bad['pillars'] is None and bad['review']['status']=='unknown'
