"""Pure adapter for the investigation-owned Reddit provider; no network or storage.

Returned source links are short-lived leads, not immutable evidence or gate votes.
"""
import datetime as dt
import hashlib
import re
from urllib.parse import urlsplit

import discovery
import screening_result

PROFILE = 'scooby.reddit-leads/1'
_ADDRESS = re.compile(r'(?<![A-Za-z0-9])0x[0-9a-fA-F]{40}(?![A-Za-z0-9])')
_TICKER = re.compile(r'(?<![A-Za-z0-9_])\$([A-Za-z][A-Za-z0-9]{1,9})(?![A-Za-z0-9_])')
_POST = re.compile(r'^/r/([A-Za-z0-9_]{2,21})/comments/([A-Za-z0-9]{1,12})(?:/[^/?#]*)?/?$')
_CHAINS = {1: re.compile(r'\b(?:ethereum|ethereum mainnet)\b', re.I),
           8453: re.compile(r'\b(?:base\s+(?:chain|network|mainnet)|on\s+base)\b', re.I)}
_OTHER_CHAIN = re.compile(r'\b(?:bsc|bnb|binance smart chain|solana|sol)\b', re.I)


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


def adapt(result, *, allowed_subreddits, allowed_queries, now=None, removed_post_ids=(),
          max_capture_age=3600, max_post_age=604800):
    """Normalize a bounded search into transient, unverified, deletion-aware leads.

    `removed_post_ids` must come from the backend's authorized deletion/removal
    handling. The provider returns per-community coverage and page cursors.
    Cursors are informational until the shared provider supports cursor input.
    """
    if not isinstance(result, dict) or result.get('profile') != PROFILE:
        raise ValueError('unsupported search provider profile')
    if (not isinstance(allowed_subreddits, (list, tuple, set)) or not 1 <= len(allowed_subreddits) <= 3
            or any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z0-9_]{2,21}', x) for x in allowed_subreddits)):
        raise ValueError('one to three configured subreddit names required')
    allowed = {x.lower() for x in allowed_subreddits}
    if (not isinstance(allowed_queries, (list, tuple, set)) or not allowed_queries
            or any(not isinstance(x, str) or not 3 <= len(x.strip()) <= 100 for x in allowed_queries)):
        raise ValueError('configured query allowlist required')
    query = result.get('query')
    if not isinstance(query, str) or query not in allowed_queries:
        raise ValueError('query outside configured search policy')
    if (type(max_capture_age) is not int or not 1 <= max_capture_age <= 3600
            or type(max_post_age) is not int or not 1 <= max_post_age <= 604800):
        raise ValueError('invalid transient retention bounds')
    if (not isinstance(removed_post_ids, (list, tuple, set))
            or any(not isinstance(x, str) or not re.fullmatch(r't3_[a-z0-9]{1,12}', x) for x in removed_post_ids)):
        raise ValueError('invalid removed post IDs')
    removed = set(removed_post_ids)
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
    status, observations, coverage = result.get('status'), result.get('observations'), result.get('coverage')
    if (status not in ('partial', 'unavailable') or not isinstance(observations, list)
            or len(observations) > 40 or not isinstance(coverage, dict)):
        raise ValueError('invalid provider status or post bound')
    if status == 'unavailable' and observations:
        raise ValueError('unavailable source cannot contain observations')
    calls, examined, complete = coverage.get('requests'), coverage.get('posts_examined'), coverage.get('complete')
    max_calls, max_posts, scopes = coverage.get('max_requests'), coverage.get('max_posts'), coverage.get('scopes')
    if (type(max_calls) is not int or not 2 <= max_calls <= 5 or type(max_posts) is not int or not 1 <= max_posts <= 40
            or type(calls) is not int or not 0 <= calls <= max_calls or type(examined) is not int
            or not 0 <= examined <= max_posts or type(complete) is not bool or len(observations) > examined
            or (status == 'unavailable' and complete) or not isinstance(scopes, list) or not 1 <= len(scopes) <= 3):
        raise ValueError('invalid source coverage')
    scope_rows, seen_scopes = [], set()
    for scope in scopes:
        if not isinstance(scope, dict) or not isinstance(scope.get('subreddit'), str):
            raise ValueError('invalid source scope')
        name, state, cursor = scope['subreddit'].lower(), scope.get('state'), scope.get('next_cursor')
        if (name not in allowed or name in seen_scopes or state not in ('exhausted', 'truncated', 'failed', 'not_started')
                or (cursor is not None and (not isinstance(cursor, str) or not re.fullmatch(r't3_[a-z0-9]{1,12}', cursor)))
                or (state in ('exhausted', 'not_started') and cursor is not None)):
            raise ValueError('invalid source scope')
        seen_scopes.add(name)
        scope_rows.append({'subreddit': name, 'state': state, 'next_cursor': cursor})
    if complete != all(scope['state'] == 'exhausted' for scope in scope_rows):
        raise ValueError('inconsistent source completeness')
    seen, groups, expired_count, removed_count = {}, {}, 0, 0
    for item in observations:
        if not isinstance(item, dict):
            raise ValueError('search post observation required')
        community, post_id, url = _post(item.get('url'), allowed)
        if community not in seen_scopes:
            raise ValueError('post outside requested source scope')
        fullname = 't3_' + post_id
        if (item.get('id') != fullname or str(item.get('subreddit', '')).lower() != community
                or item.get('query') != query or item.get('attribution') != 'unresolved'
                or type(item.get('verified_concern_votes')) is not int or item['verified_concern_votes'] != 0):
            raise ValueError('provider post identity, query, or attribution mismatch')
        observed, fetched = _stamp(item.get('observed_at')), _stamp(item.get('fetched_at'))
        text, digest = item.get('excerpt'), item.get('content_sha256')
        if (not start <= observed < end or not end <= fetched <= now or not isinstance(text, str)
                or not text.strip() or len(text) > 400 or not isinstance(digest, str)
                or not re.fullmatch(r'[0-9a-f]{64}', digest)):
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
        hints = [chain for chain, pattern in _CHAINS.items() if pattern.search(text)]
        other_chain = bool(_OTHER_CHAIN.search(text))
        hint = hints[0] if len(hints) == 1 and not other_chain else None
        expiry = min(fetched + dt.timedelta(seconds=max_capture_age), observed + dt.timedelta(seconds=max_post_age))
        if fullname in removed:
            removed_count += 1
            continue
        if expiry <= now:
            expired_count += 1
            continue
        reference = {'post_id': fullname, 'url': url, 'subreddit': community,
                     'observed_at': observed.isoformat(), 'fetched_at': fetched.isoformat(),
                     'expires_at': expiry.isoformat(), 'query': query}
        prior = seen.get(fullname)
        signature = (community, observed, digest)
        if prior is not None:
            if prior != signature:
                raise ValueError('conflicting post identity or content')
            continue
        seen[fullname] = signature
        # Group repeated mentions while preserving source references. This is not
        # proof that separate posts, claims or token identities are independent.
        key = ('address', addresses[0], hint) if len(addresses) == 1 else ('post', fullname)
        if key not in groups:
            lead_id = 'reddit:' + hashlib.sha256(repr(key).encode('utf-8')).hexdigest()[:24]
            groups[key] = {'lead_id': lead_id, 'candidate_id': None,
                           'identifiers': {'addresses': addresses, 'tickers': tickers, 'chain_hint': hint,
                                           'unsupported_or_ambiguous_chain': other_chain or len(hints) > 1},
                           'references': [], 'reason': 'unverified_social_allegation', 'verified_concern_votes': 0}
        groups[key]['references'].append(reference)
    source_state = ('unavailable' if status == 'unavailable' else
                    'empty' if not observations and complete else 'partial')
    return {'profile': 'scooby.reddit-discovery-leads/1-proposal', 'status': source_state,
            'query': query, 'window': {'start': start.isoformat(), 'end': end.isoformat()},
            'coverage': {'requests': calls, 'posts_examined': examined, 'complete': complete,
                         'scopes': scope_rows,
                         'unsearched_scope': [scope['subreddit'] for scope in scope_rows if scope['state'] != 'exhausted'],
                         'cursor_input_supported': False,
                         'expired_observations': expired_count, 'removed_observations': removed_count},
            'reason': 'provider_unavailable' if source_state == 'unavailable' else
                      'no_matching_posts' if source_state == 'empty' else 'unverified_partial_search',
            'leads': sorted(groups.values(), key=lambda x: x['lead_id'])}


