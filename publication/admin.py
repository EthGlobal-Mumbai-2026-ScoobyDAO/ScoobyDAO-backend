"""Admin boundary for the two World ID checkpoints (docs/admin-world-checkpoints.md).

World authentication identifies a person; it never grants Scooby admin permission. Permission is the
server-side reviewer allowlist (pub_reviewers, enrolled by CLI device login) plus an explicit scope per
action (admin_scopes):

  case_investigation  checkpoint 1: "Go for investigation" on a human-required Case (case bridge)
  report_review       checkpoint 2: sign-off on a generated report version (publication/review.py)
  publication         the separate, explicit publication sign-off requested from the web

An admin session is an opaque bearer token issued with a World device login. It becomes active only when
the validated (iss, sub) is an enabled reviewer holding at least one scope. The token is stored as SHA-256,
and reviewer status and scopes are re-read on every request, so disabling a reviewer or revoking a scope
takes effect immediately. A session lets an admin see private queues and start a checkpoint; each
checkpoint still needs its own fresh World confirmation bound to that action.
"""
from __future__ import annotations
import json
import logging
import re
import secrets
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from store import db, digest, ident, now
from . import service
from .config import AdminConfig
from .world import Denied, Error, Expired, Identity, SlowDown, TokenInvalid, Tokens, WorldClient, WorldError

log = logging.getLogger('publication.admin')
SCOPES = ('case_investigation', 'report_review', 'publication')
SESSION_SCHEMA = 'scooby.admin-session/1'
TOKEN_PREFIX = 'sas_'
# The case bridge binds this action into its challenge; case_investigation covers nothing else.
CASE_ACTIONS = frozenset({'diagnostic_research'})


class Unauthorized(service.PubError):
    status = 401


class Forbidden(service.PubError):
    status = 403


class TooManyRequests(service.PubError):
    status = 429


@dataclass(frozen=True)
class Principal:
    session_id: str
    iss: str
    sub: str
    label: str
    scopes: frozenset
    expires_at: float


def subject_hash(iss: str, sub: str) -> str:
    """Stable pseudonym for logs and audit detail; the pairwise sub itself never leaves the database."""
    return digest(f'{iss}|{sub}'.encode())


def audit(c, kind: str, actor: str, detail: dict | None = None) -> None:
    """Append-only. Never pass tokens, device codes or subjects in detail."""
    c.execute('INSERT INTO admin_events(kind,actor,detail_json,created) VALUES(?,?,?,?)',
              (kind, actor, json.dumps(detail or {}, sort_keys=True), now()))


def bearer(header: str | None) -> str | None:
    value = (header or '').strip()
    if value[:7].lower() != 'bearer ':
        return None
    return value[7:].strip() or None


# ---------------------------------------------------------------------------- permissions
def scopes_of(c, iss: str, sub: str) -> frozenset:
    """Scopes held by an enabled reviewer; empty for everyone else."""
    rows = c.execute('''SELECT s.scope FROM admin_scopes s JOIN pub_reviewers r ON r.iss=s.iss AND r.sub=s.sub
                        WHERE s.iss=? AND s.sub=? AND s.revoked_at IS NULL AND r.enabled=1''', (iss, sub)).fetchall()
    return frozenset(r['scope'] for r in rows)


def permitted(c, iss: str, sub: str, scope: str) -> bool:
    return scope in scopes_of(c, iss, sub)


def grant(c, iss: str, sub: str, scope: str, actor: str) -> None:
    if scope not in SCOPES:
        raise ValueError(f'unknown scope {scope!r}; expected one of {", ".join(SCOPES)}')
    c.execute('''INSERT INTO admin_scopes(iss,sub,scope,granted_by,created) VALUES(?,?,?,?,?)
                 ON CONFLICT(iss,sub,scope) DO UPDATE SET revoked_at=NULL, granted_by=excluded.granted_by,
                 created=excluded.created''', (iss, sub, scope, actor, now()))
    audit(c, 'scope_granted', actor, {'scope': scope, 'subject_sha256': subject_hash(iss, sub)})


