"""Fetch a small read-only chain snapshot for one monitored candidate."""
import argparse,datetime as dt,hashlib,json,sqlite3,urllib.request,urllib.error
from pathlib import Path
import discovery
RPC={1:'https://ethereum-rpc.publicnode.com',8453:'https://mainnet.base.org'}
IMPL='0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc'
ADMIN='0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103'
def utc():return dt.datetime.now(dt.timezone.utc).isoformat()
def call(url,method,params):
 payload={'jsonrpc':'2.0','id':1,'method':method,'params':params}
 try:
  req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','User-Agent':'ScoobyDAO-local-pilot/1.0'})
  with urllib.request.urlopen(req,timeout=15) as r: obj=json.load(r)
  if not isinstance(obj,dict) or obj.get('id')!=1: raise ValueError('invalid RPC response')
  if 'error' in obj:return {'status':'rpc_error','error':obj['error']}
  if 'result' not in obj:raise ValueError('RPC result absent')
  return {'status':'ok','result':obj['result']}
 except (OSError,ValueError) as e:return {'status':'error','error':str(e)}
def main():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--candidate-id',required=True);a=p.parse_args()
 c=sqlite3.connect(a.db);row=c.execute('SELECT record FROM candidates WHERE id=?',(a.candidate_id,)).fetchone()
 if not row:raise ValueError('candidate not found in monitoring stack')
 record=json.loads(row[0]);i=record['identity'];key=discovery.identity(i['chain_id'],i['address']);assert key==a.candidate_id
 url=RPC[i['chain_id']];calls={};calls['chain_id']=call(url,'eth_chainId',[])
 if calls['chain_id'].get('result')!=hex(i['chain_id']): raise ValueError('RPC chain mismatch/unavailable')
 calls['finalized_block']=call(url,'eth_getBlockByNumber',['finalized',False]);block=calls['finalized_block'].get('result')
 if not isinstance(block,dict) or not isinstance(block.get('number'),str): raise ValueError('finalized block unavailable; no latest fallback')
 tag=block['number'];addr=i['address']
 for name,method,params in [('code','eth_getCode',[addr,tag]),('owner','eth_call',[{'to':addr,'data':'0x8da5cb5b'},tag]),('total_supply','eth_call',[{'to':addr,'data':'0x18160ddd'},tag]),('paused','eth_call',[{'to':addr,'data':'0x5c975abb'},tag]),('implementation_slot','eth_getStorageAt',[addr,IMPL,tag]),('admin_slot','eth_getStorageAt',[addr,ADMIN,tag])]:calls[name]=call(url,method,params)
 code_exists=calls['code'].get('status')=='ok' and calls['code'].get('result') not in (None,'0x','0x0')
 blocknum=int(tag,16);observed=dt.datetime.fromtimestamp(int(block['timestamp'],16),dt.timezone.utc).isoformat();fetched=utc()
 snap={'method':'read-only JSON-RPC snapshot; finalized tag, per-call explicit block number','provider':url,'candidate_id':key,'block_number':blocknum,'block_hash':block.get('hash'),'block_time':observed,'fetched_at':fetched,'calls':calls,'limitations':['Owner, pause and proxy probes are partial; failures are unknown.','An address with code is not proof of benignness, ownership type, privilege semantics or token identity.','No four-group gate has been evaluated.'] + ([] if code_exists else ['No contract code confirmed at the finalized block; the candidate may be newer than finality or the RPC read may have failed.'])}
 raw=json.dumps(snap,sort_keys=True,indent=2).encode('utf-8');digest=hashlib.sha256(raw).hexdigest();folder=a.output/'snapshots';folder.mkdir(parents=True,exist_ok=True);(folder/(digest+'.json')).write_bytes(raw)
 ev={'id':digest,'source':'snapshots/'+digest+'.json','sha256':digest,'observed_at':observed,'fetched_at':fetched,'block_number':blocknum,'kind':'live_observation','limitations':snap['limitations']}
 if not any(x['id']==digest for x in record['evidence']):record['evidence'].append(ev)
 record['last_observed_at']=observed
 with c:c.execute('UPDATE candidates SET record=? WHERE id=?',(json.dumps(record,ensure_ascii=False),key))
 c.close();print(json.dumps({'candidate_id':key,'block_number':blocknum,'block_hash':block.get('hash'),'evidence_sha256':digest,'call_status':{k:v['status'] for k,v in calls.items()},'gate_vote':'none; requires metric-specific verification','code_confirmed_at_finalized_block':code_exists},indent=2)); return 0 if code_exists else 1
if __name__=='__main__': raise SystemExit(main())