def resolve_identity(lead, candidate_record, evidence_root, *, now=None, removed_post_ids=()):
    """Resolve a social lead only using an explicit chain mention and current on-chain verifier.

    Candidate records and evidence must come from a trusted backend. A source
    association is still an allegation; this does not verify the claimed mechanism.
    Caller must enforce source deletion/expiry and revalidate before any job.
    """
    if not isinstance(lead, dict) or lead.get('candidate_id') is not None:
        raise ValueError('unresolved lead required')
    now = now or dt.datetime.now(dt.timezone.utc)
    if not isinstance(now, dt.datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('timezone-aware current time required')
    now = now.astimezone(dt.timezone.utc)
    ident = lead.get('identifiers', {})
    addresses = ident.get('addresses', [])
    chain = ident.get('chain_hint')
    if (not isinstance(addresses, list) or len(addresses) != 1 or type(chain) is not int or chain not in (1, 8453)
            or ident.get('unsupported_or_ambiguous_chain') is not False):
        raise ValueError('social chain/address attribution is ambiguous')
    if (not isinstance(lead.get('references'), list) or not lead['references']
            or any(r.get('post_id') in removed_post_ids or _stamp(r.get('expires_at')) <= now for r in lead['references'])):
        raise ValueError('source is removed or expired')
    for reference in lead['references']:
        observed, fetched, expiry = (_stamp(reference.get(key)) for key in ('observed_at', 'fetched_at', 'expires_at'))
        if fetched > now or observed > fetched or expiry > min(fetched + dt.timedelta(hours=1), observed + dt.timedelta(days=7)):
            raise ValueError('invalid source lifetime')
    candidate = candidate_record.get('identity', {})
    if candidate.get('chain_id') != chain or candidate.get('address') != addresses[0]:
        raise ValueError('social identity does not match candidate')
    result = screening_result.screening_result(candidate_record, evidence_root, 'reddit_identity_resolution', now)
    # A pinned verifier checks chain, token/pool identity, finalized block and
    # response integrity even when its concern outcome is unknown.
    if not any(group['evidence'] for group in result['groups']):
        raise ValueError('no independent chain-bound identity evidence')
    return {'lead_id': lead['lead_id'], 'candidate_id': result['candidate']['candidate_id'],
            'identity': result['candidate'], 'screening_snapshot': result,
            'source_leads': list(lead['references']),
            'association': 'post_chain_and_address_mention_with_independent_token_identity',
            'limitation': 'The post allegation and its association with the token remain unverified.',
            'social_concern_votes': 0}


def deduplicate_resolutions(resolutions):
    """Group already-resolved references by canonical chain/address, never votes."""
    if not isinstance(resolutions, list):
        raise ValueError('resolved lead list required')
    groups = {}
    for item in resolutions:
        if not isinstance(item, dict) or item.get('social_concern_votes') != 0:
            raise ValueError('invalid resolved lead')
        identity = item.get('identity', {})
        chain, address = identity.get('chain_id'), identity.get('address')
        if type(chain) is not int or not isinstance(address, str) or address != address.lower():
            raise ValueError('canonical candidate identity required')
        candidate_id = discovery.identity(chain, address)
        if (item.get('candidate_id') != candidate_id or not isinstance(item.get('lead_id'), str)
                or item.get('association') != 'post_chain_and_address_mention_with_independent_token_identity'):
            raise ValueError('candidate identity mismatch')
        groups.setdefault(candidate_id, set()).add(item['lead_id'])
    return [{'candidate_id': key, 'lead_ids': sorted(value)} for key, value in sorted(groups.items())]
