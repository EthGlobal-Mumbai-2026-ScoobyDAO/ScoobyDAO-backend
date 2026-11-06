"""Provider-reported Base Uniswap v4 bytes32 pool IDs, entirely offline."""
import copy
import json
from pathlib import Path

import pytest

from modules.investigation import history
from modules.investigation.case_research import run_case
from modules.investigation.contract_validate import verify_digest
from test_case_research import ADDR, case, captured_snapshot, source_payloads

POOL_ID = '0x' + 'ab' * 32

def pool():
    return {'id':'base_'+POOL_ID, 'attributes':{'address':POOL_ID,'name':'TEST / ETH'},
            'relationships':{'base_token':{'data':{'id':'base_'+ADDR}},
                             'quote_token':{'data':{'id':'base_0x'+'0'*40}},
                             'dex':{'data':{'id':'uniswap-v4-base'}}}}

def snapshot():
    payload=source_payloads();payload['pools']={'data':[pool()]}
    snap=captured_snapshot(payload)
    snap['record']['candidate_id']='8453:'+ADDR
    snap['record']['identity']['chain_id']=8453
    for e in snap['record']['evidence']:
        url=e['limitations'][0]
        if '/networks/eth/new_pools' in url: e['limitations'][0]=url.replace('/networks/eth/new_pools','/networks/base/new_pools')
        if '/ohlcv/day?' in url:
            e['limitations'][0]=url.replace('/networks/eth/pools/0x'+'34'*20, '/networks/base/pools/'+POOL_ID)
    return snap

def base_case(): return {**case('automatic_policy'), 'candidate_id':'8453:'+ADDR}

def test_provider_reported_v4_pool_id_is_not_an_address_or_verified_onchain():
    chosen,_=history.select_pool({'data':[pool()]},8453,ADDR)
    assert chosen['address']==POOL_ID and chosen['side']=='base'
    assert chosen['identifier_type']=='provider_reported_uniswap_v4_pool_id'
    assert chosen['dex_id']=='uniswap-v4-base'

@pytest.mark.parametrize('problem',['wrong_dex','missing_dex','wrong_record','wrong_token','wrong_chain','short_hash'])
def test_32_byte_id_needs_source_protocol_chain_and_token_binding(problem):
    row=pool();chain=8453
    if problem=='wrong_dex': row['relationships']['dex']['data']['id']='uniswap-v2-base'
    if problem=='missing_dex': row['relationships'].pop('dex')
    if problem=='wrong_record': row['id']='base_0x'+'cd'*32
    if problem=='wrong_token': row['relationships']['base_token']['data']['id']='base_0x'+'ef'*20
    if problem=='wrong_chain': chain=1
    if problem=='short_hash': row['attributes']['address']='0x'+'ab'*31
    with pytest.raises(ValueError,match='no identity-matched pool'):
        history.select_pool({'data':[row]},chain,ADDR)

def test_replay_only_uses_matching_v4_id_and_token_side(tmp_path):
    result=run_case(base_case(),tmp_path/'out',captured_snapshot=snapshot())
    report=verify_digest(tmp_path/'out',result['report_sha256'])
    assert result['source_attempts']==[] and report['mode']=='synthetic_demo'
    assert report['pillars']['technical_health']['status']=='partial'
    assert report['pillars']['statistical_risk']['status']=='unavailable'
    claim=next(x for x in report['pillars']['microstructure']['claims'] if x['id']=='gecko-pool')
    assert 'provider-reported Uniswap v4 pool ID' in claim['statement']
    assert 'independently verified' in claim['uncertainties'][0]

def test_replay_rejects_mismatched_32_byte_pool_id(tmp_path):
    snap=snapshot()
    for e in snap['record']['evidence']:
        if '/ohlcv/day?' in e['limitations'][0]:e['limitations'][0]=e['limitations'][0].replace(POOL_ID,'0x'+'cd'*32)
    result=run_case(base_case(),tmp_path/'wrong-pool',captured_snapshot=snap)
    assert result['state']=='partial' and result['pillar_status']['technical_health']=='unavailable'
    assert 'captured_daily_pool_or_side_mismatch' in result['limitations']

def test_v4_history_fetch_uses_provider_id_and_disables_empty_fill(tmp_path, monkeypatch):
    calls=[]
    def fake_get(url,out,name):
        calls.append((url,name))
        return ({'data':[pool()]} if name=='pools' else {'data':{'attributes':{'ohlcv_list':[]}}}), {'status':'captured'}
    monkeypatch.setattr(history,'get',fake_get)
    result=history.fetch(8453,ADDR,tmp_path/'capture')
    assert result['pool']['identifier_type']=='provider_reported_uniswap_v4_pool_id'
    assert result['state']=='pending_history_or_data_gaps' and result['history']['closes_before_cutoff']==0
    assert '/pools/'+POOL_ID+'/ohlcv/day?' in calls[1][0] and 'include_empty_intervals=false' in calls[1][0]
