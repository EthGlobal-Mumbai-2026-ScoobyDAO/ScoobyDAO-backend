import datetime as dt,hashlib,json,unittest
from decimal import Decimal
import activity_30d as a
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

class ActivityTests(unittest.TestCase):
 def setUp(self):
  self.now=dt.datetime(2026,11,7,12,34,tzinfo=dt.timezone.utc);self.end=self.now.replace(minute=0);self.token='0x'+'a'*40;self.pool='0x'+'b'*40;self.candidate='1:'+self.token
  self.pool_url='https://api.geckoterminal.com/api/v2/networks/eth/tokens/'+self.token+'/pools?page=1'
  self.ohlc_url='https://pro-api.coingecko.com/api/v3/onchain/networks/eth/pools/'+self.pool+'/ohlcv/hour?aggregate=1&limit=1000&currency=usd&token=base&include_empty_intervals=false'
  self.fx_url='https://api.frankfurter.dev/v2/providers/ecb/rate/usd/inr'
  self.pools={'data':[{'attributes':{'address':self.pool,'reserve_in_usd':'12345'},'relationships':{'base_token':{'data':{'id':'eth_'+self.token}},'quote_token':{'data':{'id':'eth_0x'+'c'*40}}}}]}
  self.rows=[[int((self.end-dt.timedelta(hours=720-i)).timestamp()),1,1,1,1,1] for i in range(720)]
  self.fx={'base':'USD','quote':'INR','rate':100,'date':'2026-11-06'}
 def cap(self,url,obj):
  raw=json.dumps(obj).encode();return {'url':url,'fetched_at':self.now.isoformat(),'raw':raw,'sha256':hashlib.sha256(raw).hexdigest()}
 def run_case(self,rows=None,fx=None,pools=None,url=None):
  candle={'meta':{'base':{'address':self.token}},'data':{'attributes':{'ohlcv_list':self.rows if rows is None else rows}}}
  return a.evaluate(self.candidate,self.pool,self.cap(self.pool_url,self.pools if pools is None else pools),self.cap(url or self.ohlc_url,candle),self.cap(self.fx_url,self.fx if fx is None else fx),self.now)
 def test_threshold_above_equal_below(self):
  rows=[r[:] for r in self.rows];rows[0][5]=99281
  self.assertEqual(self.run_case(rows)['volume_inr'],'10000000');self.assertEqual(self.run_case(rows)['status'],'pass')
  rows[0][5]=99280;below=self.run_case(rows);self.assertEqual(below['status'],'excluded');self.assertEqual(below['token_activity_status'],'unknown')
  rows[0][5]=99282;above=self.run_case(rows);self.assertEqual(above['status'],'pass');self.assertEqual(above['token_activity_status'],'threshold_reported_by_selected_pool')
 def test_gap_duplicate_and_units_unknown(self):
  self.assertEqual(self.run_case(self.rows[:-1])['reason'],'incomplete_hourly_coverage')
  self.assertEqual(self.run_case(self.rows+[self.rows[0]])['reason'],'duplicate_hour')
  self.assertEqual(self.run_case(url=self.ohlc_url.replace('currency=usd','currency=token'))['status'],'unknown')
 def test_bad_rate_or_future_date_unknown(self):
  for rate in [0,-1,True]:self.assertEqual(self.run_case(fx={**self.fx,'rate':rate})['status'],'unknown')
  self.assertEqual(self.run_case(fx={**self.fx,'date':'2026-11-07'})['reason'],'fx_date_unavailable_or_stale')
 def test_identity_hash_and_age_fail_closed(self):
  pools={'data':[self.pools['data'][0],self.pools['data'][0]]};self.assertEqual(self.run_case(pools=pools)['reason'],'pool_identity_ambiguous')
  c=self.cap(self.pool_url,self.pools);c['sha256']='0'*64;self.assertEqual(a.evaluate(self.candidate,self.pool,c,None,None,self.now)['reason'],'capture_integrity')
  c=self.cap(self.pool_url,self.pools);c['fetched_at']=(self.now-dt.timedelta(hours=2)).isoformat();self.assertEqual(a.evaluate(self.candidate,self.pool,c,None,None,self.now)['reason'],'stale_or_future_capture')
 def test_context_and_scope(self):
  v=self.run_case();self.assertEqual(v['coverage']['observed_hours'],720);self.assertEqual(v['scope']['coverage'],'selected_pool_only');self.assertEqual(v['context']['liquidity_usd'],'12345');self.assertEqual(v['context']['volatility_return_count'],719);self.assertEqual(Decimal(v['context']['annualized_hourly_log_volatility']),0)
 def test_missing_and_bad_fx_does_not_become_zero(self):
  v=self.run_case(fx={**self.fx,'rate':'NaN'});self.assertEqual(v['status'],'unknown');self.assertIsNone(v['volume_inr'])
 def test_explicit_zero_bucket_is_not_missing(self):
  rows=[r[:] for r in self.rows];rows[0][5]=0;v=self.run_case(rows);self.assertEqual(v['coverage']['observed_hours'],720);self.assertEqual(v['volume_usd'],'719');self.assertEqual(v['status'],'excluded')
 def test_contract_accepts_complete_and_unknown_results(self):
  validator=Draft202012Validator(json.loads(Path(__file__).with_name('activity-30d.schema.json').read_text()),format_checker=FormatChecker())
  for v in (self.run_case(),self.run_case(self.rows[:-1])):validator.validate(v)
  v=self.run_case();self.assertEqual(v['fx']['evidence_id'],v['evidence']['fx_rate']['evidence_id']);self.assertEqual(v['decision_scope'],'selected_pool_only')
 def test_future_capture_and_wrong_canonical_identity_unknown(self):
  c=self.cap(self.pool_url,self.pools);c['fetched_at']=(self.now+dt.timedelta(seconds=1)).isoformat()
  self.assertEqual(a.evaluate(self.candidate,self.pool,c,None,None,self.now)['reason'],'stale_or_future_capture')
  self.assertEqual(a.evaluate('01:'+self.token,self.pool,None,None,None,self.now)['reason'],'identity_invalid')
 def test_provider_unavailable_never_qualifies(self):
  v=a.evaluate(self.candidate,self.pool,None,None,None,self.now);self.assertEqual(v['status'],'unknown');self.assertIsNone(v['volume_inr'])
 def test_secret_query_is_rejected_and_not_returned(self):
  v=self.run_case(url=self.ohlc_url+'&api_key=synthetic-secret');self.assertEqual(v['status'],'unknown');self.assertNotIn('synthetic-secret',json.dumps(v))

if __name__=='__main__':unittest.main()
