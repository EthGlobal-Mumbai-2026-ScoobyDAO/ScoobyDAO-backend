"""Durable Terra reservations: all inputs and outputs here are synthetic."""
import json
import pytest
import store,case_model,case_engine
from store import db,now

@pytest.fixture(autouse=True)
def state(tmp_path,monkeypatch):
 monkeypatch.setattr(store,'DB',tmp_path/'state.sqlite3');monkeypatch.setattr(case_engine,'policy_digest',lambda:'policy');store.init()
 with db() as c:
  c.execute('INSERT INTO candidates VALUES(?,?,?)',('1:synthetic','{}',now()))
  c.execute('INSERT INTO selections VALUES(?,?,?,?,?,?,?)',('sel','1:synthetic','qualified','test','synthetic',now(),'sel-idem'))
  c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?)',('run','1:synthetic','sel','running',now(),'run-idem'))
  c.execute('INSERT INTO case_snapshots VALUES(?,?,?,?,?,?,?,?)',('snap','1:synthetic','{}','{}','policy','{}',now(),now()+1000))
  c.execute('INSERT INTO cases VALUES(?,?,?,?,?)',('case','1:synthetic','snap','investigating',now()))
  c.execute('INSERT INTO case_decisions VALUES(?,?,?,?,?,?,?,?)',('decision','case','snap','policy','auto_research',json.dumps({'max_source_requests':0,'max_model_calls':1}),'run',now()))

def start_event():return {'stage':'reasoning','state':'started','input_sha256':'a'*64,'prompt_sha256':'b'*64,'schema_sha256':'c'*64,'model':'gpt-6.1-terra','max_output_tokens':4096,'max_context_chars':120000}
def test_reservation_survives_restart_and_refuses_duplicate():
 ledger=case_model.Ledger('run','decision','snap');ledger(start_event())
 with pytest.raises(case_model.ModelStageBlocked):case_model.Ledger('run','decision','snap').checkpoint()
 with pytest.raises(case_model.ModelStageBlocked):ledger(start_event())
 with db() as c:assert c.execute('SELECT count(*) FROM case_model_stages').fetchone()[0]==1

def test_completed_checkpoint_is_bound_and_reusable():
 ledger=case_model.Ledger('run','decision','snap');started=start_event();ledger(started)
 checkpoint={'profile':'scooby.reasoning-checkpoint/1','model':started['model'],'input_sha256':started['input_sha256'],'prompt_sha256':started['prompt_sha256'],'schema_sha256':started['schema_sha256'],'payload':{'synthetic':True}}
 completed={**started,'state':'completed','checkpoint':checkpoint,'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15,'secret':'never save'}};ledger(completed)
 assert case_model.Ledger('run','decision','snap').checkpoint()==checkpoint
 with db() as c:
  row=c.execute('SELECT * FROM case_model_stages').fetchone();assert json.loads(row['usage'])=={'prompt_tokens':10,'completion_tokens':5,'total_tokens':15};assert c.execute("SELECT count(*) FROM events WHERE kind='model_stage_started'").fetchone()[0]==1

def test_cancelled_and_zero_budget_never_reserve():
 ledger=case_model.Ledger('run','decision','snap')
 with db() as c:c.execute("UPDATE investigations SET status='cancelled' WHERE id='run'")
 with pytest.raises(case_model.ModelStageBlocked):ledger(start_event())
 with db() as c:
  c.execute("UPDATE investigations SET status='running' WHERE id='run'");c.execute('UPDATE case_decisions SET budget=? WHERE id=?',(json.dumps({'max_source_requests':0,'max_model_calls':0}),'decision'))
 with pytest.raises(case_model.ModelStageBlocked):ledger(start_event())
 with db() as c:assert c.execute('SELECT count(*) FROM case_model_stages').fetchone()[0]==0


def test_failed_attempt_is_consumed_and_secret_error_is_not_recorded():
 ledger=case_model.Ledger('run','decision','snap');ledger(start_event());ledger({'stage':'reasoning','state':'failed','reason':'incomplete_output','raw_error':'synthetic-secret-never-log'})
 with pytest.raises(case_model.ModelStageBlocked):case_model.Ledger('run','decision','snap').checkpoint()
 with db() as c:
  row=c.execute('SELECT state FROM case_model_stages').fetchone();assert row['state']=='failed'
  text=' '.join(r[0] for r in c.execute('SELECT detail FROM events'));assert 'incomplete_output' in text and 'synthetic-secret-never-log' not in text

def test_changed_binding_and_checkpoint_cannot_spend_again():
 ledger=case_model.Ledger('run','decision','snap');start=start_event();ledger(start)
 checkpoint={'profile':'scooby.reasoning-checkpoint/1','model':start['model'],'input_sha256':start['input_sha256'],'prompt_sha256':start['prompt_sha256'],'schema_sha256':start['schema_sha256'],'payload':{}}
 bad={**start,'state':'completed','checkpoint':checkpoint,'schema_sha256':'d'*64}
 with pytest.raises(case_model.ModelStageBlocked):ledger(bad)
 with pytest.raises(case_model.ModelStageBlocked):case_model.Ledger('run','decision','snap').checkpoint()


def test_source_progress_is_truthful_even_with_zero_model_budget():
 with db() as c:c.execute('UPDATE case_decisions SET budget=? WHERE id=?',(json.dumps({'max_source_requests':0,'max_model_calls':0}),'decision'))
 ledger=case_model.Ledger('run','decision','snap');ledger({'stage':'sources','state':'started','mode':'captured_replay'});ledger({'stage':'source','name':'market','state':'captured_replay','url':'synthetic-secret-url'});ledger({'stage':'sources','state':'completed','attempts':0,'captured':1})
 with db() as c:
  events=[dict(r) for r in c.execute('SELECT kind,detail FROM events ORDER BY seq')];assert len(events)==3 and all(e['kind'].startswith('research_stage_') for e in events);assert 'synthetic-secret-url' not in str(events);assert c.execute('SELECT count(*) FROM case_model_stages').fetchone()[0]==0


def test_grounding_diagnostic_exposes_category_not_model_text():
 ledger=case_model.Ledger('run','decision','snap');ledger(start_event());ledger({'stage':'reasoning','state':'failed','reason':'invalid_or_unlinked_output','detail':'pillar onchain: unsupported numeric literals: 123456789 SECRET'})
 with db() as c:
  event=json.loads(c.execute("SELECT detail FROM events WHERE kind='model_stage_failed'").fetchone()[0]);assert event['diagnostic']=='unsupported_numeric_literal' and '123456789' not in json.dumps(event) and 'SECRET' not in json.dumps(event)
