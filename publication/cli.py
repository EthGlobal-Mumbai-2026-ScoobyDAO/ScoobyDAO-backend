"""Operator CLI: python -m publication.cli {enroll,list,disable,enable,grant,ungrant,publish-confirm,reconcile}.

World subjects are pairwise, so a reviewer's (iss, sub) can only be learned by having them
complete a device login for this client: `enroll` does exactly that and stores nothing else.
Admin scopes (case_investigation, report_review, publication) are granted per enrolled reviewer;
World authentication alone never grants one.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import uuid

from store import db, digest, now
from . import admin, service
from .config import ConfigError, chain_config, settings, world_config
from .db import audit
from .world import Denied, Error, Expired, Pending, SlowDown, TokenInvalid, Tokens, WorldClient, WorldError


def _world() -> WorldClient:
    try:
        return WorldClient(world_config())
    except ConfigError as e:
        sys.exit(f'World is not configured: {e}')


SANDBOX_ISSUER = 'https://sandbox.auth.world.org'


def environment_label(issuer: str) -> str:
    if issuer == SANDBOX_ISSUER:
        return 'SANDBOX (test identities only; does not prove a real Orb-verified person)'
    if issuer == 'https://auth.world.org':
        return 'PRODUCTION'
    return 'CUSTOM issuer'


def world_check(world: WorldClient | None = None) -> list[str]:
    """Config + live discovery check. Makes no authenticated call and starts no login."""
    world = world or _world()
    cfg = world.config
    try:
        d = world.discovery()
    except WorldError as e:
        sys.exit(f'World discovery failed for {cfg.issuer}: {e}')
    lines = [f'Environment:     {environment_label(cfg.issuer)}',
             f'Issuer:          {d.issuer}',
             f'Client ID:       {cfg.client_id}',
             f'Key ID (kid):    {cfg.key_id or "(none; allowed only if one key is registered)"}',
             f'Accepted acr:    {", ".join(cfg.accepted_acr)}',
             f'Device endpoint: {d.device_authorization_endpoint}',
             f'Token endpoint:  {d.token_endpoint}']
    lines += [f'Warning:         {w}' for w in d.warnings]
    return lines


def enroll(label: str, world: WorldClient | None = None, *, sleep=time.sleep, scopes: tuple[str, ...] = (),
           request_acr: bool = True, verbose: bool = False) -> tuple[str, str]:
    world = world or _world()
    print(f'World environment: {environment_label(world.config.issuer)}')
    started = now()
    try:
        dev = world.start_device(request_acr=request_acr)
    except WorldError as e:
        sys.exit(f'Could not start device login: {e}')
    print(f'Reviewer "{label}": open {dev.verification_uri_complete or dev.verification_uri}')
    print(f'and enter code {dev.user_code} in World App. Waiting (expires in {dev.expires_in}s)...')
    interval = dev.interval
    deadline = started + dev.expires_in
    while now() < deadline:
        sleep(interval)
        r = world.poll(dev.device_code)
        if verbose:
            extra = getattr(r, 'code', '') or getattr(r, 'detail', '')
            print(f'  {time.strftime("%H:%M:%S")} poll -> {type(r).__name__}{" " + extra if extra else ""} (next in {interval}s)', flush=True)
        if isinstance(r, Pending):
            continue
        if isinstance(r, SlowDown):
            interval += 5
            continue
        if isinstance(r, (Denied, Expired)):
            why = f' ({r.detail})' if getattr(r, 'detail', '') else ''
            sys.exit(f'Enrollment {type(r).__name__.lower()}{why}; reviewer not added.')
        if isinstance(r, Error):
            if r.terminal:
                sys.exit(f'Issuer error ({r.code}{": " + r.detail if r.detail else ""}); reviewer not added.')
            interval = min(60, interval * 2)
            continue
        if isinstance(r, Tokens):
            try:
                ident = world.validate_id_token(r.id_token, started_at=started, accepted_acr=world.config.accepted_acr)
            except (TokenInvalid, WorldError) as e:
                sys.exit(f'ID token rejected ({e}); reviewer not added.')
            with db() as c:
                c.execute('INSERT INTO pub_reviewers(iss,sub,label,enabled,created) VALUES(?,?,?,1,?) '
                          'ON CONFLICT(iss,sub) DO UPDATE SET label=excluded.label, enabled=1', (ident.iss, ident.sub, label, now()))
                audit(c, None, 'reviewer_enrolled', 'cli', {'label': label, 'iss': ident.iss, 'sub_sha256': digest(ident.sub.encode()), 'acr': ident.acr})
                for scope in scopes:
                    admin.grant(c, ident.iss, ident.sub, scope, 'cli')
            print(f'Enrolled "{label}" ({ident.acr}){" with " + ", ".join(scopes) if scopes else ""}.')
            return ident.iss, ident.sub
    sys.exit('Device code expired; reviewer not added.')


def list_reviewers() -> list[dict]:
    with db() as c:
        out = [dict(r) for r in c.execute('SELECT iss, sub, label, enabled, created FROM pub_reviewers ORDER BY created')]
        for r in out:
            r['scopes'] = sorted(x['scope'] for x in c.execute(
                'SELECT scope FROM admin_scopes WHERE iss=? AND sub=? AND revoked_at IS NULL', (r['iss'], r['sub'])))
        return out


def set_scope(label: str, scope: str, granted: bool) -> int:
    """Grant or withdraw an admin scope for every enrolled reviewer with this label."""
    if scope not in admin.SCOPES:
        sys.exit(f'Unknown scope {scope}; expected one of {", ".join(admin.SCOPES)}.')
    with db() as c:
        rows = c.execute('SELECT iss, sub FROM pub_reviewers WHERE label=?', (label,)).fetchall()
        for r in rows:
            if granted:
                admin.grant(c, r['iss'], r['sub'], scope, 'cli')
            else:
                admin.revoke_scope(c, r['iss'], r['sub'], scope, 'cli')
        return len(rows)


def set_enabled(label: str, enabled: bool) -> int:
    with db() as c:
        n = c.execute('UPDATE pub_reviewers SET enabled=? WHERE label=?', (1 if enabled else 0, label)).rowcount
        audit(c, None, 'reviewer_enabled' if enabled else 'reviewer_disabled', 'cli', {'label': label, 'rows': n})
        return n


def publish_confirm(target_id: str, *, confirm: str | None = None) -> dict:
    from .deps import get_gate
    t = service.get_target(target_id)
    m = t['claim_manifest']
    print(f"Target {t['id']}\n  report {t['report_id']}@{t['report_version']} sha256 {t['report_sha256']}\n"
          f"  claim: {m['claimText']}\n  chain {t['target']['chainId']} registry {t['target']['registry']}\n"
          f"  target digest {t['target_digest']}\n  status {t['status']['state']}")
    typed = confirm if confirm is not None else input('Type the first 12 characters of the target digest to request publication: ').strip()
    if typed != t['target_digest'][:12]:
        sys.exit('Not confirmed; nothing requested.')
    try:
        return service.request_publication(target_id, idem=f'cli:{uuid.uuid4().hex}', actor='cli', gate=get_gate(),
                                           settings=settings(), chain_cfg=chain_config())
    except service.PubError as e:
        sys.exit(f'Refused ({e.status}): {e}')


def reconcile_all() -> list[str]:
    from .chain import Web3Sender
    from .publisher import claim, process
    cfg = chain_config()
    if not (cfg.enabled and cfg.rpc_url and cfg.registry and cfg.publisher_key):
        sys.exit('Publishing is not enabled/configured; nothing to reconcile.')
    sender = Web3Sender(cfg.rpc_url, cfg.chain_id, cfg.registry, cfg.publisher_key, cfg.confirmations)
    sender.preflight()
    out = []
    while (row := claim('cli-reconcile')) is not None:
        out.append(f"{row['id']}: {process(row, sender)}")
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog='python -m publication.cli')
    sp = ap.add_subparsers(dest='cmd', required=True)
    e = sp.add_parser('enroll', help='device-login a reviewer and allowlist their (iss, sub)')
    e.add_argument('--name', required=True)
    e.add_argument('--scope', action='append', default=[], choices=admin.SCOPES, help='admin scope to grant (repeatable)')
    e.add_argument('--no-acr-request', action='store_true',
                   help='diagnostic: omit the claims parameter; the ID token acr is still checked')
    e.add_argument('--verbose', action='store_true', help='print every poll result (never tokens or codes)')
    sp.add_parser('list', help='list reviewers')
    for name in ('disable', 'enable'):
        p = sp.add_parser(name)
        p.add_argument('--name', required=True)
    for name, text in (('grant', 'grant an admin scope'), ('ungrant', 'withdraw an admin scope')):
        p = sp.add_parser(name, help=text)
        p.add_argument('--name', required=True)
        p.add_argument('--scope', required=True, choices=admin.SCOPES)
    pc = sp.add_parser('publish-confirm', help='explicitly request publication of an approved target')
    pc.add_argument('--target', required=True)
    sp.add_parser('reconcile', help='drive outbox rows in reconcile/queued states with the real chain')
    sp.add_parser('world-check', help='show the configured World environment and check live discovery (no login)')
    x = sp.add_parser('export-reviewer', help='print a SCOOBY_REVIEWERS value for an enrolled reviewer (treat as a secret)')
    x.add_argument('--name', required=True)
    a = ap.parse_args(argv)
    if a.cmd == 'enroll':
        enroll(a.name, scopes=tuple(dict.fromkeys(a.scope)), request_acr=not a.no_acr_request, verbose=a.verbose)
    elif a.cmd == 'list':
        for r in list_reviewers():
            print(f"{'enabled ' if r['enabled'] else 'disabled'}  {r['label']:<24} {r['iss']}  sub={r['sub'][:10]}…  "
                  f"scopes={','.join(r['scopes']) or '-'}")
    elif a.cmd in ('disable', 'enable'):
        n = set_enabled(a.name, a.cmd == 'enable')
        print(f'{a.cmd}d {n} reviewer(s)')
    elif a.cmd in ('grant', 'ungrant'):
        n = set_scope(a.name, a.scope, a.cmd == 'grant')
        print(f'{a.cmd}ed {a.scope} for {n} reviewer(s)')
    elif a.cmd == 'publish-confirm':
        print(publish_confirm(a.target))
    elif a.cmd == 'export-reviewer':
        from .reviewers import export
        entries = export(a.name)
        if not entries:
            sys.exit(f'No enrolled reviewer named {a.name}; run enroll first.')
        print(json.dumps(entries, separators=(',', ':')))
    elif a.cmd == 'world-check':
        print('\n'.join(world_check()))
    elif a.cmd == 'reconcile':
        print('\n'.join(reconcile_all()) or 'nothing to reconcile')


if __name__ == '__main__':
    main()
