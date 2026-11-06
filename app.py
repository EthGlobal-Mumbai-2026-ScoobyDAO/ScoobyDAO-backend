import hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from jsonschema import Draft202012Validator
from store import ROOT, DATA, db, ident, now, dumps, digest, row, job, event, PILLARS
from worker import wake
app=FastAPI(title='Scooby DAO local operator API',version='0.1.0',description='Local-only prototype. Identities and review receipts are not authenticated.')
def err(code,msg): raise HTTPException(code,msg)
def getrow(c,sql,args):
 r=c.execute(sql,args).fetchone()
 if not r: err(404,'Not found')
 return r
def key(k):
 if not k or len(k)>200: err(400,'Idempotency-Key required (maximum 200 characters)')
 return k
def signal():
 try: wake()
 except Exception: pass # persisted queue is reconciled by worker
class Candidate(BaseModel): payload: dict
class Selection(BaseModel):
 kind: Literal['qualified','diagnostic_exception','defer']
 actor: str = Field(min_length=1,max_length=100)
 reason: str = Field(min_length=1,max_length=1000)
class Run(BaseModel): candidate_id: str; selection_id: str
class ImportReport(BaseModel): run_id: str; bundle_path: str
class Review(BaseModel):
 decision: Literal['request','approve','revise','reject']
 actor: str = Field(min_length=1,max_length=100)
 reason: str = Field(min_length=1,max_length=1000)
 sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
@app.get('/health')
def health(): return {'status':'ok','scope':'local operator only','production_authentication':False}
@app.get('/status')
def status():
 with db() as c:
  counts={x['state']:x['n'] for x in c.execute('SELECT state,count(*) n FROM jobs GROUP BY state')}
  hb=row(c.execute("SELECT * FROM heartbeats WHERE name='worker'").fetchone())
 return {'queue':counts,'worker':hb,'worker_fresh':bool(hb and now()-hb['seen']<150),'scheduler':'Huey periodic reconciliation; no discovery sources configured','feeds':[],'budget':{'call_limit':int(os.getenv('SCOOBY_MODEL_CALL_BUDGET','0')),'usage_accounting':'per-call response when available; token-spend and rate limits not implemented'}}
@app.get('/schemas')
def schemas():
 return [{'file':p.name,'sha256':digest(p.read_bytes()),'schema':json.loads(p.read_text(encoding='utf-8-sig'))} for p in sorted((ROOT/'schemas').glob('*.schema.json'))]
@app.post('/candidates')
def candidate(x:Candidate):
 try: Draft202012Validator(json.loads((ROOT/'schemas/candidate.schema.json').read_text(encoding='utf-8-sig'))).validate(x.payload)
 except Exception as e: err(422,'Candidate fails frozen schema: '+str(e).splitlines()[0])
 p=x.payload; cid=p.get('candidate_id')
 if not cid: err(422,'candidate_id missing')
 with db() as c:
  old=c.execute('SELECT payload FROM candidates WHERE id=?',(cid,)).fetchone()
  if old and old[0]!=dumps(p): err(409,'Candidate ID exists with different content')
  c.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?)',(cid,dumps(p),now()))
 return {'candidate_id':cid,'gate':'unknown','monitoring':True}
@app.get('/candidates')
def candidates():
 with db() as c: return [{'candidate_id':x['id'],'gate':'unknown','monitoring':True} for x in c.execute('SELECT * FROM candidates')]
@app.get('/candidates/{candidate_id}')
def candidate_detail(candidate_id:str):
 with db() as c: r=getrow(c,'SELECT * FROM candidates WHERE id=?',(candidate_id,))
 return {'candidate':json.loads(r['payload']),'gate':'unknown','reason':'Concern verifiers are not installed; no candidate is qualified.'}
@app.post('/candidates/{candidate_id}/selection')
def select(candidate_id:str,x:Selection,idempotency_key:str=Header(None)):
 k=key(idempotency_key)
 with db() as c:
  getrow(c,'SELECT id FROM candidates WHERE id=?',(candidate_id,))
  old=c.execute('SELECT * FROM selections WHERE idem=?',(k,)).fetchone()
  if old:
   if (old['candidate_id'],old['kind'],old['actor'],old['reason'])!=(candidate_id,x.kind,x.actor,x.reason): err(409,'Idempotency key conflict')
   return row(old)
  if x.kind=='qualified': err(409,'No verified gate implementation configured')
  i=ident(); c.execute('INSERT INTO selections VALUES(?,?,?,?,?,?,?)',(i,candidate_id,x.kind,x.actor,x.reason,now(),k))
  return row(getrow(c,'SELECT * FROM selections WHERE id=?',(i,)))
