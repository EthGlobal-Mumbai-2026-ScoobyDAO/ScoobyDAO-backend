import hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import Response
from urllib.parse import quote
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from jsonschema import Draft202012Validator
from store import ROOT, DATA, db, ident, now, dumps, digest, row, job, event, PILLARS
from worker import wake
app=FastAPI(title='Scooby DAO local operator API',version='0.1.0',description='Local-only prototype. Local review receipts are unauthenticated; World ID integration requires live verification.')
web_origin=os.getenv('SCOOBY_WEB_ORIGIN','').strip()
if web_origin:
 if not (web_origin.startswith('http://') or web_origin.startswith('https://')) or '*' in web_origin or web_origin.endswith('/'):
  raise ValueError('SCOOBY_WEB_ORIGIN must be one explicit origin without trailing slash')
 app.add_middleware(CORSMiddleware,allow_origins=[web_origin],allow_credentials=False,allow_methods=['GET'],allow_headers=['Content-Type'])
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
  candidate_row=getrow(c,'SELECT payload FROM candidates WHERE id=?',(x.candidate_id,))
  if json.loads(candidate_row['payload']).get('mode')=='live': err(403,'Live research requires a policy decision or a verified human authorization; legacy selection is unverified')
  i=ident(); c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?)',(i,x.candidate_id,x.selection_id,'queued',now(),k))
  for p in PILLARS: c.execute('INSERT INTO pillars VALUES(?,?,?,?)',(i,p,'queued','Awaiting worker'))
  event(c,i,'created','Local operator selection; human identity not authenticated'); job(c,'investigate',i,'investigate:'+i)
 signal(); return {'id':i,'status':'queued'}
@app.post('/reference-runs')
def reference_run(x:Run,idempotency_key:str=Header(None)):
 """A no-research container for separately authorized, manually imported reference reports."""
 k=key(idempotency_key)
 with db() as c:
  c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM investigations WHERE idem=?',(k,)).fetchone()
  if old:
   if (old['candidate_id'],old['selection_id'],old['status'])!=(x.candidate_id,x.selection_id,'reference_only'):err(409,'Idempotency key conflict')
   return {'id':old['id'],'status':'reference_only'}
  selection=getrow(c,'SELECT * FROM selections WHERE id=?',(x.selection_id,))
  if selection['candidate_id']!=x.candidate_id or selection['kind']!='diagnostic_exception':err(409,'Scoped reference selection required')
  run=ident();c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?)',(run,x.candidate_id,x.selection_id,'reference_only',now(),k))
  for pillar in PILLARS:c.execute('INSERT INTO pillars VALUES(?,?,?,?)',(run,pillar,'unavailable','Reference import only; no research authorized or performed.'))
  event(c,run,'reference_only','Local source-curated report import only; no research job or authenticated approval')
  return {'id':run,'status':'reference_only'}
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
  candidate_row=getrow(c,'SELECT payload FROM candidates WHERE id=?',(r['candidate_id'],))
  if json.loads(candidate_row['payload']).get('mode')=='live': err(403,'Live resumption requires a fresh authorized case decision')
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
   if not target.exists():
    try: os.rename(snap,target)
    except OSError:
     if not target.exists(): raise
   # Revalidate the installed bytes, including crash recovery or concurrent imports.
   try: subprocess.run([sys.executable,str(Path(frontend)/'build.py'),str(target/'report.json'),str(Path(tmp)/'installed-check')],check=True,timeout=120,capture_output=True)
   except Exception: err(409,'Installed bundle integrity failure')
   if digest((target/'report.json').read_bytes())!=sha: err(409,'Installed report digest mismatch')
   c.execute('INSERT INTO reports VALUES(?,?,?,?,?,?)',(d['report_id'],d['report_version'],x.run_id,sha,str(target),now()))
   event(c,x.run_id,'report_imported',sha)
   return {'report_id':d['report_id'],'version':d['report_version'],'sha256':sha,'review':'pending'}
