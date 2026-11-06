import io,json,sqlite3,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch
import rpc_snapshot,discovery
class RpcTest(unittest.TestCase):
 def test_empty_code_is_retained_and_fails_closed(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp); db=root/'db'; con=discovery.connect(db)
   address='0x'+'a'*40; key='1:'+address
   candidate={'identity':{'chain_id':1,'address':address},'candidate_id':key,'evidence':[],'last_observed_at':None}
   with con:con.execute('INSERT INTO candidates VALUES(?,?,?)',(key,json.dumps(candidate),None))
   con.close()
   def call(url,method,params):
    if method=='eth_chainId':return {'status':'ok','result':'0x1'}
    if method=='eth_getBlockByNumber':return {'status':'ok','result':{'number':'0x1','timestamp':'0x1','hash':'0x123'}}
    if method=='eth_getCode':return {'status':'ok','result':'0x'}
    return {'status':'rpc_error','error':'unknown'}
   args=['rpc_snapshot.py','--db',str(db),'--output',str(root),'--candidate-id',key]
   with patch.object(sys,'argv',args),patch.object(rpc_snapshot,'call',side_effect=call),patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(rpc_snapshot.main(),1)
   con=sqlite3.connect(db); saved=json.loads(con.execute('SELECT record FROM candidates').fetchone()[0]);con.close()
   self.assertEqual(len(saved['evidence']),1)
   blob=json.loads((root/saved['evidence'][0]['source']).read_text());self.assertIn('No contract code confirmed',blob['limitations'][-1]);self.assertEqual(blob['calls']['owner']['status'],'rpc_error')
if __name__=='__main__':unittest.main(verbosity=2)