@app.post('/investigations')
def investigate(x:Run,idempotency_key:str=Header(None)):
 k=key(idempotency_key)
 with db() as c:
  old=c.execute('SELECT * FROM investigations WHERE idem=?',(k,)).fetchone()
  if old:
   if (old['candidate_id'],old['selection_id'])!=(x.candidate_id,x.selection_id): err(409,'Idempotency key conflict')
   return row(old)
  s=getrow(c,'SELECT * FROM selections WHERE id=?',(x.selection_id,))
  if s['candidate_id']!=x.candidate_id or s['kind'] not in ('qualified','diagnostic_exception'): err(409,'Selection does not authorize this investigation')
  i=ident(); c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?)',(i,x.candidate_id,x.selection_id,'queued',now(),k))
  for p in PILLARS: c.execute('INSERT INTO pillars VALUES(?,?,?,?)',(i,p,'queued','Awaiting worker'))
  event(c,i,'created','Local operator selection; human identity not authenticated'); job(c,'investigate',i,'investigate:'+i)
 signal(); return {'id':i,'status':'queued'}
@app.get('/investigations/{run_id}')
def run(run_id:str):
 with db() as c:
  r=row(getrow(c,'SELECT * FROM investigations WHERE id=?',(run_id,))); r['pillars']=[row(x) for x in c.execute('SELECT * FROM pillars WHERE run_id=?',(run_id,))]; return r
@app.get('/investigations/{run_id}/events')
def events(run_id:str):
 with db() as c:
  getrow(c,'SELECT id FROM investigations WHERE id=?',(run_id,)); return [row(x) for x in c.execute('SELECT * FROM events WHERE run_id=? ORDER BY seq',(run_id,))]
@app.post('/investigations/{run_id}/cancel')
def cancel(run_id:str):
 with db() as c:
  getrow(c,'SELECT id FROM investigations WHERE id=?',(run_id,)); c.execute("UPDATE investigations SET status='cancelled' WHERE id=?",(run_id,)); c.execute("UPDATE jobs SET state='cancelled' WHERE kind='investigate' AND ref=? AND state='queued'",(run_id,)); event(c,run_id,'cancelled','Local operator')
 return {'status':'cancelled'}
@app.post('/investigations/{run_id}/resume')
def resume(run_id:str,idempotency_key:str=Header(None)):
 k=key(idempotency_key)
 with db() as c:
  r=getrow(c,'SELECT * FROM investigations WHERE id=?',(run_id,))
  old=c.execute('SELECT * FROM jobs WHERE idem=?',(k,)).fetchone()
  if old:
   if old['kind']!='investigate' or old['ref']!=run_id: err(409,'Idempotency key conflict')
   return {'job_id':old['id']}
  if r['status'] not in ('incomplete','cancelled'): err(409,'Run is not resumable')
  c.execute("UPDATE investigations SET status='queued' WHERE id=?",(run_id,)); c.execute("UPDATE pillars SET status='queued' WHERE run_id=? AND status IN ('unavailable','failed')",(run_id,)); event(c,run_id,'resumed','Local operator'); j=job(c,'investigate',run_id,k)
 signal(); return {'job_id':j}
@app.post('/scans')
def scan(idempotency_key:str=Header(None)):
 with db() as c: j=job(c,'scan','bounded-empty',key(idempotency_key))
 signal(); return {'job_id':j,'coverage':'unknown'}
@app.get('/jobs/{job_id}')
def jobs(job_id:str):
 with db() as c: return row(getrow(c,'SELECT * FROM jobs WHERE id=?',(job_id,)))
