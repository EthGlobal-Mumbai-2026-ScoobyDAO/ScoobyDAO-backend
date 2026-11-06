"""Admin helpers for tests. `login` creates a real admin session through the World device-login route
against tests/fake_world.py (no network). `session_headers` is a test-only shortcut for suites whose World
fake cannot drive that route (for example the case-bridge tests); it never runs in the API."""
import secrets

from store import db, digest, ident, now
from publication import admin


def enroll(iss: str, sub: str, *scopes: str, label: str = 'admin-1', enabled: bool = True) -> None:
    """Allowlist a reviewer the way `publication.cli enroll` would, then grant scopes."""
    from publication import db as publication_db
    publication_db.init()  # idempotent; suites that only run store.init() on a fresh database need the admin tables
    with db() as c:
        c.execute('INSERT INTO pub_reviewers(iss,sub,label,enabled,created) VALUES(?,?,?,?,0) '
                  'ON CONFLICT(iss,sub) DO UPDATE SET label=excluded.label, enabled=excluded.enabled',
                  (iss, sub, label, 1 if enabled else 0))
        for scope in scopes:
            admin.grant(c, iss, sub, scope, 'test')


def login(client, fw, clock, sub: str | None = None, expect: str = 'active') -> dict:
    """Start an admin login, let the fake World approve it, poll once; returns the Authorization header."""
    fw.script(('success', {'sub': sub} if sub else {}))
    r = client.post('/web/v1/admin/session')
    assert r.status_code == 200, r.text
    started = r.json()
    headers = {'Authorization': 'Bearer ' + started['session_token']}
    clock.advance(started['interval'])
    state = client.get('/web/v1/admin/session', headers=headers).json()
    assert state['state'] == expect, state
    return headers


def session_headers(iss: str, sub: str, *scopes: str, label: str = 'test-admin', ttl: float = 3600) -> dict:
    """Test-only: enroll (iss, sub) with scopes and record an already-active admin session for it."""
    enroll(iss, sub, *scopes, label=label)
    token = admin.TOKEN_PREFIX + secrets.token_urlsafe(32)
    t = now()
    with db() as c:
        c.execute('''INSERT INTO admin_sessions(id,token_hash,state,iss,sub,accepted_acr,device_code_hash,user_code,verification_uri,
                     interval,next_poll_at,started_at,login_expires_at,expires_at,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (ident(), digest(token.encode()), 'active', iss, sub, '[]', digest(b'test-only'), 'TEST', 'https://test.invalid',
                   5, t, t, t, t + ttl, t))
    return {'Authorization': 'Bearer ' + token}
