"""Durable one-attempt Terra stage ledger. No provider call is made by this module."""
import json
from store import db,now,digest,dumps,event
MODEL='gpt-6.1-terra'
OUTPUT_CAP=4096
CONTEXT_CAP=120000
PILLARS={'microstructure','onchain','fundamentals','statistical_risk','technical_health'}
class ModelStageBlocked(RuntimeError):pass

def safe_usage(value):
 if not isinstance(value,dict):return None
 result={}
 for name in ('prompt_tokens','completion_tokens','total_tokens'):
  v=value.get(name)
  if isinstance(v,int) and not isinstance(v,bool) and 0<=v<=1000000:result[name]=v
 return result or None

def fingerprint(run_id,decision_id,snapshot_id,data):
 allowed=('input_sha256','prompt_sha256','schema_sha256','model','max_output_tokens','max_context_chars')
 if any(k not in data for k in allowed):raise ModelStageBlocked('incomplete model stage identity')
 if data['model']!=MODEL or data['max_output_tokens']!=OUTPUT_CAP or data['max_context_chars']!=CONTEXT_CAP:raise ModelStageBlocked('model limits do not match policy')
 for k in ('input_sha256','prompt_sha256','schema_sha256'):
  if not isinstance(data[k],str) or len(data[k])!=64 or any(x not in '0123456789abcdef' for x in data[k]):raise ModelStageBlocked('invalid model stage hash')
 return digest(dumps({'run_id':run_id,'decision_id':decision_id,'snapshot_id':snapshot_id,**{k:data[k] for k in allowed}}).encode())

