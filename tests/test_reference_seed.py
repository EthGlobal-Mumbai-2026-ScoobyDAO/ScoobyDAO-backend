"""reference_seed.py: verified, pinned, all-or-nothing six-reference merge (docs/reference-display-contract.md).

Uses a synthetic archive built in-test (tests/reference_seed_fixture.py). The private seed itself runs only in the
env-gated test at the end: SCOOBY_REAL_REFERENCE_SEED=/path/to/scooby-six-reference-seed.zip.
"""
import json
import os
import sqlite3
from pathlib import Path

import pytest

import reference_seed
import reference_seed_fixture as fx

COUNTED = ('cases', 'case_reference_reports', 'reports', 'investigations', 'selections', 'candidates', 'case_snapshots',
           'diagnostic_imports', 'pillars', 'jobs', 'reviews', 'case_decisions', 'case_challenges', 'case_world_attempts',
           'case_challenge_admin', 'budget_reservations', 'reasoning_inputs', 'seed_imports')


@pytest.fixture
def data(monkeypatch, tmp_path):
    import store
    monkeypatch.setattr(store, 'DB', tmp_path / 'state.sqlite3')
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.init()
    return tmp_path


def pin(monkeypatch, sha, pins):
    monkeypatch.setattr(reference_seed, 'PINNED_ZIP_SHA256', sha)
    monkeypatch.setattr(reference_seed, 'PINNED_PAIRS', pins)


def counts():
    from store import db
    with db() as c:
        return {t: c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in COUNTED}


def dump():
    from store import db
    with db() as c:
        return [line for line in c.iterdump()]


def bundle_dirs(root):
    b = root / 'bundles'
    return sorted(p.name for p in b.iterdir()) if b.exists() else []


def seeded(monkeypatch, **kw):
    data, sha, pins = fx.build(**kw)
    pin(monkeypatch, sha, pins)
    return data, sha, pins


def test_fresh_restore_creates_exactly_six_display_only_pairs(data, monkeypatch):
    zip_bytes, sha, pins = seeded(monkeypatch)
    result = reference_seed.restore(zip_bytes, sha)
    assert result['pairs'] == 6 and result['bundles_installed'] == 6 and result['rows_written'] > 0
    n = counts()
    assert {k: n[k] for k in ('cases', 'case_reference_reports', 'reports', 'investigations', 'selections', 'case_snapshots', 'diagnostic_imports')} == \
        dict.fromkeys(('cases', 'case_reference_reports', 'reports', 'investigations', 'selections', 'case_snapshots', 'diagnostic_imports'), 6)
    assert n['pillars'] == 30
    for t in ('jobs', 'reviews', 'case_decisions', 'case_challenges', 'case_world_attempts', 'case_challenge_admin',
              'budget_reservations', 'reasoning_inputs', 'seed_imports'):
        assert n[t] == 0, t
    from store import db
    with db() as c:
        assert {r[0] for r in c.execute('SELECT state FROM cases')} == {'unavailable'}
        assert {r[0] for r in c.execute('SELECT status FROM investigations')} == {'reference_only'}
        assert {r[0] for r in c.execute('SELECT kind FROM selections')} == {'diagnostic_exception'}
        for sym, (cid, case_id, rid, ver, rsha) in pins.items():
            row = c.execute('SELECT r.sha256,r.path,k.candidate_id,s.reason,k.current_snapshot FROM case_reference_reports l JOIN reports r ON r.id=l.report_id '
                            'AND r.version=l.version JOIN cases k ON k.id=l.case_id JOIN investigations i ON i.id=r.run_id '
                            'JOIN selections s ON s.id=i.selection_id WHERE l.case_id=? AND l.report_id=? AND l.version=?',
                            (case_id, rid, ver)).fetchone()
            assert row['sha256'] == rsha and row['candidate_id'] == cid and Path(row['path']) == data / 'bundles' / rsha
            assert row['reason'].startswith(f'Synthetic {sym} historical reference')
    assert bundle_dirs(data) == sorted(p[4] for p in pins.values())
    # the archive's backend snapshot and restore utility are hash-checked in memory, never written or run
    assert not [p for p in data.rglob('*') if p.name in ('restore.py', 'app.py') or p.name == 'backend']


