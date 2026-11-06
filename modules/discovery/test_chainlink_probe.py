import importlib.util,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
if importlib.util.find_spec('Crypto'):
 import chainlink_probe as p
else:
 p=None
@unittest.skipIf(p is None,'pycryptodome not installed')
class ChainlinkProbeTests(unittest.TestCase):
 def test_ens_namehash_and_words(self):
  self.assertEqual(p.namehash('eth'),'93cdeb708b7545dc668eb9280176169d1c33cfd8ed6f04690a0bcc88a93fc4ae')
  self.assertEqual(p.words('0x'+format(123,'064x')),[123])
  with self.assertRaises(ValueError): p.words('0x1')
 def test_rejects_wrong_resolved_description(self):
  def word(x):return format(x,'064x')
  def fake_call(url,method,params):
   if method=='eth_chainId':return {'status':'ok','result':'0x1'}
   if method=='eth_getBlockByNumber':return {'status':'ok','result':{'number':'0x1','timestamp':'0x20','hash':'0xa'}}
   data=params[0]['data']
   if data.startswith('0x3b3b57de'):return {'status':'ok','result':'0x'+word(123)}
   if data=='0x7284e416':
    text=b'WRONG / USD';return {'status':'ok','result':'0x'+word(32)+word(len(text))+text.hex().ljust(64,'0')}
   raise AssertionError('unexpected RPC call')
  with tempfile.TemporaryDirectory() as d:
   with patch.object(sys,'argv',['chainlink_probe.py','--output',str(Path(d)/'out.json')]),patch.object(p.rpc_snapshot,'call',side_effect=fake_call),patch('sys.stdout',new_callable=io.StringIO):
    with self.assertRaisesRegex(ValueError,'description'):p.main()
if __name__=='__main__':unittest.main(verbosity=2)