@app.post('/reports/import')
def import_report(x:ImportReport):
 frontend=os.getenv('SCOOBY_FRONTEND_DIR', str(ROOT/'vendor'/'reader'))
 if not frontend: err(503,'SCOOBY_FRONTEND_DIR is not configured')
 source=Path(x.bundle_path).resolve()
 if not source.is_dir() or not (source/'report.json').is_file(): err(400,'Bundle directory missing report.json')
 if any(p.is_symlink() for p in source.rglob('*')): err(400,'Symlinks forbidden')
 with tempfile.TemporaryDirectory(dir=DATA) as tmp:
  # Work from a snapshot; validation and persistence consume identical bytes.
  snap=Path(tmp)/'bundle'; shutil.copytree(source,snap)
  try: subprocess.run([sys.executable,str(Path(frontend)/'build.py'),str(snap/'report.json'),str(Path(tmp)/'validated')],check=True,timeout=120,capture_output=True)
  except Exception: err(422,'Frontend contract validation failed; inspect bundle and adapter')
  raw=(snap/'report.json').read_bytes(); d=json.loads(raw); sha=digest(raw)
  with db() as c:
   run=getrow(c,'SELECT * FROM investigations WHERE id=?',(x.run_id,))
   if d['candidate_id']!=run['candidate_id']: err(409,'Report candidate differs from selected run')
   old=c.execute('SELECT * FROM reports WHERE id=? AND version=?',(d['report_id'],d['report_version'])).fetchone()
   if old:
    if old['sha256']!=sha or old['run_id']!=x.run_id: err(409,'Immutable report version already exists')
    return row(old)
   target=DATA/'bundles'/sha; target.parent.mkdir(exist_ok=True)
   if not target.exists(): shutil.copytree(snap,target)
   c.execute('INSERT INTO reports VALUES(?,?,?,?,?,?)',(d['report_id'],d['report_version'],x.run_id,sha,str(target),now()))
   event(c,x.run_id,'report_imported',sha)
   return {'report_id':d['report_id'],'version':d['report_version'],'sha256':sha,'review':'pending'}
@app.get('/reports/{report_id}/{version}')
def report(report_id:str,version:str):
 with db() as c:
  r=row(getrow(c,'SELECT id,version,run_id,sha256,created FROM reports WHERE id=? AND version=?',(report_id,version)))
  r['reviews']=[row(x) for x in c.execute('SELECT id,sha256,decision,actor,reason,created FROM reviews WHERE report_id=? AND version=? ORDER BY created',(report_id,version))]; return r
@app.post('/reports/{report_id}/{version}/review')
def review(report_id:str,version:str,x:Review,idempotency_key:str=Header(None)):
 k=key(idempotency_key)
 with db() as c:
  r=getrow(c,'SELECT * FROM reports WHERE id=? AND version=?',(report_id,version))
  if r['sha256']!=x.sha256: err(409,'Digest does not match immutable version')
  old=c.execute('SELECT * FROM reviews WHERE idem=?',(k,)).fetchone()
  if old:
   if (old['report_id'],old['version'],old['sha256'],old['decision'],old['actor'],old['reason'])!=(report_id,version,x.sha256,x.decision,x.actor,x.reason): err(409,'Idempotency key conflict')
   return row(old)
  i=ident(); c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?)',(i,report_id,version,x.sha256,x.decision,x.actor,x.reason,now(),k)); return {'id':i,'sha256':x.sha256,'decision':x.decision,'authentication':'unverified local operator'}
@app.post('/reports/{report_id}/{version}/render')
def render(report_id:str,version:str,idempotency_key:str=Header(None)):
 with db() as c:
  r=getrow(c,'SELECT * FROM reports WHERE id=? AND version=?',(report_id,version)); ref=dumps({'id':report_id,'version':version,'sha256':r['sha256']}); j=job(c,'render',ref,key(idempotency_key))
 signal(); return {'job_id':j,'status':'pending review draft','pdf':'attempted when SCOOBY_BROWSER is configured'}
