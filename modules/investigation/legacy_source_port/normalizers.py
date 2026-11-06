"""Normalize archived read-only result records. Never turns failed calls into zero."""
def rpc_result(record,expected_block):
 if record.get('block_hash')!=expected_block:raise ValueError('captured state mismatch')
 response=record.get('response',{})
 if record.get('state')!='captured' or 'error' in response or 'result' not in response:return None
 return response['result']
def uint256(record,block):
 raw=rpc_result(record,block)
 if raw is None:return None
 if not isinstance(raw,str) or not raw.startswith('0x') or len(raw)!=66:raise ValueError('uint256 ABI result must be exactly 32 bytes')
 return int(raw,16)
def v2_lock_capture(calls,block,pair,known_lockers,dead_addresses):
 total=uint256(calls['totalSupply'],block) if 'totalSupply' in calls else None
 balances={};missing=[]
 for address in known_lockers+dead_addresses:
  value=uint256(calls.get('balances',{}).get(address,{}),block) if address in calls.get('balances',{}) else None
  if value is None:missing.append(address)
  else:balances[address]=str(value)
 return {'pair':pair,'total_supply':str(total) if total is not None else None,'known_lockers':known_lockers,'dead_addresses':dead_addresses,'balances':balances,'complete':total is not None and not missing,'missing':missing,'block_hash':block}
def graph_positions(pages,expected_block,pool):
 positions=[]
 if not pages:return {'complete':False,'positions':[],'reason':'No captured page.'}
 for i,page in enumerate(pages):
  if page.get('block_hash')!=expected_block or page.get('pool','').lower()!=pool.lower():raise ValueError('position source identity/state mismatch')
  if page.get('state')!='captured' or page.get('response',{}).get('errors'):return {'complete':False,'positions':positions,'reason':'Graph source/page failed.'}
  response=page.get('response',{});data=response.get('data',{});batch=data.get('positions')
  if data.get('_meta',{}).get('block',{}).get('hash')!=expected_block:return {'complete':False,'positions':positions,'reason':'Response has no matching graph block provenance.'}
  if i==0 and page.get('skip')!=0:raise ValueError('first position page must start at zero')
  if batch is None:return {'complete':False,'positions':positions,'reason':'Positions field absent, not empty sample.'}
  if i and page.get('skip')!=sum(len(p.get('response',{}).get('data',{}).get('positions',[])) for p in pages[:i]):raise ValueError('pagination discontinuity')
  positions.extend(batch)
 # Completion needs an explicit valid final page, rather than inferring zero from errors.
 complete=pages[-1].get('terminal_page') is True and type(pages[-1].get('page_size')) is int and pages[-1]['page_size']>len(pages[-1]['response']['data']['positions'])
 return {'complete':complete,'positions':positions,'reason':None if complete else 'Pagination end not established.'}
