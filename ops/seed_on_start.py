"""Optional report seed at container start, for hosts without a persistent disk (Render free plan).

Unset SCOOBY_SEED_ARCHIVE and this does nothing. When set, every start:

1. reads the archive (a .zip, or its base64 text, as a Render Secret File holds text),
2. refuses it unless its SHA-256 equals SCOOBY_SEED_ARCHIVE_SHA256,
3. runs seed_restore.restore with SCOOBY_SEED_MANIFEST_SHA256 and the report ids in SCOOBY_SEED_REPORT_IDS.

seed_restore itself requires SCOOBY_REPORT_RELEASE=approved, verifies the manifest and every report digest, records
the reports as pending human review, queues renders, and is idempotent. Nothing here admits a case, verifies World ID,
approves, publishes or calls a model. The archive never enters the image or the repository, and its contents are
never logged.

    SCOOBY_SEED_ARCHIVE=/etc/secrets/report-seed.zip.b64
    SCOOBY_SEED_ARCHIVE_SHA256=<sha256 of the .zip bytes>
    SCOOBY_SEED_MANIFEST_SHA256=<sha256 of manifest.json>
    SCOOBY_SEED_REPORT_IDS=ethereum-ray-reference,case-diagnostic_hex,...
"""
from __future__ import annotations
import base64
import binascii
import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
SHA = re.compile('[0-9a-f]{64}')
MAX_BYTES = 50_000_000


class SeedError(RuntimeError):
    pass


def archive_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise SeedError('seed archive is too large')
    if raw[:4] == b'PK\x03\x04':
        return raw
    try:
        data = base64.b64decode(b''.join(raw.split()), validate=True)
    except (binascii.Error, ValueError):
        raise SeedError('seed archive is neither a zip file nor base64 of one') from None
    if data[:4] != b'PK\x03\x04':
        raise SeedError('decoded seed archive is not a zip file')
    return data


def settings() -> tuple[Path, str, str, list[str]] | None:
    archive = os.getenv('SCOOBY_SEED_ARCHIVE', '').strip()
    if not archive:
        return None
    archive_sha = os.getenv('SCOOBY_SEED_ARCHIVE_SHA256', '').strip().lower()
    manifest_sha = os.getenv('SCOOBY_SEED_MANIFEST_SHA256', '').strip().lower()
    ids = [x.strip() for x in os.getenv('SCOOBY_SEED_REPORT_IDS', '').split(',') if x.strip()]
    if not SHA.fullmatch(archive_sha):
        raise SeedError('SCOOBY_SEED_ARCHIVE_SHA256 must be a 64-character hex SHA-256')
    if not SHA.fullmatch(manifest_sha):
        raise SeedError('SCOOBY_SEED_MANIFEST_SHA256 must be a 64-character hex SHA-256')
    if not ids:
        raise SeedError('SCOOBY_SEED_REPORT_IDS lists no report ids')
    return Path(archive), archive_sha, manifest_sha, ids


def run(restore=None) -> int:
    cfg = settings()
    if cfg is None:
        return 0
    path, archive_sha, manifest_sha, ids = cfg
    if not path.is_file():
        raise SeedError(f'no seed archive at {path}')
    data = archive_bytes(path)
    if hashlib.sha256(data).hexdigest() != archive_sha:
        raise SeedError('seed archive SHA-256 does not match SCOOBY_SEED_ARCHIVE_SHA256; nothing imported')
    if restore is None:
        from seed_restore import restore
    from store import DATA
    with tempfile.TemporaryDirectory(dir=DATA) as tmp:
        zip_path = Path(tmp) / 'report-seed.zip'
        zip_path.write_bytes(data)
        return restore(zip_path, manifest_sha, ids)


def main() -> int:
    try:
        n = run()
    except Exception as e:  # report and let the API start anyway
        print(f'seed: not imported: {type(e).__name__}: {e}', flush=True)
        return 1
    if n:
        print(f'seed: {n} report versions present, pending human review; renders queued if new', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