def revoke_scope(c, iss: str, sub: str, scope: str, actor: str) -> int:
    n = c.execute('UPDATE admin_scopes SET revoked_at=? WHERE iss=? AND sub=? AND scope=? AND revoked_at IS NULL',
                  (now(), iss, sub, scope)).rowcount
    audit(c, 'scope_revoked', actor, {'scope': scope, 'subject_sha256': subject_hash(iss, sub), 'rows': n})
    return n


# ---------------------------------------------------------------------------- sessions
def _token_hash(token: str) -> str:
    return digest(token.encode())


def _session(c, session_id: str):
    return c.execute('SELECT * FROM admin_sessions WHERE id=?', (session_id,)).fetchone()


def _by_token(c, token: str | None):
    if not token or not token.startswith(TOKEN_PREFIX) or len(token) > 200:
        return None
    return c.execute('SELECT * FROM admin_sessions WHERE token_hash=?', (_token_hash(token),)).fetchone()


def public_session(c, s) -> dict:
    out = {'schema': SESSION_SCHEMA, 'state': s['state']}
    if s['state'] == 'pending':
        out.update(user_code=s['user_code'], verification_uri=s['verification_uri_complete'] or s['verification_uri'],
                   interval=s['interval'], expires_at=s['login_expires_at'])
    elif s['state'] == 'active':
        reviewer = c.execute('SELECT label FROM pub_reviewers WHERE iss=? AND sub=?', (s['iss'], s['sub'])).fetchone()
        out.update(label=reviewer['label'] if reviewer else None, scopes=sorted(scopes_of(c, s['iss'], s['sub'])),
                   expires_at=s['expires_at'])
    if s['error']:
        out['detail'] = s['error']
    return out


def _end(c, session_id: str, state: str, why: str | None = None) -> dict:
    c.execute('UPDATE admin_sessions SET state=?, error=? WHERE id=?', (state, why, session_id))
    audit(c, f'login_{state}', 'service', {'session_id': session_id, 'why': why})
    service._forget(session_id)
    return public_session(c, _session(c, session_id))


