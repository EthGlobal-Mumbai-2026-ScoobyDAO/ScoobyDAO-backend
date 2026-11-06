"""Six-reference display seed (docs/reference-display-contract.md, `scooby-six-reference-seed/1`).

Verifies and merges the private six case/report reference ZIP into the database: historical, unreviewed,
display-only. Nothing from the archive is executed: only `manifest.json` and `bundles/**` are read, and every
member (including the `backend/` snapshot and `restore.py`, which are hash-checked in memory and never written to
disk) must match `manifest.files`. The archive digest must equal both the operator's expected value and the pin in
this file; the six identities are pinned here and cannot be substituted by configuration.

The merge is one `BEGIN IMMEDIATE` transaction: an identical re-run changes nothing, a conflicting existing row
refuses the whole import and changes nothing, and bundle directories created by a failed run are removed. It
creates no jobs, reviews, decisions, challenges or World attempts, and calls no network, model or provider.

    python reference_seed.py verify  --archive PATH --sha256 HEX   # read-only verification, no database writes
    python reference_seed.py restore --archive PATH --sha256 HEX   # verified transactional merge into SCOOBY_DATA
"""
from __future__ import annotations
import argparse
import base64
import binascii
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

FORMAT = 'scooby-six-reference-seed/1'
PINNED_ZIP_SHA256 = 'c9fcbf2a32b7c58142389075511989357431b4d457ae89997ebae2261697b8a0'
# symbol -> (candidate_id, case_id, report_id, report_version, report_sha256); case_id = sha256(candidate_id)
PINNED_PAIRS = {
    'SHIB': ('1:0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce', 'ac40e79f2e6e1cc2d011d487d8a9d259700591f0f1f85f46bfa22fcd171b25ea',
             'case-shib_reference_research', 'run-shib_reference_replay_20261107', '13cfdb303407895cb1c9cf1913a138ac0191c694517606e3f2a3fa5c00bbea99'),
    'FET': ('1:0xaea46a60368a7bd060eec7df8cba43b7ef41ad85', '7b460f8e9e93aa02d7c6425b1450ec6e30c97c0beab9539a94261c4ce4daa0b8',
            'case-reference_fet', 'run-reference_fet_20261107', 'a697d2932eb2b9628229cc4283f1c1d28058953fcfdc20b37f6481ca2d0d923e'),
    'SPX': ('1:0xe0f63a424a4439cbe457d80e4f4b51ad25b2c56c', 'bbe3daeeccbe5273e4a1f742a6a872dea08e7d8313e99de4ac3ccb6203d04800',
            'case-reference_spx', 'run-reference_spx_20261107', '3f6bea48fd347c4ed8477b12ca10f53d8e06e2714ac4600f96808f78acabc854'),
    'YFI': ('1:0x0bc529c00c6401aef6d220be8c6ea1667f6ad93e', 'a7b75ac2adac7deb04fb9b11dacd165eb32a03f49c192b76ae654f6a8ee49e92',
            'case-reference_yfi', 'run-reference_yfi_20261107', '27e70de305585ebac702bcd3c041fe8d952455bbc3d3555de2bad33473d32ef9'),
    'GRT': ('1:0xc944e90c64b2c07662a292be6244bdf05cda44a7', '2f156e0056d0629c85967e90b8023ba8f7cbc827462f93a00fb021125ce16b89',
            'case-reference_grt', 'run-reference_grt_20261107', '70de2083725d70dae6874e803667527bf84d4ac303ffb97110ab5530aada7a01'),
    'METIS': ('1:0x9e32b13ce7f2e80a01932b42553652e053d6ed8e', '72557d92517b2a7e6ac0cea716bc3ca5006c78c8bfc27e3b8eb89fa5ff82b5ab',
              'case-reference_metis', 'run-reference_metis_20261107', '8bdbe633a92fdaebb57b7bd68af0dbb9f4f048b844a91f05f28f7fbd1f8541bd'),
}
SHA = re.compile('[0-9a-f]{64}')
MAX_ARCHIVE = 50_000_000
MAX_EXPANDED = 200_000_000
MAX_MEMBERS = 5000
LINK_TABLE = ('CREATE TABLE IF NOT EXISTS case_reference_reports(case_id TEXT NOT NULL REFERENCES cases(id),report_id TEXT NOT NULL,'
              'version TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(case_id,report_id,version),'
              'FOREIGN KEY(report_id,version) REFERENCES reports(id,version))')