def report_metadata(c,r):
 run=getrow(c,'SELECT * FROM investigations WHERE id=?',(r['run_id'],))
 selection=getrow(c,'SELECT * FROM selections WHERE id=?',(run['selection_id'],))
 path=Path(r['path'])/'report.json'
 if path.is_symlink() or not path.is_file(): err(409,'Stored report integrity failure')
 raw=path.read_bytes()
 if digest(raw)!=r['sha256']: err(409,'Stored report integrity failure')
 doc=json.loads(raw)
 latest=c.execute('SELECT decision,created FROM reviews WHERE report_id=? AND version=? ORDER BY created DESC',(r['id'],r['version'])).fetchone()
 return {'report_id':r['id'],'report_version':r['version'],'candidate_id':run['candidate_id'],'report_sha256':r['sha256'],
         'mode':doc.get('mode'),'identity':doc.get('identity'),'observation_times':sorted({e['observed_at'] for e in doc.get('evidence',[]) if e.get('observed_at')}),
         'selection':{'kind':selection['kind'],'reason':selection['reason'],'admission_qualified':False if selection['kind']=='diagnostic_exception' else None,'authentication':'unverified local operator'},
         'review':{'status':latest['decision'] if latest else 'pending','authentication':'unverified local operator'},'created':r['created']}
@app.get('/reports')
def list_reports():
 with db() as c: return [report_metadata(c,r) for r in c.execute('SELECT * FROM reports ORDER BY created DESC').fetchall()]
@app.get('/reports/{report_id}/{version}/artifacts')
def report_artifacts(report_id:str,version:str):
 with db() as c:
  r=getrow(c,'SELECT * FROM reports WHERE id=? AND version=?',(report_id,version)); result=report_metadata(c,r)
  jobs=c.execute("SELECT * FROM jobs WHERE kind='render' AND state='done' ORDER BY created DESC").fetchall()
  match=next((j for j in jobs if json.loads(j['ref'])=={'id':report_id,'version':version,'sha256':r['sha256']}),None)
 if not match:
  result['artifacts']={k:{'availability':'unavailable','sha256':None,'url':None} for k in ('html','markdown','pdf')}; result['render_status']='not_rendered'; result['package']={'availability':'unavailable','package_sha256':None,'url':None}; return result
 out=DATA/'artifacts'/match['id']; manifest_path=out/'manifest.json'
 if not manifest_path.is_file(): err(409,'Render manifest missing')
 with db() as c: locked=c.execute('SELECT sha256 FROM render_manifests WHERE job_id=?',(match['id'],)).fetchone()
 if manifest_path.is_symlink(): err(409,'Render manifest integrity failure')
 manifest_raw=manifest_path.read_bytes()
 if not locked or digest(manifest_raw)!=locked['sha256']: err(409,'Render manifest integrity failure')
 m=json.loads(manifest_raw)
 if (m.get('report_id'),m.get('report_version'),m.get('report_sha256'))!=(report_id,version,r['sha256']): err(409,'Render manifest identity mismatch')
 result['render_status']='pending_review_draft'; result['artifacts']={}
 result['package']={'availability':'available','package_sha256':locked['sha256'],'url':'/packages/'+locked['sha256']}
 for kind,name,keyname in [('html','index.html','html_sha256'),('markdown','report.md','markdown_sha256'),('pdf','report.pdf','pdf_sha256')]:
  expected=m.get(keyname); f=out/name
  if expected and (not f.is_file() or digest(f.read_bytes())!=expected): err(409,'Render artifact integrity failure')
  result['artifacts'][kind]={'availability':'available' if expected else 'unavailable','sha256':expected,'url':f'/artifacts/{match["id"]}/{name}' if expected else None,'report_sha256':r['sha256']}
 return result
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
def checked_bytes(path,expected):
 if path.is_symlink() or not path.is_file(): err(404,'Artifact missing')
 raw=path.read_bytes()
 if not expected or digest(raw)!=expected: err(409,'Artifact integrity failure')
 return raw
