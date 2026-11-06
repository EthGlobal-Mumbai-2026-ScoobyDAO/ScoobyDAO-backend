"""Huey is a wake-up mechanism; the database is the durable source of work."""
import json, os, shutil, subprocess, sys, time, tempfile
from pathlib import Path
from huey import SqliteHuey, crontab
from store import ROOT, DATA, db, now, event, PILLARS, digest, dumps, job
from vendor.pdf_export.full_draft_pdf import print_source
huey=SqliteHuey('scooby',filename=str(DATA/'huey.sqlite3'), immediate=False)

def validate_render(out,ref):
 """Validate complete package before publishing or reusing a crash-recovered result."""
 if out.is_symlink() or not out.is_dir(): raise RuntimeError('unsafe render directory')
 report=out/'report.json'; manifest=out/'manifest.json'
 if report.is_symlink() or manifest.is_symlink() or not report.is_file() or not manifest.is_file() or digest(report.read_bytes())!=ref['sha256']: raise RuntimeError('render report mismatch')
 d=json.loads(report.read_bytes()); m=json.loads(manifest.read_bytes())
 if (m.get('report_id'),m.get('report_version'),m.get('report_sha256'))!=(ref['id'],ref['version'],ref['sha256']): raise RuntimeError('render manifest mismatch')
 for name,k in [('index.html','html_sha256'),('report.md','markdown_sha256'),('report.pdf','pdf_sha256')]:
  if m.get(k):
   path=out/name
   if path.is_symlink() or not path.is_file() or digest(path.read_bytes())!=m[k]: raise RuntimeError('render artifact mismatch')
 for item in d['evidence']+[a for a in d['artifacts'] if a['availability']=='available']:
  name=item['path']
  if not name or any(x in name for x in ('\\',':','%','?','#')) or any(x in ('','.','..') for x in name.split('/')): raise RuntimeError('unsafe asset')
  f=out/'assets'
  for part in name.split('/'):
   f=f/part
   if f.is_symlink(): raise RuntimeError('symlink asset')
  if not f.is_file() or digest(f.read_bytes())!=item['sha256']: raise RuntimeError('asset mismatch')
 return digest(manifest.read_bytes())

