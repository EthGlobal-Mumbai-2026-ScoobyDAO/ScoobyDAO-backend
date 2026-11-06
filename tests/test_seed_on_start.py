"""ops/seed_on_start.py: verified, idempotent report seed at container start (no persistent disk)."""
import base64
import hashlib
import importlib.util
import io
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('seed_on_start', ROOT / 'ops' / 'seed_on_start.py')
seed_on_start = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_on_start)

MANIFEST_SHA = 'a' * 64
IDS = 'ethereum-ray-reference,case-diagnostic_hex'


def tiny_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('seed/manifest.json', '{}')
    return buf.getvalue()


@pytest.fixture
def seed_env(monkeypatch, tmp_path):
    data = tiny_zip()
    monkeypatch.setenv('SCOOBY_SEED_ARCHIVE_SHA256', hashlib.sha256(data).hexdigest())
    monkeypatch.setenv('SCOOBY_SEED_MANIFEST_SHA256', MANIFEST_SHA)
    monkeypatch.setenv('SCOOBY_SEED_REPORT_IDS', IDS)
    return data, tmp_path


def capture():
    calls = []

    def restore(path, manifest_sha, ids):
        calls.append((Path(path).read_bytes(), manifest_sha, ids))
        return len(ids)
    return calls, restore


def test_unset_archive_does_nothing(monkeypatch):
    monkeypatch.delenv('SCOOBY_SEED_ARCHIVE', raising=False)
    calls, restore = capture()
    assert seed_on_start.run(restore) == 0 and calls == []


@pytest.mark.parametrize('encode', [lambda b: b, lambda b: base64.b64encode(b), lambda b: base64.encodebytes(b)])
def test_zip_or_base64_text_is_verified_and_restored(seed_env, monkeypatch, encode):
    data, tmp = seed_env
    f = tmp / 'seed.b64'
    f.write_bytes(encode(data))
    monkeypatch.setenv('SCOOBY_SEED_ARCHIVE', str(f))
    calls, restore = capture()
    assert seed_on_start.run(restore) == 2
    assert calls == [(data, MANIFEST_SHA, ['ethereum-ray-reference', 'case-diagnostic_hex'])]


def test_checksum_mismatch_imports_nothing(seed_env, monkeypatch):
    data, tmp = seed_env
    f = tmp / 'seed.zip'
    f.write_bytes(data + b'tampered')
    monkeypatch.setenv('SCOOBY_SEED_ARCHIVE', str(f))
    calls, restore = capture()
    with pytest.raises(seed_on_start.SeedError, match='does not match'):
        seed_on_start.run(restore)
    assert calls == []


@pytest.mark.parametrize('var,value,match', [
    ('SCOOBY_SEED_ARCHIVE_SHA256', 'nothex', 'ARCHIVE_SHA256'),
    ('SCOOBY_SEED_MANIFEST_SHA256', '', 'MANIFEST_SHA256'),
    ('SCOOBY_SEED_REPORT_IDS', ' , ', 'REPORT_IDS'),
])
def test_incomplete_settings_are_refused(seed_env, monkeypatch, var, value, match):
    _, tmp = seed_env
    f = tmp / 'seed.zip'
    f.write_bytes(tiny_zip())
    monkeypatch.setenv('SCOOBY_SEED_ARCHIVE', str(f))
    monkeypatch.setenv(var, value)
    with pytest.raises(seed_on_start.SeedError, match=match):
        seed_on_start.run(capture()[1])


def test_missing_or_garbage_archive(seed_env, monkeypatch):
    _, tmp = seed_env
    monkeypatch.setenv('SCOOBY_SEED_ARCHIVE', str(tmp / 'absent.zip'))
    with pytest.raises(seed_on_start.SeedError, match='no seed archive'):
        seed_on_start.run(capture()[1])
    f = tmp / 'garbage'
    f.write_text('not base64 !!')
    monkeypatch.setenv('SCOOBY_SEED_ARCHIVE', str(f))
    with pytest.raises(seed_on_start.SeedError, match='neither a zip'):
        seed_on_start.run(capture()[1])


def test_main_reports_failure_without_raising(seed_env, monkeypatch, capsys):
    _, tmp = seed_env
    monkeypatch.setenv('SCOOBY_SEED_ARCHIVE', str(tmp / 'absent.zip'))
    assert seed_on_start.main() == 1
    assert 'seed: not imported' in capsys.readouterr().out


def test_start_script_is_valid_posix_sh():
    subprocess.run(['sh', '-n', str(ROOT / 'ops' / 'start.sh')], check=True)


REAL = os.getenv('SCOOBY_TEST_SEED_ARCHIVE')


@pytest.mark.skipif(not REAL, reason='set SCOOBY_TEST_SEED_ARCHIVE to a private seed archive to run')
def test_real_archive_end_to_end(monkeypatch, tmp_path):
    """Opt-in: the real private archive restores 8 pending reports, idempotently. Never committed."""
    import store
    monkeypatch.setattr(store, 'DB', tmp_path / 'state.sqlite3')
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.init()
    import seed_restore
    monkeypatch.setattr(seed_restore, 'DATA', tmp_path)
    monkeypatch.setattr(seed_on_start, 'MAX_BYTES', 50_000_000)
    raw = Path(REAL).read_bytes()
    f = tmp_path / 'seed.b64'
    f.write_bytes(base64.encodebytes(raw))
    monkeypatch.setenv('SCOOBY_SEED_ARCHIVE', str(f))
    monkeypatch.setenv('SCOOBY_SEED_ARCHIVE_SHA256', hashlib.sha256(raw).hexdigest())
    monkeypatch.setenv('SCOOBY_SEED_MANIFEST_SHA256', os.environ['SCOOBY_TEST_SEED_MANIFEST_SHA256'])
    monkeypatch.setenv('SCOOBY_SEED_REPORT_IDS', os.environ['SCOOBY_TEST_SEED_REPORT_IDS'])
    monkeypatch.setenv('SCOOBY_REPORT_RELEASE', 'approved')
    assert seed_on_start.run() == 8
    assert seed_on_start.run() == 8
    with store.db() as c:
        assert c.execute('SELECT count(*) FROM reports').fetchone()[0] == 8
        assert c.execute("SELECT count(*) FROM jobs WHERE kind='render'").fetchone()[0] == 8
