"""Optional acceptance against an operator-supplied, hash-pinned captured bundle."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import pytest
from test_reader_profiles import ROOT, builder


def test_captured_bundle_reader(tmp_path):
    supplied = os.environ.get("SCOOBY_CAPTURED_BUNDLE")
    if not supplied:
        pytest.skip("No captured bundle supplied; no external data included in this test")
    expected = os.environ.get("SCOOBY_CAPTURED_REPORT_SHA256", "")
    assert len(expected) == 64, "Provide the expected report SHA-256 separately"
    report = Path(supplied) / "report.json"
    assert hashlib.sha256(report.read_bytes()).hexdigest() == expected
    if not shutil.which("node"):
        pytest.skip("Node is required for rendered DOM checks")
    out = tmp_path / "reader"
    builder.build(report, out)
    subprocess.run(["node", str(ROOT / "tests/reader_dom_contract.js"), str(out / "index.html"), "--captured-partial"], check=True, timeout=30)