def start_session(world: WorldClient, cfg: AdminConfig) -> dict:
    """Start a World device login. Anyone may start one; only an enabled reviewer with a scope can finish it."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        for s in c.execute("SELECT id FROM admin_sessions WHERE state='pending' AND login_expires_at<=?", (now(),)).fetchall():
            _end(c, s['id'], 'expired', 'login code expired')
        pending = c.execute("SELECT count(*) FROM admin_sessions WHERE state='pending'").fetchone()[0]
        if pending >= cfg.max_pending_logins:
            raise TooManyRequests('too many admin logins are pending; retry after one completes or expires')
    started = now()
    try:
        dev = world.start_device(world.config.accepted_acr)
    except WorldError as e:
        raise service.Unavailable(f'World issuer unavailable: {e}') from None
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    sid = ident()
    with db() as c:
        c.execute('''INSERT INTO admin_sessions(id,token_hash,state,accepted_acr,device_code_hash,user_code,verification_uri,
                     verification_uri_complete,interval,next_poll_at,started_at,login_expires_at,created)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (sid, _token_hash(token), 'pending', json.dumps(list(world.config.accepted_acr)),
                   digest(dev.device_code.encode()), dev.user_code, dev.verification_uri, dev.verification_uri_complete,
                   dev.interval, started + dev.interval, started, started + dev.expires_in, now()))
        audit(c, 'login_started', 'anonymous', {'session_id': sid})
        service._remember(sid, dev.device_code)
        out = public_session(c, _session(c, sid))
    out['session_token'] = token  # returned once; only its hash is stored
    return out


def poll_session(token: str | None, world: WorldClient | None, cfg: AdminConfig) -> dict:
    """Session status. While the login is pending this polls World at most once per interval."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        s = _by_token(c, token)
        if not s:
            raise Unauthorized('unknown admin session')
        sid = s['id']
        if s['state'] == 'active' and s['expires_at'] <= now():
            c.execute("UPDATE admin_sessions SET state='expired' WHERE id=? AND state='active'", (sid,))
            audit(c, 'session_expired', 'service', {'session_id': sid})
            return public_session(c, _session(c, sid))
        if s['state'] != 'pending':
            return public_session(c, s)
        if s['login_expires_at'] <= now():
            return _end(c, sid, 'expired', 'login code expired')
        device_code = service._device_code(sid)
        if device_code is None:
            return _end(c, sid, 'expired', 'device code lost (service restarted)')
        if world is None or now() < s['next_poll_at']:
            return public_session(c, s)
        c.execute('UPDATE admin_sessions SET next_poll_at=? WHERE id=?', (now() + s['interval'], sid))
        interval, started, accepted = s['interval'], s['started_at'], tuple(json.loads(s['accepted_acr']))
    try:
        result = world.poll(device_code)
    except WorldError as e:
        result = Error(str(e), terminal=False)
    identity, problem = None, None
    if isinstance(result, Tokens):
        service._forget(sid)
        try:
            identity = world.validate_id_token(result.id_token, started_at=started, accepted_acr=accepted)
        except TokenInvalid as e:
            problem = f'id_token rejected: {e}'
        except WorldError as e:
            problem = f'verifier unavailable: {e}'
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        s = _session(c, sid)
        if s['state'] != 'pending':
            audit(c, 'late_world_result_ignored', 'service', {'session_id': sid, 'state': s['state']})
            return public_session(c, s)
        if identity is not None:
            if not scopes_of(c, identity.iss, identity.sub):
                audit(c, 'login_not_permitted', 'world', {'session_id': sid, 'subject_sha256': subject_hash(identity.iss, identity.sub)})
                return _end(c, sid, 'not_permitted', 'This World ID is not an enabled admin with a scope.')
            c.execute("UPDATE admin_sessions SET state='active', iss=?, sub=?, expires_at=? WHERE id=?",
                      (identity.iss, identity.sub, now() + cfg.session_ttl, sid))
            label = c.execute('SELECT label FROM pub_reviewers WHERE iss=? AND sub=?', (identity.iss, identity.sub)).fetchone()['label']
            audit(c, 'session_active', label, {'session_id': sid, 'acr': identity.acr, 'amr': list(identity.amr)})
        elif problem:
            return _end(c, sid, 'failed', problem)
        elif isinstance(result, SlowDown):
            interval += 5
            c.execute('UPDATE admin_sessions SET interval=?, next_poll_at=? WHERE id=?', (interval, now() + interval, sid))
        elif isinstance(result, Denied):
            return _end(c, sid, 'denied', 'Denied in World App.')
        elif isinstance(result, Expired):
            return _end(c, sid, 'expired', 'login code expired')
        elif isinstance(result, Error):
            if result.terminal:
                return _end(c, sid, 'failed', f'issuer error: {result.code}')
            c.execute('UPDATE admin_sessions SET next_poll_at=? WHERE id=?', (now() + min(60, interval * 2), sid))
        return public_session(c, _session(c, sid))


def end_session(token: str | None) -> dict:
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        s = _by_token(c, token)
        if not s:
            raise Unauthorized('unknown admin session')
        if s['state'] == 'pending':
            return _end(c, s['id'], 'cancelled', 'Login cancelled.')
        if s['state'] == 'active':
            return _end(c, s['id'], 'revoked', 'Signed out.')
        return public_session(c, s)


def principal_for_token(token: str | None) -> Principal | None:
    """The signed-in admin for a bearer token: active, unexpired session of a still-enabled reviewer."""
    with db() as c:
        s = _by_token(c, token)
        if not s or s['state'] != 'active' or s['expires_at'] is None or s['expires_at'] <= now():
            return None
        reviewer = c.execute('SELECT label, enabled FROM pub_reviewers WHERE iss=? AND sub=?', (s['iss'], s['sub'])).fetchone()
        if not reviewer or not reviewer['enabled']:
            return None
        return Principal(s['id'], s['iss'], s['sub'], reviewer['label'], scopes_of(c, s['iss'], s['sub']), s['expires_at'])


