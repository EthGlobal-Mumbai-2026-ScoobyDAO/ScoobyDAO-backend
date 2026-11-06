"""Hash/identity-bound captured-source producer. No network/model calls."""
import hashlib,json,pathlib
try:from . import adapters
except ImportError:import adapters
PILLARS=('microstructure','onchain','fundamentals','statistical_risk','technical_health')
def load_capture(root,record,candidate):
 root=pathlib.Path(root).resolve();path=record['path']
 if not path or any(c in path for c in ('\\',':','%','?','#')) or any(x in ('','.','..') for x in path.split('/')):raise ValueError('unsafe captured path')
 p=root/path
 if not p.resolve().is_relative_to(root) or not p.is_file() or any(x.is_symlink() for x in [p,*p.parents] if x!=root.parent):raise ValueError('escaping/missing captured file')
 if record['candidate_id']!=candidate:raise ValueError('capture candidate mismatch')
 if hashlib.sha256(p.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('capture hash mismatch')
 return json.loads(p.read_text(encoding='utf-8-sig'))
def run_captured(context,root,records):
 candidate=context['candidate_id'];chain,address=candidate.split(':',1)
 if chain not in ('1','8453') or len(address)!=42 or not address.startswith('0x'):raise ValueError('invalid candidate')
 out={p:{'status':'unavailable','payload':{'reason':'Required source capture not supplied; no zero/default substituted.'}} for p in PILLARS}
 for name,record in records.items():
  raw=load_capture(root,record,candidate)
  if name=='microstructure':
   if raw['pair']['chainId']!=int(chain) or raw['pair']['base'].lower()!=address.lower():raise ValueError('venue identity mismatch')
   out[name]=adapters.replay_market(raw)
  elif name=='onchain':
   if raw['chainId']!=int(chain) or raw['token'].lower()!=address.lower():raise ValueError('contract facts identity mismatch')
   out[name]=adapters.replay_control_score(raw)
  elif name=='fundamentals':
   binding=record.get('attribution')
   if binding and binding.get('candidate_id')!=candidate:raise ValueError('fundamental attribution identity mismatch')
   out[name]=adapters.fundamentals_from_capture(raw,binding)
  elif name=='legacy_metrics':
   if raw['identity']!=candidate:raise ValueError('VAE metric identity mismatch')
   for target,key in [('statistical_risk','risk_assessment'),('technical_health','technical_health')]:
    out[target]={'status':'partial','payload':{'legacy_output':raw[key],'quality_issues':['Exact captured legacy output retained. Input truth and forecast calibration are separate from calculation reproduction.']}}
   out['technical_health']['payload']['technical_series']=raw['technical_series']
  else:raise ValueError('unknown captured source kind')
  for p in out.values():
   if p['status']!='unavailable':p.setdefault('source_record_ids',[])
  targets=[name] if name in PILLARS else ['statistical_risk','technical_health']
  for target in targets:out[target].setdefault('source_record_ids',[]).append(record['id'])
 return out
