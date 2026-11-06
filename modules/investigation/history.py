"""Fetch identity-bound GeckoTerminal daily candles; no trading, no model calls."""
import argparse, datetime, hashlib, json, math, re, urllib.parse, urllib.request
from pathlib import Path
NETWORKS={1:'eth',8453:'base'}
def stamp(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def store(path,obj): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def identity(chain,address):
 if chain not in NETWORKS or not re.fullmatch(r'0x[0-9a-fA-F]{40}',address): raise ValueError('unsupported chain or invalid address')
 return f'{chain}:{address.lower()}'
def get(url,out,name):
 start=stamp(); req=urllib.request.Request(url,headers={'User-Agent':'Scooby-DAO-research/1.0','Accept':'application/json'})
 try:
  with urllib.request.urlopen(req,timeout=20) as res: raw=res.read(10000001); status=res.status
  if len(raw)>10000000: raise ValueError('response too large')
  doc=json.loads(raw,parse_constant=lambda s:(_ for _ in ()).throw(ValueError('non-finite JSON')))
  (out/(name+'.json')).write_bytes(raw); return doc,{'url':url,'requested_at':start,'fetched_at':stamp(),'http_status':status,'sha256':hashlib.sha256(raw).hexdigest(),'path':name+'.json'}
 except Exception as e: return None,{'url':url,'requested_at':start,'fetched_at':stamp(),'error_type':type(e).__name__,'status':'unavailable'}
def select_pool(doc,chain,address,preferred=None):
 asset=f'{NETWORKS[chain]}_{address.lower()}'; matches=[]
 for p in doc.get('data',[]):
  rel=p.get('relationships',{}); base=rel.get('base_token',{}).get('data',{}).get('id','').lower(); quote=rel.get('quote_token',{}).get('data',{}).get('id','').lower(); addr=p.get('attributes',{}).get('address','').lower()
  is_address=bool(re.fullmatch(r'0x[0-9a-f]{40}',addr))
  # GeckoTerminal identifies Base Uniswap v4 pools using a bytes32 pool ID,
  # not a contract address. Require its chain-specific DEX and pool record ID;
  # this is a provider attribution, not independent on-chain verification.
  dex=rel.get('dex',{}); dex=dex.get('data',{}) if isinstance(dex,dict) else {}; dex=dex if isinstance(dex,dict) else {}
  is_base_v4_id=(chain==8453 and bool(re.fullmatch(r'0x[0-9a-f]{64}',addr))
                 and dex.get('id')=='uniswap-v4-base' and str(p.get('id','')).lower()==f'base_{addr}')
  if not (is_address or is_base_v4_id): continue
  if asset==base or asset==quote:
   record={'address':addr,'side':'base' if asset==base else 'quote','name':p['attributes'].get('name'),'created_at':p['attributes'].get('pool_created_at')}
   if is_base_v4_id: record.update(identifier_type='provider_reported_uniswap_v4_pool_id',dex_id='uniswap-v4-base')
   matches.append(record)
 if preferred: matches=[p for p in matches if p['address']==preferred.lower()]
 if not matches: raise ValueError('no identity-matched pool in returned page')
 return matches[0],matches

def prepare(doc,cutoff):
 # Return closes and adjacent returns; never forward-fill missing dates or invent prices.
 rows=doc['data']['attributes']['ohlcv_list']; dates={}; cutoff=datetime.date.fromisoformat(cutoff)
 for row in rows:
  if len(row)<6: raise ValueError('malformed candle')
  dt=datetime.datetime.fromtimestamp(row[0],datetime.timezone.utc)
  if dt.time()!=datetime.time(0,0): raise ValueError('daily timestamp not UTC midnight')
  date=dt.date()
  if date>=cutoff: continue
  price=row[4]
  if isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0: raise ValueError('invalid close')
  if date in dates: raise ValueError('duplicate candle date')
  dates[date]=price
 ordered=sorted(dates.items()); returns=[]; gaps=[]
 for (prev,a),(cur,b) in zip(ordered,ordered[1:]):
  if (cur-prev).days!=1: gaps.append({'from':prev.isoformat(),'to':cur.isoformat()}); continue
  returns.append({'date':cur.isoformat(),'return':b/a-1})
 return {'close_count':len(ordered),'returns':returns,'gaps':gaps,'cutoff_utc_date':cutoff.isoformat(),'policy':'Only consecutive UTC daily closes strictly before explicit cutoff; omitted current day, no fill. This is a test input convention, not a chosen minimum-history policy.'}
def fetch(chain,address,out,pool=None):
 candidate=identity(chain,address); out=Path(out); out.mkdir(parents=True,exist_ok=True); network=NETWORKS[chain]; base='https://api.geckoterminal.com/api/v2/networks/'+network
 doc,meta=get(base+'/tokens/'+address.lower()+'/pools?page=1',out,'pools'); result={'candidate_id':candidate,'source':'GeckoTerminal public API','requests':[meta],'state':'unavailable','history':None}
 if doc is None: store(out/'source-status.json',result); return result
 try: chosen,alternatives=select_pool(doc,chain,address,pool)
 except ValueError as exc: result['error']=str(exc); store(out/'source-status.json',result); return result
 result['pool']=chosen; result['pool_alternatives']=alternatives; result['selection']='explicit pool' if pool else 'first matching pool in provider response; not best execution or market-wide coverage'
 url=base+'/pools/'+chosen['address']+'/ohlcv/day?'+urllib.parse.urlencode({'aggregate':1,'limit':1000,'currency':'usd','token':chosen['side'],'include_empty_intervals':'false'}); candles,rec=get(url,out,'daily'); result['requests'].append(rec)
 if candles is None: store(out/'source-status.json',result); return result
 cutoff=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
 try: h=prepare(candles,cutoff)
 except (KeyError,TypeError,ValueError,OverflowError) as exc:
  result['error']='Daily candle payload invalid: '+type(exc).__name__; store(out/'source-status.json',result); return result
 result['history']={'closes_before_cutoff':h['close_count'],'adjacent_daily_returns':len(h['returns']),'gaps':h['gaps'],'cutoff_utc_date':cutoff,'policy':h['policy']}; result['state']='available_for_operator_review' if len(h['returns'])>=2 and not h['gaps'] else 'pending_history_or_data_gaps'; store(out/'returns.json',h); store(out/'source-status.json',result); return result
if __name__=='__main__':
 a=argparse.ArgumentParser(description=__doc__); a.add_argument('--chain',type=int,required=True); a.add_argument('--address',required=True); a.add_argument('--output',type=Path,required=True); a.add_argument('--pool'); x=a.parse_args(); print(json.dumps(fetch(x.chain,x.address,x.output,x.pool),indent=2))
