"""Offline verification of token-level The Graph history and original VAE artifacts.

This path never calls a provider and never treats tokenDayDatas as pool candles.
"""
from __future__ import annotations
import csv
import datetime as dt
import hashlib
import io
import json
import math
import re
from pathlib import Path

from . import history

SUBGRAPH = '5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV'
QUERY = '''query($token: String!, $start: Int!, $end: Int!, $batch_size: Int!) {
  tokenDayDatas(where: {token: $token, date_gte: $start, date_lt: $end},
    first: $batch_size, orderBy: date, orderDirection: asc) {
    date token { id symbol } priceUSD open high low close totalValueLockedUSD volumeUSD
  }
}'''

def sha(raw): return hashlib.sha256(raw).hexdigest()

def _check_credentials(raw):
    if re.search(rb'(?i)gateway\.thegraph\.com/api/(?!subgraphs/)[^/\s"\x27]{8,}', raw) or re.search(rb'(?i)bearer\s+[A-Za-z0-9._-]{8,}', raw):
        raise ValueError('credential-bearing source artifact rejected')
    return raw

def _read(root, relative, maximum=10_000_000):
    root = Path(root).resolve()
    path = root / relative
    if not isinstance(relative, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', relative): raise ValueError('invalid Graph artifact path')
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root): raise ValueError('Graph artifact missing or unsafe')
    if path.stat().st_size > maximum: raise ValueError('Graph artifact exceeds size limit')
    return _check_credentials(path.read_bytes())

def _json(raw):
    return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite JSON')))

def verify_capture(source_dir, candidate_id):
    """Verify native captured pages and deterministic returns without doing I/O beyond files."""
    chain, address = candidate_id.split(':', 1)
    if history.identity(int(chain), address) != candidate_id or chain != '1': raise ValueError('Graph capture requires canonical Ethereum candidate')
    manifest_raw = _read(source_dir, 'manifest.json'); manifest = _json(manifest_raw)
    if (manifest.get('source') != 'The Graph tokenDayDatas' or manifest.get('chain') != 'ethereum'
            or manifest.get('token_address') != address or manifest.get('subgraph_id') != SUBGRAPH
            or manifest.get('query') != QUERY or manifest.get('price_field') != 'priceUSD'
            or manifest.get('price_units') != 'USD per token'):
        raise ValueError('Graph source, query, price semantics or identity mismatch')
    start = dt.date.fromisoformat(manifest['start_inclusive_utc']); end = dt.date.fromisoformat(manifest['end_exclusive_utc'])
    fetched = dt.datetime.fromisoformat(manifest['fetched_at_utc'].replace('Z', '+00:00'))
    if fetched.tzinfo is None or start >= end or end > fetched.astimezone(dt.timezone.utc).date() or fetched > dt.datetime.now(dt.timezone.utc):
        raise ValueError('Graph closed-day window or fetch time invalid')
    start_ts = int(dt.datetime.combine(start, dt.time(), dt.timezone.utc).timestamp())
    end_ts = int(dt.datetime.combine(end, dt.time(), dt.timezone.utc).timestamp())
    requests = manifest.get('requests')
    if not isinstance(requests, list) or not requests or len(requests) > 200: raise ValueError('Graph pages missing or excessive')
    cursor = start_ts; rows = []; pages = []; total_bytes = 0
    for i, record in enumerate(requests):
        if not isinstance(record, dict): raise ValueError('invalid Graph page metadata')
        variables = record.get('variables')
        stop = min(cursor + 30 * 86400, end_ts)
        if variables != {'token': address, 'start': cursor, 'end': stop, 'batch_size': 1000}: raise ValueError('Graph page/query binding mismatch')
        name = f'graph-response-{i+1:04d}.json'
        if record.get('path') != name: raise ValueError('Graph page order mismatch')
        raw = _read(source_dir, name, 5_000_000)
        total_bytes += len(raw)
        if total_bytes > 50_000_000: raise ValueError('Graph capture exceeds total size limit')
        if sha(raw) != record.get('sha256'): raise ValueError('Graph page digest mismatch')
        page = _json(raw)
        if not isinstance(page, dict) or page.get('errors') or not isinstance(page.get('data'), dict): raise ValueError('GraphQL page failed')
        batch = page['data'].get('tokenDayDatas')
        if not isinstance(batch, list) or len(batch) >= 1000: raise ValueError('Graph page incomplete or invalid')
        for row in batch:
            if not isinstance(row, dict) or not isinstance(row.get('token'), dict) or not isinstance(row['token'].get('id'), str) or row['token']['id'].lower() != address:
                raise ValueError('Graph row identity mismatch')
            timestamp = row.get('date')
            if type(timestamp) is not int or timestamp % 86400 or not cursor <= timestamp < stop: raise ValueError('Graph row date outside requested page')
            try: price = float(row['priceUSD'])
            except (TypeError, ValueError, KeyError, OverflowError): raise ValueError('invalid Graph priceUSD') from None
            if not math.isfinite(price) or price <= 0: raise ValueError('invalid Graph priceUSD')
            rows.append(row)
        pages.append((name, raw, record)); cursor = stop
    if cursor != end_ts: raise ValueError('Graph page window incomplete')
    normalized_raw = _read(source_dir, 'token_daily.json')
    if sha(normalized_raw) != manifest.get('raw_sha256'): raise ValueError('Graph normalized-row digest mismatch')
    normalized = _json(normalized_raw)
    ordered = sorted(rows, key=lambda row: row['date'])
    if normalized != ordered or len(rows) != manifest.get('row_count'): raise ValueError('Graph pages differ from normalized rows')
    dates = [dt.datetime.fromtimestamp(row['date'], dt.timezone.utc).date() for row in ordered]
    if len(set(dates)) != len(dates): raise ValueError('duplicate Graph daily date')
    present = set(dates); missing = [(start + dt.timedelta(days=i)).isoformat() for i in range((end-start).days) if start + dt.timedelta(days=i) not in present]
    if missing != manifest.get('missing_utc_dates'): raise ValueError('Graph missing-day declaration mismatch')
    returns = []
    for previous, current in zip(ordered, ordered[1:]):
        if current['date'] - previous['date'] == 86400:
            returns.append({'date': dt.datetime.fromtimestamp(current['date'], dt.timezone.utc).date().isoformat(), 'return': float(current['priceUSD']) / float(previous['priceUSD']) - 1})
    return {'candidate_id': candidate_id, 'manifest': manifest, 'manifest_raw': manifest_raw,
            'normalized_raw': normalized_raw, 'pages': pages, 'rows': ordered, 'returns': returns,
            'missing': missing, 'status': 'available' if rows else 'empty', 'source_type': 'graph_token_day'}

