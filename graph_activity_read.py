"""Local-operator capture import and read-only Graph activity evaluation; no network calls."""
import base64,datetime as dt,json,sys
from pathlib import Path
from store import ROOT,db,digest,dumps,now
sys.path.insert(0,str(ROOT/'modules'/'discovery'))
import graph_activity_30d as graph


def _encode_capture(c):
 return {**c,'raw':base64.b64encode(c['raw']).decode('ascii')}
def _decode_capture(c):
 return {**c,'raw':base64.b64decode(c['raw'],validate=True)}
def _unknown(case_id,cid,reason,**extra):
 return {'source_type':'graph_token_hour','decision_scope':'ethereum_uniswap_v3_token','status':'unknown','reason':reason,'case_id':case_id,'candidate_id':cid,'source_authentication':'local_operator_capture_not_independently_authenticated','gate_effect':'none',**extra}
def install(case_id,graph_capture,fx_capture):
 """Trusted local process only; paths, timestamps and source authenticity are not user proof."""
 with db() as c:
  row=c.execute('SELECT candidate_id FROM cases WHERE id=?',(case_id,)).fetchone()
  if not row: raise ValueError('case not found')
  cid=row['candidate_id']
  at=dt.datetime.now(dt.timezone.utc)
  prior=(at.date()-dt.timedelta(days=1)).isoformat()
  graph.common._url(fx_capture['url'],'api.frankfurter.dev','/v2/providers/ecb/rate/usd/inr',{'date':[prior]})
  fx_doc=graph.common._read(fx_capture,at)
  if fx_doc.get('base')!='USD' or fx_doc.get('quote')!='INR' or graph.common._number(fx_doc['rate'],'fx_rate_invalid')<=0:raise ValueError('fx capture invalid')
  result=graph.evaluate(cid,graph_capture,fx_capture,at)
  if result['reason'] not in ('threshold_met_in_indexed_scope','broader_venue_coverage_required','incomplete_hourly_coverage'):
   raise ValueError('capture rejected: '+result['reason'])
  doc={'profile':'scooby.local-graph-activity-input/1','case_id':case_id,'candidate_id':cid,'graph':_encode_capture(graph_capture),'fx':_encode_capture(fx_capture)}
  encoded=dumps(doc);sha=digest(encoded.encode())
  c.execute('INSERT OR IGNORE INTO graph_activity_inputs VALUES(?,?,?,?,?)',(sha,case_id,cid,encoded,now()))
 return {'case_id':case_id,'candidate_id':cid,'input_sha256':sha,'status':result['status']}

def read(case_id):
 with db() as c:
  case=c.execute('SELECT candidate_id FROM cases WHERE id=?',(case_id,)).fetchone()
  if not case:return None
  row=c.execute('SELECT * FROM graph_activity_inputs WHERE case_id=? ORDER BY created DESC,source_sha256 DESC LIMIT 1',(case_id,)).fetchone()
  if not row:return _unknown(case_id,case['candidate_id'],'no_capture')
  raw=row['source_json']
  if digest(raw.encode())!=row['source_sha256']:raise ValueError('stored activity integrity failure')
  doc=json.loads(raw)
  if (doc['case_id'],doc['candidate_id'])!=(case_id,case['candidate_id']):raise ValueError('stored activity identity failure')
  gc=_decode_capture(doc['graph']);fx=_decode_capture(doc['fx']);at=dt.datetime.now(dt.timezone.utc)
  expected_end=int(at.replace(minute=0,second=0,microsecond=0).timestamp())
  if gc['variables'].get('end')!=expected_end:
   return _unknown(case_id,case['candidate_id'],'capture_window_expired',historical_window_end_utc=dt.datetime.fromtimestamp(gc['variables']['end'],dt.timezone.utc).isoformat(),input_sha256=row['source_sha256'])
  result=graph.evaluate(case['candidate_id'],gc,fx,at)
  if result['status']!='unknown':
   source=result['source'];end=dt.datetime.fromtimestamp(gc['variables']['end'],dt.timezone.utc)
   deadline=min(graph.common._stamp(gc['fetched_at'])+dt.timedelta(hours=1),graph.common._stamp(fx['fetched_at'])+dt.timedelta(hours=1),dt.datetime.fromtimestamp(source['indexed_block_timestamp'],dt.timezone.utc)+dt.timedelta(hours=1),end+dt.timedelta(hours=1))
   if at>=deadline:
    return _unknown(case_id,case['candidate_id'],'capture_expired',input_sha256=row['source_sha256'])
   result['valid_until_utc']=deadline.isoformat()
  result.update(source_type='graph_token_hour',case_id=case_id,input_sha256=row['source_sha256'],source_authentication='local_operator_capture_not_independently_authenticated',gate_effect='none')
  return result

if __name__=='__main__':
 import argparse,hashlib
 p=argparse.ArgumentParser(description='Local operator import only; no source or model calls.')
 p.add_argument('case_id');p.add_argument('--capture-status',required=True);p.add_argument('--fx-status',required=True);p.add_argument('--graph-bytes',required=True);p.add_argument('--fx-bytes',required=True)
 a=p.parse_args();manifest=json.loads(Path(a.capture_status).read_bytes());fs=json.loads(Path(a.fx_status).read_bytes())
 entries=[x for x in manifest['requests'] if x.get('source')=='graph' and x.get('status')=='captured']
 if len(entries)!=1 or fs.get('status')!='captured' or manifest.get('query_sha256')!=hashlib.sha256(graph.QUERY.encode()).hexdigest():raise SystemExit('capture metadata invalid')
 e=entries[0]
 gc={'url':e['url'],'fetched_at':e['fetched_at_utc'],'raw':Path(a.graph_bytes).read_bytes(),'sha256':e['sha256'],'query':graph.QUERY,'variables':manifest['variables']}
 fx={'url':fs['url'],'fetched_at':fs['fetched_at_utc'],'raw':Path(a.fx_bytes).read_bytes(),'sha256':fs['sha256']}
 with db() as c: row=c.execute('SELECT candidate_id FROM cases WHERE id=?',(a.case_id,)).fetchone()
 if not row or row['candidate_id']!=manifest.get('candidate_id'):raise SystemExit('case/capture identity mismatch')
 print(json.dumps(install(a.case_id,gc,fx)))
