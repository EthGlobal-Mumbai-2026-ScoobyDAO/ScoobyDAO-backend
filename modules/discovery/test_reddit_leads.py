"""Pure adapter tests; all posts, evidence and token addresses are invented fixtures."""
import copy
import datetime as dt
import json
import unittest
from pathlib import Path

import candidate_validation
import reddit_leads as leads
import test_market_activity as market_fixtures

FIXTURE = json.loads((Path(__file__).parent / 'fixtures' / 'reddit-lead-synthetic.json').read_text(encoding='utf-8'))

class RedditLeadTests(unittest.TestCase):
    def setUp(self):
        self.result = copy.deepcopy(FIXTURE['provider_result'])
        self.now = dt.datetime.fromtimestamp(186500, dt.timezone.utc)
        self.kwargs = {'allowed_subreddits': ['CryptoScams'], 'allowed_queries': ['cannot sell'], 'now': self.now}

    def adapt(self, result=None, **kwargs):
        return leads.adapt(result or self.result, **(self.kwargs | kwargs))

    def test_unavailable_empty_and_bounds_are_distinct(self):
        result = copy.deepcopy(self.result); result.update(status='unavailable', observations=[])
        result['coverage'].update(requests=0, posts_examined=0, complete=False, reason='SECRET from provider', scopes=[{'subreddit':'CryptoScams','state':'not_started','next_cursor':None}])
        output = self.adapt(result)
        self.assertEqual(output['status'], 'unavailable')
        self.assertEqual(output['coverage']['unsearched_scope'], ['cryptoscams'])
        self.assertNotIn('SECRET', json.dumps(output))
        for reason in ('HTTP 403', 'HTTP 429', 'malformed response'):
            result['coverage']['reason'] = reason
            self.assertEqual(self.adapt(result)['reason'], 'provider_unavailable')
        result.update(status='partial'); result['coverage']['complete'] = True; result['coverage']['scopes'][0]['state'] = 'exhausted'
        self.assertEqual(self.adapt(result)['status'], 'empty')
        result['coverage']['requests'] = 6
        with self.assertRaises(ValueError): self.adapt(result)
        with self.assertRaises(ValueError): self.adapt(allowed_subreddits=['a1','a2','a3','a4'])

    def test_dedup_repeated_posts_and_mentions_without_counting_votes(self):
        item = copy.deepcopy(self.result['observations'][0])
        other = copy.deepcopy(item); other['id'] = 't3_def456'; other['url'] = 'https://reddit.com/r/CryptoScams/comments/def456/'
        self.result['observations'] = [item, copy.deepcopy(item), other]
        self.result['coverage']['posts_examined'] = 3
        result = self.adapt()
        self.assertEqual(len(result['leads']), 1)
        lead = result['leads'][0]
        self.assertEqual(len(lead['references']), 2)
        self.assertEqual(lead['candidate_id'], None)
        self.assertEqual(lead['verified_concern_votes'], 0)
        self.assertNotIn('content_sha256', json.dumps(result))
        self.assertNotIn('excerpt', json.dumps(result))
        self.assertNotIn('Synthetic allegation', json.dumps(result))

    def test_unresolved_ticker_address_and_other_chain(self):
        for text in ['cannot sell $TEST', 'cannot sell 0x' + 'a'*40,
                     'BNB cannot sell 0x' + 'a'*40, 'Solana cannot sell $TEST']:
            with self.subTest(text=text):
                result = copy.deepcopy(self.result); item = result['observations'][0]
                item['excerpt'] = text
                item['extracted_identifiers'] = ([{'kind':'evm_address','value':'0x'+'a'*40,'chain_id':None}]
                                                 if '0x' in text else [])
                lead = self.adapt(result)['leads'][0]
                self.assertIsNone(lead['candidate_id'])
                self.assertIsNone(lead['identifiers']['chain_hint'])
                self.assertEqual(lead['verified_concern_votes'], 0)

    def test_expiry_and_removed_posts_are_dropped(self):
        result = self.adapt(now=self.now + dt.timedelta(hours=2))
        self.assertEqual(result['leads'], [])
        self.assertEqual(result['coverage']['expired_observations'], 1)
        result = self.adapt(removed_post_ids=['t3_abc123'])
        self.assertEqual(result['leads'], [])
        self.assertEqual(result['coverage']['removed_observations'], 1)

    def test_incomplete_scope_and_cursor_are_reported_without_claiming_resume(self):
        self.result['coverage']['complete'] = False
        self.result['coverage']['scopes'][0].update(state='truncated', next_cursor='t3_abc123')
        coverage = self.adapt()['coverage']
        self.assertEqual(coverage['unsearched_scope'], ['cryptoscams'])
        self.assertEqual(coverage['scopes'][0]['next_cursor'], 't3_abc123')
        self.assertFalse(coverage['cursor_input_supported'])
        self.result['coverage']['scopes'][0]['next_cursor'] = 'https://example.com/secret'
        with self.assertRaises(ValueError): self.adapt()

    def test_invalid_provider_responses_fail_closed(self):
        for field, value in [('url', 'https://evil.example/r/CryptoScams/comments/abc123/'),
                             ('url', 'https://reddit.com/r/other/comments/abc123/'),
                             ('url', 'https://reddit.com/r/CryptoScams/comments/abc123/?token=secret'),
                             ('observed_at', '2026-11-06T01:00:00+00:00'),
                             ('verified_concern_votes', 1)]:
            with self.subTest(field=field):
                result = copy.deepcopy(self.result); result['observations'][0][field] = value
                with self.assertRaises(ValueError): self.adapt(result)
        result = copy.deepcopy(self.result); result['status'] = 'unavailable'
        with self.assertRaises(ValueError): self.adapt(result)
        result = copy.deepcopy(self.result); result['query'] = 'outside policy'
        with self.assertRaises(ValueError): self.adapt(result)

    def test_backend_consumable_synthetic_identity_resolution(self):
        self.assertEqual(FIXTURE['fixture_kind'], 'synthetic_historical_test_only')
        fixture = market_fixtures.MarketTests(methodName='test_trigger_from_finalized_validated_two_block_reserves')
        fixture.setUp(); self.addCleanup(fixture.tearDown)
        _, record = fixture.fixture()
        record.update(schema_version='0.1', mode='live', state='monitoring', triggers=[],
                      screening={'status':'not_scored','score':None,'score_version':None,'threshold_version':None,
                                 'quality_issues':['Invented fixture for offline tests only.']},
                      selection={'status':'not_selected','selected_by':None,'selected_at':None,'reason':None},
                      last_observed_at=None,next_check_at=None)
        record['identity']['symbol'] = 'SYNTHETIC'
        record['evidence'][0].update(kind='live_observation', fetched_at=self.now.isoformat())
        schema = json.loads((Path(__file__).parents[2] / 'schemas' / 'candidate.schema.json').read_text(encoding='utf-8-sig'))
        candidate_validation.validate(record, schema)
        lead = self.adapt()['leads'][0]
        resolved = leads.resolve_identity(lead, record, fixture.root, now=self.now)
        expected = FIXTURE['expected']
        self.assertEqual(resolved['candidate_id'], expected['candidate_id'])
        self.assertEqual(resolved['screening_snapshot']['coverage']['triggered_groups'], expected['verified_concern_groups'])
        self.assertEqual(resolved['screening_snapshot']['disposition']['lane'], expected['disposition'])
        self.assertFalse(resolved['screening_snapshot']['disposition']['gate_qualified'])
        self.assertEqual(resolved['social_concern_votes'], 0)
        self.assertEqual(resolved['source_leads'][0]['post_id'], 't3_abc123')
        duplicate = copy.deepcopy(resolved); duplicate['lead_id'] = 'reddit:other'
        grouped = leads.deduplicate_resolutions([resolved, duplicate, resolved])
        self.assertEqual(len(grouped), 1)
        self.assertEqual(len(grouped[0]['lead_ids']), 2)
        self.assertNotIn('screening_snapshot', json.dumps(grouped))
        self.assertNotIn('reddit.com', json.dumps(record))
        with self.assertRaises(ValueError): leads.resolve_identity(lead, record, fixture.root, now=self.now, removed_post_ids=['t3_abc123'])
        with self.assertRaises(ValueError): leads.resolve_identity(lead, record, fixture.root, now=self.now+dt.timedelta(hours=2))
        record['evidence'] = []
        with self.assertRaises(ValueError): leads.resolve_identity(lead, record, fixture.root, now=self.now)

if __name__ == '__main__': unittest.main()
