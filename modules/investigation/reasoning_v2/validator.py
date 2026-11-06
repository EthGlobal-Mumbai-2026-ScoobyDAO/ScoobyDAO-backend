"""Offline reasoning-v2 validation; no API calls, no decisions or score changes."""
import json,pathlib
from jsonschema import Draft202012Validator
from . import contract_validate as cv
ROOT=pathlib.Path(__file__).resolve().parent

def validate(report,side):
 if side.get('profile')!='scooby.reasoning/2':raise ValueError('unsupported profile')
 if any(side.get(k)!=report[k] for k in ('candidate_id','report_id','report_version')):raise ValueError('identity/version mismatch')
 model=side['reasoning'];Draft202012Validator(json.loads((ROOT/'output.schema.json').read_text(encoding='utf8'))).validate(model)
 names=[p['name'] for p in model['pillars']]
 if len(names)!=5 or set(names)!=set(report['pillars']):raise ValueError('expected each pillar once')
 evidence={e['id'] for e in report['evidence']};inputs={};claim_ids=set()
 for p in report['pillars'].values():
  for group in ('measurements','series','claims'):
   for x in p[group]:
    if x['id'] in inputs:raise ValueError('ambiguous input id')
    inputs[x['id']]=x
    if group=='claims':claim_ids.add(x['id'])
 def paragraph(a):
  if not a['text'].strip() or not set(a['evidence_ids'])<=evidence or not set(a['input_ids'])<=set(inputs):raise ValueError('unresolved paragraph')
  if a['input_ids'] and not a['evidence_ids']:raise ValueError('inputs require evidence')
  for id in a['input_ids']:
   item=inputs[id];refs=item.get('evidence_ids',item.get('supporting_evidence_ids',[])+item.get('counterevidence_ids',[]))
   if not set(refs)&set(a['evidence_ids']):raise ValueError('input and evidence not linked')
 for pillar in model['pillars']:
  if not pillar['summary'].strip() or not pillar['analysis']:raise ValueError('pillar analysis missing')
  for a in pillar['analysis']:paragraph(a)
 c=model['conclusion'];rec=c['recommendation']
 if not c['summary'].strip() or not c['analysis'] or not rec['action'].strip() or not rec['rationale']['text'].strip() or not rec['reversal_conditions'] or any(not x.strip() for x in rec['reversal_conditions']):raise ValueError('recommendation or conclusion incomplete')
 if evidence and not rec['rationale']['evidence_ids']:raise ValueError('recommendation evidence missing')
 for a in c['analysis']+[rec['rationale']]+rec['counterevidence']:paragraph(a)
 if not set(c['supporting_claim_ids']+c['counterevidence_claim_ids'])<=claim_ids:raise ValueError('unresolved assessment claims')
 return model

def validate_bundle(root):
 root=pathlib.Path(root);d=json.loads((root/'digest.json').read_text(encoding='utf8'))
 if d.get('algorithm')!='sha256' or d.get('target')!='report.json exact UTF-8 bytes':raise ValueError('unsupported digest')
 report=cv.verify_digest(root,d['sha256']);arts=[a for a in report['artifacts'] if a['kind']=='reasoning' and a['availability']=='available']
 if len(arts)!=1:raise ValueError('expected exactly one reasoning artifact')
 side=json.loads(cv.safe(root,arts[0]['path']).read_text(encoding='utf8'));return report,validate(report,side)