class ReferenceSeedError(ValueError):
    """Verification failed or an existing row conflicts; nothing was written."""


def h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def dumps(x) -> str:
    """Identical to store.dumps (the snapshot digest encoding), without importing store's database side effects."""
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def archive_bytes(path: Path) -> bytes:
    """The ZIP bytes from a .zip file or its base64 text (e.g. a Render Secret File)."""
    raw = Path(path).read_bytes()
    if len(raw) > MAX_ARCHIVE * 2:
        raise ReferenceSeedError('reference seed archive is too large')
    if raw[:4] != b'PK\x03\x04':
        try:
            raw = base64.b64decode(b''.join(raw.split()), validate=True)
        except (binascii.Error, ValueError):
            raise ReferenceSeedError('reference seed archive is neither a zip file nor base64 of one') from None
    if raw[:4] != b'PK\x03\x04' or len(raw) > MAX_ARCHIVE:
        raise ReferenceSeedError('reference seed archive is not an acceptable zip file')
    return raw


def _members(z: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = z.infolist()
    if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_EXPANDED:
        raise ReferenceSeedError('reference seed archive exceeds limits')
    files = {}
    for i in infos:
        name = i.filename
        parts = name.rstrip('/').split('/')
        if (not name or '\\' in name or ':' in name or name.startswith('/') or any(p in ('', '.', '..') for p in parts)
                or (i.external_attr >> 16) & 0o170000 == 0o120000):
            raise ReferenceSeedError('unsafe archive entry')
        if i.is_dir():
            continue
        if name in files:
            raise ReferenceSeedError('duplicate archive entry')
        files[name] = i
    return files


def _snapshot(pair: dict, dumps) -> dict:
    """Re-verify the case snapshot exactly as the producer's restore does: identity, digest and evidence names."""
    s = pair['snapshot']
    try:
        record, evidence, assessment = json.loads(s['record']), json.loads(s['evidence']), json.loads(s['assessment'])
    except (TypeError, ValueError, KeyError):
        raise ReferenceSeedError('case snapshot is not valid JSON') from None
    cid = pair['candidate_id']
    if record.get('candidate_id') != cid or s.get('candidate_id') != cid or h(cid.encode()) != pair['case_id']:
        raise ReferenceSeedError('case identity mismatch')
    if not SHA.fullmatch(str(s.get('policy_digest'))) or not isinstance(s.get('evaluated'), (int, float)) or not isinstance(s.get('expires'), (int, float)):
        raise ReferenceSeedError('case snapshot fields invalid')
    if h(dumps({'record': record, 'evidence': evidence, 'policy': s['policy_digest'], 'assessment': assessment}).encode()) != s['id']:
        raise ReferenceSeedError('case snapshot digest mismatch')
    if not isinstance(evidence, dict):
        raise ReferenceSeedError('case evidence invalid')
    for path, b64 in evidence.items():
        try:
            raw = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError, TypeError):
            raise ReferenceSeedError('case evidence is not base64') from None
        if path != 'snapshots/' + h(raw) + '.json':
            raise ReferenceSeedError('case evidence digest mismatch')
    return s


