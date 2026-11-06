"""Build an inspectable direct-token v0.2 draft from captured data and optional legacy VAE output."""
import argparse,datetime,hashlib,json,math,pathlib,shutil,sys
from decimal import Decimal
import history
import contract_validate as schema
load=lambda p:json.loads(pathlib.Path(p).read_text(encoding='utf8')); digest=lambda b:hashlib.sha256(b).hexdigest()
def build(hdir,cdir,out,model=None):
 hdir=pathlib.Path(hdir); cdir=pathlib.Path(cdir); out=pathlib.Path(out)
 if out.exists(): raise ValueError('output exists; choose a new output directory')
 h=load(hdir/'source-status.json'); c=load(cdir/'capture.json'); token=h['candidate_id']; chain,address=token.split(':',1); history.identity(int(chain),address)
 if token!=c['candidate_id']: raise ValueError('source identity mismatch')
 for rec,folder in [(x,hdir) for x in h['requests']]+[(x,cdir) for x in c['sources'].values() if x.get('state')=='captured']:
  path=folder/rec['path'];
  if not path.is_file() or digest(path.read_bytes())!=rec.get('sha256'): raise ValueError('source hash mismatch')
 pool=h.get('pool');
 if not pool: raise ValueError('no identity-matched pool; cannot create this draft')
 history.select_pool(load(hdir/'pools.json'),int(chain),address,pool['address'])
 model_data=None
 if model:
  model=pathlib.Path(model); m=load(model/'run-manifest.json')
  if m['candidate_id']!=token or m['source_candles_sha256']!=digest((hdir/'daily.json').read_bytes()): raise ValueError('VAE identity or data mismatch')
  if m['metrics_sha256']!=digest((model/'legacy-metrics.json').read_bytes()) or m['reconstructions_sha256']!=digest((model/'output/vae/VAE_TOKEN.csv').read_bytes()): raise ValueError('VAE output hash mismatch')
  model_data=load(model/'legacy-metrics.json')
 out.mkdir(parents=True); (out/'evidence').mkdir(); evid=[]; ledger=[]
 def evidence(id,src,url,fetch,kind='live_observation'):
  target=out/'evidence'/(id+src.suffix); shutil.copyfile(src,target); path=target.relative_to(out).as_posix(); evid.append({'id':id,'path':path,'sha256':digest(target.read_bytes()),'kind':kind,'observed_at':None,'fetched_at':fetch,'block_number':None,'window':{'start':None,'end':None,'precision':None},'coverage':'Captured source response; scope and time differ by provider.','limitations':['Source output is not independently verified.']}); ledger.append({'id':id,'url':url,'fetched_at':fetch,'path':path,'sha256':digest(target.read_bytes())})
 for name in ('pools','daily'):
  rec=next((x for x in h['requests'] if x.get('path')==name+'.json'),None)
  if rec: evidence('history_'+name,hdir/rec['path'],rec['url'],rec.get('fetched_at'))
 for name,rec in c['sources'].items():
  if rec.get('state')=='captured': evidence('source_'+name,cdir/rec['path'],rec['url'],rec.get('fetched_at'))
 if model_data:
  evidence('vae_metrics',model/'legacy-metrics.json','local legacy calculation',None,'derived'); evidence('vae_reconstructions',model/'output/vae/VAE_TOKEN.csv','local legacy reconstruction',None,'derived'); evidence('vae_manifest',model/'run-manifest.json','local run manifest',None,'derived')
 names=('microstructure','onchain','fundamentals','statistical_risk','technical_health'); pillars={k:{'status':'partial','summary':'Coverage not yet established.','evidence_ids':[],'measurements':[],'series':[],'claims':[],'quality_issues':[],'raw_payload_path':None} for k in names}
 def claim(k,id,text,ids,unc):
  ids=[x for x in ids if x in {e['id'] for e in evid}]
  if not ids: return
  pillars[k]['evidence_ids']=sorted(set(pillars[k]['evidence_ids']+ids)); pillars[k]['claims'].append({'id':id,'statement':text,'kind':'observation','supporting_evidence_ids':ids,'counterevidence_ids':[],'contradiction_claim_ids':[],'uncertainties':[unc]})
 def measurement(k,id,val,unit,ids,method):
  if isinstance(val,bool) or not isinstance(val,(int,float)) or not math.isfinite(val): return
  pillars[k]['evidence_ids']=sorted(set(pillars[k]['evidence_ids']+ids)); pillars[k]['measurements'].append({'id':id,'value':val,'unit':unit,'method':method,'quality':'unvalidated','evidence_ids':ids,'window':{'start':None,'end':None,'precision':None},'unknown_reason':None})
 market=load(cdir/'market.json') if c['sources']['market'].get('state')=='captured' else []
 selected=next((p for p in market if p.get('pairAddress','').lower()==pool['address'] and p.get('baseToken',{}).get('address','').lower()==address.lower()),None)
 if selected:
  sym=selected['baseToken'].get('symbol','UNKNOWN');
  for id,val,unit in [('provider_price_usd',float(selected['priceUsd']) if selected.get('priceUsd') else None,'USD per token'),('provider_liquidity_usd',selected.get('liquidity',{}).get('usd'),'USD')]: measurement('microstructure',id,val,unit,['source_market'],'DEX Screener reported snapshot; not independently verified')
  claim('microstructure','market-observation','DEX Screener reports the selected pool '+pool['address']+'.',['source_market'],'Pool data is not guaranteed executable depth or complete venue coverage.')
 else: sym='UNKNOWN'; pillars['microstructure']['quality_issues'].append('No matching base-token pool in market source; price omitted.')
 sec=load(cdir/'security.json') if c['sources']['security'].get('state')=='captured' else {}; sec=sec.get('result',{}).get(address.lower(),{})
 if sec:
  for key in ('is_open_source','is_proxy','is_mintable','transfer_pausable','is_honeypot'):
   if key in sec: claim('onchain','security-'+key,'GoPlus reports '+key+' = '+str(sec[key])+'.',['source_security'],'Provider result only; not independent on-chain verification or a safety verdict.')
 source=load(cdir/'source.json') if c['sources']['source'].get('state')=='captured' else {}
 if source and source.get('address','').lower()==address.lower(): claim('onchain','source-match','Sourcify reports runtime match status: '+str(source.get('runtimeMatch'))+'.',['source_source'],'Source match does not prove safe behavior or current privileged state.')
 claim('fundamentals','identity-observation','Market provider identifies the selected asset as '+sym+'.',['source_market'],'Ticker is display metadata and does not establish project attribution or development activity.')
 pillars['fundamentals']['quality_issues'].append('Project team, official sources, activity and sentiment not researched in this automated source capture.')
 if model_data:
  def walk(value,prefix,section):
   if isinstance(value,dict):
    for k,x in value.items(): walk(x,prefix+[k],section)
   elif isinstance(value,(int,float)) and not isinstance(value,bool): measurement(section,'legacy_'+'_'.join(prefix),value,None,['vae_metrics'],'Original legacy method and scale; refer to full legacy metrics artifact.')
   elif isinstance(value,str) and prefix[-1] not in ('ticker','timestamp','latest_date'): claim(section,'legacy-'+'-'.join(prefix),'Legacy output '+'.'.join(prefix)+': '+value,['vae_metrics'],'Original label preserved; not independently calibrated and not human-approved.')
  walk(model_data['risk_assessment'],[], 'statistical_risk'); walk(model_data['technical_health'],[],'technical_health')
  ts=model_data['technical_series']; dates=ts['dates']
  for key,vals in ts.items():
   if key=='dates' or len(vals)!=len(dates): continue
   pillars['technical_health']['series'].append({'id':'legacy_'+key,'unit':None,'method':'Original technical-health code on 50 reconstructions','quality':'unvalidated','evidence_ids':['vae_metrics'],'window':{'start':dates[0] if dates else None,'end':dates[-1] if dates else None,'precision':'day'},'points':[{'time':t,'value':x} for t,x in zip(dates,vals)],'unknown_reason':None})
  for k in ('statistical_risk','technical_health'): pillars[k]['quality_issues'].append('Legacy 50-reconstruction outputs and original labels are preserved; confidence, thresholds and model calibration are not independently validated. Reconstructed values are not a safety or financial verdict.')
 else:
  for k in ('statistical_risk','technical_health'): pillars[k]['status']='unavailable'; pillars[k]['quality_issues'].append('50-reconstruction legacy engine pending: no eligible identity-bound VAE run supplied. Other pillars may continue.')
 for k in names:
  p=pillars[k]; p['summary']=(p['claims'][0]['statement'] if p['claims'] else p['quality_issues'][0] if p['quality_issues'] else 'No validated result available.')
  if not p['claims'] and not p['measurements'] and not p['series'] and p['status']=='partial': p['status']='unavailable'
 now=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'); rid='token-'+str(chain)+'-'+address.lower(); version='direct-'+now
 report={'schema_version':'0.2','report_id':rid,'report_version':version,'candidate_id':token,'identity':{'chain_id':int(chain),'address':address,'symbol':sym},'mode':'live','assessment':{'status':'not_assessed','label':None,'summary':'Source capture and legacy calculation draft; no Terra synthesis or proposed assessment has been produced.','unknowns':['Independent source corroboration','Finalized on-chain controls','Project attribution and activity','Model calibration','Human review'], 'supporting_claim_ids':[],'counterevidence_claim_ids':[]},'pillars':pillars,'evidence':evid,'artifacts':[],'review':{'status':'pending','reviewer':None,'reviewed_at':None,'reviewed_version':None,'content_sha256':None,'authentication':'none'},'limitations':['Direct-input prototype; no automated Terra reasoning or complete investigation.','Provider snapshots have different fetch times and no common finalized block.','No financial verdict, human approval or publication.']}
 history.store(out/'source-ledger.json',{'candidate_id':token,'sources':ledger,'history_status':h,'capture_status':c})
 tl={'profile':'scooby.pillar-tldr/1','report_id':rid,'report_version':version,'pillars':{}}
 for k in names:
  p=pillars[k]; tl['pillars'][k]=[{'role':'finding','text':cl['statement'],'claim_ids':[cl['id']],'evidence_ids':cl['supporting_evidence_ids']} for cl in p['claims'][:2]]
  if p['evidence_ids']: tl['pillars'][k].append({'role':'caveat','text':p['quality_issues'][0] if p['quality_issues'] else 'This is an unverified provider snapshot; coverage is incomplete.','claim_ids':[],'evidence_ids':[p['evidence_ids'][0]]})
 history.store(out/'pillar-tldr.json',tl)
 lines=['# Token investigation — partial draft','',f'Chain {chain}; address `{address}`; symbol {sym}.','',f'Report {rid} | version {version} | human review pending.','','This is a source-capture and legacy-calculation prototype. No Terra synthesis or final assessment has been made.']
 for k,p in pillars.items():
  lines+=['','## '+k.replace('_',' ').title(),'',p['summary'],'','Status: '+p['status']]
  for cl in p['claims']: lines.append('- '+cl['statement']+' ['+', '.join(cl['supporting_evidence_ids'])+']')
  for q in p['quality_issues']: lines.append('- Limitation: '+q)
  for item in p['measurements']: lines.append('- '+item['id']+': '+str(item['value'])+' ('+(item['unit'] or 'source scale')+').')
  for item in p['series']: lines.append('- '+item['id']+': '+str(len(item['points']))+' dated observations; exact points in report JSON.')
 lines+=['','## Source and method details','','See source-ledger.json and source evidence for URLs, capture times and byte hashes. The legacy metrics evidence preserves the full original output, including labels and limitations. No report approval is implied.','']
 (out/'report.md').write_text('\n'.join(lines),encoding='utf8')
 for kind,path,media in [('markdown','report.md','text/markdown'),('source_ledger','source-ledger.json','application/json'),('pillar_tldr','pillar-tldr.json','application/json')]: report['artifacts'].append({'kind':kind,'media_type':media,'availability':'available','path':path,'sha256':digest((out/path).read_bytes()),'report_id':rid,'report_version':version})
 report['artifacts'].append({'kind':'pdf','media_type':None,'availability':'unavailable','path':None,'sha256':None,'report_id':rid,'report_version':version}); schema.validate(out,report); history.store(out/'report.json',report); history.store(out/'digest.json',{'algorithm':'sha256','target':'report.json exact UTF-8 bytes','sha256':digest((out/'report.json').read_bytes()),'status':'pending; not approval'}); schema.verify_digest(out,load(out/'digest.json')['sha256']); return report
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__); p.add_argument('--history',required=True,type=pathlib.Path); p.add_argument('--sources',required=True,type=pathlib.Path); p.add_argument('--output',required=True,type=pathlib.Path); p.add_argument('--vae',type=pathlib.Path); a=p.parse_args(); r=build(a.history,a.sources,a.output,a.vae); print('PASS',r['candidate_id'],r['report_version'],{k:v['status'] for k,v in r['pillars'].items()})
