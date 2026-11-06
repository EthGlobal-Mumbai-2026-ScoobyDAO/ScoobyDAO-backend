"""Server-only, separately authorized immutable Graph source binding.

No HTTP route or production admin adapter is provided. World/admin session integration
must supply the authorizer; callers cannot pass a browser boolean as proof.
"""
import hashlib,json,math,os,re,tempfile
from pathlib import Path
from store import DATA,db,now,digest,dumps
from modules.investigation import graph_history
HEX=re.compile(r'^[0-9a-f]{64}$')

def _selection(selection,candidate,manifest,evidence,manifest_hash):
 required={'profile','candidate_id','source_type','subgraph_id','window','selection_reason','discovery_status','evidence'}
 if not isinstance(selection,dict) or set(selection)!=required or selection['profile']!='scooby.graph-source-selection/1' or selection['candidate_id']!=candidate or selection['source_type']!='graph_token_day' or selection['subgraph_id']!=manifest['subgraph_id'] or selection['window']!={'start_inclusive_utc':manifest['start_inclusive_utc'],'end_exclusive_utc':manifest['end_exclusive_utc']}:raise ValueError('source selection identity or window mismatch')
 if not isinstance(selection['selection_reason'],str) or not 1<=len(selection['selection_reason'])<=1000 or selection['discovery_status'] not in ('performed','not_provided'):raise ValueError('source selection requires explicit reason and discovery status')
 if not isinstance(evidence,dict) or not evidence or len(evidence)>20:raise ValueError('source selection evidence required')
 listed=selection['evidence']
 if not isinstance(listed,list) or len(listed)!=len(evidence):raise ValueError('source selection evidence list mismatch')
 total=0
 for item in listed:
  if not isinstance(item,dict) or set(item)!={'id','sha256'} or not isinstance(item['id'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',item['id']) or not HEX.fullmatch(str(item['sha256'])):raise ValueError('invalid source evidence reference')
  raw=evidence.get(item['id'])
  if not isinstance(raw,bytes) or len(raw)>1_000_000 or digest(raw)!=item['sha256']:raise ValueError('source selection evidence hash mismatch')
  graph_history._check_credentials(raw)
  try:source_doc=json.loads(raw)
  except (ValueError,TypeError,RecursionError):raise ValueError('source selection evidence must be JSON') from None
  def no_secrets(value):
   if isinstance(value,dict):
    for key,child in value.items():
     name=str(key).lower().replace('-','_')
     if name in ('api_key','apikey','authorization','access_token','password','secret','credential','credentials') or name.endswith('_api_key'):raise ValueError('credential-bearing source selection evidence rejected')
     no_secrets(child)
   elif isinstance(value,list):
    for child in value:no_secrets(child)
  try:no_secrets(source_doc)
  except RecursionError:raise ValueError('source selection nesting exceeds bound') from None
  if b'reddit' in raw.lower() or b'redd.it' in raw.lower():raise ValueError('social retention lifecycle unavailable')
  total+=len(raw)
 if total>5_000_000 or len({x['id'] for x in listed})!=len(listed):raise ValueError('source selection evidence exceeds bounds')
 if not any(x['sha256']==manifest_hash for x in listed):raise ValueError('source selection must bind the capture manifest')
 if selection['discovery_status']=='performed' and not any(x['sha256']!=manifest_hash for x in listed):raise ValueError('claimed discovery needs separate bound evidence')
 if len(dumps(selection))>16000:raise ValueError('source selection metadata exceeds bound')
 encoded_selection=dumps(selection).encode();graph_history._check_credentials(encoded_selection)
 if b'reddit' in encoded_selection.lower() or b'redd.it' in encoded_selection.lower():raise ValueError('social retention lifecycle unavailable')
 return selection

def install(decision_id,capture_dir,model_dir,selection,selection_evidence,*,historical_horizon_days=None,technical_sha256=None,authorizer=None):
 """Validate, privately snapshot and bind evidence to an existing decision.

 authorizer is a server-owned adapter, never a request-supplied flag. It must return
 an admin receipt bound to the exact proposed digest. Default is unavailable.
 """
 if not callable(authorizer):raise PermissionError('admin source authorization adapter unavailable')
 import case_engine
 with db() as c:
  d=c.execute('SELECT * FROM case_decisions WHERE id=?',(decision_id,)).fetchone()
  if not d or not d['run_id']:raise ValueError('authorized case decision with run required')
  run=c.execute('SELECT status FROM investigations WHERE id=?',(d['run_id'],)).fetchone()
  if not run or run['status'] not in ('queued','blocked','failed'):raise ValueError('case run cannot accept a source binding')
  case=c.execute('SELECT * FROM cases WHERE id=?',(d['case_id'],)).fetchone();snap=c.execute('SELECT * FROM case_snapshots WHERE id=?',(d['snapshot_id'],)).fetchone()
  if not case or not snap or case['candidate_id']!=snap['candidate_id'] or case['current_snapshot']!=snap['id'] or snap['expires']<=now() or snap['policy_digest']!=d['policy_digest'] or case_engine.policy_digest()!=d['policy_digest']:raise ValueError('case binding expired or changed')
  candidate=case['candidate_id']
 capture=graph_history.verify_capture(Path(capture_dir),candidate);_selection(selection,candidate,capture['manifest'],selection_evidence,digest(capture['manifest_raw']))
 model=None
 if model_dir is not None:
  if type(historical_horizon_days) is not int or historical_horizon_days<1:raise ValueError('explicit historical model horizon required')
  model=graph_history.verify_model(Path(model_dir),capture,technical_sha256)
  if model['manifest']['days']!=historical_horizon_days:raise ValueError('historical horizon does not match saved run')
 elif historical_horizon_days is not None or technical_sha256 is not None:raise ValueError('model and horizon must be supplied together')
 files={'capture/manifest.json':capture['manifest_raw'],'capture/token_daily.json':capture['normalized_raw']}
 files.update({'capture/'+name:raw for name,raw,_ in capture['pages']})
 if model:
  files.update({'model/run-manifest.json':model['manifest_raw'],'model/risk-metrics.json':model['risk_raw'],'model/output/crypto_returns.csv':model['returns_raw'],'model/output/vae/VAE_TOKEN.csv':model['recon_raw']})
  if technical_sha256:files.update({'model/technical-metrics.json':model['technical_raw'],'model/technical-manifest.json':model['technical_manifest_raw']})
 files.update({'selection/'+name+'.json':raw for name,raw in selection_evidence.items()})
 inventory={k:digest(v) for k,v in sorted(files.items())};descriptor={'profile':'scooby.case-graph-binding/1','decision_id':decision_id,'case_id':d['case_id'],'candidate_id':candidate,'snapshot_digest':d['snapshot_id'],'policy_digest':d['policy_digest'],'selection':selection,'capture_status':{'status':capture['status'],'rows':len(capture['rows']),'missing_days':len(capture['missing']),'fetched_at_utc':capture['manifest']['fetched_at_utc'],'limitation':'Token-level Graph coverage for this deployment and window; not selected-pool or market-wide history.'},'historical_horizon_days':historical_horizon_days,'technical_sha256':technical_sha256,'files':inventory}
 binding_id=digest(dumps(descriptor).encode());receipt=authorizer(binding_id,descriptor)
 if not isinstance(receipt,dict) or set(receipt)!={'binding_id','role','issuer','subject_hash','verified_at','expires_at'} or receipt['binding_id']!=binding_id or receipt['role']!='admin' or not isinstance(receipt['issuer'],str) or not receipt['issuer'] or not HEX.fullmatch(str(receipt['subject_hash'])) or type(receipt['verified_at']) not in (int,float) or type(receipt['expires_at']) not in (int,float) or not math.isfinite(receipt['verified_at']) or not math.isfinite(receipt['expires_at']) or not 0<=receipt['verified_at']<=now()<receipt['expires_at'] or receipt['expires_at']-receipt['verified_at']>900:raise PermissionError('valid admin authorization receipt required')
 parent=DATA/'graph-bindings';parent.mkdir(parents=True,exist_ok=True);target=parent/binding_id
 if not target.exists():
  with tempfile.TemporaryDirectory(prefix='.graph-',dir=parent) as tmp:
   staged=Path(tmp)/'binding';staged.mkdir()
   for name,raw in files.items():
    path=staged.joinpath(*name.split('/'));path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
   try:os.rename(staged,target)
   except OSError:
    if not target.is_dir():raise
 with db() as c:
  c.execute('BEGIN IMMEDIATE');current=c.execute('SELECT * FROM case_decisions WHERE id=?',(decision_id,)).fetchone()
  latest_run=c.execute('SELECT status FROM investigations WHERE id=?',(d['run_id'],)).fetchone();latest_case=c.execute('SELECT current_snapshot FROM cases WHERE id=?',(d['case_id'],)).fetchone();latest_snapshot=c.execute('SELECT expires FROM case_snapshots WHERE id=?',(d['snapshot_id'],)).fetchone()
  if not current or not latest_run or latest_run['status'] not in ('queued','blocked','failed') or not latest_case or not latest_snapshot or (current['case_id'],current['snapshot_id'],current['policy_digest'])!=(d['case_id'],d['snapshot_id'],d['policy_digest']) or latest_case['current_snapshot']!=d['snapshot_id'] or latest_snapshot['expires']<=now() or case_engine.policy_digest()!=d['policy_digest']:raise ValueError('decision changed during binding')
  old=c.execute('SELECT * FROM case_graph_bindings WHERE decision_id=?',(decision_id,)).fetchone()
  if old and old['binding_id']!=binding_id:raise ValueError('decision already has a different immutable Graph binding')
  if old:c.execute('UPDATE case_graph_bindings SET receipt=? WHERE decision_id=?',(dumps(receipt),decision_id))
  else:c.execute('INSERT INTO case_graph_bindings VALUES(?,?,?,?,?)',(decision_id,binding_id,dumps(descriptor),dumps(receipt),now()))
  c.execute('INSERT INTO case_events(case_id,kind,detail,created) VALUES(?,?,?,?)',(d['case_id'],'graph_source_reauthorized' if old else 'graph_source_bound',dumps({'binding_id':binding_id,'decision_id':decision_id}),now()))
 return {'binding_id':binding_id,'decision_id':decision_id,'candidate_id':candidate,'source_type':'graph_token_day','historical_horizon_days':historical_horizon_days}

def materialize(decision_id,output):
 """Copy and rehash the bound private snapshot into a per-attempt directory."""
 with db() as c:
  row=c.execute('SELECT * FROM case_graph_bindings WHERE decision_id=?',(decision_id,)).fetchone();decision=c.execute('SELECT * FROM case_decisions WHERE id=?',(decision_id,)).fetchone()
 if not row:return None
 if not decision:raise ValueError('Graph decision missing')
 descriptor=json.loads(row['descriptor']);receipt=json.loads(row['receipt']);binding_id=row['binding_id']
 if receipt.get('binding_id')!=binding_id or receipt.get('role')!='admin' or type(receipt.get('expires_at')) not in (int,float) or not math.isfinite(receipt['expires_at']) or receipt['expires_at']<=now():raise PermissionError('Graph authorization expired or invalid')
 if (descriptor['decision_id'],descriptor['case_id'],descriptor['snapshot_digest'],descriptor['policy_digest'])!=(decision_id,decision['case_id'],decision['snapshot_id'],decision['policy_digest']) or digest(dumps(descriptor).encode())!=binding_id:raise ValueError('Graph binding integrity failure')
 root=DATA/'graph-bindings'/binding_id
 if root.is_symlink() or not root.is_dir():raise ValueError('Graph binding snapshot missing')
 output=Path(output);output.mkdir(parents=True,exist_ok=True)
 for name,expected in descriptor['files'].items():
  if not isinstance(name,str) or any(x in ('','.','..') for x in name.split('/')) or '\\' in name:raise ValueError('unsafe Graph binding path')
  path=root
  for part in name.split('/'):
   path=path/part
   if path.is_symlink():raise ValueError('unsafe Graph binding symlink')
  if not path.is_file() or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size>50_000_000:raise ValueError('Graph binding artifact missing or unsafe')
  raw=path.read_bytes()
  if digest(raw)!=expected:raise ValueError('Graph binding artifact changed')
  target=output.joinpath(*name.split('/'));target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
 capture=graph_history.verify_capture(output/'capture',descriptor['candidate_id'])
 if descriptor['historical_horizon_days'] is not None:
  model=graph_history.verify_model(output/'model',capture,descriptor['technical_sha256'])
  if model['manifest']['days']!=descriptor['historical_horizon_days']:raise ValueError('Graph model horizon mismatch')
 return {'binding_id':binding_id,'capture_dir':output/'capture','model_dir':output/'model' if descriptor['historical_horizon_days'] is not None else None,'technical_sha256':descriptor['technical_sha256'],'selection':descriptor['selection']}


def summary(c,decision_id):
 row=c.execute('SELECT * FROM case_graph_bindings WHERE decision_id=?',(decision_id,)).fetchone()
 if not row:return None
 descriptor=json.loads(row['descriptor']);receipt=json.loads(row['receipt'])
 if digest(dumps(descriptor).encode())!=row['binding_id'] or receipt.get('binding_id')!=row['binding_id']:raise ValueError('Graph binding integrity failure')
 selection=descriptor['selection'];expiry=receipt.get('expires_at');valid_expiry=type(expiry) in (int,float) and math.isfinite(expiry);safe_selection={k:selection[k] for k in ('profile','source_type','subgraph_id','window','discovery_status','evidence')}
 return {'binding_id':row['binding_id'],'source_type':'graph_token_day','selection':safe_selection,'capture_status':descriptor['capture_status'],'historical_horizon_days':descriptor['historical_horizon_days'],'technical_sha256':descriptor['technical_sha256'],'authorization':'invalid' if not valid_expiry or receipt.get('role')!='admin' else 'expired' if expiry<=now() else 'admin_receipt','authorization_expires_at':receipt.get('expires_at')}
