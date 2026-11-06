"""Huey is a wake-up mechanism; the database is the durable source of work."""
import json, os, shutil, subprocess, sys, time
from pathlib import Path
from huey import SqliteHuey, crontab
from store import ROOT, DATA, db, now, event, PILLARS, digest
huey=SqliteHuey('scooby',filename=str(DATA/'huey.sqlite3'), immediate=False)

def work_one():
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  c.execute("UPDATE jobs SET state='queued', lease=NULL WHERE state='running' AND lease<?",(now(),))
  j=c.execute("SELECT * FROM jobs WHERE state='queued' AND available<=? ORDER BY created LIMIT 1",(now(),)).fetchone()
  if not j: return False
  c.execute("UPDATE jobs SET state='running', attempts=attempts+1, lease=? WHERE id=?",(now()+300,j['id']))
 try:
  if j['kind']=='scan':
   # No live verifiers are shipped. Do not manufacture positive screenings.
   result='No discovery or concern verifiers configured; coverage unknown.'
  elif j['kind']=='investigate':
   with db() as c:
    run=c.execute('SELECT status FROM investigations WHERE id=?',(j['ref'],)).fetchone()
    if not run or run['status']=='cancelled': result='cancelled'
    else:
     for p in PILLARS:
      c.execute("UPDATE pillars SET status='unavailable', detail=? WHERE run_id=? AND pillar=? AND status='queued'",('No research producer configured; no findings inferred.',j['ref'],p))
      event(c,j['ref'],'pillar_unavailable',p)
     c.execute("UPDATE investigations SET status='incomplete' WHERE id=?",(j['ref'],)); event(c,j['ref'],'incomplete','Research adapters unavailable'); result='incomplete'
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
   out=DATA/'artifacts'/j['id']; out.parent.mkdir(parents=True,exist_ok=True)
   if out.exists(): shutil.rmtree(out)
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
     import tempfile
     try:
      # Source/model text is escaped; JS opens all original details after the reader has rendered.
      extra='<section class="full-report"><h1>Full report (source Markdown)</h1><pre>'+html_module.escape(markdown)+'</pre></section>'
      style='<style>@media print{details{break-inside:auto} .full-report{break-before:page} .full-report pre{white-space:pre-wrap;overflow-wrap:anywhere;font:9pt/1.45 sans-serif} nav,.skip{display:none}}</style>'
      script='<script>document.querySelectorAll("details").forEach(x=>x.open=true);</script>'
      printable=html.replace('</head>',style+'</head>',1).replace('</body>',extra+script+'</body>',1)
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
   result='HTML draft generated; PDF '+pdf_status
  else: raise RuntimeError('unknown job kind')
  with db() as c:
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
   if j['kind']=='reason':
    attempts=3 # never retry a possibly billed provider call automatically
    c.execute("UPDATE reasoning_inputs SET status='failed' WHERE id=?",(j['ref'],))
   c.execute('UPDATE jobs SET state=?, available=?, lease=NULL, error=? WHERE id=?',('failed' if attempts>=3 else 'queued',now()+min(60,2**attempts),type(e).__name__+': operation failed; inspect configuration',j['id']))
 return True
@huey.task()
def wake(): work_one()
@huey.periodic_task(crontab(minute='*'))
def reconcile():
 with db() as c: c.execute("INSERT OR REPLACE INTO heartbeats VALUES(?,?,?)",('worker',now(),'reconciliation active'))
 for _ in range(10):
  if not work_one(): break
