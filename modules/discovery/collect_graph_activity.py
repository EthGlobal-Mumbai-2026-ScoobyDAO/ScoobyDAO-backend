"""One explicitly invoked Graph query and FX query; no retries or automatic runs."""
import argparse,datetime as dt,hashlib,json,os,re,urllib.error,urllib.request
from pathlib import Path
import graph_activity_30d as graph

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
def stamp():return dt.datetime.now(dt.timezone.utc).isoformat()
def save(path,obj):
 raw=(json.dumps(obj,indent=2)+'\n').encode();tmp=path.with_suffix('.tmp')
 with tmp.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 os.replace(tmp,path)
def main():
 p=argparse.ArgumentParser();p.add_argument('--candidate-id',required=True);p.add_argument('--output',required=True,type=Path);args=p.parse_args()
 if not re.fullmatch(r'1:0x[0-9a-f]{40}',args.candidate_id):p.error('canonical Ethereum token identity required')
 key=os.environ.get('THE_GRAPH_API_KEY','').strip()
 if not key:
  try:
   import winreg
   with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as reg:key=winreg.QueryValueEx(reg,'THE_GRAPH_API_KEY')[0].strip()
  except (OSError,ImportError):pass
 if not key:print('Graph credential unavailable; no request made.');return 2
 args.output.mkdir(parents=True,exist_ok=False);started=dt.datetime.now(dt.timezone.utc);end=started.replace(minute=0,second=0,microsecond=0);start=end-dt.timedelta(hours=720)
 variables={'token':args.candidate_id[2:],'start':int(start.timestamp()),'end':int(end.timestamp())};body=json.dumps({'query':graph.QUERY,'variables':variables}).encode()
 manifest={'candidate_id':args.candidate_id,'subgraph_id':graph.SUBGRAPH,'started_at_utc':stamp(),'max_graph_requests':1,'max_fx_requests':1,'query_sha256':hashlib.sha256(graph.QUERY.encode()).hexdigest(),'variables':variables,'requests':[]};path=args.output/'capture-status.json';save(path,manifest)
 opener=urllib.request.build_opener(NoRedirect())
 fx_url='https://api.frankfurter.dev/v2/providers/ecb/rate/usd/inr?date='+(end.date()-dt.timedelta(days=1)).isoformat()
 for name,url,data,headers in [('graph',graph.URL,body,{'Authorization':'Bearer '+key,'Content-Type':'application/json'}),('fx',fx_url,None,{'Accept':'application/json'})]:
  row={'source':name,'url':url,'status':'reserved','requested_at_utc':stamp()};manifest['requests'].append(row);save(path,manifest)
  try:
   req=urllib.request.Request(url,data=data,headers={**headers,'User-Agent':'ScoobyDAO-GraphActivity/1.0'})
   with opener.open(req,timeout=20) as r:raw=r.read(3_000_001);row['http_status']=r.status
   if len(raw)>3_000_000 or key.encode() in raw:raise ValueError('unsafe response')
   json.loads(raw);file=args.output/(name+'-response.json')
   with file.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
   row.update(status='captured',fetched_at_utc=stamp(),sha256=hashlib.sha256(raw).hexdigest(),path=file.name);save(path,manifest)
  except (urllib.error.HTTPError,urllib.error.URLError,OSError,ValueError,TypeError) as exc:
   row.update(status='unavailable',http_status=getattr(exc,'code',None),fetched_at_utc=stamp(),error_type=type(exc).__name__);save(path,manifest);print(name+' unavailable; stopped without retry.');return 1
 now=dt.datetime.now(dt.timezone.utc)
 if now.replace(minute=0,second=0,microsecond=0)!=end:manifest['status']='hour_boundary_crossed';save(path,manifest);print('Hour boundary crossed; capture is not eligible.');return 1
 first,second=manifest['requests'];gc={'url':first['url'],'fetched_at':first['fetched_at_utc'],'raw':(args.output/first['path']).read_bytes(),'sha256':first['sha256'],'query':graph.QUERY,'variables':variables};fc={'url':second['url'],'fetched_at':second['fetched_at_utc'],'raw':(args.output/second['path']).read_bytes(),'sha256':second['sha256']}
 result=graph.evaluate(args.candidate_id,gc,fc,now);save(args.output/'activity.json',result);manifest.update(status='evaluated',completed_at_utc=stamp());save(path,manifest);print(json.dumps({'status':result['status'],'reason':result['reason'],'observed_hours':result['coverage']['observed_hours']}));return 0
if __name__=='__main__':raise SystemExit(main())
