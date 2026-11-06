# Native report package DTO — producer acceptance, 6 November 2026

Producer and web direction accepted as local read contract v1; fresh review state is outside this descriptor. A native client first calls `GET /reports/{report_id}/{version}/artifacts`. In addition to existing download entries, it receives `package: {availability, package_sha256, url}`. When available, `url` is the relative immutable package descriptor route `/packages/{package_sha256}`; the ID is the SHA-256 of the exact render manifest bytes recorded in the database. A package is a verified local render bundle, not report publication or sign-off.

`GET /packages/{package_sha256}` returns:

```json
{
  "package_sha256": "<sha256 of render manifest>",
  "candidate_id": "<chain:address>", "report_id": "<id>", "report_version": "<version>", "report_sha256": "<exact report.json sha256>",
  "report_review_snapshot": {"status": "pending", "authentication": "unverified report assertion"},
  "manifest": {"media_type":"application/json", "sha256":"<package sha256>", "url":"/packages/<package_sha256>/manifest.json"},
  "report": {"availability":"available", "media_type":"application/json", "sha256":"<report sha256>", "url":"/packages/<package_sha256>/report.json"},
  "artifacts": [{"kind":"pillar_irc", "path":"pillar-irc.json", "availability":"available", "media_type":"application/json", "sha256":"<sha256>", "url":"/packages/<package_sha256>/assets/pillar-irc.json"}],
  "evidence": [{"id":"<id>", "path":"evidence/foo.json", "availability":"available", "media_type":"application/octet-stream", "sha256":"<sha256>", "url":"/packages/<package_sha256>/assets/evidence/foo.json"}]
}
```

Arrays preserve the report's actual artifact/evidence identities and exact path strings. Unavailable report artifacts retain their kind/media_type/availability and null path/hash/URL; no fabricated IRC, reasoning or evidence. Every available artifact and evidence path maps to exact report-declared SHA-256; duplicate path with conflicting hashes is rejected. Client fetches report JSON and any desired sidecars/evidence via descriptor URLs and verifies hashes before interpreting. Bytes are served from a single in-memory read that is validated against the bound digest; replacement after validation cannot change that response. The package SHA identifies exact render manifest bytes, not a hash of descriptor JSON; the manifest endpoint allows the client to verify that root. Original report artifact availability is preserved; the outer render DTO separately lists derived PDF/HTML/Markdown downloads. The frozen report_review_snapshot is an unverified field from immutable report bytes; fetch current unverified review separately from report metadata. Package IDs never intentionally alias changed report/render bytes. Missing/tampered data returns 409 or 404, never a fallback; the separate standalone HTML/PDF/Markdown artifact URLs remain available. A client must preserve unknowns and unverified status; packet content is not a factual or authenticated conclusion.

Render installation writes a private staging directory, validates report, manifest, assets and output hashes, then atomically renames into a fresh per-job directory; crash/retry may reuse a valid installed result but never delete/replace it. At-least-once worker concurrency and cancellation limitations still apply and this is not production security. Exact origin CORS through `SCOOBY_WEB_ORIGIN`; GET only, no wildcard or credentials. The native web owner accepted the direction. A separately started local API/worker was tested on the RAY reference; older loopback processes remain unchanged. This branch is not merged.

`reasoning` sidecars may declare `scooby.reasoning/1` or additive `scooby.reasoning/2`. The renderer validates /2 action/rationale/counterevidence/reversal fields and references, including input-to-evidence intersections, and marks the result proposed/pending. The backend does not yet generate /2 through Chat Completions. Existing RAY is /1 and is not modified. Independent producer fixtures passed both positive v1/v2 and 11 negative cases in the bundled reader; actual v2 generation and full cross-consumer acceptance remain pending.
