"""Capture verified-source metadata for one monitored candidate; no automatic risk vote."""
import argparse,json,sqlite3
from pathlib import Path
import discovery,live_pilot

def main():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--candidate-id',required=True);a=p.parse_args()
 c=sqlite3.connect(a.db);row=c.execute('SELECT record FROM candidates WHERE id=?',(a.candidate_id,)).fetchone()
 if not row:raise ValueError('candidate not found')
 record=json.loads(row[0]);ident=record['identity'];key=discovery.identity(ident['chain_id'],ident['address'])
 if key!=a.candidate_id:raise ValueError('candidate identity mismatch')
 source=f"https://sourcify.dev/server/v2/contract/{ident['chain_id']}/{ident['address']}?fields=all"
 data,e,meta=live_pilot.Fetcher(a.output/'snapshots',1).get(source)
 if not isinstance(data,dict) or str(data.get('chainId'))!=str(ident['chain_id']) or str(data.get('address','')).lower()!=ident['address'].lower():
  print(json.dumps({'candidate_id':key,'status':'source_unavailable_or_identity_mismatch','detail':meta,'gate_vote':'none'},indent=2));return 1
 e['limitations']=['Sourcify verification match is source/bytecode matching, not proof of security, current controller or complete functionality.','Fetched source may need proxy implementation resolution and block-consistency checks.','Request URL: '+source]
 with c:live_pilot.attach_evidence(c,key,e)
 c.close();print(json.dumps({'candidate_id':key,'status':'source_captured','provider_match':data.get('match'),'runtime_match':data.get('runtimeMatch'),'proxy_resolution':data.get('proxyResolution'),'sha256':e['sha256'],'gate_vote':'none; semantic validation still required'},indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
