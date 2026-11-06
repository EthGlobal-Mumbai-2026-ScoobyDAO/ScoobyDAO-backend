"""Provisional, read-only discovery screening sidecar; no job dispatch or selection."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import discovery
import lp_concentration
import market_activity
import review_queue

SCHEMA = 'scooby.discovery-screening/1-proposal'
POLICY = 'pilot-attention-v1'
MAX_AGE_SECONDS = 3600
# This policy is deliberately pinned to these two reviewed verifier functions.
# Enabling another group requires independent review and a new policy version.
_VERIFIERS = {'G07': lp_concentration.verify, 'G09': market_activity.verify}
_SCOPE = {
    'G07': 'Sampled LP addresses for one Ethereum Uniswap V2/WETH pool; not beneficial ownership or all pools.',
    'G09': 'Price movement for one Ethereum Uniswap V2/WETH pool; volume and global price are not evaluated.',
}
_FORMAT = {'G07': ('G07_V2_LP_V1', 'point'), 'G09': ('G09_V2_WETH_V1', 'latest')}


def _provenance(group_id, reference, record, root, as_of):
    """Recheck reference integrity and expose only bounded, non-secret provenance."""
    matches = [e for e in record['evidence'] if isinstance(e, dict) and e.get('id') == reference['id']]
    if len(matches) != 1:
        raise ValueError('evidence reference is ambiguous')
    e = matches[0]
    fetched = discovery.stamp(e['fetched_at'])
    observed = discovery.stamp(e['observed_at'])
    if not (0 <= (as_of - fetched).total_seconds() <= MAX_AGE_SECONDS and
            0 <= (as_of - observed).total_seconds() <= MAX_AGE_SECONDS and fetched >= observed):
        raise ValueError('evidence is stale or has inconsistent timestamps')
    block_number = e['block_number']
    if isinstance(block_number, bool) or not isinstance(block_number, int) or block_number < 0:
        raise ValueError('block number unavailable')
    path = Path(root) / reference['source']
    if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('unsafe evidence path')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference['sha256']:
        raise ValueError('evidence changed after verification')
    document = json.loads(raw)
    expected_format, point_name = _FORMAT[group_id]
    point = document[point_name]
    if (document.get('format') != expected_format or document.get('candidate_id') != record['candidate_id']
            or document.get('chain_id') != record['identity']['chain_id']
            or point.get('finality') != 'finalized'
            or not isinstance(point.get('block_hash'), str)
            or not re.fullmatch(r'0x[0-9a-fA-F]{64}', point['block_hash'])
            or market_activity.integer(point['block_tag']) != block_number
            or point['block_timestamp'] != int(observed.timestamp())):
        raise ValueError('candidate or block provenance mismatch')
    return {'id': e['id'], 'sha256': e['sha256'], 'source': reference['source'],
            'observed_at': observed.isoformat(), 'fetched_at': fetched.isoformat(),
            'block_number': block_number, 'block_hash': point['block_hash'].lower(),
            'finality': 'finalized', 'scope': _SCOPE[group_id]}


def _deduplicate(groups):
    """A shared evidence artifact cannot count independently for multiple groups."""
    owners = {}
    for group in groups:
        if group['vote']:
            for evidence in group['evidence']:
                owners.setdefault(evidence['id'], set()).add(group['id'])
    correlated = set().union(*(ids for ids in owners.values() if len(ids) > 1)) if owners else set()
    for group in groups:
        if group['id'] in correlated:
            group.update(status='unknown', vote=0,
                         detail='Evidence overlaps another triggered group; independent votes not established.')


def screening_result(record, root, run_id, as_of=None):
    """Build a deterministic point-in-time sidecar from live records and pinned verifiers.

    run_id is a caller-provided correlation ID, not proof that a run was executed. The
    backend must associate it with its durable run and re-evaluate before dispatch.
    """
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', run_id):
        raise ValueError('a safe run correlation ID is required')
    as_of = as_of or dt.datetime.now(dt.timezone.utc)
    if not isinstance(as_of, dt.datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('timezone-aware assessment time required')
    as_of = as_of.astimezone(dt.timezone.utc)
    root = Path(root)
    assessed = review_queue.assess(record, root, as_of, verifiers=_VERIFIERS, max_age_seconds=MAX_AGE_SECONDS)
    identity = record['identity']
    if type(identity['chain_id']) is not int or identity['chain_id'] not in (1, 8453):
        raise ValueError('supported numeric chain ID required')
    if identity['address'] != identity['address'].lower():
        raise ValueError('canonical lowercase candidate address required')
    groups = []
    for row in assessed['groups']:
        group = {'id': row['id'], 'name': row['name'], 'status': row['status'],
                 'vote': row['votes'], 'detail': row['detail'],
                 'measurements': row['measurements'], 'evidence': []}
        if row['evidence']:
            try:
                group['evidence'] = [_provenance(row['id'], e, record, root, as_of) for e in row['evidence']]
            except (ValueError, TypeError, KeyError, OSError, OverflowError, json.JSONDecodeError):
                group.update(status='unknown', vote=0, detail='Evidence provenance or freshness unavailable.',
                             measurements=[], evidence=[])
        elif row['status'] == 'unknown' and row['id'] in _VERIFIERS:
            # Do not leak provider exceptions or local paths through an API response.
            group['detail'] = 'Verification unavailable or incomplete.'
        groups.append(group)
    _deduplicate(groups)
    count = sum(g['vote'] for g in groups)
    evaluated = sum(g['status'] in ('triggered', 'not_triggered') for g in groups)
    lane = 'auto_eligible' if count >= 4 else 'human_review_required' if count else 'monitor'
    reasons = ([{'code': 'verified_concern', 'group_id': g['id']} for g in groups if g['vote']]
               or [{'code': 'no_verified_concerns'}])
    symbol = identity.get('symbol')
    if not isinstance(symbol, str):
        symbol = None
    result = {
        'schema_version': SCHEMA,
        'policy': {'id': POLICY, 'gate_concerns': 4, 'higher_priority_concerns': 5,
                   'max_evidence_age_seconds': MAX_AGE_SECONDS, 'enabled_groups': sorted(_VERIFIERS)},
        'run_id': run_id, 'generated_at': as_of.isoformat(),
        'candidate': {'candidate_id': record['candidate_id'], 'chain_id': identity['chain_id'],
                      'address': identity['address'], 'symbol': symbol},
        'groups': groups,
        'coverage': {'triggered_groups': count, 'evaluated_groups': evaluated,
                     'unknown_or_held_groups': len(groups) - evaluated,
                     'limitations': ['Only two narrow concern verifiers are enabled; provider hints do not vote.',
                                     'Evidence is a point-in-time provider capture, not a consensus proof.']},
        'disposition': {'lane': lane, 'gate_qualified': count >= 4,
                        'reason': 'Automatic research requires dispatch-time revalidation.' if count >= 4
                        else 'Diagnostic research requires human authorization.' if count
                        else 'No verified concern currently supports escalation.'},
        'urgency': {'verified_concern_count': count, 'reasons': reasons,
                    'note': 'Attention ordering only; not a probability or fraud verdict.'},
    }
    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    result['snapshot_id'] = hashlib.sha256(canonical).hexdigest()
    return result
