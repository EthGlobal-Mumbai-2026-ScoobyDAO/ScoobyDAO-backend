"""/web/v1: read model shaped like ScoobyDAO-web/src/lib/types.ts (Report, Approval).

Point the web app's NEXT_PUBLIC_API_URL at http://<host>/web/v1. Only health, reports,
report approval requests and approvals live here; /claims, /deployments and /demo/scan
belong to other workstreams (see docs/publication-decisions.md).

Responses never include device codes, tokens or key material.
"""
from __future__ import annotations
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from store import db, digest
from . import service
from .deps import get_chain_cfg, get_gate, get_settings, get_world, get_world_optional

log = logging.getLogger('publication.web')
router = APIRouter(prefix='/web/v1', tags=['web'])


def _split(web_id: str) -> tuple[str, str]:
    if '@' not in web_id:
        raise HTTPException(404, 'report id must be report_id@version')
    rid, ver = web_id.rsplit('@', 1)
    return rid, ver


def _latest_target(c, report_id: str, version: str):
    return c.execute('SELECT * FROM pub_targets WHERE report_id=? AND report_version=? ORDER BY created DESC LIMIT 1',
                     (report_id, version)).fetchone()


def _web_report(c, t) -> dict:
    manifest = json.loads(t['claim_manifest_json'])
    st = service._status(c, t)
    attempt = st['latest_attempt']
    receipt = st['latest_receipt']
    outbox = st['outbox']
    if st['published_onchain']:
        status = 'published'
    elif receipt and receipt['decision'] in ('reject', 'revise') and (not attempt or attempt['status'] != 'pending'):
        status = 'denied'
    elif not attempt:
        status = 'draft'
    else:
        status = {'pending': 'awaiting_approval', 'denied': 'denied', 'rejected_not_reviewer': 'denied',
                  'expired': 'expired', 'cancelled': 'expired', 'error': 'expired',
                  'approved': 'awaiting_approval'}[attempt['status']]
    out = {
        'id': f"{t['report_id']}@{t['report_version']}",
        'token': manifest['token'],
        'chainId': manifest['chainId'],
        'status': status,
        'manifest': manifest,
        'manifestHash': '0x' + t['claim_hash'],
        'createdAt': int(t['created']),
        'reportSha256': t['report_sha256'],
        'targetDigest': t['target_digest'],
        'publicationState': st['state'],
        'revoked': st['revoked'],
    }
    if attempt:
        out['approvalId'] = attempt['id']
    if outbox and outbox['state'] == 'confirmed':
        out['txHash'] = outbox['tx_hash']
        if outbox['onchain_report_id']:
            out['claimId'] = outbox['onchain_report_id']
            out['onchainReportId'] = outbox['onchain_report_id']
    return out


def _web_approval(c, a: dict) -> dict:
    t = c.execute('SELECT * FROM pub_targets WHERE id=?', (a['target_id'],)).fetchone()
    receipt = c.execute('SELECT * FROM pub_receipts WHERE attempt_id=?', (a['id'],)).fetchone()
    outbox = c.execute('SELECT * FROM pub_outbox WHERE receipt_id=?', (receipt['id'],)).fetchone() if receipt else None
    if receipt and receipt['decision'] != 'approve':
        status = 'denied'
    elif outbox and outbox['state'] == 'confirmed':
        status = 'spent'
    elif receipt:
        status = 'approved'
    else:
        status = {'pending': 'pending', 'denied': 'denied', 'rejected_not_reviewer': 'rejected_not_reviewer',
                  'expired': 'expired', 'cancelled': 'expired', 'error': 'expired', 'approved': 'approved'}[a['status']]
    out = {
        'id': a['id'],
        'reportId': f"{t['report_id']}@{t['report_version']}",
        'manifestHash': '0x' + t['claim_hash'],
        'status': status,
        'expiresAt': int(a['expires_at']),
    }
    if a['status'] == 'pending':
        out['userCode'] = a['user_code']
        out['verificationUri'] = a['verification_uri_complete'] or a['verification_uri']
    if outbox and outbox['tx_hash'] and outbox['state'] in ('submitted', 'confirmed'):
        out['publishTxHash'] = outbox['tx_hash']
    if outbox and outbox['onchain_report_id']:
        out['onchainReportId'] = outbox['onchain_report_id']
    if a['status'] == 'error':
        out['detail'] = 'Sign-off could not be verified; nothing was approved.'
    return out


