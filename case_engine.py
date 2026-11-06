"""Server-owned discovery bridge. No caller-supplied verifier, gate or human authorization."""
import base64, datetime as dt, hashlib, json, os, re, sqlite3, sys, tempfile
from pathlib import Path
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from store import ROOT, PILLARS, db, now, ident, digest, dumps, job, event
DISCOVERY=ROOT/'modules'/'discovery'
if str(DISCOVERY) not in sys.path: sys.path.insert(0,str(DISCOVERY))
import review_queue, scouting_brief
SCHEMA=json.loads((ROOT/'schemas'/'candidate.schema.json').read_text(encoding='utf-8-sig'))
MAX_BYTES=5_000_000
def policy_budget():
 # Server-owned policy; defaults to no paid calls. Existing decisions never inherit changes.
 value=os.getenv('SCOOBY_CASE_MODEL_MAX_CALLS','0').strip()
 if value not in ('0','1'):raise ValueError('SCOOBY_CASE_MODEL_MAX_CALLS must be 0 or 1')
 return {'max_source_requests':0,'max_model_calls':int(value)}

def _policy_sources():
 manifest={p.name:digest(p.read_bytes()) for p in sorted(DISCOVERY.glob('*.py')) if not p.name.startswith('test_')}
 manifest['case_engine.py']=digest(Path(__file__).read_bytes());manifest['candidate.schema.json']=digest((ROOT/'schemas'/'candidate.schema.json').read_bytes())
 # Bind the model stage code and its static prompt/schema to the policy source snapshot.
 for relative in ('case_jobs.py','case_model.py','case_graph.py','modules/investigation/case_research.py','modules/investigation/history.py','modules/investigation/graph_history.py','modules/investigation/model_reasoning.py','modules/investigation/reasoning_v2/output.schema.json','modules/investigation/reasoning_v2/analyst-v2.txt','modules/investigation/reasoning_v2/legacy-math-v1.txt'):
  source=ROOT/relative
  if source.is_file():manifest[relative]=digest(source.read_bytes())
 return manifest
_LOADED_POLICY_SOURCES=_policy_sources()
def policy_digest():
 # A running process must not attest to newly edited source it has not loaded.
 manifest=_policy_sources()
 if manifest!=_LOADED_POLICY_SOURCES: raise RuntimeError('policy source changed; restart the process')
 return digest(dumps({'policy':review_queue.POLICY,'sources':manifest,'threshold':4,'age_seconds':3600,'budget':policy_budget()}).encode())

def collect_evidence(record,root):
 root=Path(root).resolve(); data={};total=0
 for e in record.get('evidence',[]):
  name=e.get('source'); sha=e.get('sha256')
  if not isinstance(name,str) or not re.fullmatch(r'snapshots/[0-9a-f]{64}\.json',name) or sha!=e.get('id') or name!='snapshots/'+str(sha)+'.json': continue
  p=root
  for part in name.split('/'):
   p=p/part
   if p.is_symlink(): raise ValueError('unsafe evidence symlink')
  if not p.is_file() or not p.resolve().is_relative_to(root): continue
  if p.stat().st_size>MAX_BYTES-total: raise ValueError('evidence byte budget exceeded')
  raw=p.read_bytes();total+=len(raw)
  if total>MAX_BYTES: raise ValueError('evidence byte budget exceeded')
  if digest(raw)!=sha: raise ValueError('evidence hash mismatch')
  if b'reddit' in raw.lower() or b'redd.it' in raw.lower(): raise ValueError('Reddit-derived content blocked pending retention lifecycle')
  data[name]=base64.b64encode(raw).decode('ascii')
 return data

def evaluate(record,evidence):
 # Recreate exactly the captured bytes; independent metric verifiers run on them.
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp)
  for name,b64 in evidence.items():
   if not re.fullmatch(r'snapshots/[0-9a-f]{64}\.json',name): raise ValueError('unsafe evidence path')
   raw=base64.b64decode(b64,validate=True)
   if len(raw)>MAX_BYTES or digest(raw)!=Path(name).stem: raise ValueError('captured evidence hash mismatch')
   target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
  brief=scouting_brief.scouting_brief(record,root,'case-assessment',dt.datetime.now(dt.timezone.utc))
  groups=[{**{k:v for k,v in g.items() if k!='vote'},'votes':g['vote']} for g in brief['deterministic_checks']]
  count=brief['coverage']['triggered_groups']
  return {'candidate_id':record['candidate_id'],'identity':record['identity'],'policy':review_queue.POLICY,
          'triggered_count':count,'evaluated_count':brief['coverage']['evaluated_groups'],
          'eligible':brief['routing']['recommendation']=='auto_eligible',
          'priority':'higher' if count>=5 else 'standard' if count>=4 else None,'groups':groups,
          'scouting':{'routing':brief['routing'],'provider_observations':brief['provider_observations'],
                      'scouting_origins':brief['scouting_origins']}}

