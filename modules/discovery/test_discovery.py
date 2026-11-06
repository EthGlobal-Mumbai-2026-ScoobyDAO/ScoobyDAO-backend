import json, os, sqlite3, tempfile, unittest
from pathlib import Path
import discovery as d
try:
    import jsonschema
except ImportError:
    jsonschema = None
ROOT=Path(__file__).resolve().parent
class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'state.sqlite'; self.db=d.connect(self.path); self.adapter=d.FixtureAdapter(ROOT/'fixtures.json')
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def runfeed(self,**kw): return d.run(self.db,'test',self.adapter,kw.get('budget',100),3600)
    def test_replay_selection_restart_and_resurfacing(self):
        self.assertEqual(self.runfeed(budget=2)['status'],'backpressure')
        self.db.close(); self.db=d.connect(self.path)
        self.assertEqual(self.runfeed()['processed'],4)
        rows=self.db.execute('SELECT id,record FROM candidates ORDER BY id').fetchall(); self.assertEqual(len(rows),2)
        self.assertEqual(len(self.db.execute('SELECT * FROM events').fetchall()),5)
        result=dict(self.db.execute('SELECT event_id,outcome FROM events'))
        self.assertEqual(result['change-one'],'resurfaced'); self.assertEqual(result['change-suppressed'],'recorded'); self.assertEqual(result['change-after-cooldown'],'resurfaced')
        shib=next(k for k,_ in rows if k.startswith('1:')); base=next(k for k,_ in rows if k.startswith('8453:'))
        self.assertEqual(json.loads(dict(rows)[base])['identity']['symbol'],'TEST')
        d.action(self.db,shib,'select','TEST OPERATOR','synthetic test action')
        self.assertEqual(json.loads(self.db.execute('SELECT record FROM candidates WHERE id=?',(base,)).fetchone()[0])['selection']['status'],'not_selected')
        self.assertEqual(self.runfeed()['status'],'no_new_candidates')
        self.assertEqual(d.run(self.db,'test',d.FixtureAdapter(ROOT/'fixtures.json',True),100,3600)['status'],'feed_down')
        self.assertEqual(self.runfeed()['status'],'no_new_candidates')
        self.db.close(); self.db=d.connect(self.path)
        self.assertEqual(json.loads(self.db.execute('SELECT record FROM candidates WHERE id=?',(shib,)).fetchone()[0])['selection']['status'],'selected')
    def test_defer_and_validation(self):
        self.runfeed(); key=self.db.execute("SELECT id FROM candidates WHERE id LIKE '8453:%'").fetchone()[0]
        r=d.action(self.db,key,'defer','TEST OPERATOR','test deferral'); self.assertEqual(r['state'],'monitoring')
        with self.assertRaises(ValueError): d.action(self.db,key,'select',' ','reason')
        with self.assertRaises(ValueError): d.identity(1,'0xdead')
        self.assertIsNone(r['screening']['score'])
    @unittest.skipIf(jsonschema is None or not os.environ.get('SCOOBY_CANDIDATE_SCHEMA'),'jsonschema or SCOOBY_CANDIDATE_SCHEMA not configured')
    def test_export_schema(self):
        self.runfeed(); key=self.db.execute("SELECT id FROM candidates WHERE id LIKE '1:%'").fetchone()[0]; selected=d.action(self.db,key,'select','TEST OPERATOR','test selection')
        schema=json.loads(Path(os.environ['SCOOBY_CANDIDATE_SCHEMA']).read_text(encoding='utf-8-sig')); jsonschema.Draft202012Validator.check_schema(schema)
        for row in self.db.execute('SELECT record FROM candidates'): jsonschema.Draft202012Validator(schema).validate(json.loads(row[0]))
        jsonschema.Draft202012Validator(schema).validate(selected)
    def test_conflicting_event_id_stops_checkpoint(self):
        fixture=json.loads((ROOT/'fixtures.json').read_text()); fixture['events'][1]['observed_at']='2025-09-27T00:01:00Z'
        path=Path(self.tmp.name)/'bad.json'; path.write_text(json.dumps(fixture)); result=d.run(self.db,'bad',d.FixtureAdapter(path),100,3600)
        self.assertEqual(result['status'],'invalid_event'); self.assertEqual(result['cursor'],1)
if __name__=='__main__': unittest.main(verbosity=2)
