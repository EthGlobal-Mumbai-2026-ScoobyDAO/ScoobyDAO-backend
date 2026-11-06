"""Synthetic `scooby-six-reference-seed/1` archive built in-test (same manifest shape as the private seed).

Bundles are tests/historical-bundle re-identified per synthetic pair; identities, snapshots and evidence are
synthetic. No bytes from the private seed are used.
"""
import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

BUNDLE = Path(__file__).parent / 'historical-bundle'
SYMBOLS = ('SHIB', 'FET', 'SPX', 'YFI', 'GRT', 'METIS')
POLICY = 'f' * 64


def h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _bundle(i: int, sym: str) -> tuple[dict, dict]:
    address = '0x' + f'{i + 1:040x}'
    cid = '1:' + address
    case, run = 'synthetic_' + sym.lower(), 'synthetic_' + sym.lower() + '_run'
    files = {p.relative_to(BUNDLE).as_posix(): p.read_bytes() for p in BUNDLE.rglob('*') if p.is_file()}
    doc = json.loads(files['report.json'])
    doc.update(candidate_id=cid, identity={'chain_id': 1, 'address': address, 'symbol': sym},
               report_id='case-' + case, report_version='run-' + run)
    for a in doc['artifacts']:
        a['report_id'], a['report_version'] = doc['report_id'], doc['report_version']
    files['report.json'] = json.dumps(doc, indent=2).encode()
    files['case-lineage.json'] = json.dumps({'case_id': case, 'run_id': run, 'candidate_id': cid,
                                             'authorization_route': 'automatic_policy',
                                             'authorization_reference_id': 'synthetic_auth_not_admission'}).encode()
    raw = json.dumps({'synthetic': True, 'symbol': sym}).encode()
    source = 'snapshots/' + h(raw) + '.json'
    record = {'candidate_id': cid, 'identity': {'chain_id': 1, 'address': address, 'symbol': sym}, 'mode': 'live', 'state': 'monitoring',
              'evidence': [{'id': h(raw), 'sha256': h(raw), 'source': source, 'kind': 'live_observation', 'fetched_at': '2026-11-06T20:00:00+00:00',
                            'observed_at': None, 'block_number': None, 'limitations': ['Synthetic test evidence.']}],
              'screening': {'status': 'insufficient_data', 'quality_issues': ['Synthetic historical reference.'], 'score': None,
                            'score_version': None, 'threshold_version': None},
              'triggers': [{'description': 'Synthetic historical reference, not a finding.', 'evidence_ids': [h(raw)], 'reason_code': 'historical_reference'}],
              'schema_version': '0.1'}
    evidence = {source: base64.b64encode(raw).decode()}
    assessment = {'groups': [{'id': 'G01', 'name': 'G01', 'detail': 'Unknown.', 'status': 'unknown', 'evidence': [], 'measurements': [], 'votes': 0}]}
    snap = {'id': h(dumps({'record': record, 'evidence': evidence, 'policy': POLICY, 'assessment': assessment}).encode()),
            'candidate_id': cid, 'record': dumps(record), 'evidence': dumps(evidence), 'policy_digest': POLICY,
            'assessment': dumps(assessment), 'evaluated': 1000.5, 'expires': 2000.5}
    pair = {'symbol': sym, 'candidate_id': cid, 'case_id': h(cid.encode()), 'report_id': doc['report_id'], 'version': doc['report_version'],
            'report_sha256': h(files['report.json']), 'bundle': 'bundles/' + sym.lower(),
            'description': f'Synthetic {sym} historical reference; pending review, synthetic lineage.', 'snapshot': snap}
    return pair, files


def build(mutate=None, tamper=None, extra=None) -> tuple[bytes, str, dict]:
    """(zip bytes, zip sha256, pins). `mutate(manifest, members)` runs before hashing; `tamper(members)` after."""
    members, pairs = {}, []
    for i, sym in enumerate(SYMBOLS):
        pair, files = _bundle(i, sym)
        pairs.append(pair)
        for rel, b in files.items():
            members[pair['bundle'] + '/' + rel] = b
    members['backend/app.py'] = b"raise SystemExit('the seed backend snapshot must never run')\n"
    members['restore.py'] = b"raise SystemExit('restore.py must never run')\n"
    members['README.txt'] = b'Synthetic test seed.\n'
    manifest = {'format': 'scooby-six-reference-seed/1', 'backend_commit': 'synthetic', 'pairs': pairs}
    if mutate:
        mutate(manifest, members)
    manifest['files'] = {k: h(v) for k, v in sorted(members.items())}
    members['manifest.json'] = json.dumps(manifest, indent=2).encode()
    if tamper:
        tamper(members)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, b in members.items():
            z.writestr(name, b)
        for name, b in (extra or {}).items():
            z.writestr(name, b)
    data = buf.getvalue()
    pins = {p['symbol']: (p['candidate_id'], p['case_id'], p['report_id'], p['version'], p['report_sha256']) for p in pairs}
    return data, h(data), pins
