import json,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
import discovery
class LiveSelectionTests(unittest.TestCase):
 def test_old_cli_cannot_select_unverified_live_candidate(self):
  with tempfile.TemporaryDirectory() as td:
   db=Path(td)/'test.sqlite'; con=discovery.connect(db);cid='1:0x'+'a'*40
   record={'mode':'live','state':'monitoring','selection':{'status':'not_selected'}}
   with con:con.execute('INSERT INTO candidates VALUES(?,?,?)',(cid,json.dumps(record),None))
   con.close()
   result=subprocess.run([sys.executable,str(Path(discovery.__file__)),'--db',str(db),'select',cid,'--actor','TEST','--reason','test'],capture_output=True,text=True)
   self.assertNotEqual(result.returncode,0);self.assertIn('verified review queue',result.stderr)
   con=sqlite3.connect(db);saved=json.loads(con.execute('SELECT record FROM candidates').fetchone()[0]);con.close();self.assertEqual(saved['selection']['status'],'not_selected')
if __name__=='__main__':unittest.main(verbosity=2)
