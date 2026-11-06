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
  CREATE TABLE IF NOT EXISTS heartbeats(name TEXT PRIMARY KEY, seen REAL NOT NULL, detail TEXT NOT NULL);
  ''')
def row(r): return dict(r) if r else None
def event(c, rid, kind, detail): c.execute('INSERT INTO events(run_id,kind,detail,created) VALUES(?,?,?,?)',(rid,kind,detail,now()))
def job(c, kind, ref, key):
 old=c.execute('SELECT * FROM jobs WHERE idem=?',(key,)).fetchone()
 if old:
  if old['kind']!=kind or old['ref']!=ref: raise ValueError('idempotency key reused with different request')
  return old['id']
 i=ident(); c.execute('INSERT INTO jobs(id,kind,ref,state,available,idem,created) VALUES(?,?,?,?,?,?,?)',(i,kind,ref,'queued',now(),key,now())); return i
init()
