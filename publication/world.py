"""World ID (auth.world.org) OIDC client: discovery, JWKS, private_key_jwt, device grant, ID token.

Every endpoint, parameter, error code and claim used here comes from the live discovery
document or https://auth.world.org/docs (guides: oidc, step-up, app-registration, id-token).
Undocumented choices are listed in WORLD_FEEDBACK.md under "missing docs".

Tests inject an httpx transport through the constructor. There is deliberately no env flag
that swaps in a fake issuer.
"""
from __future__ import annotations
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

import httpx
import jwt
from jwt import PyJWK

from .config import WorldConfig

log = logging.getLogger('publication.world')
DEVICE_GRANT = 'urn:ietf:params:oauth:grant-type:device_code'
ASSERTION_TYPE = 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer'
VERIFIER_VERSION = 'scooby.world-verifier/1'
ASSERTION_LIFETIME = 60  # seconds; World allows up to one hour
ID_TOKEN_SKEW = 60
AUTH_TIME_SKEW = 30


class WorldError(RuntimeError):
    """Issuer unavailable or misbehaving. Never treated as approval."""


class TokenInvalid(ValueError):
    """ID token failed validation. The message is safe to log (no token content)."""


@dataclass(frozen=True)
class Discovery:
    issuer: str
    device_authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    id_token_algs: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeviceStart:
    device_code: str = field(repr=False)
    user_code: str = ''
    verification_uri: str = ''
    verification_uri_complete: str | None = None
    expires_in: int = 0
    interval: int = 5


@dataclass(frozen=True)
class Pending: pass


@dataclass(frozen=True)
class SlowDown: pass


@dataclass(frozen=True)
class Denied: pass


@dataclass(frozen=True)
class Expired: pass


@dataclass(frozen=True)
class Tokens:
    id_token: str = field(repr=False)


@dataclass(frozen=True)
class Error:
    code: str
    terminal: bool  # True: end the attempt (503, invalid_grant, invalid_client...). False: back off and retry.


PollResult = Pending | SlowDown | Denied | Expired | Tokens | Error


@dataclass(frozen=True)
class Identity:
    iss: str
    sub: str
    acr: str
    amr: tuple[str, ...]
    auth_time: int


