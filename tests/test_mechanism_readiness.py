import copy,json,pathlib,tempfile,unittest
from modules.investigation import mechanism_evidence as m
ROOT=pathlib.Path(__file__).parent/'fixtures'/'mechanism-readiness'
class Controls(unittest.TestCase):
 def test_vectors(self):
  for name,status in m.read(ROOT/'expectations.json').items():
   with self.subTest(name=name):
    p=m.read(ROOT/(name+'.json'));r=m.evaluate(p,ROOT);self.assertEqual(r['status'],status);self.assertEqual(r['live_verdict'],'not_determined')
 def test_isolated_calls_not_coherent(self):
  p=m.read(ROOT/'repeated-restriction.json')
  for s in p['scenarios']:s['sequence_proof']['mode']='isolated_calls'
  self.assertEqual(m.evaluate(p,ROOT)['status'],'inconclusive')
 def test_forged_sequence_label_not_enough(self):
  p=m.read(ROOT/'repeated-restriction.json')
  for s in p['scenarios']:
   if s['direction']=='sell':s['pre_state_id']='unlinked-state'
  self.assertEqual(m.evaluate(p,ROOT)['status'],'inconclusive')
 def test_insufficient_acquired_balance_not_coherent(self):
  p=m.read(ROOT/'repeated-restriction.json')
  for s in p['scenarios']:
   if s['direction']=='sell':s['input_amount']='101'
  self.assertEqual(m.evaluate(p,ROOT)['status'],'inconclusive')
 def test_wrong_replication_or_asset_not_coherent(self):
  for field,value in [('replication_id','other-run'),('input_asset','1:0x'+'f'*40)]:
   p=m.read(ROOT/'repeated-restriction.json')
   for s in p['scenarios']:
    if s['direction']=='sell':s[field]=value
   self.assertEqual(m.evaluate(p,ROOT)['status'],'inconclusive')
 def test_mixed_block_rejected(self):
  p=m.read(ROOT/'known-sellable.json');p['scenarios'][0]['block_hash']='0x'+'b'*64
  with self.assertRaises(ValueError):m.evaluate(p,ROOT)
 def test_tampered_evidence_rejected(self):
  p=m.read(ROOT/'known-sellable.json');p['evidence'][0]['sha256']='0'*64
  with self.assertRaises(ValueError):m.evaluate(p,ROOT)
 def test_selection_is_required(self):
  path=ROOT/'known-sellable.json'
  with self.assertRaises(ValueError):m.producer(path,{})
  self.assertEqual(m.producer(path,{'candidate_id':m.read(path)['candidate_id'],'decision':'selected','record_id':'offline-selection'})['status'],'partial')
 def test_missing_controls_rejected(self):
  p=m.read(ROOT/'known-sellable.json');del p['scenarios'][0]['controls']['allowance']
  with self.assertRaises(ValueError):m.evaluate(p,ROOT)
 def test_no_reference_label_in_neutral_payload(self):
  p=m.read(ROOT/'known-sellable.json');p['expected_label']='HONEYPOT_EXPECTED';p['scenarios'][0]['expected_label']='HONEYPOT_EXPECTED';p['mechanism']['expected_label']='HONEYPOT_EXPECTED'
  self.assertNotIn('HONEYPOT_EXPECTED',json.dumps(m.neutral_payload(p)))
if __name__=='__main__':unittest.main(verbosity=2)