def verify(data: bytes, expected_sha: str, staging: Path) -> list[dict]:
    """Verify the archive and write only its six bundles under `staging`; returns the verified pairs."""
    from modules.investigation.contract_validate import verify_digest  # no store import: verify never touches the DB
    expected_sha = (expected_sha or '').strip().lower()
    if not SHA.fullmatch(expected_sha) or expected_sha != PINNED_ZIP_SHA256 or h(data) != expected_sha:
        raise ReferenceSeedError('reference seed SHA-256 does not match the configured and pinned digest; nothing imported')
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ReferenceSeedError('reference seed is not a valid zip') from None
    with z:
        files = _members(z)
        if 'manifest.json' not in files:
            raise ReferenceSeedError('manifest.json missing')
        try:
            manifest = json.loads(z.read(files['manifest.json']))
        except ValueError:
            raise ReferenceSeedError('manifest.json is not valid JSON') from None
        listed = manifest.get('files') if isinstance(manifest, dict) else None
        if manifest.get('format') != FORMAT or not isinstance(listed, dict) or not isinstance(manifest.get('pairs'), list):
            raise ReferenceSeedError('unsupported reference seed manifest')
        if set(files) != set(listed) | {'manifest.json'} or 'manifest.json' in listed:
            raise ReferenceSeedError('archive files differ from manifest')
        for name, want in listed.items():  # every member, including backend/** and restore.py: hashed in memory only
            if not isinstance(want, str) or h(z.read(files[name])) != want:
                raise ReferenceSeedError('file hash mismatch: ' + name)
        pairs = manifest['pairs']
        if len(pairs) != len(PINNED_PAIRS) or {p.get('symbol') for p in pairs if isinstance(p, dict)} != set(PINNED_PAIRS):
            raise ReferenceSeedError('unexpected reference pair set')
        verified = []
        for p in pairs:
            pin = PINNED_PAIRS[p['symbol']]
            if (p.get('candidate_id'), p.get('case_id'), p.get('report_id'), p.get('version'), p.get('report_sha256')) != pin:
                raise ReferenceSeedError('pair identity differs from the pinned identity: ' + p['symbol'])
            if not isinstance(p.get('description'), str) or not p['description'].strip():
                raise ReferenceSeedError('pair description missing')
            bundle = p.get('bundle')
            if not isinstance(bundle, str) or not re.fullmatch(r'bundles/[a-z0-9_-]{1,40}', bundle):
                raise ReferenceSeedError('unsafe bundle path')
            snap = _snapshot(p, dumps)
            prefix = bundle + '/'
            names = [n for n in listed if n.startswith(prefix)]
            if prefix + 'report.json' not in names:
                raise ReferenceSeedError('bundle report.json missing: ' + p['symbol'])
            root = staging / pin[4]
            if root.exists():
                raise ReferenceSeedError('bundle listed twice')
            for n in names:
                out = root.joinpath(*PurePosixPath(n[len(prefix):]).parts)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(files[n]))
            doc = _bundle(root, p, verify_digest)
            verified.append({'symbol': p['symbol'], 'candidate_id': pin[0], 'case_id': pin[1], 'report_id': pin[2], 'version': pin[3],
                             'sha256': pin[4], 'run_id': doc['_run'], 'description': p['description'], 'snapshot': snap,
                             'doc': doc, 'staged': root})
        bundle_files = [n for n in listed if n.startswith('bundles/')]
        if sum(1 for n in bundle_files if any(n.startswith(p['bundle'] + '/') for p in pairs)) != len(bundle_files):
            raise ReferenceSeedError('archive carries unlisted bundles')
    return verified


