"""Fenced outbox publisher: `python -m publication.publisher` (separate process, not Huey).

Claiming bumps `fence` and sets a lease; every later write is `... WHERE id=? AND fence=?`.
A publisher that loses its lease sees rowcount 0 and stops without broadcasting. The signed
tx and its hash are stored before broadcast so a crash can be reconciled without a second
logical publish; the contract's usedNonce makes an onchain duplicate impossible anyway.
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
import time

from store import db, now
from .chain import ChainSender, LOCAL_CHAIN_IDS
from .config import chain_config
from .db import audit

log = logging.getLogger('publication.publisher')
LEASE_SECONDS = 120
EXPIRY_MARGIN = 60


class LostLease(Exception):
    pass


def claim(owner: str = 'publisher') -> dict | None:
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        r = c.execute("""SELECT * FROM pub_outbox
                         WHERE state IN ('queued','reconcile') OR (state IN ('signing','submitted') AND lease < ?)
                         ORDER BY created LIMIT 1""", (now(),)).fetchone()
        if not r:
            return None
        nxt = 'reconcile' if r['tx_hash'] else 'signing'
        c.execute('UPDATE pub_outbox SET fence=fence+1, lease=?, state=? WHERE id=? AND fence=?',
                  (now() + LEASE_SECONDS, nxt, r['id'], r['fence']))
        audit(c, r['target_id'], 'outbox_claimed', owner, {'outbox_id': r['id'], 'fence': r['fence'] + 1, 'state': nxt})
        return dict(c.execute('SELECT * FROM pub_outbox WHERE id=?', (r['id'],)).fetchone())


def _write(row_id: str, fence: int, **cols) -> None:
    sets = ', '.join(f'{k}=?' for k in cols)
    with db() as c:
        n = c.execute(f'UPDATE pub_outbox SET {sets} WHERE id=? AND fence=?', (*cols.values(), row_id, fence)).rowcount
        if n == 0:
            raise LostLease(row_id)


def _still_allowed(row_id: str, fence: int) -> bool:
    """Right before broadcast: receipt not revoked, row still ours and not stopped."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        r = c.execute('SELECT o.state, o.fence, r.revoked_at FROM pub_outbox o JOIN pub_receipts r ON r.id=o.receipt_id WHERE o.id=?',
                      (row_id,)).fetchone()
        if not r or r['fence'] != fence or r['state'] != 'signing' or r['revoked_at'] is not None:
            return False
        c.execute('UPDATE pub_outbox SET lease=? WHERE id=? AND fence=?', (now() + LEASE_SECONDS, row_id, fence))
        return True


def _target(target_id: str) -> dict:
    with db() as c:
        return json.loads(c.execute('SELECT target_json FROM pub_targets WHERE id=?', (target_id,)).fetchone()['target_json'])


def process(row: dict, sender: ChainSender) -> str:
    """Drive one claimed row to a terminal or reconcilable state. Returns the resulting state."""
    rid, fence = row['id'], row['fence']
    try:
        if row['state'] == 'reconcile' or row['tx_hash']:
            return reconcile(row, sender)
        if row['approval_expiry'] <= now() + EXPIRY_MARGIN:
            _write(rid, fence, state='failed', error='approval expired before broadcast; fresh approval required')
            return 'failed'
        nonce = int(row['nonce'])
        if sender.nonce_used(row['reviewer_addr'], nonce):
            _write(rid, fence, state='failed', error='nonce already used onchain')
            return 'failed'
        target = _target(row['target_id'])
        tx_hash, raw = sender.build_signed(target, row['reviewer_addr'], nonce, row['approval_expiry'], row['signature'])
        # Persist before broadcast: a crash after this point is reconciled, not re-signed.
        _write(rid, fence, tx_hash=tx_hash, raw_tx=raw)
        if not _still_allowed(rid, fence):
            _write(rid, fence, state='failed', error='revoked or lease lost before broadcast', tx_hash=None, raw_tx=None)
            return 'failed'
        _write(rid, fence, state='submitted')
        try:
            sender.broadcast(raw)
        except Exception as e:
            _write(rid, fence, state='reconcile', error=f'broadcast uncertain ({type(e).__name__})')
            return 'reconcile'
        with db() as c:
            audit(c, row['target_id'], 'broadcast', 'publisher', {'outbox_id': rid, 'tx_hash': tx_hash})
        return _confirm(row, sender, tx_hash)
    except LostLease:
        log.warning('lost lease on outbox %s; stopping without further writes', rid)
        return 'lost_lease'


