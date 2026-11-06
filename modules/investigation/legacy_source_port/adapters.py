"""Offline source adapters. All numerical definitions are original legacy functions."""
import copy,math,types
from decimal import Decimal
try:
 from .legacy import market_score,mev,lp,locks,control_score,swapmath,cliffs
except ImportError:
 from legacy import market_score,mev,lp,locks,control_score,swapmath,cliffs

def finite(x):
 if isinstance(x,float) and not math.isfinite(x):raise ValueError('non-finite input')
 if isinstance(x,dict):
  for v in x.values():finite(v)
 elif isinstance(x,list):
  for v in x:finite(v)

def replay_market(raw):
 finite(raw);v=raw['venues'][0];d=v['depth'];c=v['lpConcentration'];cs=v['cliffs']
 kwargs={'depth_up_5':d['up']['pct5']['notionalQuote'],'depth_down_5_quote':d['down']['pct5']['notionalQuote'],'depth_up_10':d['up']['pct10']['notionalQuote'],'depth_down_10':d['down']['pct10']['notionalQuote'],'max_deltaL_ratio_near':max((x['deltaLRatio'] for x in cs),default=0.0),'cliff_within_100':any(abs(x['tick']-v['tick'])<=100 for x in cs),'active_liq_ratio':v['activeLiquidityRatio'],'top1_share':c['top1Share'],'top5_share':c['top5Share'],'hhi':c['hhi'],'cross_spread_bps':raw['crossVenueSpreadBps'],'mev_badge':raw['mevExposure']['evidence']['sandwichDensity']}
 score=market_score.microstructure_score(**kwargs);proxy=mev.mev_exposure_proxy(kwargs['depth_up_5'],v['slippageCurve']);issues=[]
 if int(v['liquidity'])==0:issues.append('Zero reported active liquidity: legacy slippage fallback is not executable depth.')
 if c['sampledPositions']==0:issues.append('No sampled LP owners; zero concentration values are legacy empty-sample sentinels, not decentralization.')
 if raw['crossVenueSpreadBps']==0:issues.append('Legacy runner hardcodes zero cross-venue spread for its single-venue implementation; not observed market-wide price agreement.')
 return {'status':'partial','payload':{'microstructure_score':score,'mevExposure':proxy,'original_inputs':kwargs,'quality_issues':issues,'scope':'Exact calculation replay from captured historical venue fields; no source collection or safety conclusion.'}}

def lp_from_captured_positions(positions,complete):
 if complete is not True:return {'status':'unavailable','payload':{'reason':'Positions capture incomplete or failed; zero values not substituted.'}}
 finite(positions)
 # Bind the unchanged original aggregation function to an in-memory captured source.
 env={**lp.lp_concentration.__globals__,'GraphQLClient':lambda _:None,'_fetch_positions_any':lambda *_:copy.deepcopy(positions)}
 fn=types.FunctionType(lp.lp_concentration.__code__,env)
 result=fn('offline-captured-source','0x'+'1'*40,0)
 return {'status':'partial','payload':{'legacy_lpConcentration':result,'quality_issues':['sampledPositions counts aggregated owners in the original code, not NFT positions.','Source pagination completeness and owner identity are separate from aggregation arithmetic.']}}

def v3_from_captured_state(data):
 finite(data);s=data['state'];ticks=data.get('ticks')
 if ticks is None or data.get('ticks_complete') is not True:return {'status':'unavailable','payload':{'reason':'Missing or incomplete captured tick window; no synthetic tick inserted.'}}
 if not ticks:return {'status':'unavailable','payload':{'reason':'Empty tick capture; explicit original sparse fallback replay can be tested separately, not inferred as observed liquidity.'}}
 raw=swapmath.notional_for_pct_moves(s['sqrtP'],s['tick'],s['L'],ticks,fee_bps=s['fee'])
 depth={'up':{},'down':{}};scale0=10**s['decimals0'];scale1=10**s['decimals1'];S=swapmath.sqrtX96_to_unscaled_sqrt(s['sqrtP']);price=float(S*S)*10**(s['decimals0']-s['decimals1'])
 for k,v in raw['up'].items():depth['up'][k]=float(v/scale1)
 for k,v in raw['down'].items():depth['down'][k]=float((v/scale0)*price)
 trades=[x*scale1 for x in data['trade_sizes_quote']];curve=swapmath.slippage_curve_for_quote_in(s['sqrtP'],s['tick'],s['L'],ticks,trades,fee_bps=s['fee']);curve=[{'notionalQuote':x['notionalQuote']/scale1,'slippagePct':x['slippagePct']} for x in curve]
 return {'status':'partial','payload':{'depth_quote':depth,'slippageCurve':curve,'cliffs':cliffs.detect_liquidity_cliffs(ticks,s['tick'],window_ticks=200),'activeLiquidityRatio':cliffs.active_liquidity_ratio(ticks,s['tick'],s['L'],band_ticks=600),'quality_issues':['Original token0/token1 orientation and asymmetric down-target definition retained.','Legacy zero-liquidity and sparse-ladder fallbacks are not executable-price evidence.','No market-wide coverage, live quote, LP source validation or independent math calibration implied.']}}

