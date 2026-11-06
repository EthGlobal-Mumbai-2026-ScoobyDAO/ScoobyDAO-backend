"""Reviewers (subject-matter experts) and their admin scopes from the SCOOBY_REVIEWERS environment variable.

A host without a persistent disk (for example Render's free plan) loses its database on every restart, so the
reviewer allowlist is reapplied from configuration at startup:

    SCOOBY_REVIEWERS='[{"label": "alice", "iss": "https://auth.world.org", "sub": "<pairwise sub>",
                        "scopes": ["report_review"], "enabled": true}]'

`python -m publication.cli export-reviewer --name alice` prints an entry for an enrolled reviewer. The `sub` is
learned only from a real World login (`enroll`); this module never invents one.

For every listed (iss, sub) the entry is authoritative: the reviewer row is upserted, the listed scopes are granted
and any other scope is withdrawn. Reviewers that are not listed are left as they are. Being listed never approves
anything: every checkpoint still needs a fresh World confirmation. Invalid configuration loads nobody and is logged.
"""
from __future__ import annotations
import json
import logging
import os

from store import db, now
from . import admin
from .db import audit

log = logging.getLogger('publication.reviewers')
ENV = 'SCOOBY_REVIEWERS'
MAX_ENTRIES = 100


class ReviewerConfigError(ValueError):
    """SCOOBY_REVIEWERS is malformed. The message never contains a subject."""


def parse(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except ValueError:
        raise ReviewerConfigError(f'{ENV} is not valid JSON') from None
    if not isinstance(data, list) or len(data) > MAX_ENTRIES:
        raise ReviewerConfigError(f'{ENV} must be a JSON list of at most {MAX_ENTRIES} reviewers')
    out, seen = [], set()
    for i, e in enumerate(data):
        if not isinstance(e, dict) or set(e) - {'label', 'iss', 'sub', 'scopes', 'enabled'}:
            raise ReviewerConfigError(f'{ENV}[{i}] must be an object with label, iss, sub, scopes and optional enabled')
        label, iss, sub, scopes = e.get('label'), e.get('iss'), e.get('sub'), e.get('scopes', [])
        enabled = e.get('enabled', True)
        if not isinstance(label, str) or not 1 <= len(label) <= 100:
            raise ReviewerConfigError(f'{ENV}[{i}].label must be 1-100 characters')
        if not isinstance(iss, str) or not iss.startswith('https://') or len(iss) > 200:
            raise ReviewerConfigError(f'{ENV}[{i}].iss must be an https issuer URL')
        if not isinstance(sub, str) or not 1 <= len(sub) <= 256:
            raise ReviewerConfigError(f'{ENV}[{i}].sub must be 1-256 characters')
        if not isinstance(scopes, list) or not all(isinstance(s, str) and s in admin.SCOPES for s in scopes):
            raise ReviewerConfigError(f'{ENV}[{i}].scopes must be a list drawn from {", ".join(admin.SCOPES)}')
        if not isinstance(enabled, bool):
            raise ReviewerConfigError(f'{ENV}[{i}].enabled must be true or false')
        if (iss, sub) in seen:
            raise ReviewerConfigError(f'{ENV}[{i}] repeats a reviewer')
        seen.add((iss, sub))
        out.append({'label': label, 'iss': iss, 'sub': sub, 'scopes': sorted(set(scopes)), 'enabled': enabled})
    return out


def apply(entries: list[dict], actor: str = 'env') -> int:
    with db() as c:
        for e in entries:
            c.execute('INSERT INTO pub_reviewers(iss,sub,label,enabled,created) VALUES(?,?,?,?,?) '
                      'ON CONFLICT(iss,sub) DO UPDATE SET label=excluded.label, enabled=excluded.enabled',
                      (e['iss'], e['sub'], e['label'], 1 if e['enabled'] else 0, now()))
            held = {r['scope'] for r in c.execute(
                'SELECT scope FROM admin_scopes WHERE iss=? AND sub=? AND revoked_at IS NULL', (e['iss'], e['sub']))}
            for scope in sorted(set(e['scopes']) - held):
                admin.grant(c, e['iss'], e['sub'], scope, actor)
            for scope in sorted(held - set(e['scopes'])):
                admin.revoke_scope(c, e['iss'], e['sub'], scope, actor)
            audit(c, None, 'reviewer_configured', actor, {'label': e['label'], 'iss': e['iss'],
                  'subject_sha256': admin.subject_hash(e['iss'], e['sub']), 'scopes': e['scopes'], 'enabled': e['enabled']})
    return len(entries)


def load_from_env() -> int:
    """Apply SCOOBY_REVIEWERS if set. Returns the number of reviewers applied (0 when unset or invalid)."""
    raw = os.getenv(ENV, '').strip()
    if not raw:
        return 0
    try:
        n = apply(parse(raw))
    except ReviewerConfigError as e:
        log.error('reviewers not loaded: %s', e)
        return 0
    log.info('reviewers loaded from %s: %d', ENV, n)
    return n


def export(label: str) -> list[dict]:
    """SCOOBY_REVIEWERS entries for enrolled reviewers with this label, with their current scopes."""
    with db() as c:
        rows = c.execute('SELECT iss, sub, label, enabled FROM pub_reviewers WHERE label=? ORDER BY created', (label,)).fetchall()
        return [{'label': r['label'], 'iss': r['iss'], 'sub': r['sub'],
                 'scopes': sorted(admin.scopes_of(c, r['iss'], r['sub'])) if r['enabled'] else [],
                 'enabled': bool(r['enabled'])} for r in rows]
