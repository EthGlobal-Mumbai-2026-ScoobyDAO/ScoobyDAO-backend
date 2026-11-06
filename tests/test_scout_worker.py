import store,worker,case_engine,bounded_scout

def test_periodic_scout_is_opt_in_and_reconciles_only_after_capture(tmp_path,monkeypatch):
 monkeypatch.setattr(store,'DB',tmp_path/'jobs.sqlite');store.init();monkeypatch.delenv('SCOOBY_SCOUT_ENABLED',raising=False)
 assert worker.enqueue_periodic_scout() is None
 monkeypatch.setenv('SCOOBY_SCOUT_ENABLED','true');monkeypatch.setenv('SCOOBY_DISCOVERY_DB',str(tmp_path/'discovery.sqlite'));monkeypatch.setenv('SCOOBY_DISCOVERY_ROOT',str(tmp_path/'evidence'));monkeypatch.setenv('SCOOBY_SCOUT_CYCLE_BUDGET','2');monkeypatch.setenv('SCOOBY_SCOUT_HOURLY_BUDGET','2')
 calls=[]
 def fake(*args,**kwargs):calls.append(kwargs);return {'status':'no_leads','calls':0}
 monkeypatch.setattr(bounded_scout,'run_once',fake)
 worker.enqueue_periodic_scout();assert worker.enqueue_periodic_scout() is None;assert worker.work_one();assert len(calls)==1 and calls[0]['budget']==2
 with store.db() as c:assert c.execute("SELECT count(*) FROM jobs WHERE kind='case_scan' AND state='queued'").fetchone()[0]==1

def test_unconfigured_scout_reports_unavailable_and_never_fetches(tmp_path,monkeypatch):
 monkeypatch.setattr(store,'DB',tmp_path/'jobs.sqlite');store.init();monkeypatch.setenv('SCOOBY_SCOUT_ENABLED','true');monkeypatch.delenv('SCOOBY_DISCOVERY_DB',raising=False);monkeypatch.delenv('SCOOBY_DISCOVERY_ROOT',raising=False)
 monkeypatch.setattr(bounded_scout,'run_once',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('unexpected collection')))
 worker.enqueue_periodic_scout();assert worker.work_one()
 with store.db() as c:
  assert c.execute("SELECT status FROM case_sources WHERE id='discovery'").fetchone()[0]=='unavailable'
  assert c.execute("SELECT count(*) FROM jobs WHERE kind='case_scan'").fetchone()[0]==0

def test_expired_scout_lease_is_not_retried(tmp_path,monkeypatch):
 monkeypatch.setattr(store,'DB',tmp_path/'jobs.sqlite');store.init()
 with store.db() as c:
  ident=store.job(c,'scout_collect','bounded','crash-test')
  c.execute("UPDATE jobs SET state='running',lease=? WHERE id=?",(store.now()-1,ident))
 monkeypatch.setattr(bounded_scout,'run_once',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('unexpected retry')))
 assert not worker.work_one()
 with store.db() as c:assert c.execute('SELECT state FROM jobs WHERE id=?',(ident,)).fetchone()[0]=='failed'
