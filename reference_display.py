"""Read side of `scooby.reference-display/1` (docs/reference-display-contract.md).

Public case items get identifiers and labels only. The admin routes, under /web/v1/admin/ so AdminWebCORS and the
admin route guard apply, need a real World ID `report_review` session (per-report sessions accepted) and serve
the report metadata and the exact, re-hashed bundle files that report.json names. Nothing here writes.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response

from store import db, digest

SCHEMA = 'scooby.reference-display/1'
LABEL = 'Historical reference — unreviewed'
LABELS = ['historical', 'unreviewed', 'synthetic_lineage', 'uncalibrated_var', 'snapshot_expired']
SHA = re.compile('[0-9a-f]{64}')
MEDIA = {'.json': 'application/json', '.csv': 'text/csv; charset=utf-8', '.md': 'text/plain; charset=utf-8'}
MAX_FILE = 20_000_000
router = APIRouter(prefix='/web/v1/admin', tags=['admin'])

LINKS = ('SELECT l.case_id,l.report_id,l.version,r.sha256,r.path,r.run_id,i.candidate_id FROM case_reference_reports l '
         'JOIN reports r ON r.id=l.report_id AND r.version=l.version JOIN investigations i ON i.id=r.run_id '
         "JOIN cases k ON k.id=l.case_id WHERE i.status='reference_only' AND k.candidate_id=i.candidate_id")


def _has_link_table(c) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='case_reference_reports'").fetchone() is not None


def case_links(c, case_id: str) -> list:
    if not _has_link_table(c):
        return []
    return c.execute(LINKS + ' AND l.case_id=? ORDER BY r.created DESC, l.report_id, l.version', (case_id,)).fetchall()


def is_reference_case(c, case_id: str) -> bool:
    return bool(case_links(c, case_id))


def is_reference_report(c, report_id: str, version: str) -> bool:
    return _has_link_table(c) and c.execute(
        'SELECT 1 FROM case_reference_reports WHERE report_id=? AND version=?', (report_id, version)).fetchone() is not None


def review_state(c, report_id: str, version: str) -> tuple[str, bool]:
    """From the real review tables: (state, world_verified). A future genuine approval shows here."""
    from publication import review
    try:
        status = review.public_status(c, report_id, version)
    except Exception:  # missing publication tables or unreadable bytes: never claim a review state
        return 'unavailable', False
    state = status['state']
    return state, state == 'approved' and status['method'] == 'world_id_admin_signoff'


def _public_report(c, link) -> dict:
    state, world = review_state(c, link['report_id'], link['version'])
    return {'report_id': link['report_id'], 'report_version': link['version'], 'report_sha256': link['sha256'],
            'association': 'historical_reference', 'review_state': state, 'world_verified': world, 'gate_effect': 'none'}


def case_reference(c, case_id: str) -> dict | None:
    links = case_links(c, case_id)
    if not links:
        return None
    return {'kind': 'historical_reference', 'label': LABEL, 'reports': [_public_report(c, x) for x in links]}


# ---------------------------------------------------------------------------- admin read model
def _link(c, report_id: str, version: str):
    if not _has_link_table(c):
        return None
    return c.execute(LINKS + ' AND l.report_id=? AND l.version=?', (report_id, version)).fetchone()


def _integrity(detail: str = 'integrity unavailable'):
    raise HTTPException(409, detail)


def _report_doc(link) -> dict:
    path = Path(link['path']) / 'report.json'
    try:
        if path.is_symlink() or not path.is_file():
            _integrity()
        raw = path.read_bytes()
    except OSError:
        _integrity()
    if digest(raw) != link['sha256']:
        _integrity()
    try:
        doc = json.loads(raw)
    except ValueError:
        _integrity()
    if not isinstance(doc, dict) or (doc.get('report_id'), doc.get('report_version'), doc.get('candidate_id')) != (
            link['report_id'], link['version'], link['candidate_id']):
        _integrity()
    return doc


def file_map(link, doc: dict) -> dict:
    """Exactly report.json plus every evidence[]/artifacts[] entry carrying a path."""
    files = {'report.json': link['sha256']}
    for item in (doc.get('evidence') or []) + (doc.get('artifacts') or []):
        if not isinstance(item, dict):
            _integrity()
        path, value = item.get('path'), item.get('sha256')
        if path is None:
            if item.get('availability') == 'unavailable':
                continue
            _integrity()
        if (not isinstance(path, str) or not isinstance(value, str) or not SHA.fullmatch(value) or path == 'report.json'
                or '\\' in path or path.startswith('/') or any(p in ('', '.', '..') for p in path.split('/'))):
            _integrity()
        if files.get(path, value) != value:
            _integrity()
        files[path] = value
    return files


def metadata(c, link, full_verify: bool = True) -> dict:
    from modules.investigation.contract_validate import verify_digest
    doc = _report_doc(link)
    if full_verify:
        try:
            verify_digest(Path(link['path']), link['sha256'])
        except (OSError, ValueError, KeyError, TypeError):
            _integrity()
    files = file_map(link, doc)
    diag = c.execute('SELECT description FROM diagnostic_imports WHERE run_id=?', (link['run_id'],)).fetchone()
    state, world = review_state(c, link['report_id'], link['version'])
    identity = doc.get('identity') or {}
    return {'schema': SCHEMA, 'report_id': link['report_id'], 'report_version': link['version'], 'report_sha256': link['sha256'],
            'case_id': link['case_id'], 'candidate_id': link['candidate_id'], 'symbol': identity.get('symbol'),
            'identity': {'chain_id': identity.get('chain_id'), 'address': identity.get('address'), 'symbol': identity.get('symbol')},
            'mode': doc.get('mode'), 'review_state': state, 'world_verified': world, 'gate_effect': 'none',
            'association': 'historical_reference', 'labels': list(LABELS), 'description': diag['description'] if diag else None,
            'pillars': {name: {'status': p.get('status'), 'quality_issues': p.get('quality_issues', [])}
                        for name, p in (doc.get('pillars') or {}).items() if isinstance(p, dict)},
            'files': files,
            'file_base': f'/web/v1/admin/reference-reports/{quote(link["report_id"], safe="")}/{quote(link["version"], safe="")}/files/'}


def _require():
    from publication.deps import require_admin
    return require_admin('report_review')


@router.get('/reference-reports/{report_id}/{version}')
def reference_report(report_id: str, version: str, principal=Depends(_require())):
    with db() as c:
        link = _link(c, report_id, version)
        if not link:
            raise HTTPException(404, 'Not a linked reference report')
        return metadata(c, link)


@router.get('/reference-reports/{report_id}/{version}/files/{path:path}')
def reference_file(report_id: str, version: str, path: str, principal=Depends(_require())):
    with db() as c:
        link = _link(c, report_id, version)
        if not link:
            raise HTTPException(404, 'Not a linked reference report')
        doc = _report_doc(link)
        expected = file_map(link, doc).get(path)
    if expected is None:
        raise HTTPException(404, 'File not in this report')
    base = Path(link['path'])
    target = base
    for part in path.split('/'):
        target = target / part
        if target.is_symlink():
            _integrity()
    try:
        if not target.resolve().is_relative_to(base.resolve()) or not target.is_file() or target.stat().st_size > MAX_FILE:
            _integrity()
        content = target.read_bytes()
    except OSError:
        _integrity()
    if digest(content) != expected:
        _integrity()
    suffix = Path(path).suffix.lower()
    headers = {'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
               'Content-Security-Policy': "default-src 'none'; sandbox", 'X-Report-SHA256': link['sha256'], 'X-File-SHA256': expected}
    if suffix not in MEDIA:
        headers['Content-Disposition'] = 'attachment'
    return Response(content=content, media_type=MEDIA.get(suffix, 'application/octet-stream'), headers=headers)


def _case_principal(case_id: str, request: Request, authorization: str | None = Header(None)):
    """report_review session for the case route. A per-report session is accepted only when its report is linked
    to this case (and then sees only that report); with SCOOBY_REVIEW_PER_REPORT=true a general session is refused."""
    from publication.admin import bearer, principal_for_token, report_resource
    from publication.config import review_per_report
    principal = principal_for_token(bearer(authorization))
    if principal is None:
        raise HTTPException(401, 'admin session required', headers={'WWW-Authenticate': 'Bearer'})
    if 'report_review' not in principal.scopes:
        raise HTTPException(403, 'admin scope report_review required')
    with db() as c:
        links = case_links(c, case_id)
    if not links:
        raise HTTPException(404, 'Not a reference case')
    if principal.resource is not None:
        links = [x for x in links if report_resource(x['report_id'], x['version']) == principal.resource]
        if not links:
            raise HTTPException(403, 'this session is limited to another report; use Read on this report')
    elif review_per_report():
        raise HTTPException(403, 'reading a report needs its own World ID confirmation; use Read on this report')
    return links


@router.get('/cases/{case_id}/reference-reports')
def case_reference_reports(case_id: str, links=Depends(_case_principal)):
    with db() as c:
        reports = [metadata(c, x) for x in links]
        case = c.execute('SELECT candidate_id FROM cases WHERE id=?', (case_id,)).fetchone()
    return {'case_id': case_id, 'candidate_id': case['candidate_id'], 'association': 'historical_reference', 'gate_effect': 'none',
            'reports': reports}
