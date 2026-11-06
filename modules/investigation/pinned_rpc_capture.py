"""Bounded read-only JSON-RPC capture. No wallet, signing, broadcast or live CLI."""
import datetime,hashlib,json,pathlib,urllib.request,urllib.parse
ALLOWED={'eth_call':1,'debug_traceCall':1,'eth_getCode':1,'eth_getStorageAt':2,'eth_getBalance':1}
def rpc_transport(endpoint):
 u=urllib.parse.urlparse(endpoint)
 if u.scheme!='https' and not (u.scheme=='http' and u.hostname in ('127.0.0.1','localhost','::1')):raise ValueError('HTTPS or loopback endpoint required')
 def send(body):
  req=urllib.request.Request(endpoint,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=30) as r:return r.read()
 return send

def capture(plan,selection,out,transport,max_requests=0):
 # The backend, not this function, authenticates the selected human actor.
 if selection.get('candidate_id')!=plan['candidate_id'] or selection.get('decision') not in ('selected','diagnostic_exception') or not selection.get('record_id'):raise ValueError('recorded selection required')
 if max_requests<3+len(plan['operations']):raise ValueError('request budget too small; no calls made')
 number=plan['block']['number'];tag=hex(number);expected_hash=plan['block']['hash']
 for op in plan['operations']:
  if op['method'] not in ALLOWED:raise ValueError('non-read-only operation rejected')
  idx=ALLOWED[op['method']]
  if len(op['params'])<=idx or op['params'][idx]!=tag:raise ValueError('operation must use pinned numeric block')
 out=pathlib.Path(out)
 if out.exists():raise ValueError('output exists')
 out.mkdir(parents=True);records=[]
 def call(method,params):
  if len(records)>=max_requests:raise ValueError('request budget exhausted')
  request={'jsonrpc':'2.0','id':len(records)+1,'method':method,'params':params};stem=str(len(records)+1).zfill(3);(out/(stem+'-request.json')).write_text(json.dumps(request,indent=2)+'\n',encoding='utf8')
  rec={'method':method,'request_path':stem+'-request.json','attempted_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'response_path':None,'sha256':None,'status':'attempted'};records.append(rec)
  try:
   raw=transport(request);path=out/(stem+'-response.json');path.write_bytes(raw);rec.update(response_path=path.name,sha256=hashlib.sha256(raw).hexdigest(),status='received');response=json.loads(raw)
   if response.get('id')!=request['id'] or 'error' in response or 'result' not in response:raise ValueError('RPC error or mismatched reply')
   return response['result']
  except Exception:
   rec['status']='failed';raise
  finally:(out/'requests.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf8')
 chain=call('eth_chainId',[])
 if int(chain,16)!=int(plan['candidate_id'].split(':')[0]):raise ValueError('wrong RPC chain')
 for phase in ('before','operations','after'):
  if phase=='operations':
   for op in plan['operations']:call(op['method'],op['params'])
  else:
   header=call('eth_getBlockByNumber',[tag,False])
   if not header or header['hash'].lower()!=expected_hash.lower() or int(header['number'],16)!=number:raise ValueError('pinned block mismatch/reorg')
 manifest={'profile':'scooby.pinned-rpc-capture/1','candidate_id':plan['candidate_id'],'block':plan['block'],'selection_record_id':selection['record_id'],'attempts':len(records),'records':records,'scope':'Independent read-only calls; not a stateful round-trip buy/sell simulation. No conclusion inferred.'}
 (out/'capture.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8');return manifest