def artifact_headers():
 return {'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:"}
def safe_asset(base,asset_path):
 if not asset_path or any(x in asset_path for x in ('\\',':','%','?','#')) or any(x in ('','.','..') for x in asset_path.split('/')): err(400,'Unsafe asset path')
 path=base
 for part in asset_path.split('/'):
  path=path/part
  if path.is_symlink(): err(400,'Symlink forbidden')
 if not path.resolve().is_relative_to(base.resolve()): err(400,'Unsafe asset path')
 return path
def report_assets(doc):
 allowed={}
 for x in doc['evidence']+[a for a in doc['artifacts'] if a['availability']=='available']:
  name=x['path']; sha=x['sha256']
  if name in allowed and allowed[name]!=sha: err(409,'Conflicting asset hashes')
  allowed[name]=sha
 return allowed
def package_context(package_sha256):
 import re
 if not re.fullmatch('[0-9a-f]{64}',package_sha256): err(404,'Package not found')
 with db() as c:
  j=c.execute("SELECT jobs.* FROM jobs JOIN render_manifests ON jobs.id=render_manifests.job_id WHERE render_manifests.sha256=? AND jobs.state='done' AND jobs.kind='render' LIMIT 1",(package_sha256,)).fetchone()
  if not j: err(404,'Package not found')
 out=DATA/'artifacts'/j['id']; ref=json.loads(j['ref']); manifest=json.loads(checked_bytes(out/'manifest.json',package_sha256))
 if (manifest.get('report_id'),manifest.get('report_version'),manifest.get('report_sha256'))!=(ref['id'],ref['version'],ref['sha256']): err(409,'Package identity mismatch')
 raw=checked_bytes(out/'report.json',ref['sha256']); doc=json.loads(raw)
 if (doc['report_id'],doc['report_version'])!=(ref['id'],ref['version']): err(409,'Report identity mismatch')
 return out,ref,manifest,raw,doc
@app.get('/packages/{package_sha256}')
def package_descriptor(package_sha256:str):
 out,ref,m,raw,doc=package_context(package_sha256); report_assets(doc)
 prefix='/packages/'+package_sha256
 def asset_url(path): return prefix+'/assets/'+quote(path,safe='/') if path else None
 artifacts=[{'kind':a['kind'],'path':a['path'],'availability':a['availability'],'media_type':a['media_type'],'sha256':a['sha256'],'url':asset_url(a['path']) if a['availability']=='available' else None} for a in doc['artifacts']]
 evidence=[{'id':e['id'],'path':e['path'],'availability':'available','media_type':'application/octet-stream','sha256':e['sha256'],'url':asset_url(e['path'])} for e in doc['evidence']]
 return {'package_sha256':package_sha256,'candidate_id':doc['candidate_id'],'report_id':ref['id'],'report_version':ref['version'],'report_sha256':ref['sha256'],'report_review_snapshot':{'status':doc['review']['status'],'authentication':'unverified report assertion'},'manifest':{'media_type':'application/json','sha256':package_sha256,'url':prefix+'/manifest.json'},'report':{'availability':'available','media_type':'application/json','sha256':ref['sha256'],'url':prefix+'/report.json'},'artifacts':artifacts,'evidence':evidence}
@app.get('/packages/{package_sha256}/manifest.json')
def package_manifest(package_sha256:str):
 out,ref,m,raw,doc=package_context(package_sha256)
 data=checked_bytes(out/'manifest.json',package_sha256)
 return Response(content=data,media_type='application/json',headers=artifact_headers())
@app.get('/packages/{package_sha256}/report.json')
def package_report(package_sha256:str):
 out,ref,m,raw,doc=package_context(package_sha256)
 return Response(content=raw,media_type='application/json',headers=artifact_headers())
@app.get('/packages/{package_sha256}/assets/{asset_path:path}')
def package_asset(package_sha256:str,asset_path:str):
 out,ref,m,raw,doc=package_context(package_sha256); allowed=report_assets(doc)
 path=safe_asset(out/'assets',asset_path)
 if asset_path not in allowed: err(404,'Asset not found')
 data=checked_bytes(path,allowed[asset_path])
 media=next((a['media_type'] for a in doc['artifacts'] if a['availability']=='available' and a['path']==asset_path),None)
 return Response(content=data,media_type=media or 'application/octet-stream',headers=artifact_headers())
@app.get('/artifacts/{job_id}/{name}')
def artifact(job_id:str,name:str):
 if name not in ('index.html','report.json','report.md','report.pdf','manifest.json'): err(404,'Artifact unavailable')
 with db() as c:
  j=getrow(c,'SELECT * FROM jobs WHERE id=?',(job_id,))
  if j['kind']!='render' or j['state']!='done': err(409,'Artifact not ready')
  locked=getrow(c,'SELECT sha256 FROM render_manifests WHERE job_id=?',(job_id,))
 out=DATA/'artifacts'/job_id; ref=json.loads(j['ref']); manifest_raw=checked_bytes(out/'manifest.json',locked['sha256']); m=json.loads(manifest_raw)
 if (m.get('report_id'),m.get('report_version'),m.get('report_sha256'))!=(ref['id'],ref['version'],ref['sha256']): err(409,'Render manifest identity mismatch')
 if name=='manifest.json': data=manifest_raw
 elif name=='report.json': data=checked_bytes(out/name,ref['sha256'])
 else: data=checked_bytes(out/name,m.get({'index.html':'html_sha256','report.md':'markdown_sha256','report.pdf':'pdf_sha256'}[name]))
 media={'index.html':'text/html','report.json':'application/json','manifest.json':'application/json','report.md':'text/markdown','report.pdf':'application/pdf'}[name]
 return Response(content=data,media_type=media,headers=artifact_headers())
@app.get('/artifacts/{job_id}/assets/{asset_path:path}')
def artifact_asset(job_id:str,asset_path:str):
 with db() as c:
  j=getrow(c,'SELECT * FROM jobs WHERE id=?',(job_id,))
  if j['kind']!='render' or j['state']!='done': err(409,'Artifact not ready')
  locked=getrow(c,'SELECT sha256 FROM render_manifests WHERE job_id=?',(job_id,))
 return package_asset(locked['sha256'],asset_path)

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
  source=getrow(c,'SELECT payload FROM candidates WHERE id=?',(run['candidate_id'],))
  if json.loads(source['payload']).get('mode')=='live': err(403,'Live reasoning requires a bound, authorized evidence adapter')
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
  'checkpoint_case_status':'no_fresh_milestone_selection_recorded_in_this_checkpoint',
  'reference_track':'RAY source-curated report imported; diagnostic exception, not gate-qualified; review pending',
  'normal_gate':{'required_distinct_verified_groups':4,'wired_verifiers':0,'qualified_selection_enabled':False},
  'discovery_newer_work':'G07 and partial G09 exist in discovery work; neither is wired to this worker',
  'investigation':'five persisted pillar states; producers are not wired',
  'research_output':'reference bundle imported and rendered; no automated end-to-end deep research',
  'reader':'corrected IRC reader integrated for imported bundles; automated research remains unwired',
  'pdf':'reference draft contains expanded reader and bound full Markdown; thumbnail and text checks passed, detailed accessibility and typography QA pending',
  'review':'local receipts are unauthenticated; separate World ID integration is not live-verified',
  'publication':'optional World ID and outbox implementation; disabled by default, not live-verified',
  'paid_model_budget_default':0,
  'documentation':'docs/honeypot-readiness.md'
 }

