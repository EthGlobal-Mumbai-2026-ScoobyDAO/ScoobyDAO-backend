"""Offline diagnostic imports never confer a case or World authorization."""
from fastapi.testclient import TestClient
import pytest
from app import app
from diagnostic_import import install
from modules.investigation.case_research import run_case
from test_case_research import captured_snapshot, source_payloads, CANDIDATE


def test_historical_diagnostic_import_is_immutable_and_explicit(tmp_path):
    snap=captured_snapshot(source_payloads())
    snap['record']['mode']='historical_replay'
    for evidence in snap['record']['evidence']: evidence['kind']='historical_fixture'
    descriptor={'case_id':'diagnostic_test','run_id':'diagnostic_test_run','candidate_id':CANDIDATE,
                'mode':'historical_replay','authorization':{'route':'automatic_policy','reference_id':'synthetic_auth_not_admission'}}
    bundle=tmp_path/'bundle'
    generated=run_case(descriptor,bundle,captured_snapshot=snap)
    result=install(bundle,generated['report_sha256'],'Historical diagnostic, pending review.')
    assert install(bundle,generated['report_sha256'],'Historical diagnostic, pending review.')==result
    client=TestClient(app)
    item=next(x for x in client.get('/reports').json() if x['run_id']==result['run_id'])
    assert item['provenance']=='user_requested_historical_diagnostic'
    assert item['diagnostic']['case_admitted'] is False and item['diagnostic']['world_verified'] is False
    assert item['selection']['admission_qualified'] is False and item['review']['status']=='pending'
    assert item['release']['status']=='unavailable'
    with pytest.raises(ValueError): install(bundle,'0'*64,'Historical diagnostic, pending review.')
