import pytest
from fastapi import HTTPException
from publication import admin
from store import db, now
import case_world
from admin_support import session_headers


def test_challenge_owner_is_bound_to_exact_active_admin_session():
    a=session_headers('test-issuer','case-admin-a','case_investigation')
    b=session_headers('test-issuer','case-admin-b','case_investigation')
    a2=session_headers('test-issuer','case-admin-a','case_investigation')
    p=admin.principal_for_token(admin.bearer(a['Authorization']))
    q=admin.principal_for_token(admin.bearer(b['Authorization']))
    second=admin.principal_for_token(admin.bearer(a2['Authorization']))
    with db() as c:
        c.execute('PRAGMA defer_foreign_keys=ON')
        c.execute("INSERT INTO case_snapshots VALUES('owner-snap','1:test','{}','{}','p','{}',?,?)",(now(),now()+500))
        c.execute("INSERT INTO cases VALUES('owner-case','1:test','owner-snap','monitoring',?)",(now(),))
        c.execute("INSERT INTO case_challenges VALUES('owner-ch','owner-case','owner-snap','p','diagnostic_research','owner-nonce','pending',?,?,?)",(now()+500,now(),'owner-idem'))
        c.execute('INSERT INTO case_challenge_admin VALUES(?,?,?)',('owner-ch',p.session_id,admin.subject_hash(p.iss,p.sub)))
        case_world.require_owner(c,'owner-ch',p)
        for other in (q,second,None):
            with pytest.raises(HTTPException) as error:case_world.require_owner(c,'owner-ch',other)
            assert error.value.status_code==403
        admin.revoke_scope(c,p.iss,p.sub,'case_investigation','test')
        with pytest.raises(HTTPException):case_world.require_owner(c,'owner-ch',p)

def test_public_gate_case_preflight_and_guard(monkeypatch):
 from fastapi.testclient import TestClient
 import app as module
 monkeypatch.setenv('SCOOBY_PUBLIC_GATE','true')
 client=TestClient(module.app)
 headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type,idempotency-key'}
 assert client.options('/scouting/cases/test/challenge',headers=headers).status_code==200
 assert client.post('/scouting/cases/test/challenge',json={'expected_revision':'0'*64}).status_code==401
 assert client.post('/scouting/cases/refresh',json={'limit':1}).status_code==404
 headers['Origin']='https://untrusted.invalid'
 assert client.options('/scouting/cases/test/challenge',headers=headers).status_code==400

def test_world_checkpoint_binds_initiating_session_end_to_end(tmp_path,monkeypatch):
 from types import SimpleNamespace
 from fastapi.testclient import TestClient
 from app import app
 from publication.deps import get_world_optional
 from publication.world import DeviceStart,Tokens
 from admin_support import session_headers
 from test_cases import record,with_sources,result
 import store,case_engine,case_world
 monkeypatch.setattr(store,'DB',tmp_path/'case.sqlite');store.init()
 monkeypatch.setenv('SCOOBY_PUBLIC_GATE','true')
 monkeypatch.setattr(case_engine,'evaluate',lambda record,evidence:result(1,record))
 case=case_engine.ingest_record(with_sources(record(15555),tmp_path),tmp_path)
 a=session_headers('owner-test','alice','case_investigation');b=session_headers('owner-test','bob','case_investigation')
 class FakeWorld:
  config=SimpleNamespace(accepted_acr=('synthetic',))
  def start_device(self,_):return DeviceStart(device_code='test-only',user_code='TEST',verification_uri='https://world.example',expires_in=100,interval=0)
  def poll(self,_):return Tokens('synthetic')
  def validate_id_token(self,*a,**kw):return SimpleNamespace(iss='owner-test',sub='alice')
  def authorize_case_admin(self,identity,binding):return True
 app.dependency_overrides[get_world_optional]=lambda:FakeWorld()
 try:
  c=TestClient(app);revision=c.get('/scouting/cases/'+case).json()['snapshot_digest']
  ch=c.post('/scouting/cases/'+case+'/challenge',json={'expected_revision':revision},headers={**a,'Idempotency-Key':'same-owner-test'}).json()['challenge_id']
  assert c.post('/scouting/challenges/'+ch+'/world-attempt',headers=b).status_code==403
  attempt=c.post('/scouting/challenges/'+ch+'/world-attempt',headers=a).json()['attempt_id']
  assert c.get('/scouting/world-attempts/'+attempt,headers=b).status_code==403
  assert c.post('/scouting/world-attempts/'+attempt+'/cancel',headers=b).status_code==403
  result=c.get('/scouting/world-attempts/'+attempt,headers=a);assert result.status_code==200 and result.json()['state']=='approved'
  assert c.get('/scouting/world-attempts/'+attempt,headers=a).json()['run_id']==result.json()['run_id']
 finally:
  app.dependency_overrides.pop(get_world_optional,None);case_world._codes.clear()