def _bundle(root: Path, p: dict, verify_digest) -> dict:
    try:
        doc = verify_digest(root, p['report_sha256'])
        lineage = json.loads((root / 'case-lineage.json').read_bytes())
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ReferenceSeedError(f'bundle verification failed for {p["symbol"]}: {type(e).__name__}') from None
    cid = p['candidate_id']
    identity = doc.get('identity') or {}
    run = lineage.get('run_id')
    if ((doc['report_id'], doc['report_version'], doc['candidate_id']) != (p['report_id'], p['version'], cid)
            or doc.get('mode') != 'historical_replay' or doc['review']['status'] != 'pending'
            or str(identity.get('chain_id')) + ':' + str(identity.get('address', '')).lower() != cid
            or lineage.get('candidate_id') != cid or lineage.get('authorization_reference_id') != 'synthetic_auth_not_admission'
            or not isinstance(run, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', run)
            or doc['report_version'] != 'run-' + run or doc['report_id'] != 'case-' + str(lineage.get('case_id'))):
        raise ReferenceSeedError('report identity, mode, review or synthetic lineage mismatch: ' + p['symbol'])
    doc['_run'] = run
    return doc


def _same(row, values: dict) -> bool:
    return all(row[k] == v for k, v in values.items())


def _merge(c, x: dict, target: Path, created: float, store) -> int:
    """Insert what is missing for one pair; raise on any conflicting row. Returns the number of rows written."""
    cid, run, sha = x['candidate_id'], x['run_id'], x['sha256']
    written = 0
    cand = c.execute('SELECT payload FROM candidates WHERE id=?', (cid,)).fetchone()
    if cand:
        try:
            if json.loads(cand['payload']).get('candidate_id') not in (cid, None):
                raise ReferenceSeedError('candidate conflict: ' + x['symbol'])
        except ValueError:
            raise ReferenceSeedError('candidate conflict: ' + x['symbol']) from None
    else:
        c.execute('INSERT INTO candidates VALUES(?,?,?)', (cid, store.dumps({'candidate_id': cid, 'identity': x['doc']['identity'], 'mode': 'historical_replay'}), created))
        written += 1
    inv = c.execute('SELECT * FROM investigations WHERE id=?', (run,)).fetchone()
    if inv:
        if (inv['candidate_id'], inv['status']) != (cid, 'reference_only'):
            raise ReferenceSeedError('run identity conflict: ' + x['symbol'])
    else:
        sel = 'refseed-' + run
        if c.execute('SELECT 1 FROM selections WHERE id=? OR idem=?', (sel, 'refseed-sel:' + run)).fetchone():
            raise ReferenceSeedError('selection identity conflict: ' + x['symbol'])
        c.execute('INSERT INTO selections VALUES(?,?,?,?,?,?,?)', (sel, cid, 'diagnostic_exception', 'reference seed import', x['description'], created, 'refseed-sel:' + run))
        c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?)', (run, cid, sel, 'reference_only', created, 'refseed-run:' + run))
        for name in store.PILLARS:
            pillar = x['doc']['pillars'][name]
            c.execute('INSERT INTO pillars VALUES(?,?,?,?)', (run, name, pillar['status'], pillar['summary']))
        c.execute('INSERT INTO diagnostic_imports VALUES(?,?,?,?,?)', (run, cid, x['description'], 'restored_pending_review', created))
        store.event(c, run, 'reference_seed_imported', 'Historical reference from the six-reference seed; synthetic lineage, no gate, '
                    'case admission, World verification or review. Display only; no research job.')
        written += 1
    rep = c.execute('SELECT * FROM reports WHERE id=? AND version=?', (x['report_id'], x['version'])).fetchone()
    if rep:
        if (rep['sha256'], rep['run_id']) != (sha, run):
            raise ReferenceSeedError('immutable report conflict: ' + x['symbol'])
    else:
        c.execute('INSERT INTO reports VALUES(?,?,?,?,?,?)', (x['report_id'], x['version'], run, sha, str(target), created))
        written += 1
    s = x['snapshot']
    snap_values = {'candidate_id': cid, 'record': s['record'], 'evidence': s['evidence'], 'policy_digest': s['policy_digest'],
                   'assessment': s['assessment'], 'evaluated': s['evaluated'], 'expires': s['expires']}
    old = c.execute('SELECT * FROM case_snapshots WHERE id=?', (s['id'],)).fetchone()
    if old:
        if not _same(old, snap_values):
            raise ReferenceSeedError('case snapshot conflict: ' + x['symbol'])
    else:
        c.execute('INSERT INTO case_snapshots VALUES(?,?,?,?,?,?,?,?)', (s['id'], cid, s['record'], s['evidence'], s['policy_digest'],
                                                                         s['assessment'], s['evaluated'], s['expires']))
        written += 1
    case = c.execute('SELECT * FROM cases WHERE id=?', (x['case_id'],)).fetchone()
    if case:
        if (case['candidate_id'], case['current_snapshot']) != (cid, s['id']):
            raise ReferenceSeedError('existing case has another candidate or snapshot: ' + x['symbol'])
    else:
        if c.execute('SELECT 1 FROM cases WHERE candidate_id=?', (cid,)).fetchone():
            raise ReferenceSeedError('candidate already has another case: ' + x['symbol'])
        c.execute('INSERT INTO cases VALUES(?,?,?,?,?)', (x['case_id'], cid, s['id'], 'unavailable', created))
        written += 1
    if not c.execute('SELECT 1 FROM case_reference_reports WHERE case_id=? AND report_id=? AND version=?', (x['case_id'], x['report_id'], x['version'])).fetchone():
        c.execute('INSERT INTO case_reference_reports VALUES(?,?,?,?)', (x['case_id'], x['report_id'], x['version'], created))
        written += 1
    return written


