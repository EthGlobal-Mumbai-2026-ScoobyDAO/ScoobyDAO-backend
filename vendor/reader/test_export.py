import unittest,importlib.util,pathlib,tempfile,json,hashlib
P=pathlib.Path(__file__).resolve().parent;s=importlib.util.spec_from_file_location('reader',P/'build.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class ExportTests(unittest.TestCase):
 def test_path_rejections(self):
  with tempfile.TemporaryDirectory() as t:
   p=pathlib.Path(t)
   for x in ['../x','%2e%2e/x','/abs','C:/x','a?x','a#x','a\\b','']:
    with self.subTest(x=x),self.assertRaises(ValueError):m.safe(p,x)
 def test_valid_bundle_and_tamper(self):
  with tempfile.TemporaryDirectory() as t:
   root=pathlib.Path(t)/'in';root.mkdir(); address='0x'+'1'*40; names=['microstructure','onchain','fundamentals','statistical_risk','technical_health'];(root/'source.json').write_text('{"test":true}',encoding='utf-8');sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
   ev={'id':'e','path':'source.json','sha256':sha(root/'source.json'),'kind':'synthetic','observed_at':None,'fetched_at':None,'block_number':None,'window':{'start':None,'end':None,'precision':None},'coverage':'unknown','limitations':[]}
   pillar={'status':'unavailable','summary':'No source data.','evidence_ids':[],'measurements':[],'series':[],'claims':[],'quality_issues':[],'raw_payload_path':None}
   report={'schema_version':'0.2','report_id':'test','report_version':'v1','candidate_id':'1:'+address,'identity':{'chain_id':1,'address':address,'symbol':'TEST'},'mode':'synthetic_demo','assessment':{'status':'not_assessed','label':None,'summary':'Synthetic test only','unknowns':[],'supporting_claim_ids':[],'counterevidence_claim_ids':[]},'pillars':{n:dict(pillar) for n in names},'evidence':[ev],'artifacts':[],'review':{'status':'pending','reviewer':None,'reviewed_at':None,'reviewed_version':None,'content_sha256':None,'authentication':'none'},'limitations':[]}
   side={'profile':'scooby.pillar-tldr/1','report_id':'test','report_version':'v1','pillars':{n:[{'role':'caveat','text':'<script>not executable</script>','claim_ids':[],'evidence_ids':['e']}] for n in names}};(root/'tldr.json').write_text(json.dumps(side),encoding='utf-8');report['artifacts'].append({'kind':'pillar_tldr','availability':'available','path':'tldr.json','sha256':sha(root/'tldr.json'),'report_id':'test','report_version':'v1','media_type':'application/json'})
   f=root/'report.json';f.write_text(json.dumps(report),encoding='utf-8');(root/'digest.json').write_text(json.dumps({'algorithm':'sha256','target':'report.json exact UTF-8 bytes','sha256':sha(f)}),encoding='utf-8');m.build(f,pathlib.Path(t)/'out');html=(pathlib.Path(t)/'out/index.html').read_text(encoding='utf-8');self.assertNotIn('<script>not executable</script>',html);self.assertIn('\\u003cscript',html);(root/'source.json').write_text('{}');
   with self.assertRaisesRegex(ValueError,'hash mismatch'):m.build(f,pathlib.Path(t)/'bad')
if __name__=='__main__':unittest.main()

