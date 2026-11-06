"""Synthetic-only SearchApi boundary tests; no provider credits or network calls."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from modules.investigation import reddit_search as reddit
from modules.investigation.searchapi_reddit import SearchApiCredentials, credentials_from_environment, social_window

SECRET = 'synthetic-secret-do-not-log'
ADDR = '0x' + '12' * 20
CREDS = SearchApiCredentials(SECRET)
NOW = datetime.now(timezone.utc).replace(microsecond=0)
WINDOW = {'start': (NOW - timedelta(days=31)).isoformat(), 'end': NOW.isoformat()}


def post(identifier='a1', *, when=None, subreddit='CryptoScams', title='Synthetic honeypot alert'):
    return {'id': 't3_' + identifier, 'link': f'https://www.reddit.com/r/{subreddit}/comments/{identifier}/example/',
            'subreddit': {'name': subreddit}, 'iso_date': when or (NOW - timedelta(days=1)).isoformat(),
            'title': title, 'score': 3, 'comments': 2, 'author': {'username': 'never-retain'}}


def page(posts, token=None):
    return {'search_metadata': {'status': 'Success'}, 'organic_results': posts,
            'pagination': {'next_page_token': token}}


def test_selected_provider_defaults_to_one_page_and_excludes_seven_stale_smoke_dates():
    # These are the dates reported by the separate live smoke; all other content is synthetic.
    dates = ['2026-09-26T07:16:34Z', '2026-05-21T08:58:35Z', '2026-03-20T10:08:47Z',
             '2026-02-14T12:37:32Z', '2026-01-30T11:15:17Z', '2025-12-22T17:10:00Z', '2025-11-14T19:45:17Z']
    recorded = []
    def send(request):
        recorded.append(request)
        assert request.url.host == 'www.searchapi.io' and request.url.path == '/api/v1/search'
        assert request.headers['Authorization'] == 'Bearer ' + SECRET
        assert 'api_key' not in request.url.params and SECRET not in str(request.url)
        assert request.url.params['engine'] == 'reddit_search'
        assert request.url.params['subreddit'] == 'CryptoScams'
        assert request.url.params['sort_by'] == 'new' and request.url.params['safe'] == 'active'
        return httpx.Response(200, json=page([post('a' + str(i), when=d) for i, d in enumerate(dates)], 'opaque-next'))
    fixed = {'start': '2026-10-06T11:02:48+00:00', 'end': '2026-11-06T11:02:48+00:00'}
    result = reddit.search_leads('honeypot', ['CryptoScams', 'ExampleTwo'], fixed, CREDS, transport=httpx.MockTransport(send))
    assert len(recorded) == 1 and result['provider'] == 'searchapi.io'
    assert result['observations'] == [] and result['coverage']['excluded']['outside_window'] == 7
    assert [s['state'] for s in result['coverage']['scopes']] == ['truncated', 'not_started']
    assert result['coverage']['scopes'][0]['next_cursor'] == 'opaque-next'
    assert SECRET not in json.dumps(result) and 'never-retain' not in json.dumps(result)


def test_candidate_context_attribution_comment_limit_and_unresolved_chain():
    item = post(title=f'Warning {ADDR} {SECRET}')
    item['matching_comment'] = {'id': 't1_abc', 'snippet': f'Potential scam; {SECRET}'}
    def send(request):
        return httpx.Response(200, json=page([item]))
    result = reddit.collect({'chain_id': 1, 'address': ADDR}, WINDOW, CREDS, transport=httpx.MockTransport(send))
    observation = result['observations'][0]
    assert result['profile'] == 'scooby.reddit-evidence/1' and result['status'] == 'partial'
    assert observation['attribution'] == 'address_mentioned' and observation['verified_concern_votes'] == 0
    assert observation['extracted_identifiers'][0]['chain_id'] is None
    assert observation['source_components'] == ['title', 'matching_comment_snippet']
    assert observation['content_hash_scope'] == 'redacted_excerpt_only'
    assert SECRET not in json.dumps(result) and 'never-retain' not in json.dumps(result)
    assert result['interpretation']['method'] == 'literal-term-presence/1'
    no_comments = reddit.collect({'chain_id': 1, 'address': ADDR}, WINDOW, CREDS, max_comments=0, transport=httpx.MockTransport(send))
    assert no_comments['observations'][0]['source_components'] == ['title']


def test_date_subreddit_dedup_and_invalid_source_are_counted():
    future = (NOW + timedelta(days=1)).isoformat()
    items = [post('a1'), post('a1'), post('a2', subreddit='OtherSub'),
             post('a3', when=future), {**post('a4'), 'iso_date': None},
             {**post('a5'), 'link': 'https://evil.example/r/CryptoScams/comments/a5/example/'}]
    result = reddit.search_leads('honeypot', ['CryptoScams'], WINDOW, CREDS,
                                 transport=httpx.MockTransport(lambda request: httpx.Response(200, json=page(items))))
    assert len(result['observations']) == 1
    counts = result['coverage']['excluded']
    assert (counts['duplicate'], counts['wrong_subreddit'], counts['future'], counts['missing_or_invalid_date'], counts['invalid_source']) == (1, 1, 1, 1, 1)
    assert result['coverage']['complete'] is True


def test_365_day_context_accepts_older_posts_without_changing_gate():
    old = post('a1', when=(NOW - timedelta(days=300)).isoformat())
    too_old = post('a2', when=(NOW - timedelta(days=366)).isoformat())
    result = reddit.search_leads('honeypot', ['CryptoScams'], social_window(end=NOW), CREDS,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=page([old, too_old]))))
    assert len(result['observations']) == 1 and result['coverage']['excluded']['outside_window'] == 1
    assert result['observations'][0]['source_mode'] == 'dated_social_context'
    assert result['observations'][0]['age_days'] >= 300
    assert result['observations'][0]['verified_concern_votes'] == 0


def test_cursor_and_cancel_are_bounded():
    requests = []
    def send(request):
        requests.append(request)
        return httpx.Response(200, json=page([post('a1')], token='same-cursor'))
    result = reddit.search_leads('honeypot', ['CryptoScams'], WINDOW, CREDS, max_requests=2, transport=httpx.MockTransport(send))
    assert len(requests) == 2 and requests[1].url.params['next_page_token'] == 'same-cursor'
    assert result['coverage']['reason'] == 'invalid_or_repeated_cursor'
    assert result['status'] == 'partial' and result['coverage']['excluded']['duplicate'] == 1
    cancelled = reddit.search_leads('honeypot', ['CryptoScams'], WINDOW, CREDS,
                                    cancelled=lambda: True, transport=httpx.MockTransport(send))
    assert cancelled['coverage']['reason'] == 'cancelled' and cancelled['coverage']['requests'] == 0


@pytest.mark.parametrize(('status', 'reason'), [(401, 'authentication_denied'), (403, 'authentication_denied'),
                                               (429, 'rate_limited'), (500, 'http_error')])
def test_http_errors_are_distinct_and_do_not_return_reflected_secret(status, reason):
    result = reddit.search_leads('honeypot', ['CryptoScams'], WINDOW, CREDS,
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json={'error': SECRET})))
    assert result['status'] == 'unavailable' and result['coverage']['reason'] == reason
    assert result['coverage']['requests'] == 1 and SECRET not in json.dumps(result)


def test_provider_errors_empty_malformed_timeout_and_missing_key(monkeypatch):
    for payload, reason in [({'error': SECRET}, 'provider_error'), ({'search_metadata': {'status': 'Failed'}}, 'provider_error'),
                            ({'search_metadata': {'status': 'Success'}, 'organic_results': {}}, 'malformed_response')]:
        result = reddit.search_leads('honeypot', ['CryptoScams'], WINDOW, CREDS,
                                   transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
        assert result['coverage']['reason'] == reason and result['coverage']['last_http_status'] == 200
        assert SECRET not in json.dumps(result)
        if 'error' in payload:
            assert result['coverage']['provider_error_field_present'] is True
    empty = reddit.search_leads('honeypot', ['CryptoScams'], WINDOW, CREDS,
                               transport=httpx.MockTransport(lambda request: httpx.Response(200, json=page([]))))
    assert empty['status'] == 'partial' and empty['coverage']['reason'] == 'success_empty'
    assert empty['coverage']['last_http_status'] == 200 and 'provider_error_field_present' not in empty['coverage']
    def timeout(request):
        raise httpx.ReadTimeout(SECRET, request=request)
    result = reddit.search_leads('honeypot', ['CryptoScams'], WINDOW, CREDS, transport=httpx.MockTransport(timeout))
    assert result['coverage']['reason'] == 'timeout' and SECRET not in json.dumps(result)
    monkeypatch.delenv('SEARCHAPI_API_KEY', raising=False)
    assert credentials_from_environment() is None
    missing = reddit.search_leads('honeypot', ['CryptoScams'], WINDOW, None, transport=httpx.MockTransport(timeout))
    assert missing['coverage']['reason'] == 'missing_searchapi_key' and missing['coverage']['requests'] == 0
    monkeypatch.setenv('SEARCHAPI_API_KEY', SECRET)
    assert SECRET not in repr(credentials_from_environment())
