"""Local, offline ingestion of attributed Reddit search results as unverified leads.

This module never contacts Reddit, owns no credentials, and does not resolve tokens.
The shared investigation provider must supply the bounded search result.
"""
import datetime as dt
import re
import sqlite3
from urllib.parse import urlsplit

import discovery

PROFILE = 'scooby.reddit-leads/1'
_ADDRESS = re.compile(r'(?<![A-Za-z0-9])0x[0-9a-fA-F]{40}(?![A-Za-z0-9])')
_TICKER = re.compile(r'(?<![A-Za-z0-9_])\$([A-Za-z][A-Za-z0-9]{1,9})(?![A-Za-z0-9_])')
_POST = re.compile(r'^/r/([A-Za-z0-9_]{2,21})/comments/([A-Za-z0-9]{1,12})(?:/[^/?#]*)?/?$')


def _stamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp required')
    return discovery.stamp(value)


def _post(url, allowlist):
    if not isinstance(url, str):
        raise ValueError('post URL required')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc.lower() not in ('reddit.com', 'www.reddit.com')
            or parsed.query or parsed.fragment):
        raise ValueError('invalid Reddit post URL')
    match = _POST.fullmatch(parsed.path)
    if not match or match.group(1).lower() not in allowlist:
        raise ValueError('post outside allowed communities')
    community, post_id = match.group(1).lower(), match.group(2).lower()
    return community, post_id, f'https://www.reddit.com/r/{community}/comments/{post_id}/'


def ingest(db, result, *, allowed_subreddits, allowed_queries, max_posts=100, now=None):
    """Persist bounded, provider-attributed posts; all identifiers remain unresolved.

    Caller owns access, provider budget and configured source availability. This is an
    isolated prototype store, not the backend durable lead repository or a gate input.
    Malformed batches fail atomically; unavailable provider results retain no posts.
    """
    if not isinstance(result, dict) or result.get('profile') != PROFILE:
        raise ValueError('unsupported search provider profile')
    if not isinstance(allowed_subreddits, (list, tuple, set)) or not allowed_subreddits:
        raise ValueError('nonempty configured subreddit allowlist required')
    if any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z0-9_]{2,21}', x) for x in allowed_subreddits):
        raise ValueError('invalid subreddit allowlist')
    allowed = {x.lower() for x in allowed_subreddits}
    if not isinstance(allowed_queries, (list, tuple, set)) or not allowed_queries:
        raise ValueError('nonempty configured query allowlist required')
    if any(not isinstance(x, str) or not x.strip() or len(x) > 100 for x in allowed_queries):
        raise ValueError('invalid query allowlist')
    query = result.get('query')
    if query not in allowed_queries:
        raise ValueError('query outside configured search policy')
    if isinstance(max_posts, bool) or not isinstance(max_posts, int) or not 1 <= max_posts <= 100:
        raise ValueError('invalid post bound')
    window = result.get('window')
    if not isinstance(window, dict):
        raise ValueError('search window required')
    start, end = _stamp(window.get('start')), _stamp(window.get('end'))
    now = now or dt.datetime.now(dt.timezone.utc)
    if not isinstance(now, dt.datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('timezone-aware current time required')
    now = now.astimezone(dt.timezone.utc)
    if end <= start or end - start > dt.timedelta(days=31) or end > now:
        raise ValueError('invalid or future search window')
    status = result.get('status')
    observations = result.get('observations')
    if status not in ('partial', 'unavailable') or not isinstance(observations, list) or len(observations) > max_posts:
        raise ValueError('invalid provider status or post bound')
    if status == 'unavailable' and observations:
        raise ValueError('unavailable source cannot contain observations')
    parsed = []
    for item in observations:
        if not isinstance(item, dict):
            raise ValueError('search post observation required')
        community, post_id, url = _post(item.get('url'), allowed)
        if (item.get('id') != 't3_' + post_id or str(item.get('subreddit', '')).lower() != community
                or item.get('query') != query or item.get('attribution') != 'unresolved'
                or item.get('verified_concern_votes') != 0):
            raise ValueError('provider post identity, query, or attribution mismatch')
        observed = _stamp(item.get('observed_at'))
        fetched = _stamp(item.get('fetched_at'))
        text = item.get('excerpt')
        digest = item.get('content_sha256')
        if (not start <= observed < end or not end <= fetched <= now or not isinstance(text, str) or not text.strip() or len(text) > 400
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise ValueError('invalid post observation')
        identifiers = item.get('extracted_identifiers')
        if not isinstance(identifiers, list) or len(identifiers) > 100:
            raise ValueError('invalid extracted identifiers')
        addresses = set()
        for identifier in identifiers:
            if (not isinstance(identifier, dict) or identifier.get('kind') != 'evm_address'
                    or identifier.get('chain_id') is not None or not isinstance(identifier.get('value'), str)
                    or not _ADDRESS.fullmatch(identifier['value'])):
                raise ValueError('invalid unresolved address')
            addresses.add(identifier['value'].lower())
        addresses.update(value.lower() for value in _ADDRESS.findall(text))
        addresses = sorted(addresses)
        tickers = sorted({value.upper() for value in _TICKER.findall(text)})
        parsed.append((community, post_id, url, observed.isoformat(), fetched.isoformat(), text, digest, addresses, tickers))
    con = sqlite3.connect(db)
    try:
        with con:
            con.execute('''CREATE TABLE IF NOT EXISTS reddit_leads (
                lead_id TEXT PRIMARY KEY, post_id TEXT UNIQUE NOT NULL, post_url TEXT NOT NULL,
                subreddit TEXT NOT NULL, observed_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
                claim_excerpt TEXT NOT NULL, content_sha256 TEXT NOT NULL, candidate_id TEXT)''')
            con.execute('''CREATE TABLE IF NOT EXISTS reddit_lead_queries (
                lead_id TEXT NOT NULL, query TEXT NOT NULL, window_start TEXT NOT NULL,
                window_end TEXT NOT NULL, PRIMARY KEY(lead_id, query, window_start, window_end))''')
            con.execute('''CREATE TABLE IF NOT EXISTS reddit_lead_identifiers (
                lead_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
                PRIMARY KEY(lead_id, kind, value))''')
            for community, post_id, url, observed, fetched, text, digest, addresses, tickers in parsed:
                lead_id = 'reddit:' + post_id
                existing = con.execute('SELECT subreddit, observed_at, content_sha256 FROM reddit_leads WHERE lead_id=?', (lead_id,)).fetchone()
                if existing and existing != (community, observed, digest):
                    raise ValueError('conflicting post identity or content; refresh requires explicit reconciliation')
                con.execute('INSERT OR IGNORE INTO reddit_leads VALUES(?,?,?,?,?,?,?,?,NULL)',
                            (lead_id, post_id, url, community, observed, fetched, text, digest))
                con.execute('INSERT OR IGNORE INTO reddit_lead_queries VALUES(?,?,?,?)',
                            (lead_id, query, start.isoformat(), end.isoformat()))
                for kind, values in (('address_mentioned', addresses), ('ticker_mentioned', tickers)):
                    con.executemany('INSERT OR IGNORE INTO reddit_lead_identifiers VALUES(?,?,?)',
                                    [(lead_id, kind, value) for value in values])
        return {'status': status, 'posts_received': len(parsed), 'candidate_ids_resolved': 0,
                'verified_concern_votes': 0,
                'limitation': 'Reddit allegations and identifier mentions are unverified leads only.'}
    finally:
        con.close()
