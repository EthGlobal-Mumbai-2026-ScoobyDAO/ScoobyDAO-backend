"""FastAPI dependencies. Tests replace get_world / get_gate through app.dependency_overrides;
production code never reads an env flag to substitute a fake issuer or chain."""
from __future__ import annotations
import hmac
import threading
from functools import lru_cache

from fastapi import Header, HTTPException

from . import service
from .config import ConfigError, chain_config, settings, world_config
from .world import WorldClient

_world_lock = threading.Lock()
_world: WorldClient | None = None


def get_settings():
    try:
        return settings()
    except ConfigError as e:
        raise HTTPException(503, str(e)) from None


def get_chain_cfg():
    try:
        return chain_config()
    except ConfigError as e:
        raise HTTPException(503, str(e)) from None


def get_world() -> WorldClient:
    """Real World client from env. No configuration means 503 (fail closed)."""
    global _world
    with _world_lock:
        if _world is None:
            try:
                _world = WorldClient(world_config())
            except ConfigError as e:
                raise HTTPException(503, f'World sign-off is not configured: {e}') from None
        return _world


def get_world_optional() -> WorldClient | None:
    try:
        return get_world()
    except HTTPException:
        return None


@lru_cache(maxsize=1)
def _sender_preflight(rpc_url: str, chain_id: int, registry: str, publisher_key: str):
    from .chain import Web3Sender
    sender = Web3Sender(rpc_url, chain_id, registry, publisher_key)
    sender.preflight()  # raises ChainError; lru_cache does not cache exceptions
    return True


def get_gate():
    cfg = chain_config()

    def preflight():
        if not (cfg.rpc_url and cfg.registry and cfg.publisher_key):
            from .chain import ChainError
            raise ChainError('SCOOBY_RPC_URL / SCOOBY_REPORT_REGISTRY / SCOOBY_PUBLISHER_KEY missing')
        _sender_preflight(cfg.rpc_url, cfg.chain_id, cfg.registry, cfg.publisher_key)
    return service.make_gate(cfg, preflight)


def require_operator(authorization: str | None = Header(None)) -> str:
    token = settings().operator_token
    if not token:
        raise HTTPException(503, 'SCOOBY_OPERATOR_TOKEN is not configured; operator routes are disabled')
    supplied = (authorization or '').removeprefix('Bearer ').strip()
    if not supplied or not hmac.compare_digest(supplied.encode(), token.encode()):
        raise HTTPException(401, 'operator bearer token required')
    return 'operator'


def idem_key(k: str | None) -> str:
    if not k or len(k) > 200:
        raise HTTPException(400, 'Idempotency-Key required (maximum 200 characters)')
    return k