# Publication boundary and World ID Agent Pass sign-off live in publication/ (see docs/publication-plan.md).
from publication import routes as publication_routes, web_adapter as publication_web
app.include_router(publication_routes.router)
app.include_router(publication_web.router)

class PublicationWebCORS(CORSMiddleware):
 async def __call__(self, scope, receive, send):
  if scope['type'] == 'http' and scope['path'].startswith('/web/v1/'):
   await super().__call__(scope, receive, send)
  else:
   await self.app(scope, receive, send)

if web_origin:
 app.add_middleware(PublicationWebCORS, allow_origins=[web_origin], allow_methods=['GET','POST'],
                    allow_headers=['Content-Type'])

class CaseScan(BaseModel):
 limit: int = Field(default=10,ge=1,le=25)
class ChallengeRequest(BaseModel):
 action: Literal['diagnostic_research'] = 'diagnostic_research'
 expected_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
@app.post('/scouting/cases/refresh')
def refresh_cases(x:CaseScan,idempotency_key:str=Header(None)):
 with db() as c:
  try: jid=job(c,'case_scan',str(x.limit),key(idempotency_key))
  except ValueError: err(409,'Idempotency key conflict')
 signal();return {'job_id':jid,'status':'queued','scope':'configured local discovery store; no network calls'}
