"""Offline Graph token-hour screen; no source calls or concern-gate votes."""
import datetime as dt
import hashlib
import json
import math
import re
import statistics
from decimal import Decimal, InvalidOperation, localcontext
import activity_30d as common

# Ethereum Uniswap V3 deployment used in the prior VaR capture. No Base claim.
SUBGRAPH='5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV'
URL='https://gateway.thegraph.com/api/subgraphs/id/'+SUBGRAPH
QUERY='''query($token: String!, $start: Int!, $end: Int!) {
  _meta { deployment hasIndexingErrors block { number timestamp } }
  tokenHourDatas(first: 1000, where: {token: $token, periodStartUnix_gte: $start, periodStartUnix_lt: $end}, orderBy: periodStartUnix, orderDirection: asc) {
    periodStartUnix token { id } volumeUSD totalValueLockedUSD priceUSD
  }
}'''

def evaluate(candidate_id,graph_capture,fx_capture,as_of):
 if not isinstance(as_of,dt.datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:raise ValueError('as_of must be timezone aware')
 now=as_of.astimezone(dt.timezone.utc);end=now.replace(minute=0,second=0,microsecond=0);start=end-dt.timedelta(hours=720)
 out={'profile':'scooby.graph-activity-30d/1-proposal','status':'unknown','decision_scope':'ethereum_uniswap_v3_token','network':'ethereum','reason':'not_evaluated','evaluated_at_utc':now.isoformat(),'window_start_utc':start.isoformat(),'window_end_utc':end.isoformat(),'threshold_inr':'10000000','volume_usd':None,'volume_inr':None,'candidate_id':candidate_id,'subgraph_id':SUBGRAPH,'coverage':{'expected_hours':720,'observed_hours':0},'context':{'indexed_tvl_usd':None,'annualized_hourly_log_volatility':None,'volatility_return_count':0,'volatility_method':'sample_stddev_hourly_log_returns_times_sqrt_8760','volatility_unit':'annualized_fraction'},'fx':None,'source':None,'limitations':['One Ethereum Uniswap V3 subgraph only; no token-wide or other-chain coverage.','Missing hours are unknown, not zero.','Derived USD volume can be distorted by pricing, wash trading or indexer coverage.','The full USD window is converted at one dated reference FX rate, not trade-time rates.','TVL is a subgraph-derived token-level estimate, not executable pool liquidity or a trade quote.','Indexed block timestamp and number are not independently verified finality.']}
 try:
  chain,address=candidate_id.split(':')
  if chain!='1' or not re.fullmatch(r'0x[0-9a-f]{40}',address):raise ValueError('identity_invalid')
  if not isinstance(graph_capture,dict) or set(graph_capture)!={'url','fetched_at','raw','sha256','query','variables'}:raise ValueError('missing_capture')
  if graph_capture['url']!=URL or graph_capture['query']!=QUERY or graph_capture['variables']!={'token':address,'start':int(start.timestamp()),'end':int(end.timestamp())}:raise ValueError('query_binding_invalid')
  captured={k:graph_capture[k] for k in ('url','fetched_at','raw','sha256')};data=common._read(captured,now)
  if data.get('errors') or not isinstance(data.get('data'),dict):raise ValueError('graph_query_failed')
  payload=data['data'];meta=payload['_meta'];block=meta['block'];block_time=block['timestamp'];number=block['number']
  if meta.get('hasIndexingErrors') is not False or not isinstance(meta.get('deployment'),str) or not meta['deployment']:raise ValueError('indexer_unhealthy')
  if type(block_time) is not int or type(number) is not int or number<=0 or block_time<int(end.timestamp()) or not 0<=now.timestamp()-block_time<=3600:raise ValueError('indexer_stale_or_unconfirmed')
  rows=payload['tokenHourDatas']
  if not isinstance(rows,list) or len(rows)>=1000:raise ValueError('pagination_incomplete')
  buckets={};prices={};tvl={};start_ts=int(start.timestamp());end_ts=int(end.timestamp())
  for row in rows:
   ts=row['periodStartUnix']
   if type(ts) is not int or ts%3600 or not start_ts<=ts<end_ts or row['token']['id'].lower()!=address:raise ValueError('hour_identity_or_window_invalid')
   if ts in buckets:raise ValueError('duplicate_hour')
   value=row['volumeUSD']
   if not isinstance(value,str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?',value):raise ValueError('volume_invalid')
   amount=common._number(Decimal(value),'volume_invalid')
   if amount<0:raise ValueError('volume_invalid')
   buckets[ts]=amount
   for field,target,positive in [('priceUSD',prices,True),('totalValueLockedUSD',tvl,False)]:
    try:
     val=row[field]
     if not isinstance(val,str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?',val):continue
     context_value=common._number(Decimal(val),'invalid_context')
     if context_value>=0 and (not positive or context_value>0):target[ts]=context_value
    except (KeyError,ValueError,InvalidOperation):pass
  out['coverage']['observed_hours']=len(buckets)
  if set(buckets)!=set(range(start_ts,end_ts,3600)):raise ValueError('incomplete_hourly_coverage')
  if end_ts-3600 in tvl:out['context']['indexed_tvl_usd']=str(tvl[end_ts-3600])
  if len(prices)==720:
   try:
    ordered=[prices[t] for t in sorted(prices)];returns=[math.log(float(b/a)) for a,b in zip(ordered,ordered[1:])];vol=statistics.stdev(returns)*math.sqrt(8760)
    if math.isfinite(vol):out['context'].update(annualized_hourly_log_volatility=str(vol),volatility_return_count=719)
   except (OverflowError,ValueError,ZeroDivisionError):pass
  prior=(end.date()-dt.timedelta(days=1)).isoformat();common._url(fx_capture['url'],'api.frankfurter.dev','/v2/providers/ecb/rate/usd/inr',{'date':[prior]});fx=common._read(fx_capture,now)
  if fx.get('base')!='USD' or fx.get('quote')!='INR':raise ValueError('fx_pair_mismatch')
  rate=common._number(fx['rate'],'fx_rate_invalid');date=dt.date.fromisoformat(fx['date'])
  if rate<=0:raise ValueError('fx_rate_invalid')
  if date>dt.date.fromisoformat(prior) or not 1 <= (end.date()-date).days <= common.FX_MAX_DAYS:raise ValueError('fx_date_unavailable_or_stale')
  with localcontext() as ctx:ctx.prec=160;total=sum(buckets.values(),Decimal(0));inr=total*rate
  out.update(status='pass' if inr>=common.THRESHOLD else 'below_indexed_scope_threshold',reason='threshold_met_in_indexed_scope' if inr>=common.THRESHOLD else 'broader_venue_coverage_required',volume_usd=str(total),volume_inr=str(inr),fx={'provider':'ECB via Frankfurter','inr_per_usd':str(rate),'rate_date':date.isoformat(),'evidence_id':fx_capture['sha256'],'captured_at_utc':fx_capture['fetched_at'],'method':'single_reference_rate_for_full_window'},source={'response_sha256':graph_capture['sha256'],'fetched_at_utc':graph_capture['fetched_at'],'subgraph_id':SUBGRAPH,'deployment':meta['deployment'],'indexed_block_number':number,'indexed_block_timestamp':block_time,'query_sha256':hashlib.sha256(QUERY.encode()).hexdigest(),'variables':graph_capture['variables']})
 except (ValueError,TypeError,KeyError,IndexError,AttributeError,InvalidOperation,OverflowError,json.JSONDecodeError) as exc:
  reason=str(exc);out['reason']=reason if re.fullmatch(r'[a-z_]{1,64}',reason) else 'invalid_or_missing_evidence'
 return out
