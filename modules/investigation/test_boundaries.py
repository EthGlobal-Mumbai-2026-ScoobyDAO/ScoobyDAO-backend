import datetime,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT)); import history,contract_validate,pillars
class BoundaryTests(unittest.TestCase):
 def test_address_identity_and_chain(self):
  self.assertEqual(history.identity(1,'0x'+'AB'*20),'1:0x'+'ab'*20)
  with self.assertRaises(ValueError): history.identity(42,'0x'+'ab'*20)
 def test_pool_side_and_no_alias(self):
  x='0x'+'ab'*20; y='0x'+'cd'*20; p='0x'+'ef'*20; doc={'data':[{'attributes':{'address':p},'relationships':{'base_token':{'data':{'id':'eth_'+y}},'quote_token':{'data':{'id':'eth_'+x}}}}]}; self.assertEqual(history.select_pool(doc,1,x)[0]['side'],'quote')
  with self.assertRaises(ValueError): history.select_pool(doc,8453,x)
 def test_gaps_and_incomplete_day(self):
  def row(day,value): return [int(datetime.datetime(2026,1,day,tzinfo=datetime.timezone.utc).timestamp()),1,1,1,value,1]
  d={'data':{'attributes':{'ohlcv_list':[row(1,10),row(2,20),row(4,40),row(5,80)]}}}; r=history.prepare(d,'2026-01-05'); self.assertEqual(r['close_count'],3); self.assertEqual([x['return'] for x in r['returns']],[1.0]); self.assertEqual(len(r['gaps']),1)
 def test_pillar_failure_isolation_and_unavailable(self):
  def fail(_): raise RuntimeError('not for user display')
  result=pillars.run_pillars({'candidate_id':'demo'},{'microstructure':lambda c:{'status':'partial','payload':{'candidate_id':c['candidate_id']}},'onchain':fail})
  self.assertEqual(result['microstructure']['payload']['candidate_id'],'demo'); self.assertEqual(result['onchain']['status'],'failed'); self.assertEqual(result['fundamentals']['status'],'unavailable'); self.assertEqual(len(result),5)
 def test_source_failure_is_explicit(self):
  with tempfile.TemporaryDirectory() as d:
   with patch.object(history,'get',return_value=(None,{'status':'unavailable','error_type':'TimeoutError'})):
    result=history.fetch(1,'0x'+'ab'*20,pathlib.Path(d)); self.assertEqual(result['state'],'unavailable'); self.assertIsNone(result['history'])
 def test_malformed_history_is_unavailable(self):
  token='0x'+'ab'*20; other='0x'+'cd'*20; pool='0x'+'ef'*20; doc={'data':[{'attributes':{'address':pool},'relationships':{'base_token':{'data':{'id':'eth_'+token}},'quote_token':{'data':{'id':'eth_'+other}}}}]}
  with tempfile.TemporaryDirectory() as d:
   with patch.object(history,'get',side_effect=[(doc,{'status':'ok'}),({'data':{}},{'status':'ok'})]):
    result=history.fetch(1,token,pathlib.Path(d)); self.assertEqual(result['state'],'unavailable'); self.assertIn('invalid',result['error'])
 def test_unsafe_asset_names(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d)
   for p in ('../a','x?y','x#y','%2e%2e/x','a\\b'):
    with self.assertRaises(ValueError): contract_validate.safe(root,p)
if __name__=='__main__': unittest.main(verbosity=2)
