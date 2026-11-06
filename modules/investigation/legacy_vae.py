"""Execute the original legacy VAE and risk/technical code using validated captured data."""
import argparse, ast, csv, hashlib, json, os, pathlib, subprocess, sys
from datetime import date
try:
 from . import history
except ImportError:
 import history
def sha(b): return hashlib.sha256(b).hexdigest()
def load(p): return json.loads(pathlib.Path(p).read_text(encoding='utf8'))
def run(source,out,days,legacy_repo):
 LEGACY=pathlib.Path(legacy_repo).resolve()
 source=pathlib.Path(source); out=pathlib.Path(out)
 if out.exists(): raise ValueError('output exists; select a new directory')
 if days<1: raise ValueError('horizon must be a positive integer')
 status=load(source/'source-status.json'); candidate=status['candidate_id']; chain,address=candidate.split(':',1); history.identity(int(chain),address)
 if [q.get('path') for q in status['requests']]!=['pools.json','daily.json']: raise ValueError('unexpected source snapshot paths')
 for req in status['requests']:
  path=source/req.get('path','');
  if not path.is_file() or sha(path.read_bytes())!=req.get('sha256'): raise ValueError('source hash mismatch or unavailable')
 chosen,_=history.select_pool(load(source/'pools.json'),int(chain),address,status['pool']['address'])
 if chosen['side']!=status['pool']['side']: raise ValueError('pool token side mismatch')
 calc=history.prepare(load(source/'daily.json'),status['history']['cutoff_utc_date']); recorded=load(source/'returns.json')
 if calc!=recorded: raise ValueError('stored returns do not match source candles')
 if calc['gaps'] or len(calc['returns'])<2: raise ValueError('pending history: need consecutive closed daily returns; no values fabricated')
 # Two observations are the computational minimum for sample covariance, not a validated adequacy threshold.
 try:
  import torch,numpy as np,pandas as pd,scipy
  from scipy.stats import norm
 except ImportError as e: raise RuntimeError('VAE runtime missing; install torch, numpy, pandas and scipy in an isolated environment') from e
 out.mkdir(parents=True); data=out/'output'; data.mkdir();
 with (data/'crypto_returns.csv').open('w',newline='',encoding='utf8') as f:
  w=csv.writer(f); w.writerow(['datetime','TOKEN']); w.writerows((x['date'],x['return']) for x in calc['returns'])
 vae=LEGACY/'vae.py'; pre=LEGACY/'precompute.py'; child_env=os.environ.copy(); child_env['PYTHONUTF8']='1'; proc=subprocess.run([sys.executable,str(vae)],cwd=out,env=child_env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8',timeout=600)
 (out/'training.log').write_text(proc.stdout+'\n'+proc.stderr,encoding='utf8');
 if proc.returncode: raise RuntimeError('legacy VAE failed; inspect local training.log')
 series=data/'vae'/'VAE_TOKEN.csv'; raw=pd.read_csv(series,parse_dates=['datetime'],index_col='datetime');
 if raw.shape[1]!=50: raise ValueError('legacy output must have exactly 50 reconstructions')
 # Extract the original definitions as Python AST: importing the full legacy app executes unrelated
 # I/O and loads unrelated credentials. Function/class bodies remain unchanged.
 src=pre.read_text(encoding='utf8'); tree=ast.parse(src); wanted={'CryptoTechnicalAnalyzer','var_cov_var','calculate_vae_risk_metrics'}; nodes=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in wanted]
 if {x.name for x in nodes}!=wanted: raise RuntimeError('legacy method definitions missing')
 env={'np':np,'pd':pd,'norm':norm,'sqrt':__import__('math').sqrt,'os':os}; exec(compile(ast.Module(body=nodes,type_ignores=[]),str(pre),'exec'),env)
 old=os.getcwd()
 try:
  os.chdir(out.resolve()); risk=env['calculate_vae_risk_metrics']('TOKEN',0.95,days); technical=env['CryptoTechnicalAnalyzer'](raw,list(raw.columns)); metrics=technical.generate_health_metrics(); series_out=technical.get_time_series_data(days=30)
 finally: os.chdir(old)
 if 'error' in risk: raise RuntimeError('legacy risk calculation failed: '+str(risk['error']))
 history.store(out/'legacy-metrics.json',{'identity':candidate,'risk_assessment':risk,'technical_health':metrics,'technical_series':series_out})
 history.store(out/'run-manifest.json',{'candidate_id':candidate,'source_status_sha256':sha((source/'source-status.json').read_bytes()),'source_candles_sha256':sha((source/'daily.json').read_bytes()),'input_returns_sha256':sha((data/'crypto_returns.csv').read_bytes()),'reconstructions_sha256':sha(series.read_bytes()),'metrics_sha256':sha((out/'legacy-metrics.json').read_bytes()),'legacy_vae_sha256':sha(vae.read_bytes()),'legacy_precompute_sha256':sha(pre.read_bytes()),'reconstructions':int(raw.shape[1]),'return_rows':len(raw),'first_date':str(raw.index.min()),'last_date':str(raw.index.max()),'alpha':0.95,'days':days,'randomness':'original unseeded legacy script; outputs vary across runs','dependencies':{'torch':torch.__version__,'numpy':np.__version__,'pandas':pd.__version__,'scipy':scipy.__version__},'limitations':['Legacy metrics and labels reproduced, not independently calibrated.','Two returns is a computation minimum, not proof of sufficient history.','No inference from a different token and no model call.']})
 return out/'legacy-metrics.json'
if __name__=='__main__':
 a=argparse.ArgumentParser(description=__doc__); a.add_argument('--source',required=True,type=pathlib.Path); a.add_argument('--output',required=True,type=pathlib.Path); a.add_argument('--days',required=True,type=int,help='explicit legacy VaR horizon in days'); a.add_argument('--legacy-repo',required=True,type=pathlib.Path); x=a.parse_args(); print('Wrote',run(x.source.resolve(),x.output.resolve(),x.days,x.legacy_repo))
