"""Bounded case research and frozen-v0.2 report bundle producer.

The backend authenticates admission, owns the durable job and renders HTML/PDF.
This module does not authorize a case. Optional model requests require an explicit
positive budget; remote source requests also default to zero.
"""
from __future__ import annotations

import csv
import base64
import binascii
import datetime as dt
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs

import httpx
from jsonschema import Draft202012Validator

from . import contract_analysis, contract_validate, graph_history, history, model_reasoning
from .legacy_source_port import producer as legacy_producer

PILLARS = ('microstructure', 'onchain', 'fundamentals', 'statistical_risk', 'technical_health')
NETWORKS = {1: ('ethereum', 'eth'), 8453: ('base', 'base')}
EMPTY_WINDOW = {'start': None, 'end': None, 'precision': None}
_ID = re.compile(r'^[A-Za-z0-9_-]{1,120}$')


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _number(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _replay_sources(snapshot: dict, candidate_id: str, input_mode: str):
    """Validate the backend's immutable discovery record and path→base64 snapshot."""
    if not isinstance(snapshot, dict) or set(snapshot) != {'record', 'evidence'}:
        raise ValueError('captured snapshot requires record and evidence')
    record, files = snapshot['record'], snapshot['evidence']
    if not isinstance(record, dict) or not isinstance(files, dict) or len(files) > 100:
        raise ValueError('invalid captured snapshot')
    schema = json.loads((Path(__file__).resolve().parents[2] / 'schemas' / 'candidate.schema.json').read_bytes())
    Draft202012Validator(schema).validate(record)
    identity = record['identity']; chain = identity['chain_id']; address = identity['address'].lower()
    if (record['candidate_id'] != candidate_id or f'{chain}:{address}' != candidate_id
            or record['mode'] != input_mode):
        raise ValueError('captured candidate identity or mode mismatch')
    refs = {}
    for e in record['evidence']:
        name, sha = e.get('source'), e.get('sha256')
        if not isinstance(name, str) or not re.fullmatch(r'snapshots/[0-9a-f]{64}\.json', name) or e.get('id') != sha or name != f'snapshots/{sha}.json':
            continue
        if name in refs:
            raise ValueError('duplicate captured evidence reference')
        refs[name] = e
    if not set(files) <= set(refs):
        raise ValueError('captured bytes lack a candidate evidence reference')
    network, gecko = NETWORKS[chain]; captured = {}; ignored = []; total = 0
    for name, encoded in sorted(files.items()):
        if not isinstance(encoded, str) or len(encoded) > 7_000_000:
            raise ValueError('invalid or oversized captured evidence')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('invalid captured evidence encoding') from None
        total += len(raw); e = refs[name]
        if total > 5_000_000 or _sha(raw) != e['sha256']:
            raise ValueError('captured evidence byte limit or digest mismatch')
        allowed_kind = {'live': {'live_observation'}, 'historical_replay': {'historical_fixture', 'live_observation'},
                        'synthetic_demo': {'synthetic'}}[input_mode]
        if e.get('kind') not in allowed_kind:
            ignored.append({'sha256': e['sha256'], 'reason': 'evidence_kind_incompatible_with_candidate_mode'}); continue
        if b'reddit' in raw.lower() or b'redd.it' in raw.lower():
            raise ValueError('social content cannot enter immutable replay bundles')
        try:
            doc = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite JSON')))
        except (ValueError, TypeError):
            raise ValueError('captured evidence is not valid JSON') from None
        limits = e.get('limitations', [])
        urls = [x[len('Request URL: '):] for x in limits if isinstance(x, str) and x.startswith('Request URL: ')]
        if len(urls) != 1:
            ignored.append({'sha256': e['sha256'], 'reason': 'unsupported_or_missing_source_url'}); continue
        url = urls[0]
        try:
            parsed = urlsplit(url); params = parse_qs(parsed.query, keep_blank_values=True)
        except ValueError:
            ignored.append({'sha256': e['sha256'], 'reason': 'invalid_source_url'}); continue
        if parsed.scheme != 'https' or parsed.fragment or parsed.username or parsed.password:
            ignored.append({'sha256': e['sha256'], 'reason': 'untrusted_source_url'}); continue
        path = parsed.path.lower(); host = parsed.netloc.lower(); kind = None; meta = {}
        if host == 'api.dexscreener.com' and path == f'/token-pairs/v1/{network}/{address}' and not params:
            kind = 'market'
        elif host == 'api.gopluslabs.io' and path == f'/api/v1/token_security/{chain}' and params == {'contract_addresses': [address]}:
            kind = 'security'
        elif host == 'api.honeypot.is' and path == '/v2/ishoneypot' and params == {'address': [address], 'chainID': [str(chain)]}:
            kind = 'honeypot_is'
        elif host == 'sourcify.dev' and path == f'/server/v2/contract/{chain}/{address}' and params in ({}, {'fields': ['all']}):
            kind = 'source'
        elif host == 'api.geckoterminal.com' and path in (f'/api/v2/networks/{gecko}/new_pools', f'/api/v2/networks/{gecko}/tokens/{address}/pools') and params in ({}, {'page': ['1']}):
            kind = 'pools'
        elif host == 'api.geckoterminal.com':
            match = re.fullmatch(f'/api/v2/networks/{gecko}/pools/(0x(?:[0-9a-f]{{40}}|[0-9a-f]{{64}}))/ohlcv/day', path)
            if (match and set(params) <= {'aggregate', 'limit', 'currency', 'token', 'include_empty_intervals'}
                    and params.get('token') in (['base'], ['quote']) and params.get('currency') == ['usd']
                    and params.get('aggregate') == ['1'] and params.get('include_empty_intervals') == ['false']):
                kind = 'daily'; meta = {'pool': match.group(1), 'side': params['token'][0]}
        if not kind:
            ignored.append({'sha256': e['sha256'], 'reason': 'unsupported_source_or_identity'}); continue
        fetched = e.get('fetched_at')
        observed = e.get('observed_at')
        order_time = -1.0
        if fetched is not None:
            try:
                t = dt.datetime.fromisoformat(fetched.replace('Z', '+00:00'))
                if t.tzinfo is None or t.utcoffset() is None or t > dt.datetime.now(dt.timezone.utc):
                    raise ValueError('invalid capture time')
                order_time = t.timestamp()
            except (ValueError, TypeError, AttributeError):
                raise ValueError('captured evidence has invalid or future fetched_at') from None
        if observed is not None:
            try:
                t = dt.datetime.fromisoformat(observed.replace('Z', '+00:00'))
                if t.tzinfo is None or t.utcoffset() is None or t > dt.datetime.now(dt.timezone.utc):
                    raise ValueError('invalid observation time')
            except (ValueError, TypeError, AttributeError):
                raise ValueError('captured evidence has invalid or future observed_at') from None
        rec = {'name': kind, 'url': url, 'status': 'captured', 'fetched_at': fetched, 'observed_at': e.get('observed_at'),
               'block_number': e.get('block_number'), 'sha256': e['sha256'], 'origin_snapshot_id': e['id'],
               'transport_mode': 'captured_snapshot', 'evidence_mode': 'historical_replay', '_order_time': order_time, **meta}
        old = captured.get(kind)
        if old is None or (order_time, e['sha256']) > (old[2]['_order_time'], old[2]['sha256']):
            captured[kind] = (doc, raw, rec)
    return captured, ignored


def _legacy_model(model_dir: Path, candidate: str, daily_sha256: str | None):
    """Verify the actual 50-column run and its identity/candle hashes before using it."""
    root = Path(model_dir).resolve()
    paths = [root / 'run-manifest.json', root / 'legacy-metrics.json', root / 'output' / 'vae' / 'VAE_TOKEN.csv']
    for path in paths:
        if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
            raise ValueError('legacy model evidence missing or unsafe')
    manifest = json.loads(paths[0].read_bytes()); metrics = json.loads(paths[1].read_bytes())
    if (manifest.get('candidate_id') != candidate or metrics.get('identity') != candidate
            or manifest.get('reconstructions') != 50 or not daily_sha256
            or manifest.get('source_candles_sha256') != daily_sha256
            or manifest.get('metrics_sha256') != _sha(paths[1].read_bytes())
            or manifest.get('reconstructions_sha256') != _sha(paths[2].read_bytes())):
        raise ValueError('legacy model candidate, reconstruction count, candle or output hash mismatch')
    with paths[2].open(encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f); header = next(reader, []); rows = 0
        if len(header) != 51 or len(set(header)) != 51:
            raise ValueError('legacy reconstruction CSV must contain timestamp and 50 distinct series')
        for row in reader:
            rows += 1
            if len(row) != 51 or not row[0] or any(_number(v) is None for v in row[1:]):
                raise ValueError('invalid legacy reconstruction row')
        if not rows:
            raise ValueError('legacy reconstruction CSV has no observations')
    return manifest, metrics, [path.read_bytes() for path in paths]


def run_case(case: dict, output_dir: str | Path, *, max_source_requests: int = 0,
             transport: httpx.BaseTransport | None = None, legacy_model_dir: str | Path | None = None,
             pinned_contract_capture: dict | None = None, legacy_capture_root: str | Path | None = None,
             legacy_records: dict | None = None, vae_config: dict | None = None,
             vae_runner=None, captured_snapshot: dict | None = None, cancelled=None,
             max_model_calls: int = 0, model_client=None, max_model_output_tokens: int = 4096,
             max_model_context_chars: int = 120000, stage_callback=None, reasoning_checkpoint: dict | None = None,
             graph_capture_dir: str | Path | None = None, graph_model_dir: str | Path | None = None,
             graph_technical_sha256: str | None = None) -> dict:
    """Research one backend-authorized case and atomically assemble a report bundle.

    `case` contains case_id, run_id, candidate_id, mode and an authorization reference
    with route `automatic_policy` or `world_confirmed` and reference_id. This validates
    shape, not authorization. The backend must verify/consume authorization before calling.
    `max_source_requests` bounds all HTTP GET attempts; default zero makes no source call.
    `captured_snapshot` accepts the backend's immutable record and base64 evidence; it
    requires a zero source budget, makes no HTTP calls and preserves source timestamps.
    Inject MockTransport for synthetic network tests. Retry uses a new output directory.
    Optional Terra reasoning defaults to zero calls; see docs/terra-case-reasoning.md
    for durable budget, callback and trusted checkpoint responsibilities.
    """
    case_id, run_id, candidate_id = case.get('case_id'), case.get('run_id'), case.get('candidate_id')
    if not all(isinstance(x, str) and _ID.fullmatch(x) for x in (case_id, run_id)):
        raise ValueError('case and run IDs must be bounded safe identifiers')
    try:
        chain_text, address = candidate_id.split(':', 1); chain = int(chain_text)
        canonical = history.identity(chain, address)
    except (AttributeError, TypeError, ValueError):
        raise ValueError('supported canonical chain:address candidate required') from None
    if canonical != candidate_id:
        raise ValueError('candidate ID must be canonical lowercase')
    auth = case.get('authorization', {})
    if (not isinstance(auth, dict) or auth.get('route') not in ('automatic_policy', 'world_confirmed')
            or not isinstance(auth.get('reference_id'), str) or not _ID.fullmatch(auth['reference_id'])):
        raise ValueError('backend authorization route and reference required')
    mode = case.get('mode', 'live')
    if mode not in ('live', 'synthetic_demo', 'historical_replay'):
        raise ValueError('invalid evidence mode')
    if isinstance(max_source_requests, bool) or not isinstance(max_source_requests, int) or not 0 <= max_source_requests <= 5:
        raise ValueError('source request budget must be an integer between zero and five')
    if captured_snapshot is not None and (max_source_requests != 0 or transport is not None):
        raise ValueError('captured replay requires zero source budget and no HTTP transport')
    if mode != 'live' and transport is None and max_source_requests:
        raise ValueError('synthetic or historical mode requires injected source transport')
    if graph_model_dir is not None and (graph_capture_dir is None or legacy_model_dir is not None or vae_config is not None):
        raise ValueError('Graph model requires Graph capture and cannot be combined with another VAE input')
    if graph_technical_sha256 is not None and (graph_model_dir is None or not re.fullmatch(r'[0-9a-f]{64}', graph_technical_sha256)):
        raise ValueError('Graph technical artifact requires its model and exact SHA-256')
    if vae_config is not None:
        if legacy_model_dir is not None or not isinstance(vae_config, dict):
            raise ValueError('choose either legacy model artifacts or an explicit VAE execution configuration')
        if (not isinstance(vae_config.get('legacy_repo'), (str, Path)) or isinstance(vae_config.get('days'), bool)
                or not isinstance(vae_config.get('days'), int) or vae_config['days'] < 1):
            raise ValueError('VAE execution requires a legacy repository and explicit positive horizon in days')
    if isinstance(max_model_calls, bool) or not isinstance(max_model_calls, int) or max_model_calls not in (0, 1):
        raise ValueError('model call budget must be zero or one')
    output = Path(output_dir).resolve()
    if output.exists():
        raise ValueError('output already exists; retry with a new run directory')
    if not output.parent.is_dir():
        raise ValueError('output parent must already exist')
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    attempts = []; captured = {}; stops = []; replay_ignored = []; network, gecko = NETWORKS[chain]
    model_reasoning._emit(stage_callback, {'stage': 'sources', 'state': 'started',
                                           'mode': 'captured_replay' if captured_snapshot is not None else 'bounded_fetch'})
    if cancelled and cancelled():
        return {'state': 'cancelled', 'bundle_path': None, 'case_id': case_id, 'run_id': run_id,
                'source_attempts': attempts, 'reason': 'cancelled_before_source_read'}
    if captured_snapshot is not None:
        captured, replay_ignored = _replay_sources(captured_snapshot, candidate_id, mode)
        for name in captured:
            model_reasoning._emit(stage_callback, {'stage': 'source', 'name': name, 'state': 'captured_replay'})
        mode = 'synthetic_demo' if mode == 'synthetic_demo' else 'historical_replay'
        market, security, source, pools = (captured.get(k, (None,))[0] for k in ('market', 'security', 'source', 'pools'))
        chosen = None; candles = None
        if isinstance(pools, dict):
            try:
                chosen, _ = history.select_pool(pools, chain, address)
            except (ValueError, KeyError, TypeError, AttributeError):
                stops.append('no_identity_matched_pool')
        if 'daily' in captured:
            daily_rec = captured['daily'][2]
            if chosen and (daily_rec['pool'], daily_rec['side']) == (chosen['address'], chosen['side']):
                candles = captured['daily'][0]
            else:
                stops.append('captured_daily_pool_or_side_mismatch'); captured.pop('daily')
    else:
      with httpx.Client(transport=transport, timeout=15, follow_redirects=False, headers={'User-Agent': 'ScoobyDAO-research/1.0'}) as client:
        def fetch(name, url):
            if cancelled and cancelled():
                stops.append('cancelled'); return None
            if len(attempts) >= max_source_requests:
                stops.append('source_request_budget_exhausted')
                model_reasoning._emit(stage_callback, {'stage': 'source', 'name': name, 'state': 'skipped_budget'})
                return None
            record = {'name': name, 'url': url, 'status': 'unavailable', 'fetched_at': None,
                      'transport_mode': 'injected_transport' if transport is not None else 'direct_http', 'evidence_mode': mode}
            attempts.append(record)
            try:
                response = client.get(url); record['http_status'] = response.status_code
                response.raise_for_status()
                raw = response.content
                if len(raw) > 10_000_000:
                    raise ValueError('response too large')
                doc = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite JSON')))
                record.update(status='captured', fetched_at=dt.datetime.now(dt.timezone.utc).isoformat() if mode == 'live' else None, sha256=_sha(raw))
                captured[name] = (doc, raw, record)
                model_reasoning._emit(stage_callback, {'stage': 'source', 'name': name, 'state': 'captured'})
                return doc
            except (httpx.HTTPError, ValueError, TypeError):
                record['status'] = 'unavailable'; record['reason'] = 'source_http_transport_or_format_failure'
                model_reasoning._emit(stage_callback, {'stage': 'source', 'name': name, 'state': 'unavailable'})
                return None

        market = fetch('market', f'https://api.dexscreener.com/token-pairs/v1/{network}/{address}')
        security = fetch('security', f'https://api.gopluslabs.io/api/v1/token_security/{chain}?'+urlencode({'contract_addresses': address}))
        source = fetch('source', f'https://sourcify.dev/server/v2/contract/{chain}/{address}?fields=all')
        pools = fetch('pools', f'https://api.geckoterminal.com/api/v2/networks/{gecko}/tokens/{address}/pools?page=1')
        chosen = None; candles = None
        if isinstance(pools, dict):
            try:
                chosen, _ = history.select_pool(pools, chain, address)
            except (ValueError, KeyError, TypeError, AttributeError):
                stops.append('no_identity_matched_pool')
        if chosen:
            url = f'https://api.geckoterminal.com/api/v2/networks/{gecko}/pools/{chosen["address"]}/ohlcv/day?'+urlencode({'aggregate': 1, 'limit': 1000, 'currency': 'usd', 'token': chosen['side'], 'include_empty_intervals': 'false'})
            candles = fetch('daily', url)
    if 'cancelled' in stops:
        model_reasoning._emit(stage_callback, {'stage': 'sources', 'state': 'cancelled'})
        return {'state': 'cancelled', 'bundle_path': None, 'case_id': case_id, 'run_id': run_id,
                'source_attempts': attempts, 'reason': 'cancelled_before_bundle_commit'}
    model_reasoning._emit(stage_callback, {'stage': 'sources', 'state': 'completed', 'attempts': len(attempts), 'captured': len(captured)})

    # Reject an unrelated/malformed response as a source for this candidate.
    valid = {}
    pair = None
    if isinstance(market, list):
        pair = next((x for x in market if isinstance(x, dict) and str(x.get('chainId', '')).lower() == network
                     and isinstance(x.get('baseToken'), dict) and str(x['baseToken'].get('address', '')).lower() == address), None)
        if pair: valid['market'] = captured['market']
    sec = security.get('result', {}).get(address) if (isinstance(security, dict) and security.get('code') in (1, '1')
        and isinstance(security.get('result'), dict)) else None
    if isinstance(sec, dict) and sec: valid['security'] = captured['security']
    honeypot = captured.get('honeypot_is', (None,))[0]
    if isinstance(honeypot, dict):
        token_info = honeypot.get('token'); chain_info = honeypot.get('chain'); pair_info = honeypot.get('pair')
        pair_info = pair_info.get('pair') if isinstance(pair_info, dict) else None
        scan = honeypot.get('honeypotResult')
        # If the provider returns pair token details, require them to agree with
        # the selected GeckoTerminal pool relationship, not just its ID.
        pair_tokens_match = True
        if isinstance(pair_info, dict) and ('token0' in pair_info or 'token1' in pair_info):
            actual = [pair_info.get('token0'), pair_info.get('token1')]
            pool_row = next((row for row in pools.get('data', []) if isinstance(row, dict)
                             and isinstance(row.get('attributes'), dict)
                             and str(row['attributes'].get('address', '')).lower() == chosen['address']), None) if chosen and isinstance(pools, dict) else None
            rel = pool_row.get('relationships', {}) if isinstance(pool_row, dict) else {}
            provider_tokens = [rel.get(side, {}).get('data', {}).get('id') for side in ('base_token', 'quote_token')] if isinstance(rel, dict) else []
            pair_tokens_match = (len(provider_tokens) == 2 and all(isinstance(x, str) and x.startswith(gecko+'_') for x in provider_tokens)
                                 and all(isinstance(x, str) for x in actual)
                                 and {x.lower() for x in actual} == {x[len(gecko)+1:].lower() for x in provider_tokens})
        if (isinstance(token_info, dict) and isinstance(token_info.get('address'), str)
                and token_info['address'].lower() == address and isinstance(chain_info, dict) and str(chain_info.get('id')) == str(chain)
                and isinstance(pair_info, dict) and isinstance(pair_info.get('address'), str) and chosen
                and pair_info['address'].lower() == chosen['address'] and pair_tokens_match and isinstance(scan, dict) and type(scan.get('isHoneypot')) is bool
                and type(honeypot.get('simulationSuccess')) is bool):
            valid['honeypot_is'] = captured['honeypot_is']
        else:
            honeypot = None; stops.append('honeypot_provider_identity_or_selected_pool_mismatch')
    if isinstance(source, dict) and str(source.get('address', '')).lower() == address and str(source.get('chainId')) == str(chain):
        valid['source'] = captured['source']
    graph_capture = None; graph_model = None; graph_summary = None
    if graph_capture_dir is not None:
        graph_capture = graph_history.verify_capture(Path(graph_capture_dir), candidate_id)
        graph_summary = {'source_type': 'graph_token_day', 'subgraph_id': graph_history.SUBGRAPH,
            'start_inclusive_utc': graph_capture['manifest']['start_inclusive_utc'], 'end_exclusive_utc': graph_capture['manifest']['end_exclusive_utc'],
            'fetched_at_utc': graph_capture['manifest']['fetched_at_utc'], 'rows': len(graph_capture['rows']),
            'missing_days': len(graph_capture['missing']), 'status': graph_capture['status'],
            'limitation': 'Token-level subgraph result; not selected-pool or market-wide coverage.'}
        if not graph_capture['rows']: stops.append('graph_token_day_zero_rows_for_selected_source_and_window')
        if graph_model_dir is not None:
            graph_model = graph_history.verify_model(Path(graph_model_dir), graph_capture, graph_technical_sha256)
        if not attempts and mode != 'synthetic_demo': mode = 'historical_replay'
        model_reasoning._emit(stage_callback, {'stage': 'source', 'name': 'graph_token_day',
                                               'state': 'captured_replay', 'rows': len(graph_capture['rows'])})
    daily_prepared = None; gecko_row = None
    if chosen:
        valid['pools'] = captured['pools']
        gecko_row = next((p for p in pools.get('data', []) if isinstance(p, dict)
                          and isinstance(p.get('attributes'), dict)
                          and str(p['attributes'].get('address', '')).lower() == chosen['address']), None)
    if chosen and isinstance(candles, dict):
        try:
            daily_prepared = history.prepare(candles, dt.datetime.now(dt.timezone.utc).date().isoformat())
            valid['daily'] = captured['daily']
        except (ValueError, KeyError, TypeError, OverflowError, OSError):
            stops.append('invalid_daily_candles')
    if pinned_contract_capture is not None:
        try:
            analysis = contract_analysis.analyze({'chain_id': chain, 'address': address}, pinned_contract_capture)
        except (ValueError, KeyError, TypeError):
            analysis = None; stops.append('pinned_contract_capture_rejected')
    else:
        analysis = None
    legacy = None
    if legacy_records is not None or legacy_capture_root is not None:
        try:
            if not legacy_capture_root or not isinstance(legacy_records, dict) or not set(legacy_records) <= {'microstructure', 'onchain'}:
                raise ValueError('only identity-bound legacy microstructure/onchain captures are supported')
            legacy = legacy_producer.run_captured({'candidate_id': candidate_id}, legacy_capture_root, legacy_records)
            # Re-read only paths independently verified by load_capture; no arbitrary source paths are trusted.
            legacy_inputs = {name: (Path(legacy_capture_root) / record['path']).read_bytes() for name, record in legacy_records.items()}
        except (ValueError, KeyError, TypeError, OSError):
            legacy = None; stops.append('legacy_pillar_capture_rejected')
    if not valid and not (graph_capture and graph_capture['rows']) and analysis is None and not (legacy and any(legacy[k]['status'] == 'partial' for k in ('microstructure', 'onchain'))):
        model_reasoning._emit(stage_callback, {'stage': 'report', 'state': 'blocked', 'reason': 'no_identity_bound_source_evidence'})
        return {'state': 'blocked', 'bundle_path': None, 'case_id': case_id, 'run_id': run_id,
                'source_attempts': attempts, 'reason': 'no_identity_bound_source_evidence',
                'replay_sources': 0, 'replay_ignored': replay_ignored, 'graph_capture': graph_summary, 'limitations': stops}

    model = None
    if graph_model is not None:
        tech = graph_model['technical'] or {'technical_health': {}, 'technical_series': {}}
        wrapped = {'identity': candidate_id, 'risk_assessment': graph_model['risk'],
                   'technical_health': tech['technical_health'], 'technical_series': tech['technical_series']}
        wrapped_raw = _bytes(wrapped)
        graph_manifest = {'candidate_id': candidate_id, 'source_type': 'graph_token_day',
            'source_candles_sha256': graph_history.sha(graph_capture['normalized_raw']),
            'reconstructions': 50, 'return_rows': len(graph_capture['returns']),
            'metrics_sha256': _sha(wrapped_raw), 'reconstructions_sha256': _sha(graph_model['recon_raw']),
            'graph_run_manifest_sha256': _sha(graph_model['manifest_raw']),
            'graph_technical_sha256': graph_technical_sha256,
            'limitations': ['Token-level Graph priceUSD, not selected-pool candles.',
                            'Provider history, legacy reconstruction calibration and sample adequacy are not independently established.']}
        model = (graph_manifest, wrapped, [_bytes(graph_manifest), wrapped_raw, graph_model['recon_raw']])
    elif legacy_model_dir is not None:
        try:
            model = _legacy_model(Path(legacy_model_dir), candidate_id, valid.get('daily', (None, None, {}))[2].get('sha256'))
        except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError):
            stops.append('legacy_50_reconstruction_evidence_rejected')
    elif vae_config is not None:
        if not daily_prepared or daily_prepared['gaps'] or len(daily_prepared['returns']) < 2:
            stops.append('legacy_vae_pending_insufficient_or_gapped_history')
        elif cancelled and cancelled():
            return {'state': 'cancelled', 'bundle_path': None, 'case_id': case_id, 'run_id': run_id,
                    'source_attempts': attempts, 'reason': 'cancelled_before_vae'}
        else:
            try:
                with tempfile.TemporaryDirectory(prefix='.case-vae-', dir=output.parent) as scratch:
                    scratch = Path(scratch); source_dir = scratch / 'source'; source_dir.mkdir()
                    (source_dir / 'pools.json').write_bytes(valid['pools'][1]); (source_dir / 'daily.json').write_bytes(valid['daily'][1])
                    (source_dir / 'returns.json').write_bytes(_bytes(daily_prepared))
                    source_status = {'candidate_id': candidate_id, 'pool': chosen,
                        'history': {'cutoff_utc_date': daily_prepared['cutoff_utc_date']},
                        'requests': [{'path': name + '.json', 'sha256': valid[name][2]['sha256']} for name in ('pools', 'daily')]}
                    (source_dir / 'source-status.json').write_bytes(_bytes(source_status))
                    if vae_runner is None:
                        from .legacy_vae import run as vae_runner
                    model_dir = scratch / 'model'
                    vae_runner(source_dir, model_dir, vae_config['days'], Path(vae_config['legacy_repo']))
                    model = _legacy_model(model_dir, candidate_id, valid['daily'][2]['sha256'])
            except (ValueError, KeyError, TypeError, OSError, RuntimeError, ImportError):
                stops.append('legacy_vae_execution_failed')
    report_id = 'case-' + case_id; version = 'run-' + run_id
    symbol = str(pair.get('baseToken', {}).get('symbol') or 'UNKNOWN')[:80] if pair else 'UNKNOWN'
    if symbol == 'UNKNOWN' and graph_capture and graph_capture['rows']:
        graph_symbols = {row['token'].get('symbol') for row in graph_capture['rows'] if isinstance(row['token'].get('symbol'), str)}
        if len(graph_symbols) == 1:
            graph_symbol = next(iter(graph_symbols))
            if re.fullmatch(r'[A-Za-z0-9 ._-]{1,40}', graph_symbol): symbol = graph_symbol
    if symbol == 'UNKNOWN' and isinstance(candles, dict) and isinstance(candles.get('meta'), dict):
        for token in candles['meta'].values():
            if isinstance(token, dict) and str(token.get('address', '')).lower() == address and token.get('symbol'):
                symbol = str(token['symbol'])[:80]; break
    pillars = {p: {'status': 'unavailable', 'summary': 'Required source evidence was not available.', 'evidence_ids': [],
                   'measurements': [], 'series': [], 'claims': [], 'quality_issues': [], 'raw_payload_path': None} for p in PILLARS}
    evidence = []; ledger = []
    with tempfile.TemporaryDirectory(prefix='.case-research-', dir=output.parent) as temp:
        root = Path(temp); (root / 'evidence').mkdir()
        def add_evidence(name, raw, record, kind='live_observation'):
            rel = f'evidence/{name}.json'; (root / rel).write_bytes(raw)
            evidence.append({'id': name, 'path': rel, 'sha256': _sha(raw), 'kind': kind,
                'observed_at': record.get('observed_at'), 'fetched_at': record.get('fetched_at'), 'block_number': record.get('block_number'),
                'window': dict(EMPTY_WINDOW), 'coverage': 'Bounded identity-checked source response.',
                'limitations': ['Provider response and identity assertions require independent verification.']})
            ledger.append({'id': name, 'url': record.get('url'), 'fetched_at': record.get('fetched_at'),
                           'sha256': _sha(raw), 'origin_snapshot_id': record.get('origin_snapshot_id'),
                           'transport_mode': record.get('transport_mode')})
        if graph_capture is not None:
            def graph_evidence(identifier, relative, raw, coverage, kind):
                target = root / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
                evidence.append({'id': identifier, 'path': relative, 'sha256': _sha(raw), 'kind': kind,
                    'observed_at': None, 'fetched_at': graph_capture['manifest']['fetched_at_utc'] if kind != 'derived' else None, 'block_number': None,
                    'window': dict(EMPTY_WINDOW), 'coverage': coverage,
                    'limitations': ['Token-level Graph subgraph data, not a selected-pool candle; source truth and completeness require independent verification.']})
            graph_kind = 'synthetic' if mode == 'synthetic_demo' else 'historical_observation'
            graph_evidence('graph_source_manifest', 'evidence/graph/manifest.json', graph_capture['manifest_raw'], 'Graph tokenDayDatas capture and query metadata.', graph_kind)
            graph_evidence('graph_token_daily', 'evidence/graph/token_daily.json', graph_capture['normalized_raw'], 'Normalized rows from the retained Graph pages.', graph_kind)
            for index, (name, raw, record) in enumerate(graph_capture['pages']):
                graph_evidence(f'graph_page_{index+1:04d}', 'evidence/graph/' + name, raw, 'Exact captured GraphQL response page.', graph_kind)
            ledger.append({'id': 'graph_token_daily', 'url': 'https://gateway.thegraph.com/api/subgraphs/id/' + graph_history.SUBGRAPH,
                           'fetched_at': graph_capture['manifest']['fetched_at_utc'], 'sha256': _sha(graph_capture['normalized_raw']),
                           'origin_snapshot_id': None, 'transport_mode': 'captured_replay'})
            if graph_model is not None:
                for identifier, relative, raw in (
                    ('graph_model_manifest', 'evidence/graph_model/run-manifest.json', graph_model['manifest_raw']),
                    ('graph_model_risk', 'evidence/graph_model/risk-metrics.json', graph_model['risk_raw']),
                    ('graph_model_returns', 'evidence/graph_model/output/crypto_returns.csv', graph_model['returns_raw']),
                    ('graph_model_reconstructions', 'evidence/graph_model/output/vae/VAE_TOKEN.csv', graph_model['recon_raw'])):
                    graph_evidence(identifier, relative, raw, 'Original Graph-backed VAE run artifact.', 'derived')
                if graph_model['technical'] is not None:
                    graph_evidence('graph_technical_manifest', 'evidence/graph_model/technical-manifest.json', graph_model['technical_manifest_raw'], 'Supplemental original technical provenance.', 'derived')
                    graph_evidence('graph_technical_metrics', 'evidence/graph_model/technical-metrics.json', graph_model['technical_raw'], 'Original technical metrics from preserved reconstructions.', 'derived')
        for name, (_, raw, rec) in valid.items():
            kind = {'synthetic_demo': 'synthetic', 'historical_replay': 'historical_observation', 'live': 'live_observation'}[mode]
            add_evidence(name, raw, rec, kind)
        if analysis is not None:
            add_evidence('contract_analysis', _bytes(analysis), {'url': None, 'fetched_at': started}, 'derived')
            evidence_input = {k: pinned_contract_capture[k] for k in ('chain_id', 'address', 'block', 'runtime_hex', 'source', 'proxy') if k in pinned_contract_capture}
            add_evidence('pinned_contract_capture', _bytes(evidence_input), {'url': None, 'fetched_at': started}, 'derived')
        if legacy:
            for name, raw in legacy_inputs.items():
                add_evidence('legacy_' + name + '_input', raw, {'url': None, 'fetched_at': started}, 'derived')
                add_evidence('legacy_' + name + '_result', _bytes(legacy[name]), {'url': None, 'fetched_at': started}, 'derived')
        if model:
            manifest, metrics, files = model
            add_evidence('legacy_manifest', files[0], {'url': None, 'fetched_at': started}, 'derived')
            add_evidence('legacy_metrics', files[1], {'url': None, 'fetched_at': started}, 'derived')
            # CSV is retained as CSV, not mislabelled JSON.
            csv_path = root / 'evidence' / 'legacy_reconstructions.csv'; csv_path.write_bytes(files[2])
            evidence.append({'id': 'legacy_reconstructions', 'path': 'evidence/legacy_reconstructions.csv', 'sha256': _sha(files[2]),
                'kind': 'derived', 'observed_at': None, 'fetched_at': started, 'block_number': None,
                'window': dict(EMPTY_WINDOW), 'coverage': 'Original 50-reconstruction output.',
                'limitations': ['Legacy model calibration is not independently verified.']})
        def claim(p, identifier, text, evidence_id, limitation):
            v = pillars[p]; v['status'] = 'partial'; v['evidence_ids'] = sorted(set(v['evidence_ids'] + [evidence_id]))
            v['claims'].append({'id': identifier, 'statement': text, 'kind': 'observation',
                'supporting_evidence_ids': [evidence_id], 'counterevidence_ids': [], 'contradiction_claim_ids': [], 'uncertainties': [limitation]})
        def measurement(p, identifier, value, unit, evidence_id, method):
            n = _number(value)
            if n is None: return
            v = pillars[p]; v['status'] = 'partial'; v['evidence_ids'] = sorted(set(v['evidence_ids'] + [evidence_id]))
            v['measurements'].append({'id': identifier, 'value': n, 'unit': unit, 'method': method,
                'quality': 'unvalidated', 'evidence_ids': [evidence_id], 'window': dict(EMPTY_WINDOW), 'unknown_reason': None})
        if pair:
            pool = pair.get('pairAddress', 'unknown')
            claim('microstructure', 'market-pool', f'The market provider returned an identity-matched base-token pool {pool}.', 'market', 'A provider snapshot is not executable market-wide liquidity.')
            liquidity = pair.get('liquidity') if isinstance(pair.get('liquidity'), dict) else {}
            volume = pair.get('volume') if isinstance(pair.get('volume'), dict) else {}
            measurement('microstructure', 'liquidity_usd', liquidity.get('usd'), 'USD', 'market', 'DEX Screener reported pool liquidity snapshot')
            measurement('microstructure', 'volume_24h_usd', volume.get('h24'), 'USD', 'market', 'DEX Screener reported 24-hour pool volume')
            measurement('microstructure', 'price_usd', pair.get('priceUsd'), 'USD per token', 'market', 'DEX Screener reported token price snapshot')
            txns = pair.get('txns') if isinstance(pair.get('txns'), dict) else {}
            daily_txns = txns.get('h24') if isinstance(txns.get('h24'), dict) else {}
            for field in ('buys', 'sells'):
                measurement('microstructure', 'provider_24h_' + field, daily_txns.get(field), 'provider-reported transactions', 'market', 'DEX Screener reported 24-hour pool transactions; not a holder-specific execution test')
            changes = pair.get('priceChange') if isinstance(pair.get('priceChange'), dict) else {}
            measurement('microstructure', 'provider_price_change_24h', changes.get('h24'), 'percent', 'market', 'DEX Screener reported 24-hour pool price change')
            claim('fundamentals', 'market-symbol', f'The market provider identifies the base token symbol as {symbol}.', 'market', 'Ticker alone does not establish project identity or social attribution.')
        elif gecko_row:
            attrs = gecko_row['attributes']
            pool_kind = 'provider-reported Uniswap v4 pool ID' if chosen.get('identifier_type') == 'provider_reported_uniswap_v4_pool_id' else 'pool'
            claim('microstructure', 'gecko-pool', f'GeckoTerminal returned an identity-matched {chosen["side"]}-token {pool_kind} {chosen["address"]}.', 'pools', 'A provider snapshot is not independently verified or executable market-wide liquidity.')
            measurement('microstructure', 'liquidity_usd', attrs.get('reserve_in_usd'), 'USD', 'pools', 'GeckoTerminal reported pool reserve snapshot')
            volume = attrs.get('volume_usd') if isinstance(attrs.get('volume_usd'), dict) else {}
            measurement('microstructure', 'volume_24h_usd', volume.get('h24'), 'USD', 'pools', 'GeckoTerminal reported 24-hour pool volume')
            if symbol != 'UNKNOWN' and 'daily' in valid:
                claim('fundamentals', 'gecko-symbol', f'The candle provider identifies the token symbol as {symbol}.', 'daily', 'Ticker alone does not establish project identity or social attribution.')
        if sec:
            # Exact bounded provider assertions: source attribution is not proof of
            # executable fees, address ownership, or locked balances. Values remain
            # decimal strings to avoid losing precision in financial source data.
            def source_decimal(value):
                value = str(value)
                return value if re.fullmatch(r'-?(?:0|[1-9][0-9]{0,29})(?:\.[0-9]{1,40})?', value) else None
            def source_address(value):
                return value.lower() if isinstance(value, str) and re.fullmatch(r'0x(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', value) else None
            entries = sec.get('dex') if isinstance(sec.get('dex'), list) else []
            for index, row in enumerate(entries[:20]):
                if not isinstance(row, dict): continue
                address_field = source_address(row.get('pair'))
                fee = source_decimal(row.get('pool_fee'))
                liquidity = source_decimal(row.get('liquidity'))
                if address_field and (fee is not None or liquidity is not None):
                    parts = [f'The security provider reports pool {address_field}']
                    if fee is not None: parts.append(f'pool_fee = {fee}')
                    if liquidity is not None: parts.append(f'liquidity = {liquidity} (provider units unspecified)')
                    claim('microstructure', f'provider-pool-{index+1}', '; '.join(parts) + '.', 'security',
                          'Provider pool listing, fee and liquidity require independent pool-state and route verification.')
            entries = sec.get('holders') if isinstance(sec.get('holders'), list) else []
            for index, row in enumerate(entries[:20]):
                if not isinstance(row, dict): continue
                address_field = source_address(row.get('address'))
                fraction = source_decimal(row.get('percent'))
                if address_field and fraction is not None:
                    parts = [f'The security provider reports holder {address_field}', f'supply fraction = {fraction}']
                    tag = row.get('tag')
                    if isinstance(tag, str) and re.fullmatch(r'[A-Za-z0-9 _.-]{1,40}', tag): parts.append(f'tag = {tag}')
                    locked = row.get('is_locked')
                    if type(locked) is int and locked in (0, 1): parts.append(f'is_locked = {locked}')
                    claim('onchain', f'provider-holder-{index+1}', '; '.join(parts) + '.', 'security',
                          'Provider labels, supply fraction and lock status do not establish ownership or future behavior.')
            for key in ('is_open_source', 'is_proxy', 'is_mintable', 'transfer_pausable', 'is_honeypot'):
                if key in sec and isinstance(sec[key], (str, int, bool)):
                    claim('onchain', 'provider-'+key, f'The security provider reports {key} = {sec[key]}.', 'security', 'Provider field is not independent proof of current contract behavior.')
        if 'honeypot_is' in valid:
            scan = honeypot['honeypotResult']
            flagged = scan['isHoneypot']
            claim('onchain', 'honeypot-provider-verdict', f'The Honeypot.is provider reports isHoneypot = {str(flagged).lower()} for the selected pool.',
                  'honeypot_is', 'A provider verdict is not independent proof of a holder-specific or universal restriction.')
            claim('onchain', 'honeypot-provider-simulation', f'The Honeypot.is provider reports simulationSuccess = {str(honeypot["simulationSuccess"]).lower()} for its simulated trade.',
                  'honeypot_is', 'Provider simulation outcome does not establish all holders, sizes, routes or future states.')
            provider_summary = honeypot.get('summary')
            flags = provider_summary.get('flags') if isinstance(provider_summary, dict) else None
            if isinstance(flags, list):
                for index, item in enumerate(flags[:10]):
                    flag = item.get('flag') if isinstance(item, dict) else None
                    if isinstance(flag, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', flag):
                        claim('onchain', f'honeypot-provider-flag-{index+1}', f'The Honeypot.is provider reports flag {flag} for the selected pool.',
                              'honeypot_is', 'Provider flag is not independently verified; its underlying conditions and failure causes require review.')
            holder = honeypot.get('holderAnalysis')
            if isinstance(holder, dict):
                def provider_count(value):
                    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,9}', str(value)): return None
                    return int(value)
                counts = {key: provider_count(holder.get(key)) for key in ('holders', 'successful', 'failed')}
                if all(v is not None for v in counts.values()) and counts['successful'] + counts['failed'] == counts['holders']:
                    for key in ('holders', 'successful', 'failed'):
                        measurement('onchain', 'honeypot_holder_' + key, counts[key], 'provider-reported holder analyses',
                                    'honeypot_is', 'Honeypot.is reported count; failure causes and independent reproducibility are not established')
            simulation = honeypot.get('simulationResult')
            if isinstance(simulation, dict):
                for key in ('buyTax', 'sellTax'):
                    measurement('onchain', 'honeypot_simulation_' + key, simulation.get(key), 'provider-reported percent',
                                'honeypot_is', 'Honeypot.is reported simulated tax; not a universal execution quote')
            if isinstance(sec, dict) and str(sec.get('is_honeypot')) in ('0', '1') and (str(sec['is_honeypot']) == '1') != flagged:
                provider_claim = next(x for x in pillars['onchain']['claims'] if x['id'] == 'honeypot-provider-verdict')
                goplus_claim = next((x for x in pillars['onchain']['claims'] if x['id'] == 'provider-is_honeypot'), None)
                if goplus_claim:
                    provider_claim['counterevidence_ids'].append('security'); goplus_claim['counterevidence_ids'].append('honeypot_is')
                pillars['onchain']['quality_issues'].append('Honeypot.is and GoPlus provider verdicts conflict; route-, holder-, size- and state-specific independent investigation is required.')
        if 'source' in valid:
            claim('onchain', 'source-status', f'The source provider reports runtime match status: {source.get("runtimeMatch", "unknown")}.', 'source', 'Provider match does not establish safety, current state or sell behavior.')
            verified_at = source.get('verifiedAt')
            if isinstance(verified_at, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', verified_at):
                try:
                    dt.datetime.strptime(verified_at, '%Y-%m-%dT%H:%M:%SZ')
                except ValueError:
                    pass
                else:
                    claim('onchain', 'source-verified-at', f'The source provider reports a verification timestamp of {verified_at}.', 'source', 'The provider timestamp is not independent evidence of current contract behavior.')
        if analysis:
            seen_categories = set()
            for finding in analysis.get('findings', []):
                if finding.get('category') in seen_categories:
                    continue
                seen_categories.add(finding['category'])
                claim('onchain', 'contract-indicator-'+str(len(seen_categories)),
                      f'Source navigation found a {finding["category"]} indicator in {finding["function"]} at {finding["path"]}:{finding["line"]}.',
                      'contract_analysis', 'Lexical indicator is not proof of live control, reachability or safety.')
                pillars['onchain']['claims'][-1]['supporting_evidence_ids'].append('pinned_contract_capture')
                pillars['onchain']['evidence_ids'] = sorted(set(pillars['onchain']['evidence_ids'] + ['pinned_contract_capture']))
            for i, hypothesis in enumerate(analysis.get('mechanism_hypotheses', [])):
                claim('onchain', f'contract-hypothesis-{i+1}', hypothesis['rationale'], 'contract_analysis', 'Lexical source hypothesis needs provenance, control-flow and runtime review.')
                pillars['onchain']['claims'][-1]['supporting_evidence_ids'].append('pinned_contract_capture')
                pillars['onchain']['evidence_ids'] = sorted(set(pillars['onchain']['evidence_ids'] + ['pinned_contract_capture']))
            pillars['onchain']['quality_issues'].extend(analysis.get('unknowns', []))
        if legacy:
            for name in ('microstructure', 'onchain'):
                if name not in legacy_inputs or legacy[name]['status'] != 'partial':
                    continue
                payload = legacy[name]['payload']; ref = 'legacy_' + name + '_result'
                if name == 'microstructure':
                    measurement(name, 'legacy_microstructure_score', payload.get('microstructure_score'), None, ref, 'Original legacy microstructure score and scale')
                    measurement(name, 'legacy_mev_score', (payload.get('mevExposure') or {}).get('score'), None, ref, 'Original legacy MEV proxy score and scale')
                else:
                    score = payload.get('legacy_summary') or {}
                    measurement(name, 'legacy_fundamentals_score', score.get('fundamentals_score'), None, ref, 'Original legacy contract-control score and scale')
                    if score.get('label'):
                        claim(name, 'legacy-control-label', f'Original legacy contract-control label: {score["label"]}.', ref, 'Legacy label is not a safety or honeypot certification.')
                pillars[name]['evidence_ids'] = sorted(set(pillars[name]['evidence_ids'] + ['legacy_' + name + '_input']))
                pillars[name]['quality_issues'].extend(payload.get('quality_issues', []))
        if graph_capture and graph_capture['rows']:
            p = pillars['technical_health']; p['status'] = 'partial'; p['evidence_ids'] = sorted(set(p['evidence_ids'] + ['graph_token_daily', 'graph_source_manifest']))
            points = [{'time': dt.datetime.fromtimestamp(row['date'], dt.timezone.utc).date().isoformat(), 'value': float(row['priceUSD'])} for row in graph_capture['rows']]
            p['series'].append({'id': 'graph_token_daily_price_usd', 'unit': 'USD per token',
                'method': 'The Graph tokenDayDatas priceUSD; token-level, not selected-pool price', 'quality': 'unvalidated',
                'evidence_ids': ['graph_token_daily', 'graph_source_manifest'], 'window': {'start': points[0]['time'], 'end': points[-1]['time'], 'precision': 'day'},
                'points': points, 'unknown_reason': None})
            claim('technical_health', 'graph-token-history', f'The Graph token-level source returned {len(points)} closed daily price observations.', 'graph_token_daily',
                  'Token-level subgraph coverage is not a selected-pool price, a history-adequacy judgment or an independently verified market-wide observation.')
            if graph_capture['returns']:
                daily_points = [{'time': row['date'], 'value': row['return']} for row in graph_capture['returns']]
                p['series'].append({'id': 'graph_token_daily_returns', 'unit': 'fraction', 'method': 'Adjacent Graph token-level priceUSD ratios; no filled gaps',
                    'quality': 'unvalidated', 'evidence_ids': ['graph_token_daily'],
                    'window': {'start': daily_points[0]['time'], 'end': daily_points[-1]['time'], 'precision': 'day'}, 'points': daily_points, 'unknown_reason': None})
            p['quality_issues'].append('Graph token-level data is not selected-pool history; source correctness and history adequacy remain open.')
            if graph_capture['missing']: p['quality_issues'].append('Graph capture has missing days; no values were filled.')
        if daily_prepared and daily_prepared['close_count']:
            p = pillars['technical_health']; p['status'] = 'partial'; p['evidence_ids'] = sorted(set(p['evidence_ids'] + ['daily', 'pools']))
            rows = candles['data']['attributes']['ohlcv_list']; cutoff = dt.date.fromisoformat(daily_prepared['cutoff_utc_date'])
            closes = sorted([{'time': dt.datetime.fromtimestamp(row[0], dt.timezone.utc).date().isoformat(), 'value': float(row[4])}
                             for row in rows if dt.datetime.fromtimestamp(row[0], dt.timezone.utc).date() < cutoff], key=lambda x: x['time'])
            p['series'].append({'id': 'observed_daily_closes', 'unit': 'USD per token', 'method': 'Provider token-side closed daily prices; missing dates not filled',
                'quality': 'unvalidated', 'evidence_ids': ['daily', 'pools'],
                'window': {'start': closes[0]['time'], 'end': closes[-1]['time'], 'precision': 'day'}, 'points': closes, 'unknown_reason': None})
            claim('technical_health', 'daily-coverage', f'The price provider returned {len(closes)} closed daily observations for the selected token-side pool.',
                  'daily', 'Observation count and coverage do not establish a trend or model-history adequacy.')
            if daily_prepared['returns']:
                points = [{'time': x['date'], 'value': x['return']} for x in daily_prepared['returns']]
                p['series'].append({'id': 'observed_daily_returns', 'unit': 'fraction', 'method': 'Adjacent closed daily close ratios; no filled gaps',
                    'quality': 'unvalidated', 'evidence_ids': ['daily', 'pools'],
                    'window': {'start': points[0]['time'], 'end': points[-1]['time'], 'precision': 'day'}, 'points': points, 'unknown_reason': None})
            p['quality_issues'].append('Observed daily prices and returns are not the legacy VAE technical score or a calibrated trading signal.')
            if daily_prepared['gaps']: p['quality_issues'].append('Daily candle gaps were excluded; series is not continuously sampled.')
        if model:
            for key, target in [('risk_assessment', 'statistical_risk'), ('technical_health', 'technical_health')]:
                def walk(value, path):
                    if isinstance(value, dict):
                        for k, x in value.items(): walk(x, path + [str(k)])
                    elif isinstance(value, (int, float)) and not isinstance(value, bool):
                        measurement(target, 'legacy_' + '_'.join(path), value, None, 'legacy_metrics', 'Original legacy 50-reconstruction method and original scale')
                    elif isinstance(value, str):
                        claim(target, 'legacy-' + '-'.join(path), f'Legacy output {".".join(path)}: {value}', 'legacy_metrics', 'Original label is retained; independent calibration is not established.')
                walk(metrics.get(key, {}), [])
            ts = metrics.get('technical_series', {})
            dates = ts.get('dates') if isinstance(ts, dict) else None
            if isinstance(dates, list):
                for key, values in ts.items():
                    if key == 'dates' or not isinstance(values, list) or len(values) != len(dates) or not dates:
                        continue
                    if any(not isinstance(t, str) or _number(v) is None for t, v in zip(dates, values)):
                        continue
                    pillars['technical_health']['series'].append({'id': 'legacy_' + str(key), 'unit': None,
                        'method': 'Original legacy technical-health series on 50 reconstructions', 'quality': 'unvalidated',
                        'evidence_ids': ['legacy_metrics'], 'window': {'start': dates[0], 'end': dates[-1], 'precision': 'day'},
                        'points': [{'time': t, 'value': float(v)} for t, v in zip(dates, values)], 'unknown_reason': None})
            for p in ('statistical_risk', 'technical_health'):
                pillars[p]['quality_issues'].append('Original legacy metrics use 50 reconstructions; model calibration is not independently verified.')
        else:
            pillars['statistical_risk']['quality_issues'].append('Legacy VAE risk is pending until an identity- and candle-bound 50-reconstruction run is supplied.')
            pillars['technical_health']['quality_issues'].append('Legacy VAE technical metrics are pending; observed history, if present, remains separate.')
        pillars['fundamentals']['quality_issues'].append('Project attribution, social context and development require additional evidence; no Reddit content is persisted here.')
        for p in pillars.values():
            if p['claims']: p['summary'] = p['claims'][0]['statement']
            elif p['series']: p['summary'] = 'Observed daily price history is available; legacy VAE metrics may remain pending.'
            elif p['measurements']: p['summary'] = 'Legacy measurements are available with their original scale and source evidence.'
            elif p['quality_issues']: p['summary'] = p['quality_issues'][0]
        available = [name for name, p in pillars.items() if p['status'] == 'partial']
        if not available:
            model_reasoning._emit(stage_callback, {'stage': 'report', 'state': 'blocked', 'reason': 'sources_contain_no_usable_pillar_observation'})
            return {'state': 'blocked', 'bundle_path': None, 'case_id': case_id, 'run_id': run_id,
                    'source_attempts': attempts, 'reason': 'sources_contain_no_usable_pillar_observation'}
        # Coverage records are real run-state evidence, not token-risk measurements.
        # They let the IRC present missing pillars without citing an unrelated source.
        if max_model_calls or reasoning_checkpoint is not None:
            for name, p in pillars.items():
                if p['status'] not in ('partial', 'complete'):
                    eid = 'coverage_' + name
                    add_evidence(eid, _bytes({'candidate_id': candidate_id, 'pillar': name, 'status': p['status'],
                                              'reason': p['summary'], 'quality_issues': p['quality_issues']}),
                                 {'url': None, 'fetched_at': None}, 'derived')
                    p['evidence_ids'].append(eid)
        report = {'schema_version': '0.2', 'report_id': report_id, 'report_version': version,
            'candidate_id': candidate_id, 'identity': {'chain_id': chain, 'address': address, 'symbol': symbol}, 'mode': mode,
            'assessment': {'status': 'not_assessed', 'label': None,
                'summary': 'Evidence-linked draft: review source observations, control hypotheses and coverage before a final conclusion.',
                'unknowns': ['Independent source verification', 'Current contract control state and executable sells', 'Authenticated report review'],
                'supporting_claim_ids': [], 'counterevidence_claim_ids': []}, 'pillars': pillars, 'evidence': evidence,
            'artifacts': [], 'review': {'status': 'pending', 'reviewer': None, 'reviewed_at': None,
                'reviewed_version': None, 'content_sha256': None, 'authentication': 'none'},
            'limitations': ['Bounded source snapshots may be incomplete or taken at different times.',
                            'No paid model interpretation, final report approval or publication was performed.']
                            + (['Replayed captured evidence retains its original timestamps; this is not fresh source collection.'] if captured_snapshot is not None else [])}
        if graph_capture is not None:
            report['limitations'].append('Graph tokenDayDatas is token-level subgraph coverage, not selected-pool history; missing rows do not establish absence of trading elsewhere.')
            report['limitations'].append('Graph page capture times are bundle-level; source correctness, indexed coverage and statistical adequacy are not independently established.')
        if graph_model is not None:
            report['limitations'].append(f"The preserved Graph-backed run used a {graph_model['manifest']['days']}-day VaR horizon as historical test scope, not an approved general default.")
        model = model_reasoning.run(report, root, max_model_calls=max_model_calls, client=model_client,
            max_output_tokens=max_model_output_tokens, max_context_chars=max_model_context_chars,
            stage_callback=stage_callback, checkpoint=reasoning_checkpoint, cancelled=cancelled)
        if model['status'] == 'cancelled':
            return {'state': 'cancelled', 'bundle_path': None, 'case_id': case_id, 'run_id': run_id,
                    'source_attempts': attempts, 'model_status': 'cancelled', 'model_calls': model['calls'],
                    'model_usage': model.get('usage'), 'reason': 'cancelled_before_bundle_commit'}
        sidecar = model.get('sidecar')
        analyzed = {x['name']: x for x in sidecar['reasoning']['pillars']} if sidecar else {}
        if sidecar:
            conclusion = sidecar['reasoning']['conclusion']
            report['assessment'] = {'status': 'proposed', 'label': conclusion['label'], 'summary': conclusion['summary'],
                'unknowns': conclusion['unknowns'], 'supporting_claim_ids': conclusion['supporting_claim_ids'],
                'counterevidence_claim_ids': conclusion['counterevidence_claim_ids']}
            report['limitations'] = [x for x in report['limitations'] if not x.startswith('No paid model interpretation')]
            report['limitations'].append('Model reasoning is a proposed draft; citation links are checked but factual entailment and human approval are not established.')
            sidecar['model_call'] = {'model': model_reasoning.MODEL, 'transport': 'chat.completions',
                                     'provider': 'resumed_checkpoint' if model['status'] == 'resumed' else ('injected_client' if model_client is not None else 'openai'),
                                     'status': model['status'], 'scope': 'one_shared_five_pillar_and_conclusion_call',
                                     'usage': model.get('usage')}
            (root / 'reasoning.json').write_bytes(_bytes(sidecar))
        elif model['status'] != 'skipped_budget':
            report['limitations'].append('Model analysis was not produced: ' + model['status'] + '.')
        tldr = {'profile': 'scooby.pillar-tldr/1', 'report_id': report_id, 'report_version': version, 'pillars': {}}
        irc = {'profile': 'scooby.pillar-irc/1', 'report_id': report_id, 'report_version': version,
               'candidate_id': candidate_id, 'pillars': {}}
        lines = ['# Investigation report — pending review', '', f'Case {case_id}; candidate `{candidate_id}`; run {run_id}.', '']
        for name, p in pillars.items():
            tldr['pillars'][name] = [{'role': 'finding', 'text': x['statement'], 'claim_ids': [x['id']],
                                      'evidence_ids': x['supporting_evidence_ids']} for x in p['claims'][:2]]
            if p['claims'] and p['claims'][0]['uncertainties']:
                first = p['claims'][0]
                tldr['pillars'][name].append({'role': 'interpretation', 'text': first['uncertainties'][0],
                    'claim_ids': [first['id']], 'evidence_ids': first['supporting_evidence_ids']})
            elif p['measurements']:
                first = p['measurements'][0]
                tldr['pillars'][name].append({'role': 'finding', 'text': f'{first["id"]}: {first["value"]} (original or provider scale; not independently validated).',
                    'claim_ids': [], 'evidence_ids': first['evidence_ids']})
            if p['evidence_ids'] and p['quality_issues']:
                tldr['pillars'][name].append({'role': 'caveat', 'text': p['quality_issues'][0], 'claim_ids': [], 'evidence_ids': [p['evidence_ids'][0]]})
            if sidecar:
                section = analyzed[name]; first = section['analysis'][0]
                claim_ids = [i for i in first['input_ids'] if i in {c['id'] for c in p['claims']}]
                ev_ids = first['evidence_ids'] or (p['evidence_ids'] if p['status'] not in ('partial', 'complete') else [])
                if p['claims']:
                    observed = p['claims'][0]
                    tldr['pillars'][name] = [{'role': 'finding', 'text': observed['statement'],
                        'claim_ids': [observed['id']], 'evidence_ids': observed['supporting_evidence_ids']}]
                elif p['measurements']:
                    observed = p['measurements'][0]
                    tldr['pillars'][name] = [{'role': 'finding', 'text': f'{observed["id"]}: {observed["value"]} (source scale; not independently validated).',
                        'claim_ids': [], 'evidence_ids': observed['evidence_ids']}]
                else:
                    tldr['pillars'][name] = [{'role': 'caveat', 'text': p['summary'], 'claim_ids': [], 'evidence_ids': ev_ids}]
                tldr['pillars'][name] += [{'role': 'interpretation', 'text': section['summary'], 'claim_ids': claim_ids, 'evidence_ids': ev_ids},
                    {'role': 'interpretation', 'text': first['text'], 'claim_ids': claim_ids, 'evidence_ids': ev_ids}]
                irc['pillars'][name] = {'insight': {'text': section['summary'], 'claim_ids': claim_ids, 'evidence_ids': ev_ids},
                    'reasoning': {'text': first['text'], 'claim_ids': claim_ids, 'evidence_ids': ev_ids},
                    'citations': {'claim_ids': claim_ids, 'input_ids': first['input_ids'], 'evidence_ids': ev_ids},
                    'limitations': section['limitations'], 'questions': section['questions']}
            lines.extend(['## ' + name.replace('_', ' ').title(), '', p['summary'], '', 'Status: ' + p['status']])
            lines.extend('- ' + c['statement'] + ' [' + ', '.join(c['supporting_evidence_ids']) + ']' for c in p['claims'])
            if sidecar:
                lines.extend(['', '### Proposed analysis', '', analyzed[name]['summary']])
                lines.extend('- ' + a['text'] + ' [evidence: ' + ', '.join(a['evidence_ids']) + '; inputs: ' + ', '.join(a['input_ids']) + ']' for a in analyzed[name]['analysis'])
                lines.extend('- Limitation: ' + x for x in analyzed[name]['limitations'])
                lines.extend('- Follow-up: ' + x for x in analyzed[name]['questions'])
            lines.extend('- ' + q for q in p['quality_issues']); lines.append('')
        if sidecar:
            c = sidecar['reasoning']['conclusion']; rec = c['recommendation']
            lines.extend(['## Proposed conclusion', '', c['summary'], '', 'Proposed action: ' + rec['action'], '',
                          rec['rationale']['text'] + ' [evidence: ' + ', '.join(rec['rationale']['evidence_ids']) +
                          '; inputs: ' + ', '.join(rec['rationale']['input_ids']) + ']'])
            lines.extend('- Counterevidence: ' + a['text'] + ' [' + ', '.join(a['evidence_ids']) + ']' for a in rec['counterevidence'])
            lines.extend('- Would change this view: ' + q for q in rec['reversal_conditions']); lines.append('')
        (root / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
        (root / 'pillar-tldr.json').write_bytes(_bytes(tldr))
        if sidecar:
            (root / 'pillar-irc.json').write_bytes(_bytes(irc))
        (root / 'source-ledger.json').write_bytes(_bytes({'candidate_id': candidate_id, 'sources': ledger, 'attempts': attempts,
                                                           'limits': stops, 'replay_ignored': replay_ignored}))
        (root / 'case-lineage.json').write_bytes(_bytes({'case_id': case_id, 'run_id': run_id, 'candidate_id': candidate_id,
                                                         'authorization_route': auth['route'], 'authorization_reference_id': auth['reference_id']}))
        for kind, filename, mime in [('markdown', 'report.md', 'text/markdown'), ('pillar_tldr', 'pillar-tldr.json', 'application/json'),
                                     ('source_ledger', 'source-ledger.json', 'application/json'), ('case_lineage', 'case-lineage.json', 'application/json')]:
            report['artifacts'].append({'kind': kind, 'availability': 'available', 'path': filename,
                'sha256': _sha((root / filename).read_bytes()), 'report_id': report_id, 'report_version': version, 'media_type': mime})
        if sidecar:
            for kind, filename in [('reasoning', 'reasoning.json'), ('pillar_irc', 'pillar-irc.json')]:
                report['artifacts'].append({'kind': kind, 'availability': 'available', 'path': filename,
                    'sha256': _sha((root / filename).read_bytes()), 'report_id': report_id, 'report_version': version,
                    'media_type': 'application/json'})
        report['artifacts'].append({'kind': 'pdf', 'availability': 'unavailable', 'path': None, 'sha256': None,
                                    'report_id': report_id, 'report_version': version, 'media_type': None})
        contract_validate.validate(root, report)
        raw = _bytes(report); (root / 'report.json').write_bytes(raw)
        (root / 'digest.json').write_bytes(_bytes({'algorithm': 'sha256', 'target': 'report.json exact UTF-8 bytes', 'sha256': _sha(raw), 'status': 'pending; not approval'}))
        contract_validate.verify_digest(root, _sha(raw))
        if cancelled and cancelled():
            return {'state': 'cancelled', 'bundle_path': None, 'case_id': case_id, 'run_id': run_id,
                    'source_attempts': attempts, 'reason': 'cancelled_before_bundle_commit'}
        model_reasoning._emit(stage_callback, {'stage': 'report', 'state': 'validated', 'report_sha256': _sha(raw)})
        os.rename(root, output)
    return {'state': 'partial', 'bundle_path': str(output), 'case_id': case_id, 'run_id': run_id,
            'report_id': report_id, 'report_version': version, 'report_sha256': _sha(raw),
            'pillar_status': {k: v['status'] for k, v in pillars.items()}, 'source_attempts': attempts,
            'model_status': model['status'], 'model_calls': model['calls'],
            'model_usage': model.get('usage'), 'model_detail': model.get('detail'), 'graph_capture': graph_summary,
            'replay_sources': len(valid) if captured_snapshot is not None else 0,
            'replay_ignored': replay_ignored, 'limitations': stops}
