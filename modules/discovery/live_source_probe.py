"""Bounded read-only connectivity probe; creates source snapshots, never evaluates or selects a candidate."""
import argparse, datetime as dt, hashlib, json, re, urllib.request, urllib.error
from pathlib import Path

def fetch(url,path):
    fetched_at=dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'ScoobyDAO-local-source-probe/1.0','Accept':'application/json;version=20230203' if 'geckoterminal.com' in url else 'application/json'})
        with urllib.request.urlopen(req,timeout=15) as response:
            payload=response.read(3_000_001); status=response.status
        if len(payload)>3_000_000: raise ValueError('response exceeds 3 MB safety bound')
        parsed=json.loads(payload); path.write_bytes(payload)
        return {'status':'ok','http_status':status,'url':url,'requested_at':fetched_at,'received_at':dt.datetime.now(dt.timezone.utc).isoformat(),'file':path.name,'sha256':hashlib.sha256(payload).hexdigest(),'provider_code':parsed.get('code') if isinstance(parsed,dict) else None,'record_count':len(parsed) if isinstance(parsed,list) else (len(parsed['data']) if isinstance(parsed,dict) and isinstance(parsed.get('data'),list) else None),'observation_time':'unknown; request time is not observation time'}
    except (OSError,ValueError) as e:
        return {'status':'error','url':url,'requested_at':fetched_at,'error':str(e),'observation_time':None}

def main():
    p=argparse.ArgumentParser();p.add_argument('--chain',choices=('ethereum','base'),required=True);p.add_argument('--address',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not re.fullmatch(r'0x[0-9a-fA-F]{40}',a.address): p.error('address must be a 20-byte EVM address')
    a.output.mkdir(parents=True,exist_ok=True); token=a.address.lower(); chain_id={'ethereum':1,'base':8453}[a.chain]; network={'ethereum':'eth','base':'base'}[a.chain]
    urls={'new_pools':f'https://api.geckoterminal.com/api/v2/networks/{network}/new_pools?page=1','market_pairs':f'https://api.dexscreener.com/token-pairs/v1/{a.chain}/{token}','security':f'https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={token}'}
    results={k:fetch(url,a.output/(k+'.json')) for k,url in urls.items()}
    security=results['security']
    if security['status']=='ok':
        obj=json.loads((a.output/'security.json').read_text(encoding='utf-8'))
        if obj.get('code')!=1 or token not in obj.get('result',{}): security['status']='provider_error';security['error']='provider did not return a successful record for requested address'
    manifest={'purpose':'Connectivity and response capture only; not a security verdict, gate decision or human selection.','identity_requested':{'chain_id':chain_id,'address':token},'sources':results,'calls':3,'freshness':'Provider timestamps and cache age require separate verification.','gate_status':'not_evaluated'}
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2));return 1 if any(v['status']!='ok' for v in results.values()) else 0
if __name__=='__main__': raise SystemExit(main())
