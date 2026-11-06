"""One-shot technical archive smoke test. It does not assess or select a token."""
import argparse,datetime as dt,json,os,re,sqlite3,subprocess,sys,tempfile,urllib.request
from pathlib import Path
import live_pilot
TOKEN='0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce'
POOL='0x811beed0119b4afce20d2583eb608c6f7af1954f'
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--scratch',required=True,type=Path);args=parser.parse_args()
 args.scratch.mkdir(parents=True,exist_ok=True)
 secret=os.environ.get('PUBLICNODE_TOKEN','').strip()
 if not secret:print('PUBLICNODE_TOKEN is not set in this PowerShell session.');return 2
 url='https://api.dexscreener.com/token-pairs/v1/ethereum/'+TOKEN
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'ScoobyDAO-archive-smoke/1.0','Accept':'application/json'})
  with urllib.request.urlopen(req,timeout=15) as r:pairs=json.load(r)
  pool=next(x for x in pairs if x.get('pairAddress','').lower()==POOL and x.get('chainId')=='ethereum')
  created=dt.datetime.fromtimestamp(pool['pairCreatedAt']/1000,dt.timezone.utc).isoformat()
 except (OSError,ValueError,KeyError,StopIteration,TypeError):print('FAIL: reference pool metadata unavailable.');return 1
 with tempfile.TemporaryDirectory(prefix='scooby-archive-test-',dir=args.scratch) as temp:
  root=Path(temp);db=root/'state.sqlite';c=live_pilot.setup(db);cid='1:'+TOKEN
  record={'schema_version':'0.1','candidate_id':cid,'identity':{'chain_id':1,'address':TOKEN,'symbol':'SHIB'},'mode':'live','state':'monitoring','triggers':[],'screening':{'status':'not_scored','score':None,'score_version':None,'threshold_version':None,'quality_issues':['Reference-only technical smoke test; no selection or assessment.']},'selection':{'status':'not_selected','selected_by':None,'selected_at':None,'reason':None},'evidence':[],'last_observed_at':None,'next_check_at':None}
  with c:
   c.execute('INSERT INTO candidates VALUES(?,?,?)',(cid,json.dumps(record),None));c.execute('INSERT INTO pilot_leads VALUES(?,?,?,?)',(cid,'technical-reference',POOL,created))
  c.close()
  cmd=[sys.executable,str(Path(__file__).with_name('collect_market_activity.py')),'--db',str(db),'--output',str(root),'--candidate-id',cid,'--pool',POOL,'--budget','40']
  result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8')
  if result.returncode!=0:
   reason=result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ''
   if re.fullmatch(r'PublicNode request failed with HTTP [0-9]{3}',reason) or reason in ('PublicNode request or response failed','RPC returned error or mismatched request','RPC request budget exhausted','wrong chain','block unavailable','block search range does not cover 24 hours','requires 24-25 hours of ordered history','missing or stale reference price','not canonical Ethereum Uniswap V2 factory','factory does not recognize this pair'):
    print('FAIL: '+reason+'. The test did not pass.')
   else:print('FAIL: full collector did not complete; the test did not pass.')
   return 1
  try:
   response=json.loads(result.stdout);path=root/response['snapshot'];raw=path.read_text(encoding='utf-8');snapshot=json.loads(raw)
   if secret in raw or secret in result.stdout or secret in result.stderr:print('FAIL: credential detected in output; test stopped.');return 1
   if snapshot.get('authentication')!='personal_token_path' or snapshot.get('rpc_url')!='https://ethereum-rpc.publicnode.com':raise ValueError('unexpected provenance')
   if not isinstance(response.get('calls'),int) or response['calls']>40:raise ValueError('request budget violated')
  except (OSError,KeyError,ValueError,TypeError):print('FAIL: collector response did not pass the smoke checks.');return 1
  print('PASS: authenticated collector completed with '+str(response['calls'])+' RPC calls; token absent from evidence and logs. Reference-only test; no gate or investigation was run.')
 return 0
if __name__=='__main__':raise SystemExit(main())
