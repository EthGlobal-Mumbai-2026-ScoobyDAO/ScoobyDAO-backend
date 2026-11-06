"""Capture complementary public source responses for one chain/address."""
import argparse,json,pathlib
import history
CHAINS={1:'ethereum',8453:'base'}
def capture(chain,address,out):
 id=history.identity(chain,address); out=pathlib.Path(out); out.mkdir(parents=True,exist_ok=True)
 requests={'market':'https://api.dexscreener.com/token-pairs/v1/'+CHAINS[chain]+'/'+address.lower(),'security':'https://api.gopluslabs.io/api/v1/token_security/'+str(chain)+'?contract_addresses='+address.lower(),'source':'https://sourcify.dev/server/v2/contract/'+str(chain)+'/'+address.lower()+'?fields=all'}
 results={}
 for name,url in requests.items():
  data,meta=history.get(url,out,name); results[name]=meta
  if data is not None: results[name]['state']='captured'
 history.store(out/'capture.json',{'candidate_id':id,'sources':results,'limitations':['Provider results are not independently verified; source times may differ.','A successful fetch does not establish correctness or coverage.']}); return results
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__); p.add_argument('--chain',required=True,type=int); p.add_argument('--address',required=True); p.add_argument('--output',required=True,type=pathlib.Path); a=p.parse_args(); print(json.dumps(capture(a.chain,a.address,a.output),indent=2))
