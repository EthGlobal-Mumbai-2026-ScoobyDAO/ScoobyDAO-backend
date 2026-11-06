import hashlib, json, math
from pathlib import Path
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parent

def digest(data): return hashlib.sha256(data).hexdigest()

def safe(root,path):
 if not isinstance(path,str) or not path or '\\' in path or ':' in path or '%' in path or '?' in path or '#' in path or path.startswith('/') or any(x in ('','.','..') for x in path.split('/')): raise ValueError('unsafe path')
 p=root.joinpath(*path.split('/')); resolved=p.resolve()
 current=root
 for part in path.split('/'):
  current=current/part
  if current.is_symlink(): raise ValueError('symlinks forbidden')
 if not resolved.is_relative_to(root.resolve()) or not p.is_file(): raise ValueError('missing or escaping path')
 return p

def validate(root, report):
 def finite(x):
  if isinstance(x,float) and not math.isfinite(x): raise ValueError('non-finite number')
  if isinstance(x,dict):
   for v in x.values(): finite(v)
  elif isinstance(x,list):
   for v in x: finite(v)
 finite(report)
 schema=json.loads((ROOT.parent.parent/'schemas'/'report.schema.json').read_text(encoding='utf8')); Draft202012Validator.check_schema(schema); Draft202012Validator(schema).validate(report)
 i=report['identity']; 
 if report['candidate_id']!=str(i['chain_id'])+':'+i['address'].lower(): raise ValueError('candidate identity mismatch')
 evidence={e['id']:e for e in report['evidence']}; 
 if len(evidence)!=len(report['evidence']): raise ValueError('duplicate evidence')
 for e in evidence.values():
  if digest(safe(root,e['path']).read_bytes())!=e['sha256']: raise ValueError('evidence hash mismatch')
 claim_ids=[]
 for p in report['pillars'].values(): claim_ids += [c['id'] for c in p['claims']]
 
 if len(claim_ids)!=len(set(claim_ids)): raise ValueError('duplicate claims')
 if not set(report['assessment']['supporting_claim_ids']+report['assessment']['counterevidence_claim_ids'])<=set(claim_ids): raise ValueError('unresolved assessment claim')
 for p in report['pillars'].values():
  if p['raw_payload_path'] is not None:
   path=p['raw_payload_path']; safe(root,path)
   matches=[a for a in report['artifacts'] if a['availability']=='available' and a['path']==path]
   if len(matches)!=1: raise ValueError('raw payload requires exactly one available artifact record')
  for x in p['evidence_ids']:
   if x not in evidence: raise ValueError('unresolved evidence')
  for m in p['measurements']+p['series']:
   if not set(m['evidence_ids'])<=set(evidence): raise ValueError('unresolved measurement evidence')
   if m['quality']=='unknown' and not m['unknown_reason']: raise ValueError('unknown requires reason')
  for c in p['claims']:
   if not set(c['supporting_evidence_ids']+c['counterevidence_ids'])<=set(evidence) or not set(c['contradiction_claim_ids'])<=set(claim_ids): raise ValueError('unresolved claim links')
 for a in report['artifacts']:
  if a['report_id']!=report['report_id'] or a['report_version']!=report['report_version']: raise ValueError('artifact version mismatch')
  if a['availability']=='available':
   if digest(safe(root,a['path']).read_bytes())!=a['sha256']: raise ValueError('artifact hash mismatch')
  elif a['path'] is not None or a['sha256'] is not None: raise ValueError('unavailable artifact has path/hash')
 if report['review']['status']=='approved_unverified':
  if not all(report['review'][k] for k in ('reviewer','reviewed_at','reviewed_version','content_sha256')) or report['review']['reviewed_version']!=report['report_version'] or report['review']['authentication']!='unverified': raise ValueError('unverified approval fields required')

def verify_digest(root, expected):
 root=Path(root); content=(root/'report.json').read_bytes()
 if digest(content)!=expected: raise ValueError('report content digest mismatch')
 report=json.loads(content); validate(root,report)
 return report