def test_repeat_restore_changes_nothing(data, monkeypatch):
    zip_bytes, sha, _ = seeded(monkeypatch)
    reference_seed.restore(zip_bytes, sha)
    before, dirs = dump(), bundle_dirs(data)
    again = reference_seed.restore(zip_bytes, sha)
    assert again == {'pairs': 6, 'rows_written': 0, 'bundles_installed': 0}
    assert dump() == before and bundle_dirs(data) == dirs


def test_upgrade_merges_into_existing_nonempty_database(data, monkeypatch):
    from store import db, now
    with db() as c:  # an existing seed report (main's SCOOBY_SEED_* format) and its private-draft marker
        c.execute("INSERT INTO candidates VALUES('1:0xabc','{}',?)", (now(),))
        c.execute("INSERT INTO selections VALUES('seed-r1','1:0xabc','diagnostic_exception','seed import','x',?,'seed-sel:r1')", (now(),))
        c.execute("INSERT INTO investigations VALUES('r1','1:0xabc','seed-r1','reference_only',?,'seed-run:r1')", (now(),))
        c.execute("INSERT INTO reports VALUES('existing-report','v1','r1',?,'/nonexistent',?)", ('e' * 64, now()))
        c.execute("INSERT INTO seed_imports VALUES('existing-report','v1')")
        c.execute("INSERT INTO jobs(id,kind,ref,state,available,idem,created) VALUES('j1','render','{}','done',0,'k1',0)")
    before = counts()
    zip_bytes, sha, _ = seeded(monkeypatch)
    reference_seed.restore(zip_bytes, sha)
    after = counts()
    assert after['reports'] == before['reports'] + 6 and after['seed_imports'] == 1 and after['jobs'] == 1
    with db() as c:
        assert c.execute("SELECT sha256,path FROM reports WHERE id='existing-report'").fetchone()[:] == ('e' * 64, '/nonexistent')


def refused(data, zip_bytes, sha, match):
    before, dirs = dump(), bundle_dirs(data)
    with pytest.raises(reference_seed.ReferenceSeedError, match=match):
        reference_seed.restore(zip_bytes, sha)
    assert dump() == before and bundle_dirs(data) == dirs
    assert not [p for p in data.iterdir() if p.name.startswith('reference-seed-')]


def test_bad_zip_sha_or_unpinned_archive_writes_nothing(data, monkeypatch):
    zip_bytes, sha, _ = seeded(monkeypatch)
    refused(data, zip_bytes, 'a' * 64, 'SHA-256')
    mid = len(zip_bytes) // 2
    refused(data, zip_bytes[:mid] + bytes([zip_bytes[mid] ^ 1]) + zip_bytes[mid + 1:], sha, 'SHA-256')
    monkeypatch.setattr(reference_seed, 'PINNED_ZIP_SHA256', 'b' * 64)  # env matches the bytes but not the code pin
    refused(data, zip_bytes, sha, 'SHA-256')


def test_tampered_bundle_file_writes_nothing(data, monkeypatch):
    def tamper(m):
        m['bundles/fet/report.md'] = m['bundles/fet/report.md'] + b'tampered'
    zip_bytes, sha, _ = seeded(monkeypatch, tamper=tamper)
    refused(data, zip_bytes, sha, 'file hash mismatch')


def test_tampered_backend_snapshot_is_still_refused(data, monkeypatch):
    zip_bytes, sha, _ = seeded(monkeypatch, tamper=lambda m: m.__setitem__('restore.py', b'import os'))
    refused(data, zip_bytes, sha, 'file hash mismatch: restore.py')


