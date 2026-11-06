import datetime as dt,hashlib,json,tempfile,unittest
from pathlib import Path
import market_activity as m
import review_queue
class MarketTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'snapshots').mkdir();self.token='0x'+'a'*40;self.pool='0x'+'b'*40;self.asof=dt.datetime.fromtimestamp(200000,dt.timezone.utc)
 def tearDown(self):self.tmp.cleanup()
 def point(self,block,ts,reserves):
  tag=hex(block);pool=self.pool;pair='0xe6a43905'+self.token[2:].rjust(64,'0')+m.WETH[2:].rjust(64,'0')
  word=lambda x:format(x,'064x')
  def call(to,data,result):return {'to':to,'data':data,'block':tag,'result':result}
  d={'token0':call(pool,'0x0dfe1681','0x'+word(int(self.token,16))),'token1':call(pool,'0xd21220a7','0x'+word(int(m.WETH,16))),'factory':call(pool,'0xc45a0155','0x'+word(int(m.FACTORY,16))),'factory_pair':call(m.FACTORY,pair,'0x'+word(int(pool,16))),'reserves':call(pool,'0x0902f1ac','0x'+''.join(word(x) for x in (reserves[0],reserves[1],ts-10))),'feed_decimals':call(m.FEED,'0x313ce567','0x'+word(8)),'feed_round':call(m.FEED,'0xfeaf968c','0x'+''.join(word(x) for x in (1,2000*10**8,ts-10,ts-10,1)))}
  return {'block_tag':tag,'block_timestamp':ts,'block_hash':'0x'+'c'*64,'finality':'finalized','calls':d}
 def fixture(self):
  prior=self.point(10,100000,(100,100));latest=self.point(20,186400,(100,125));doc={'format':'G09_V2_WETH_V1','chain_id':1,'source_kind':'rpc_capture','rpc_url':'https://ethereum-rpc.publicnode.com','candidate_id':'1:'+self.token,'pool':self.pool,'prior':prior,'latest':latest}
  trace=[]
  def add(method,params,result):
   n=len(trace)+1;trace.append({'request':{'jsonrpc':'2.0','id':n,'method':method,'params':params},'response':{'jsonrpc':'2.0','id':n,'result':result}})
  add('eth_chainId',[],'0x1')
  for point,tag in ((prior,prior['block_tag']),(latest,'finalized')):
   add('eth_getBlockByNumber',[tag,False],{'number':point['block_tag'],'timestamp':hex(point['block_timestamp']),'hash':point['block_hash']})
   for call in point['calls'].values():add('eth_call',[{'to':call['to'],'data':call['data']},point['block_tag']],call['result'])
  doc['rpc_trace']=trace
  raw=json.dumps(doc).encode();h=hashlib.sha256(raw).hexdigest();(self.root/'snapshots'/(h+'.json')).write_bytes(raw)
  e={'id':h,'sha256':h,'source':'snapshots/'+h+'.json','observed_at':dt.datetime.fromtimestamp(186400,dt.timezone.utc).isoformat(),'fetched_at':self.asof.isoformat(),'block_number':20,'limitations':['G09_V2_WETH_V1']}
  record={'candidate_id':'1:'+self.token,'identity':{'chain_id':1,'address':self.token},'evidence':[e]};return doc,record
 def test_trigger_from_finalized_validated_two_block_reserves(self):
  _,r=self.fixture();result=m.verify(r,self.root,self.asof);self.assertTrue(result['triggered']);self.assertEqual(result['measurements'][0]['value'],'25.0000')
  r.update(mode='live',selection={'status':'not_selected'});r['identity']['symbol']='TEST';r['evidence'][0]['kind']='live_observation'
  item=review_queue.assess(r,self.root,dt.datetime.fromtimestamp(186500,dt.timezone.utc))
  self.assertEqual(item['triggered_count'],1);self.assertFalse(item['eligible']);self.assertEqual(next(g for g in item['groups'] if g['id']=='G09')['status'],'triggered')
 def test_tampered_or_incomplete_history_never_votes(self):
  doc,r=self.fixture();doc['prior']['block_timestamp']=186000
  raw=json.dumps(doc).encode();h=hashlib.sha256(raw).hexdigest();(self.root/'snapshots'/(h+'.json')).write_bytes(raw);r['evidence'][0].update(id=h,sha256=h,source='snapshots/'+h+'.json')
  with self.assertRaisesRegex(ValueError,'24-25'):m.verify(r,self.root,self.asof)
 def test_factory_identity_is_required(self):
  doc,r=self.fixture();doc['latest']['calls']['factory_pair']['result']='0x'+'0'*64
  for entry in doc['rpc_trace']:
   if entry['request']['method']=='eth_call' and entry['request']['params'][0]['data']==doc['latest']['calls']['factory_pair']['data'] and entry['request']['params'][1]==doc['latest']['block_tag']:entry['response']['result']='0x'+'0'*64
  raw=json.dumps(doc).encode();h=hashlib.sha256(raw).hexdigest();(self.root/'snapshots'/(h+'.json')).write_bytes(raw);r['evidence'][0].update(id=h,sha256=h,source='snapshots/'+h+'.json')
  with self.assertRaisesRegex(ValueError,'recognize'):m.verify(r,self.root,self.asof)
 def test_value_not_in_rpc_transcript_never_votes(self):
  doc,r=self.fixture();doc['latest']['calls']['reserves']['result']='0x'+''.join(format(x,'064x') for x in (100,150,0))
  raw=json.dumps(doc).encode();h=hashlib.sha256(raw).hexdigest();(self.root/'snapshots'/(h+'.json')).write_bytes(raw);r['evidence'][0].update(id=h,sha256=h,source='snapshots/'+h+'.json')
  with self.assertRaisesRegex(ValueError,'transcript call mismatch'):m.verify(r,self.root,self.asof)
 def test_finalized_block_must_match_transcript(self):
  doc,r=self.fixture();doc['latest']['block_hash']='0x'+'d'*64
  raw=json.dumps(doc).encode();h=hashlib.sha256(raw).hexdigest();(self.root/'snapshots'/(h+'.json')).write_bytes(raw);r['evidence'][0].update(id=h,sha256=h,source='snapshots/'+h+'.json')
  with self.assertRaisesRegex(ValueError,'transcript block mismatch'):m.verify(r,self.root,self.asof)
 def test_below_threshold_price_does_not_clear_missing_volume_check(self):
  doc,r=self.fixture();call=doc['latest']['calls']['reserves'];call['result']='0x'+''.join(format(x,'064x') for x in (100,105,186390))
  for entry in doc['rpc_trace']:
   if entry['request']['method']=='eth_call' and entry['request']['params'][0]['data']==call['data'] and entry['request']['params'][1]==doc['latest']['block_tag']:entry['response']['result']=call['result']
  raw=json.dumps(doc).encode();h=hashlib.sha256(raw).hexdigest();(self.root/'snapshots'/(h+'.json')).write_bytes(raw);r['evidence'][0].update(id=h,sha256=h,source='snapshots/'+h+'.json')
  result=m.verify(r,self.root,self.asof);self.assertIsNone(result['triggered']);self.assertEqual(result['measurements'][0]['value'],'5.0000')
 def test_stale_reserves_do_not_vote(self):
  doc,r=self.fixture();call=doc['latest']['calls']['reserves'];call['result']='0x'+''.join(format(x,'064x') for x in (100,125,180000))
  for entry in doc['rpc_trace']:
   if entry['request']['method']=='eth_call' and entry['request']['params'][0]['data']==call['data'] and entry['request']['params'][1]==doc['latest']['block_tag']:entry['response']['result']=call['result']
  raw=json.dumps(doc).encode();h=hashlib.sha256(raw).hexdigest();(self.root/'snapshots'/(h+'.json')).write_bytes(raw);r['evidence'][0].update(id=h,sha256=h,source='snapshots/'+h+'.json')
  with self.assertRaisesRegex(ValueError,'reserves are stale'):m.verify(r,self.root,self.asof)
if __name__=='__main__':unittest.main(verbosity=2)
