"""Isolated read-only loopback review of six explicitly selected unapproved references."""
import json,sqlite3,hashlib,pathlib,re
from fastapi import FastAPI,HTTPException,Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
ROOT=pathlib.Path(r'C:\Users\ASUS\Documents\Codex\2026-11-06\scooby-dao-backend\outputs\new-scout-cases-runtime')
ITEMS={'shib':('ac40e79f2e6e1cc2d011d487d8a9d259700591f0f1f85f46bfa22fcd171b25ea','case-shib_reference_research','run-shib_reference_replay_20261107'),'fet':('7b460f8e9e93aa02d7c6425b1450ec6e30c97c0beab9539a94261c4ce4daa0b8','case-reference_fet','run-reference_fet_20261107'),'spx':('bbe3daeeccbe5273e4a1f742a6a872dea08e7d8313e99de4ac3ccb6203d04800','case-reference_spx','run-reference_spx_20261107'),'yfi':('a7b75ac2adac7deb04fb9b11dacd165eb32a03f49c192b76ae654f6a8ee49e92','case-reference_yfi','run-reference_yfi_20261107'),'grt':('2f156e0056d0629c85967e90b8023ba8f7cbc827462f93a00fb021125ce16b89','case-reference_grt','run-reference_grt_20261107'),'metis':('72557d92517b2a7e6ac0cea716bc3ca5006c78c8bfc27e3b8eb89fa5ff82b5ab','case-reference_metis','run-reference_metis_20261107')}
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:3139','http://127.0.0.1:3139'],allow_methods=['GET'],allow_headers=['Content-Type'])
sha=lambda b:hashlib.sha256(b).hexdigest()
@app.middleware('http')
async def no_store(req,call_next):
 response=await call_next(req);response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';return response

def load(name):
 if name not in ITEMS:raise HTTPException(404)
 case,rid,ver=ITEMS[name];db=sqlite3.connect((ROOT/'state.sqlite3').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 try:
  r=db.execute('SELECT r.*,c.candidate_id,i.status FROM case_reference_reports l JOIN cases c ON c.id=l.case_id JOIN reports r ON r.id=l.report_id AND r.version=l.version JOIN investigations i ON i.id=r.run_id WHERE l.case_id=? AND r.id=? AND r.version=? AND i.candidate_id=c.candidate_id',(case,rid,ver)).fetchone()
  if not r or r['status']!='reference_only':raise HTTPException(404)
  raw=(pathlib.Path(r['path'])/'report.json').read_bytes()
  if sha(raw)!=r['sha256'] or json.loads(raw)['candidate_id']!=r['candidate_id']:raise HTTPException(409)
  jobs=db.execute("SELECT id,ref FROM jobs WHERE kind='render' AND state='done' ORDER BY created DESC").fetchall()
  j=next((x for x in jobs if json.loads(x['ref'])=={'id':rid,'version':ver,'sha256':r['sha256']}),None)
  if not j:raise HTTPException(503,'render unavailable')
  lock=db.execute('SELECT sha256 FROM render_manifests WHERE job_id=?',(j['id'],)).fetchone();out=ROOT/'artifacts'/j['id'];mraw=(out/'manifest.json').read_bytes()
  if not lock or sha(mraw)!=lock['sha256']:raise HTTPException(409)
  m=json.loads(mraw)
  if (m['report_id'],m['report_version'],m['report_sha256'])!=(rid,ver,r['sha256']):raise HTTPException(409)
  html=(out/'index.html').read_bytes()
  if sha(html)!=m['html_sha256']:raise HTTPException(409)
  doc=json.loads(raw); files={'report.json':r['sha256']}
  for item in doc.get('evidence',[])+doc.get('artifacts',[]):
   path=item.get('path'); value=item.get('sha256')
   if path is None and item.get('availability')=='unavailable':continue
   if not isinstance(path,str) or not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{64}',value):raise HTTPException(409,'invalid descriptor')
   if path in files and files[path]!=value:raise HTTPException(409,'conflicting descriptor')
   files[path]=value
  return {'symbol':name.upper(),'case_id':case,'candidate_id':r['candidate_id'],'report_id':rid,'version':ver,'report_sha256':r['sha256'],'html_sha256':m['html_sha256'],'status':'unreviewed_historical_reference','world_verified':False,'gate_effect':'none','html_url':'/preview/'+name+'/html','files':files},html,pathlib.Path(r['path'])
 except (OSError,ValueError,KeyError,json.JSONDecodeError):raise HTTPException(409,'artifact integrity unavailable')
 finally:db.close()
@app.get('/preview')
def listing():return {'notice':'LOCAL REVIEW ONLY: unreviewed historical references; synthetic lineage; no World or gate approval.','reports':[load(n)[0] for n in ITEMS]}
@app.get('/preview/{name}/html')
def report(name:str):
 info,raw,_=load(name); banner=b'<div style="padding:16px;background:#fff3c4;color:#111;font:16px sans-serif">LOCAL REVIEW ONLY - Unreviewed historical reference; synthetic lineage. No World or gate approval.</div>'
 return HTMLResponse(content=banner+raw,headers={'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'"})

@app.get('/preview/{name}/files/{file_path:path}')
def bundle_file(name:str,file_path:str):
 info,_,root=load(name);expected=info['files'].get(file_path)
 if expected is None:raise HTTPException(404)
 parts=pathlib.PurePosixPath(file_path).parts
 if not parts or any(x in ('.','..') for x in parts) or '\\' in file_path or file_path.startswith('/'):raise HTTPException(404)
 target=root
 for part in parts:
  target=target/part
  if target.is_symlink():raise HTTPException(409)
 try:
  if not target.resolve().is_relative_to(root.resolve()) or target.stat().st_size>20000000:raise HTTPException(409)
  content=target.read_bytes()
 except OSError:raise HTTPException(409)
 if sha(content)!=expected:raise HTTPException(409,'artifact integrity unavailable')
 ext=target.suffix.lower();media={' .json':'application/json','.json':'application/json','.md':'text/plain; charset=utf-8','.csv':'text/plain; charset=utf-8','.png':'image/png','.svg':'image/svg+xml'}.get(ext,'application/octet-stream')
 return Response(content=content,media_type=media,headers={'Content-Security-Policy':"default-src 'none'; sandbox"})
