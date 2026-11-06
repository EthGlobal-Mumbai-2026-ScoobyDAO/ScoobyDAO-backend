"""Optional adapter boundary for five independently failing research producers.

Not wired into build_report yet. A backend can inject producer callables and must
validate evidence/claims against the frozen report contract before publication.
"""
PILLARS=('microstructure','onchain','fundamentals','statistical_risk','technical_health')
VALID_STATUSES={'complete','partial','failed','unavailable'}
def run_pillars(context, producers):
 """Return per-pillar status and producer payload; missing producers stay unavailable."""
 extra=set(producers)-set(PILLARS)
 if extra: raise ValueError('unknown pillar')
 results={}
 for name in PILLARS:
  fn=producers.get(name)
  if fn is None:
   results[name]={'status':'unavailable','detail':'No producer configured.','payload':None}; continue
  try:
   result=fn(context)
   if not isinstance(result,dict) or result.get('status') not in VALID_STATUSES or 'payload' not in result: raise ValueError('invalid producer result')
   results[name]=result
  except Exception:
   results[name]={'status':'failed','detail':'Producer failed; inspect local logs.','payload':None}
 return results
