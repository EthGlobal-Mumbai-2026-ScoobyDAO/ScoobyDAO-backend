"""Single-operator, bounded discovery loop; no provider hints become gate votes."""
import argparse
from contextlib import closing
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import discovery
import collect_lp_concentration
import live_pilot
import review_queue

MIN_INTERVAL = 300
MARKET_RETRY = 3600
LP_GLOBAL_INTERVAL = 300


def lock_runner(db):
    """Hold a separate SQLite write lock for this database until the process exits."""
    lock = sqlite3.connect(str(db.resolve()) + '.runner-lock.sqlite3', timeout=0)
    try:
        lock.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError:
        lock.close()
        raise RuntimeError('Another discovery runner holds the database lock') from None
    return lock


def choose_market(db, as_of):
    """Reserve one old Ethereum pool for a bounded experimental collection attempt."""
    with closing(sqlite3.connect(db)) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS market_attempts (
            candidate_id TEXT NOT NULL, pool_id TEXT NOT NULL,
            attempted_at TEXT NOT NULL, status TEXT NOT NULL,
            PRIMARY KEY(candidate_id, pool_id))''')
        last = con.execute('SELECT MAX(attempted_at) FROM market_attempts').fetchone()[0]
        if last and (as_of - discovery.stamp(last)).total_seconds() < MARKET_RETRY:
            return None
        rows = con.execute('''SELECT l.candidate_id, l.pool_id, l.created_at, c.record, a.attempted_at
            FROM pilot_leads l JOIN candidates c ON c.id=l.candidate_id
            LEFT JOIN market_attempts a ON a.candidate_id=l.candidate_id AND a.pool_id=l.pool_id
            GROUP BY l.candidate_id, l.pool_id
            ORDER BY COALESCE(a.attempted_at, ''), l.candidate_id, l.pool_id''').fetchall()
        for candidate, pool, created, raw, attempted in rows:
            try:
                record = json.loads(raw)
                if (record.get('mode') != 'live' or record['identity']['chain_id'] != 1
                    or record.get('selection', {}).get('status') == 'selected'
                    or discovery.identity(1, record['identity']['address']) != candidate
                    or not re.fullmatch(r'0x[0-9a-f]{40}', pool)
                    or not created or (as_of - discovery.stamp(created)).total_seconds() < 86400
                    or (attempted and (as_of - discovery.stamp(attempted)).total_seconds() < MARKET_RETRY)):
                    continue
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
            con.execute('''INSERT INTO market_attempts VALUES(?,?,?,?)
                ON CONFLICT(candidate_id,pool_id) DO UPDATE SET
                attempted_at=excluded.attempted_at,status=excluded.status''',
                (candidate, pool, as_of.isoformat(), 'started'))
            con.commit()
            return candidate, pool
    return None


def collect_market(db, root, as_of):
    if not os.environ.get('PUBLICNODE_TOKEN', '').strip():
        return 'token_unavailable'
    target = choose_market(db, as_of)
    if target is None:
        return 'no_due_pool'
    candidate, pool = target
    command = [sys.executable, str(Path(__file__).with_name('collect_market_activity.py')),
               '--db', str(db), '--output', str(root), '--candidate-id', candidate,
               '--pool', pool, '--budget', '40']
    try:
        result = subprocess.run(command, capture_output=True, timeout=480)
        status = 'collected' if result.returncode == 0 else 'unavailable'
    except (OSError, subprocess.TimeoutExpired):
        status = 'unavailable'
    with closing(sqlite3.connect(db)) as con:
        con.execute('UPDATE market_attempts SET status=? WHERE candidate_id=? AND pool_id=?',
                    (status, candidate, pool))
        con.commit()
    return status


def collect_lp(db, root, as_of):
    """Reserve at most one address-sample capture per five minutes per database."""
    with closing(sqlite3.connect(db)) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS lp_attempts (
            candidate_id TEXT NOT NULL, pool_id TEXT NOT NULL,
            attempted_at TEXT NOT NULL, status TEXT NOT NULL,
            PRIMARY KEY(candidate_id, pool_id))''')
        last = con.execute('SELECT MAX(attempted_at) FROM lp_attempts').fetchone()[0]
        if last and (as_of - discovery.stamp(last)).total_seconds() < LP_GLOBAL_INTERVAL:
            return 'not_due'
        rows = con.execute('''SELECT l.candidate_id, l.pool_id, c.record, a.attempted_at
            FROM pilot_leads l JOIN candidates c ON c.id=l.candidate_id
            LEFT JOIN lp_attempts a ON a.candidate_id=l.candidate_id AND a.pool_id=l.pool_id
            GROUP BY l.candidate_id, l.pool_id
            ORDER BY COALESCE(a.attempted_at, ''), l.candidate_id, l.pool_id''').fetchall()
        target = None
        for candidate, pool, raw, attempted in rows:
            try:
                record = json.loads(raw)
                if (record.get('mode') != 'live' or record['identity']['chain_id'] != 1
                    or record.get('selection', {}).get('status') == 'selected'
                    or discovery.identity(1, record['identity']['address']) != candidate
                    or not re.fullmatch(r'0x[0-9a-f]{40}', pool)
                    or (attempted and (as_of - discovery.stamp(attempted)).total_seconds() < MARKET_RETRY)
                    or not collect_lp_concentration.holder_hints(record, root, pool)):
                    continue
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
            target = candidate, pool
            con.execute('''INSERT INTO lp_attempts VALUES(?,?,?,?)
                ON CONFLICT(candidate_id,pool_id) DO UPDATE SET
                attempted_at=excluded.attempted_at,status=excluded.status''',
                (candidate, pool, as_of.isoformat(), 'started'))
            con.commit()
            break
    if target is None:
        return 'no_due_pool'
    candidate, pool = target
    command = [sys.executable, str(Path(__file__).with_name('collect_lp_concentration.py')),
               '--db', str(db), '--output', str(root), '--candidate-id', candidate,
               '--pool', pool, '--budget', '17']
    try:
        result = subprocess.run(command, capture_output=True, timeout=240)
        status = 'collected' if result.returncode == 0 else 'unavailable'
    except (OSError, subprocess.TimeoutExpired):
        status = 'unavailable'
    with closing(sqlite3.connect(db)) as con:
        con.execute('UPDATE lp_attempts SET status=? WHERE candidate_id=? AND pool_id=?',
                    (status, candidate, pool))
        con.commit()
    return status


