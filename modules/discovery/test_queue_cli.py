import json,subprocess,sys,tempfile,unittest
from pathlib import Path
class QueueCliTests(unittest.TestCase):
 def test_bounded_scan_renders_empty_queue_without_calls(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);cmd=[sys.executable,str(Path(__file__).with_name('live_pilot.py')),'--db',str(root/'db.sqlite'),'--output',str(root),'--budget','0']
   p=subprocess.run(cmd,text=True,capture_output=True,encoding='utf-8',check=True)
   summary=json.loads(p.stdout);self.assertEqual(summary['calls'],0);self.assertEqual(summary['qualified'],0)
   q=json.loads((root/'review-queue.json').read_text());self.assertEqual(q['metric_verifiers_enabled'],2)
   self.assertIn('No candidates have passed the gate',(root/'review-queue.html').read_text())
 def test_no_selection_bypasses_queue(self):
  with tempfile.TemporaryDirectory() as tmp:
   import discovery
   root=Path(tmp);db=root/'db.sqlite';discovery.connect(db).close()
   cmd=[sys.executable,str(Path(__file__).with_name('review_queue.py')),'--db',str(db),'--root',str(root),'select','--candidate-id','1:0x'+'a'*40,'--actor','test','--reason','test']
   p=subprocess.run(cmd,text=True,capture_output=True,encoding='utf-8');self.assertEqual(p.returncode,1);self.assertIn('not currently eligible',p.stderr)
if __name__=='__main__':unittest.main(verbosity=2)