def _confirm(row: dict, sender: ChainSender, tx_hash: str) -> str:
    rec = sender.wait(tx_hash)
    if rec is None:
        _write(row['id'], row['fence'], state='reconcile', error='no receipt yet')
        return 'reconcile'
    if rec.status != 1:
        _write(row['id'], row['fence'], state='failed', error='transaction reverted')
        return 'failed'
    _write(row['id'], row['fence'], state='confirmed', onchain_report_id=rec.onchain_report_id, error=None, lease=None)
    with db() as c:
        audit(c, row['target_id'], 'published', 'publisher', {'outbox_id': row['id'], 'tx_hash': tx_hash,
                                                              'onchain_report_id': rec.onchain_report_id})
    return 'confirmed'


def reconcile(row: dict, sender: ChainSender) -> str:
    rid, fence = row['id'], row['fence']
    nonce = int(row['nonce'])
    if sender.nonce_used(row['reviewer_addr'], nonce):
        report_id = sender.find_published(row['tx_hash']) if row['tx_hash'] else None
        _write(rid, fence, state='confirmed', onchain_report_id=report_id, error=None, lease=None)
        with db() as c:
            audit(c, row['target_id'], 'published', 'reconciler', {'outbox_id': rid, 'tx_hash': row['tx_hash'],
                                                                   'onchain_report_id': report_id})
        return 'confirmed'
    if row['tx_hash'] and sender.tx_known(row['tx_hash']):
        return _confirm(row, sender, row['tx_hash'])
    if row['approval_expiry'] <= now() + EXPIRY_MARGIN:
        _write(rid, fence, state='failed', error='approval expired before confirmation; fresh approval required')
        return 'failed'
    if row['raw_tx']:
        with db() as c:
            r = c.execute('SELECT revoked_at FROM pub_receipts WHERE id=?', (row['receipt_id'],)).fetchone()
        if r['revoked_at'] is not None:
            _write(rid, fence, state='failed', error='revoked')
            return 'failed'
        _write(rid, fence, state='submitted')
        try:
            sender.broadcast(row['raw_tx'])  # same signed tx; same nonce
        except Exception as e:
            _write(rid, fence, state='reconcile', error=f'rebroadcast uncertain ({type(e).__name__})')
            return 'reconcile'
        return _confirm(row, sender, row['tx_hash'])
    # Never signed a tx: go back through the normal path.
    _write(rid, fence, state='queued')
    return 'queued'


def run_once(sender: ChainSender, owner: str = 'publisher') -> str | None:
    row = claim(owner)
    return process(row, sender) if row else None


def _confirm_live(cfg) -> None:
    if cfg.chain_id in LOCAL_CHAIN_IDS:
        return
    expected = f'publish to {cfg.chain_id} {cfg.registry}'
    print(f'About to broadcast ReportRegistry.publish transactions on chain {cfg.chain_id}, registry {cfg.registry}.')
    print(f'Type exactly: {expected}')
    if input('> ').strip() != expected:
        sys.exit('Not confirmed; nothing broadcast.')


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description='Fenced outbox publisher (separate process).')
    ap.add_argument('--once', action='store_true', help='process at most one row and exit')
    ap.add_argument('--interval', type=float, default=5.0)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    cfg = chain_config()
    if not cfg.enabled:
        sys.exit('SCOOBY_PUBLISH_ENABLED is not true; refusing to start.')
    if not (cfg.rpc_url and cfg.registry and cfg.publisher_key):
        sys.exit('SCOOBY_RPC_URL, SCOOBY_REPORT_REGISTRY and SCOOBY_PUBLISHER_KEY are required.')
    from .chain import Web3Sender
    sender = Web3Sender(cfg.rpc_url, cfg.chain_id, cfg.registry, cfg.publisher_key, cfg.confirmations)
    sender.preflight()
    _confirm_live(cfg)
    while True:
        state = run_once(sender)
        if args.once:
            print(state or 'idle')
            return
        if state is None:
            time.sleep(args.interval)


if __name__ == '__main__':
    main()
