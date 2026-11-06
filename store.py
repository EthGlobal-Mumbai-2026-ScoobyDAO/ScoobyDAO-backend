from __future__ import annotations
import hashlib, json, os, sqlite3, time, uuid
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv('SCOOBY_DATA', str(ROOT/'data'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA/'state.sqlite3'
PILLARS = ('microstructure','onchain','fundamentals','statistical_risk','technical_health')
def now(): return time.time()
def ident(): return uuid.uuid4().hex
def dumps(x): return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',',':'), allow_nan=False)
def digest(b): return hashlib.sha256(b).hexdigest()
@contextmanager
def db():
 c=sqlite3.connect(DB, timeout=30); c.row_factory=sqlite3.Row
 c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA busy_timeout=30000')
 try:
  yield c; c.commit()
 except: c.rollback(); raise
 finally: c.close()
def init():
 with db() as c:
  c.executescript('''
  PRAGMA journal_mode=WAL;
  CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS selections(id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidates(id), kind TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL, idem TEXT UNIQUE NOT NULL);
  CREATE TABLE IF NOT EXISTS investigations(id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidates(id), selection_id TEXT NOT NULL REFERENCES selections(id), status TEXT NOT NULL, created REAL NOT NULL, idem TEXT UNIQUE NOT NULL);
  CREATE TABLE IF NOT EXISTS pillars(run_id TEXT NOT NULL REFERENCES investigations(id), pillar TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL, PRIMARY KEY(run_id,pillar));
  CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT NOT NULL, ref TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, available REAL NOT NULL, lease REAL, error TEXT, idem TEXT UNIQUE NOT NULL, created REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS reports(id TEXT NOT NULL, version TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES investigations(id), sha256 TEXT NOT NULL, path TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(id,version));
  CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY, report_id TEXT NOT NULL, version TEXT NOT NULL, sha256 TEXT NOT NULL, decision TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL, idem TEXT UNIQUE NOT NULL, FOREIGN KEY(report_id,version) REFERENCES reports(id,version));
  CREATE TABLE IF NOT EXISTS reasoning_inputs(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES investigations(id), pillar TEXT NOT NULL, evidence TEXT NOT NULL, output TEXT, status TEXT NOT NULL, created REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS budget_reservations(job_id TEXT PRIMARY KEY, created REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS render_manifests(job_id TEXT PRIMARY KEY REFERENCES jobs(id), sha256 TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS case_snapshots(id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL,record TEXT NOT NULL,evidence TEXT NOT NULL,policy_digest TEXT NOT NULL,assessment TEXT NOT NULL,evaluated REAL NOT NULL,expires REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL UNIQUE,current_snapshot TEXT NOT NULL REFERENCES case_snapshots(id),state TEXT NOT NULL,updated REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS case_decisions(id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES cases(id),snapshot_id TEXT NOT NULL REFERENCES case_snapshots(id),policy_digest TEXT NOT NULL,action TEXT NOT NULL,budget TEXT NOT NULL,run_id TEXT,created REAL NOT NULL,UNIQUE(case_id,snapshot_id,policy_digest,action));
  CREATE TABLE IF NOT EXISTS case_challenges(id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES cases(id),snapshot_id TEXT NOT NULL REFERENCES case_snapshots(id),policy_digest TEXT NOT NULL,action TEXT NOT NULL,nonce TEXT NOT NULL UNIQUE,state TEXT NOT NULL,expires REAL NOT NULL,created REAL NOT NULL,idem TEXT NOT NULL UNIQUE);
  CREATE TABLE IF NOT EXISTS case_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT NOT NULL,kind TEXT NOT NULL,detail TEXT NOT NULL,created REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS case_scan_cursor(name TEXT PRIMARY KEY,position INTEGER NOT NULL);
  CREATE TABLE IF NOT EXISTS case_sources(id TEXT PRIMARY KEY,status TEXT NOT NULL,detail TEXT NOT NULL,updated REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS case_leads(id TEXT PRIMARY KEY,provider TEXT NOT NULL,candidate_id TEXT,origin TEXT,created REAL NOT NULL,FOREIGN KEY(candidate_id) REFERENCES candidates(id));
  CREATE TABLE IF NOT EXISTS heartbeats(name TEXT PRIMARY KEY, seen REAL NOT NULL, detail TEXT NOT NULL);
  ''')
  c.execute("INSERT OR IGNORE INTO case_sources VALUES('discovery','unavailable','Local discovery store not yet synchronized.',?)",(now(),))
  c.execute("INSERT OR IGNORE INTO case_sources VALUES('reddit','unavailable','SearchApi Reddit adapter is not integrated; retention/deletion lifecycle is not implemented.',?)",(now(),))
def row(r): return dict(r) if r else None
def event(c, rid, kind, detail): c.execute('INSERT INTO events(run_id,kind,detail,created) VALUES(?,?,?,?)',(rid,kind,detail,now()))
def job(c, kind, ref, key):
 old=c.execute('SELECT * FROM jobs WHERE idem=?',(key,)).fetchone()
 if old:
  if old['kind']!=kind or old['ref']!=ref: raise ValueError('idempotency key reused with different request')
  return old['id']
 i=ident(); c.execute('INSERT INTO jobs(id,kind,ref,state,available,idem,created) VALUES(?,?,?,?,?,?,?)',(i,kind,ref,'queued',now(),key,now())); return i
init()
