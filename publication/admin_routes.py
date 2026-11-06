"""/web/v1/admin: the admin API for the two World ID checkpoints (docs/admin-world-checkpoints.md).

Consumers never need these routes. Everything except starting a login needs `Authorization: Bearer
<admin session token>`, and checkpoint routes also need the matching scope. The path prefix is an
organizational choice; authorization is checked on the server for every request. Responses never carry
World tokens, device codes, private keys or reviewer subjects.
"""
from __future__ import annotations
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from store import db
from . import admin, review, service
from .deps import get_admin_cfg, get_world, get_world_optional, idem_key, require_admin

router = APIRouter(prefix='/web/v1/admin', tags=['admin'])
public_router = APIRouter(prefix='/web/v1', tags=['admin'])


def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except service.PubError as e:
        headers = {'WWW-Authenticate': 'Bearer'} if e.status == 401 else None
        raise HTTPException(e.status, str(e), headers=headers) from None


class DecisionIn(BaseModel):
    decision: Literal['approve', 'reject', 'revise']
    reason: str = Field(min_length=1, max_length=1000)
    expected_target_digest: str = Field(pattern=r'^[0-9a-f]{64}$')


class ReviewRevokeIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


# ---------------------------------------------------------------------------- session
class SessionIn(BaseModel):
    report_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=200)


@router.post('/session')
def start_session(x: SessionIn | None = None, cfg=Depends(get_admin_cfg), world=Depends(get_world)):
    """Start a World login. The response carries the session token once; it stays inactive until an
    enabled reviewer holding at least one scope completes the login. With {report_id, version} in the body the
    session is limited to that report version (the review desk "Read" button)."""
    return _call(admin.start_session, world, cfg, (x.report_id, x.version) if x else None)


@router.get('/session')
def session_status(authorization: str | None = Header(None), cfg=Depends(get_admin_cfg), world=Depends(get_world_optional)):
    return _call(admin.poll_session, admin.bearer(authorization), world, cfg)


@router.delete('/session')
def end_session(authorization: str | None = Header(None)):
    return _call(admin.end_session, admin.bearer(authorization))


# ---------------------------------------------------------------------------- checkpoint 2: report sign-off
@public_router.get('/review-queue')
def public_review_queue():
    """Anonymous list for the review desk's Read buttons: id, version, report hash and review state only."""
    with db() as c:
        q = review.queue(c)
    return {'schema': 'scooby.review-queue-public/1', 'generated_at': q['generated_at'],
            'items': [{k: i[k] for k in ('report_id', 'report_version', 'report_sha256', 'created', 'state')} for i in q['items']]}


@router.get('/reviews')
def review_queue(principal=Depends(require_admin('report_review'))):
    with db() as c:
        return review.queue(c)


@router.get('/reviews/{report_id}/{version}')
def review_detail(report_id: str, version: str, principal=Depends(require_admin('report_review'))):
    with db() as c:
        return _call(review.detail, c, report_id, version, principal)


@router.post('/reviews/{report_id}/{version}/attempts')
def start_review(report_id: str, version: str, x: DecisionIn, idempotency_key: str | None = Header(None),
                 principal=Depends(require_admin('report_review')), cfg=Depends(get_admin_cfg), world=Depends(get_world)):
    return _call(review.create_attempt, report_id, version, decision=x.decision, reason=x.reason,
                 expected_target_digest=x.expected_target_digest, idem=idem_key(idempotency_key),
                 principal=principal, world=world, cfg=cfg)


@router.get('/review-attempts/{attempt_id}')
def poll_review(attempt_id: str, principal=Depends(require_admin('report_review')), cfg=Depends(get_admin_cfg),
                world=Depends(get_world_optional)):
    return _call(review.poll_attempt, attempt_id, principal, world, cfg)


@router.post('/review-attempts/{attempt_id}/cancel')
def cancel_review(attempt_id: str, principal=Depends(require_admin('report_review'))):
    return _call(review.cancel_attempt, attempt_id, principal)


@router.post('/reviews/{report_id}/{version}/revoke')
def revoke_review(report_id: str, version: str, x: ReviewRevokeIn, principal=Depends(require_admin('report_review'))):
    return _call(review.revoke, report_id, version, principal, x.reason)


# ---------------------------------------------------------------------------- browser CORS
def cors_path(path: str) -> bool:
    """Browser routes that carry an admin bearer token: the admin API and the web publication sign-off."""
    return (path.startswith('/web/v1/admin/') or path.startswith('/web/v1/approvals/')
            or (path.startswith('/web/v1/reports/') and path.endswith('/approve')))


class AdminWebCORS(CORSMiddleware):
    """Exact web origin only, no cookies; allows the Authorization and Idempotency-Key headers."""

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and cors_path(scope['path']):
            await super().__call__(scope, receive, send)
        else:
            await self.app(scope, receive, send)
