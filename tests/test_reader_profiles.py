import copy, hashlib, importlib.util, json, shutil
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('reader_builder', ROOT/'vendor/reader/build.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
def dump(path, obj): path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def bundle(tmp_path):
 root=tmp_path/'bundle';shutil.copytree(ROOT/'tests/historical-bundle',root);rp=root/'report.json';d=json.loads(rp.read_bytes());eid=d['evidence'][0]['id']
 data={'profile':'scooby.reasoning/2','candidate_id':d['candidate_id'],'report_id':d['report_id'],'report_version':d['report_version'],'reasoning':{'pillars':[{'name':k,'summary':'Synthetic fixture only','analysis':[]} for k in d['pillars']],'conclusion':{'summary':'Mocked test only','analysis':[],'recommendation':{'action':'Defer pending review','rationale':{'text':'Synthetic rationale','evidence_ids':[eid],'input_ids':[]},'counterevidence':[{'text':'Synthetic counterevidence','evidence_ids':[eid],'input_ids':[]}],'reversal_conditions':['New verified evidence']}}}}
 return root,d,data
def save(root,d,data):
 side=root/'reasoning.json';dump(side,data); d=copy.deepcopy(d);d['artifacts'].append({'kind':'reasoning','media_type':'application/json','availability':'available','path':'reasoning.json','sha256':hashlib.sha256(side.read_bytes()).hexdigest(),'report_id':d['report_id'],'report_version':d['report_version']});rp=root/'report.json';dump(rp,d);dg=json.loads((root/'digest.json').read_bytes());dg['sha256']=hashlib.sha256(rp.read_bytes()).hexdigest();dump(root/'digest.json',dg);return rp
def test_v2_supported_and_unresolved_recommendation_rejected(tmp_path):
 root,d,data=bundle(tmp_path);report=save(root,d,data);out=tmp_path/'out';builder.build(report,out);html=(out/'index.html').read_text(encoding='utf-8');assert 'Defer pending review' in html and 'Proposed action (pending review)' in html
 data['reasoning']['conclusion']['recommendation']['rationale']['evidence_ids']=['nonexistent'];report=save(root,d,data)
 with pytest.raises(ValueError,match='recommendation citation'):builder.build(report,tmp_path/'bad')
def test_v1_keeps_compatibility_and_v2_requires_reversal(tmp_path):
 root,d,data=bundle(tmp_path);data['profile']='scooby.reasoning/1';data['reasoning']['conclusion'].pop('recommendation');builder.build(save(root,d,data),tmp_path/'v1')
 data['profile']='scooby.reasoning/2';data['reasoning']['conclusion']['recommendation']={'action':'Defer','rationale':{'text':'No supported conclusion','evidence_ids':[],'input_ids':[]},'counterevidence':[],'reversal_conditions':[]}
 with pytest.raises(ValueError,match='review conditions'):builder.build(save(root,d,data),tmp_path/'v2-bad')

def test_v2_input_evidence_must_intersect_and_audit_ids_resolve(tmp_path):
 root,d,data=bundle(tmp_path); item=next(x for p in d['pillars'].values() for x in p['measurements'] if x['evidence_ids']);r=data['reasoning']['conclusion']['recommendation']['rationale'];r['input_ids']=[item['id']];r['evidence_ids']=item['evidence_ids'][:1]
 builder.build(save(root,d,data),tmp_path/'valid')
 other=next(e['id'] for e in d['evidence'] if e['id'] not in item['evidence_ids']);r['evidence_ids']=[other]
 with pytest.raises(ValueError,match='must link to evidence'):builder.build(save(root,d,data),tmp_path/'bad-link')

def test_v2_untrusted_recommendation_is_embedded_as_data(tmp_path):
 root,d,data=bundle(tmp_path);data['reasoning']['conclusion']['recommendation']['action']='<script>alert(1)</script>';out=tmp_path/'xss';builder.build(save(root,d,data),out);html=(out/'index.html').read_text(encoding='utf-8');assert '<script>alert(1)</script>' not in html and '\\u003cscript' in html

def test_producer_compatibility_packet(tmp_path):
 root=ROOT/'tests/fixtures/reasoning-compatibility';manifest=json.loads((root/'fixture-manifest.json').read_bytes())
 for item in manifest['positive']:
  builder.build(root/item['path']/'report.json',tmp_path/item['name'])
 for item in manifest['negative']:
  with pytest.raises(ValueError):
   builder.build(root/item['path']/'report.json',tmp_path/item['name'])
