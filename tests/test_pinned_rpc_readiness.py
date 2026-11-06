import json,pathlib,tempfile,unittest
from modules.investigation import pinned_rpc_capture as r
class RPCBoundary(unittest.TestCase):
 def setUp(self):
  self.plan={'candidate_id':'1:0x'+'1'*40,'block':{'number':123,'hash':'0x'+'a'*64},'operations':[{'method':'eth_getCode','params':['0x'+'1'*40,'0x7b']}]};self.sel={'candidate_id':self.plan['candidate_id'],'decision':'selected','record_id':'offline'};self.calls=[]
 def send(self,req):
  self.calls.append(req)
  value='0x1' if req['method']=='eth_chainId' else {'number':'0x7b','hash':'0x'+'a'*64} if req['method']=='eth_getBlockByNumber' else '0x6000'
  return json.dumps({'id':req['id'],'jsonrpc':'2.0','result':value}).encode()
 def test_capture(self):
  with tempfile.TemporaryDirectory() as t:
   result=r.capture(self.plan,self.sel,pathlib.Path(t)/'out',self.send,4);self.assertEqual(result['attempts'],4)
 def test_budget_and_broadcast_rejected_before_network(self):
  with tempfile.TemporaryDirectory() as t:
   for budget in (0,3):
    with self.assertRaises(ValueError):r.capture(self.plan,self.sel,pathlib.Path(t)/'out',self.send,budget)
   self.plan['operations'][0]['method']='eth_sendTransaction'
   with self.assertRaises(ValueError):r.capture(self.plan,self.sel,pathlib.Path(t)/'out',self.send,4)
  self.assertFalse(self.calls)
 def test_reorg_fails(self):
  self.plan['block']['hash']='0x'+'b'*64
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises(ValueError):r.capture(self.plan,self.sel,pathlib.Path(t)/'out',self.send,4)
if __name__=='__main__':unittest.main(verbosity=2)
