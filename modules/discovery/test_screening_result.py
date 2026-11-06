"""Offline synthetic controls; none of these fixtures is a live token."""
import copy
import datetime as dt
import hashlib
import json
import unittest
import screening_result as s
import test_market_activity as market_fixtures
import test_lp_concentration as lp_fixtures

class ScreeningResultTests(unittest.TestCase):
    def setUp(self):
        self.fixture = market_fixtures.MarketTests(methodName='test_trigger_from_finalized_validated_two_block_reserves')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        _, self.record = self.fixture.fixture()
        self.as_of = dt.datetime.fromtimestamp(186500, dt.timezone.utc)
        self.record.update(mode='live', selection={'status': 'not_selected'})
        self.record['identity']['symbol'] = 'SYNTHETIC'
        self.record['evidence'][0].update(kind='live_observation', fetched_at=self.as_of.isoformat())

    def result(self, record=None, as_of=None):
        return s.screening_result(record or self.record, self.fixture.root, 'synthetic_run', as_of or self.as_of)

    def test_verified_partial_screening_and_digest(self):
        result = self.result()
        group = next(g for g in result['groups'] if g['id'] == 'G09')
        self.assertEqual((group['status'], group['vote']), ('triggered', 1))
        self.assertEqual(group['evidence'][0]['block_number'], 20)
        self.assertEqual(group['evidence'][0]['block_hash'], '0x' + 'c' * 64)
        self.assertEqual(result['disposition']['lane'], 'human_review_required')
        self.assertFalse(result['disposition']['gate_qualified'])
        self.assertEqual(result['coverage']['triggered_groups'], 1)
        self.assertEqual(result['coverage']['unknown_or_held_groups'], 11)
        snapshot = result.pop('snapshot_id')
        raw = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        self.assertEqual(snapshot, hashlib.sha256(raw).hexdigest())
        self.assertEqual(snapshot, self.result()['snapshot_id'])

    def test_lp_verifier_preserves_actual_scope_and_never_auto_qualifies(self):
        fixture = lp_fixtures.LPTests(methodName='test_onchain_balance_not_provider_percentage_casts_one_vote')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        record = fixture.run_capture(1600)
        now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)
        result = s.screening_result(record, fixture.root, 'synthetic_lp_run', now)
        group = next(g for g in result['groups'] if g['id'] == 'G07')
        self.assertEqual((group['status'], group['vote']), ('triggered', 1))
        self.assertEqual(group['evidence'][0]['block_number'], 16)
        self.assertIn('not beneficial ownership', group['evidence'][0]['scope'])
        self.assertEqual(result['disposition']['lane'], 'human_review_required')
        self.assertFalse(result['disposition']['gate_qualified'])

    def test_provider_hints_never_vote(self):
        self.record['evidence'] = []
        self.record['triggers'] = [{'description': 'provider says dangerous'}]
        result = self.result()
        self.assertEqual(result['disposition']['lane'], 'monitor')
        self.assertEqual(result['coverage']['triggered_groups'], 0)
        self.assertEqual(result['policy']['enabled_groups'], ['G07', 'G09'])
        self.assertNotIn('dangerous', json.dumps(result))

    def test_stale_tampered_and_future_fetch_do_not_vote(self):
        self.assertEqual(self.result(as_of=self.as_of + dt.timedelta(hours=2))['coverage']['triggered_groups'], 0)
        self.record['evidence'][0]['fetched_at'] = (self.as_of + dt.timedelta(seconds=1)).isoformat()
        self.assertEqual(self.result()['coverage']['triggered_groups'], 0)
        self.record['evidence'][0]['fetched_at'] = self.as_of.isoformat()
        (self.fixture.root / self.record['evidence'][0]['source']).write_text('tampered')
        self.assertEqual(self.result()['coverage']['triggered_groups'], 0)

    def test_missing_block_or_fetch_never_votes(self):
        for field in ('block_number', 'fetched_at'):
            with self.subTest(field=field):
                record = copy.deepcopy(self.record)
                del record['evidence'][0][field]
                self.assertEqual(self.result(record)['coverage']['triggered_groups'], 0)

    def test_wrong_identity_and_replay_rejected(self):
        record = copy.deepcopy(self.record)
        record['candidate_id'] = '8453:' + record['identity']['address']
        with self.assertRaises(ValueError): self.result(record)
        record = copy.deepcopy(self.record)
        record['identity']['chain_id'] = True
        with self.assertRaises(ValueError): self.result(record)
        record = copy.deepcopy(self.record)
        record['mode'] = 'fixture'
        with self.assertRaises(ValueError): self.result(record)

    def test_overlapping_evidence_does_not_count(self):
        groups = [{'id': 'G01', 'vote': 1, 'status': 'triggered', 'evidence': [{'id': 'same'}]},
                  {'id': 'G02', 'vote': 1, 'status': 'triggered', 'evidence': [{'id': 'same'}]},
                  {'id': 'G03', 'vote': 1, 'status': 'triggered', 'evidence': [{'id': 'other'}]}]
        s._deduplicate(groups)
        self.assertEqual([g['vote'] for g in groups], [0, 0, 1])
        self.assertEqual([g['status'] for g in groups], ['unknown', 'unknown', 'triggered'])

    def test_unsafe_run_and_naive_time_rejected(self):
        with self.assertRaises(ValueError): s.screening_result(self.record, self.fixture.root, '../run', self.as_of)
        with self.assertRaises(ValueError): self.result(as_of=self.as_of.replace(tzinfo=None))

if __name__ == '__main__': unittest.main()
