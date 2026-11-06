import datetime as dt,hashlib,json,unittest
import graph_activity_30d as graph
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker

class GraphActivityTests(unittest.TestCase):
 def setUp(self):
  self.now=dt.datetime(2026,11,7,12,30,tzinfo=dt.timezone.utc);self.end=self.now.replace(minute=0);self.start=self.end-dt.timedelta(hours=720);self.token='0x'+'a'*40
  self.rows=[{'periodStartUnix':int((self.start+dt.timedelta(hours=i)).timestamp()),'token':{'id':self.token},'volumeUSD':'1','priceUSD':'1','totalValueLockedUSD':'10'} for i in range(720)]
  self.doc={'data':{'_meta':{'deployment':'synthetic','hasIndexingErrors':False,'block':{'number':100,'timestamp':int(self.now.timestamp())}},'tokenHourDatas':self.rows}}
  self.fx={'base':'USD','quote':'INR','rate':100,'date':'2026-11-06'}
 def captures(self,doc=None,fx=None):
  raw=json.dumps(self.doc if doc is None else doc).encode();body={'url':graph.URL,'fetched_at':self.now.isoformat(),'raw':raw,'sha256':hashlib.sha256(raw).hexdigest(),'query':graph.QUERY,'variables':{'token':self.token,'start':int(self.start.timestamp()),'end':int(self.end.timestamp())}}
  raw=json.dumps(self.fx if fx is None else fx).encode();f={'url':'https://api.frankfurter.dev/v2/providers/ecb/rate/usd/inr?date=2026-11-06','fetched_at':self.now.isoformat(),'raw':raw,'sha256':hashlib.sha256(raw).hexdigest()};return body,f
 def run_case(self,doc=None,fx=None):
  b,f=self.captures(doc,fx);return graph.evaluate('1:'+self.token,b,f,self.now)
 def test_threshold_and_scope(self):
  self.assertEqual(self.run_case()['status'],'below_indexed_scope_threshold');self.rows[0]['volumeUSD']='99281';v=self.run_case();self.assertEqual(v['status'],'pass');self.assertEqual(v['volume_inr'],'10000000');self.assertEqual(v['decision_scope'],'ethereum_uniswap_v3_token');self.assertEqual(v['source']['indexed_block_number'],100);json.dumps(v)
 def test_missing_or_duplicate_hours_remain_unknown(self):
  self.rows.pop();self.assertEqual(self.run_case()['reason'],'incomplete_hourly_coverage');self.rows.append(self.rows[0]);self.assertEqual(self.run_case()['reason'],'duplicate_hour')
 def test_stale_index_and_graphql_errors(self):
  self.doc['data']['_meta']['block']['timestamp']=int(self.now.timestamp())-7200;self.assertEqual(self.run_case()['reason'],'indexer_stale_or_unconfirmed')
  self.doc['errors']=[{'message':'indexing_error'}];self.assertEqual(self.run_case()['reason'],'graph_query_failed')
 def test_wrong_identity_or_query(self):
  self.rows[0]['token']['id']='0x'+'b'*40;self.assertEqual(self.run_case()['reason'],'hour_identity_or_window_invalid')
  b,f=self.captures();b['variables']['token']='0x'+'c'*40;self.assertEqual(graph.evaluate('1:'+self.token,b,f,self.now)['reason'],'query_binding_invalid')
 def test_invalid_fx_and_data_hash(self):
  self.assertEqual(self.run_case(fx={**self.fx,'rate':0})['reason'],'fx_rate_invalid')
  b,f=self.captures();b['sha256']='0'*64;self.assertEqual(graph.evaluate('1:'+self.token,b,f,self.now)['reason'],'capture_integrity')
 def test_schema_for_present_and_missing(self):
  validator=Draft202012Validator(json.loads(Path(__file__).with_name('graph-activity-30d.schema.json').read_text()),format_checker=FormatChecker())
  validator.validate(self.run_case());self.rows.pop();validator.validate(self.run_case())

if __name__=='__main__':unittest.main()
