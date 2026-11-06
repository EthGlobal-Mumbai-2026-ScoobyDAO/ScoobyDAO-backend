"""Synthetic, server-authorizer-only Graph binding tests; no network or model calls."""
import hashlib,json,datetime
from pathlib import Path
import pytest
import case_graph,case_engine,case_jobs,store
from store import db,now
from test_cases import record,result
from test_graph_history import build,CANDIDATE

@pytest.fixture(autouse=True)
def state(tmp_path,monkeypatch):
 monkeypatch.delenv('SCOOBY_CASE_MODEL_MAX_CALLS',raising=False);monkeypatch.setattr(store,'DB',tmp_path/'state.sqlite3');monkeypatch.setattr(case_graph,'DATA',tmp_path);monkeypatch.setattr(case_jobs,'DATA',tmp_path);store.init()

def decision_for_fixture(tmp_path,monkeypatch):
 d=record(int(CANDIDATE.split(':')[1][2:],16));stamp=datetime.datetime.now(datetime.timezone.utc).isoformat();folder=tmp_path/'snapshots';folder.mkdir(exist_ok=True)
 for i in range(4):
  raw=json.dumps({'synthetic_test':i}).encode();sha=hashlib.sha256(raw).hexdigest();(folder/(sha+'.json')).write_bytes(raw);d['evidence'].append({'id':sha,'source':'snapshots/'+sha+'.json','sha256':sha,'observed_at':stamp,'fetched_at':stamp,'block_number':None,'kind':'live_observation','limitations':['synthetic test evidence only']})
 monkeypatch.setattr(case_engine,'evaluate',lambda r,_:result(4,r));case=case_engine.ingest_record(d,tmp_path)
 with db() as c:decision=c.execute('SELECT * FROM case_decisions WHERE case_id=?',(case,)).fetchone()
 run=case_engine.start_decision(decision['id']);return decision,run

def selection_for(source):
 manifest=json.loads((source/'manifest.json').read_bytes());raw=(source/'manifest.json').read_bytes();evidence={'capture_manifest':raw};selection={'profile':'scooby.graph-source-selection/1','candidate_id':CANDIDATE,'source_type':'graph_token_day','subgraph_id':manifest['subgraph_id'],'window':{'start_inclusive_utc':manifest['start_inclusive_utc'],'end_exclusive_utc':manifest['end_exclusive_utc']},'selection_reason':'SYNTHETIC: selected saved capture for test','discovery_status':'not_provided','evidence':[{'id':'capture_manifest','sha256':hashlib.sha256(raw).hexdigest()}]};return selection,evidence

def admin(binding,descriptor):return {'binding_id':binding,'role':'admin','issuer':'synthetic-test-only','subject_hash':'a'*64,'verified_at':now()-1,'expires_at':now()+600}

def test_graph_binding_is_decision_scoped_immutable_and_drives_worker(tmp_path,monkeypatch):
 decision,run=decision_for_fixture(tmp_path,monkeypatch);source,model,technical=build(tmp_path);selection,evidence=selection_for(source)
 with pytest.raises(PermissionError):case_graph.install(decision['id'],source,model,selection,evidence,historical_horizon_days=4,technical_sha256=technical)
 grant=case_graph.install(decision['id'],source,model,selection,evidence,historical_horizon_days=4,technical_sha256=technical,authorizer=admin)
 assert grant['candidate_id']==CANDIDATE and grant['historical_horizon_days']==4
 assert case_jobs.run_case(run)=='partial report generated'
 with db() as c:
  report=Path(c.execute('SELECT path FROM reports').fetchone()[0]);doc=json.loads((report/'report.json').read_bytes());assert doc['candidate_id']==CANDIDATE and doc['mode']=='historical_replay';assert doc['pillars']['statistical_risk']['status']=='partial'
  assert c.execute('SELECT count(*) FROM case_graph_bindings').fetchone()[0]==1
 # Original legacy horizon is preserved; no new horizon was selected by worker.
 assert any(a['kind']=='case_lineage' for a in doc['artifacts'])
 from fastapi.testclient import TestClient
 from app import app
 client=TestClient(app);item=client.get('/reports').json()[0];assert item['run_id']==run and item['case_id']==decision['case_id'] and item['graph_source']['binding_id']==grant['binding_id'];assert item['graph_source']['selection']['discovery_status']=='not_provided' and 'selection_reason' not in item['graph_source']['selection'];assert item['pillars']['statistical_risk']['status']=='partial' and item['release']['status']=='unavailable'
 with db() as c:c.execute("UPDATE jobs SET state='failed' WHERE kind='render'")
 artifacts=client.get('/reports/'+item['report_id']+'/'+item['report_version']+'/artifacts').json();assert artifacts['render_status']=='failed' and artifacts['artifacts']['html']['availability']=='unavailable'

