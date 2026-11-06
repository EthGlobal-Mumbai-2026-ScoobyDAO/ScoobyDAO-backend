"""Case-scoped World device authorization; unrelated to report sign-off.

Device codes are process-local secrets. Losing them fails closed. A device grant
proves the holder's World authentication; the application must display the bound
case and requested action before initiating the grant.
"""
import json, threading
from fastapi import HTTPException
from store import db, now, ident, digest, dumps, job, event, PILLARS
from publication.world import Tokens, Pending, SlowDown, Denied, Expired, Error, WorldError, TokenInvalid
_codes={}; _lock=threading.Lock()

def fail(status,message): raise HTTPException(status,message)
def public(c,a):
 ch=c.execute('SELECT * FROM case_challenges WHERE id=?',(a['challenge_id'],)).fetchone();case=c.execute('SELECT * FROM cases WHERE id=?',(ch['case_id'],)).fetchone()
 return {'attempt_id':a['id'],'challenge_id':ch['id'],'case_id':ch['case_id'],'candidate_id':case['candidate_id'],'snapshot_digest':ch['snapshot_id'],'policy_digest':ch['policy_digest'],'action':ch['action'],'nonce':ch['nonce'],'state':a['state'],'expires_at':a['expires'],'user_code':a['user_code'],'verification_uri':a['verification_uri'],'verification_uri_complete':a['verification_uri_complete'],'interval_seconds':a['interval'],'run_id':(c.execute("SELECT run_id FROM case_decisions WHERE case_id=? AND snapshot_id=? AND action='human_research'",(ch['case_id'],ch['snapshot_id'])).fetchone() or {'run_id':None})['run_id']}

def binding_hash(case,ch):
 return digest(dumps({'case_id':case['id'],'candidate_id':case['candidate_id'],'snapshot':ch['snapshot_id'],'policy':ch['policy_digest'],'action':ch['action'],'nonce':ch['nonce'],'expires':ch['expires']}).encode())

def valid_binding(c,ch):
 import case_engine
 case=c.execute('SELECT * FROM cases WHERE id=?',(ch['case_id'],)).fetchone();snap=c.execute('SELECT * FROM case_snapshots WHERE id=?',(ch['snapshot_id'],)).fetchone()
 if not case or not snap or ch['state']!='pending' or ch['expires']<=now() or snap['expires']<=now() or case['current_snapshot']!=ch['snapshot_id'] or ch['policy_digest']!=snap['policy_digest'] or case_engine.policy_digest()!=ch['policy_digest'] or ch['action']!='diagnostic_research':fail(409,'Case authorization expired or superseded')
 expected=digest(dumps({'record':json.loads(snap['record']),'evidence':json.loads(snap['evidence']),'policy':snap['policy_digest'],'assessment':json.loads(snap['assessment'])}).encode())
 if expected!=snap['id']:fail(409,'Case snapshot integrity failure')
 return case,snap