def verify_model(model_dir, capture, technical_sha256=None):
    """Bind a preserved original VAE run to this Graph capture; never run training."""
    root = Path(model_dir).resolve()
    def safe(relative):
        path = root.joinpath(*relative.split('/'))
        if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent) or not path.is_file() or not path.resolve().is_relative_to(root): raise ValueError('unsafe Graph model artifact')
        if path.stat().st_size > 50_000_000: raise ValueError('Graph model artifact too large')
        return _check_credentials(path.read_bytes())
    manifest_raw = safe('run-manifest.json'); manifest = _json(manifest_raw)
    risk_raw = safe('risk-metrics.json'); returns_raw = safe('output/crypto_returns.csv'); recon_raw = safe('output/vae/VAE_TOKEN.csv')
    if (capture['missing'] or len(capture['returns']) < 2 or manifest.get('candidate_id') != capture['candidate_id']
            or manifest.get('source') != 'The Graph tokenDayDatas token-level USD'
            or manifest.get('source_manifest') != capture['manifest'] or manifest.get('graph_rows_sha256') != sha(capture['normalized_raw'])
            or manifest.get('returns_sha256') != sha(returns_raw) or manifest.get('metrics_sha256') != sha(risk_raw)
            or manifest.get('reconstructions_sha256') != sha(recon_raw) or manifest.get('returns') != len(capture['returns'])
            or manifest.get('reconstructions') != 50): raise ValueError('Graph model provenance or hash mismatch')
    records = list(csv.reader(io.StringIO(returns_raw.decode('utf-8-sig'), newline='')))
    if not records or records[0] != ['datetime', 'TOKEN'] or len(records) != len(capture['returns']) + 1: raise ValueError('Graph return CSV shape mismatch')
    for row, expected in zip(records[1:], capture['returns']):
        if len(row) != 2 or row[0] != expected['date'] or float(row[1]) != expected['return']: raise ValueError('Graph return values do not match captured prices')
    recon = csv.reader(io.StringIO(recon_raw.decode('utf-8-sig'), newline='')); header = next(recon, [])
    if len(header) != 51 or len(set(header)) != 51: raise ValueError('Graph VAE requires 50 distinct reconstruction columns')
    count = 0
    for row in recon:
        if count >= len(capture['returns']): raise ValueError('Graph VAE reconstruction count mismatch')
        if len(row) != 51 or row[0] != capture['returns'][count]['date'] or any(not math.isfinite(float(v)) for v in row[1:]): raise ValueError('Graph VAE reconstruction row mismatch')
        count += 1
        if count > len(capture['returns']): raise ValueError('Graph VAE reconstruction count mismatch')
    if count != len(capture['returns']): raise ValueError('Graph VAE reconstruction count mismatch')
    risk = _json(risk_raw)
    if (not isinstance(risk, dict) or not isinstance(risk.get('var_metrics'), dict) or not isinstance(risk.get('risk_assessment'), dict)
            or type(manifest.get('days')) is not int or manifest['days'] < 1 or risk['var_metrics'].get('time_horizon_days') != manifest['days']):
        raise ValueError('Graph original risk result or horizon mismatch')
    technical = None; technical_raw = None; technical_manifest_raw = None
    if technical_sha256 is not None:
        technical_raw = safe('technical-metrics.json')
        if sha(technical_raw) != technical_sha256: raise ValueError('Graph technical artifact hash mismatch')
        technical_manifest_raw = safe('technical-manifest.json'); technical_manifest = _json(technical_manifest_raw)
        if (technical_manifest.get('candidate_id') != capture['candidate_id'] or technical_manifest.get('technical_metrics_sha256') != sha(technical_raw)
                or technical_manifest.get('reconstructions_sha256') != sha(recon_raw) or technical_manifest.get('legacy_precompute_sha256') != manifest.get('legacy_precompute_sha256')
                or technical_manifest.get('source_manifest_sha256') != sha(manifest_raw)):
            raise ValueError('Graph technical provenance mismatch')
        technical = _json(technical_raw)
        if not isinstance(technical, dict) or not isinstance(technical.get('technical_health'), dict) or not isinstance(technical.get('technical_series'), dict): raise ValueError('Graph technical artifact shape invalid')
    return {'manifest': manifest, 'manifest_raw': manifest_raw, 'risk': risk, 'risk_raw': risk_raw,
            'returns_raw': returns_raw, 'recon_raw': recon_raw, 'technical': technical, 'technical_raw': technical_raw,
            'technical_manifest_raw': technical_manifest_raw}
