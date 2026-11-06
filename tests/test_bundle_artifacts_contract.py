"""Producer-bundle consumer seam; NOT an automatic investigation acceptance test.

Synthetic fixture import exercises the existing renderer while real producer and
case workflow owners implement the shared end-to-end path.
"""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import app
from worker import work_one

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/fixtures/reasoning-compatibility/synthetic-v2-r2"


def post(client, url, body, key=None):
    return client.post(url, json=body, headers={"Idempotency-Key": key} if key else {})


def make_run(client, address, suffix):
    candidate = json.loads((ROOT / "tests/candidate.json").read_bytes())
    candidate["candidate_id"] = "1:" + address.lower()
    candidate["identity"] = {"chain_id": 1, "address": address, "symbol": "TEST-ONLY"}
    candidate["mode"] = "synthetic_demo"
    result = post(client, "/candidates", {"payload": candidate})
    assert result.status_code == 200, result.text
    selection = post(client, "/candidates/" + candidate["candidate_id"] + "/selection", {"kind": "diagnostic_exception", "actor": "SYNTHETIC TEST", "reason": "Offline renderer fixture only"}, "bundle-selection-" + suffix)
    assert selection.status_code == 200, selection.text
    run = post(client, "/investigations", {"candidate_id": candidate["candidate_id"], "selection_id": selection.json()["id"]}, "bundle-run-" + suffix)
    assert run.status_code == 200, run.text
    return candidate["candidate_id"], run.json()["id"]


def test_bound_synthetic_producer_bundle_to_draft_artifacts(tmp_path):
    """Bound input -> import -> worker render -> retrieved draft; no live research."""
    client = TestClient(app)
    report_bytes = (FIXTURE / "report.json").read_bytes()
    report = json.loads(report_bytes)
    candidate_id, run_id = make_run(client, report["identity"]["address"], "positive")
    _, wrong_run = make_run(client, "0x" + "2" * 40, "wrong")
    wrong = post(client, "/reports/import", {"run_id": wrong_run, "bundle_path": str(FIXTURE)})
    assert wrong.status_code == 409
    tampered = tmp_path / "tampered"
    shutil.copytree(FIXTURE, tampered)
    with (tampered / "evidence/a.json").open("ab") as evidence:
        evidence.write(b"tampered")
    rejected = post(client, "/reports/import", {"run_id": run_id, "bundle_path": str(tampered)})
    assert rejected.status_code == 422
    imported = post(client, "/reports/import", {"run_id": run_id, "bundle_path": str(FIXTURE)})
    assert imported.status_code == 200, imported.text
    expected = hashlib.sha256(report_bytes).hexdigest()
    assert imported.json()["sha256"] == expected
    report_id, version = report["report_id"], report["report_version"]
    listing = client.get("/reports").json()
    item = next(x for x in listing if (x["report_id"], x["report_version"]) == (report_id, version))
    assert item["candidate_id"] == candidate_id and item["report_sha256"] == expected
    assert item["mode"] == "synthetic_demo" and item["review"]["status"] == "pending"
    exact = client.get(f"/reports/{report_id}/{version}").json()
    assert exact["run_id"] == run_id and exact["reviews"] == []
    render = post(client, f"/reports/{report_id}/{version}/render", {}, "bundle-render")
    assert render.status_code == 200
    job_id = render.json()["job_id"]
    for _ in range(10):
        if client.get("/jobs/" + job_id).json()["state"] == "done":
            break
        assert work_one()
    assert client.get("/jobs/" + job_id).json()["state"] == "done"
    artifacts = client.get(f"/reports/{report_id}/{version}/artifacts").json()
    assert artifacts["candidate_id"] == candidate_id and artifacts["report_sha256"] == expected
    assert artifacts["render_status"] == "pending_review_draft"
    html_ref = artifacts["artifacts"]["html"]
    html = client.get(html_ref["url"]).content
    assert hashlib.sha256(html).hexdigest() == html_ref["sha256"]
    assert b"PENDING REVIEW" in html and candidate_id.encode() in html
    page = tmp_path / "index.html"
    page.write_bytes(html)
    if shutil.which("node"):
        subprocess.run(["node", str(ROOT / "tests/reader_dom_contract.js"), str(page)], check=True, capture_output=True)
    pdf_ref = artifacts["artifacts"]["pdf"]
    if os.environ.get("SCOOBY_BROWSER"):
        assert pdf_ref["availability"] == "available"
        pdf = client.get(pdf_ref["url"]).content
        assert hashlib.sha256(pdf).hexdigest() == pdf_ref["sha256"]
        parsed = PdfReader(BytesIO(pdf))
        text = "\n".join(page.extract_text() or "" for page in parsed.pages)
        assert "SYNTHETIC TEST ONLY" in text and "Evidence and artifact index" in text
        for expected_text in ("SYNTHETIC TEST ONLY: defer the fictional interaction.", "SYNTHETIC rationale.", "SYNTHETIC counterevidence.", "SYNTHETIC reversal condition."):
            assert expected_text in text
        destinations = parsed.named_destinations
        found = 0
        for page in parsed.pages:
            for ref in page.get("/Annots", []):
                annot = ref.get_object()
                action = annot.get("/A")
                action = action.get_object() if action else {}
                assert action.get("/S") != "/URI"
                dest = annot.get("/Dest") or action.get("/D")
                if isinstance(dest, str):
                    assert dest in destinations
                    found += 1
        assert found > 0
    else:
        assert pdf_ref["availability"] == "unavailable"