def case_view(c,case,policy=None):
 import datetime as dt
 policy=policy or __import__('case_engine').policy_digest()
 snap=getrow(c,'SELECT * FROM case_snapshots WHERE id=?',(case['current_snapshot'],));record=json.loads(snap['record']);ass=json.loads(snap['assessment']);state=case['state']
 decision=c.execute('SELECT case_decisions.run_id,case_decisions.budget,investigations.status FROM case_decisions JOIN investigations ON investigations.id=case_decisions.run_id WHERE case_decisions.case_id=? AND case_decisions.run_id IS NOT NULL ORDER BY case_decisions.created DESC LIMIT 1',(case['id'],)).fetchone()
 if decision: state='investigating' if decision['status'] in ('queued','running') else 'unavailable'
 captured=json.loads(snap['evidence'])
 expected=digest(dumps({'record':record,'evidence':captured,'policy':snap['policy_digest'],'assessment':ass}).encode())
 if expected!=snap['id']: err(409,'Case snapshot integrity failure')
 if (snap['expires']<=now() or policy!=snap['policy_digest']) and state!='investigating': state='unavailable'
 lane={'monitoring':'monitoring','awaiting_human':'human_review_required','auto_queued':'auto_qualified','investigating':'research_running','unavailable':'unavailable'}[state]
 def latest(key):
  values=[e.get(key) for e in record.get('evidence',[]) if e.get(key)]
  try:return max(values,key=lambda x:dt.datetime.fromisoformat(x.replace('Z','+00:00'))) if values else None
  except (ValueError,TypeError):return None
 reasons=[{'group_id':g['id'],'description':g['detail'],'verification_status':g['status'],'evidence_ids':[e['id'] for e in g.get('evidence',[])],'observed_at':max((e['observed_at'] for e in g.get('evidence',[])),default=None)} for g in ass['groups']]
 pillars=[row(x) for x in c.execute('SELECT pillar,status,detail FROM pillars WHERE run_id=? ORDER BY pillar',(decision['run_id'],))] if decision else []
 _,count,_=__import__('case_engine').verified_gate(ass,captured)
 priority={'human_review_required':0,'auto_qualified':1,'research_running':2,'monitoring':3,'unavailable':4}[lane]*100+(12-min(count,12))
 return {'case_id':case['id'],'candidate_id':record['candidate_id'],'identity':record['identity'],'mode':record['mode'],'reference':None,'lane':lane,'human_action_required':lane=='human_review_required','priority_order':priority,'verified_triggered_count':count,'status_label':lane.replace('_',' '),'summary':'Deterministic screening; not a report or safety verdict.','uncertainties':record['screening'].get('quality_issues',[]),'observed_at':latest('observed_at'),'fetched_at':latest('fetched_at'),'reasons':reasons,'snapshot_digest':snap['id'],'policy_digest':snap['policy_digest'],'expires_at':dt.datetime.fromtimestamp(snap['expires'],dt.timezone.utc).isoformat(),'continuation':{'availability':'unavailable','reason':'Authenticated human authorization verifier is not configured.','action_url':None,'expected_revision':snap['id']},'research':{'run_id':decision['run_id'],'status':decision['status'],'report_id':None,'report_version':None,'budget':json.loads(decision['budget']),'pillars':pillars,'reason':'One or more research producers are unavailable; no completed report.' if decision['status']=='incomplete' else None} if decision else None}