class Ledger:
 def __init__(self,run_id,decision_id,snapshot_id):self.run_id=run_id;self.decision_id=decision_id;self.snapshot_id=snapshot_id
 def checkpoint(self):
  with db() as c:
   row=c.execute("SELECT * FROM case_model_stages WHERE run_id=? AND stage='reasoning'",(self.run_id,)).fetchone()
   if not row:return None
   if row['decision_id']!=self.decision_id or row['state']!='completed' or not row['checkpoint']:raise ModelStageBlocked('prior model attempt consumed or ambiguous')
   return json.loads(row['checkpoint'])
 def __call__(self,data):
  if not isinstance(data,dict):raise ModelStageBlocked('invalid stage event')
  stage=data.get('stage');state=data.get('state')
  if stage not in ('sources','source','report','reasoning','pillar','conclusion') or state not in ('started','completed','failed','cancelled','unavailable','resumed','analyzed','validated_shared_output','proposed','captured_replay','captured','skipped_budget','skipped','blocked','validated'):raise ModelStageBlocked('invalid stage event')
  detail={'stage':stage,'state':state}
  if stage=='pillar':
   if data.get('name') not in PILLARS:raise ModelStageBlocked('invalid pillar')
   detail['pillar']=data['name'];detail['shared_request']=True
  if stage=='conclusion':detail['shared_request']=True
  if stage=='source':
   if data.get('name') not in ('market','security','source','pools','daily'):raise ModelStageBlocked('invalid source stage')
   detail['source']=data['name']
  if stage=='sources' and data.get('mode') in ('captured_replay','bounded_fetch'):detail['mode']=data['mode']
  for name in ('attempts','captured'):
   if isinstance(data.get(name),int) and not isinstance(data[name],bool) and 0<=data[name]<=5:detail[name]=data[name]
  if state in ('failed','unavailable','cancelled','blocked','skipped'):
   reason=data.get('reason')
   if isinstance(reason,str) and reason in ('context_or_evidence_invalid','missing_openai_key','provider_or_validation_failure','client_retries_not_disabled','refused','incomplete_output','invalid_or_unlinked_output','provider_failure','model_identifier_mismatch','cancelled','no_identity_bound_source_evidence','sources_contain_no_usable_pillar_observation','model_budget_zero'):detail['reason']=reason
  with db() as c:
   c.execute('BEGIN IMMEDIATE');run=c.execute('SELECT status FROM investigations WHERE id=?',(self.run_id,)).fetchone();decision=c.execute('SELECT * FROM case_decisions WHERE id=? AND run_id=?',(self.decision_id,self.run_id)).fetchone()
   if not run or not decision:raise ModelStageBlocked('run authorization missing')
   if run['status']=='cancelled':
    current=c.execute("SELECT * FROM case_model_stages WHERE run_id=? AND stage='reasoning'",(self.run_id,)).fetchone()
    if stage=='reasoning' and state in ('completed','failed','cancelled') and current and current['state']=='reserved':
     usage=safe_usage(data.get('usage'));c.execute("UPDATE case_model_stages SET state='cancelled',usage=?,finished=? WHERE run_id=? AND stage='reasoning' AND state='reserved'",(dumps(usage) if usage else None,now(),self.run_id));event(c,self.run_id,'model_stage_cancelled',dumps({'stage':'reasoning','state':'cancelled','usage':usage}));return
    raise ModelStageBlocked('run cancelled')
   case=c.execute('SELECT current_snapshot FROM cases WHERE id=?',(decision['case_id'],)).fetchone();snap=c.execute('SELECT expires,policy_digest FROM case_snapshots WHERE id=?',(self.snapshot_id,)).fetchone()
   import case_engine
   if not case or not snap or decision['snapshot_id']!=self.snapshot_id or case['current_snapshot']!=self.snapshot_id or snap['expires']<=now() or snap['policy_digest']!=decision['policy_digest'] or case_engine.policy_digest()!=decision['policy_digest']:raise ModelStageBlocked('case policy or evidence binding expired')
   budget=json.loads(decision['budget'])
   if budget.get('max_model_calls') not in (0,1) or budget.get('max_source_requests')!=0:raise ModelStageBlocked('model budget is unavailable')
   if stage in ('reasoning','pillar','conclusion') and budget['max_model_calls']!=1 and not (stage=='reasoning' and state=='skipped' and data.get('reason')=='model_budget_zero'):raise ModelStageBlocked('model budget is unavailable')
   current=c.execute("SELECT * FROM case_model_stages WHERE run_id=? AND stage='reasoning'",(self.run_id,)).fetchone()
   if stage=='reasoning' and state=='started':
    fp=fingerprint(self.run_id,self.decision_id,self.snapshot_id,data)
    if current:raise ModelStageBlocked('model attempt already reserved')
    c.execute('INSERT INTO case_model_stages VALUES(?,?,?,?,?,?,?,?,?)',(self.run_id,'reasoning',self.decision_id,fp,'reserved',None,None,now(),None));detail.update(model=MODEL,scope='shared_five_pillars_and_conclusion',max_output_tokens=OUTPUT_CAP,max_context_chars=CONTEXT_CAP,budget_calls=1,attempts_used=1)
   elif stage=='reasoning' and state=='completed':
    if not current or current['state']!='reserved':raise ModelStageBlocked('model attempt not reserved')
    checkpoint=data.get('checkpoint');encoded=dumps(checkpoint)
    if not isinstance(checkpoint,dict) or len(encoded)>500000 or fingerprint(self.run_id,self.decision_id,self.snapshot_id,data)!=current['request_digest'] or checkpoint.get('profile')!='scooby.reasoning-checkpoint/1' or not isinstance(checkpoint.get('payload'),dict) or checkpoint.get('model')!=MODEL or any(checkpoint.get(k)!=data.get(k) for k in ('input_sha256','prompt_sha256','schema_sha256')):raise ModelStageBlocked('model checkpoint binding mismatch')
    usage=safe_usage(data.get('usage'));c.execute("UPDATE case_model_stages SET state='completed',checkpoint=?,usage=?,finished=? WHERE run_id=? AND stage='reasoning' AND state='reserved'",(encoded,dumps(usage) if usage else None,now(),self.run_id));detail['usage']=usage
   elif stage=='reasoning' and state in ('failed','cancelled') and current and current['state']=='reserved':
    usage=safe_usage(data.get('usage'));c.execute('UPDATE case_model_stages SET state=?,usage=?,finished=? WHERE run_id=? AND stage=\'reasoning\' AND state=\'reserved\'',('failed' if state=='failed' else 'cancelled',dumps(usage) if usage else None,now(),self.run_id));detail['usage']=usage
   elif stage in ('pillar','conclusion') and (not current or current['state']!='completed'):raise ModelStageBlocked('model stage not completed')
   event(c,self.run_id,('research_stage_' if stage in ('sources','source','report') else 'model_stage_')+state,dumps(detail))
