"""Environment parsing with fail-closed validation. Secrets never appear in repr()."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ACR = ('https://world.org/oidc/acr/orb', 'https://world.org/oidc/acr/orb-face')


class ConfigError(RuntimeError):
    """Configuration is missing or unsafe; the dependent feature stays disabled."""


def _bool(v: str | None) -> bool:
    return (v or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == '':
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ConfigError(f'{name} must be an integer') from e


@dataclass(frozen=True)
class WorldConfig:
    issuer: str
    client_id: str
    key_id: str | None
    accepted_acr: tuple[str, ...]
    # 'endpoint' = aud is the exact endpoint being called (World docs: app-registration);
    # 'issuer' = aud is the issuer. The prompt's 'token_endpoint' value maps to 'endpoint'.
    assertion_aud: str
    private_key_pem: bytes = field(repr=False)
    http_timeout: float = 10.0
    discovery_ttl: float = 3600.0

    def __repr__(self) -> str:  # never print key material
        return f'WorldConfig(issuer={self.issuer!r}, client_id={self.client_id!r}, key_id={self.key_id!r}, accepted_acr={self.accepted_acr!r}, assertion_aud={self.assertion_aud!r})'


@dataclass(frozen=True)
class ChainConfig:
    enabled: bool
    chain_id: int
    rpc_url: str | None
    registry: str | None
    publisher_key: str | None = field(repr=False)
    attestor_key: str | None = field(repr=False)
    resolver: str | None
    adjudicator: str | None
    confirmations: int
    demo_autopublish: bool

    def __repr__(self) -> str:
        return (f'ChainConfig(enabled={self.enabled}, chain_id={self.chain_id}, registry={self.registry!r}, '
                f'resolver={self.resolver!r}, adjudicator={self.adjudicator!r}, confirmations={self.confirmations})')


@dataclass(frozen=True)
class Settings:
    approval_ttl: int
    operator_token: str | None = field(repr=False)
    web_origin: str = 'http://localhost:3000'
    claim_hash_alg: str = 'keccak256'
    lock_margin: int = 3600

    def __repr__(self) -> str:
        return f'Settings(approval_ttl={self.approval_ttl}, web_origin={self.web_origin!r}, claim_hash_alg={self.claim_hash_alg!r})'


def settings() -> Settings:
    alg = os.getenv('SCOOBY_CLAIM_HASH_ALG', 'keccak256').strip().lower()
    if alg not in ('sha256', 'keccak256'):
        raise ConfigError('SCOOBY_CLAIM_HASH_ALG must be sha256 or keccak256')
    return Settings(
        approval_ttl=_int('SCOOBY_APPROVAL_TTL', 600),
        operator_token=os.getenv('SCOOBY_OPERATOR_TOKEN') or None,
        web_origin=os.getenv('SCOOBY_WEB_ORIGIN', 'http://localhost:3000'),
        claim_hash_alg=alg,
        lock_margin=_int('SCOOBY_LOCK_MARGIN', 3600),
    )


def world_config() -> WorldConfig:
    """Raises ConfigError unless every World setting needed for a live device grant is present."""
    issuer = (os.getenv('WORLD_ISSUER') or '').rstrip('/')
    client_id = os.getenv('WORLD_CLIENT_ID') or ''
    key_path = os.getenv('WORLD_CLIENT_KEY_PATH') or ''
    if not issuer.startswith('https://'):
        raise ConfigError('WORLD_ISSUER must be an https URL')
    if not client_id:
        raise ConfigError('WORLD_CLIENT_ID is not set')
    if not key_path or not Path(key_path).is_file():
        raise ConfigError('WORLD_CLIENT_KEY_PATH does not point to a private key file')
    acr = tuple(a.strip() for a in os.getenv('WORLD_ACCEPTED_ACR', ','.join(DEFAULT_ACR)).split(',') if a.strip())
    if not acr:
        raise ConfigError('WORLD_ACCEPTED_ACR is empty')
    aud = os.getenv('WORLD_ASSERTION_AUD', 'endpoint').strip().lower()
    if aud == 'token_endpoint':
        aud = 'endpoint'
    if aud not in ('endpoint', 'issuer'):
        raise ConfigError('WORLD_ASSERTION_AUD must be endpoint (alias token_endpoint) or issuer')
    return WorldConfig(issuer=issuer, client_id=client_id, key_id=os.getenv('WORLD_CLIENT_KEY_ID') or None,
                       accepted_acr=acr, assertion_aud=aud, private_key_pem=Path(key_path).read_bytes())


def chain_config() -> ChainConfig:
    enabled = _bool(os.getenv('SCOOBY_PUBLISH_ENABLED'))
    return ChainConfig(
        enabled=enabled,
        chain_id=_int('SCOOBY_CHAIN_ID', 11155111),
        rpc_url=os.getenv('SCOOBY_RPC_URL') or None,
        registry=os.getenv('SCOOBY_REPORT_REGISTRY') or None,
        publisher_key=os.getenv('SCOOBY_PUBLISHER_KEY') or None,
        attestor_key=os.getenv('SCOOBY_ATTESTOR_KEY') or None,
        resolver=os.getenv('SCOOBY_RESOLVER') or None,
        adjudicator=os.getenv('SCOOBY_ADJUDICATOR') or None,
        confirmations=max(1, _int('SCOOBY_CONFIRMATIONS', 1)),
        demo_autopublish=_bool(os.getenv('SCOOBY_DEMO_AUTOPUBLISH')),
    )


@dataclass(frozen=True)
class AdminConfig:
    """Admin boundary for the two World ID checkpoints (see docs/admin-world-checkpoints.md)."""
    session_ttl: int                   # seconds an admin session stays active after its World login
    attempt_ttl: int                   # upper bound for one checkpoint confirmation (World caps device codes at 20 min)
    audience: str                      # bound into every checkpoint binding; a receipt for another audience never counts
    max_pending_logins: int            # unauthenticated login starts are capped (each one calls World)
    report_release: str                # 'all': consumers list every report with its review state; 'approved': only approved ones
    publication_requires_review: bool  # a publication target needs a current World-confirmed report approval


def admin_config() -> AdminConfig:
    release = os.getenv('SCOOBY_REPORT_RELEASE', 'all').strip().lower()
    if release not in ('all', 'approved'):
        raise ConfigError('SCOOBY_REPORT_RELEASE must be all or approved')
    audience = (os.getenv('SCOOBY_ADMIN_AUDIENCE') or 'scooby-admin').strip()
    if not audience or len(audience) > 200:
        raise ConfigError('SCOOBY_ADMIN_AUDIENCE must be 1-200 characters')
    session_ttl = _int('SCOOBY_ADMIN_SESSION_TTL', 4 * 3600)
    attempt_ttl = _int('SCOOBY_ADMIN_ATTEMPT_TTL', 600)
    if not 60 <= session_ttl <= 24 * 3600:
        raise ConfigError('SCOOBY_ADMIN_SESSION_TTL must be between 60 and 86400 seconds')
    if not 60 <= attempt_ttl <= 1200:
        raise ConfigError('SCOOBY_ADMIN_ATTEMPT_TTL must be between 60 and 1200 seconds')
    return AdminConfig(
        session_ttl=session_ttl,
        attempt_ttl=attempt_ttl,
        audience=audience,
        max_pending_logins=max(1, _int('SCOOBY_ADMIN_MAX_PENDING_LOGINS', 20)),
        report_release=release,
        publication_requires_review=os.getenv('SCOOBY_PUBLICATION_REQUIRES_REVIEW', 'true').strip().lower()
        not in ('0', 'false', 'no', 'off'),
    )
