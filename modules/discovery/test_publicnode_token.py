import io,json,os,unittest,urllib.error
from unittest.mock import patch
import collect_market_activity as c
class Response:
 def __init__(self,obj):self.obj=obj
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def read(self,*args):return json.dumps(self.obj).encode()
class PublicNodeTokenTests(unittest.TestCase):
 @patch.object(c.time,'sleep')
 def test_path_token_not_in_trace(self,_):
  secret='synthetic token/?'
  class Opener:
   def open(self,request,timeout):
    self.url=request.full_url;return Response({'jsonrpc':'2.0','id':1,'result':'0x1'})
  opener=Opener()
  with patch.dict(os.environ,{'PUBLICNODE_TOKEN':secret}),patch.object(c.urllib.request,'build_opener',return_value=opener):
   rpc=c.RPC(2);self.assertEqual(rpc.call('eth_chainId',[]),'0x1');self.assertTrue(opener.url.startswith(c.URL+'/'));self.assertIn('%2F',opener.url);self.assertNotIn(secret,json.dumps(rpc.trace))
 @patch.object(c.time,'sleep')
 def test_http_failure_never_exposes_url_or_secret(self,_):
  secret='syntheticsecret'
  class Opener:
   def open(self,request,timeout):raise urllib.error.HTTPError(request.full_url,403,'forbidden',{},None)
  with patch.dict(os.environ,{'PUBLICNODE_TOKEN':secret}),patch.object(c.urllib.request,'build_opener',return_value=Opener()):
   with self.assertRaises(ValueError) as error:c.RPC(2).call('eth_chainId',[])
   self.assertEqual(str(error.exception),'PublicNode request failed with HTTP 403');self.assertNotIn(secret,str(error.exception))
 def test_redirect_not_followed(self):
  self.assertIsNone(c.NoRedirect().redirect_request(None,None,302,'Found',{},'https://example.com/'))
if __name__=='__main__':unittest.main(verbosity=2)
