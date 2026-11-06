"""Synthetic offline tests of the shared-provider discovery seam."""
import copy
from contextlib import closing
import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path
import reddit_leads as leads

class RedditLeadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'leads.sqlite'
        self.now = dt.datetime(2026, 11, 6, 12, 0, tzinfo=dt.timezone.utc)
        self.result = {'profile': leads.PROFILE, 'query': 'honeypot', 'status': 'partial',
                       'window': {'start': '2026-11-05T00:00:00+00:00', 'end': '2026-11-06T00:00:00+00:00'},
                       'observations': [{'id': 't3_abc123', 'subreddit': 'CryptoScams', 'query': 'honeypot', 'attribution': 'unresolved', 'verified_concern_votes': 0, 'fetched_at': '2026-11-06T10:00:00+00:00', 'extracted_identifiers': [{'kind': 'evm_address', 'value': '0x' + 'a' * 40, 'chain_id': None}], 'url': 'https://www.reddit.com/r/CryptoScams/comments/abc123/example/',
                                         'observed_at': '2026-11-05T10:00:00+00:00',
                                         'excerpt': 'Allegation: cannot sell $EXAMPLE 0x' + 'a' * 40,
                                         'content_sha256': 'a' * 64}]}
        self.kwargs = {'allowed_subreddits': ['CryptoScams'], 'allowed_queries': ['honeypot', 'cannot sell'], 'now': self.now}

    def ingest(self, result=None, **kwargs):
        return leads.ingest(self.db, result or self.result, **(self.kwargs | kwargs))

    def rows(self, sql):
        with closing(sqlite3.connect(self.db)) as con: return con.execute(sql).fetchall()

    def test_dedup_posts_and_record_queries_without_claiming_identity(self):
        self.ingest(); self.ingest()
        second = copy.deepcopy(self.result); second['query'] = 'cannot sell'; second['observations'][0]['query'] = 'cannot sell'
        summary = self.ingest(second)
        self.assertEqual(summary['verified_concern_votes'], 0)
        self.assertEqual(summary['candidate_ids_resolved'], 0)
        self.assertEqual(self.rows('SELECT lead_id,candidate_id FROM reddit_leads'), [('reddit:abc123', None)])
        self.assertEqual(len(self.rows('SELECT * FROM reddit_lead_queries')), 2)
        self.assertEqual(set(self.rows('SELECT kind,value FROM reddit_lead_identifiers')),
                         {('ticker_mentioned', 'EXAMPLE'), ('address_mentioned', '0x' + 'a' * 40)})
        self.assertEqual(self.rows('SELECT post_url FROM reddit_leads')[0][0], 'https://www.reddit.com/r/cryptoscams/comments/abc123/')

    def test_unavailable_and_invalid_provider_results_fail_closed(self):
        result = copy.deepcopy(self.result); result.update(status='unavailable', observations=[])
        self.assertEqual(self.ingest(result)['status'], 'unavailable')
        self.assertEqual(self.rows('SELECT * FROM reddit_leads'), [])
        result['observations'] = self.result['observations']
        with self.assertRaises(ValueError): self.ingest(result)
        result = copy.deepcopy(self.result); result['query'] = 'outside policy'
        with self.assertRaises(ValueError): self.ingest(result)
        with self.assertRaises(ValueError): self.ingest(allowed_subreddits=[])

    def test_rejects_wrong_community_host_time_and_excess(self):
        for field, value in [('url', 'https://evil.example/r/CryptoScams/comments/abc123/'),
                             ('url', 'https://reddit.com/r/other/comments/abc123/'),
                             ('url', 'https://reddit.com/r/CryptoScams/comments/abc123/?token=secret'),
                             ('observed_at', '2026-11-06T01:00:00+00:00')]:
            with self.subTest(field=field, value=value):
                result = copy.deepcopy(self.result); result['observations'][0][field] = value
                with self.assertRaises(ValueError): self.ingest(result)
        result = copy.deepcopy(self.result); result['observations'] *= 2
        with self.assertRaises(ValueError): self.ingest(result, max_posts=1)
        result = copy.deepcopy(self.result); result['observations'][0]['fetched_at'] = '2026-11-07T00:00:00+00:00'
        with self.assertRaises(ValueError): self.ingest(result)

    def test_conflicting_post_content_rolls_back_batch(self):
        self.ingest()
        result = copy.deepcopy(self.result)
        other = copy.deepcopy(result['observations'][0]); other['url'] = 'https://reddit.com/r/CryptoScams/comments/zzz99/'; other['id'] = 't3_zzz99'
        conflict = copy.deepcopy(result['observations'][0]); conflict['content_sha256'] = 'b' * 64
        result['observations'] = [other, conflict]
        with self.assertRaises(ValueError): self.ingest(result)
        self.assertEqual(self.rows('SELECT lead_id FROM reddit_leads'), [('reddit:abc123',)])

if __name__ == '__main__': unittest.main()
