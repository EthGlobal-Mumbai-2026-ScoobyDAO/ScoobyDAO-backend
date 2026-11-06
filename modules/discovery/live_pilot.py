"""Bounded local live discovery pilot. Provider hints never become verified votes."""
import argparse, datetime as dt, hashlib, json, re, sqlite3, sys, time, urllib.request, urllib.error
from pathlib import Path
import discovery

CHAINS={'ethereum':(1,'eth'),'base':(8453,'base')}
EXCLUDED={
 1:{'0x0000000000000000000000000000000000000000','0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2','0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'},
 8453:{'0x0000000000000000000000000000000000000000','0x4200000000000000000000000000000000000006','0x833589fcd6edb6e08f4c7c32d4f71b54bda02913'}}
GROUPS=['G01','G02','G03','G04','G05','G06','G07','G08','G09','G10','G11','G12']
HELD={'G06','G08','G10','G11','G12'}
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def read_json(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def setup(db):
 discovery.connect(db).close()
 c=sqlite3.connect(db)
 c.executescript('''CREATE TABLE IF NOT EXISTS pilot_runs(run_id TEXT PRIMARY KEY,started_at TEXT NOT NULL,completed_at TEXT,status TEXT NOT NULL,calls INTEGER NOT NULL DEFAULT 0,budget INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS pilot_sources(run_id TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,detail TEXT NOT NULL,PRIMARY KEY(run_id,source));
 CREATE TABLE IF NOT EXISTS pilot_findings(id INTEGER PRIMARY KEY,candidate_id TEXT NOT NULL,run_id TEXT NOT NULL,group_id TEXT NOT NULL,status TEXT NOT NULL,detail TEXT NOT NULL,evidence_ids TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS pilot_leads(candidate_id TEXT NOT NULL,run_id TEXT NOT NULL,pool_id TEXT NOT NULL,created_at TEXT,PRIMARY KEY(candidate_id,run_id,pool_id));''')
 c.commit();return c
class BudgetExhausted(Exception): pass
class Fetcher:
 def __init__(self,root,budget): self.root=Path(root);self.budget=budget;self.calls=0;self.root.mkdir(parents=True,exist_ok=True)
 def get(self,url):
  if self.calls>=self.budget: raise BudgetExhausted('request budget exhausted')
  self.calls+=1; start=now()
  req=urllib.request.Request(url,headers={'Accept':'application/json;version=20230203' if 'geckoterminal.com' in url else 'application/json','User-Agent':'ScoobyDAO-local-pilot/1.0'})
  try:
   with urllib.request.urlopen(req,timeout=15) as res: raw=res.read(3_000_001);code=res.status
   if len(raw)>3_000_000: raise ValueError('response too large')
   parsed=json.loads(raw); digest=hashlib.sha256(raw).hexdigest(); file=self.root/(digest+'.json')
   if not file.exists(): file.write_bytes(raw)
   return parsed,{'id':digest,'source':f'snapshots/{digest}.json','sha256':digest,'observed_at':None,'fetched_at':now(),'block_number':None,'kind':'live_observation','limitations':['Raw provider response; observation time, source coverage and correctness are not verified.','Request URL: '+url]}, {'status':'ok','http_status':code,'requested_at':start,'fetched_at':now(),'sha256':digest}
  except (OSError,ValueError,UnicodeError) as e:
   return None,None,{'status':'error','requested_at':start,'fetched_at':now(),'error':str(e)}
def extract_leads(chain, document,limit):
 if not isinstance(document,dict) or not isinstance(document.get('data'),list): raise ValueError('invalid new pools response')
 cid,network=CHAINS[chain]; leads=[];seen=set()
 for item in document['data']:
  try:
   rel=item['relationships']; a=item['attributes']; raw=rel['base_token']['data']['id']; prefix=network+'_'
   if not isinstance(raw,str) or not raw.startswith(prefix): continue
   address=raw[len(prefix):].lower(); key=discovery.identity(cid,address)
   if address in EXCLUDED[cid] or key in seen: continue
   name=str(a.get('name','')).split(' / ')[0].strip()[:64] or '?'
   pool=a.get('address'); created=a.get('pool_created_at')
   if not isinstance(pool,str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}|0x[0-9a-fA-F]{64}',pool): continue
   seen.add(key);leads.append({'candidate_id':key,'chain_id':cid,'address':address,'symbol':name,'pool_id':pool.lower(),'created_at':created})
   if len(leads)>=limit: break
  except (KeyError,TypeError,ValueError): continue
 return leads

def record_candidate(c,lead,evidence,run_id):
 key=lead['candidate_id'];found=c.execute('SELECT record,last_surface FROM candidates WHERE id=?',(key,)).fetchone()
 if found:
  old=json.loads(found[0])
  if old['mode']!='live': return False
  record=old
 else:
  record={'schema_version':'0.1','candidate_id':key,'identity':{'chain_id':lead['chain_id'],'address':lead['address'],'symbol':lead['symbol']},'mode':'live','state':'monitoring','triggers':[],'screening':{'status':'not_scored','score':None,'score_version':None,'threshold_version':None,'quality_issues':['Provider-reported pool lead; no independent token identity or gate checks verified.']},'selection':{'status':'not_selected','selected_by':None,'selected_at':None,'reason':None},'evidence':[],'last_observed_at':None,'next_check_at':None}
 if not any(x['id']==evidence['id'] for x in record['evidence']):record['evidence'].append(evidence)
 trigger={'reason_code':'new_pool_lead','description':'Provider-reported new pool; a discovery lead, not a concern vote.','evidence_ids':[evidence['id']]}
 if trigger not in record['triggers']: record['triggers'].append(trigger)
 c.execute('INSERT OR REPLACE INTO candidates VALUES(?,?,?)',(key,json.dumps(record,ensure_ascii=False),found[1] if found else None))
 c.execute('INSERT OR IGNORE INTO pilot_leads VALUES(?,?,?,?)',(key,run_id,lead['pool_id'],lead['created_at']))
 return True

def attach_evidence(c,key,e):
 row=c.execute('SELECT record FROM candidates WHERE id=?',(key,)).fetchone(); record=json.loads(row[0])
 if not any(x['id']==e['id'] for x in record['evidence']):record['evidence'].append(e)
 c.execute('UPDATE candidates SET record=? WHERE id=?',(json.dumps(record,ensure_ascii=False),key))

def evaluate(groups):
 """Gate boundary: only separately verified, evidence-linked observations may vote."""
 if not isinstance(groups,dict): raise ValueError('group map required')
 result={}
 for group in GROUPS:
  item=groups.get(group)
  if group in HELD: result[group]='held'
  elif not isinstance(item,dict) or item.get('verification')!='verified' or not item.get('evidence_ids') or not isinstance(item.get('triggered'),bool): result[group]='unknown'
  else: result[group]='triggered' if item['triggered'] else 'not_triggered'
 count=sum(v=='triggered' for v in result.values())
 return {'groups':result,'triggered_groups':count,'evaluated_groups':sum(v in ('triggered','not_triggered') for v in result.values()),'eligible':count>=4,'priority':'higher' if count>=5 else 'standard' if count>=4 else None,'note':'Votes require validated metric-specific evidence; this boundary does not itself validate observations.'}

def run(db,root,limit,budget,chain_names):
 if limit<1 or limit>10 or budget<0 or budget>30:raise ValueError('limit must be 1-10 per chain and budget 0-30')
 c=setup(db); started=now();run_id=hashlib.sha256(started.encode()).hexdigest()[:16]; f=Fetcher(Path(root)/'snapshots',budget); c.execute('INSERT INTO pilot_runs VALUES(?,?,?,?,?,?)',(run_id,started,None,'running',0,budget));c.commit(); all_leads=[]; issues=[]
 def fetch_source(name,url):
  try: data,e,meta=f.get(url)
  except BudgetExhausted as ex: data,e,meta=None,None,{'status':'backpressure','error':str(ex)}
  c.execute('INSERT OR REPLACE INTO pilot_sources VALUES(?,?,?,?)',(run_id,name,meta['status'],json.dumps(meta))); c.execute('UPDATE pilot_runs SET calls=? WHERE run_id=?',(f.calls,run_id)); c.commit()
  if meta['status']!='ok':issues.append(name+': '+meta['status'])
  return data,e
 for name in chain_names:
  _,network=CHAINS[name]; data,e=fetch_source('new_pools:'+name,f'https://api.geckoterminal.com/api/v2/networks/{network}/new_pools?page=1')
  if data is None: continue
  try: leads=extract_leads(name,data,limit)
  except ValueError as ex: issues.append(name+': invalid response'); c.execute('UPDATE pilot_sources SET status=?,detail=? WHERE run_id=? AND source=?',('invalid_response',str(ex),run_id,'new_pools:'+name));c.commit();continue
  for lead in leads:
   with c:
    if record_candidate(c,lead,e,run_id):all_leads.append((name,lead))
 for name,lead in all_leads:
  key=lead['candidate_id']; addr=lead['address'];cid=lead['chain_id']
  for source,url in [('market',f'https://api.dexscreener.com/token-pairs/v1/{name}/{addr}'),('security',f'https://api.gopluslabs.io/api/v1/token_security/{cid}?contract_addresses={addr}')]:
   data,e=fetch_source(source+':'+key,url)
   if e is None:continue
   valid=isinstance(data,list) if source=='market' else isinstance(data,dict) and data.get('code')==1 and isinstance(data.get('result'),dict) and addr in data['result']
   if not valid:
    issues.append(source+': provider returned no usable data');c.execute('UPDATE pilot_sources SET status=? WHERE run_id=? AND source=?',('invalid_response',run_id,source+':'+key));c.commit();continue
   with c:attach_evidence(c,key,e)
  assessment=evaluate({})
  with c:
   for group,status in assessment['groups'].items():c.execute('INSERT INTO pilot_findings(candidate_id,run_id,group_id,status,detail,evidence_ids) VALUES(?,?,?,?,?,?)',(key,run_id,group,status,'Held pending method validation.' if status=='held' else 'Provider hints not independently verified; no gate vote.','[]'))
 selected_count=sum(json.loads(c.execute('SELECT record FROM candidates WHERE id=?',(lead['candidate_id'],)).fetchone()[0])['selection']['status']=='selected' for _,lead in all_leads)
 status='partial' if issues else 'ok' if all_leads else 'no_leads';c.execute('UPDATE pilot_runs SET completed_at=?,status=?,calls=? WHERE run_id=?',(now(),status,f.calls,run_id));c.commit()
 report={'run_id':run_id,'status':status,'calls':f.calls,'budget':budget,'chains':chain_names,'leads':[x[1] for x in all_leads],'issues':issues,'gate':'not_evaluated_by_scan: see the review queue for verified results','qualified_candidates':None,'selected_candidates':selected_count,'limitations':['New-pool feed is not exhaustive. Base/quote orientation and token identity are provider-reported.','Market and security responses are captured as hints only. Source observation freshness is unknown.','The scan itself does not verify or apply concern measurements.']}
 (Path(root)/'latest-run.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8');c.close();return report

def main():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--limit-per-chain',type=int,default=2);p.add_argument('--budget',type=int,default=10);p.add_argument('--chains',nargs='+',choices=list(CHAINS),default=list(CHAINS));a=p.parse_args()
 a.db.parent.mkdir(parents=True,exist_ok=True);a.output.mkdir(parents=True,exist_ok=True)
 result=run(a.db,a.output,a.limit_per_chain,a.budget,a.chains)
 import review_queue
 q=review_queue.queue(a.db,a.output)
 review_queue.save_atomic(a.output/'review-queue.html',review_queue.html_page(q))
 review_queue.save_atomic(a.output/'review-queue.json',json.dumps(q,indent=2,ensure_ascii=False))
 print(json.dumps({'run_id':result['run_id'],'status':result['status'],'calls':result['calls'],'budget':result['budget'],'qualified':q['qualified_count'],'monitored':q['monitored_count'],'source_issues':result['issues'],'review_queue':str(a.output/'review-queue.html'),'gate':'The review queue evaluates registered verifiers; unverified source hints do not vote.'},indent=2))
if __name__=='__main__':main()
