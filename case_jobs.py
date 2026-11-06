"""Durable case investigation-to-report bridge. No provider calls beyond decision budget."""
import json
from pathlib import Path
from store import DATA, db, now, digest, dumps, job, event, PILLARS

def run_case(run_id, producer=None):
 import case_engine
 with db() as c:
  run=c.execute('SELECT * FROM investigations WHERE id=?',(run_id,)).fetchone()
  decision=c.execute('SELECT * FROM case_decisions WHERE run_id=?',(run_id,)).fetchone()
  if not run or not decision:raise ValueError('case authorization not found')
  if run['status']=='cancelled':return 'cancelled'
  snap=c.execute('SELECT * FROM case_snapshots WHERE id=?',(decision['snapshot_id'],)).fetchone()
  case=c.execute('SELECT * FROM cases WHERE id=?',(decision['case_id'],)).fetchone()
  if not snap or not case or snap['candidate_id']!=run['candidate_id'] or snap['expires']<=now() or case['current_snapshot']!=snap['id'] or case_engine.policy_digest()!=decision['policy_digest'] or snap['policy_digest']!=decision['policy_digest']:raise ValueError('authorization binding expired or changed')
  if digest(dumps({'record':json.loads(snap['record']),'evidence':json.loads(snap['evidence']),'policy':snap['policy_digest'],'assessment':json.loads(snap['assessment'])}).encode())!=snap['id']:raise ValueError('snapshot integrity failure')
  budget=json.loads(decision['budget'])
  if budget!={'max_source_requests':0,'max_model_calls':0}:raise ValueError('unauthorized budget')
  if decision['action'] not in ('auto_research','human_research'):raise ValueError('unsupported authorization')
  binding={'case':case['id'],'snapshot':snap['id'],'policy':snap['policy_digest'],'action':decision['action'],'budget':budget}
  if decision['action']=='human_research':
   ch=c.execute("SELECT ch.*,a.binding_hash FROM case_challenges ch JOIN case_world_attempts a ON a.challenge_id=ch.id WHERE ch.case_id=? AND ch.snapshot_id=? AND ch.policy_digest=? AND ch.state='consumed' AND a.state='approved'",(case['id'],snap['id'],snap['policy_digest'])).fetchone()
   import case_world
   if not ch or ch['action']!='diagnostic_research' or ch['binding_hash']!=case_world.binding_hash(case,ch):raise ValueError('missing verified World confirmation or binding changed')
   binding['challenge']=ch['id']
  if digest(dumps(binding).encode())!=decision['id']:raise ValueError('decision integrity failure')
  descriptor={'case_id':case['id'],'run_id':run_id,'candidate_id':run['candidate_id'],'mode':json.loads(snap['record'])['mode'],'authorization':{'route':'automatic_policy' if decision['action']=='auto_research' else 'world_confirmed','reference_id':decision['id']}}
  c.execute("UPDATE investigations SET status='running' WHERE id=? AND status='queued'",(run_id,))
 def cancelled():
  with db() as c:
   current=c.execute('SELECT status FROM investigations WHERE id=?',(run_id,)).fetchone();return not current or current['status']=='cancelled'
 if producer is None:
  from modules.investigation import case_research
  producer=case_research.run_case
 from modules.investigation import contract_validate
 parent=DATA/'case-research';parent.mkdir(parents=True,exist_ok=True);out=parent/run_id
 if out.exists():
  if out.is_symlink() or not out.is_dir():raise ValueError('unsafe bundle path')
  doc=json.loads((out/'report.json').read_bytes());sha=digest((out/'report.json').read_bytes());contract_validate.verify_digest(out,sha)
  result={'state':'partial','bundle_path':str(out),'report_id':doc['report_id'],'report_version':doc['report_version'],'report_sha256':sha,'pillar_status':{k:v['status'] for k,v in doc['pillars'].items()}}
 else:result=producer(descriptor,out,max_source_requests=budget['max_source_requests'],cancelled=cancelled)
 if result.get('state') in ('blocked','cancelled'):
  with db() as c:
   c.execute('BEGIN IMMEDIATE');current=c.execute('SELECT status FROM investigations WHERE id=?',(run_id,)).fetchone()
   if current and current['status']!='cancelled':
    c.execute("UPDATE investigations SET status='blocked' WHERE id=?",(run_id,))
    for p in PILLARS:c.execute("UPDATE pillars SET status='unavailable',detail=? WHERE run_id=? AND pillar=?",('No usable source evidence under the authorized budget.',run_id,p))
    event(c,run_id,'blocked','No usable source evidence under the authorized budget; no report produced.')
  return result['state']
 if result.get('state')!='partial' or Path(result.get('bundle_path','')).resolve()!=out.resolve():raise ValueError('unexpected producer result')
 raw=(out/'report.json').read_bytes();sha=digest(raw)
 if sha!=result['report_sha256']:raise ValueError('producer report digest mismatch')
 doc=contract_validate.verify_digest(out,sha);lineage=json.loads((out/'case-lineage.json').read_bytes())
 if (doc['candidate_id'],lineage.get('candidate_id'),lineage.get('case_id'),lineage.get('run_id'),lineage.get('authorization_route'),lineage.get('authorization_reference_id'))!=(run['candidate_id'],run['candidate_id'],case['id'],run_id,descriptor['authorization']['route'],decision['id']):raise ValueError('producer report lineage mismatch')
 if not any(p['status'] in ('partial','complete') and (p['claims'] or p['measurements'] or p['series']) for p in doc['pillars'].values()):raise ValueError('empty report cannot complete research')
 with db() as c:
  c.execute('BEGIN IMMEDIATE');current=c.execute('SELECT status FROM investigations WHERE id=?',(run_id,)).fetchone()
  if not current or current['status']=='cancelled':return 'cancelled'
  old=c.execute('SELECT * FROM reports WHERE id=? AND version=?',(doc['report_id'],doc['report_version'])).fetchone()
  if old and (old['run_id']!=run_id or old['sha256']!=sha):raise ValueError('report identity conflict')
  c.execute('INSERT OR IGNORE INTO reports VALUES(?,?,?,?,?,?)',(doc['report_id'],doc['report_version'],run_id,sha,str(out),now()))
  for name,p in doc['pillars'].items():c.execute('UPDATE pillars SET status=?,detail=? WHERE run_id=? AND pillar=?',(p['status'],p['summary'],run_id,name))
  c.execute("UPDATE investigations SET status='partial' WHERE id=?",(run_id,));event(c,run_id,'report_generated','Evidence-linked draft generated; report review pending.')
  ref=dumps({'id':doc['report_id'],'version':doc['report_version'],'sha256':sha});job(c,'render',ref,'case-render:'+run_id)
 return 'partial report generated'
