"""Capture a finalized V2 LP balance sample using provider addresses only as hints."""
import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

import collect_market_activity as collector
import discovery
import lp_concentration as lp
import market_activity as market


def holder_hints(record, root, pool):
    url = 'Request URL: https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses=' + record['identity']['address'].lower()
    candidates = [e for e in record['evidence'] if url in e.get('limitations', [])]
    candidates.sort(key=lambda e: e.get('fetched_at') or '', reverse=True)
    for evidence in candidates[:20]:
        source = evidence.get('source', '')
        if not re.fullmatch(r'snapshots/[0-9a-f]{64}\.json', source):
            continue
        path = root / source
        try:
            if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                continue
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != evidence.get('sha256') or evidence.get('id') != evidence.get('sha256'):
                continue
            doc = json.loads(raw)
            entry = doc['result'][record['identity']['address'].lower()]
            lp_rows, token_rows = entry.get('lp_holders') or [], entry.get('holders') or []
            if doc.get('code') != 1 or not isinstance(lp_rows, list) or not isinstance(token_rows, list):
                continue
            rows = lp_rows + token_rows
            addresses = []
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get('address'), str):
                    continue
                address = row.get('address', '').lower()
                if lp.usable_holder(address, pool) and address not in addresses:
                    addresses.append(address)
                    if len(addresses) == 10:
                        break
            if addresses:
                return addresses
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--candidate-id', required=True)
    parser.add_argument('--pool', required=True)
    parser.add_argument('--budget', type=int, default=20)
    args = parser.parse_args()
    if not 7 <= args.budget <= 20:
        raise ValueError('LP request budget must be 7-20')
    con = sqlite3.connect(args.db)
    try:
        row = con.execute('SELECT record FROM candidates WHERE id=?', (args.candidate_id,)).fetchone()
        if not row:
            raise ValueError('candidate not found')
        record = json.loads(row[0])
        token = record['identity']['address'].lower()
        pool = args.pool.lower()
        if (record.get('mode') != 'live' or record['identity']['chain_id'] != 1
            or discovery.identity(1, token) != args.candidate_id or not re.fullmatch(r'0x[0-9a-f]{40}', pool)):
            raise ValueError('unsupported candidate or pool')
        if not con.execute('SELECT 1 FROM pilot_leads WHERE candidate_id=? AND pool_id=?', (args.candidate_id, pool)).fetchone():
            raise ValueError('pool is not a monitored lead')
        holders = holder_hints(record, args.output, pool)[:args.budget - 7]
        if not holders:
            raise ValueError('no usable LP holder hints')
        rpc = collector.RPC(args.budget)
        if rpc.call('eth_chainId', []) != '0x1':
            raise ValueError('wrong chain')
        block = rpc.block('finalized')
        tag = block['number']
        pair = '0xe6a43905' + token[2:].rjust(64, '0') + market.WETH[2:].rjust(64, '0')
        specs = [('token0', pool, '0x0dfe1681'), ('token1', pool, '0xd21220a7'),
                 ('factory', pool, '0xc45a0155'), ('factory_pair', market.FACTORY, pair),
                 ('total_supply', pool, '0x18160ddd')]
        specs += [('balance:' + address, pool, '0x70a08231' + address[2:].rjust(64, '0')) for address in holders]
        point = {'block_tag': tag, 'block_hash': block['hash'], 'block_timestamp': market.integer(block['timestamp']),
                 'finality': 'finalized', 'calls': {name: rpc.eth(to, data, tag) for name, to, data in specs}}
        doc = {'format': lp.FORMAT, 'candidate_id': args.candidate_id, 'chain_id': 1, 'pool': pool,
               'rpc_url': collector.URL, 'authentication': 'personal_token_path' if rpc.token else 'public',
               'point': point, 'holders': [{'address': address} for address in holders], 'rpc_trace': rpc.trace,
               'limitations': ['Single V2/WETH pool; provider holder list is a non-exhaustive hint.',
                               'Direct LP addresses may represent pooled custody; this is not beneficial ownership.',
                               'RPC response is not a cryptographic consensus proof.']}
        raw = json.dumps(doc, sort_keys=True, indent=2).encode()
        digest = hashlib.sha256(raw).hexdigest()
        folder = args.output / 'snapshots'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (digest + '.json')).write_bytes(raw)
        observed = dt.datetime.fromtimestamp(point['block_timestamp'], dt.timezone.utc).isoformat()
        evidence = {'id': digest, 'source': 'snapshots/' + digest + '.json', 'sha256': digest,
                    'observed_at': observed, 'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'block_number': market.integer(tag), 'kind': 'live_observation',
                    'limitations': [lp.FORMAT, 'Address sample only; pooled custody and other pools are not resolved.']}
        pending = dict(record)
        pending['evidence'] = record['evidence'] + [evidence]
        result = lp.verify(pending, args.output, dt.datetime.now(dt.timezone.utc))
        with con:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT record FROM candidates WHERE id=?', (args.candidate_id,)).fetchone()
            if not current:
                raise ValueError('candidate disappeared during collection')
            current = json.loads(current[0])
            if current.get('mode') != 'live' or current.get('candidate_id') != args.candidate_id or current.get('identity', {}).get('address', '').lower() != token:
                raise ValueError('candidate identity changed during collection')
            if not any(e['id'] == digest for e in current['evidence']):
                current['evidence'].append(evidence)
            con.execute('UPDATE candidates SET record=? WHERE id=?', (json.dumps(current, ensure_ascii=False), args.candidate_id))
        print(json.dumps({'calls': rpc.calls, 'snapshot': evidence['source'], 'result': result}, ensure_ascii=False))
        return 0
    finally:
        con.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