def refresh_security(db, root, as_of):
    """Refresh one older Ethereum lead's provider hints; these never cast a vote."""
    with closing(sqlite3.connect(db)) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS security_refresh_attempts (
            candidate_id TEXT PRIMARY KEY, attempted_at TEXT NOT NULL, status TEXT NOT NULL)''')
        last = con.execute('SELECT MAX(attempted_at) FROM security_refresh_attempts').fetchone()[0]
        if last and (as_of - discovery.stamp(last)).total_seconds() < LP_GLOBAL_INTERVAL:
            return 'not_due', 0
        rows = con.execute('''SELECT c.id, c.record, a.attempted_at FROM candidates c
            LEFT JOIN security_refresh_attempts a ON a.candidate_id=c.id
            ORDER BY COALESCE(a.attempted_at, ''), c.id''').fetchall()
        target = None
        for candidate, raw, attempted in rows:
            try:
                record = json.loads(raw)
                address = record['identity']['address'].lower()
                if (record.get('mode') != 'live' or record['identity']['chain_id'] != 1
                    or record.get('selection', {}).get('status') == 'selected'
                    or discovery.identity(1, address) != candidate
                    or (attempted and (as_of - discovery.stamp(attempted)).total_seconds() < MARKET_RETRY)):
                    continue
                url = 'https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses=' + address
                recent = False
                for e in record.get('evidence', []):
                    if 'Request URL: ' + url in e.get('limitations', []) and e.get('fetched_at'):
                        age = (as_of - discovery.stamp(e['fetched_at'])).total_seconds()
                        if 0 <= age < MARKET_RETRY:
                            recent = True
                            break
                if recent:
                    continue
            except (ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
                continue
            target = candidate, address, url
            con.execute('''INSERT INTO security_refresh_attempts VALUES(?,?,?)
                ON CONFLICT(candidate_id) DO UPDATE SET attempted_at=excluded.attempted_at,status=excluded.status''',
                (candidate, as_of.isoformat(), 'started'))
            con.commit()
            break
    if target is None:
        return 'no_due_lead', 0
    candidate, address, url = target
    data, evidence, metadata = live_pilot.Fetcher(root / 'snapshots', 1).get(url)
    valid = (metadata['status'] == 'ok' and isinstance(data, dict) and data.get('code') == 1
             and isinstance(data.get('result'), dict) and address in data['result'])
    status = 'refreshed' if valid else 'unavailable'
    with closing(sqlite3.connect(db)) as con:
        with con:
            con.execute('BEGIN IMMEDIATE')
            if valid and con.execute('SELECT 1 FROM candidates WHERE id=?', (candidate,)).fetchone():
                live_pilot.attach_evidence(con, candidate, evidence)
            con.execute('UPDATE security_refresh_attempts SET status=? WHERE candidate_id=?', (status, candidate))
    return status, 1


def cycle(db, root, limit, budget, chains, market, lp_enabled=False):
    report = live_pilot.run(db, root, limit, budget, chains)
    refresh_status, refresh_calls = refresh_security(db, root, dt.datetime.now(dt.timezone.utc))
    market_status = collect_market(db, root, dt.datetime.now(dt.timezone.utc)) if market else 'disabled'
    lp_status = collect_lp(db, root, dt.datetime.now(dt.timezone.utc)) if lp_enabled else 'disabled'
    queue = review_queue.queue(db, root)
    review_queue.save_atomic(root / 'review-queue.html', review_queue.html_page(queue))
    review_queue.save_atomic(root / 'review-queue.json', json.dumps(queue, indent=2, ensure_ascii=False))
    return {'status': report['status'], 'source_calls': report['calls'] + refresh_calls, 'security_refresh': refresh_status,
            'source_issues': report['issues'], 'market_collection': market_status, 'lp_collection': lp_status,
            'monitored': queue['monitored_count'], 'qualified': queue['qualified_count'],
            'enabled_verifiers': queue['metric_verifiers_enabled']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--interval', type=int, default=MIN_INTERVAL)
    parser.add_argument('--limit-per-chain', type=int, default=5)
    parser.add_argument('--budget', type=int, default=22)
    parser.add_argument('--chains', nargs='+', choices=list(live_pilot.CHAINS), default=list(live_pilot.CHAINS))
    parser.add_argument('--collect-market', action='store_true', help='Enable experimental, bounded archive collection')
    parser.add_argument('--skip-lp', action='store_true', help='Disable bounded LP-address collection')
    parser.add_argument('--once', action='store_true', help='Run one cycle and exit')
    args = parser.parse_args()
    if args.interval < MIN_INTERVAL or not 1 <= args.limit_per_chain <= 10 or not 0 <= args.budget <= 30 or len(set(args.chains)) != len(args.chains):
        parser.error('interval must be at least 300 seconds; limit 1-10; budget 0-30; chains must be unique')
    args.db.parent.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    lock = lock_runner(args.db)
    try:
        while True:
            try:
                outcome = cycle(args.db, args.output, args.limit_per_chain, args.budget, args.chains, args.collect_market, not args.skip_lp)
                print(json.dumps(outcome, ensure_ascii=False), flush=True)
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                print(json.dumps({'status': 'cycle_failed', 'error_type': type(exc).__name__}), flush=True)
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    finally:
        lock.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