@router.get('/health')
def health():
    return {'ok': True}


@router.get('/reports')
def reports():
    with db() as c:
        rows = c.execute('''SELECT t.* FROM pub_targets t
                            WHERE t.created = (SELECT max(created) FROM pub_targets u
                                               WHERE u.report_id=t.report_id AND u.report_version=t.report_version)
                            ORDER BY t.created DESC''').fetchall()
        return [_web_report(c, t) for t in rows]


@router.get('/reports/{web_id}')
def report(web_id: str):
    rid, ver = _split(web_id)
    with db() as c:
        t = _latest_target(c, rid, ver)
        if not t:
            raise HTTPException(404, 'no publication target prepared for this report version')
        return _web_report(c, t)


@router.get('/reports/{web_id}/raw')
def report_raw(web_id: str):
    """Exact report.json bytes so the browser can recompute SHA-256."""
    rid, ver = _split(web_id)
    with db() as c:
        rep = c.execute('SELECT * FROM reports WHERE id=? AND version=?', (rid, ver)).fetchone()
    if not rep:
        raise HTTPException(404, 'report not found')
    from pathlib import Path
    raw = (Path(rep['path']) / 'report.json').read_bytes()
    if digest(raw) != rep['sha256']:
        raise HTTPException(409, 'report bytes changed on disk')
    return Response(raw, media_type='application/json', headers={'X-Content-SHA256': rep['sha256']})


@router.post('/reports/{web_id}/approve')
def request_approval(web_id: str, world=Depends(get_world)):
    rid, ver = _split(web_id)
    with db() as c:
        t = _latest_target(c, rid, ver)
        if not t:
            raise HTTPException(409, 'no publication target prepared; an operator must create one first')
        service._expire_stale(c, target_id=t['id'])
        pending = c.execute("SELECT * FROM pub_attempts WHERE target_id=? AND status='pending' ORDER BY created DESC LIMIT 1",
                            (t['id'],)).fetchone()
        if pending:
            return _web_approval(c, dict(pending))
    try:
        a = service.create_attempt(t['id'], 'approve', 'Requested from the web sign-off page',
                                   idem=f'web:{t["id"]}:{uuid.uuid4().hex}', actor='web', world=world)
    except service.PubError as e:
        raise HTTPException(e.status, str(e)) from None
    with db() as c:
        return _web_approval(c, a)


@router.get('/approvals/{attempt_id}')
def approval(attempt_id: str, world=Depends(get_world_optional), settings=Depends(get_settings),
             chain_cfg=Depends(get_chain_cfg), gate=Depends(get_gate)):
    try:
        a = service.poll_attempt(attempt_id, world)
    except service.PubError as e:
        raise HTTPException(e.status, str(e)) from None
    if chain_cfg.demo_autopublish and chain_cfg.enabled:
        _demo_autopublish(a, gate, settings, chain_cfg)
    with db() as c:
        return _web_approval(c, a)


def _demo_autopublish(a: dict, gate, settings, chain_cfg) -> None:
    """Stage-demo convenience (SCOOBY_DEMO_AUTOPUBLISH=true, default false): one explicit publish
    request per approve receipt. Idempotent on the receipt id; all request_publication checks apply."""
    with db() as c:
        receipt = c.execute("SELECT * FROM pub_receipts WHERE attempt_id=? AND decision='approve'", (a['id'],)).fetchone()
    if not receipt:
        return
    try:
        service.request_publication(a['target_id'], idem=f"demo-autopublish:{receipt['id']}", actor='demo-autopublish',
                                    gate=gate, settings=settings, chain_cfg=chain_cfg)
    except service.PubError as e:
        log.info('demo autopublish skipped: %s', e)
