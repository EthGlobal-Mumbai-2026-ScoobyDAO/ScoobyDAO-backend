import argparse, hashlib, json, shutil, sys, math
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def load(p):
 return json.loads(p.read_text(encoding='utf-8-sig'),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('non-finite number')))
def safe(root, value):
 if not isinstance(value,str) or not value or any(c in value for c in ('\\',':','%','?', '#')) or value.startswith('/') or any(x in ('','.','..') for x in value.split('/')): raise ValueError('unsafe path: '+str(value))
 p=root
 for part in value.split('/'):
  p=p/part
  if p.is_symlink(): raise ValueError('symlink forbidden')
 if not p.resolve().is_relative_to(root.resolve()) or not p.is_file(): raise ValueError('missing/escaping path: '+value)
 return p

def build(source, dest):
 source=source.resolve(); root=source.parent; d=load(source)
 receipt=load(root/'digest.json')
 if receipt.get('algorithm')!='sha256' or receipt.get('target')!='report.json exact UTF-8 bytes': raise ValueError('unsupported digest protocol')
 if receipt.get('sha256')!=hashlib.sha256(source.read_bytes()).hexdigest(): raise ValueError('report digest mismatch')
 def finite(x):
  if isinstance(x,float) and not math.isfinite(x): raise ValueError('non-finite number')
  if isinstance(x,dict):
   for v in x.values(): finite(v)
  if isinstance(x,list):
   for v in x: finite(v)
 finite(d)
 if d.get('schema_version')!='0.2': raise ValueError('expected v0.2 report')
 if dest.resolve()==root or dest.resolve().is_relative_to(root): raise ValueError('output must be outside input bundle')
 schema=ROOT/'report.schema.json'
 # Validation uses the producer's bundled dependency if available, or an installed jsonschema.
 try: from jsonschema import Draft202012Validator
 except ImportError: raise ValueError('jsonschema is required; see README')
 Draft202012Validator(load(schema)).validate(d)
 if d['review']['status']=='approved_unverified':
  rev=d['review']
  if rev['reviewed_version']!=d['report_version'] or rev['authentication']!='unverified' or not all(rev[k] for k in ('reviewer','reviewed_at','content_sha256')): raise ValueError('unverified review metadata invalid')
 if d['candidate_id']!=str(d['identity']['chain_id'])+':'+d['identity']['address'].lower(): raise ValueError('identity mismatch')
 assets=[]
 evidence={e['id'] for e in d['evidence']}
 claims=[c['id'] for p in d['pillars'].values() for c in p['claims']]
 if len(evidence)!=len(d['evidence']) or len(set(claims))!=len(claims): raise ValueError('duplicate IDs')
 for ids in (d['assessment'].get('supporting_claim_ids',[]),d['assessment'].get('counterevidence_claim_ids',[])):
  if not set(ids)<=set(claims): raise ValueError('unresolved assessment claim')
 for p in d['pillars'].values():
  if not set(p['evidence_ids'])<=evidence: raise ValueError('unresolved pillar evidence')
  for x in p['measurements']+p['series']:
   if not set(x['evidence_ids'])<=evidence: raise ValueError('unresolved measurement evidence')
   if x['quality']=='unknown' and not x['unknown_reason']: raise ValueError('unknown requires reason')
  for c in p['claims']:
   if not set(c['supporting_evidence_ids']+c['counterevidence_ids'])<=evidence or not set(c['contradiction_claim_ids'])<=set(claims): raise ValueError('unresolved claim reference')
 for e in d['evidence']: assets.append((e['path'],e['sha256']))
 for a in d['artifacts']:
  if a['report_id']!=d['report_id'] or a['report_version']!=d['report_version']: raise ValueError('artifact version mismatch')
  if a['availability']=='available': assets.append((a['path'],a['sha256']))
  elif a['path'] is not None or a['sha256'] is not None: raise ValueError('unavailable artifact path/hash')
 bound={a['path'] for a in d['artifacts'] if a['availability']=='available'}
 for p in d['pillars'].values():
  if p['raw_payload_path'] is not None and p['raw_payload_path'] not in bound: raise ValueError('raw payload is not bound as artifact')
 for path, expected in assets:
  f=safe(root,path)
  if hashlib.sha256(f.read_bytes()).hexdigest()!=expected: raise ValueError('asset hash mismatch: '+path)
 # Build into a fresh output so replacement cannot retain stale assets.
 if dest.exists(): raise ValueError('output already exists; choose a new output directory')
 dest.mkdir(parents=True)
 for path,_ in assets:
  target=dest/'assets'/path; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(safe(root,path),target)
 def embed(x): return json.dumps(x,ensure_ascii=True,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
 payload=embed(d)
 mapping_art=[a for a in d['artifacts'] if a['kind']=='mapping_manifest' and a['availability']=='available']
 if len(mapping_art)>1: raise ValueError('duplicate mapping manifest')
 manifest=load(safe(root,mapping_art[0]['path'])) if mapping_art else []
 if not isinstance(manifest,list): raise ValueError('mapping manifest must be a list')
 target_ids={x['id'] for p in d['pillars'].values() for x in p['measurements']+p['series']+p['claims']}
 mapping_ids={x['target_id'] for x in manifest}
 if mapping_art and target_ids!=mapping_ids: raise ValueError('mapping IDs do not match rendered data')
 # Optional, version-bound sidecar; absence is an explicit empty state.
 tldr=None
 tldr_art=[a for a in d['artifacts'] if a['kind']=='pillar_tldr' and a['availability']=='available']
 if len(tldr_art)>1: raise ValueError('duplicate TLDR artifact')
 if tldr_art:
  tldr=load(safe(root,tldr_art[0]['path']))
  if tldr.get('profile')!='scooby.pillar-tldr/1' or tldr.get('report_id')!=d['report_id'] or tldr.get('report_version')!=d['report_version']: raise ValueError('TLDR profile or identity mismatch')
  if not isinstance(tldr.get('pillars'),dict) or set(tldr['pillars'])!=set(d['pillars']): raise ValueError('TLDR pillars mismatch')
  for items in tldr['pillars'].values():
   if not isinstance(items,list) or len(items)>5: raise ValueError('invalid TLDR bullets')
   for item in items:
    if set(item)!={'role','text','claim_ids','evidence_ids'} or item['role'] not in ('finding','support','interpretation','caveat') or not isinstance(item['text'],str) or not item['text'].strip() or not isinstance(item['claim_ids'],list) or not isinstance(item['evidence_ids'],list): raise ValueError('invalid TLDR bullet')
    if not (item['claim_ids'] or item['evidence_ids']) or not set(item['claim_ids'])<=set(claims) or not set(item['evidence_ids'])<=evidence: raise ValueError('TLDR reference unresolved')
 selection=None
 selection_art=[a for a in d['artifacts'] if a['kind'] in ('selection_context','selection') and a['availability']=='available']
 if len(selection_art)>1: raise ValueError('duplicate selection context')
 if selection_art:
  selection=load(safe(root,selection_art[0]['path']))
  if selection.get('candidate_id')!=d['candidate_id']: raise ValueError('selection identity mismatch')
  if selection.get('gate_exception',{}).get('kind')=='one_off_diagnostic_reference' and selection.get('admission_qualified') is not False: raise ValueError('inconsistent diagnostic exception')
 control={}
 # Historical presentation profile: follow each bound producer mapping to verified evidence.
 for target,display in [('role','roles'),('lock_state','lp_locked'),('pause','pause_status')]:
  rows=[x for x in manifest if x.get('pillar')=='onchain' and x.get('target_id')==target]
  if not rows: continue
  if len(rows)!=1: raise ValueError('ambiguous control mapping: '+target)
  row=rows[0]; e=next((x for x in d['evidence'] if x['id']==row.get('evidence_id')),None)
  if e is None: raise ValueError('control mapping evidence unresolved: '+target)
  pointer=row.get('source_json_pointer')
  if not isinstance(pointer,str) or not pointer.startswith('/'): raise ValueError('invalid control pointer')
  value=load(safe(root,e['path']))
  try:
   for segment in pointer[1:].split('/'):
    segment=segment.replace('~1','/').replace('~0','~')
    value=value[int(segment)] if isinstance(value,list) else value[segment]
  except (KeyError,IndexError,ValueError,TypeError): raise ValueError('unresolved control pointer: '+target)
  control[display]=value
 html=(ROOT/'reader.html').read_text(encoding='utf-8-sig').replace('/*STYLE*/',(ROOT/'style.css').read_text(encoding='utf-8-sig')).replace('/*SCRIPT*/',(ROOT/'app.js').read_text(encoding='utf-8-sig')).replace('/*DATA*/',payload).replace('/*MANIFEST*/',embed(manifest)).replace('/*CONTROLS*/',embed(control)).replace('/*TLDR*/',embed(tldr)).replace('/*SELECTION*/',embed(selection))
 (dest/'index.html').write_text(html,encoding='utf-8'); shutil.copyfile(source,dest/'report.json')
 print('PASS: schema and asset hashes; packaged',source,'->',dest)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('report',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
 try: build(a.report,a.output)
 except Exception as e: print('FAILED:',e,file=sys.stderr);sys.exit(1)