def start(challenge_id,world):
 if world is None:fail(503,'World ID case confirmation is not configured')
 with db() as c:
  ch=c.execute('SELECT * FROM case_challenges WHERE id=?',(challenge_id,)).fetchone()
  if not ch:fail(404,'Challenge not found')
  old=c.execute('SELECT * FROM case_world_attempts WHERE challenge_id=?',(challenge_id,)).fetchone()
  if old:return public(c,old)
  valid_binding(c,ch)
 started=now()
 try: dev=world.start_device(world.config.accepted_acr)
 except WorldError:fail(503,'World ID confirmation is unavailable')
 with db() as c:
  c.execute('BEGIN IMMEDIATE');ch=c.execute('SELECT * FROM case_challenges WHERE id=?',(challenge_id,)).fetchone();case,_=valid_binding(c,ch)
  old=c.execute('SELECT * FROM case_world_attempts WHERE challenge_id=?',(challenge_id,)).fetchone()
  if old:return public(c,old)
  aid=ident();expiration=min(ch['expires'],started+dev.expires_in)
  c.execute('INSERT INTO case_world_attempts(id,challenge_id,state,started,expires,interval,next_poll,user_code,verification_uri,verification_uri_complete,accepted_acr,binding_hash,subject_hash,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(aid,challenge_id,'pending',started,expiration,dev.interval,started+dev.interval,dev.user_code,dev.verification_uri,dev.verification_uri_complete,json.dumps(list(world.config.accepted_acr)),binding_hash(case,ch),None,now()))
  with _lock:_codes[aid]=dev.device_code
  return public(c,c.execute('SELECT * FROM case_world_attempts WHERE id=?',(aid,)).fetchone())

def poll(attempt_id,world):
 with db() as c:
  c.execute('BEGIN IMMEDIATE');a=c.execute('SELECT * FROM case_world_attempts WHERE id=?',(attempt_id,)).fetchone()
  if not a:fail(404,'Attempt not found')
  if a['state']!='pending':return public(c,a)
  if a['expires']<=now():c.execute("UPDATE case_world_attempts SET state='expired' WHERE id=?",(attempt_id,));return public(c,c.execute('SELECT * FROM case_world_attempts WHERE id=?',(attempt_id,)).fetchone())
  with _lock:code=_codes.get(attempt_id)
  if not code:c.execute("UPDATE case_world_attempts SET state='expired' WHERE id=?",(attempt_id,));return public(c,c.execute('SELECT * FROM case_world_attempts WHERE id=?',(attempt_id,)).fetchone())
  if not world or a['next_poll']>now():return public(c,a)
  c.execute('UPDATE case_world_attempts SET next_poll=? WHERE id=?',(now()+a['interval'],attempt_id))
 try: result=world.poll(code)
 except WorldError:result=Error('unavailable',terminal=False)
 identity=None
 if isinstance(result,Tokens):
  try:identity=world.validate_id_token(result.id_token,started_at=a['started'],accepted_acr=tuple(json.loads(a['accepted_acr'])))
  except (WorldError,TokenInvalid):result=Error('token_rejected',terminal=True)
 with db() as c:
  c.execute('BEGIN IMMEDIATE');a=c.execute('SELECT * FROM case_world_attempts WHERE id=?',(attempt_id,)).fetchone()
  if a['state']!='pending':return public(c,a)
  if a['expires']<=now():c.execute("UPDATE case_world_attempts SET state='expired' WHERE id=?",(attempt_id,))
  elif identity:
   ch=c.execute('SELECT * FROM case_challenges WHERE id=?',(a['challenge_id'],)).fetchone()
   try:
    case,snap=valid_binding(c,ch)
    if a['binding_hash']!=binding_hash(case,ch):fail(409,'Case authorization binding changed')
   except HTTPException:c.execute("UPDATE case_world_attempts SET state='superseded' WHERE id=?",(attempt_id,))
   else:
    existing=c.execute("SELECT id FROM investigations WHERE candidate_id=? AND status!='reference_only' LIMIT 1",(case['candidate_id'],)).fetchone()
    if existing:c.execute("UPDATE case_world_attempts SET state='superseded' WHERE id=?",(attempt_id,))
    else:
     candidate=json.loads(snap['record']);selection=ident();run=ident();budget={'max_source_requests':0,'max_model_calls':0};decision=digest(dumps({'case':case['id'],'snapshot':snap['id'],'policy':snap['policy_digest'],'action':'human_research','budget':budget,'challenge':ch['id']}).encode())
     c.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?)',(case['candidate_id'],dumps(candidate),now()))
     c.execute('INSERT INTO selections VALUES(?,?,?,?,?,?,?)',(selection,case['candidate_id'],'diagnostic_exception','world-id','Case-scoped World ID confirmed; final report approval separate',now(),'case-human:'+ch['id']))
     c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?)',(run,case['candidate_id'],selection,'queued',now(),'case-human-run:'+ch['id']))
     for p in PILLARS:c.execute('INSERT INTO pillars VALUES(?,?,?,?)',(run,p,'queued','Awaiting producer'))
     c.execute('INSERT INTO case_decisions VALUES(?,?,?,?,?,?,?,?)',(decision,case['id'],snap['id'],snap['policy_digest'],'human_research',dumps(budget),run,now()))
     c.execute("UPDATE case_challenges SET state='consumed' WHERE id=? AND state='pending'",(ch['id'],));c.execute("UPDATE case_world_attempts SET state='approved',subject_hash=? WHERE id=?",(digest((identity.iss+'|'+identity.sub).encode()),attempt_id));c.execute("UPDATE cases SET state='investigating',updated=? WHERE id=?",(now(),case['id']))
     event(c,run,'created','Case-scoped World ID authentication; pending report approval');job(c,'investigate',run,'investigate:'+run)
  elif isinstance(result,Denied):c.execute("UPDATE case_world_attempts SET state='denied' WHERE id=?",(attempt_id,))
  elif isinstance(result,Expired):c.execute("UPDATE case_world_attempts SET state='expired' WHERE id=?",(attempt_id,))
  elif isinstance(result,Error) and result.terminal:c.execute("UPDATE case_world_attempts SET state='failed' WHERE id=?",(attempt_id,))
  elif isinstance(result,SlowDown):c.execute('UPDATE case_world_attempts SET interval=interval+5,next_poll=? WHERE id=?',(now()+a['interval']+5,attempt_id))
  current=c.execute('SELECT * FROM case_world_attempts WHERE id=?',(attempt_id,)).fetchone()
  if current['state']!='pending':
   with _lock:_codes.pop(attempt_id,None)
  return public(c,current)


def cancel(attempt_id):
 with db() as c:
  c.execute('BEGIN IMMEDIATE');a=c.execute('SELECT * FROM case_world_attempts WHERE id=?',(attempt_id,)).fetchone()
  if not a:fail(404,'Attempt not found')
  if a['state']=='pending':
   c.execute("UPDATE case_world_attempts SET state='cancelled' WHERE id=?",(attempt_id,));c.execute("UPDATE case_challenges SET state='cancelled' WHERE id=? AND state='pending'",(a['challenge_id'],))
   with _lock:_codes.pop(attempt_id,None)
  return public(c,c.execute('SELECT * FROM case_world_attempts WHERE id=?',(attempt_id,)).fetchone())
