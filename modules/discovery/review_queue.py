"""HITL queue: eligible live candidates only; evidence-bound verifier results."""
import argparse, datetime as dt, hashlib, html, json, math, os, re, sqlite3, sys, tempfile
from pathlib import Path
import discovery, live_pilot, lp_concentration, market_activity

GROUP_NAMES={'G01':'Control','G02':'Transfer restrictions','G03':'Holder concentration','G04':'Liquidity removal control','G05':'Execution depth','G06':'Liquidity shape','G07':'LP concentration','G08':'Venue divergence','G09':'Market activity','G10':'Statistical stress','G11':'Trend','G12':'Indicator extremes'}
# Only code-reviewed metric-specific functions go here. Provider hints, database status strings,
# and arbitrary operator attestations cannot register a verifier or create a vote.
VERIFIERS={'G07':lp_concentration.verify,'G09':market_activity.verify}
POLICY='pilot-concerns-v1'

def evidence_check(record, root, evidence_ids, as_of, max_age_seconds):
 if not isinstance(evidence_ids,list) or not evidence_ids or any(not isinstance(v,str) or not v for v in evidence_ids):raise ValueError('missing evidence references')
 by_id={x.get('id'):x for x in record.get('evidence',[]) if isinstance(x,dict)}
 if len(by_id)!=len(record.get('evidence',[])):raise ValueError('duplicate or malformed evidence IDs')
 results=[]
 for eid in evidence_ids:
  e=by_id.get(eid)
  if not e or e.get('kind')!='live_observation':raise ValueError('live evidence missing')
  path=e.get('source'); digest=e.get('sha256');observed=e.get('observed_at')
  if not isinstance(path,str) or not re.fullmatch(r'snapshots/[0-9a-f]{64}\.json',path) or not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):raise ValueError('invalid evidence path or hash')
  target=root/path
  if target.is_symlink() or target.parent.is_symlink() or not target.resolve().is_relative_to(root.resolve()) or not target.is_file():raise ValueError('evidence path missing or unsafe')
  raw=target.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=digest or eid!=digest or target.name!=digest+'.json':raise ValueError('evidence digest mismatch')
  if not isinstance(observed,str) or not observed:raise ValueError('observation time unknown')
  timestamp=discovery.stamp(observed); age=(as_of-timestamp).total_seconds()
  if age<0 or age>max_age_seconds:raise ValueError('evidence timestamp future or stale')
  results.append({'id':eid,'source':path,'observed_at':observed,'sha256':digest})
 return results

def assess(record,root,as_of,verifiers=None,max_age_seconds=3600):
 if verifiers is None:verifiers=VERIFIERS
 if record.get('mode')!='live' or record.get('candidate_id')!=discovery.identity(record['identity']['chain_id'],record['identity']['address']):raise ValueError('candidate identity or live provenance invalid')
 groups=[]
 for group in live_pilot.GROUPS:
  row={'id':group,'name':GROUP_NAMES[group],'status':'held' if group in live_pilot.HELD else 'unknown','votes':0,'detail':'No validated metric-specific verifier is enabled.','measurements':[],'evidence':[]}
  verifier=verifiers.get(group)
  if verifier and group not in live_pilot.HELD:
   try:
    r=verifier(record,root,as_of)
    if not isinstance(r,dict) or 'triggered' not in r or (r['triggered'] is not None and not isinstance(r['triggered'],bool)) or not isinstance(r.get('detail'),str) or not r['detail'].strip() or not isinstance(r.get('measurements'),list):raise ValueError('invalid verifier output')
    if not r['measurements']:raise ValueError('a concrete measurement is required')
    for measurement in r['measurements']:
     if not isinstance(measurement,dict) or not isinstance(measurement.get('label','Value'),str) or not isinstance(measurement.get('unit',''),str):raise ValueError('invalid measurement metadata')
     value=measurement.get('value')
     if value is not None and not isinstance(value,(str,int,float,bool)):raise ValueError('invalid measurement value')
     if isinstance(value,float) and not math.isfinite(value):raise ValueError('non-finite measurement')
    e=evidence_check(record,root,r.get('evidence_ids'),as_of,max_age_seconds)
    row.update(status='unknown' if r['triggered'] is None else 'triggered' if r['triggered'] else 'not_triggered',votes=int(r['triggered'] is True),detail=r['detail'],measurements=r['measurements'],evidence=e)
   except (ValueError,KeyError,TypeError,OSError,OverflowError) as exc:row.update(status='unknown',detail='Verification unavailable: '+str(exc))
  groups.append(row)
 count=sum(x['votes'] for x in groups)
 return {'candidate_id':record['candidate_id'],'identity':record['identity'],'policy':POLICY,'as_of':as_of.isoformat(),'triggered_count':count,'evaluated_count':sum(r['status'] in ('triggered','not_triggered') for r in groups),'eligible':count>=4,'priority':'higher' if count>=5 else 'standard' if count>=4 else None,'groups':groups}

def queue(db,root,as_of=None,verifiers=None):
 as_of=as_of or dt.datetime.now(dt.timezone.utc); con=sqlite3.connect(db);items=[]; monitored=0
 for (raw,) in con.execute('SELECT record FROM candidates ORDER BY id'):
  record=json.loads(raw)
  if record.get('mode')!='live' or record.get('selection',{}).get('status')=='selected':continue
  monitored+=1
  try:item=assess(record,root,as_of,verifiers)
  except (ValueError,KeyError,TypeError):continue
  if item['eligible']:items.append(item)
 con.close();items.sort(key=lambda x:(-x['triggered_count'],x['candidate_id']))
 return {'policy':POLICY,'generated_at':as_of.isoformat(),'qualification':'4 verified concern groups; 5+ higher priority','candidates':items[:5],'qualified_count':len(items),'shown_count':min(len(items),5),'monitored_count':monitored,'metric_verifiers_enabled':len(VERIFIERS if verifiers is None else verifiers),'limitation':'Group results are screening signals, not fraud findings or authenticated human approval.'}

