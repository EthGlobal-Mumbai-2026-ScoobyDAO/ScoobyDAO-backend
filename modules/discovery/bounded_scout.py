"""Opt-in bounded discovery cycle; never invokes refresh, LP, market, or model collectors."""
import datetime as dt
import hashlib
import json
import sqlite3
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import continuous_pilot
import live_pilot

MIN_INTERVAL=300
WINDOW=3600
HOSTS={'api.geckoterminal.com','api.dexscreener.com','api.gopluslabs.io'}

@contextmanager
def _ledger(path):
 c=sqlite3.connect(path,timeout=5)
 try:
  c.executescript('''CREATE TABLE IF NOT EXISTS scout_requests(id INTEGER PRIMARY KEY,provider TEXT NOT NULL,reserved REAL NOT NULL,status TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS scout_cooldowns(provider TEXT PRIMARY KEY,until REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS scout_cycles(id INTEGER PRIMARY KEY,started REAL NOT NULL,status TEXT NOT NULL);''')
  with c:yield c
 finally:c.close()

class ReservedFetcher:
 def __init__(self,root,budget,ledger,hourly_limit):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.budget=budget;self.calls=0;self.ledger=ledger;self.hourly_limit=hourly_limit
 def get(self,url):
  parsed=urlsplit(url);host=parsed.hostname
  if parsed.scheme!='https' or host not in HOSTS or parsed.username or parsed.password or parsed.port or parsed.fragment:raise ValueError('provider URL rejected')
  start=dt.datetime.now(dt.timezone.utc);ts=start.timestamp()
  with _ledger(self.ledger) as c:
   c.execute('BEGIN IMMEDIATE')
   cooldown=c.execute('SELECT until FROM scout_cooldowns WHERE provider=?',(host,)).fetchone()
   used=c.execute('SELECT count(*) FROM scout_requests WHERE reserved>?',(ts-WINDOW,)).fetchone()[0]
   if cooldown and cooldown[0]>ts:return None,None,{'status':'rate_limited','requested_at':None}
   if self.calls>=self.budget or used>=self.hourly_limit:raise live_pilot.BudgetExhausted('durable request budget exhausted')
   row=c.execute('INSERT INTO scout_requests(provider,reserved,status) VALUES(?,?,?)',(host,ts,'reserved')).lastrowid
  self.calls+=1
  status='error';meta={'requested_at':start.isoformat()}
  try:
   request=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'ScoobyDAO-bounded-scout/1.0'})
   # Redirects could send a bounded request to an unapproved host; reject them.
   opener=urllib.request.build_opener(_NoRedirect())
   with opener.open(request,timeout=15) as response:raw=response.read(3_000_001);code=response.status
   if len(raw)>3_000_000:raise ValueError('response exceeds size cap')
   data=json.loads(raw);digest=hashlib.sha256(raw).hexdigest();target=self.root/(digest+'.json')
   if not target.exists():
    with target.open('xb') as f:f.write(raw)
   fetched=live_pilot.now();status='ok';meta.update(status=status,http_status=code,fetched_at=fetched,sha256=digest)
   evidence={'id':digest,'source':'snapshots/'+digest+'.json','sha256':digest,'observed_at':None,'fetched_at':fetched,'block_number':None,'kind':'live_observation','limitations':['Raw provider response; observation time, source coverage and correctness are not verified.','Request URL: '+url]}
   return data,evidence,meta
  except urllib.error.HTTPError as e:
   meta.update(status='rate_limited' if e.code==429 else 'error',http_status=e.code,fetched_at=live_pilot.now());status=meta['status']
   if e.code==429:
    with _ledger(self.ledger) as c:c.execute('INSERT INTO scout_cooldowns VALUES(?,?) ON CONFLICT(provider) DO UPDATE SET until=MAX(until,excluded.until)',(host,dt.datetime.now(dt.timezone.utc).timestamp()+WINDOW))
   return None,None,meta
  except (OSError,ValueError,UnicodeError):
   meta.update(status='error',fetched_at=live_pilot.now());return None,None,meta
  finally:
   with _ledger(self.ledger) as c:c.execute('UPDATE scout_requests SET status=? WHERE id=?',(status,row))

class _NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def run_once(db,root,*,enabled=False,budget=0,hourly_limit=0,limit=5,chains=('ethereum','base')):
 """One isolated cycle; reservation history and cooldown survive process restarts."""
 if not enabled:return {'status':'disabled','calls':0}
 if (type(budget) is not int or type(hourly_limit) is not int or not 1<=budget<=30 or not 1<=hourly_limit<=30
     or type(limit) is not int or not 1<=limit<=10 or not chains or len(set(chains))!=len(chains) or any(c not in live_pilot.CHAINS for c in chains)):
  return {'status':'configuration_unavailable','calls':0}
 db=Path(db);root=Path(root);db.parent.mkdir(parents=True,exist_ok=True);root.mkdir(parents=True,exist_ok=True)
 ledger=Path(str(db.resolve())+'.scout-budget.sqlite3');lock=continuous_pilot.lock_runner(db)
 try:
  ts=dt.datetime.now(dt.timezone.utc).timestamp()
  with _ledger(ledger) as c:
   c.execute('BEGIN IMMEDIATE');last=c.execute('SELECT max(started) FROM scout_cycles').fetchone()[0]
   if last is not None and ts-last<MIN_INTERVAL:return {'status':'not_due','calls':0}
   cycle=c.execute('INSERT INTO scout_cycles(started,status) VALUES(?,?)',(ts,'started')).lastrowid
  try:
   result=live_pilot.run(db,root,limit,budget,list(chains),fetcher_factory=lambda path,cap:ReservedFetcher(path,cap,ledger,hourly_limit))
   with _ledger(ledger) as c:c.execute('UPDATE scout_cycles SET status=? WHERE id=?',(result['status'],cycle))
   return result
  except Exception:
   with _ledger(ledger) as c:c.execute('UPDATE scout_cycles SET status=? WHERE id=?',('failed',cycle))
   raise
 finally:lock.close()