def test_graph_binding_rejects_identity_horizon_and_mutation(tmp_path,monkeypatch):
 decision,run=decision_for_fixture(tmp_path,monkeypatch);source,model,technical=build(tmp_path);selection,evidence=selection_for(source)
 with pytest.raises(ValueError,match='horizon'):case_graph.install(decision['id'],source,model,selection,evidence,historical_horizon_days=5,technical_sha256=technical,authorizer=admin)
 bad=dict(selection,candidate_id='1:0x'+'34'*20)
 with pytest.raises(ValueError,match='identity'):case_graph.install(decision['id'],source,model,bad,evidence,historical_horizon_days=4,technical_sha256=technical,authorizer=admin)
 grant=case_graph.install(decision['id'],source,model,selection,evidence,historical_horizon_days=4,technical_sha256=technical,authorizer=admin)
 target=tmp_path/'graph-bindings'/grant['binding_id']/'capture'/'token_daily.json';target.write_bytes(b'[]')
 with pytest.raises(ValueError,match='changed'):case_jobs.run_case(run)
 with db() as c:assert c.execute('SELECT count(*) FROM reports').fetchone()[0]==0


def test_graph_grant_requires_bound_admin_receipt_and_rejects_expiry(tmp_path,monkeypatch):
 decision,run=decision_for_fixture(tmp_path,monkeypatch);source,model,technical=build(tmp_path);selection,evidence=selection_for(source)
 def wrong(binding,descriptor):return {'binding_id':'0'*64,'role':'admin','issuer':'synthetic','subject_hash':'a'*64,'verified_at':now()-1,'expires_at':now()+100}
 with pytest.raises(PermissionError):case_graph.install(decision['id'],source,model,selection,evidence,historical_horizon_days=4,technical_sha256=technical,authorizer=wrong)
 grant=case_graph.install(decision['id'],source,model,selection,evidence,historical_horizon_days=4,technical_sha256=technical,authorizer=admin)
 with db() as c:
  row=c.execute('SELECT receipt FROM case_graph_bindings').fetchone();receipt=json.loads(row[0]);receipt['expires_at']=now()-1;c.execute('UPDATE case_graph_bindings SET receipt=?',(json.dumps(receipt),))
 assert case_jobs.run_case(run)=='blocked'
 renewed=case_graph.install(decision['id'],source,model,selection,evidence,historical_horizon_days=4,technical_sha256=technical,authorizer=admin);assert renewed['binding_id']==grant['binding_id'];assert case_jobs.run_case(run)=='partial report generated'


def test_graph_discovery_claim_requires_separate_evidence(tmp_path,monkeypatch):
 decision,_=decision_for_fixture(tmp_path,monkeypatch);source,model,technical=build(tmp_path);selection,evidence=selection_for(source);selection['discovery_status']='performed'
 with pytest.raises(ValueError,match='separate bound evidence'):case_graph.install(decision['id'],source,model,selection,evidence,historical_horizon_days=4,technical_sha256=technical,authorizer=admin)


def test_empty_graph_capture_remains_source_scoped_and_blocked(tmp_path,monkeypatch):
 from fastapi.testclient import TestClient
 from app import app
 decision,run=decision_for_fixture(tmp_path,monkeypatch);source,_,_=build(tmp_path);manifest=json.loads((source/'manifest.json').read_bytes());page=json.dumps({'data':{'tokenDayDatas':[]}},indent=2).encode();(source/'graph-response-0001.json').write_bytes(page);manifest['requests'][0]['sha256']=hashlib.sha256(page).hexdigest();rows=b'[]';(source/'token_daily.json').write_bytes(rows);manifest['raw_sha256']=hashlib.sha256(rows).hexdigest();manifest['row_count']=0;manifest['missing_utc_dates']=['2020-01-01','2020-01-02','2020-01-03'];(source/'manifest.json').write_text(json.dumps(manifest))
 selection,evidence=selection_for(source);case_graph.install(decision['id'],source,None,selection,evidence,authorizer=admin)
 assert case_jobs.run_case(run)=='blocked';detail=TestClient(app).get('/investigations/'+run).json();assert detail['status']=='blocked' and detail['graph_source']['capture_status']['status']=='empty' and detail['graph_source']['capture_status']['rows']==0
 with db() as c:assert c.execute('SELECT count(*) FROM reports').fetchone()[0]==0
