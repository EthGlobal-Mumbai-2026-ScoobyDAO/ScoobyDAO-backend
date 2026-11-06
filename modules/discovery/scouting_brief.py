"""Produce source-grounded scout rationale; never dispatch or promote provider hints to votes."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import discovery
import screening_result

PROFILE = 'scooby.scouting-brief/1-proposal'
POLICY = 'pilot-actionability-v1'
MAX_HINT_AGE_SECONDS = 3600
# These are provider statements, not verified findings or separate gate groups.
_FLAG_HINTS = {
    'is_honeypot': ('provider_honeypot_flag', 'Provider reports a possible honeypot; independent sell testing is required.'),
    'cannot_sell_all': ('provider_sell_restriction', 'Provider reports a possible sell restriction; independent testing is required.'),
    'is_blacklisted': ('provider_blacklist_flag', 'Provider reports a possible blacklist capability; contract control needs verification.'),
    'is_mintable': ('provider_mint_flag', 'Provider reports a possible mint capability; contract control needs verification.'),
    'transfer_pausable': ('provider_pause_flag', 'Provider reports transfers may be pausable; contract control needs verification.'),
    'hidden_owner': ('provider_hidden_owner', 'Provider reports a possible hidden owner; contract control needs verification.'),
    'owner_change_balance': ('provider_balance_control', 'Provider reports possible owner balance control; contract control needs verification.'),
}


def _checked_snapshot(record, root, evidence, now):
    digest, path, fetched = evidence.get('sha256'), evidence.get('source'), evidence.get('fetched_at')
    if (evidence.get('kind') != 'live_observation' or not isinstance(digest, str)
            or not re.fullmatch(r'[0-9a-f]{64}', digest) or evidence.get('id') != digest
            or path != 'snapshots/' + digest + '.json' or not isinstance(fetched, str)):
        raise ValueError('invalid provider provenance')
    fetched_time = discovery.stamp(fetched)
    age = (now - fetched_time).total_seconds()
    if age < 0 or age > MAX_HINT_AGE_SECONDS:
        raise ValueError('provider response is stale or future')
    root = Path(root)
    target = root / path
    if target.is_symlink() or target.parent.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('unsafe provider snapshot')
    raw = target.read_bytes()
    if len(raw) > 3_000_000 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('provider snapshot integrity failure')
    document = json.loads(raw)
    if not isinstance(document, dict) or document.get('code') != 1 or not isinstance(document.get('result'), dict):
        raise ValueError('provider response unavailable')
    address = record['identity']['address']
    entries = [(key, value) for key, value in document['result'].items()
               if isinstance(key, str) and key.lower() == address]
    if len(entries) != 1 or not isinstance(entries[0][1], dict):
        raise ValueError('provider candidate identity mismatch')
    return entries[0][1], {'id': digest, 'source': path, 'sha256': digest,
                            'fetched_at': fetched_time.isoformat(), 'observed_at': None}


def _provider_observations(record, root, now):
    """Read only the latest trusted-capture GoPlus response for this chain/address."""
    chain, address = record['identity']['chain_id'], record['identity']['address']
    expected = f'Request URL: https://api.gopluslabs.io/api/v1/token_security/{chain}?contract_addresses={address}'
    candidates = [e for e in record.get('evidence', []) if isinstance(e, dict)
                  and isinstance(e.get('limitations'), list) and expected in e['limitations']]
    if not candidates:
        return {'status': 'unavailable', 'reason': 'no_provider_capture', 'observations': []}
    # If the latest matching capture is invalid or stale, do not resurrect older hints.
    def order(e):
        try:
            return discovery.stamp(e.get('fetched_at', '')).timestamp()
        except (ValueError, TypeError, OverflowError, AttributeError):
            return float('inf')
    evidence = max(candidates, key=order)
    try:
        data, source = _checked_snapshot(record, root, evidence, now)
    except (ValueError, TypeError, KeyError, OSError, OverflowError, AttributeError, json.JSONDecodeError):
        return {'status': 'unavailable', 'reason': 'capture_stale_or_invalid', 'observations': []}
    rows = []
    for field, (code, description) in _FLAG_HINTS.items():
        if data.get(field) == '1':
            rows.append({'code': code, 'group_hint': 'unverified', 'description': description,
                         'verification': 'provider_reported_unverified', 'gate_votes': 0,
                         'source_name': 'GoPlus Token Security', 'source_evidence': source})
    if data.get('is_open_source') == '0':
        rows.append({'code': 'provider_source_unavailable', 'group_hint': 'unverified',
                     'description': 'Provider reports source code unavailable; this is a verification gap, not a fraud finding.',
                     'verification': 'provider_reported_unverified', 'gate_votes': 0,
                     'source_name': 'GoPlus Token Security', 'source_evidence': source})
    return {'status': 'available', 'reason': 'provider_capture_read', 'observations': rows}


def _scouting_origins(record, root, now):
    """Link new-pool provenance without treating a discovery source as a concern."""
    chain, address = record['identity']['chain_id'], record['identity']['address']
    network = {1: 'eth', 8453: 'base'}[chain]
    expected = f'Request URL: https://api.geckoterminal.com/api/v2/networks/{network}/new_pools?page=1'
    evidence_by_id = {e.get('id'): e for e in record.get('evidence', []) if isinstance(e, dict)}
    for trigger in record.get('triggers', []):
        if not isinstance(trigger, dict) or trigger.get('reason_code') != 'new_pool_lead':
            continue
        for eid in trigger.get('evidence_ids', []):
            e = evidence_by_id.get(eid, {})
            digest, path = e.get('sha256'), e.get('source')
            if (not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
                    or eid != digest or path != 'snapshots/' + digest + '.json'
                    or e.get('kind') != 'live_observation' or not isinstance(e.get('limitations'), list)
                    or expected not in e['limitations']):
                continue
            try:
                fetched = discovery.stamp(e['fetched_at'])
                root = Path(root)
                target = root / path
                if (fetched > now or target.is_symlink() or target.parent.is_symlink()
                        or not target.resolve().is_relative_to(root.resolve()) or target.stat().st_size > 3_000_000):
                    continue
                raw = target.read_bytes()
                if hashlib.sha256(raw).hexdigest() != digest:
                    continue
                document = json.loads(raw)
                rows = document.get('data') if isinstance(document, dict) else None
                if not isinstance(rows, list):
                    continue
                matching = any(isinstance(row, dict) and
                               row.get('relationships', {}).get('base_token', {}).get('data', {}).get('id', '').lower()
                               == network + '_' + address for row in rows)
                if matching:
                    return [{'code': 'new_pool_lead',
                             'description': 'A provider-reported new pool brought this token into scouting; it is not itself a concern.',
                             'verification': 'provider_reported_unverified', 'gate_votes': 0,
                             'source_name': 'GeckoTerminal',
                             'source_evidence': {'id': eid, 'source': path, 'sha256': digest,
                                                 'fetched_at': fetched.isoformat(), 'observed_at': None}}]
            except (ValueError, TypeError, KeyError, OSError, OverflowError, AttributeError, json.JSONDecodeError):
                continue
    return []


def scouting_brief(record, evidence_root, run_id, as_of=None):
    """Build a bounded, server-consumable recommendation from existing local evidence.

    Provider hints can recommend human review but cannot alter deterministic gate
    results. The backend owns sorting, consent, revalidation and job execution.
    """
    now = as_of or dt.datetime.now(dt.timezone.utc)
    if not isinstance(now, dt.datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('timezone-aware assessment time required')
    now = now.astimezone(dt.timezone.utc)
    result = screening_result.screening_result(record, evidence_root, run_id, now)
    provider = _provider_observations(record, evidence_root, now)
    positive_hints = [x for x in provider['observations'] if x['code'] != 'provider_source_unavailable']
    triggered = [group for group in result['groups'] if group['vote'] == 1]
    if result['disposition']['gate_qualified']:
        route = 'auto_eligible'
        why = ['four_distinct_verified_concerns']
    elif triggered or positive_hints:
        route = 'human_review_required'
        why = (['verified_concern_below_auto_gate'] if triggered else []) + (['unverified_provider_concern'] if positive_hints else [])
    else:
        route = 'monitor'
        why = ['no_current_verified_or_provider_reported_concern']
        if provider['status'] != 'available':
            why.append('provider_check_unavailable')
    origin = _scouting_origins(record, evidence_root, now)
    return {'profile': PROFILE, 'policy': POLICY, 'candidate': result['candidate'],
            'generated_at': result['generated_at'], 'run_id': result['run_id'],
            'screening_snapshot_id': result['snapshot_id'], 'scouting_origins': origin,
            'provider_observations': provider, 'deterministic_checks': result['groups'],
            'coverage': result['coverage'], 'routing': {'recommendation': route, 'reason_codes': why,
                'note': 'Recommendation only; backend revalidates policy, evidence and authorization before research.'},
            'limitations': ['Provider observations are unverified leads and cannot cast gate votes.',
                            'Actionability is not a scam probability or report approval.',
                            'Only two narrow Ethereum concern verifiers are currently enabled.']}