def work_one():
 # SCOOBY_DISPLAY_ONLY=true: never consume queued work, even if a worker was started by mistake.
 if os.getenv('SCOOBY_DISPLAY_ONLY','').strip().lower() in ('1','true','yes','on'): return False
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  c.execute("UPDATE jobs SET state='failed', lease=NULL, error='Scout interrupted; manual inspection required' WHERE kind='scout_collect' AND state='running' AND lease<?",(now(),))
  c.execute("UPDATE jobs SET state='queued', lease=NULL WHERE kind!='scout_collect' AND state='running' AND lease<?",(now(),))
  j=c.execute("SELECT * FROM jobs WHERE state='queued' AND available<=? ORDER BY created LIMIT 1",(now(),)).fetchone()
  if not j: return False
  c.execute("UPDATE jobs SET state='running', attempts=attempts+1, lease=? WHERE id=?",(now()+300,j['id']))
  attempt=j['attempts']+1
 try:
  if j['kind']=='scout_collect':
   import case_engine
   import bounded_scout
   source_db=os.getenv('SCOOBY_DISCOVERY_DB');source_root=os.getenv('SCOOBY_DISCOVERY_ROOT')
   try:
    budget=int(os.getenv('SCOOBY_SCOUT_CYCLE_BUDGET','0'));hourly=int(os.getenv('SCOOBY_SCOUT_HOURLY_BUDGET','0'));limit=int(os.getenv('SCOOBY_SCOUT_LIMIT_PER_CHAIN','5'))
   except ValueError:budget=hourly=0;limit=5
   if not source_db or not source_root:outcome={'status':'configuration_unavailable','calls':0}
   else:outcome=bounded_scout.run_once(source_db,source_root,enabled=os.getenv('SCOOBY_SCOUT_ENABLED','false').lower()=='true',budget=budget,hourly_limit=hourly,limit=limit)
   result=dumps(outcome)
   with db() as c:
    if outcome['status'] in ('ok','partial','no_leads'):
     c.execute("UPDATE case_sources SET status=?,detail=?,updated=? WHERE id='discovery'",('available' if outcome['status']!='partial' else 'unavailable','Bounded scout cycle '+outcome['status']+'; evidence freshness is per source.',now()))
     job(c,'case_scan','25','scout-sync:'+j['id'])
    elif outcome['status']!='not_due':c.execute("UPDATE case_sources SET status='unavailable',detail=?,updated=? WHERE id='discovery'",('Scout '+outcome['status']+'; no clean result inferred.',now()))
  elif j['kind']=='case_scan':
   import case_engine
   result=dumps(case_engine.reconcile(int(j['ref'])))
   with db() as c:c.execute("UPDATE case_sources SET status='available',detail=?,updated=? WHERE id='discovery'",('Local discovery snapshot synchronized; source freshness is per evidence.',now()))
  elif j['kind']=='case_start':
   import case_engine
   result='Research run '+case_engine.start_decision(j['ref'])
  elif j['kind']=='scan':
   # No live verifiers are shipped. Do not manufacture positive screenings.
   result='No discovery or concern verifiers configured; coverage unknown.'
  elif j['kind']=='investigate':
   with db() as c:is_case=bool(c.execute('SELECT 1 FROM case_decisions WHERE run_id=?',(j['ref'],)).fetchone())
   if is_case:
    import case_jobs
    result=case_jobs.run_case(j['ref'])
   else:
    with db() as c:
     run=c.execute('SELECT status FROM investigations WHERE id=?',(j['ref'],)).fetchone()
     if not run or run['status']=='cancelled':result='cancelled'
     else:
      for p in PILLARS:c.execute("UPDATE pillars SET status='unavailable', detail=? WHERE run_id=? AND pillar=? AND status='queued'",('No research producer configured; no findings inferred.',j['ref'],p))
      c.execute("UPDATE investigations SET status='incomplete' WHERE id=?",(j['ref'],));event(c,j['ref'],'incomplete','Legacy non-case research producer unavailable');result='incomplete'

  elif j['kind']=='reason':
   import provider
   with db() as c:
    c.execute('BEGIN IMMEDIATE')
    inp=c.execute('SELECT * FROM reasoning_inputs WHERE id=?',(j['ref'],)).fetchone()
    run=c.execute('SELECT status FROM investigations WHERE id=?',(inp['run_id'],)).fetchone()
    if run['status']=='cancelled': raise RuntimeError('cancelled')
    budget=int(os.getenv('SCOOBY_MODEL_CALL_BUDGET','0'))
    used=c.execute('SELECT count(*) FROM budget_reservations').fetchone()[0]
    if used>=budget or c.execute('SELECT 1 FROM budget_reservations WHERE job_id=?',(j['id'],)).fetchone(): raise RuntimeError('budget exhausted or attempt already reserved')
    c.execute('INSERT INTO budget_reservations VALUES(?,?)',(j['id'],now()))
   output=provider.reason(json.loads(inp['evidence']))
   with db() as c:
    c.execute("UPDATE reasoning_inputs SET output=?,status='complete' WHERE id=?",(json.dumps(output,allow_nan=False),inp['id']))
    event(c,inp['run_id'],'reasoning_complete','Operator-supplied evidence; not an investigation report')
   result='Bounded provider result stored; research coverage remains unverified.'
  elif j['kind']=='render':
   ref=json.loads(j['ref']); frontend=os.getenv('SCOOBY_FRONTEND_DIR', str(ROOT/'vendor'/'reader'))
   if not frontend: raise RuntimeError('SCOOBY_FRONTEND_DIR not configured')
   with db() as c:
    report=c.execute('SELECT * FROM reports WHERE id=? AND version=?',(ref['id'],ref['version'])).fetchone()
   if not report or report['sha256']!=ref['sha256'] or digest((Path(report['path'])/'report.json').read_bytes())!=ref['sha256']: raise RuntimeError('report version mismatch')
   final=DATA/'artifacts'/j['id']; final.parent.mkdir(parents=True,exist_ok=True)
   # A published path is never replaced: retry reuses a fully verified existing result.
   if final.exists():
    validate_render(final,ref)
    out=final
    result='Existing immutable render recovered'
   else:
    out=Path(tempfile.mkdtemp(prefix='.render-',dir=final.parent)); out.rmdir()
    subprocess.run([sys.executable,str(Path(frontend)/'build.py'),str(Path(report['path'])/'report.json'),str(out)],check=True,timeout=120,capture_output=True)
    # The generated reader is always a visibly pending-review draft, never an approved export.
    page=out/'index.html'; html=page.read_text(encoding='utf-8-sig')
    banner='<div style="background:#fff1b8;color:#222;padding:12px;font:16px sans-serif">PENDING REVIEW - LOCAL DRAFT | report '+ref['id']+' | version '+ref['version']+' | SHA-256 '+ref['sha256']+'</div>'
    import html as html_module
    banner='<div style="background:#fff1b8;color:#222;padding:12px;font:16px sans-serif">'+html_module.escape('PENDING REVIEW - LOCAL DRAFT | report '+ref['id']+' | version '+ref['version']+' | SHA-256 '+ref['sha256'])+'</div>'
    html=html.replace('<body>', '<body>'+banner, 1); page.write_text(html,encoding='utf-8')
    # The full PDF includes expanded reader details and exact, hash-verified Markdown.
    doc=json.loads((Path(report['path'])/'report.json').read_text(encoding='utf-8-sig'))
    markdowns=[a for a in doc['artifacts'] if a['kind']=='markdown' and a['availability']=='available']
    pdf=out/'report.pdf'; browser=os.getenv('SCOOBY_BROWSER'); pdf_status='unavailable: SCOOBY_BROWSER not configured'; markdown_sha=None
    if len(markdowns)!=1:
     pdf_status='unavailable: exactly one bound Markdown report required'
    else:
     m=markdowns[0]; markdown_path=out/'assets'/m['path']
     if not markdown_path.is_file() or digest(markdown_path.read_bytes())!=m['sha256']: raise RuntimeError('Markdown digest mismatch')
     markdown=markdown_path.read_text(encoding='utf-8-sig'); markdown_sha=m['sha256']; (out/'report.md').write_bytes(markdown_path.read_bytes())
     if browser:
      try:
       # Shared adapter validates report identity and bound Markdown before preparing print HTML.
       printable, _ = print_source(page, out/'report.json', ref['sha256'])
       (out/'print.html').write_text(printable,encoding='utf-8')
       with tempfile.TemporaryDirectory(dir=DATA) as profile:
        subprocess.run([browser,'--headless','--disable-gpu','--no-first-run','--no-default-browser-check','--no-pdf-header-footer','--virtual-time-budget=3000','--user-data-dir='+profile,'--print-to-pdf='+str(pdf),(out/'print.html').resolve().as_uri()],check=True,timeout=90,capture_output=True)
       if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'): raise RuntimeError('PDF missing')
       pdf_status='available'
      except Exception:
       if pdf.exists(): pdf.unlink()
       pdf_status='failed: browser rendering failed'
    manifest={'report_id':ref['id'],'report_version':ref['version'],'report_sha256':ref['sha256'],'status':'pending_review_draft','html_sha256':digest(page.read_bytes()),'markdown_sha256':markdown_sha,'pdf_status':pdf_status,'pdf_sha256':digest(pdf.read_bytes()) if pdf.is_file() else None,'pdf_content':'expanded reader and bound full Markdown' if pdf.is_file() else None}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    validate_render(out,ref)
    try: os.rename(out,final)
    except OSError:
     if not final.exists(): raise
     validate_render(final,ref)
     shutil.rmtree(out) # private staging directory created by this attempt
    out=final
    result='HTML draft generated; PDF '+pdf_status
  else: raise RuntimeError('unknown job kind')
  with db() as c:
   current=c.execute('SELECT state,attempts FROM jobs WHERE id=?',(j['id'],)).fetchone()
   if current['state']!='running' or current['attempts']!=attempt: return True
   if j['kind']=='render':
    manifest_sha=digest((out/'manifest.json').read_bytes())
    existing=c.execute('SELECT sha256 FROM render_manifests WHERE job_id=?',(j['id'],)).fetchone()
    if existing and existing['sha256']!=manifest_sha: raise RuntimeError('immutable render manifest conflict')
    c.execute('INSERT OR IGNORE INTO render_manifests VALUES(?,?)',(j['id'],manifest_sha))
   c.execute("UPDATE jobs SET state='done', lease=NULL, error=? WHERE id=?",(result,j['id']))
 except Exception as e:
  with db() as c:
   # Bounded exponential backoff. Persist terminal errors without exception payloads that could contain secrets.
   attempts=c.execute('SELECT attempts FROM jobs WHERE id=?',(j['id'],)).fetchone()[0]
   if j['kind']=='scout_collect':
    attempts=3 # Never automatically repeat a possibly transmitted provider request.
    c.execute("UPDATE case_sources SET status='unavailable',detail=?,updated=? WHERE id='discovery'",('Scout failed; no clean result inferred.',now()))
   if j['kind']=='case_scan':
    c.execute("UPDATE case_sources SET status='unavailable',detail=?,updated=? WHERE id='discovery'",('Configured discovery store is unavailable; no case was qualified from this failure.',now()))
   if j['kind']=='case_start':
    c.execute("UPDATE cases SET state='unavailable',updated=? WHERE id=(SELECT case_id FROM case_decisions WHERE id=?) AND current_snapshot=(SELECT snapshot_id FROM case_decisions WHERE id=?) AND NOT EXISTS (SELECT 1 FROM case_decisions WHERE id=? AND run_id IS NOT NULL)",(now(),j['ref'],j['ref'],j['ref']))
   if j['kind']=='investigate':
    from case_model import ModelStageBlocked
    if isinstance(e,ModelStageBlocked):
     attempts=3;c.execute("UPDATE investigations SET status='blocked' WHERE id=? AND status NOT IN ('cancelled','partial','complete')",(j['ref'],));event(c,j['ref'],'model_stage_blocked',dumps({'stage':'reasoning','state':'blocked','reason':'attempt_consumed_or_authorization_changed'}))
    elif attempts>=3:c.execute("UPDATE investigations SET status='failed' WHERE id=? AND status NOT IN ('cancelled','partial','complete')",(j['ref'],))
   if j['kind']=='reason':
    attempts=3 # never retry a possibly billed provider call automatically
    c.execute("UPDATE reasoning_inputs SET status='failed' WHERE id=?",(j['ref'],))
   c.execute("UPDATE jobs SET state=?, available=?, lease=NULL, error=? WHERE id=? AND state='running' AND attempts=?",('failed' if attempts>=3 else 'queued',now()+min(60,2**attempts),type(e).__name__+': operation failed; inspect configuration',j['id'],attempt))
 return True
