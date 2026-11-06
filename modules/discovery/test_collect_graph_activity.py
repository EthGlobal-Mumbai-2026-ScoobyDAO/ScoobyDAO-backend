import datetime as dt,json,os,sys,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
import collect_graph_activity as cli

class Response:
 status=200
 def __init__(self,data):self.data=json.dumps(data).encode()
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def read(self,n):return self.data

class Opener:
 def __init__(self,fail=False):self.calls=[];self.fail=fail
 def open(self,req,timeout):
  self.calls.append(req.full_url)
  if self.fail:raise urllib.error.HTTPError(req.full_url,429,'limited',{},None)
  now=dt.datetime.now(dt.timezone.utc)
  if req.data:
   v=json.loads(req.data)['variables'];rows=[{'periodStartUnix':t,'token':{'id':v['token']},'volumeUSD':'2000'} for t in range(v['start'],v['end'],3600)]
   return Response({'data':{'_meta':{'deployment':'synthetic','hasIndexingErrors':False,'block':{'number':1,'timestamp':int(now.timestamp())}},'tokenHourDatas':rows}})
  return Response({'base':'USD','quote':'INR','date':(now.date()-dt.timedelta(days=1)).isoformat(),'rate':100})

class CollectorTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.out=Path(self.tmp.name)/'capture';self.argv=['collect','--candidate-id','1:0x'+'a'*40,'--output',str(self.out)]
 def test_one_request_per_source_and_no_key_in_artifacts(self):
  op=Opener()
  with patch.object(sys,'argv',self.argv),patch.dict(os.environ,{'THE_GRAPH_API_KEY':'synthetic-secret'},clear=False),patch('urllib.request.build_opener',return_value=op):self.assertEqual(cli.main(),0)
  self.assertEqual(len(op.calls),2);self.assertEqual(json.loads((self.out/'activity.json').read_bytes())['status'],'pass')
  for path in self.out.iterdir():self.assertNotIn(b'synthetic-secret',path.read_bytes())
 def test_429_stops_without_fx_or_retry(self):
  op=Opener(True)
  with patch.object(sys,'argv',self.argv),patch.dict(os.environ,{'THE_GRAPH_API_KEY':'synthetic-secret'},clear=False),patch('urllib.request.build_opener',return_value=op):self.assertEqual(cli.main(),1)
  self.assertEqual(len(op.calls),1);self.assertEqual(json.loads((self.out/'capture-status.json').read_bytes())['requests'][0]['http_status'],429)
 def test_existing_output_is_not_overwritten(self):
  self.out.mkdir();op=Opener()
  with patch.object(sys,'argv',self.argv),patch.dict(os.environ,{'THE_GRAPH_API_KEY':'synthetic-secret'},clear=False),patch('urllib.request.build_opener',return_value=op):
   with self.assertRaises(FileExistsError):cli.main()
  self.assertEqual(op.calls,[])

if __name__=='__main__':unittest.main()
