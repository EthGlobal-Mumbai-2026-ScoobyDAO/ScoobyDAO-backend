import datetime as dt,hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
import discovery, review_queue as rq
class QueueTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'snapshots').mkdir();self.db=self.root/'db';self.asof=dt.datetime(2026,11,6,6,0,tzinfo=dt.timezone.utc)
  raw=b'{"synthetic":"test"}';self.digest=hashlib.sha256(raw).hexdigest();(self.root/'snapshots'/(self.digest+'.json')).write_bytes(raw)
  addr='0x'+'a'*40;self.key='1:'+addr
  self.record={'schema_version':'0.1','candidate_id':self.key,'identity':{'chain_id':1,'address':addr,'symbol':'<script>alert(1)</script>'},'mode':'live','state':'monitoring','selection':{'status':'not_selected','selected_by':None,'selected_at':None,'reason':None},'evidence':[{'id':self.digest,'source':'snapshots/'+self.digest+'.json','sha256':self.digest,'observed_at':self.asof.isoformat(),'kind':'live_observation'}]}
  db=discovery.connect(self.db)
  with db:db.execute('INSERT INTO candidates VALUES(?,?,?)',(self.key,json.dumps(self.record),None))
  db.close()
 def tearDown(self):self.tmp.cleanup()
 def verifiers(self,n):
  def f(record,root,asof):return {'triggered':True,'detail':'Test-only concern','measurements':[{'value':1,'unit':'test'}],'evidence_ids':[self.digest]}
  return {g:f for g in ['G01','G02','G03','G04','G05'][:n]}
 def test_only_four_or_more_verified_appear(self):
  self.assertEqual(rq.queue(self.db,self.root,self.asof,self.verifiers(3))['qualified_count'],0)
  q=rq.queue(self.db,self.root,self.asof,self.verifiers(4));self.assertEqual(q['qualified_count'],1);item=q['candidates'][0];self.assertEqual(item['triggered_count'],4);self.assertEqual(len(item['groups']),12)
  self.assertEqual(rq.queue(self.db,self.root,self.asof,self.verifiers(5))['candidates'][0]['priority'],'higher')
  page=rq.html_page(q);self.assertIn('&lt;script&gt;',page);self.assertNotIn('<script>alert',page);self.assertIn('snapshots/'+self.digest+'.json',page);self.assertIn('Value: 1 test',page);self.assertNotIn('{&quot;value&quot;',page)
 def test_top_five_does_not_discard_other_qualified_candidates(self):
  db=sqlite3.connect(self.db)
  for i in range(1,6):
   record=dict(self.record);address='0x'+format(i,'040x');record['identity']=dict(self.record['identity'],address=address);record['candidate_id']='1:'+address
   db.execute('INSERT INTO candidates VALUES(?,?,?)',(record['candidate_id'],json.dumps(record),None))
  db.commit();db.close()
  q=rq.queue(self.db,self.root,self.asof,self.verifiers(4))
  self.assertEqual(q['qualified_count'],6);self.assertEqual(q['shown_count'],5);self.assertEqual(len(q['candidates']),5);self.assertEqual(q['monitored_count'],6)
  db=sqlite3.connect(self.db);self.assertEqual(db.execute('SELECT count(*) FROM candidates').fetchone()[0],6);db.close()
 def test_provider_hints_and_database_status_never_qualify(self):
  q=rq.queue(self.db,self.root,self.asof);self.assertEqual(q['qualified_count'],0);self.assertEqual(q['monitored_count'],1)
  self.assertNotIn(self.key,rq.html_page(q));self.assertIn('not been evaluated',rq.html_page(q))
 def test_tampered_or_stale_evidence_fails_closed(self):
  path=self.root/'snapshots'/(self.digest+'.json');path.write_text('altered');self.assertEqual(rq.queue(self.db,self.root,self.asof,self.verifiers(4))['qualified_count'],0)
  path.write_bytes(b'{"synthetic":"test"}');later=self.asof+dt.timedelta(hours=2)
  self.assertEqual(rq.queue(self.db,self.root,later,self.verifiers(4))['qualified_count'],0)
if __name__=='__main__':unittest.main(verbosity=2)