def restore(data: bytes, expected_sha: str) -> dict:
    """Verified all-or-nothing merge. Returns {'pairs': 6, 'rows_written': n, 'bundles_installed': m}."""
    import store
    from modules.investigation.contract_validate import verify_digest
    bundles = store.DATA / 'bundles'
    bundles.mkdir(parents=True, exist_ok=True)
    created_dirs: list[Path] = []
    with tempfile.TemporaryDirectory(dir=store.DATA, prefix='reference-seed-') as tmp:
        verified = verify(data, expected_sha, Path(tmp))
        try:
            with store.db() as c:
                c.execute('BEGIN IMMEDIATE')
                c.execute(LINK_TABLE)
                rows, t = 0, store.now()
                for x in verified:
                    target = bundles / x['sha256']
                    rep = c.execute('SELECT sha256,run_id,path FROM reports WHERE id=? AND version=?', (x['report_id'], x['version'])).fetchone()
                    if rep:  # never write into a path another row names; it must already hold the verified bytes
                        if (rep['sha256'], rep['run_id']) != (x['sha256'], x['run_id']):
                            raise ReferenceSeedError('immutable report conflict: ' + x['symbol'])
                        target = Path(rep['path'])
                    if target.is_symlink():
                        raise ReferenceSeedError('installed bundle is a link: ' + x['symbol'])
                    if not target.exists() and not rep:
                        os.rename(x['staged'], target)
                        created_dirs.append(target)
                    try:
                        verify_digest(target, x['sha256'])
                    except (OSError, ValueError, KeyError, TypeError):
                        raise ReferenceSeedError('installed bundle differs from the verified seed: ' + x['symbol']) from None
                    rows += _merge(c, x, target, t, store)
                n = c.execute('SELECT count(*) FROM case_reference_reports l JOIN reports r ON r.id=l.report_id AND r.version=l.version '
                              'JOIN investigations i ON i.id=r.run_id JOIN cases k ON k.id=l.case_id '
                              "WHERE i.status='reference_only' AND k.candidate_id=i.candidate_id AND r.id||'@'||r.version IN (%s)"
                              % ','.join('?' * len(verified)), [x['report_id'] + '@' + x['version'] for x in verified]).fetchone()[0]
                if n != len(verified):
                    raise ReferenceSeedError('reference link count invalid after merge')
        except BaseException:
            for d in created_dirs:  # nothing references them: the transaction rolled back
                shutil.rmtree(d, ignore_errors=True)
            raise
    return {'pairs': len(verified), 'rows_written': rows, 'bundles_installed': len(created_dirs)}


FETCH_TIMEOUT = 30.0
FETCH_MAX = 10_000_000
HEADER_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}")


