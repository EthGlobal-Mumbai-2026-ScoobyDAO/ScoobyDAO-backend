"""Capture a bounded finalized-block G09 V2/WETH series for a monitored Ethereum candidate."""
import argparse,datetime as dt,hashlib,json,sqlite3,sys,time,urllib.request
from pathlib import Path
import discovery,market_activity as m
URL='https://ethereum-rpc.publicnode.com'
class RPC:
 def __init__(self,budget):self.budget=budget;self.calls=0;self.trace=[]
 def call(self,method,params):
  if self.calls>=self.budget:raise ValueError('RPC request budget exhausted')
  self.calls+=1; time.sleep(0.12)
  request={'jsonrpc':'2.0','id':self.calls,'method':method,'params':params}
  req=urllib.request.Request(URL,data=json.dumps(request).encode(),headers={'User-Agent':'ScoobyDAO-market-capture/1.0','Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=10) as r:response=json.load(r)
  self.trace.append({'request':request,'response':response})
  if response.get('id')!=self.calls or 'error' in response or 'result' not in response:raise ValueError('RPC returned error or mismatched request')
  return response['result']
 def block(self,n):
  obj=self.call('eth_getBlockByNumber',[n,False])
  if not isinstance(obj,dict) or not all(k in obj for k in ('number','timestamp','hash')):raise ValueError('block unavailable')
  return obj
 def eth(self,to,data,tag):return {'to':to,'data':data,'block':tag,'result':self.call('eth_call',[{'to':to,'data':data},tag])}
def main():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--candidate-id',required=True);p.add_argument('--pool',required=True);p.add_argument('--budget',type=int,default=40);a=p.parse_args()
 if not 1<=a.budget<=45:raise ValueError('budget must be between 1 and 45')
 db=sqlite3.connect(a.db);row=db.execute('SELECT record FROM candidates WHERE id=?',(a.candidate_id,)).fetchone()
 if not row:raise ValueError('candidate not found')
 record=json.loads(row[0]);token=record['identity']['address'].lower();pool=a.pool.lower()
 if record.get('mode')!='live' or record['identity']['chain_id']!=1 or discovery.identity(1,token)!=a.candidate_id:raise ValueError('only monitored Ethereum live candidates supported')
 if not m.re.fullmatch(r'0x[0-9a-f]{40}',pool):raise ValueError('pool address malformed')
 lead=db.execute('SELECT created_at FROM pilot_leads WHERE candidate_id=? AND pool_id=? ORDER BY created_at LIMIT 1',(a.candidate_id,pool)).fetchone()
 if not lead:raise ValueError('pool not attached to monitored candidate')
 # Pool age is a conservative prefilter only; source-provided creation time is not accepted as proof.
 if not lead[0] or (dt.datetime.now(dt.timezone.utc)-discovery.stamp(lead[0])).total_seconds()<86400:raise ValueError('pool age or history insufficient for a complete 24-hour observation')
 rpc=RPC(a.budget)
 if rpc.call('eth_chainId',[])!='0x1':raise ValueError('wrong chain')
 current=rpc.block('finalized');end=m.integer(current['number']);end_ts=m.integer(current['timestamp']);target=end_ts-86400
 lo=max(1,end-10000);left=rpc.block(hex(lo))
 if m.integer(left['timestamp'])>target:raise ValueError('block search range does not cover 24 hours')
 hi=end
 while lo+1<hi:
  mid=(lo+hi)//2;b=rpc.block(hex(mid))
  if m.integer(b['timestamp'])<=target:lo=mid
  else:hi=mid
 old=rpc.block(hex(lo));
 def point(b,finality):
  tag=b['number'];pair='0xe6a43905'+token[2:].rjust(64,'0')+m.WETH[2:].rjust(64,'0')
  specs=[('token0',pool,'0x0dfe1681'),('token1',pool,'0xd21220a7'),('factory',pool,'0xc45a0155'),('factory_pair',m.FACTORY,pair),('reserves',pool,'0x0902f1ac'),('feed_decimals',m.FEED,'0x313ce567'),('feed_round',m.FEED,'0xfeaf968c')]
  return {'block_tag':tag,'block_hash':b['hash'],'block_timestamp':m.integer(b['timestamp']),'finality':finality,'calls':{name:rpc.eth(to,data,tag) for name,to,data in specs}}
 snapshot={'format':'G09_V2_WETH_V1','source_kind':'rpc_capture','rpc_url':URL,'chain_id':1,'candidate_id':a.candidate_id,'pool':pool,'prior':point(old,'historical_finalized'),'latest':point(current,'finalized'),'rpc_trace':rpc.trace,'limitations':['Single direct Uniswap V2/WETH pool, not global price or a trade quote.','RPC evidence is a provider response, not a cryptographic consensus proof.']}
 raw=json.dumps(snapshot,sort_keys=True,indent=2).encode();digest=hashlib.sha256(raw).hexdigest();folder=a.output/'snapshots';folder.mkdir(parents=True,exist_ok=True);(folder/(digest+'.json')).write_bytes(raw)
 observed=dt.datetime.fromtimestamp(snapshot['latest']['block_timestamp'],dt.timezone.utc).isoformat();fetched=dt.datetime.now(dt.timezone.utc).isoformat()
 evidence={'id':digest,'source':'snapshots/'+digest+'.json','sha256':digest,'observed_at':observed,'fetched_at':fetched,'block_number':end,'kind':'live_observation','limitations':['G09_V2_WETH_V1','Single-pool price only; RPC source and method are in snapshot.']}
 pending=dict(record);pending['evidence']=record['evidence']+[evidence]
 outcome=m.verify(pending,a.output,dt.datetime.now(dt.timezone.utc))
 if not any(e['id']==digest for e in record['evidence']):record['evidence'].append(evidence)
 with db:db.execute('UPDATE candidates SET record=? WHERE id=?',(json.dumps(record,ensure_ascii=False),a.candidate_id))
 db.close();print(json.dumps({'candidate_id':a.candidate_id,'calls':rpc.calls,'snapshot':evidence['source'],'sha256':digest,'result':outcome,'note':'G09 is one concern; four verified distinct groups are needed to enter the queue.'},indent=2))
 return 0
if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as e:print(str(e),file=sys.stderr);raise SystemExit(1)