def test_manifest_identity_must_match_code_pins(data, monkeypatch):
    _, _, clean_pins = fx.build()

    def other_candidate(manifest, members):
        manifest['pairs'][2]['description'] = 'changed'   # still self-consistent, but...
        manifest['pairs'][2]['report_sha256'] = 'c' * 64   # ...identity differs from the pin
    zip_bytes, sha, _ = fx.build(mutate=other_candidate)
    pin(monkeypatch, sha, clean_pins)
    refused(data, zip_bytes, sha, 'pinned identity: SPX')


def test_snapshot_digest_and_case_identity_are_reverified(data, monkeypatch):
    def bad_snapshot(manifest, members):
        manifest['pairs'][0]['snapshot']['policy_digest'] = 'd' * 64
    refused(data, *seeded(monkeypatch, mutate=bad_snapshot)[:2], 'snapshot digest mismatch')

    def bad_case(manifest, members):
        manifest['pairs'][1]['case_id'] = 'e' * 64
    zip_bytes, sha, pins = fx.build(mutate=bad_case)
    pin(monkeypatch, sha, pins)
    refused(data, zip_bytes, sha, 'case identity mismatch')


def test_unlisted_or_unsafe_members_are_refused(data, monkeypatch):
    refused(data, *seeded(monkeypatch, extra={'bundles/extra.json': b'{}'})[:2], 'differ from manifest')
    refused(data, *seeded(monkeypatch, extra={'../escape.txt': b'x'})[:2], 'unsafe archive entry')
    refused(data, b'PK\x03\x04not a zip', fx.h(b'PK\x03\x04not a zip'), 'SHA-256')


def test_bundle_must_be_pending_historical_replay(data, monkeypatch):
    def approved(manifest, members):
        doc = json.loads(members['bundles/grt/report.json'])
        doc['mode'] = 'live'
        raw = json.dumps(doc).encode()
        members['bundles/grt/report.json'] = raw
        manifest['pairs'][4]['report_sha256'] = fx.h(raw)
    refused(data, *seeded(monkeypatch, mutate=approved)[:2], 'mode, review or synthetic lineage mismatch: GRT')


def test_conflicting_existing_report_refuses_everything(data, monkeypatch):
    zip_bytes, sha, pins = seeded(monkeypatch)
    _, _, rid, ver, _ = pins['YFI']
    from store import db, now
    with db() as c:
        c.execute("INSERT INTO candidates VALUES('1:0xdef','{}',?)", (now(),))
        c.execute("INSERT INTO selections VALUES('s-x','1:0xdef','diagnostic_exception','x','x',?,'s-x')", (now(),))
        c.execute("INSERT INTO investigations VALUES('run-x','1:0xdef','s-x','reference_only',?,'run-x')", (now(),))
        c.execute('INSERT INTO reports VALUES(?,?,?,?,?,?)', (rid, ver, 'run-x', '0' * 64, '/elsewhere', now()))
    refused(data, zip_bytes, sha, 'immutable report conflict: YFI')


def test_existing_live_case_with_another_snapshot_is_a_conflict(data, monkeypatch):
    zip_bytes, sha, pins = seeded(monkeypatch)
    cid, case_id, *_ = pins['METIS']
    from store import db, now
    with db() as c:
        c.execute("INSERT INTO case_snapshots VALUES('9'||?,?,'{}','{}',?,'{}',0,0)", ('9' * 63, cid, 'f' * 64))
        c.execute("INSERT INTO cases VALUES(?,?,?,'monitoring',?)", (case_id, cid, '9' * 64, now()))
    refused(data, zip_bytes, sha, 'another candidate or snapshot: METIS')


