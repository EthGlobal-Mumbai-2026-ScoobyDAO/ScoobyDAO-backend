"""Source-bound, selected-pool activity prefilter. No network or gate votes."""
import datetime as dt
import hashlib
import json
import math
import re
import statistics
from decimal import Decimal, InvalidOperation, localcontext
from urllib.parse import parse_qs,urlsplit

PROFILE='scooby.activity-30d/1-proposal'
THRESHOLD=Decimal('10000000')
HOURS=720
FX_MAX_DAYS=4
CAPTURE_MAX_SECONDS=3600
NET={1:'eth',8453:'base'}
LIMITATIONS=['Selected pool only; not token-wide or all-exchange volume.',
 'Reported USD volume can include wash trading and provider coverage or valuation errors.',
 'Entire USD window is converted using one dated INR-per-USD reference rate, not contemporaneous trade FX.',
 'Missing hourly intervals are unknown, not assumed zero; the latest incomplete hour is excluded.']

def _stamp(value):
 t=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
 if t.tzinfo is None or t.utcoffset() is None:raise ValueError('invalid_timestamp')
 return t.astimezone(dt.timezone.utc)

def _number(value,reason):
 if type(value) not in (int,Decimal):raise ValueError(reason)
 n=Decimal(value)
 if not n.is_finite() or len(n.as_tuple().digits)>60 or not -60<=n.as_tuple().exponent<=60:raise ValueError(reason)
 return n

def _read(capture,as_of):
 if not isinstance(capture,dict) or set(capture)!={'url','fetched_at','raw','sha256'}:raise ValueError('missing_capture')
 raw=capture['raw'];fetched=_stamp(capture['fetched_at'])
 if not isinstance(raw,bytes) or len(raw)>3_000_000 or hashlib.sha256(raw).hexdigest()!=capture['sha256']:raise ValueError('capture_integrity')
 if not 0 <= (as_of-fetched).total_seconds() <= CAPTURE_MAX_SECONDS:raise ValueError('stale_or_future_capture')
 return json.loads(raw,parse_float=Decimal,parse_int=int,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))

def _url(url,host,path,required):
 u=urlsplit(url)
 if u.scheme!='https' or u.netloc!=host or u.path!=path or u.fragment or u.username or u.password or parse_qs(u.query,keep_blank_values=True)!=required:raise ValueError('source_or_query_mismatch')