class WorldClient:
    def __init__(self, config: WorldConfig, *, transport: httpx.BaseTransport | None = None,
                 clock: Callable[[], float] = time.time):
        self.config = config
        self.clock = clock
        self._http = httpx.Client(transport=transport, timeout=config.http_timeout, follow_redirects=False)
        self._discovery: Discovery | None = None
        self._discovery_at = 0.0
        self._jwks: dict[str, dict] = {}
        self._timing_logged: set[str] = set()

    # ------------------------------------------------------------------ discovery / jwks
    def discovery(self) -> Discovery:
        if self._discovery and self.clock() - self._discovery_at < self.config.discovery_ttl:
            return self._discovery
        doc = self._get_json(self.config.issuer + '/.well-known/openid-configuration', 'discovery')
        if doc.get('issuer') != self.config.issuer:
            raise WorldError('discovery issuer does not match WORLD_ISSUER')
        for k in ('device_authorization_endpoint', 'token_endpoint', 'jwks_uri'):
            if not isinstance(doc.get(k), str) or not doc[k].startswith('https://'):
                raise WorldError(f'discovery is missing {k}')
        warnings = []
        for k, want in (('grant_types_supported', DEVICE_GRANT), ('token_endpoint_auth_methods_supported', 'private_key_jwt')):
            if k not in doc:
                warnings.append(f'{k} absent from discovery')
                log.warning('world discovery: %s absent; continuing', k)
            elif want not in doc[k]:
                raise WorldError(f'discovery {k} does not include {want}')
        algs = tuple(a for a in doc.get('id_token_signing_alg_values_supported') or ['RS256'] if a != 'none' and not a.startswith('HS'))
        if not algs:
            raise WorldError('no acceptable asymmetric id_token signing algorithm')
        self._discovery = Discovery(doc['issuer'], doc['device_authorization_endpoint'], doc['token_endpoint'],
                                    doc['jwks_uri'], algs, tuple(warnings))
        self._discovery_at = self.clock()
        self._timing('discovery_ok')
        return self._discovery

    def _load_jwks(self) -> None:
        doc = self._get_json(self.discovery().jwks_uri, 'jwks')
        keys = {k['kid']: k for k in doc.get('keys', []) if isinstance(k, dict) and k.get('kid') and k.get('kty') == 'RSA'}
        if not keys:
            raise WorldError('JWKS contains no usable RSA keys')
        self._jwks = keys

    def _key_for(self, kid: str) -> dict:
        if kid not in self._jwks:
            self._load_jwks()  # refresh once on unknown kid, then fail
        if kid not in self._jwks:
            raise TokenInvalid('unknown kid')
        return self._jwks[kid]

    # ------------------------------------------------------------------ client auth
    def client_assertion(self, endpoint: str) -> str:
        """Fresh single-use RS256 assertion per request (World: assertions are single-use across endpoints)."""
        iat = int(self.clock())
        aud = self.config.issuer if self.config.assertion_aud == 'issuer' else endpoint
        claims = {'iss': self.config.client_id, 'sub': self.config.client_id, 'aud': aud,
                  'jti': uuid.uuid4().hex, 'iat': iat, 'exp': iat + ASSERTION_LIFETIME}
        headers = {'kid': self.config.key_id} if self.config.key_id else None
        return jwt.encode(claims, self.config.private_key_pem, algorithm='RS256', headers=headers)

    def _auth_form(self, endpoint: str) -> dict:
        return {'client_id': self.config.client_id, 'client_assertion_type': ASSERTION_TYPE,
                'client_assertion': self.client_assertion(endpoint)}

    # ------------------------------------------------------------------ device grant
    def acr_claims(self, accepted: tuple[str, ...] | None = None) -> str:
        values = list(accepted or self.config.accepted_acr)
        return json.dumps({'id_token': {'acr': {'essential': True, 'values': values}}}, separators=(',', ':'))

    def start_device(self, accepted_acr: tuple[str, ...] | None = None) -> DeviceStart:
        d = self.discovery()
        form = {'scope': 'openid', 'claims': self.acr_claims(accepted_acr), **self._auth_form(d.device_authorization_endpoint)}
        try:
            r = self._http.post(d.device_authorization_endpoint, data=form)
        except httpx.HTTPError as e:
            raise WorldError(f'device authorization request failed ({type(e).__name__})') from None
        if r.status_code == 429:
            raise WorldError('device authorization rate limited (429); retry after Retry-After')
        if r.status_code != 200:
            raise WorldError(f'device authorization failed: HTTP {r.status_code} {_oauth_error(r)}')
        body = _json(r)
        try:
            out = DeviceStart(device_code=str(body['device_code']), user_code=str(body['user_code']),
                              verification_uri=str(body['verification_uri']),
                              verification_uri_complete=body.get('verification_uri_complete'),
                              expires_in=int(body['expires_in']), interval=max(1, int(body.get('interval', 5))))
        except (KeyError, TypeError, ValueError):
            raise WorldError('device authorization response is missing required fields') from None
        self._timing('first_device_request')
        return out

    def poll(self, device_code: str) -> PollResult:
        d = self.discovery()
        form = {'grant_type': DEVICE_GRANT, 'device_code': device_code, **self._auth_form(d.token_endpoint)}
        try:
            r = self._http.post(d.token_endpoint, data=form)
        except httpx.TimeoutException:
            return Error('timeout', terminal=False)
        except httpx.HTTPError as e:
            return Error(type(e).__name__, terminal=False)
        if r.status_code == 200:
            body = _json(r)
            if not isinstance(body.get('id_token'), str):
                return Error('no_id_token', terminal=True)
            self._timing('first_token_success')
            return Tokens(body['id_token'])
        if r.status_code >= 500:
            # World: "HTTP 503: Temporary unavailability, never approval. End this attempt."
            return Error(f'http_{r.status_code}', terminal=True)
        if r.status_code == 429:
            return Error('rate_limited', terminal=False)
        code = _oauth_error(r)
        if code == 'authorization_pending':
            return Pending()
        if code == 'slow_down':
            return SlowDown()
        if code == 'access_denied':
            return Denied()
        if code == 'expired_token':
            return Expired()
        return Error(code or f'http_{r.status_code}', terminal=True)

    # ------------------------------------------------------------------ id token
    def validate_id_token(self, id_token: str, *, started_at: float, accepted_acr: tuple[str, ...]) -> Identity:
        d = self.discovery()
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError:
            raise TokenInvalid('malformed token') from None
        alg = header.get('alg')
        if alg not in d.id_token_algs or alg == 'none' or str(alg).startswith('HS'):
            raise TokenInvalid('signing algorithm not accepted')
        kid = header.get('kid')
        if not kid:
            raise TokenInvalid('missing kid')
        key = PyJWK(self._key_for(kid), algorithm=alg)
        now = self.clock()
        try:
            claims = jwt.decode(id_token, key=key.key, algorithms=[alg], audience=self.config.client_id,
                                issuer=self.config.issuer, leeway=ID_TOKEN_SKEW,
                                options={'require': ['iss', 'sub', 'aud', 'exp', 'iat', 'auth_time', 'acr', 'amr'],
                                         'verify_iat': False, 'verify_exp': False})
        except jwt.InvalidAudienceError:
            raise TokenInvalid('wrong audience') from None
        except jwt.InvalidIssuerError:
            raise TokenInvalid('wrong issuer') from None
        except jwt.MissingRequiredClaimError as e:
            raise TokenInvalid(f'missing claim {e.claim}') from None
        except jwt.InvalidSignatureError:
            raise TokenInvalid('bad signature') from None
        except jwt.PyJWTError as e:
            raise TokenInvalid(f'invalid token ({type(e).__name__})') from None
        # Time checks against our injectable clock (PyJWT uses wall time).
        if not isinstance(claims['exp'], (int, float)) or claims['exp'] < now - ID_TOKEN_SKEW:
            raise TokenInvalid('token expired')
        if not isinstance(claims['iat'], (int, float)) or claims['iat'] > now + ID_TOKEN_SKEW:
            raise TokenInvalid('iat in the future')
        aud = claims['aud']
        if isinstance(aud, list) and len(aud) > 1 and claims.get('azp') != self.config.client_id:
            raise TokenInvalid('azp does not match client_id')
        auth_time = claims['auth_time']
        if not isinstance(auth_time, int):
            raise TokenInvalid('auth_time is not an integer')
        if auth_time < started_at - AUTH_TIME_SKEW or auth_time > now + AUTH_TIME_SKEW:
            raise TokenInvalid('auth_time outside this attempt')
        if claims['acr'] not in accepted_acr:
            raise TokenInvalid('acr not accepted')
        amr = claims['amr']
        if not isinstance(amr, list) or not all(isinstance(a, str) for a in amr) or not amr:
            raise TokenInvalid('amr missing or malformed')
        if not isinstance(claims['sub'], str) or not claims['sub']:
            raise TokenInvalid('sub missing')
        # World documents no delegation claim for ID tokens. An RFC 8693 actor claim would mean someone other
        # than the authenticated person is acting, and no human checkpoint accepts that.
        if 'act' in claims or 'may_act' in claims:
            raise TokenInvalid('delegated (actor) token cannot confirm a human checkpoint')
        return Identity(iss=claims['iss'], sub=claims['sub'], acr=claims['acr'], amr=tuple(amr), auth_time=auth_time)

    # ------------------------------------------------------------------ helpers
    def _get_json(self, url: str, what: str) -> dict:
        try:
            r = self._http.get(url)
        except httpx.HTTPError as e:
            raise WorldError(f'{what} request failed ({type(e).__name__})') from None
        if r.status_code != 200:
            raise WorldError(f'{what} request failed: HTTP {r.status_code}')
        return _json(r)

    def _timing(self, event: str) -> None:
        if event not in self._timing_logged:
            self._timing_logged.add(event)
            log.info('world_timing %s', json.dumps({'event': event, 'at': self.clock()}))


def _json(r: httpx.Response) -> dict:
    try:
        body = r.json()
    except ValueError:
        raise WorldError('issuer returned non-JSON') from None
    if not isinstance(body, dict):
        raise WorldError('issuer returned unexpected JSON')
    return body


def _oauth_error(r: httpx.Response) -> str:
    try:
        e = r.json().get('error')
        return e if isinstance(e, str) else ''
    except ValueError:
        return ''