def test_failure_mid_transaction_rolls_back_rows_and_new_bundles(data, monkeypatch):
    zip_bytes, sha, _ = seeded(monkeypatch)
    real, calls = reference_seed._merge, []

    def failing(c, x, *a):
        calls.append(x['symbol'])
        if len(calls) == 4:
            raise sqlite3.OperationalError('simulated failure mid-transaction')
        return real(c, x, *a)
    monkeypatch.setattr(reference_seed, '_merge', failing)
    before = dump()
    with pytest.raises(sqlite3.OperationalError):
        reference_seed.restore(zip_bytes, sha)
    assert dump() == before and bundle_dirs(data) == [] and len(calls) == 4
    monkeypatch.setattr(reference_seed, '_merge', real)
    assert reference_seed.restore(zip_bytes, sha)['pairs'] == 6   # a clean retry succeeds


def test_altered_installed_bundle_is_refused_not_overwritten(data, monkeypatch):
    zip_bytes, sha, pins = seeded(monkeypatch)
    reference_seed.restore(zip_bytes, sha)
    md = data / 'bundles' / pins['SHIB'][4] / 'report.md'
    md.write_bytes(md.read_bytes() + b'changed')
    with pytest.raises(reference_seed.ReferenceSeedError, match='installed bundle differs'):
        reference_seed.restore(zip_bytes, sha)
    assert md.read_bytes().endswith(b'changed')


def test_base64_archive_and_env_settings(data, monkeypatch, tmp_path):
    import base64
    zip_bytes, sha, _ = seeded(monkeypatch)
    path = tmp_path / 'seed.zip.b64'
    path.write_bytes(base64.encodebytes(zip_bytes))
    monkeypatch.delenv('SCOOBY_REFERENCE_SEED_ARCHIVE', raising=False)
    assert reference_seed.run_from_env() is None
    monkeypatch.setenv('SCOOBY_REFERENCE_SEED_ARCHIVE', str(path))
    monkeypatch.setenv('SCOOBY_REFERENCE_SEED_SHA256', 'not-hex')
    with pytest.raises(reference_seed.ReferenceSeedError):
        reference_seed.run_from_env()
    monkeypatch.setenv('SCOOBY_REFERENCE_SEED_SHA256', sha)
    assert reference_seed.run_from_env()['pairs'] == 6


def test_store_init_adds_the_link_table_to_an_older_database(monkeypatch, tmp_path):
    import store
    monkeypatch.setattr(store, 'DB', tmp_path / 'old.sqlite3')
    store.init()
    with store.db() as c:
        c.execute('DROP TABLE case_reference_reports')
    store.init()
    with store.db() as c:
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name='case_reference_reports'").fetchone()


def test_cli_verify_writes_no_database(tmp_path, monkeypatch):
    zip_bytes, sha, pins = seeded(monkeypatch)
    path = tmp_path / 'seed.zip'
    path.write_bytes(zip_bytes)
    import io
    from contextlib import redirect_stdout
    out = io.StringIO()
    with redirect_stdout(out):
        assert reference_seed.main(['verify', '--archive', str(path), '--sha256', sha]) == 0
    assert [x['symbol'] for x in json.loads(out.getvalue())['verified_pairs']] == list(pins)


REAL = os.getenv('SCOOBY_REAL_REFERENCE_SEED')


@pytest.mark.skipif(not REAL, reason='set SCOOBY_REAL_REFERENCE_SEED to the private seed ZIP to run')
def test_real_private_seed_restores_and_repeats(data):
    zip_bytes = reference_seed.archive_bytes(Path(REAL))
    first = reference_seed.restore(zip_bytes, reference_seed.PINNED_ZIP_SHA256)
    assert first['pairs'] == 6 and first['bundles_installed'] == 6
    n = counts()
    assert n['cases'] == n['case_reference_reports'] == n['reports'] == 6
    assert n['jobs'] == n['reviews'] == n['case_decisions'] == n['case_world_attempts'] == 0
    before = dump()
    assert reference_seed.restore(zip_bytes, reference_seed.PINNED_ZIP_SHA256) == {'pairs': 6, 'rows_written': 0, 'bundles_installed': 0}
    assert dump() == before
