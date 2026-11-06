import base64,datetime,hashlib,json
from pathlib import Path
import case_engine,store

def test_fresh_provider_concern_routes_human_without_gate_vote(tmp_path,monkeypatch):
 monkeypatch.setattr(store,'DB',tmp_path/'backend.sqlite');store.init()
 record=json.loads((Path(__file__).parent/'candidate.json').read_text(encoding='utf-8-sig'));address='0x'+'a'*40
 record.update(mode='live',candidate_id='1:'+address,triggers=[]);record['identity'].update(chain_id=1,address=address)
 stamp=datetime.datetime.now(datetime.timezone.utc).isoformat();raw=json.dumps({'code':1,'result':{address:{'is_honeypot':'1'}}}).encode();sha=hashlib.sha256(raw).hexdigest();folder=tmp_path/'snapshots';folder.mkdir();(folder/(sha+'.json')).write_bytes(raw)
 record['evidence']=[{'id':sha,'sha256':sha,'source':'snapshots/'+sha+'.json','kind':'live_observation','observed_at':None,'fetched_at':stamp,'block_number':None,'limitations':['Request URL: https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses='+address]}]
 case=case_engine.ingest_record(record,tmp_path)
 with store.db() as c:
  row=c.execute('SELECT state,current_snapshot FROM cases WHERE id=?',(case,)).fetchone();assert row['state']=='awaiting_human'
  assessment=json.loads(c.execute('SELECT assessment FROM case_snapshots WHERE id=?',(row['current_snapshot'],)).fetchone()[0]);assert assessment['triggered_count']==0 and not assessment['eligible'];assert assessment['scouting']['routing']['recommendation']=='human_review_required'
  assert c.execute('SELECT count(*) FROM case_decisions WHERE case_id=?',(case,)).fetchone()[0]==0

def test_same_artifact_cannot_count_for_distinct_groups():
 raw=b'synthetic';sha=hashlib.sha256(raw).hexdigest();path='snapshots/'+sha+'.json';stamp=datetime.datetime.now(datetime.timezone.utc).isoformat();e={'id':sha,'source':path,'sha256':sha,'observed_at':stamp}
 groups=[{'id':'G%02d'%i,'status':'triggered' if i<=4 else 'unknown','votes':1 if i<=4 else 0,'evidence':[e] if i<=4 else []} for i in range(1,13)]
 valid,count,_=case_engine.verified_gate({'groups':groups,'eligible':True,'triggered_count':4},{path:base64.b64encode(raw).decode()});assert not valid and count==0