def verified_gate(assessment,evidence):
 """Count only distinct triggered groups carrying fresh captured source evidence."""
 groups=assessment.get('groups')
 if not isinstance(groups,list): return False,0,None
 expected=set(review_queue.live_pilot.GROUPS); group_ids=[g.get('id') for g in groups if isinstance(g,dict)]
 if len(groups)!=len(expected) or len(set(group_ids))!=len(expected) or set(group_ids)!=expected: return False,0,None
 if any(g.get('status') not in ('triggered','not_triggered','unknown','held') or g.get('votes')!=(1 if g.get('status')=='triggered' else 0) for g in groups): return False,0,None
 triggered=[g for g in groups if isinstance(g,dict) and g.get('status')=='triggered' and g.get('votes')==1]
 ids=[g.get('id') for g in triggered]
 if any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids): return False,0,None
 expiry=[];seen_evidence=set();as_of=dt.datetime.now(dt.timezone.utc).timestamp()
 for group in triggered:
  ev=group.get('evidence')
  if not isinstance(ev,list) or not ev: return False,0,None
  for e in ev:
   try:
    name=e['source'];raw=base64.b64decode(evidence[name],validate=True); stamp=dt.datetime.fromisoformat(e['observed_at'].replace('Z','+00:00'))
    if name in seen_evidence:return False,0,None
    seen_evidence.add(name)
    if stamp.tzinfo is None or digest(raw)!=e['sha256'] or e['id']!=e['sha256'] or name!='snapshots/'+e['sha256']+'.json':return False,0,None
    end=stamp.timestamp()+3600
    if stamp.timestamp()>as_of or end<=as_of:return False,0,None
    expiry.append(end)
   except (KeyError,ValueError,TypeError,OverflowError):return False,0,None
 count=len(triggered)
 return assessment.get('eligible') is True and count>=4 and count==assessment.get('triggered_count'),count,min(expiry) if expiry else None

def ingest_record(record,source_root):
 Draft202012Validator(SCHEMA).validate(record)
 text=dumps(record).lower()
 if 'reddit' in text or 'redd.it' in text: raise ValueError('Reddit-derived content blocked pending retention lifecycle')
 if record.get('mode')!='live' or record['identity']['chain_id'] not in (1,8453): raise ValueError('live Ethereum/Base only')
 cid=record['candidate_id']; identity=record['identity']
 if cid!=str(identity['chain_id'])+':'+identity['address'].lower(): raise ValueError('candidate identity mismatch')
 evidence=collect_evidence(record,source_root);policy=policy_digest();assessment=evaluate(record,evidence);assessment.pop('as_of',None)
 # Assessment is recomputed; ignore eligibility/score supplied by sources.
 valid,count,gate_expiry=verified_gate(assessment,evidence);budget=policy_budget()
 snap=digest(dumps({'record':record,'evidence':evidence,'policy':policy,'assessment':assessment}).encode());case=digest(cid.encode()); t=now();state='auto_queued' if valid else 'awaiting_human' if count>0 or assessment.get('scouting',{}).get('routing',{}).get('recommendation')=='human_review_required' else 'monitoring'
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  old=c.execute('SELECT current_snapshot FROM cases WHERE id=?',(case,)).fetchone()
  c.execute('INSERT OR IGNORE INTO case_snapshots VALUES(?,?,?,?,?,?,?,?)',(snap,cid,dumps(record),dumps(evidence),policy,dumps(assessment),t,min(t+3600,gate_expiry) if gate_expiry else t+3600))
  existing_run=c.execute("SELECT status FROM investigations WHERE candidate_id=? AND status!='reference_only' ORDER BY created DESC LIMIT 1",(cid,)).fetchone()
  if existing_run: state='investigating' if existing_run['status'] in ('queued','running') else 'monitoring'
  c.execute('INSERT INTO cases VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET current_snapshot=excluded.current_snapshot,state=excluded.state,updated=excluded.updated',(case,cid,snap,state,t))
  if old and old['current_snapshot']!=snap:c.execute("UPDATE case_challenges SET state='superseded' WHERE case_id=? AND state='pending'",(case,))
  if valid and not existing_run:
   did=digest(dumps({'case':case,'snapshot':snap,'policy':policy,'action':'auto_research','budget':budget}).encode())
   c.execute('INSERT OR IGNORE INTO case_decisions VALUES(?,?,?,?,?,?,?,?)',(did,case,snap,policy,'auto_research',dumps(budget),None,t))
   job(c,'case_start',did,'case-start:'+did)
  c.execute('INSERT INTO case_events(case_id,kind,detail,created) VALUES(?,?,?,?)',(case,'assessed',state,t))
 return case

