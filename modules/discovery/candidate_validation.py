"""Validate one candidate against an externally supplied frozen schema and semantic rules."""
import argparse,datetime as dt,hashlib,json,re,sys
from pathlib import Path
from jsonschema import Draft202012Validator

def validate(candidate,schema,selected=False,evidence_root=None):
 Draft202012Validator.check_schema(schema);Draft202012Validator(schema).validate(candidate)
 i=candidate['identity'];expected=f"{i['chain_id']}:{i['address'].lower()}"
 if candidate['candidate_id']!=expected:raise ValueError('candidate identity mismatch')
 screen=candidate['screening']
 if screen['status'] in ('not_scored','insufficient_data') and any(screen[k] is not None for k in ('score','score_version','threshold_version')):raise ValueError('unavailable score must be null')
 sel=candidate['selection']
 if selected:
  if candidate['state']!='selected' or sel['status']!='selected' or not isinstance(sel['selected_by'],str) or not sel['selected_by'].strip() or not isinstance(sel['reason'],str) or not sel['reason'].strip():raise ValueError('explicit selection and nonblank actor and reason required')
  try:when=dt.datetime.fromisoformat(sel['selected_at'].replace('Z','+00:00'))
  except (TypeError,AttributeError,ValueError):raise ValueError('selection time invalid')
  if when.tzinfo is None or when.utcoffset() is None:raise ValueError('selection time requires timezone')
 ids=[x['id'] for x in candidate['evidence']]
 if len(ids)!=len(set(ids)) or any(x not in ids for t in candidate['triggers'] for x in t['evidence_ids']):raise ValueError('evidence IDs must be unique and references resolve')
 if evidence_root is not None:
  root=Path(evidence_root).resolve()
  for e in candidate['evidence']:
   path=e['source'];digest=e['sha256']
   if not isinstance(path,str) or not path or any(x in path for x in ('\\',':','%','?','#')) or path.startswith('/') or any(x in ('','.','..') for x in path.split('/')):raise ValueError('unsafe evidence path')
   parts=path.split('/');p=root
   for part in parts:
    p=p/part
    if p.is_symlink():raise ValueError('symlink evidence path')
   if not p.resolve().is_relative_to(root) or not p.is_file() or not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest) or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('missing evidence or hash mismatch')
 return True

def main():
 p=argparse.ArgumentParser();p.add_argument('--candidate',required=True,type=Path);p.add_argument('--schema',required=True,type=Path);p.add_argument('--selected',action='store_true');p.add_argument('--evidence-root',type=Path);a=p.parse_args()
 validate(json.loads(a.candidate.read_text(encoding='utf-8-sig')),json.loads(a.schema.read_text(encoding='utf-8-sig')),a.selected,a.evidence_root);print('PASS candidate schema and requested semantic checks')
if __name__=='__main__':
 try:main()
 except Exception as e:print(str(e),file=sys.stderr);raise SystemExit(1)
