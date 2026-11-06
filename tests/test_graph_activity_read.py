"""Read-only activity integration: source scope and time are backend-owned."""
import datetime as dt,hashlib,json
from fastapi.testclient import TestClient
import pytest
import store,graph_activity_read as service
from app import app
from store import db,dumps,digest,now

@pytest.fixture
def captures(tmp_path,monkeypatch):
 monkeypatch.setattr(store,'DB',tmp_path/'db.sqlite');store.init()
 clock=dt.datetime.now(dt.timezone.utc);end=clock.replace(minute=0,second=0,microsecond=0);start=end-dt.timedelta(hours=720);token='0x'+'a'*40;cid='1:'+token
 with db() as c:
  c.execute('INSERT INTO case_snapshots VALUES(?,?,?,?,?,?,?,?)',('snap',cid,'{}','{}','policy','{}',now(),now()+3600))
  c.execute('INSERT INTO cases VALUES(?,?,?,?,?)',('case',cid,'snap','monitoring',now()))
 rows=[{'periodStartUnix':int((start+dt.timedelta(hours=i)).timestamp()),'token':{'id':token},'volumeUSD':'200','priceUSD':'1','totalValueLockedUSD':'10'} for i in range(720)]
 doc={'data':{'_meta':{'deployment':'SYNTHETIC','hasIndexingErrors':False,'block':{'number':100,'timestamp':int(clock.timestamp())}},'tokenHourDatas':rows}}
 raw=json.dumps(doc).encode();g={'url':service.graph.URL,'fetched_at':clock.isoformat(),'raw':raw,'sha256':hashlib.sha256(raw).hexdigest(),'query':service.graph.QUERY,'variables':{'token':token,'start':int(start.timestamp()),'end':int(end.timestamp())}}
 fxraw=json.dumps({'base':'USD','quote':'INR','rate':100,'date':(end.date()-dt.timedelta(days=1)).isoformat()}).encode();fx={'url':'https://api.frankfurter.dev/v2/providers/ecb/rate/usd/inr?date='+(end.date()-dt.timedelta(days=1)).isoformat(),'fetched_at':clock.isoformat(),'raw':fxraw,'sha256':hashlib.sha256(fxraw).hexdigest()}
 return g,fx

def test_scope_expiry_integrity_and_no_gate_votes(captures,monkeypatch):
 g,fx=captures;service.install('case',g,fx);client=TestClient(app);r=client.get('/scouting/cases/case/activity').json()
 assert r['status']=='pass' and r['decision_scope']=='ethereum_uniswap_v3_token' and r['gate_effect']=='none'
 assert dt.datetime.fromisoformat(r['valid_until_utc'])<=dt.datetime.fromtimestamp(g['variables']['end'],dt.timezone.utc)+dt.timedelta(hours=1)
 assert r['source_authentication']=='local_operator_capture_not_independently_authenticated'
 with db() as c:
  row=c.execute('SELECT source_json FROM graph_activity_inputs').fetchone();v=json.loads(row[0]);v['graph']['variables']['end']-=3600;raw=dumps(v);c.execute('UPDATE graph_activity_inputs SET source_json=?,source_sha256=?',(raw,digest(raw.encode())))
 r=client.get('/scouting/cases/case/activity').json();assert r['status']=='unknown' and r['reason']=='capture_window_expired' and 'volume_inr' not in r
 with db() as c:c.execute("UPDATE graph_activity_inputs SET source_json='{}'")
 assert client.get('/scouting/cases/case/activity').status_code==409

def test_wrong_token_and_unknown_case_are_not_imported(captures):
 g,fx=captures;g['variables']['token']='0x'+'b'*40
 with pytest.raises(ValueError):service.install('case',g,fx)
 assert TestClient(app).get('/scouting/cases/no-such-case/activity').status_code==404

def test_incomplete_graph_does_not_accept_secret_bearing_fx_url(captures):
 g,fx=captures;doc=json.loads(g['raw']);doc['data']['tokenHourDatas'].pop();g['raw']=json.dumps(doc).encode();g['sha256']=digest(g['raw'])
 fx['url']+='&api_key=not-a-real-key'
 with pytest.raises(ValueError):service.install('case',g,fx)
 with db() as c:assert c.execute('SELECT count(*) FROM graph_activity_inputs').fetchone()[0]==0
