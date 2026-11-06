import datetime as dt
import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import collect_lp_concentration as capture
import live_pilot
import lp_concentration as lp
import market_activity as market
import review_queue


class LPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'state.sqlite'
        self.token = '0x' + 'a' * 40
        self.pool = '0x' + 'b' * 40
        self.holder = '0x' + 'c' * 40
        self.cid = '1:' + self.token
        self.now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        self.timestamp = int(self.now.timestamp())
        source = {'code': 1, 'result': {self.token: {'lp_holders': [{'address': self.holder, 'percent': '0.99'}]}}}
        raw = json.dumps(source).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (self.root / 'snapshots').mkdir()
        (self.root / 'snapshots' / (digest + '.json')).write_bytes(raw)
        evidence = {'id': digest, 'source': 'snapshots/' + digest + '.json', 'sha256': digest,
                    'fetched_at': self.now.isoformat(), 'limitations': [
                        'Request URL: https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses=' + self.token]}
        self.record = {'candidate_id': self.cid, 'identity': {'chain_id': 1, 'address': self.token, 'symbol': 'TEST'},
                       'mode': 'live', 'selection': {'status': 'not_selected'}, 'evidence': [evidence]}
        con = live_pilot.setup(self.db)
        with con:
            con.execute('INSERT INTO candidates VALUES(?,?,?)', (self.cid, json.dumps(self.record), None))
            con.execute('INSERT INTO pilot_leads VALUES(?,?,?,?)', (self.cid, 'run', self.pool, self.now.isoformat()))
        con.close()

    def run_capture(self, balance, concurrent_update=False):
        outer = self
        class FakeRPC:
            token = ''
            def __init__(self, budget):
                self.budget, self.calls, self.trace = budget, 0, []
            def call(self, method, params):
                self.calls += 1
                assert self.calls <= self.budget
                if self.calls == 1 and concurrent_update:
                    with closing(sqlite3.connect(outer.db)) as con:
                        record = json.loads(con.execute('SELECT record FROM candidates WHERE id=?', (outer.cid,)).fetchone()[0])
                        record['selection']['status'] = 'selected'
                        con.execute('UPDATE candidates SET record=? WHERE id=?', (json.dumps(record), outer.cid))
                        con.commit()
                if method == 'eth_chainId': result = '0x1'
                elif method == 'eth_getBlockByNumber': result = {'number': '0x10', 'timestamp': hex(outer.timestamp), 'hash': '0x' + 'f' * 64}
                else:
                    data = params[0]['data']
                    if data == '0x0dfe1681': n = int(outer.token, 16)
                    elif data == '0xd21220a7': n = int(market.WETH, 16)
                    elif data == '0xc45a0155': n = int(market.FACTORY, 16)
                    elif data.startswith('0xe6a43905'): n = int(outer.pool, 16)
                    elif data == '0x18160ddd': n = 10000
                    elif data.startswith('0x70a08231'): n = balance
                    else: raise AssertionError(data)
                    result = '0x' + format(n, '064x')
                request = {'jsonrpc': '2.0', 'id': self.calls, 'method': method, 'params': params}
                self.trace.append({'request': request, 'response': {'jsonrpc': '2.0', 'id': self.calls, 'result': result}})
                return result
            def block(self, tag): return self.call('eth_getBlockByNumber', [tag, False])
            def eth(self, to, data, tag): return {'to': to, 'data': data, 'block': tag, 'result': self.call('eth_call', [{'to': to, 'data': data}, tag])}
        argv = ['collect_lp_concentration', '--db', str(self.db), '--output', str(self.root), '--candidate-id', self.cid, '--pool', self.pool]
        with patch.object(sys, 'argv', argv), patch.object(capture.collector, 'RPC', FakeRPC), redirect_stdout(io.StringIO()):
            self.assertEqual(capture.main(), 0)
        with closing(sqlite3.connect(self.db)) as con:
            return json.loads(con.execute('SELECT record FROM candidates WHERE id=?', (self.cid,)).fetchone()[0])

    def test_onchain_balance_not_provider_percentage_casts_one_vote(self):
        record = self.run_capture(1600)
        result = lp.verify(record, self.root, self.now)
        self.assertTrue(result['triggered'])
        self.assertEqual(result['measurements'][0]['value'], '16.0000')
        assessed = review_queue.assess(record, self.root, self.now, {'G07': lp.verify})
        self.assertEqual(assessed['triggered_count'], 1)
        self.assertFalse(assessed['eligible'])

    def test_threshold_and_incomplete_sample_remain_unknown(self):
        record = self.run_capture(1500)
        result = lp.verify(record, self.root, self.now)
        self.assertIsNone(result['triggered'])
        assessed = review_queue.assess(record, self.root, self.now, {'G07': lp.verify})
        self.assertEqual(next(g for g in assessed['groups'] if g['id'] == 'G07')['status'], 'unknown')
        self.assertEqual(assessed['triggered_count'], 0)

    def test_changed_balance_not_matching_rpc_transcript_is_rejected(self):
        record = self.run_capture(1600)
        evidence = record['evidence'][-1]
        doc = json.loads((self.root / evidence['source']).read_text(encoding='utf-8'))
        doc['point']['calls']['balance:' + self.holder]['result'] = '0x' + format(9000, '064x')
        raw = json.dumps(doc).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (self.root / 'snapshots' / (digest + '.json')).write_bytes(raw)
        evidence.update(id=digest, sha256=digest, source='snapshots/' + digest + '.json')
        with self.assertRaisesRegex(ValueError, 'transcript mismatch'):
            lp.verify(record, self.root, self.now)

    def test_evidence_is_merged_without_overwriting_a_concurrent_selection(self):
        record = self.run_capture(1600, concurrent_update=True)
        self.assertEqual(record['selection']['status'], 'selected')
        self.assertEqual(len(record['evidence']), 2)

    def test_wrong_factory_is_rejected_even_if_transcript_matches(self):
        record = self.run_capture(1600)
        evidence = record['evidence'][-1]
        doc = json.loads((self.root / evidence['source']).read_text(encoding='utf-8'))
        wrong = '0x' + '0' * 64
        doc['point']['calls']['factory']['result'] = wrong
        for entry in doc['rpc_trace']:
            if entry['request']['method'] == 'eth_call' and entry['request']['params'][0]['data'] == '0xc45a0155':
                entry['response']['result'] = wrong
        raw = json.dumps(doc).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (self.root / 'snapshots' / (digest + '.json')).write_bytes(raw)
        evidence.update(id=digest, sha256=digest, source='snapshots/' + digest + '.json')
        with self.assertRaisesRegex(ValueError, 'factory mismatch'):
            lp.verify(record, self.root, self.now)

    def test_stale_onchain_observation_does_not_vote(self):
        record = self.run_capture(1600)
        assessed = review_queue.assess(record, self.root, self.now + dt.timedelta(hours=2), {'G07': lp.verify})
        self.assertEqual(assessed['triggered_count'], 0)
        self.assertEqual(next(g for g in assessed['groups'] if g['id'] == 'G07')['status'], 'unknown')

    def test_burn_reserved_and_pool_addresses_are_not_lp_owners(self):
        for address in ('0x' + '0' * 40, '0x' + '0' * 39 + '1', '0x' + '0' * 36 + 'dead', self.pool):
            self.assertFalse(lp.usable_holder(address, self.pool))
        self.assertTrue(lp.usable_holder(self.holder, self.pool))


if __name__ == '__main__':
    unittest.main()
