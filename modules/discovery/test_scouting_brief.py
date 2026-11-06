"""Offline synthetic controls for source-grounded scouting recommendations."""
import copy
import datetime as dt
import hashlib
import json
import unittest
from unittest.mock import patch

import scouting_brief as scout
import test_market_activity as market_fixtures


class ScoutingBriefTests(unittest.TestCase):
    def setUp(self):
        self.fixture = market_fixtures.MarketTests(methodName='test_trigger_from_finalized_validated_two_block_reserves')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        _, self.record = self.fixture.fixture()
        self.now = dt.datetime.fromtimestamp(186500, dt.timezone.utc)
        self.record.update(mode='live', selection={'status': 'not_selected'}, triggers=[])
        self.record['identity']['symbol'] = 'SYNTHETIC'
        self.record['evidence'][0].update(kind='live_observation', fetched_at=self.now.isoformat())

    def capture(self, doc, url, at=None):
        raw = json.dumps(doc).encode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        (self.fixture.root / 'snapshots' / (digest + '.json')).write_bytes(raw)
        evidence = {'id': digest, 'sha256': digest, 'source': 'snapshots/' + digest + '.json',
                    'observed_at': None, 'fetched_at': (at or self.now).isoformat(),
                    'kind': 'live_observation', 'limitations': ['Request URL: ' + url]}
        self.record['evidence'].append(evidence)
        return evidence

    def security(self, fields, at=None):
        addr = self.record['identity']['address']
        return self.capture({'code': 1, 'result': {addr: fields}},
                            'https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses=' + addr, at)

    def assess(self):
        return scout.scouting_brief(self.record, self.fixture.root, 'synthetic_run', self.now)

    def test_provider_hint_and_independent_check_are_distinct(self):
        self.security({'is_honeypot': '1', 'cannot_sell_all': '1', 'is_open_source': '0'})
        output = self.assess()
        self.assertEqual(output['routing']['recommendation'], 'human_review_required')
        self.assertEqual(output['coverage']['triggered_groups'], 1)
        self.assertEqual(set(output['routing']['reason_codes']), {'verified_concern_below_auto_gate', 'unverified_provider_concern'})
        observations = output['provider_observations']['observations']
        self.assertEqual(len(observations), 3)
        self.assertTrue(all(row['gate_votes'] == 0 and row['verification'] == 'provider_reported_unverified' for row in observations))
        self.assertEqual(output['deterministic_checks'][8]['id'], 'G09')
        self.assertEqual(output['deterministic_checks'][8]['vote'], 1)
        self.assertEqual(output['provider_observations']['observations'][0]['source_evidence']['observed_at'], None)

    def test_provider_hint_alone_can_recommend_human_but_never_qualify(self):
        self.record['evidence'] = []
        self.security({'is_honeypot': '1'})
        output = self.assess()
        self.assertEqual(output['routing']['recommendation'], 'human_review_required')
        self.assertEqual(output['coverage']['triggered_groups'], 0)
        self.assertEqual(output['routing']['reason_codes'], ['unverified_provider_concern'])
        self.assertTrue(all(group['vote'] == 0 for group in output['deterministic_checks']))

    def test_synthetic_qualified_assessment_recommends_automatic_path(self):
        # This mocks a future trusted four-group assessment; no such live case exists today.
        fake = {'candidate': self.record['identity'], 'generated_at': self.now.isoformat(),
                'run_id': 'synthetic_run', 'snapshot_id': 'synthetic',
                'groups': [{'id': group, 'vote': 1} for group in ('G01', 'G02', 'G03', 'G04')],
                'coverage': {'triggered_groups': 4}, 'disposition': {'gate_qualified': True}}
        with patch.object(scout.screening_result, 'screening_result', return_value=fake):
            result = self.assess()
        self.assertEqual(result['routing']['recommendation'], 'auto_eligible')
        self.assertEqual(result['routing']['reason_codes'], ['four_distinct_verified_concerns'])

    def test_new_pool_and_unavailable_source_are_not_suspicion(self):
        self.record['evidence'] = []
        addr = self.record['identity']['address']
        doc = {'data': [{'relationships': {'base_token': {'data': {'id': 'eth_' + addr}}}}]}
        evidence = self.capture(doc, 'https://api.geckoterminal.com/api/v2/networks/eth/new_pools?page=1')
        self.record['triggers'] = [{'reason_code': 'new_pool_lead', 'evidence_ids': [evidence['id']]}]
        self.security({'is_open_source': '0', 'is_honeypot': '0'})
        output = self.assess()
        self.assertEqual(output['routing']['recommendation'], 'monitor')
        self.assertEqual(output['scouting_origins'][0]['source_evidence']['id'], evidence['id'])
        self.assertEqual(output['provider_observations']['observations'][0]['code'], 'provider_source_unavailable')
        self.assertEqual(output['coverage']['triggered_groups'], 0)

    def test_stale_tampered_and_wrong_identity_provider_cannot_change_route(self):
        self.record['evidence'] = []
        evidence = self.security({'is_honeypot': '1'}, self.now - dt.timedelta(hours=2))
        self.assertEqual(self.assess()['routing']['recommendation'], 'monitor')
        evidence['fetched_at'] = self.now.isoformat()
        (self.fixture.root / evidence['source']).write_text('tampered')
        result = self.assess()
        self.assertEqual(result['routing']['recommendation'], 'monitor')
        self.assertEqual(result['provider_observations']['status'], 'unavailable')
        self.assertIn('provider_check_unavailable', result['routing']['reason_codes'])
        self.record['evidence'] = []
        wrong = {'code': 1, 'result': {'0x' + 'b'*40: {'is_honeypot': '1'}}}
        self.capture(wrong, 'https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses=' + self.record['identity']['address'])
        self.assertEqual(self.assess()['routing']['recommendation'], 'monitor')

    def test_untrusted_trigger_or_old_provider_must_not_be_invented(self):
        self.record['evidence'] = []
        self.record['triggers'] = [{'reason_code': 'new_pool_lead', 'evidence_ids': ['invented']}]
        old = self.security({'is_honeypot': '1'}, self.now - dt.timedelta(minutes=5))
        self.security({'is_honeypot': '0'})
        result = self.assess()
        self.assertEqual(result['scouting_origins'], [])
        self.assertEqual(result['provider_observations']['observations'], [])
        self.assertEqual(result['routing']['recommendation'], 'monitor')
        self.assertIsNotNone(old)

if __name__ == '__main__': unittest.main()
