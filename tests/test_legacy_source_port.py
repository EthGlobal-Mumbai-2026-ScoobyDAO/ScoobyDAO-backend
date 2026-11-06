import ast,json,pathlib,unittest,hashlib,os
from modules.investigation.legacy_source_port import producer,normalizers,adapters
from modules.investigation.legacy_source_port.adapters import *
ROOT=pathlib.Path(adapters.__file__).parent
load=lambda name:json.loads((ROOT/'fixtures'/name).read_text(encoding='utf8'))
class LegacySourceTests(unittest.TestCase):
 def test_synthetic_market_score_and_mev(self):
  raw=load('market.json');r=replay_market(raw)['payload'];self.assertEqual(r['microstructure_score'],raw['microstructure_score']);self.assertEqual(r['mevExposure'],raw['mevExposure'])
 def test_synthetic_control_score(self):
  raw=load('onchain.json');self.assertEqual(replay_control_score(raw)['payload']['legacy_summary'],raw['summary'])
 def test_zero_liquidity_slippage_anomaly_reproduced(self):
  raw=load('market.json');v=raw['venues'][0]
  r=v3_from_captured_state({'state':{'sqrtP':int(v['sqrtPriceX96']),'tick':v['tick'],'L':int(v['liquidity']),'fee':v['feeBps'],'decimals0':18,'decimals1':6},'ticks':[{'tick':v['tick'],'liquidityNet':0,'liquidityGross':0}],'ticks_complete':True,'trade_sizes_quote':[p['notionalQuote'] for p in v['slippageCurve']]})['payload']
  self.assertEqual(r['slippageCurve'],v['slippageCurve']);self.assertTrue(all(x==0 for d in r['depth_quote'].values() for x in d.values()));self.assertEqual(r['activeLiquidityRatio'],v['activeLiquidityRatio'])
 def test_missing_ticks_not_zero_depth(self):
  self.assertEqual(v3_from_captured_state({'state':{},'ticks_complete':False})['status'],'unavailable')
 def test_lp_empty_distinguished_from_failure(self):
  self.assertEqual(lp_from_captured_positions([],False)['status'],'unavailable');r=lp_from_captured_positions([],True)['payload']['legacy_lpConcentration'];self.assertEqual(r,{'top1Share':0.0,'top5Share':0.0,'hhi':0.0,'sampledPositions':0.0})
 def test_lp_owner_aggregation_original_definition(self):
  p=[{'id':'1','owner':'a','liquidity':'50'},{'id':'2','owner':'a','liquidity':'25'},{'id':'3','owner':'b','liquidity':'25'}];r=lp_from_captured_positions(p,True)['payload']['legacy_lpConcentration'];self.assertEqual(r,{'top1Share':0.75,'top5Share':1.0,'hhi':0.625,'sampledPositions':2.0})
 def test_lock_threshold_and_missing_balance(self):
  p={'pair':'pair','total_supply':'1000','known_lockers':['locker'],'dead_addresses':['dead'],'balances':{'locker':'400','dead':'100'},'complete':True};r=lock_from_captured_balances(p)['payload']['legacy_lock_result'];self.assertEqual(r,{'lpLocked':True,'lockEvidence':{'lockerBalance':'400','deadAddressBalance':'100','pctLocked':50.0}});del p['balances']['dead'];self.assertEqual(lock_from_captured_balances(p)['status'],'unavailable')
 def test_control_missing_fields_dont_become_green(self):
  raw=load('onchain.json');del raw['facts']['liquidity'];self.assertEqual(replay_control_score(raw)['status'],'unavailable')
 def test_nested_missing_control_state_is_unavailable(self):
  raw=load('onchain.json');del raw['facts']['multisig']['isSafe'];self.assertEqual(replay_control_score(raw)['status'],'unavailable')
 def test_fundamental_ticker_not_contract_attribution(self):
  self.assertEqual(fundamentals_from_capture(load('fundamentals.json'),None)['status'],'unavailable')
 def test_fundamental_preserves_structured_fields_excludes_prose(self):
  raw=load('fundamentals.json');r=fundamentals_from_capture(raw,{'status':'evidence_bound','candidate_id':'test-only','evidence_ids':['fixture']})['payload'];self.assertEqual(r['legacy_structured_fields']['market_data'],raw['market_data']);self.assertNotIn('reddit_sentiment',r['legacy_structured_fields'])
 def test_captured_abi_privileges_and_unknown_pause(self):
  r=privileges_from_captured_source([{'type':'function','name':'setBlacklist'}],None,None)['payload']['legacy_privileged_facts'];self.assertEqual(r['pauseStatus'],'unknown');self.assertEqual(r['blacklistPrimitives'],['setBlacklist'])
  self.assertEqual(privileges_from_captured_source(None,None,None)['status'],'unavailable')
 def test_source_keyword_heuristic_retained_as_heuristic(self):
  r=privileges_from_captured_source([], '// blacklist is only a comment', 'unpaused')['payload']['legacy_privileged_facts'];self.assertIn('blacklist',r['blacklistPrimitives'])
 def test_bound_five_pillar_boundary_and_missing_sources(self):
  candidate='1:0x'+'1'*40;records={}
  for name,file in [('microstructure','market.json'),('onchain','onchain.json'),('fundamentals','fundamentals.json')]:
   records[name]={'id':'fixture-'+name,'path':file,'candidate_id':candidate,'sha256':hashlib.sha256((ROOT/'fixtures'/file).read_bytes()).hexdigest()}
  results=producer.run_captured({'candidate_id':candidate},ROOT/'fixtures',records)
  self.assertEqual(results['microstructure']['payload']['microstructure_score'],7);self.assertEqual(results['onchain']['payload']['legacy_summary']['fundamentals_score'],85)
  self.assertTrue(all(results[k]['status']=='unavailable' for k in ('fundamentals','statistical_risk','technical_health')))
  records['microstructure']['sha256']='0'*64
  with self.assertRaises(ValueError):producer.run_captured({'candidate_id':candidate},ROOT/'fixtures',records)
 def test_wrong_capture_candidate_rejected(self):
  with self.assertRaises(ValueError):producer.load_capture(ROOT/'fixtures',{'path':'market.json','candidate_id':'wrong','sha256':'0'*64},'expected')
 def test_raw_rpc_lock_normalization_missing_is_not_zero(self):
  block='block-hash';rec=lambda n:{'state':'captured','block_hash':block,'response':{'result':'0x'+format(n,'064x')}}
  data=normalizers.v2_lock_capture({'totalSupply':rec(1000),'balances':{'locker':rec(500)}},block,'pair',['locker'],['dead'])
  self.assertFalse(data['complete']);self.assertEqual(lock_from_captured_balances(data)['status'],'unavailable')
  data=normalizers.v2_lock_capture({'totalSupply':rec(1000),'balances':{'locker':rec(500),'dead':rec(0)}},block,'pair',['locker'],['dead'])
  self.assertTrue(lock_from_captured_balances(data)['payload']['legacy_lock_result']['lpLocked'])
 def test_graph_error_and_pagination_not_empty_owners(self):
  p={'state':'captured','pool':'pool','block_hash':'block','response':{'errors':['failed']},'terminal_page':True}
  self.assertFalse(normalizers.graph_positions([p],'block','pool')['complete'])
  p['response']={'data':{'positions':[],'_meta':{'block':{'hash':'block'}}}};p['skip']=0;p['page_size']=1000;self.assertTrue(normalizers.graph_positions([p],'block','pool')['complete'])
  p['terminal_page']=False;self.assertFalse(normalizers.graph_positions([p],'block','pool')['complete'])
 def test_exported_definitions_match_original_ast(self):
  original=pathlib.Path(os.environ.get('SCOOBY_LEGACY_AGENTS_DIR','/__legacy_not_configured__'))
  if not original.exists():self.skipTest('optional original checkout not configured; synthetic parity only')
  manifest=json.loads((ROOT/'SOURCE-MANIFEST.json').read_text(encoding='utf8'))
  for rec in manifest:
   source=ast.parse((original/rec['source']).read_text(encoding='utf8'));port=ast.parse((ROOT/rec['target']).read_text(encoding='utf8'));s={n.name:ast.dump(n,include_attributes=False) for n in source.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))};p={n.name:ast.dump(n,include_attributes=False) for n in port.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
   for name in rec['definitions']:self.assertEqual(s[name],p[name],rec['source']+':'+name)
if __name__=='__main__':unittest.main(verbosity=2)
