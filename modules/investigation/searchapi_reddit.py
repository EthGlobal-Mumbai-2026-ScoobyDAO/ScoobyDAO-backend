"""SearchApi Reddit search: bounded one-page default, no persistence or fallback."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlsplit

import httpx

from . import reddit_search as shared

_ENDPOINT = 'https://www.searchapi.io/api/v1/search'
_PERIODS = {'last_hour', 'last_day', 'last_week', 'last_month', 'last_year', 'any_time'}
_COMMENT_ID = re.compile(r'^t1_[a-z0-9]+$')


@dataclass(frozen=True, repr=False)
class SearchApiCredentials:
    api_key: str


def credentials_from_environment() -> SearchApiCredentials | None:
    """Read a process-injected secret; never consult the Windows user registry here."""
    key = os.getenv('SEARCHAPI_API_KEY', '')
    return SearchApiCredentials(key) if key else None


def social_window(days: int = 365, *, end: datetime | None = None) -> dict:
    """Provisional configurable lookback; not a fresh-incident policy."""
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
        raise ValueError('lookback must be between 1 and 3650 days')
    instant = end or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('lookback end must be timezone-aware')
    instant = instant.astimezone(timezone.utc)
    return {'start': (instant - timedelta(days=days)).isoformat(), 'end': instant.isoformat()}


def _valid_link(link, subreddit, post_id):
    if not isinstance(link, str) or len(link) > 1000:
        return False
    try:
        url = urlsplit(link)
    except ValueError:
        return False
    parts = url.path.split('/')
    return (url.scheme == 'https' and url.netloc in ('www.reddit.com', 'reddit.com')
            and not url.query and not url.fragment and len(parts) >= 6
            and parts[1].lower() == 'r' and parts[2].lower() == subreddit.lower()
            and parts[3].lower() == 'comments' and parts[4].lower() == post_id[3:].lower())


def search(query: str, subreddits: list[str | None], window: dict, credentials: SearchApiCredentials | None,
           *, max_requests: int = 1, max_posts: int = 40, time_period: str = 'any_time',
           max_comment_snippets: int = 20,
           cancelled: Callable[[], bool] | None = None, transport: httpx.BaseTransport | None = None) -> dict:
    """Search at most max_requests pages. Query results and cursors are transient."""
    if not isinstance(query, str) or not 3 <= len(query.strip()) <= 200:
        raise ValueError('a bounded search query is required')
    if (not isinstance(subreddits, list) or not 1 <= len(subreddits) <= 3
            or any(s is not None and (not isinstance(s, str) or not shared._SUBREDDIT.fullmatch(s)) for s in subreddits)
            or len({s.lower() if s is not None else None for s in subreddits}) != len(subreddits)):
        raise ValueError('one to three distinct valid subreddit scopes are required')
    if isinstance(max_requests, bool) or not 1 <= max_requests <= 12 or isinstance(max_posts, bool) or not 1 <= max_posts <= 100:
        raise ValueError('invalid provider request or post budget')
    if isinstance(max_comment_snippets, bool) or not 0 <= max_comment_snippets <= 100:
        raise ValueError('invalid comment snippet limit')
    if time_period not in _PERIODS:
        raise ValueError('unsupported provider time period')
    if credentials is not None and not isinstance(credentials, SearchApiCredentials):
        raise ValueError('SearchApi credentials required; Reddit OAuth is an explicit separate adapter')
    if credentials is not None and (not isinstance(credentials.api_key, str) or
                                    any(ord(c) < 32 or ord(c) == 127 for c in credentials.api_key)):
        raise ValueError('invalid provider credential format')
    start, end = shared._time(window['start']), shared._time(window['end'])
    now = datetime.now(timezone.utc)
    if end <= start or end > now:
        raise ValueError('window must be ordered and not extend into the future')
    if credentials and credentials.api_key and (credentials.api_key in query or any(
            s is not None and credentials.api_key in s for s in subreddits)):
        raise ValueError('search inputs must not contain provider credentials')
    result = {'profile': 'scooby.reddit-leads/1', 'provider': 'searchapi.io', 'status': 'unavailable',
        'query': query, 'window': {'start': start.isoformat(), 'end': end.isoformat()}, 'observations': [],
        'coverage': {'requests': 0, 'posts_examined': 0, 'max_requests': max_requests, 'max_posts': max_posts,
            'matching_comment_snippets': 0, 'max_comment_snippets': max_comment_snippets,
            'complete': False, 'reason': 'missing_searchapi_key',
            'excluded': {'outside_window': 0, 'future': 0, 'missing_or_invalid_date': 0,
                         'wrong_subreddit': 0, 'invalid_source': 0, 'duplicate': 0},
            'scopes': [{'subreddit': s, 'state': 'not_started', 'next_cursor': None} for s in subreddits]},
        'limitations': ['SearchApi returned search-result metadata, not full post bodies or comment trees.',
                        'Provider date filtering can be wrong; caller window is checked locally.',
                        'Mentions and allegations are unverified leads, not identity or verified concern votes.',
                        'The sampled titles/snippets do not represent all holders and may be manipulated.',
                        'Output is transient and requires a reviewed retention/deletion lifecycle before storage.']}
    if not credentials or not credentials.api_key:
        return result
    secret = credentials.api_key
    c = result['coverage']; seen = set(); current_scope = None; successful = 0
    try:
        with httpx.Client(transport=transport, timeout=10, follow_redirects=False,
                          headers={'Authorization': 'Bearer ' + secret}) as client:
            for current_scope in c['scopes']:
                if c['requests'] >= max_requests or c['posts_examined'] >= max_posts:
                    break
                current_scope['state'] = 'in_progress'; cursor = None; cursors = set()
                while c['requests'] < max_requests and c['posts_examined'] < max_posts:
                    if cancelled and cancelled():
                        c['reason'] = 'cancelled'; current_scope['state'] = 'cancelled'
                        return result
                    params = {'engine': 'reddit_search', 'q': query, 'sort_by': 'new',
                              'time_period': time_period, 'safe': 'active'}
                    if current_scope['subreddit'] is not None:
                        params['subreddit'] = current_scope['subreddit']
                    if cursor:
                        params['next_page_token'] = cursor
                    c['requests'] += 1
                    response = client.get(_ENDPOINT, params=params)
                    c['last_http_status'] = response.status_code
                    if response.status_code in (401, 403):
                        c['reason'] = 'authentication_denied'; current_scope['state'] = 'failed'; return result
                    if response.status_code == 429:
                        c['reason'] = 'rate_limited'; current_scope['state'] = 'failed'
                        try:
                            c['retry_after_seconds'] = max(0.0, float(response.headers.get('retry-after', '')))
                        except ValueError:
                            pass
                        return result
                    if response.status_code != 200:
                        c['reason'] = 'http_error'; current_scope['state'] = 'failed'; return result
                    try:
                        page = response.json()
                    except ValueError:
                        c['reason'] = 'malformed_response'; current_scope['state'] = 'failed'; return result
                    if not isinstance(page, dict):
                        c['reason'] = 'malformed_response'; current_scope['state'] = 'failed'; return result
                    if page.get('error') or (isinstance(page.get('search_metadata'), dict)
                                             and page['search_metadata'].get('status') not in (None, 'Success')):
                        c['provider_error_field_present'] = bool(page.get('error'))
                        c['provider_status_category'] = ('failed' if isinstance(page.get('search_metadata'), dict)
                            and page['search_metadata'].get('status') not in (None, 'Success') else 'unknown')
                        c['reason'] = 'provider_error'; current_scope['state'] = 'failed'; return result
                    if not isinstance(page.get('search_metadata'), dict) or page['search_metadata'].get('status') != 'Success' or not isinstance(page.get('organic_results'), list):
                        c['reason'] = 'malformed_response'; current_scope['state'] = 'failed'; return result
                    fetched = datetime.now(timezone.utc).isoformat(); successful += 1; result['status'] = 'partial'
                    remaining = max_posts - c['posts_examined']
                    dropped_on_page = len(page['organic_results']) > remaining
                    for item in page['organic_results'][:remaining]:
                        c['posts_examined'] += 1
                        if not isinstance(item, dict):
                            c['excluded']['invalid_source'] += 1; continue
                        post_id, link = item.get('id'), item.get('link')
                        sub = item.get('subreddit', {})
                        sub = sub.get('name') if isinstance(sub, dict) else None
                        if not isinstance(post_id, str) or not shared._FULLNAME.fullmatch(post_id) or not isinstance(sub, str) or not shared._SUBREDDIT.fullmatch(sub) or not _valid_link(link, sub, post_id) or secret in link or secret in post_id or secret in sub:
                            c['excluded']['invalid_source'] += 1; continue
                        if current_scope['subreddit'] and sub.lower() != current_scope['subreddit'].lower():
                            c['excluded']['wrong_subreddit'] += 1; continue
                        if post_id in seen:
                            c['excluded']['duplicate'] += 1; continue
                        seen.add(post_id)
                        try:
                            if not isinstance(item.get('iso_date'), str):
                                raise ValueError('missing')
                            observed = shared._time(item['iso_date'])
                        except (ValueError, TypeError, AttributeError):
                            c['excluded']['missing_or_invalid_date'] += 1; continue
                        if observed > datetime.now(timezone.utc):
                            c['excluded']['future'] += 1; continue
                        if not start <= observed < end:
                            c['excluded']['outside_window'] += 1; continue
                        title = item.get('title')
                        if not isinstance(title, str) or not title.strip():
                            c['excluded']['invalid_source'] += 1; continue
                        comment = item.get('matching_comment')
                        snippet = comment.get('snippet') if isinstance(comment, dict) else None
                        comment_id = comment.get('id') if isinstance(comment, dict) else None
                        if (not isinstance(snippet, str) or not _COMMENT_ID.fullmatch(str(comment_id))
                                or secret in str(comment_id) or c['matching_comment_snippets'] >= max_comment_snippets):
                            snippet = None; comment_id = None
                        if snippet:
                            c['matching_comment_snippets'] += 1
                        raw_text = title + ('\n' + snippet if snippet else '')
                        safe_text = raw_text.replace(secret, '[redacted]')
                        excerpt = shared._redact(safe_text)
                        addresses = sorted({m.group().lower() for m in shared._ADDRESS_IN_TEXT.finditer(safe_text)})
                        # No author identity, raw response or raw-content hash is retained.
                        obs = {'id': post_id, 'subreddit': sub, 'url': link, 'observed_at': observed.isoformat(),
                            'fetched_at': fetched, 'query': query, 'excerpt': excerpt,
                            'age_days': (datetime.fromisoformat(fetched) - observed).total_seconds() / 86400,
                            'source_mode': 'dated_social_context',
                            'content_sha256': hashlib.sha256(excerpt.encode('utf-8')).hexdigest(),
                            'content_hash_scope': 'redacted_excerpt_only', 'provider': 'searchapi.io',
                            'source_components': ['title'] + (['matching_comment_snippet'] if snippet else []),
                            'extracted_identifiers': [{'kind': 'evm_address', 'value': a, 'chain_id': None} for a in addresses],
                            'attribution': 'unresolved', 'verified_concern_votes': 0}
                        if comment_id:
                            obs['matching_comment_id'] = comment_id
                        for name in ('score', 'comments'):
                            if isinstance(item.get(name), int) and not isinstance(item.get(name), bool):
                                obs[name] = item[name]
                        result['observations'].append(obs)
                    pagination = page.get('pagination', {})
                    if not isinstance(pagination, dict):
                        c['reason'] = 'malformed_response'; current_scope['state'] = 'failed'; return result
                    next_cursor = pagination.get('next_page_token')
                    if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor or len(next_cursor) > 4096 or next_cursor in cursors or secret in next_cursor):
                        c['reason'] = 'invalid_or_repeated_cursor'; current_scope['state'] = 'failed'; return result
                    current_scope['next_cursor'] = next_cursor
                    if not next_cursor:
                        current_scope['state'] = 'truncated' if dropped_on_page else 'exhausted'; break
                    cursors.add(next_cursor); cursor = next_cursor
                if current_scope['state'] == 'in_progress':
                    current_scope['state'] = 'truncated'
            c['complete'] = all(s['state'] == 'exhausted' for s in c['scopes'])
            c['reason'] = ('bounded_or_unsearched_scope' if not c['complete'] else
                           ('success_empty' if not c['posts_examined'] else
                            ('outside_window_only' if not result['observations'] and c['excluded']['outside_window'] else 'success')))
            result['status'] = 'partial' if successful else 'unavailable'
    except httpx.TimeoutException:
        c['reason'] = 'timeout'
        if current_scope: current_scope['state'] = 'failed'
    except httpx.HTTPError:
        c['reason'] = 'transport_error'
        if current_scope: current_scope['state'] = 'failed'
    if successful:
        result['status'] = 'partial'
    return result


def collect(candidate: dict, window: dict, credentials: SearchApiCredentials | None, *,
            max_requests: int = 1, max_posts: int = 25, max_comments: int = 20,
            subreddits: list[str] | None = None, time_period: str = 'any_time',
            cancelled: Callable[[], bool] | None = None, transport: httpx.BaseTransport | None = None) -> dict:
    """Return candidate-context observations without asserting token identity or sentiment."""
    chain, address = candidate.get('chain_id'), candidate.get('address', '')
    if isinstance(chain, bool) or not isinstance(chain, int) or chain <= 0 or not shared._ADDRESS.fullmatch(address):
        raise ValueError('positive chain id and EVM token address required')
    alias = candidate.get('project_alias', '').strip(); alias_source = candidate.get('alias_evidence_url', '')
    if alias and (len(alias) < 5 or not alias_source.startswith('https://')):
        raise ValueError('project alias requires at least five characters and an HTTPS attribution source')
    result = search(address, subreddits or [None], window, credentials, max_requests=max_requests,
                    max_posts=max_posts, max_comment_snippets=max_comments, time_period=time_period,
                    cancelled=cancelled, transport=transport)
    result['profile'] = 'scooby.reddit-evidence/1'
    result['candidate_id'] = f'{chain}:{address.lower()}'
    retained = []
    for obs in result['observations']:
        direct = any(x['value'] == address.lower() for x in obs['extracted_identifiers'])
        alias_hit = bool(alias and re.search(r'(?<!\w)' + re.escape(alias.lower()) + r'(?!\w)', obs['excerpt'].lower()))
        if not direct and not alias_hit:
            continue
        obs['attribution'] = 'address_mentioned' if direct else 'operator_sourced_project_alias'
        obs['attribution_scope'] = 'title_or_matching_comment_snippet'
        obs['alias_evidence_url'] = alias_source if alias_hit and not direct else None
        retained.append(obs)
    result['coverage']['unattributed_excluded'] = len(result['observations']) - len(retained)
    result['observations'] = retained
    result['interpretation'] = shared.summarize(retained)
    result['limitations'].append('An address mention can concern another chain; alias/source attribution is an operator assertion.')
    return result