@huey.task()
def wake(): work_one()
def enqueue_periodic_case_sync():
 if os.getenv('SCOOBY_DISPLAY_ONLY','').strip().lower() in ('1','true','yes','on'): return None
 # Local DB reconciliation only; discovery owns all outbound collection.
 if os.getenv('SCOOBY_CASE_SYNC_ENABLED','false').lower()!='true': return None
 try: limit=max(1,min(25,int(os.getenv('SCOOBY_CASE_SYNC_LIMIT','10'))))
 except ValueError: limit=10
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute("SELECT 1 FROM jobs WHERE kind='case_scan' AND state IN ('queued','running') LIMIT 1").fetchone(): return None
  return job(c,'case_scan',str(limit),'case-period:'+str(int(now()//60)))
def enqueue_periodic_scout():
 if os.getenv('SCOOBY_DISPLAY_ONLY','').strip().lower() in ('1','true','yes','on'):return None
 if os.getenv('SCOOBY_SCOUT_ENABLED','false').lower()!='true':return None
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute("SELECT 1 FROM jobs WHERE kind='scout_collect' AND state IN ('queued','running') LIMIT 1").fetchone():return None
  return job(c,'scout_collect','bounded','scout-period:'+str(int(now()//300)))
@huey.periodic_task(crontab(minute='*'))
def reconcile():
 enqueue_periodic_scout()
 enqueue_periodic_case_sync()
 with db() as c: c.execute("INSERT OR REPLACE INTO heartbeats VALUES(?,?,?)",('worker',now(),'reconciliation active'))
 for _ in range(10):
  if not work_one(): break
