import json, sqlite3, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import live_pilot as p
class GateTests(unittest.TestCase):
 def test_gate_counts_groups_only_and_holds_unverified(self):
  def item(flag=True): return {'verification':'verified','evidence_ids':['test-evidence'],'triggered':flag}
  four={g:item() for g in ('G01','G02','G03','G04')}; result=p.evaluate(four)
  self.assertEqual(result['triggered_groups'],4);self.assertTrue(result['eligible']);self.assertEqual(result['priority'],'standard')
  four['G05']=item();four['G06']=item();result=p.evaluate(four)
  self.assertEqual(result['triggered_groups'],5);self.assertEqual(result['groups']['G06'],'held');self.assertEqual(result['priority'],'higher')
  self.assertEqual(p.evaluate({'G01':{'triggered':True,'verification':'provider_hint','evidence_ids':['x']}})['triggered_groups'],0)
  self.assertEqual(p.evaluate({'G01':{'triggered':1,'verification':'verified','evidence_ids':['x']}})['groups']['G01'],'unknown')
 def test_live_capture_retains_leads_without_counting_hints(self):
  addr='0x'+'a'*40;pool='0x'+'b'*40
  class Fake:
   def __init__(self,root,budget):self.calls=0;self.budget=budget
   def get(self,url):
    if self.calls>=self.budget: raise p.BudgetExhausted('budget')
    self.calls+=1
    data=({'data':[{'attributes':{'name':'TEST / WETH','address':pool,'pool_created_at':'2026-01-01T00:00:00Z'},'relationships':{'base_token':{'data':{'id':'eth_'+addr}}}}]} if 'new_pools' in url else [{'priceUsd':'1'}] if 'dexscreener' in url else {'code':1,'result':{addr:{'is_honeypot':'1'}}})
    eid=str(self.calls)*64
    evidence={'id':eid,'source':'snapshots/'+eid+'.json','sha256':eid,'observed_at':None,'fetched_at':'2026-01-01T00:00:00Z','block_number':None,'kind':'live_observation','limitations':['synthetic test']}
    return data,evidence,{'status':'ok'}
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);db=root/'state.sqlite'
   with patch.object(p,'Fetcher',Fake): r=p.run(db,root,2,3,['ethereum'])
   self.assertIsNone(r['qualified_candidates']);self.assertEqual(len(r['leads']),1)
   c=sqlite3.connect(db); record=json.loads(c.execute('SELECT record FROM candidates').fetchone()[0]); findings=c.execute('SELECT status FROM pilot_findings').fetchall()
   self.assertEqual(record['state'],'monitoring');self.assertEqual(record['selection']['status'],'not_selected');self.assertIsNone(record['screening']['score'])
   self.assertTrue(all(row[0] in ('unknown','held') for row in findings));c.close()
 def test_validates_pool_ids_and_excludes_native(self):
  d={'data':[{'attributes':{'name':'ETH / foo','address':'0x'+'a'*64},'relationships':{'base_token':{'data':{'id':'base_0x0000000000000000000000000000000000000000'}}}}]}
  self.assertEqual(p.extract_leads('base',d,2),[])
if __name__=='__main__':unittest.main(verbosity=2)