def replay_control_score(raw):
 finite(raw);f=raw['facts'];required=('owner','ownershipModel','renounced','multisig','proxy','pauseStatus','mintBurnPrimitives','blacklistPrimitives','taxPrimitives','maxTxPrimitives','supply','liquidity','honeypot');missing=[k for k in required if k not in f]
 for parent,key in [('multisig','isSafe'),('proxy','type'),('proxy','admin'),('supply','topHolders'),('liquidity','pair'),('liquidity','lpLocked'),('honeypot','risk')]:
  if parent in f and (not isinstance(f[parent],dict) or key not in f[parent]):missing.append(parent+'.'+key)
 if f.get('multisig',{}).get('isSafe') and 'threshold' not in f['multisig']:missing.append('multisig.threshold')
 if f.get('liquidity',{}).get('lpLocked') and 'pctLocked' not in f['liquidity'].get('lockEvidence',{}):missing.append('liquidity.lockEvidence.pctLocked')
 if missing:return {'status':'unavailable','payload':{'reason':'Required legacy facts missing; defaults not promoted into a new score.','missing':missing}}
 return {'status':'partial','payload':{'legacy_summary':control_score.compute_score(f,raw['flags']),'quality_issues':['Original fundamentals_score here is contract mechanics scoring, not project-fundamental or honeypot certification.','Primitive absence, empty holders and unknown pause state remain scope limitations.','Flag list is accepted but not used by the original score function.']}}

def lock_from_captured_balances(data):
 required=('total_supply','known_lockers','dead_addresses','balances','complete')
 if any(k not in data for k in required) or data['complete'] is not True:return {'status':'unavailable','payload':{'reason':'Incomplete LP balance capture; no false unlocked/zero-lock inference.'}}
 addresses=data['known_lockers']+data['dead_addresses'];missing=[a for a in addresses if a not in data['balances']]
 if missing:return {'status':'unavailable','payload':{'reason':'Missing LP address balances.','missing':missing}}
 if int(data['total_supply'])<=0:return {'status':'unavailable','payload':{'reason':'LP total supply unavailable/zero; legacy zero percentage cannot establish withdrawability.'}}
 class Call:
  def __init__(self,value):self.value=value
  def call(self):return int(self.value)
 class Functions:
  def totalSupply(self):return Call(data['total_supply'])
  def balanceOf(self,a):return Call(data['balances'][a])
 class W3:
  def to_checksum_address(self,a):return a
  @property
  def eth(self):return self
  def contract(self,**_):return types.SimpleNamespace(functions=Functions())
 env={**locks.lp_locked_evidence_v2.__globals__,'Web3':W3(),'UNIV2_PAIR_ABI':[]};fn=types.FunctionType(locks.lp_locked_evidence_v2.__code__,env);result=fn(W3(),data['pair'],data['known_lockers'],data['dead_addresses'])
 return {'status':'partial','payload':{'legacy_lock_result':result,'quality_issues':['Original >=50 percent label retained. Balance at a known locker is not proof of beneficiary, unlock date or irrevocable lock.','Dead-address lists and locker lists require independent identity/configuration validation.']}}

def fundamentals_from_capture(raw,binding):
 if not binding or binding.get('status')!='evidence_bound' or not binding.get('candidate_id') or not binding.get('evidence_ids'):return {'status':'unavailable','payload':{'reason':'No evidence-bound exact-contract project attribution. Ticker match and empty GitHub search cannot establish project activity.'}}
 return {'status':'partial','payload':{'legacy_structured_fields':{k:copy.deepcopy(raw[k]) for k in ('coin','github_activity','market_data') if k in raw},'attribution':copy.deepcopy(binding),'quality_issues':['Attribution assertion/source evidence must be independently reviewed.','Original thesis and sentiment prose are excluded from trusted observations without underlying post/source evidence.','Missing or zero repository search results do not establish no development.']}}

def privileges_from_captured_source(abi,source_code,pause_status):
 try:
  from .legacy import privileges
 except ImportError:
  from legacy import privileges
 if abi is None:return {'status':'unavailable','payload':{'reason':'ABI capture missing; no empty primitive list substituted.'}}
 if pause_status not in ('paused','unpaused',None):raise ValueError('invalid captured pause state')
 env={**privileges.privileged_facts.__globals__,'read_pause_status':lambda *_:pause_status};fn=types.FunctionType(privileges.privileged_facts.__code__,env);result=fn(None,'captured-token',abi,source_code)
 return {'status':'partial','payload':{'legacy_privileged_facts':result,'quality_issues':['Original substring heuristic retained; matches in comments or unrelated names can occur.','ABI/source keyword absence does not prove no hidden/external transfer restriction.','Pause result must be separately pinned and source/control path independently reviewed.']}}