@app.get('/artifacts/{job_id}/{name}')
def artifact(job_id:str,name:str):
 if name not in ('index.html','report.json','report.pdf','manifest.json'): err(404,'Artifact unavailable')
 with db() as c:
  j=getrow(c,'SELECT * FROM jobs WHERE id=?',(job_id,))
  if j['kind']!='render' or j['state']!='done': err(409,'Artifact not ready')
 path=DATA/'artifacts'/job_id/name
 if not path.is_file(): err(404,'Artifact missing')
 return FileResponse(path,headers={'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:;"})

@app.get('/artifacts/{job_id}/assets/{asset_path:path}')
def artifact_asset(job_id:str,asset_path:str):
 if not asset_path or any(x in asset_path for x in ('\\',':','%','?','#')) or any(x in ('','.','..') for x in asset_path.split('/')): err(400,'Unsafe asset path')
 with db() as c:
  j=getrow(c,'SELECT * FROM jobs WHERE id=?',(job_id,))
  if j['kind']!='render' or j['state']!='done': err(409,'Artifact not ready')
 base=(DATA/'artifacts'/job_id/'assets').resolve(); path=base
 for part in asset_path.split('/'):
  path=path/part
  if path.is_symlink(): err(400,'Symlink forbidden')
 if not path.resolve().is_relative_to(base) or not path.is_file(): err(404,'Asset not found')
 return FileResponse(path,media_type='application/octet-stream',headers={'X-Content-Type-Options':'nosniff','Content-Disposition':'attachment'})

class ReasonInput(BaseModel):
 pillar: Literal['microstructure','onchain','fundamentals','statistical_risk','technical_health']
 evidence: list[dict] = Field(min_length=1,max_length=20)
@app.post('/investigations/{run_id}/reason')
def queue_reason(run_id:str,x:ReasonInput,idempotency_key:str=Header(None)):
 k=key(idempotency_key)
 if len(dumps(x.evidence))>30000 or any(not isinstance(e.get('id'),str) or not e['id'] for e in x.evidence): err(422,'Bounded evidence with IDs required')
 if len({e['id'] for e in x.evidence})!=len(x.evidence): err(422,'Evidence IDs must be unique')
 if int(os.getenv('SCOOBY_MODEL_CALL_BUDGET','0'))<=0: err(503,'Model call budget is zero')
 with db() as c:
  run=getrow(c,'SELECT * FROM investigations WHERE id=?',(run_id,))
  if run['status']=='cancelled': err(409,'Run cancelled')
  old=c.execute('SELECT * FROM jobs WHERE idem=?',(k,)).fetchone()
  if old:
   inp=c.execute('SELECT * FROM reasoning_inputs WHERE id=?',(old['ref'],)).fetchone()
   if old['kind']!='reason' or not inp or (inp['run_id'],inp['pillar'],inp['evidence'])!=(run_id,x.pillar,dumps(x.evidence)): err(409,'Idempotency key conflict')
   return {'job_id':old['id'],'input_id':inp['id']}
  i=ident(); c.execute('INSERT INTO reasoning_inputs VALUES(?,?,?,?,?,?,?)',(i,run_id,x.pillar,dumps(x.evidence),None,'queued',now())); j=job(c,'reason',i,k)
 signal(); return {'job_id':j,'input_id':i,'coverage':'operator-supplied, unverified'}
@app.get('/reasoning/{input_id}')
def get_reason(input_id:str):
 with db() as c:
  x=row(getrow(c,'SELECT * FROM reasoning_inputs WHERE id=?',(input_id,)))
  x['evidence']=json.loads(x['evidence']); x['output']=json.loads(x['output']) if x['output'] else None
  return x

@app.get('/readiness/honeypot', tags=['readiness'])
def honeypot_readiness():
 return {
  'kind':'static_integration_inventory',
  'checkpoint_case_status':'no_selection_recorded_in_this_checkpoint',
  'normal_gate':{'required_distinct_verified_groups':4,'wired_verifiers':0,'qualified_selection_enabled':False},
  'discovery_newer_work':'G07 and partial G09 exist in an unmerged worktree, not in this worker',
  'investigation':'five persisted pillar states; producers are not wired',
  'research_output':'external bundle import and validation only; no automated end-to-end report',
  'reader':'bundled earlier reader; newer IRC reader not integrated',
  'pdf':'draft browser print only; full report PDF not implemented',
  'review':'local unverified receipts; no authenticated sign-off',
  'publication':'reserved for human teammate; not implemented',
  'paid_model_budget_default':0,
  'documentation':'docs/honeypot-readiness.md'
 }

# Publication boundary and World ID Agent Pass sign-off live in publication/ (see docs/publication-plan.md).
from fastapi.middleware.cors import CORSMiddleware
from publication import routes as publication_routes, web_adapter as publication_web
from publication.config import settings as publication_settings
app.include_router(publication_routes.router)
app.include_router(publication_web.router)
app.add_middleware(CORSMiddleware, allow_origins=[publication_settings().web_origin], allow_methods=['GET','POST'],
                   allow_headers=['Authorization','Content-Type','Idempotency-Key'])
