"""Offline mechanism evidence evaluator. Does not collect data or send transactions."""
import argparse,copy,hashlib,json,pathlib,re
CHECKS=('identity_route','balance','allowance','gas','deadline','slippage','liquidity','ordinary_tax','launch_controls','engine_support')
PILLARS=('microstructure','onchain','fundamentals','statistical_risk','technical_health')
ADDRESS=re.compile(r'^0x[0-9a-fA-F]{40}$'); HASH=re.compile(r'^0x[0-9a-fA-F]{64}$')

def read(p): return json.loads(pathlib.Path(p).read_text(encoding='utf-8-sig'))
def digest(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def require(value,message):
 if not value:raise ValueError(message)
def validate(packet,root):
 root=pathlib.Path(root).resolve();require(packet.get('profile')=='scooby.mechanism-observations/1','unknown profile')
 chain,address=packet['candidate_id'].split(':');require(chain in ('1','8453') and ADDRESS.fullmatch(address),'invalid identity')
 b=packet['block'];require(type(b['number']) is int and b['number']>=0 and HASH.fullmatch(b['hash']) and b['observed_at'].endswith('Z'),'block number/hash/UTC time required')
 require(packet['environment']['mode'] in ('offline_fixture','local_fork','read_only_simulation'),'unapproved environment')
 require(packet['environment']['engine'] and packet['environment']['version'],'engine version missing')
 ids={e['id'] for e in packet['evidence']};require(len(ids)==len(packet['evidence']),'duplicate evidence ID')
 for e in packet['evidence']:
  path=e['path'];require(isinstance(path,str) and path and not any(x in path for x in ('\\',':','%','?','#')) and all(x not in ('','.','..') for x in path.split('/')),'unsafe evidence path')
  p=root/path;require(p.resolve().is_relative_to(root) and p.is_file() and not any(x.is_symlink() for x in [p,*p.parents] if x!=root.parent),'missing/escaping evidence')
  require(digest(p)==e['sha256'],'evidence hash mismatch')
 require(set(packet['mechanism']['evidence_ids'])<=ids,'unresolved mechanism evidence')
 seen=set()
 for s in packet['scenarios']:
  require(s['id'] not in seen,'duplicate scenario');seen.add(s['id'])
  require(s['block_hash']==b['hash'],'mixed block state')
  require(ADDRESS.fullmatch(s['wallet']) and ADDRESS.fullmatch(s['router']) and ADDRESS.fullmatch(s['pool']),'scenario addresses missing')
  require(s['role'] in ('ordinary','privileged','unknown') and s['direction'] in ('buy','sell'),'invalid scenario role/direction')
  require(s['outcome'] in ('success','token_restriction','execution_failure','unknown'),'invalid outcome')
  require(s['input_amount'].isdigit() and int(s['input_amount'])>0 and s['received_amount'].isdigit(),'amounts must be unsigned base-unit strings')
  require(s['state_id'] and s['sequence_id'] and s['overrides'] is not None,'state provenance missing')
  require(set(s['controls'])==set(CHECKS) and all(x is None or type(x) is bool for x in s['controls'].values()),'control coverage required')
  require(s['evidence_ids'] and set(s['evidence_ids'])<=ids,'scenario evidence missing')
  require(set(s['trace_evidence_ids'])<=ids,'unresolved trace')
  proof=s['sequence_proof'];require(proof['mode'] in ('atomic_trace','fork_sequence','isolated_calls'),'invalid sequence proof mode')
  require(set(proof['evidence_ids'])<=ids,'unresolved sequence proof')
  require(s['balance_before'].isdigit() and s['balance_after'].isdigit() and s['pre_state_id'] and s['post_state_id'],'balance and state lineage required')
 return packet

def evaluate(packet,root):
 validate(packet,root);m=packet['mechanism'];sc=packet['scenarios'];qualified=[];success=[];unresolved=[]
 def coherent_buy(s):
  proof=s['sequence_proof']
  if proof['mode']=='isolated_calls' or not proof['evidence_ids'] or proof['review_status']!='reviewed':return False
  return any(x['id']==s['parent_scenario_id'] and x['direction']=='buy' and x['outcome']=='success' and int(x['received_amount'])>0 and int(x['balance_after'])-int(x['balance_before'])==int(x['received_amount']) and int(s['balance_before'])>=int(s['input_amount']) and s['balance_before']==x['balance_after'] and s['pre_state_id']==x['post_state_id'] and x['wallet']==s['wallet'] and x['router']==s['router'] and x['pool']==s['pool'] and x['sequence_id']==s['sequence_id'] and x['replication_id']==s['replication_id'] and x['output_asset']==packet['candidate_id'] and s['input_asset']==packet['candidate_id'] and x['input_asset']==s['output_asset'] and all(v is True for v in x['controls'].values()) for x in sc)
 for s in sc:
  controlled=all(v is True for v in s['controls'].values())
  if s['direction']=='sell' and s['role']=='ordinary' and controlled and s['outcome']=='success' and int(s['received_amount'])>0:success.append(s)
  elif s['direction']=='sell' and s['role']=='ordinary' and controlled and s['outcome']=='token_restriction' and s['trace_evidence_ids'] and coherent_buy(s) and not s['overrides']:qualified.append(s)
  elif s['direction']=='sell':unresolved.append(s['id'])
 mechanism=all(m.get(k) is True for k in ('runtime_matched','control_path_attributed','controller_state_pinned')) and bool(m['evidence_ids']) and m.get('review',{}).get('status')=='reviewed' and bool(m.get('review',{}).get('record_id'))
 wallets={s['wallet'] for s in qualified};replications={s['replication_id'] for s in qualified}
 coverage={'ordinary_wallet_count':len(wallets),'replication_id_count':len(replications),'independence':'not_established_by_ID_counts'}
 if qualified:
  status='selective_restriction_reproduced' if success else 'restriction_reproduced'
 elif success:status='no_restriction_observed_in_tested_scope'
 else:status='inconclusive'
 # No autonomous warning or sufficiency threshold is authorized by this helper.
 return {'profile':'scooby.mechanism-evaluation/1','candidate_id':packet['candidate_id'],'block':packet['block'],'status':status,'restriction_scenario_ids':[s['id'] for s in qualified],'successful_ordinary_sell_ids':[s['id'] for s in success],'unresolved_scenario_ids':unresolved,'source_control_attributed':mechanism,'coverage':coverage,'source_provenance':'supplied_review_assertions_require_independent_check','proposed_interpretation':'Review the observed scope, successes, trace/source evidence and alternatives before any warning.','live_verdict':'not_determined','limits':['Input records require source/trace review; hashes prove integrity, not truth.','Successful ordinary sells constrain a universal claim and require a selective-mechanism explanation.','Offline fixtures are software controls and never support a live token verdict.','No safety certification, calibrated probability, human sign-off or publication is established.']}

def neutral_payload(packet):
 # Expected labels/reference verdicts and this evaluator's output never enter synthesis.
 top=('profile','candidate_id','block','environment','evidence','mechanism','scenarios','pillar_coverage')
 d={k:copy.deepcopy(packet[k]) for k in top}
 d['block']={k:packet['block'][k] for k in ('number','hash','observed_at')}
 d['environment']={k:packet['environment'][k] for k in ('mode','engine','version')}
 d['mechanism']={k:packet['mechanism'][k] for k in ('runtime_matched','control_path_attributed','controller_state_pinned','evidence_ids','review')}
 d['mechanism']['review']={k:packet['mechanism']['review'][k] for k in ('status','record_id','evidence_ids')}
 d['evidence']=[{k:e[k] for k in ('id','path','sha256')} for e in packet['evidence']]
 d['pillar_coverage']={k:{'status':packet['pillar_coverage'][k]['status'],'reason':packet['pillar_coverage'][k]['reason']} for k in PILLARS}
 permitted=('id','wallet','role','direction','router','pool','input_amount','received_amount','block_hash','state_id','sequence_id','replication_id','overrides','outcome','controls','evidence_ids','trace_evidence_ids','input_asset','output_asset','parent_scenario_id','pre_state_id','post_state_id','balance_before','balance_after','sequence_proof')
 d['scenarios']=[{k:s[k] for k in permitted} for s in packet['scenarios']]
 for scenario in d['scenarios']:
  scenario['sequence_proof']={k:scenario['sequence_proof'][k] for k in ('mode','review_status','evidence_ids')}
 d['question']='Explain observed behavior, alternatives, counterevidence and coverage at the stated state. Decide whether any scoped warning is supported. You may disagree or be inconclusive.'
 return d

def producer(packet_path,selection):
 """Explicit backend boundary. Caller authenticates selection before invoking."""
 path=pathlib.Path(packet_path);p=read(path);validate(p,path.parent)
 require(selection.get('candidate_id')==p['candidate_id'],'selection identity mismatch')
 require(selection.get('decision') in ('selected','diagnostic_exception') and selection.get('record_id'),'recorded selection required')
 return {'status':'partial','payload':neutral_payload(p)}

def bind_for_report(packet,report,root):
 validate(packet,root)
 require(packet['candidate_id']==report['candidate_id'],'report candidate mismatch')
 result=copy.deepcopy(packet)
 result['report_id']=report['report_id'];result['report_version']=report['report_version']
 return result

if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('packet',type=pathlib.Path);a.add_argument('--output',type=pathlib.Path,required=True);args=a.parse_args();p=read(args.packet);result=evaluate(p,args.packet.parent)
 if args.output.exists():raise ValueError('choose a new output file')
 args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');print(result['status'])