def settings() -> dict | None:
    """SCOOBY_REFERENCE_SEED_ARCHIVE (a local .zip/.b64 path) or SCOOBY_REFERENCE_SEED_URL (one HTTPS GET), never both."""
    archive = os.getenv('SCOOBY_REFERENCE_SEED_ARCHIVE', '').strip()
    url = os.getenv('SCOOBY_REFERENCE_SEED_URL', '').strip()
    if not archive and not url:
        return None
    if archive and url:
        raise ReferenceSeedError('set SCOOBY_REFERENCE_SEED_ARCHIVE or SCOOBY_REFERENCE_SEED_URL, not both')
    sha = os.getenv('SCOOBY_REFERENCE_SEED_SHA256', '').strip().lower()
    if not SHA.fullmatch(sha):
        raise ReferenceSeedError('SCOOBY_REFERENCE_SEED_SHA256 must be a 64-character hex SHA-256')
    header = None
    raw_header = os.getenv('SCOOBY_REFERENCE_SEED_AUTH_HEADER', '').strip()
    if raw_header:
        name, sep, value = raw_header.partition(':')
        if not url or not sep or not HEADER_NAME.fullmatch(name.strip()) or not value.strip() or any(ch in value for ch in '\r\n'):
            raise ReferenceSeedError('SCOOBY_REFERENCE_SEED_AUTH_HEADER must be "Name: value" and needs SCOOBY_REFERENCE_SEED_URL')
        header = (name.strip(), value.strip())
    if url:
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            raise ReferenceSeedError('SCOOBY_REFERENCE_SEED_URL must be an https URL without credentials')
    return {'archive': Path(archive) if archive else None, 'url': url or None, 'header': header, 'sha256': sha}


def fetch(url: str, header: tuple[str, str] | None, dest: Path, transport=None) -> bytes:
    """One storage GET: HTTPS, no redirects, bounded time and size, streamed to `dest`. Bytes are returned unparsed;
    the caller checks the pinned digest before anything reads them. Never logs the URL query or the header."""
    import httpx
    headers = {header[0]: header[1]} if header else {}
    try:
        with httpx.Client(transport=transport, timeout=FETCH_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            with client.stream('GET', url, headers=headers) as r:
                if r.status_code != 200:
                    raise ReferenceSeedError(f'reference seed fetch returned HTTP {r.status_code} (redirects are not followed)')
                declared = r.headers.get('content-length')
                if declared and declared.isdigit() and int(declared) > FETCH_MAX:
                    raise ReferenceSeedError('reference seed download exceeds the size limit')
                size = 0
                with open(dest, 'wb') as out:
                    for chunk in r.iter_bytes():
                        size += len(chunk)
                        if size > FETCH_MAX:
                            raise ReferenceSeedError('reference seed download exceeds the size limit')
                        out.write(chunk)
    except httpx.HTTPError as e:
        raise ReferenceSeedError(f'reference seed fetch failed: {type(e).__name__}') from None
    return archive_bytes(dest)


def run_from_env(transport=None) -> dict | None:
    cfg = settings()
    if cfg is None:
        return None
    if cfg['archive'] is not None:
        if not cfg['archive'].is_file():
            raise ReferenceSeedError('no reference seed archive at the configured path')
        return restore(archive_bytes(cfg['archive']), cfg['sha256'])
    import store
    with tempfile.TemporaryDirectory(dir=store.DATA, prefix='reference-seed-fetch-') as tmp:
        data = fetch(cfg['url'], cfg['header'], Path(tmp) / 'seed.download', transport)
    return restore(data, cfg['sha256'])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('command', choices=('verify', 'restore'))
    p.add_argument('--archive', required=True)
    p.add_argument('--sha256', required=True)
    a = p.parse_args(argv)
    data = archive_bytes(Path(a.archive))
    if a.command == 'verify':
        with tempfile.TemporaryDirectory(prefix='reference-seed-verify-') as tmp:
            pairs = verify(data, a.sha256, Path(tmp))
        print(json.dumps({'verified_pairs': [{k: x[k] for k in ('symbol', 'case_id', 'report_id', 'version', 'sha256')} for x in pairs]}, indent=2))
    else:
        print(json.dumps(restore(data, a.sha256)))
    return 0


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
