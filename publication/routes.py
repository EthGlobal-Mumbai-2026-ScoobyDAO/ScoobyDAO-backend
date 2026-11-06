"""Operator API: /publication/v1. Mutating routes need the operator bearer token."""
from __future__ import annotations
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from . import service
from .deps import get_chain_cfg, get_gate, get_settings, get_world, get_world_optional, idem_key, require_operator

router = APIRouter(prefix='/publication/v1', tags=['publication'])


def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except service.PubError as e:
        raise HTTPException(e.status, str(e)) from None


class TargetIn(BaseModel):
    report_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=200)
    params: dict[str, Any] = Field(default_factory=dict)


class AttemptIn(BaseModel):
    decision: Literal['approve', 'reject', 'revise']
    reason: str = Field(min_length=1, max_length=1000)


class RevokeIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


@router.post('/targets')
def create_target(x: TargetIn, idempotency_key: str | None = Header(None), actor: str = Depends(require_operator),
                  settings=Depends(get_settings), chain_cfg=Depends(get_chain_cfg)):
    return _call(service.prepare_target, x.report_id, x.version, x.params, idem=idem_key(idempotency_key),
                 actor=actor, settings=settings, chain_cfg=chain_cfg)


@router.get('/targets/{target_id}')
def read_target(target_id: str):
    return _call(service.get_target, target_id)


@router.post('/targets/{target_id}/attempts')
def create_attempt(target_id: str, x: AttemptIn, idempotency_key: str | None = Header(None),
                   actor: str = Depends(require_operator), world=Depends(get_world)):
    return _call(service.create_attempt, target_id, x.decision, x.reason, idem=idem_key(idempotency_key),
                 actor=actor, world=world)


@router.get('/attempts/{attempt_id}')
def read_attempt(attempt_id: str, world=Depends(get_world_optional)):
    return _call(service.poll_attempt, attempt_id, world)


@router.post('/attempts/{attempt_id}/cancel')
def cancel_attempt(attempt_id: str, actor: str = Depends(require_operator)):
    return _call(service.cancel_attempt, attempt_id, actor)


@router.post('/targets/{target_id}/publish')
def publish(target_id: str, idempotency_key: str | None = Header(None), actor: str = Depends(require_operator),
            gate=Depends(get_gate), settings=Depends(get_settings), chain_cfg=Depends(get_chain_cfg)):
    return _call(service.request_publication, target_id, idem=idem_key(idempotency_key), actor=actor, gate=gate,
                 settings=settings, chain_cfg=chain_cfg)


@router.post('/targets/{target_id}/revoke')
def revoke(target_id: str, x: RevokeIn, actor: str = Depends(require_operator)):
    return _call(service.revoke, target_id, actor, x.reason)