def reconcile(limit):
 path=os.getenv('SCOOBY_DISCOVERY_DB');root=os.getenv('SCOOBY_DISCOVERY_ROOT')
 if not path or not root: raise RuntimeError('discovery store not configured')
 # Read-only connection. The discovery workstream owns all collection and its DB.
 uri=Path(path).resolve().as_uri()+'?mode=ro';con=sqlite3.connect(uri,uri=True)
 try:
  scan_key=digest((str(Path(path).resolve())+'|'+str(Path(root).resolve())).encode())
  with db() as c:
   cursor=c.execute('SELECT position FROM case_scan_cursor WHERE name=?',(scan_key,)).fetchone();offset=cursor['position'] if cursor else 0
  rows=con.execute('SELECT record FROM candidates ORDER BY id LIMIT ? OFFSET ?', (limit,offset)).fetchall()
  if not rows and offset:offset=0;rows=con.execute('SELECT record FROM candidates ORDER BY id LIMIT ? OFFSET ?', (limit,0)).fetchall()
 finally: con.close()
 counts={'processed':0,'skipped':0,'offset':offset}
 for (raw,) in rows:
  try:ingest_record(json.loads(raw),root);counts['processed']+=1
  except (ValueError,TypeError,KeyError,OSError,ValidationError):counts['skipped']+=1
 with db() as c:c.execute('INSERT INTO case_scan_cursor VALUES(?,?) ON CONFLICT(name) DO UPDATE SET position=excluded.position',(scan_key,offset+len(rows)))
 return counts

def start_decision(decision_id):
 with db() as c:
  d=c.execute('SELECT * FROM case_decisions WHERE id=?',(decision_id,)).fetchone()
  if not d: raise ValueError('decision not found')
  snap=c.execute('SELECT * FROM case_snapshots WHERE id=?',(d['snapshot_id'],)).fetchone();case=c.execute('SELECT * FROM cases WHERE id=?',(d['case_id'],)).fetchone()
  if d['run_id']: return d['run_id']
  budget=json.loads(d['budget'])
  if budget!=policy_budget() or d['budget']!=dumps(budget) or d['id']!=digest(dumps({'case':d['case_id'],'snapshot':d['snapshot_id'],'policy':d['policy_digest'],'action':d['action'],'budget':budget}).encode()):raise ValueError('decision budget or binding tampered')
  if case['current_snapshot']!=snap['id'] or snap['expires']<=now() or policy_digest()!=snap['policy_digest']: raise ValueError('snapshot or policy stale')
  record=json.loads(snap['record']); evidence=json.loads(snap['evidence'])
  if digest(dumps({'record':record,'evidence':evidence,'policy':snap['policy_digest'],'assessment':json.loads(snap['assessment'])}).encode())!=snap['id']: raise ValueError('snapshot tampered')
 # Re-evaluate trusted verifiers immediately before transaction; no caller-controlled result.
 assessment=evaluate(record,evidence);valid,_,_=verified_gate(assessment,evidence)
 if not valid: raise ValueError('gate not verified')
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  d=c.execute('SELECT * FROM case_decisions WHERE id=?',(decision_id,)).fetchone();case=c.execute('SELECT * FROM cases WHERE id=?',(d['case_id'],)).fetchone();current=c.execute('SELECT * FROM case_snapshots WHERE id=?',(d['snapshot_id'],)).fetchone()
  if d['run_id']:return d['run_id']
  budget=json.loads(d['budget'])
  if budget!=policy_budget() or d['budget']!=dumps(budget) or d['id']!=digest(dumps({'case':d['case_id'],'snapshot':d['snapshot_id'],'policy':d['policy_digest'],'action':d['action'],'budget':budget}).encode()):raise ValueError('decision budget or binding tampered')
  other=c.execute("SELECT id FROM investigations WHERE candidate_id=? AND status!='reference_only' LIMIT 1",(record['candidate_id'],)).fetchone()
  if other: raise ValueError('candidate already has research run; explicit supersession required')
  if case['current_snapshot']!=snap['id'] or current['expires']<=now() or policy_digest()!=snap['policy_digest'] or (current['record'],current['evidence'],current['policy_digest'],current['assessment'])!=(snap['record'],snap['evidence'],snap['policy_digest'],snap['assessment']): raise ValueError('binding changed')
  c.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?)',(record['candidate_id'],dumps(record),now()))
  sel=ident();run=ident();c.execute('INSERT INTO selections VALUES(?,?,?,?,?,?,?)',(sel,record['candidate_id'],'qualified','policy-engine','Four independently verified groups; not human report approval',now(),'case-selection:'+decision_id))
  c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?)',(run,record['candidate_id'],sel,'queued',now(),'case-run:'+decision_id))
  for p in PILLARS:c.execute('INSERT INTO pillars VALUES(?,?,?,?)',(run,p,'queued','Awaiting producer'))
  c.execute('UPDATE case_decisions SET run_id=? WHERE id=? AND run_id IS NULL',(run,decision_id));c.execute("UPDATE cases SET state='investigating',updated=? WHERE id=?",(now(),case['id']))
  c.execute('INSERT INTO case_events(case_id,kind,detail,created) VALUES(?,?,?,?)',(case['id'],'research_started',run,now()))
  event(c,run,'created','Policy-qualified auto start; report sign-off remains separate');job(c,'investigate',run,'investigate:'+run)
  return run