@app.get('/cases')
@app.get('/scouting/cases')
def scouting_cases():
 import datetime as dt
 with db() as c:
  total=c.execute('SELECT count(*) FROM cases').fetchone()[0]
  if total>5000: err(503,'Case index exceeds bounded list capacity; cursor pagination required')
  policy=__import__('case_engine').policy_digest();items=[case_view(c,x,policy) for x in c.execute('SELECT * FROM cases').fetchall()]
 items.sort(key=lambda x:(x['priority_order'],x['candidate_id']))
 return {'schema_version':'scouting-case-list/1','generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'stale_after_seconds':60,'cases':items[:100],'truncated':total>100,'authentication':'none; local operator prototype'}
@app.get('/cases/{case_id}')
@app.get('/scouting/cases/{case_id}')
def scouting_case(case_id:str):
 with db() as c:return case_view(c,getrow(c,'SELECT * FROM cases WHERE id=?',(case_id,)))
@app.post('/scouting/cases/{case_id}/challenge')
def challenge(case_id:str,x:ChallengeRequest,idempotency_key:str=Header(None)):
 import secrets
 k=key(idempotency_key)
 with db() as c:
  c.execute('BEGIN IMMEDIATE');case=getrow(c,'SELECT * FROM cases WHERE id=?',(case_id,));snap=getrow(c,'SELECT * FROM case_snapshots WHERE id=?',(case['current_snapshot'],))
  old=c.execute('SELECT * FROM case_challenges WHERE idem=?',(k,)).fetchone()
  if old:
   if (old['case_id'],old['snapshot_id'],old['action'])!=(case_id,x.expected_revision,x.action):err(409,'Idempotency key conflict')
   old_state=old['state']
   if old_state=='pending' and old['expires']<=now():old_state='expired'
   if old_state=='pending' and (case['current_snapshot']!=old['snapshot_id'] or __import__('case_engine').policy_digest()!=old['policy_digest']):old_state='superseded'
   return {'challenge_id':old['id'],'case_id':case_id,'candidate_id':case['candidate_id'],'snapshot_digest':old['snapshot_id'],'policy_digest':old['policy_digest'],'action':old['action'],'nonce':old['nonce'],'state':old_state,'expires_at':old['expires'],'verification':'unavailable'}
  if snap['id']!=x.expected_revision or snap['expires']<=now() or __import__('case_engine').policy_digest()!=snap['policy_digest']:err(409,'Snapshot is stale or superseded')
  if case['state'] not in ('awaiting_human','monitoring'):err(409,'Case is not awaiting an exception')
  i=ident();nonce=secrets.token_hex(32);expires=min(snap['expires'],now()+900)
  c.execute('INSERT INTO case_challenges VALUES(?,?,?,?,?,?,?,?,?,?)',(i,case_id,snap['id'],snap['policy_digest'],x.action,nonce,'pending',expires,now(),k))
  c.execute("UPDATE cases SET state='awaiting_human',updated=? WHERE id=?",(now(),case_id))
  return {'challenge_id':i,'case_id':case_id,'candidate_id':case['candidate_id'],'snapshot_digest':snap['id'],'policy_digest':snap['policy_digest'],'action':x.action,'nonce':nonce,'state':'pending','expires_at':expires,'verification':'unavailable'}
@app.post('/scouting/challenges/{challenge_id}/continue')
def continue_challenge(challenge_id:str):
 # Fail closed until the separately owned verifier checks action, identity, nonce, expiry and revocation.
 with db() as c:
  challenge=getrow(c,'SELECT * FROM case_challenges WHERE id=?',(challenge_id,))
  if challenge['state']!='pending' or challenge['expires']<=now():err(409,'Challenge is expired or superseded')
  case=getrow(c,'SELECT * FROM cases WHERE id=?',(challenge['case_id'],))
  if case['current_snapshot']!=challenge['snapshot_id'] or __import__('case_engine').policy_digest()!=challenge['policy_digest']:err(409,'Challenge is stale or superseded')
 err(503,'Authenticated human verification adapter is not configured')

@app.get('/scouting/challenges/{challenge_id}')
def challenge_status(challenge_id:str):
 with db() as c:
  challenge=getrow(c,'SELECT * FROM case_challenges WHERE id=?',(challenge_id,));case=getrow(c,'SELECT * FROM cases WHERE id=?',(challenge['case_id'],));state=challenge['state']
  if state=='pending' and challenge['expires']<=now():state='expired'
  if state=='pending' and (case['current_snapshot']!=challenge['snapshot_id'] or __import__('case_engine').policy_digest()!=challenge['policy_digest']):state='superseded'
  return {'challenge_id':challenge_id,'candidate_id':case['candidate_id'],'snapshot_digest':challenge['snapshot_id'],'policy_digest':challenge['policy_digest'],'action':challenge['action'],'nonce':challenge['nonce'],'expires_at':challenge['expires'],'state':state,'verification':'unavailable'}
@app.post('/scouting/challenges/{challenge_id}/{human_action}')
def human_challenge_action(challenge_id:str,human_action:Literal['deny','revoke','revise']):
 with db() as c:getrow(c,'SELECT id FROM case_challenges WHERE id=?',(challenge_id,))
 err(503,'Authenticated human verification adapter is not configured')

@app.get('/scouting/sources')
def scouting_sources():
 with db() as c:return {'sources':[row(x) for x in c.execute('SELECT * FROM case_sources ORDER BY id')],'reddit_lead_storage':'blocked_pending_retention_and_deletion_review','authentication':'none; local operator prototype'}
@app.get('/scouting/leads')
def scouting_leads():
 # No post identifiers, excerpts, author metadata or derived content are stored until deletion is implemented.
 return {'leads':[],'status':'unavailable','reason':'Reddit provider access and deletion/retention lifecycle are not implemented; no lead can vote or qualify.'}

@app.get('/scouting/schema')
def scouting_schema():
 path=ROOT/'schemas/runtime/scouting-case-list-v1.schema.json';raw=path.read_bytes()
 return {'schema_version':'scouting-case-list/1','sha256':digest(raw),'schema':json.loads(raw)}