def html_page(q):
 esc=lambda v:html.escape(str(v),quote=True)
 blocks=[]
 for item in q['candidates']:
  ident=item['identity']; lines=[]
  for g in item['groups']:
   measurements='; '.join(esc(m.get('label','Value')+': '+str(m.get('value') if m.get('value') is not None else 'unknown')+(' '+m.get('unit','') if m.get('unit') else '')) for m in g['measurements']) or '—'
   evidence='; '.join("<a href='"+esc(e['source'])+"'>"+esc(e['id'][:16]+'…')+"</a> @ "+esc(e['observed_at']) for e in g['evidence']) or '—'
   lines.append(f"<tr><th scope='row'>{esc(g['name'])}</th><td>{esc(g['status'])}</td><td>{g['votes']} / 1</td><td>{esc(g['detail'])}</td><td>{measurements}</td><td>{evidence}</td></tr>")
  cid=esc(item['candidate_id'])
  blocks.append(f"<section><h2>{esc(ident['symbol'])} — chain {ident['chain_id']}</h2><p class='identity'>{cid}</p><p><strong>{item['triggered_count']} concern groups triggered</strong> · {item['evaluated_count']} evaluated · {esc(item['priority'])} priority</p><div class='scroll'><table><thead><tr><th>Concern</th><th>Result</th><th>Gate count</th><th>Why</th><th>Measurements</th><th>Evidence / observed</th></tr></thead><tbody>{''.join(lines)}</tbody></table></div><p>To choose this case, use the local selection command described in LIVE-PILOT.md with candidate ID <code>{cid}</code>.</p></section>")
 body=''.join(blocks) or ('<div class="empty"><h2>No verified candidates available yet</h2><p>Metric-specific screening checks are not enabled yet. The monitored leads have not been evaluated against the gate.</p></div>' if q['metric_verifiers_enabled']==0 else '<div class="empty"><h2>No candidates have passed the gate</h2><p>Unverified leads stay monitored. They will appear here only after four concern groups pass verification.</p></div>')
 return """<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Scooby DAO — review queue</title><style>body{font:16px system-ui,sans-serif;background:#f3f5f6;color:#17212b;margin:0}main{max-width:1200px;margin:auto;padding:32px 20px}h1{font-size:2rem;margin-bottom:8px}.meta{color:#435363}.empty,section{background:white;border:1px solid #ccd6dc;border-radius:12px;padding:22px;margin-top:22px}h2{font-size:1.3rem}.identity,code{overflow-wrap:anywhere}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;min-width:800px}th,td{text-align:left;padding:10px;border-bottom:1px solid #dce4e8;vertical-align:top}th{background:#f5f8fa}p{line-height:1.5}</style></head><body><main><h1>Candidate review queue</h1><p class='meta'>"""+esc(q['qualification'])+" · Generated "+esc(q['generated_at'])+"</p><p>"+str(q['qualified_count'])+" qualified · showing "+str(q['shown_count'])+" · "+str(q['monitored_count'])+" monitored</p><p>Concern results guide selection for investigation; they are not final findings. This is a point-in-time view; regenerate it for current results. Selection rechecks the gate.</p>"+body+"</main></body></html>"

def save_atomic(path,content):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as f:f.write(content);tmp=f.name
 os.replace(tmp,path)
def main():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--root',type=Path,required=True);sub=p.add_subparsers(dest='command',required=True)
 s=sub.add_parser('render');s.add_argument('--output',type=Path,required=True);s.add_argument('--json-output',type=Path,required=True)
 s=sub.add_parser('select');s.add_argument('--candidate-id',required=True);s.add_argument('--actor',required=True);s.add_argument('--reason',required=True)
 a=p.parse_args();q=queue(a.db,a.root)
 if a.command=='render':save_atomic(a.output,html_page(q));save_atomic(a.json_output,json.dumps(q,indent=2,ensure_ascii=False));print(json.dumps({'qualified':q['qualified_count'],'monitored':q['monitored_count'],'html':str(a.output),'json':str(a.json_output)}));return 0
 con=sqlite3.connect(a.db)
 try: row=con.execute('SELECT record FROM candidates WHERE id=?',(a.candidate_id,)).fetchone()
 finally: con.close()
 if not row or not assess(json.loads(row[0]),a.root,dt.datetime.now(dt.timezone.utc))['eligible']:raise ValueError('candidate is not currently eligible; gate must be re-evaluated before selection')
 con=sqlite3.connect(a.db)
 try:result=discovery.action(con,a.candidate_id,'select',a.actor,a.reason)
 finally:con.close()
 updated=queue(a.db,a.root)
 save_atomic(a.root/'review-queue.html',html_page(updated))
 save_atomic(a.root/'review-queue.json',json.dumps(updated,indent=2,ensure_ascii=False))
 print(json.dumps(result,indent=2));return 0
if __name__=='__main__':
 try:raise SystemExit(main())
 except (ValueError,OSError,sqlite3.Error) as exc:print(str(exc),file=sys.stderr);raise SystemExit(1)
