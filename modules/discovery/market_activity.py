"""G09: finalized-block Ethereum Uniswap V2/WETH market activity evidence.
Data producer must supply the full RPC transcript; no provider summary casts a vote.
"""
import datetime as dt, json, math, re
from decimal import Decimal, localcontext
from pathlib import Path
import discovery

FACTORY='0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f'
WETH='0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
FEED='0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419'

def integer(value):
 if not isinstance(value,str) or not re.fullmatch(r'0x[0-9a-fA-F]+',value):raise ValueError('invalid RPC hex')
 return int(value,16)
def address_word(v):
 n=integer(v)
 if n>=2**160:raise ValueError('invalid address word')
 return '0x'+format(n,'040x')
def response(point,name,target,selector):
 v=point['calls'][name]
 if v.get('to','').lower()!=target or v.get('data','').lower()!=selector or v.get('block')!=point['block_tag']:raise ValueError('RPC call not bound to the expected contract, selector and block')
 return v['result']
def check_trace(doc,prior,latest):
 """Bind displayed values to matching requests and responses in the captured transcript."""
 trace=doc.get('rpc_trace')
 if not isinstance(trace,list) or not trace:raise ValueError('missing RPC transcript')
 def match(method,params):
  entries=[]
  for entry in trace:
   if not isinstance(entry,dict):raise ValueError('invalid RPC transcript')
   req=entry.get('request');res=entry.get('response')
   if not isinstance(req,dict) or not isinstance(res,dict):raise ValueError('invalid RPC transcript')
   if req.get('method')==method and req.get('params')==params:
    if req.get('id')!=res.get('id') or 'error' in res or 'result' not in res:raise ValueError('invalid RPC transcript response')
    entries.append(res['result'])
  if not entries:raise ValueError('RPC transcript request missing')
  if any(value!=entries[0] for value in entries):raise ValueError('conflicting RPC transcript responses')
  return entries[0]
 if match('eth_chainId',[])!='0x1':raise ValueError('RPC transcript chain mismatch')
 for point,tag in ((prior,prior['block_tag']),(latest,'finalized')):
  block=match('eth_getBlockByNumber',[tag,False])
  if not isinstance(block,dict) or block.get('number')!=point['block_tag'] or block.get('hash')!=point['block_hash'] or integer(block.get('timestamp'))!=point['block_timestamp']:raise ValueError('RPC transcript block mismatch')
  for call in point['calls'].values():
   result=match('eth_call',[{'to':call['to'],'data':call['data']},point['block_tag']])
   if result!=call['result']:raise ValueError('RPC transcript call mismatch')
def price(point,token,pool):
 tag=point['block_tag'];num=integer(tag);ts=point['block_timestamp']
 if not isinstance(ts,int) or num<=0:raise ValueError('invalid block metadata')
 calls=point['calls']; token0=address_word(response(point,'token0',pool,'0x0dfe1681'));token1=address_word(response(point,'token1',pool,'0xd21220a7'))
 if {token0,token1}!={token,WETH}:raise ValueError('pool tokens do not match candidate and WETH')
 if address_word(response(point,'factory',pool,'0xc45a0155'))!=FACTORY:raise ValueError('not canonical Ethereum Uniswap V2 factory')
 pair_call='0xe6a43905'+token[2:].rjust(64,'0')+WETH[2:].rjust(64,'0')
 if address_word(response(point,'factory_pair',FACTORY,pair_call))!=pool:raise ValueError('factory does not recognize this pair')
 r=response(point,'reserves',pool,'0x0902f1ac');s=r[2:]
 if len(s)!=192:raise ValueError('invalid reserve response')
 a,b,updated=(int(s[i:i+64],16) for i in (0,64,128))
 if a<=0 or b<=0 or a>=2**112 or b>=2**112 or updated>=2**32:raise ValueError('invalid reserves')
 if updated==0 or ((ts-updated) % 2**32)>3600:raise ValueError('pool reserves are stale')
 decimals=integer(response(point,'feed_decimals',FEED,'0x313ce567'))
 if decimals>36:raise ValueError('invalid feed decimals')
 ans=response(point,'feed_round',FEED,'0xfeaf968c')[2:]
 if len(ans)!=320:raise ValueError('invalid feed response')
 rr,answer,started,updated_at,answered=[int(ans[i:i+64],16) for i in range(0,320,64)]
 if answer>=2**255:answer-=2**256
 if rr==0 or answer<=0 or updated_at<=0 or updated_at>ts or ts-updated_at>3600:raise ValueError('missing or stale reference price')
 token_reserve,eth_reserve=(a,b) if token0==token else (b,a)
 # Token decimals cancel in the percentage change, because the same asset is compared twice.
 return Decimal(eth_reserve)*Decimal(answer)/(Decimal(token_reserve)*(Decimal(10)**decimals))
