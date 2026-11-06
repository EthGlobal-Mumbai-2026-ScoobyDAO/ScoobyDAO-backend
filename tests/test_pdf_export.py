"""Contract checks for the shared draft PDF print preparation."""
import hashlib
import json
from pathlib import Path
import pytest
from vendor.pdf_export.full_draft_pdf import print_source


def make_reader(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    md = assets / "full.md"
    md.write_text("Full source <script>unsafe</script>", encoding="utf-8")
    report = {"report_id": "r", "report_version": "v1", "evidence": [{"id": "</script><script>bad()</script>", "path": "evidence/a.json", "sha256": "1" * 64}], "artifacts": [{"kind": "markdown", "availability": "available", "path": "full.md", "sha256": hashlib.sha256(md.read_bytes()).hexdigest(), "report_id": "r", "report_version": "v1"}]}
    raw = json.dumps(report).encode()
    (tmp_path / "report.json").write_bytes(raw)
    payload = json.dumps(report).replace("<", "\\u003c")
    (tmp_path / "index.html").write_text('<html><body><script id="data" type="application/json">' + payload + '</script><a href="assets/evidence/a.json">evidence</a><a href="https://example.invalid">unbound</a></body></html>', encoding="utf-8")
    return hashlib.sha256(raw).hexdigest(), md


def test_bound_report_and_safe_companion_index(tmp_path):
    digest, md = make_reader(tmp_path)
    text, identity = print_source(tmp_path / "index.html", tmp_path / "report.json", digest)
    assert digest in identity and "HUMAN REVIEW PENDING" in identity
    assert "Evidence and artifact index" in text
    assert "evidence bytes are not embedded in this PDF" in text
    assert "pdf-asset-" in text and "removeAttribute('href')" in text
    assert "Full source &lt;script&gt;unsafe&lt;/script&gt;" in text
    assert "</script><script>bad()</script>" not in text
    with pytest.raises(ValueError, match="report digest mismatch"):
        print_source(tmp_path / "index.html", tmp_path / "report.json", "0" * 64)
    md.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="Markdown hash mismatch"):
        print_source(tmp_path / "index.html", tmp_path / "report.json", digest)


def test_report_and_embedded_reader_must_match(tmp_path):
    digest, _ = make_reader(tmp_path)
    page = tmp_path / "index.html"
    page.write_text(page.read_text(encoding="utf-8").replace('"report_id": "r"', '"report_id": "other"'), encoding="utf-8")
    with pytest.raises(ValueError, match="reader and report contents differ"):
        print_source(page, tmp_path / "report.json", digest)