def session_active(c, session_id: str, iss: str, sub: str) -> bool:
    s = _session(c, session_id)
    return bool(s and s['state'] == 'active' and s['expires_at'] > now() and (s['iss'], s['sub']) == (iss, sub))


# ---------------------------------------------------------------------------- checkpoint 1 hook
def authorize_case_admin(identity: Identity, binding: dict) -> bool:
    """Checkpoint 1 for the case bridge: case_world.poll calls world.authorize_case_admin(identity, binding)
    after validating the World token and the case binding, and starts no run unless this returns True.

    True only when the bound action is an investigation action and the World-validated person is an enabled
    reviewer holding case_investigation who is signed in to an active admin session. Read-only, because the
    caller holds a write transaction on the same database; the decision is logged, not stored.
    """
    action = binding.get('action') if isinstance(binding, dict) else None
    try:
        with db() as c:
            allowed = (action in CASE_ACTIONS and permitted(c, identity.iss, identity.sub, 'case_investigation')
                       and c.execute("SELECT 1 FROM admin_sessions WHERE iss=? AND sub=? AND state='active' AND expires_at>?",
                                     (identity.iss, identity.sub, now())).fetchone() is not None)
    except Exception as e:  # fail closed; never let an authorizer error approve
        log.warning('case admin authorization failed closed (%s)', type(e).__name__)
        return False
    log.info('case_admin_authorization %s', json.dumps({
        'allowed': allowed, 'action': action, 'case_id': binding.get('case_id') if isinstance(binding, dict) else None,
        'subject_sha256': subject_hash(identity.iss, identity.sub)}, sort_keys=True))
    return allowed


class AdminWorldClient(WorldClient):
    """The API's World client. It carries the checkpoint-1 hook the case bridge looks for."""

    def authorize_case_admin(self, identity: Identity, binding: dict) -> bool:
        return authorize_case_admin(identity, binding)


# ---------------------------------------------------------------------------- route guard
# Case-checkpoint routes (backend PR #12) that start, show or continue an investigation authorization.
# Guarded by path so they stay protected wherever they are defined; CORS and hidden buttons are not authorization.
GUARDED_ROUTES = (
    (re.compile(r'^/scouting/cases/[^/]+/challenge/?$'), 'case_investigation'),
    (re.compile(r'^/scouting/(?:challenges|world-attempts)(?:/|$)'), 'case_investigation'),
    (re.compile(r'^/investigations/[^/]+/resume/?$'), 'case_investigation'),
)


def guarded_scope(path: str) -> str | None:
    for pattern, scope in GUARDED_ROUTES:
        if pattern.match(path):
            return scope
    return None


class AdminRouteGuard:
    """ASGI middleware: guarded routes need an active admin session holding the route's scope."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') == 'OPTIONS':
            return await self.app(scope, receive, send)
        required = guarded_scope(scope['path'])
        if required is None:
            return await self.app(scope, receive, send)
        token = bearer(dict(scope.get('headers') or []).get(b'authorization', b'').decode('latin-1'))
        principal = await run_in_threadpool(principal_for_token, token)
        if principal is None:
            return await _deny(send, 401, 'admin session required')
        if required not in principal.scopes:
            return await _deny(send, 403, f'admin scope {required} required')
        return await self.app(scope, receive, send)


async def _deny(send, status: int, detail: str) -> None:
    body = json.dumps({'detail': detail}).encode()
    headers = [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode())]
    if status == 401:
        headers.append((b'www-authenticate', b'Bearer'))
    await send({'type': 'http.response.start', 'status': status, 'headers': headers})
    await send({'type': 'http.response.body', 'body': body})
