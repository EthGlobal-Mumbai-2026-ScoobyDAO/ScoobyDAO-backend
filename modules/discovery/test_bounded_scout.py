import io
import sqlite3
import tempfile
import unittest
import urllib.error
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import bounded_scout as scout
import live_pilot

class Opener:
 def __init__(self,error=None):self.calls=0;self.error=error
 def open(self,request,timeout):
  self.calls+=1
  if self.error:raise urllib.error.HTTPError(request.full_url,self.error,'error',{},None)
  return Response()
class Response:
 status=200
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def read(self,size):return b'{"data": []}'

class BoundedScoutTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup);self.db=self.root/'db.sqlite';self.ledger=self.root/'ledger.sqlite'
 def test_disabled_and_zero_config_never_touch_sources(self):
  with patch('urllib.request.build_opener',side_effect=AssertionError('network')):
   self.assertEqual(scout.run_once(self.db,self.root/'out')['status'],'disabled')
   self.assertEqual(scout.run_once(self.db,self.root/'out',enabled=True,budget=0,hourly_limit=1)['status'],'configuration_unavailable')
  self.assertFalse(self.db.exists())
 def test_total_reservations_survive_fetcher_restart(self):
  op=Opener()
  with patch('urllib.request.build_opener',return_value=op):
   f=scout.ReservedFetcher(self.root/'snapshots',3,self.ledger,1);self.assertEqual(f.get('https://api.geckoterminal.com/api/v2/networks/eth/new_pools?page=1')[2]['status'],'ok')
   g=scout.ReservedFetcher(self.root/'snapshots',3,self.ledger,1)
   with self.assertRaises(live_pilot.BudgetExhausted):g.get('https://api.gopluslabs.io/api/v1/token_security/1')
  self.assertEqual(op.calls,1)
 def test_429_blocks_provider_after_restart_without_second_send(self):
  op=Opener(429)
  with patch('urllib.request.build_opener',return_value=op):
   f=scout.ReservedFetcher(self.root/'snapshots',3,self.ledger,3);self.assertEqual(f.get('https://api.geckoterminal.com/a')[2]['status'],'rate_limited')
   g=scout.ReservedFetcher(self.root/'snapshots',3,self.ledger,3);self.assertEqual(g.get('https://api.geckoterminal.com/b')[2]['status'],'rate_limited')
  self.assertEqual(op.calls,1)
 def test_unapproved_host_rejected(self):
  f=scout.ReservedFetcher(self.root/'snapshots',1,self.ledger,1)
  with self.assertRaises(ValueError):f.get('https://example.com/')
 def test_cycle_is_rate_limited_and_uses_only_bounded_run(self):
  with patch('live_pilot.run',return_value={'status':'ok','calls':0}) as run:
   self.assertEqual(scout.run_once(self.db,self.root/'out',enabled=True,budget=2,hourly_limit=2)['status'],'ok')
   self.assertEqual(scout.run_once(self.db,self.root/'out',enabled=True,budget=2,hourly_limit=2)['status'],'not_due')
   self.assertEqual(run.call_count,1)
 def test_actual_pilot_cycle_respects_total_reservation_cap(self):
  op=Opener()
  with patch('urllib.request.build_opener',return_value=op):
   result=scout.run_once(self.db,self.root/'out',enabled=True,budget=5,hourly_limit=1)
  self.assertEqual(op.calls,1)
  self.assertEqual(result['calls'],1)
  self.assertEqual(result['status'],'partial')
  with closing(sqlite3.connect(str(self.db.resolve())+'.scout-budget.sqlite3')) as c:self.assertEqual(c.execute('SELECT count(*) FROM scout_requests').fetchone()[0],1)

if __name__=='__main__':unittest.main()