def verify(record,root,as_of):
 if record['identity']['chain_id']!=1:raise ValueError('G09 Ethereum V2 only; other chains remain unknown')
 token=record['identity']['address'].lower();evidence=[x for x in record['evidence'] if any('G09_V2_WETH_V1' in str(z) for z in x.get('limitations',[]))]
 if not evidence:raise ValueError('no market history evidence')
 evidence.sort(key=lambda e:e.get('fetched_at') or '',reverse=True);e=evidence[0]
 if not re.fullmatch(r'snapshots/[0-9a-f]{64}\.json',e.get('source','')):raise ValueError('invalid source')
 path=root/e['source'];resolved=path.resolve()
 if path.is_symlink() or path.parent.is_symlink() or not resolved.is_relative_to(root.resolve()):raise ValueError('unsafe snapshot')
 import hashlib
 raw=path.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=e.get('sha256') or e.get('id')!=e.get('sha256'):raise ValueError('snapshot digest mismatch')
 doc=json.loads(raw)
 if doc.get('format')!='G09_V2_WETH_V1' or doc.get('chain_id')!=1 or doc.get('candidate_id')!=record['candidate_id'] or doc.get('source_kind')!='rpc_capture' or doc.get('rpc_url')!='https://ethereum-rpc.publicnode.com':raise ValueError('snapshot provenance mismatch')
 pool=doc.get('pool','').lower()
 if not re.fullmatch(r'0x[0-9a-f]{40}',pool):raise ValueError('invalid pool address')
 prior,latest=doc['prior'],doc['latest']
 if latest.get('finality')!='finalized' or any(not re.fullmatch(r'0x[0-9a-fA-F]{64}',p.get('block_hash','')) for p in (prior,latest)):raise ValueError('missing finalized block/hash provenance')
 elapsed=latest['block_timestamp']-prior['block_timestamp']
 if not 86400<=elapsed<=90000 or integer(prior['block_tag'])>=integer(latest['block_tag']):raise ValueError('requires 24-25 hours of ordered history')
 if e.get('block_number')!=integer(latest['block_tag']) or discovery.stamp(e['observed_at']).timestamp()!=latest['block_timestamp']:raise ValueError('evidence block/time mismatch')
 check_trace(doc,prior,latest)
 with localcontext() as context:
  context.prec=60; before=price(prior,token,pool);after=price(latest,token,pool);pct=(after/before-1)*100
 if not pct.is_finite():raise ValueError('invalid percentage')
 return {'triggered':True if abs(pct)>=Decimal(20) else None,'detail':'USD price change over a complete 24–25 hour interval from finalized-block V2 pool reserves and Chainlink ETH/USD; one direct pool only. Volume change is not evaluated, so a below-threshold price move leaves this concern unknown.','measurements':[{'label':'USD price change','value':str(round(pct,4)),'unit':'%'},{'label':'observation interval','value':elapsed,'unit':'seconds'}],'evidence_ids':[e['id']]}