def evaluate(candidate_id,pool_id,pools_capture,ohlcv_capture,fx_capture,as_of):
 """Evaluate one explicitly selected pool using three immutable raw captures."""
 if not isinstance(as_of,dt.datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:raise ValueError('as_of must be timezone aware')
 now=as_of.astimezone(dt.timezone.utc);end=now.replace(minute=0,second=0,microsecond=0);start=end-dt.timedelta(hours=HOURS)
 result={'profile':PROFILE,'status':'unknown','decision_scope':'selected_pool_only','token_activity_status':'unknown','reason':'not_evaluated','evaluated_at_utc':now.isoformat(),'window_start_utc':start.isoformat(),'window_end_utc':end.isoformat(),'threshold_inr':str(THRESHOLD),'volume_usd':None,'volume_inr':None,'scope':None,'fx':None,'evidence':{},'coverage':{'expected_hours':HOURS,'observed_hours':0},'context':{'liquidity_usd':None,'annualized_hourly_log_volatility':None,'volatility_return_count':0,'volatility_method':'sample_stddev_hourly_log_returns_times_sqrt_8760','volatility_unit':'annualized_fraction'},'limitations':LIMITATIONS[:]}
 verified={}
 try:
  chain,address=candidate_id.split(':');chain=int(chain)
  if chain not in NET or candidate_id!=str(chain)+':'+address or not re.fullmatch(r'0x[0-9a-f]{40}',address) or not re.fullmatch(r'0x(?:[0-9a-f]{40}|[0-9a-f]{64})',pool_id):raise ValueError('identity_invalid')
  net=NET[chain];result['scope']={'chain_id':chain,'token_address':address,'pool_id':pool_id,'coverage':'selected_pool_only'}
  _url(pools_capture['url'],'api.geckoterminal.com',f'/api/v2/networks/{net}/tokens/{address}/pools',{'page':['1']})
  pools=_read(pools_capture,now);verified['pool_identity']=pools_capture;rows=pools['data'];matches=[x for x in rows if x.get('attributes',{}).get('address','').lower()==pool_id]
  if len(matches)!=1:raise ValueError('pool_identity_ambiguous')
  try:
   reserve=Decimal(str(matches[0]['attributes']['reserve_in_usd']))
   if reserve.is_finite() and reserve>=0:result['context']['liquidity_usd']=str(reserve if reserve else Decimal(0))
  except (InvalidOperation,ValueError,TypeError,KeyError):pass
  rel=matches[0]['relationships'];sides=[s for s in ('base','quote') if rel[s+'_token']['data']['id'].lower()==net+'_'+address]
  if len(sides)!=1:raise ValueError('token_side_ambiguous')
  side=sides[0];result['scope']['token_side']=side
  _url(ohlcv_capture['url'],'pro-api.coingecko.com',f'/api/v3/onchain/networks/{net}/pools/{pool_id}/ohlcv/hour',{'aggregate':['1'],'limit':['1000'],'currency':['usd'],'token':[side],'include_empty_intervals':['false']})
  candles=_read(ohlcv_capture,now);verified['hourly_volume']=ohlcv_capture
  if candles['meta'][side]['address'].lower()!=address:raise ValueError('ohlc_token_mismatch')
  hours={};closes={};begin=int(start.timestamp());finish=int(end.timestamp())
  for row in candles['data']['attributes']['ohlcv_list']:
   if not isinstance(row,list) or len(row)!=6 or type(row[0]) is not int or row[0]%3600:raise ValueError('invalid_hour_row')
   ts=row[0]
   if begin<=ts<finish:
    if ts in hours:raise ValueError('duplicate_hour')
    volume=_number(row[5],'invalid_volume')
    if volume<0:raise ValueError('invalid_volume')
    hours[ts]=volume
    try:
     close=Decimal(str(row[4]))
     if close.is_finite() and close>0:closes[ts]=close
    except (InvalidOperation,ValueError,TypeError):pass
  result['coverage']['observed_hours']=len(hours)
  if set(hours)!=set(range(begin,finish,3600)):raise ValueError('incomplete_hourly_coverage')
  if len(closes)==HOURS:
   try:
    ordered=[closes[t] for t in sorted(closes)];returns=[math.log(float(b/a)) for a,b in zip(ordered,ordered[1:])]
    vol=statistics.stdev(returns)*math.sqrt(365*24)
    if math.isfinite(vol):result['context'].update(annualized_hourly_log_volatility=str(vol),volatility_return_count=len(returns))
   except (OverflowError,ValueError,ZeroDivisionError):pass
  _url(fx_capture['url'],'api.frankfurter.dev','/v2/providers/ecb/rate/usd/inr',{})
  fx=_read(fx_capture,now);verified['fx_rate']=fx_capture
  if fx.get('base')!='USD' or fx.get('quote')!='INR':raise ValueError('fx_pair_mismatch')
  rate=_number(fx['rate'],'fx_rate_invalid');rate_date=dt.date.fromisoformat(fx['date'])
  if rate<=0:raise ValueError('fx_rate_invalid')
  # Date-only observations cannot prove intraday publication time. Avoid look-ahead.
  if not 1 <= (end.date()-rate_date).days <= FX_MAX_DAYS:raise ValueError('fx_date_unavailable_or_stale')
  with localcontext() as ctx:
   ctx.prec=160;total=sum(hours.values(),Decimal(0));inr=total*rate
  result['fx']={'provider':'ECB via Frankfurter','inr_per_usd':str(rate),'rate_date':rate_date.isoformat(),'captured_at_utc':fx_capture['fetched_at'],'evidence_id':fx_capture['sha256'],'method':'single_reference_rate_for_full_window'}
  result['volume_usd']=str(total);result['volume_inr']=str(inr);result['status']='pass' if inr>=THRESHOLD else 'excluded';result['reason']='selected_pool_meets_threshold' if result['status']=='pass' else 'selected_pool_below_threshold';result['token_activity_status']='threshold_reported_by_selected_pool' if result['status']=='pass' else 'unknown'
 except (ValueError,TypeError,KeyError,IndexError,AttributeError,InvalidOperation,OverflowError,json.JSONDecodeError) as exc:
  reason=str(exc);result['reason']=reason if re.fullmatch(r'[a-z_]{1,64}',reason) else 'invalid_or_missing_evidence'
 for label,capture in verified.items():
  result['evidence'][label]={'evidence_id':capture['sha256'],'source_url':capture['url'],'fetched_at_utc':capture['fetched_at']}
 return result
