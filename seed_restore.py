"""Explicit offline restore of selected report seed entries, never admission or publication."""
import argparse, json, os, re, shutil, tempfile, zipfile
from pathlib import Path
from store import DATA, db, digest, dumps, event, job, now, PILLARS
from modules.investigation.contract_validate import verify_digest

def restore(root, manifest_sha, selected):
 if os.getenv('SCOOBY_REPORT_RELEASE','').strip().lower()!='approved':raise ValueError('SCOOBY_REPORT_RELEASE=approved required before seed restore')
 root=Path(root).resolve()
 if root.is_file() and root.suffix.lower()=='.zip':
  with tempfile.TemporaryDirectory(dir=DATA) as tmp:
   with zipfile.ZipFile(root) as z:
    members=z.infolist()
    if len(members)>10000 or sum(x.file_size for x in members)>200_000_000:raise ValueError('seed archive exceeds limits')
    for item in members:
     path=item.filename
     if not path or '\\' in path or path.startswith('/') or any(x in ('','.','..') for x in path.rstrip('/').split('/')) or ':' in path or (item.external_attr >> 16) & 0o170000 == 0o120000:raise ValueError('unsafe archive entry')
    z.extractall(tmp)
   base=Path(tmp); manifests=list(base.glob('manifest.json'))+list(base.glob('*/manifest.json'))
   if len(manifests)!=1:raise ValueError('seed manifest location ambiguous')
   return restore(manifests[0].parent,manifest_sha,selected)
 manifest=root/'manifest.json'
 if not re.fullmatch('[0-9a-f]{64}',manifest_sha) or manifest.is_symlink() or digest(manifest.read_bytes())!=manifest_sha:raise ValueError('manifest hash mismatch')
 m=json.loads(manifest.read_bytes()); entries=m['reports']; chosen=[x for x in entries if x['report_id'] in selected]
 if len(chosen)!=len(selected) or len(set(selected))!=len(selected):raise ValueError('missing or duplicate selection')
 verified=[]
 with tempfile.TemporaryDirectory(dir=DATA) as tmp:
  for x in chosen:
   name=x['folder']
   if not re.fullmatch(r'report-[0-9]+-[0-9a-f]+',name):raise ValueError('unsafe seed path')
   folder=root/name
   if folder.is_symlink() or any(p.is_symlink() for p in folder.rglob('*')):raise ValueError('unsafe seed links')
   candidate_raw=(folder/'candidate.json').read_bytes(); candidate=json.loads(candidate_raw)
   if digest(candidate_raw)!=x['candidate_sha256'] or candidate['candidate_id']!=x['candidate_id']:raise ValueError('candidate integrity mismatch')
   snap=Path(tmp)/name;shutil.copytree(folder/'bundle',snap)
   doc=verify_digest(snap,x['report_sha256'])
   if (doc['report_id'],doc['report_version'],doc['candidate_id'],doc['mode'])!=(x['report_id'],x['version'],x['candidate_id'],x['mode']) or doc['review']['status']!='pending':raise ValueError('report identity or review mismatch')
   diagnostic=doc['mode']=='historical_replay' and (snap/'case-lineage.json').is_file()
   if diagnostic:
    lin=json.loads((snap/'case-lineage.json').read_bytes())
    if lin.get('candidate_id')!=x['candidate_id'] or lin.get('run_id')!=x['original_run_id'] or lin.get('authorization_reference_id')!='synthetic_auth_not_admission':raise ValueError('diagnostic lineage mismatch')
   verified.append((x,candidate,doc,snap,diagnostic))
  targets=[]
  for x,candidate,doc,snap,diagnostic in verified:
   target=DATA/'bundles'/x['report_sha256'];target.parent.mkdir(exist_ok=True)
   if not target.exists():os.rename(snap,target)
   verify_digest(target,x['report_sha256']);targets.append(target)
  with db() as c:
   c.execute('BEGIN IMMEDIATE')
   for (x,candidate,doc,_,diagnostic),target in zip(verified,targets):
    run=x['original_run_id']; old=c.execute('SELECT * FROM reports WHERE id=? AND version=?',(x['report_id'],x['version'])).fetchone()
    if old:
     if (old['sha256'],old['run_id'])!=(x['report_sha256'],run):raise ValueError('immutable report conflict')
     continue
    if c.execute('SELECT 1 FROM investigations WHERE id=?',(run,)).fetchone():raise ValueError('run identity conflict')
    cid=x['candidate_id']; sel='seed-'+run
    existing=c.execute('SELECT payload FROM candidates WHERE id=?',(cid,)).fetchone()
    if existing and json.loads(existing['payload']).get('candidate_id')!=cid:raise ValueError('candidate conflict')
    c.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?)',(cid,dumps(candidate),now()))
    description='Restored historical diagnostic; pending human review. No case admission or World verification. Editorial provenance, when present, is a local edit; seed does not prove independent review.' if diagnostic else 'Restored source-curated reference; pending review, no World verification or case admission.'
    c.execute('INSERT INTO selections VALUES(?,?,?,?,?,?,?)',(sel,cid,'diagnostic_exception','seed import',description,now(),'seed-sel:'+run))
    c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?)',(run,cid,sel,'reference_only',now(),'seed-run:'+run))
    for p in PILLARS:c.execute('INSERT INTO pillars VALUES(?,?,?,?)',(run,p,doc['pillars'][p]['status'],doc['pillars'][p]['summary']))
    if diagnostic:c.execute('INSERT INTO diagnostic_imports VALUES(?,?,?,?,?)',(run,cid,description,'restored_pending_review',now()))
    c.execute('INSERT INTO reports VALUES(?,?,?,?,?,?)',(x['report_id'],x['version'],run,x['report_sha256'],str(target),now()))
    event(c,run,'seed_imported',description)
    job(c,'render',dumps({'id':x['report_id'],'version':x['version'],'sha256':x['report_sha256']}),'seed-render:'+run)
 return len(verified)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('seed');p.add_argument('--manifest-sha256',required=True);p.add_argument('--report-id',action='append',required=True)
 a=p.parse_args();print('Restored',restore(a.seed,a.manifest_sha256,a.report_id),'pending reports')
