import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import continuous_pilot as runner
import live_pilot


class ContinuousPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'state.sqlite'
        self.now = dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc)
        self.con = live_pilot.setup(self.db)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.con.close)

    def add_lead(self, address, pool, created, selected=False):
        candidate = '1:' + address
        record = {'candidate_id': candidate, 'identity': {'chain_id': 1, 'address': address},
                  'mode': 'live', 'selection': {'status': 'selected' if selected else 'not_selected'}, 'evidence': []}
        with self.con:
            self.con.execute('INSERT INTO candidates VALUES(?,?,?)', (candidate, json.dumps(record), None))
            self.con.execute('INSERT INTO pilot_leads VALUES(?,?,?,?)', (candidate, 'run', pool, created))
        return candidate

    def test_single_runner_lock_releases_on_close(self):
        lock = runner.lock_runner(self.db)
        with self.assertRaises(RuntimeError):
            runner.lock_runner(self.db)
        lock.close()
        lock2 = runner.lock_runner(self.db)
        lock2.close()

    def test_old_unselected_pools_are_reserved_and_retried_later(self):
        old = (self.now - dt.timedelta(days=2)).isoformat()
        recent = (self.now - dt.timedelta(hours=2)).isoformat()
        self.add_lead('0x' + '1' * 40, '0x' + 'a' * 40, old, selected=True)
        self.add_lead('0x' + '2' * 40, '0x' + 'b' * 40, recent)
        candidate = self.add_lead('0x' + '3' * 40, '0x' + 'c' * 40, old)
        self.assertEqual(runner.choose_market(self.db, self.now), (candidate, '0x' + 'c' * 40))
        self.assertIsNone(runner.choose_market(self.db, self.now))
        self.assertEqual(runner.choose_market(self.db, self.now + dt.timedelta(hours=1)), (candidate, '0x' + 'c' * 40))

    def test_collection_failure_is_unknown_and_bounded(self):
        old = (self.now - dt.timedelta(days=2)).isoformat()
        candidate = self.add_lead('0x' + '3' * 40, '0x' + 'c' * 40, old)
        class Failure:
            returncode = 1
        with patch.dict(os.environ, {'PUBLICNODE_TOKEN': 'synthetic'}), patch.object(runner.subprocess, 'run', return_value=Failure()) as run:
            self.assertEqual(runner.collect_market(self.db, self.root, self.now), 'unavailable')
            self.assertEqual(runner.collect_market(self.db, self.root, self.now), 'no_due_pool')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(self.con.execute('SELECT status FROM market_attempts WHERE candidate_id=?', (candidate,)).fetchone()[0], 'unavailable')

    def test_cycle_refreshes_empty_queue_without_promoting_hints(self):
        report = {'status': 'ok', 'calls': 2, 'issues': []}
        with patch.object(runner.live_pilot, 'run', return_value=report):
            result = runner.cycle(self.db, self.root, 5, 22, ['ethereum'], False)
        self.assertEqual(result['enabled_verifiers'], 2)
        self.assertEqual(result['qualified'], 0)
        saved = json.loads((self.root / 'review-queue.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['candidates'], [])
        self.assertTrue((self.root / 'review-queue.html').exists())

    def test_lp_collection_is_bounded_and_preserves_failures(self):
        old = (self.now - dt.timedelta(days=2)).isoformat()
        candidate = self.add_lead('0x' + '3' * 40, '0x' + 'c' * 40, old)
        class Failure:
            returncode = 1
        with patch.object(runner.collect_lp_concentration, 'holder_hints', return_value=['0x' + 'd' * 40]), patch.object(runner.subprocess, 'run', return_value=Failure()) as run:
            self.assertEqual(runner.collect_lp(self.db, self.root, self.now), 'unavailable')
            self.assertEqual(runner.collect_lp(self.db, self.root, self.now), 'not_due')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(self.con.execute('SELECT status FROM lp_attempts WHERE candidate_id=?', (candidate,)).fetchone()[0], 'unavailable')

    def test_refresh_attaches_provider_hints_without_qualifying_and_is_bounded(self):
        old = (self.now - dt.timedelta(days=2)).isoformat()
        address = '0x' + '3' * 40
        candidate = self.add_lead(address, '0x' + 'c' * 40, old)
        outer = self
        class Fetcher:
            def __init__(self, root, budget): pass
            def get(self, url):
                evidence = {'id': 'hint', 'fetched_at': outer.now.isoformat(), 'limitations': ['Request URL: ' + url]}
                return {'code': 1, 'result': {address: {'holders': []}}}, evidence, {'status': 'ok'}
        with patch.object(runner.live_pilot, 'Fetcher', Fetcher):
            self.assertEqual(runner.refresh_security(self.db, self.root, self.now), ('refreshed', 1))
            self.assertEqual(runner.refresh_security(self.db, self.root, self.now), ('not_due', 0))
        record = json.loads(self.con.execute('SELECT record FROM candidates WHERE id=?', (candidate,)).fetchone()[0])
        self.assertEqual(record['evidence'][0]['id'], 'hint')
        self.assertEqual(record['selection']['status'], 'not_selected')

    def test_loop_repeats_and_releases_lock_when_stopped(self):
        args = ['continuous_pilot', '--db', str(self.db), '--output', str(self.root)]
        with patch.object(sys, 'argv', args), patch.object(runner, 'cycle', return_value={'status': 'ok'}) as cycle, patch.object(runner.time, 'sleep', side_effect=[None, KeyboardInterrupt]), patch('builtins.print'):
            self.assertEqual(runner.main(), 0)
        self.assertEqual(cycle.call_count, 2)
        lock = runner.lock_runner(self.db)
        lock.close()


if __name__ == '__main__':
    unittest.main()
