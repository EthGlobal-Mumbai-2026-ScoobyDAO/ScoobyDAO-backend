import copy,json,pathlib,tempfile,shutil,unittest
from jsonschema.exceptions import ValidationError
from modules.investigation.reasoning_v2 import validator
R=pathlib.Path(__file__).parent/'fixtures'/'reasoning_v2'
class Tests(unittest.TestCase):
 def setUp(self):self.report,self.model=validator.validate_bundle(R/'v2');self.side=json.loads((R/'v2/reasoning.json').read_text(encoding='utf8'))
 def test_uses_frozen_report_schema(self):
  project=pathlib.Path(__file__).resolve().parent.parent;self.assertEqual(validator.cv.SCHEMA.resolve(),(project/'schemas/report.schema.json').resolve())
 def test_valid_v2(self):self.assertEqual(self.model['conclusion']['recommendation']['action'],'SYNTHETIC TEST ONLY: defer the fictional interaction.')
 def test_v1_explicitly_handed_to_v1_consumer(self):
  old=json.loads((R/'v1/reasoning.json').read_text(encoding='utf8'))
  with self.assertRaises(ValueError):validator.validate(self.report,old)
 def test_negatives(self):
  for name,edit in [('unsupported',lambda x:x.update(profile='scooby.reasoning/999')),('identity',lambda x:x.update(candidate_id='bad')),('missing_action',lambda x:x['reasoning']['conclusion']['recommendation'].pop('action')),('blank_action',lambda x:x['reasoning']['conclusion']['recommendation'].update(action=' ')),('blank_rationale',lambda x:x['reasoning']['conclusion']['recommendation']['rationale'].update(text=' ')),('blank_reversal',lambda x:x['reasoning']['conclusion']['recommendation'].update(reversal_conditions=[' '])),('unrelated_source',lambda x:x['reasoning']['conclusion']['recommendation']['rationale'].update(evidence_ids=['test-c'])),('unresolved',lambda x:x['reasoning']['conclusion']['recommendation']['counterevidence'][0].update(evidence_ids=['missing']))]:
   with self.subTest(case=name):
    side=copy.deepcopy(self.side);edit(side)
    with self.assertRaises((ValueError,ValidationError)):validator.validate(self.report,side)
 def test_stale_hash_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   dest=pathlib.Path(t)/'bundle';shutil.copytree(R/'v2',dest);p=dest/'reasoning.json';p.write_text(p.read_text(encoding='utf8')+' ',encoding='utf8')
   with self.assertRaises(ValueError):validator.validate_bundle(dest)
if __name__=='__main__':unittest.main(verbosity=2)
