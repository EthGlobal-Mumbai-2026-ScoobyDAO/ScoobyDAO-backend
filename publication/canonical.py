"""Builders and digests for the service-owned records:

- `scooby.claim-manifest/1`: the human-readable claim the reviewer approves. It is a superset
  of the web `Manifest` type (ScoobyDAO-web/src/lib/types.ts) so the /web/v1 adapter can
  return it unchanged.
- `scooby.publication-target/1`: everything the onchain `publish` call commits to.

Canonical bytes are `store.dumps` (sorted keys, no whitespace, ensure_ascii=False, no NaN)
encoded as UTF-8. Records contain integers and strings only; floats are rejected.
"""
from __future__ import annotations
import hashlib
from typing import Any
from store import PILLARS, dumps

CLAIM_MANIFEST_SCHEMA = 'scooby.claim-manifest/1'
TARGET_SCHEMA = 'scooby.publication-target/1'
POLICY_VERSION = 'scooby.review-policy/1'
NOT_STATED = 'not stated'
THIRTY_DAYS = 30 * 24 * 3600
UINT64_MAX = 2**64 - 1
ZERO_ADDR = '0x' + '0' * 40


class TargetError(ValueError):
    """Target parameters violate a contract rule; maps to HTTP 422."""


def canonical(record: Any) -> bytes:
    _reject_floats(record)
    return dumps(record).encode('utf-8')


def _reject_floats(x: Any) -> None:
    if isinstance(x, float):
        raise TargetError('canonical records must not contain floats')
    if isinstance(x, dict):
        for v in x.values():
            _reject_floats(v)
    elif isinstance(x, list):
        for v in x:
            _reject_floats(v)


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def keccak_hex(b: bytes) -> str:
    from eth_utils import keccak
    return keccak(b).hex().removeprefix('0x')


def claim_hash(manifest: dict, alg: str = 'sha256') -> str:
    """Hex digest (no 0x) of the canonical claim manifest. alg is configurable, see decisions doc."""
    b = canonical(manifest)
    return keccak_hex(b) if alg == 'keccak256' else sha256_hex(b)


def target_digest(target: dict) -> str:
    return sha256_hex(canonical(target))


def bytes32(hex_digest: str) -> str:
    h = hex_digest.lower().removeprefix('0x')
    if len(h) != 64 or any(ch not in '0123456789abcdef' for ch in h):
        raise TargetError('expected a 32-byte hex digest')
    return '0x' + h


def _address(value: Any, name: str) -> str:
    from eth_utils import is_address, to_checksum_address
    if not isinstance(value, str) or not is_address(value):
        raise TargetError(f'{name} must be an address')
    a = to_checksum_address(value)
    if a.lower() == ZERO_ADDR:
        raise TargetError(f'{name} must be non-zero')
    return a


def _uint64(params: dict, name: str) -> int:
    v = params.get(name)
    if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > UINT64_MAX:
        raise TargetError(f'{name} must be a uint64 integer')
    return v


def build_claim_manifest(report: dict, report_sha256: str, created_at: int, lock_time: int,
                         excluded_wallets: list[str]) -> dict:
    """Summarises the report for the reviewer. Uses only v0.2 fields; missing text is 'not stated'.
    It invents no findings: claims are the report's own pillar claim statements."""
    identity = report.get('identity') or {}
    assessment = report.get('assessment') or {}
    symbol = identity.get('symbol') or NOT_STATED
    chain_id = identity.get('chain_id')
    address = identity.get('address') or NOT_STATED
    claims: list[dict] = []
    for pillar in PILLARS:
        for c in (report.get('pillars') or {}).get(pillar, {}).get('claims') or []:
            claims.append({'id': len(claims), 'type': 'REPORT_CLAIM', 'params': {
                'statement': c.get('statement') or NOT_STATED,
                'kind': c.get('kind') or NOT_STATED,
                'pillar': pillar,
                'reportClaimId': c.get('id') or NOT_STATED,
            }})
    evidence = []
    for e in report.get('evidence') or []:
        evidence.append({
            'kind': e.get('kind') or NOT_STATED,
            'result': e.get('coverage') or NOT_STATED,
            'detail': f"{e.get('id') or NOT_STATED} sha256:{e.get('sha256') or NOT_STATED}",
        })
    label = assessment.get('label')
    summary = assessment.get('summary') or NOT_STATED
    return {
        'schema': CLAIM_MANIFEST_SCHEMA,
        'version': 1,
        'title': f"{symbol} on chain {chain_id if chain_id is not None else NOT_STATED}: {report.get('report_id', NOT_STATED)}@{report.get('report_version', NOT_STATED)}",
        'chainId': chain_id if isinstance(chain_id, int) else 0,
        'token': address,
        'symbol': symbol,
        'claimText': f"{label if label else NOT_STATED}. {summary}",
        'assessmentStatus': assessment.get('status') or NOT_STATED,
        'claims': claims,
        'evidence': evidence,
        'summary': summary,
        'excludedWallets': sorted({w.lower() for w in excluded_wallets}),
        'windowSeconds': max(0, lock_time - created_at),
        'createdAt': created_at,
        'reportId': report.get('report_id') or NOT_STATED,
        'reportVersion': report.get('report_version') or NOT_STATED,
        'reportSha256': report_sha256,
    }


def build_target(*, report_id: str, report_version: str, report_sha256: str, claim_hash_hex: str,
                 claim_hash_alg: str, chain_id: int, registry: str, params: dict, now: float,
                 lock_margin: int) -> dict:
    """Validates ReportRegistry.publish timing/authority rules up front (422 on violation)."""
    resolver = _address(params.get('resolver'), 'resolver')
    adjudicator = _address(params.get('adjudicator'), 'adjudicator')
    lock_time = _uint64(params, 'lock_time')
    cutoff = _uint64(params, 'cross_chain_cutoff')
    deadline = _uint64(params, 'result_deadline')
    challenge = _uint64(params, 'challenge_period')
    if not cutoff < lock_time:
        raise TargetError('cross_chain_cutoff must be before lock_time')
    if not lock_time > int(now) + lock_margin:
        raise TargetError(f'lock_time must be more than {lock_margin}s in the future')
    if not deadline > lock_time + THIRTY_DAYS:
        raise TargetError('result_deadline must be more than 30 days after lock_time')
    if not challenge > 0:
        raise TargetError('challenge_period must be positive')
    return {
        'schema': TARGET_SCHEMA,
        'reportId': report_id,
        'reportVersion': report_version,
        'reportSha256': report_sha256,
        'claimHash': claim_hash_hex,
        'claimHashAlg': claim_hash_alg,
        'chainId': chain_id,
        'registry': _address(registry, 'registry'),
        'resolver': resolver,
        'adjudicator': adjudicator,
        'lockTime': lock_time,
        'crossChainCutoff': cutoff,
        'resultDeadline': deadline,
        'challengePeriod': challenge,
        'policyVersion': POLICY_VERSION,
    }
