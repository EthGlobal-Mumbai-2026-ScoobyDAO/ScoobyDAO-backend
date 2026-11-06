import copy,json,os,unittest
from pathlib import Path
try: import candidate_validation as cv
except ImportError: cv=None
@unittest.skipIf(cv is None or not os.environ.get('SCOOBY_CANDIDATE_SCHEMA'),'jsonschema or shared schema not configured')
class CandidateValidationTests(unittest.TestCase):
 def test_identity_gate_and_null_scoring(self):
  schema=json.loads(Path(os.environ['SCOOBY_CANDIDATE_SCHEMA']).read_text(encoding='utf-8-sig'));fixture=json.loads(Path(__file__).with_name('fixtures.json').read_text())['events'][0]['candidate']
  self.assertTrue(cv.validate(fixture,schema))
  with self.assertRaises(ValueError):cv.validate(fixture,schema,selected=True)
  broken=copy.deepcopy(fixture);broken['candidate_id']='8453:'+broken['identity']['address']
  with self.assertRaises(ValueError):cv.validate(broken,schema)
  broken=copy.deepcopy(fixture);broken['screening']['score']=42
  with self.assertRaises(ValueError):cv.validate(broken,schema)
if __name__=='__main__':unittest.main(verbosity=2)
