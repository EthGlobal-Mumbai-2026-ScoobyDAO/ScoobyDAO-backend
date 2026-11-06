"""Bounded, read-only Reddit OAuth evidence capture. No interpretation or model calls."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

_ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')
_ADDRESS_IN_TEXT = re.compile(r'(?<![A-Za-z0-9])0x[0-9a-fA-F]{40}(?![A-Za-z0-9])')
_SUBREDDIT = re.compile(r'^[A-Za-z0-9_]{2,21}$')
_FULLNAME = re.compile(r'^t3_[a-z0-9]+$')
_MENTION = re.compile(r'(?i)(?:https?://\S+|[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?<!\w)(?:u/|@)[\w-]+)')
_LANGUAGE = {
    'concern': re.compile(r'\b(?:scam|rugpull|rug|honeypot|blocked|cannot sell|cant sell|fraud|exploit|warning)\b', re.I),
    'support': re.compile(r'\b(?:promising|useful|trusted|bullish|positive|legitimate)\b', re.I),
}


@dataclass(frozen=True, repr=False)
class RedditCredentials:
    client_id: str
    client_secret: str
    user_agent: str
    # This assertion is supplied by the operator; this module cannot verify Reddit approval.
    approved: bool = False


def credentials_from_environment() -> RedditCredentials | None:
    """Load names only when caller explicitly attests existing app approval."""
    if os.getenv('SCOOBY_REDDIT_APPROVED', '').strip().lower() != 'true':
        return None
    client_id = os.getenv('SCOOBY_REDDIT_CLIENT_ID', '')
    secret = os.getenv('SCOOBY_REDDIT_CLIENT_SECRET', '')
    agent = os.getenv('SCOOBY_REDDIT_USER_AGENT', '')
    if not all((client_id, secret, agent)):
        return None
    return RedditCredentials(client_id, secret, agent, approved=True)


def _time(s: str) -> datetime:
    result = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('window timestamps must contain timezone offsets')
    return result.astimezone(timezone.utc)


def _redact(text: str) -> str:
    return _MENTION.sub('[redacted]', text).replace('\x00', '')[:400]


def _request(client, coverage, max_requests, method, url, **kwargs):
    if coverage['requests'] >= max_requests:
        return None
    if coverage.get('rate_limit_remaining') == 0:
        raise RuntimeError('Reddit rate limit reached; retry only after provider reset')
    coverage['requests'] += 1
    response = client.request(method, url, **kwargs)
    for header, field in (('x-ratelimit-remaining', 'rate_limit_remaining'),
                          ('x-ratelimit-reset', 'rate_limit_reset_seconds'), ('retry-after', 'retry_after_seconds')):
        try:
            if header in response.headers:
                coverage[field] = max(0.0, float(response.headers[header]))
        except ValueError:
            pass
    if response.status_code == 429:
        raise RuntimeError('Reddit rate limit reached; retry only after provider reset')
    response.raise_for_status()
    return response.json()


def search_leads(query: str, subreddits: list[str], window: dict, credentials: RedditCredentials | None,
                 *, max_requests: int = 5, max_posts: int = 40,
                 transport: httpx.BaseTransport | None = None) -> dict:
    """Bounded subreddit search for unverified leads, independent of token analysis.

    Reddit search only finds leads. Contract addresses are extracted without choosing a
    chain; tickers and unsupported-chain identifiers are never resolved automatically.
    """
    if not isinstance(query, str) or not 3 <= len(query.strip()) <= 200:
        raise ValueError('a bounded nonempty search query is required')
    if (not isinstance(subreddits, list) or not 1 <= len(subreddits) <= 3
            or any(not isinstance(s, str) or not _SUBREDDIT.fullmatch(s) for s in subreddits)
            or len({s.lower() for s in subreddits}) != len(subreddits)):
        raise ValueError('one to three distinct valid subreddit names required')
    if not 2 <= max_requests <= 12 or not 1 <= max_posts <= 100:
        raise ValueError('invalid request or post bound')
    start, end = _time(window['start']), _time(window['end'])
    if end <= start or end > datetime.now(timezone.utc):
        raise ValueError('window must be ordered and not extend into the future')
    result = {'profile': 'scooby.reddit-leads/1', 'status': 'unavailable', 'query': query,
              'window': {'start': start.isoformat(), 'end': end.isoformat()}, 'observations': [],
              'coverage': {'requests': 0, 'posts_examined': 0, 'max_requests': max_requests,
                           'max_posts': max_posts, 'complete': False,
                           'scopes': [{'subreddit': s, 'state': 'not_started', 'next_cursor': None} for s in subreddits],
                           'reason': 'Reddit credentials or approved application missing'},
              'limitations': ['Unverified allegations are leads, not evidence of a token mechanism or concern votes.',
                              'An address in a post does not establish chain, attribution or a current condition.',
                              'Keyword search is nonrepresentative and can be manipulated or omit relevant posts.']}
    if not credentials or not credentials.approved or not all((credentials.client_id, credentials.client_secret, credentials.user_agent)):
        return result
    c = result['coverage']; seen = set(); stopped = False; current_scope = None
    try:
        with httpx.Client(transport=transport, timeout=10, follow_redirects=False, headers={'User-Agent': credentials.user_agent}) as client:
            auth = _request(client, c, max_requests, 'POST', 'https://www.reddit.com/api/v1/access_token',
                            auth=(credentials.client_id, credentials.client_secret), data={'grant_type': 'client_credentials'})
            token = auth.get('access_token') if isinstance(auth, dict) else None
            if not token:
                raise RuntimeError('Reddit OAuth did not return an access token')
            headers = {'Authorization': 'Bearer ' + token}
            for current_scope in c['scopes']:
                subreddit = current_scope['subreddit']; after = None; cursors = set()
                if c['requests'] >= max_requests or c['posts_examined'] >= max_posts:
                    stopped = True
                    break
                current_scope['state'] = 'in_progress'
                while c['requests'] < max_requests and c['posts_examined'] < max_posts:
                    params = {'q': query, 'restrict_sr': 'true', 'sort': 'new', 't': 'all', 'type': 'link',
                              'limit': min(100, max_posts - c['posts_examined'])}
                    if after:
                        params['after'] = after
                    page = _request(client, c, max_requests, 'GET', f'https://oauth.reddit.com/r/{subreddit}/search',
                                    headers=headers, params=params)
                    listing = page['data']; children = listing['children']
                    if not isinstance(children, list):
                        raise ValueError('invalid Reddit listing')
                    fetched = datetime.now(timezone.utc).isoformat()
                    for entry in children[:max_posts - c['posts_examined']]:
                        item = entry.get('data', {}); c['posts_examined'] += 1
                        name, permalink, ts = item.get('name'), item.get('permalink'), item.get('created_utc')
                        if not isinstance(name, str) or not _FULLNAME.fullmatch(name) or name in seen:
                            continue
                        if not isinstance(permalink, str) or not permalink.startswith('/r/') or '?' in permalink or '#' in permalink:
                            continue
                        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
                            continue
                        try:
                            observed = datetime.fromtimestamp(ts, timezone.utc)
                        except (ValueError, OverflowError, OSError):
                            continue
                        if not start <= observed < end:
                            continue
                        raw = str(item.get('title', '')) + '\n' + str(item.get('selftext', ''))
                        addresses = sorted({m.group().lower() for m in _ADDRESS_IN_TEXT.finditer(raw)})
                        seen.add(name)
                        result['observations'].append({'id': name, 'subreddit': subreddit,
                            'url': 'https://www.reddit.com' + permalink, 'observed_at': observed.isoformat(),
                            'fetched_at': fetched, 'query': query, 'excerpt': _redact(raw.strip()),
                            'content_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                            'extracted_identifiers': [{'kind': 'evm_address', 'value': a, 'chain_id': None} for a in addresses],
                            'attribution': 'unresolved', 'verified_concern_votes': 0})
                    after = listing.get('after')
                    if after is not None and (not isinstance(after, str) or not _FULLNAME.fullmatch(after) or after in cursors):
                        raise ValueError('invalid or repeated Reddit cursor')
                    current_scope['next_cursor'] = after
                    if not after:
                        current_scope['state'] = 'exhausted'
                        break
                    cursors.add(after)
                if after:
                    current_scope['state'] = 'truncated'
                    stopped = True
            stopped = stopped or any(s['state'] != 'exhausted' for s in c['scopes'])
            c['complete'] = not stopped
            c['reason'] = 'bounded results; additional pages may exist' if stopped else 'search pages exhausted within bounds'
            result['status'] = 'partial'
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError, TypeError):
        if current_scope and current_scope['state'] == 'in_progress':
            current_scope['state'] = 'failed'
        c['reason'] = 'Reddit authentication, rate limit, transport, or response failure'
        result['status'] = 'partial' if result['observations'] else 'unavailable'
    return result


def summarize(observations: list[dict]) -> dict:
    """Provider-independent, auditable language counts over already-attributed excerpts.

    A hit is a word occurrence, not a judgment of the writer's position; negation,
    quotation and sarcasm are not resolved. Empty data is unavailable, never neutral.
    """
    if not isinstance(observations, list) or len(observations) > 200:
        raise ValueError('bounded observation list required')
    counts = {'concern': 0, 'support': 0, 'both': 0, 'no_configured_terms': 0}
    daily: dict[str, dict[str, int]] = {}
    references = []
    for item in observations:
        text, sha, url, stamp = item.get('excerpt'), item.get('content_sha256'), item.get('url'), item.get('observed_at')
        if not isinstance(text, str) or len(text) > 400 or not re.fullmatch(r'[0-9a-f]{64}', str(sha)) or not str(url).startswith('https://'):
            raise ValueError('observation lacks bounded excerpt, HTTPS source, or SHA-256')
        day = _time(stamp).date().isoformat()
        terms = [name for name, pattern in _LANGUAGE.items() if pattern.search(text)]
        label = 'both' if len(terms) == 2 else (terms[0] if terms else 'no_configured_terms')
        counts[label] += 1
        daily.setdefault(day, {k: 0 for k in counts})[label] += 1
        references.append({'content_sha256': sha, 'url': url, 'matched_categories': terms})
    return {'status': 'partial' if observations else 'unavailable', 'method': 'literal-term-presence/1',
            'counts': counts if observations else None,
            'daily': [{'date': date, **values} for date, values in sorted(daily.items())],
            'evidence': references,
            'limitations': ['Keyword presence is not sentiment classification; negation, sarcasm, quotation and selection bias remain unresolved.',
                            'Counts reflect supplied excerpts, not people, independent posts, or market-wide opinion.']}


def collect(candidate: dict, window: dict, credentials: RedditCredentials | None, *,
            max_requests: int = 5, max_posts: int = 25, max_comments: int = 20,
            transport: httpx.BaseTransport | None = None) -> dict:
    """Capture explicitly attributed observations. Counts include OAuth and comment reads.

    Candidate requires chain_id, address, and optionally project_alias + alias_evidence_url.
    Caller owns authorization, budget and storage; no OAuth token is persisted in output.
    """
    chain, address = candidate.get('chain_id'), candidate.get('address', '')
    if isinstance(chain, bool) or not isinstance(chain, int) or chain <= 0 or not _ADDRESS.fullmatch(address):
        raise ValueError('a positive chain id and EVM token address are required')
    start, end = _time(window['start']), _time(window['end'])
    if end <= start or end > datetime.now(timezone.utc):
        raise ValueError('window must be ordered and not extend into the future')
    if not (2 <= max_requests <= 12 and 1 <= max_posts <= 100 and 0 <= max_comments <= 100):
        raise ValueError('invalid request, post, or comment bound')
    alias = candidate.get('project_alias', '').strip()
    alias_source = candidate.get('alias_evidence_url', '')
    if alias and (len(alias) < 5 or not alias_source.startswith('https://')):
        raise ValueError('project alias requires at least five characters and an HTTPS attribution source')
    result: dict[str, Any] = {
        'profile': 'scooby.reddit-evidence/1', 'candidate_id': f'{chain}:{address.lower()}',
        'window': {'start': start.isoformat(), 'end': end.isoformat()}, 'status': 'unavailable',
        'observations': [], 'interpretation': None,
        'coverage': {'requests': 0, 'posts_examined': 0, 'comments_examined': 0,
                     'max_requests': max_requests, 'max_posts': max_posts, 'max_comments': max_comments,
                     'query_scopes': [{'query': q, 'state': 'not_started', 'next_cursor': None}
                                      for q in [address] + ([f'"{alias}"'] if alias else [])],
                     'complete': False, 'reason': 'Reddit credentials or approved application missing'},
        'limitations': ['Search is not representative of all holders or all Reddit discussion.',
                        'Text can be manipulated, coordinated or promotional; engagement is not independent sentiment.',
                        'Address mentions may discuss another chain; alias attribution is weaker than address attribution.',
                        'No sentiment inference, vote, or model analysis was performed.'],
    }
    if not credentials or not credentials.approved or not all((credentials.client_id, credentials.client_secret, credentials.user_agent)):
        return result
    c = result['coverage']
    current_scope = None
    def request(client, method, url, **kwargs):
        return _request(client, c, max_requests, method, url, **kwargs)
    seen: set[str] = set()
    comments_for: list[tuple[str, str]] = []
    def retain(item: dict, kind: str, parent_attributed: bool = False, query: str = ''):
        raw = str(item.get('title', '')) + '\n' + str(item.get('selftext' if kind == 'post' else 'body', ''))
        lower = raw.lower()
        direct = address.lower() in lower
        alias_hit = bool(alias and re.search(r'(?<!\w)' + re.escape(alias.lower()) + r'(?!\w)', lower))
        if not direct and not alias_hit and not (kind == 'comment' and parent_attributed):
            return False
        created = item.get('created_utc')
        if isinstance(created, bool) or not isinstance(created, (int, float)):
            return False
        try:
            t = datetime.fromtimestamp(created, timezone.utc)
        except (ValueError, OverflowError, OSError):
            return False
        if not start <= t < end:
            return False
        permalink = item.get('permalink', '')
        if not isinstance(permalink, str) or not permalink.startswith('/r/') or '?' in permalink or '#' in permalink:
            return False
        identifier = item.get('name') or permalink
        if identifier in seen:
            return False
        seen.add(identifier)
        result['observations'].append({'kind': kind, 'id': identifier, 'subreddit': item.get('subreddit'),
            'url': 'https://www.reddit.com' + permalink, 'query': query,
            'observed_at': t.isoformat(), 'fetched_at': datetime.now(timezone.utc).isoformat(), 'excerpt': _redact(raw.strip()),
            'content_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            'attribution': 'address_mentioned' if direct else ('operator_sourced_project_alias' if alias_hit else 'comment_on_attributed_post'),
            'alias_evidence_url': alias_source if alias_hit and not direct else None})
        return True
    try:
        with httpx.Client(transport=transport, timeout=10, follow_redirects=False,
                          headers={'User-Agent': credentials.user_agent}) as client:
            auth = request(client, 'POST', 'https://www.reddit.com/api/v1/access_token',
                           auth=(credentials.client_id, credentials.client_secret), data={'grant_type': 'client_credentials'})
            token = auth.get('access_token') if isinstance(auth, dict) else None
            if not token:
                raise RuntimeError('Reddit OAuth did not return an access token')
            headers = {'Authorization': 'Bearer ' + token}
            # Search exact address first. Alias search is separate and retains weaker attribution.
            stopped = False
            for current_scope in c['query_scopes']:
                query = current_scope['query']; after = None; cursors = set()
                if c['requests'] >= max_requests or c['posts_examined'] >= max_posts:
                    stopped = True
                    break
                current_scope['state'] = 'in_progress'
                while c['requests'] < max_requests and c['posts_examined'] < max_posts:
                    params = {'q': query, 'sort': 'new', 't': 'all', 'type': 'link',
                              'limit': min(100, max_posts - c['posts_examined'])}
                    if after:
                        params['after'] = after
                    page = request(client, 'GET', 'https://oauth.reddit.com/search', headers=headers, params=params)
                    listing = page['data']; children = listing['children']
                    if not isinstance(children, list):
                        raise ValueError('invalid Reddit listing')
                    for entry in children[:max_posts - c['posts_examined']]:
                        item = entry.get('data', {}); c['posts_examined'] += 1
                        if retain(item, 'post', query=query) and _FULLNAME.fullmatch(str(item.get('name', ''))):
                            comments_for.append((item['name'][3:], query))
                    after = listing.get('after')
                    if after is not None and (not isinstance(after, str) or not _FULLNAME.fullmatch(after) or after in cursors):
                        raise ValueError('invalid or repeated Reddit cursor')
                    current_scope['next_cursor'] = after
                    if not after:
                        current_scope['state'] = 'exhausted'
                        break
                    cursors.add(after)
                if after:
                    current_scope['state'] = 'truncated'
                    stopped = True
            stopped = stopped or any(s['state'] != 'exhausted' for s in c['query_scopes'])
            for post_id, query in comments_for:
                if c['requests'] >= max_requests or c['comments_examined'] >= max_comments:
                    stopped = True
                    break
                page = request(client, 'GET', f'https://oauth.reddit.com/comments/{post_id}', headers=headers,
                               params={'limit': max_comments - c['comments_examined'], 'depth': 1, 'sort': 'new'})
                if not isinstance(page, list) or len(page) < 2:
                    raise ValueError('invalid Reddit comments listing')
                for entry in page[1]['data']['children'][:max_comments - c['comments_examined']]:
                    if entry.get('kind') != 't1':
                        continue
                    c['comments_examined'] += 1
                    retain(entry.get('data', {}), 'comment', parent_attributed=True, query=query)
            c['complete'] = not stopped
            c['reason'] = 'bounded results; additional pages or comments may exist' if stopped else 'search pages exhausted within bounds'
            result['status'] = 'partial'  # search cannot establish representative sentiment
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError, TypeError):
        if current_scope and current_scope['state'] == 'in_progress':
            current_scope['state'] = 'failed'
        c['reason'] = 'Reddit authentication, rate limit, transport, or response failure'
        result['status'] = 'partial' if result['observations'] else 'unavailable'
    result['interpretation'] = summarize(result['observations'])
    return result
