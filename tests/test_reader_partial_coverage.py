from pathlib import Path
import hashlib, json, shutil, subprocess
import pytest
from test_reader_profiles import ROOT, builder


def test_partial_producer_without_reasoning_keeps_summary_and_status(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node is required to execute the reader DOM contract")
    fixture = ROOT / "tests/fixtures/reasoning-compatibility/synthetic-v2-r2"
    source = tmp_path / "bundle"
    shutil.copytree(fixture, source)
    path = source / "report.json"
    report = json.loads(path.read_bytes())
    report["artifacts"] = [a for a in report["artifacts"] if a["kind"] not in ("reasoning", "pillar_irc", "validation_audit")]
    assert all(p["status"] == "partial" for p in report["pillars"].values())
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    digest = json.loads((source / "digest.json").read_bytes())
    digest["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (source / "digest.json").write_text(json.dumps(digest), encoding="utf-8")
    out = tmp_path / "out"
    builder.build(path, out)
    subprocess.run(["node", str(ROOT / "tests/reader_dom_contract.js"), str(out / "index.html"), "--partial-only"], check=True, timeout=30)


def test_day_precision_chart_preserves_date_gaps(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node is required to execute the reader DOM contract")
    fixture = ROOT / "tests/fixtures/reasoning-compatibility/synthetic-v2-r2"
    source = tmp_path / "bundle"
    shutil.copytree(fixture, source)
    path = source / "report.json"
    report = json.loads(path.read_bytes())
    report["pillars"]["technical_health"]["series"] = [{
        "id": "observed_daily_closes", "unit": "USD", "method": "Synthetic dated observations", "quality": "unvalidated", "evidence_ids": ["test-a"],
        "window": {"start": "2026-11-03", "end": "2026-11-06", "precision": "day"},
        "points": [{"time": "2026-11-03", "value": 1}, {"time": "2026-11-04", "value": 2}, {"time": "2026-11-06", "value": 3}], "unknown_reason": None}]
    path.write_text(json.dumps(report), encoding="utf-8")
    digest = json.loads((source / "digest.json").read_bytes())
    digest["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (source / "digest.json").write_text(json.dumps(digest), encoding="utf-8")
    out = tmp_path / "out"
    builder.build(path, out)
    subprocess.run(["node", str(ROOT / "tests/reader_dom_contract.js"), str(out / "index.html"), "--day-series"], check=True, timeout=30)
