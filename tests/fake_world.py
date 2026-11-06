"""Fake World issuer for tests: an httpx.MockTransport (no network).

It serves discovery, JWKS (an RSA key generated here), the device authorization endpoint and
a token endpoint whose outcomes each test scripts. It enforces the client assertion the way
World documents it: RS256 signature with the registered public key, iss=sub=client_id,
aud = issuer or the exact endpoint called, exp in the future and at most 1h after iat, and a
jti never seen before (assertions are single-use across endpoints).
"""
from __future__ import annotations
import json
import secrets
import time
import uuid
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ISSUER = 'https://fake-world.test'
CLIENT_ID = 'app_scooby_test'
ORB = 'https://world.org/oidc/acr/orb'


def new_rsa():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


class Clock:
    def __init__(self, t: float | None = None):
        self.t = t if t is not None else time.time()

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class FakeWorld:
    def __init__(self, clock: Clock, client_key, *, client_id: str = CLIENT_ID, interval: int = 5, expires_in: int = 1200):
        self.clock = clock
        self.client_id = client_id
        self.client_pub = client_key.public_key()
        self.idp_key = new_rsa()
        self.idp_kid = 'idp-1'
        self.interval = interval
        self.expires_in = expires_in
        self.seen_jti: set[str] = set()
        self.scripts: list[list] = []      # queued scripts for the next device starts
        self.devices: dict[str, dict] = {}  # device_code -> {'script': [...], 'started': t}
        self.issued_device_codes: list[str] = []
        self.issued_id_tokens: list[str] = []
        self.device_requests: list[dict] = []
        self.token_requests = 0
        self.rejected_assertions = 0
        self.default_sub = 'pairwise-sub-reviewer-1'
        self.down = False  # discovery/JWKS unavailable

    # -------------------------------------------------------------- scripting
    def script(self, *steps) -> None:
        """Steps for the next device start: 'pending', 'slow_down', 'denied', 'expired', 'http500',
        'timeout', 'invalid_grant' or ('success', {claim overrides / '_alg' / '_kid' / '_key'})."""
        self.scripts.append(list(steps))

    def id_token(self, overrides: dict | None = None) -> str:
        o = dict(overrides or {})
        alg = o.pop('_alg', 'RS256')
        kid = o.pop('_kid', self.idp_kid)
        key = o.pop('_key', None)
        t = int(self.clock())
        claims = {'iss': ISSUER, 'sub': self.default_sub, 'aud': self.client_id, 'iat': t, 'exp': t + 300,
                  'jti': uuid.uuid4().hex, 'auth_time': t, 'acr': ORB, 'amr': ['pop']}
        for k, v in o.items():
            if v is None:
                claims.pop(k, None)
            else:
                claims[k] = v
        if alg == 'none':
            tok = jwt.encode(claims, key=None, algorithm='none', headers={'kid': kid})
        elif alg == 'HS256':
            tok = jwt.encode(claims, key or 'shared-secret-that-is-long-enough-32b', algorithm='HS256', headers={'kid': kid})
        else:
            tok = jwt.encode(claims, key or self.idp_key, algorithm=alg, headers={'kid': kid})
        self.issued_id_tokens.append(tok)
        return tok

    # -------------------------------------------------------------- transport
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if self.down and path.startswith('/.well-known'):
            return httpx.Response(503, json={'error': 'temporarily_unavailable'})
        if path == '/.well-known/openid-configuration':
            return httpx.Response(200, json=self.discovery())
        if path == '/.well-known/jwks.json':
            jwk = json.loads(RSAAlgorithm.to_jwk(self.idp_key.public_key()))
            jwk.update({'kid': self.idp_kid, 'alg': 'RS256', 'use': 'sig'})
            return httpx.Response(200, json={'keys': [jwk]})
        form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        endpoint = f'{ISSUER}{path}'
        if not self._assertion_ok(form, endpoint):
            self.rejected_assertions += 1
            return httpx.Response(400, json={'error': 'invalid_client'})
        if path == '/api/v1/device_authorization':
            return self._device(form)
        if path == '/api/v1/token':
            return self._token(form, req)
        return httpx.Response(404)

    def discovery(self) -> dict:
        return {
            'issuer': ISSUER,
            'authorization_endpoint': f'{ISSUER}/api/v1/authorize',
            'token_endpoint': f'{ISSUER}/api/v1/token',
            'device_authorization_endpoint': f'{ISSUER}/api/v1/device_authorization',
            'jwks_uri': f'{ISSUER}/.well-known/jwks.json',
            'grant_types_supported': ['authorization_code', 'urn:ietf:params:oauth:grant-type:device_code'],
            'token_endpoint_auth_methods_supported': ['client_secret_basic', 'private_key_jwt'],
            'token_endpoint_auth_signing_alg_values_supported': ['RS256'],
            'id_token_signing_alg_values_supported': ['RS256'],
            'acr_values_supported': [ORB, 'https://world.org/oidc/acr/orb-face'],
            'claims_parameter_supported': True,
            'subject_types_supported': ['pairwise'],
        }

    def _assertion_ok(self, form: dict, endpoint: str) -> bool:
        if form.get('client_assertion_type') != 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer':
            return False
        a = form.get('client_assertion')
        if not a or form.get('client_id') != self.client_id:
            return False
        try:
            claims = jwt.decode(a, self.client_pub, algorithms=['RS256'], options={'verify_aud': False, 'verify_exp': False, 'verify_iat': False})
        except jwt.PyJWTError:
            return False
        now = self.clock()
        if claims.get('iss') != self.client_id or claims.get('sub') != self.client_id:
            return False
        if claims.get('aud') not in (ISSUER, endpoint):
            return False
        if not isinstance(claims.get('exp'), int) or claims['exp'] <= now or claims['exp'] - claims.get('iat', 0) > 3600:
            return False
        jti = claims.get('jti')
        if not jti or len(jti) > 256 or jti in self.seen_jti:
            return False
        self.seen_jti.add(jti)
        return True

    def _device(self, form: dict) -> httpx.Response:
        self.device_requests.append({k: v for k, v in form.items() if k != 'client_assertion'})
        if form.get('scope') != 'openid':
            return httpx.Response(400, json={'error': 'invalid_scope'})
        code = 'dc_' + secrets.token_urlsafe(24)
        self.issued_device_codes.append(code)
        self.devices[code] = {'script': self.scripts.pop(0) if self.scripts else [('success', {})], 'started': self.clock()}
        user = secrets.token_hex(2).upper() + '-' + secrets.token_hex(2).upper()
        return httpx.Response(200, json={'device_code': code, 'user_code': user,
                                         'verification_uri': f'{ISSUER}/device',
                                         'verification_uri_complete': f'{ISSUER}/device?user_code={user}',
                                         'expires_in': self.expires_in, 'interval': self.interval})

    def _token(self, form: dict, req: httpx.Request) -> httpx.Response:
        self.token_requests += 1
        if form.get('grant_type') != 'urn:ietf:params:oauth:grant-type:device_code':
            return httpx.Response(400, json={'error': 'unsupported_grant_type'})
        dev = self.devices.get(form.get('device_code', ''))
        if not dev:
            return httpx.Response(400, json={'error': 'invalid_grant'})
        step = dev['script'].pop(0) if dev['script'] else 'pending'
        if isinstance(step, tuple):
            step, overrides = step
        else:
            overrides = {}
        if step == 'pending':
            return httpx.Response(400, json={'error': 'authorization_pending'})
        if step == 'slow_down':
            return httpx.Response(400, json={'error': 'slow_down'})
        if step == 'denied':
            return httpx.Response(400, json={'error': 'access_denied'})
        if step == 'denied_detail':
            return httpx.Response(400, json={'error': 'access_denied', 'error_description': 'account does not meet the requested acr\x07'})
        if step == 'expired':
            return httpx.Response(400, json={'error': 'expired_token'})
        if step == 'invalid_grant':
            return httpx.Response(400, json={'error': 'invalid_grant'})
        if step == 'http500':
            return httpx.Response(500, json={'error': 'server_error'})
        if step == 'timeout':
            raise httpx.ReadTimeout('fake timeout', request=req)
        if step == 'success':
            overrides.setdefault('auth_time', int(self.clock()))
            return httpx.Response(200, json={'id_token': self.id_token(overrides), 'access_token': 'at_' + secrets.token_hex(8),
                                             'token_type': 'Bearer', 'expires_in': 300})
        raise AssertionError(f'unknown step {step}')
