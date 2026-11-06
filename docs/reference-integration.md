# Reference integration track

This local operator flow is separate from the production four-concern admission policy. It consumes a supplied candidate v0.1 and evidence-backed report v0.2 bundle, never infers current fraud from public labels, and preserves pending human review. The newer IRC reader validates schema, exact digest, asset paths/hashes and bound IRC, TL;DR, reasoning and validation-audit profile references.

1. POST `/candidates` with the candidate document; POST `/candidates/{id}/selection` with a scoped diagnostic exception, operator label, reason and `Idempotency-Key`. The operator label is not authentication. POST `/investigations` with candidate and selection IDs.
2. POST `/reports/import` with the run ID and absolute local bundle path. The adapter copies and validates report bytes and all bound assets. It rejects a candidate mismatch.
3. POST `/reports/{id}/{version}/render` with an idempotency key, then poll `/jobs/{id}`. Retrieve `/artifacts/{job_id}/index.html`, `report.md`, `manifest.json`, and, if configured and successful, `report.pdf`. Artifact hashes and report digest are in the manifest.
4. Set `SCOOBY_BROWSER` to an installed headless Chromium-compatible browser. The generated pending-review PDF opens the reader details and appends the exact source-bound Markdown. It uses local isolated browser profiles, not desktop control. Missing Markdown/browser or failure produces explicit PDF unavailable/failure. Validate all pages and content for each real report.

The independent investigation and discovery workstreams remain unchanged. This flow does not perform live collection or model synthesis, and a real packet must identify current source capture vs historical replay and independent evidence vs provider allegations. No new paid call is authorized. The separate human teammate owns publication and World ID/AgentKit.

## Web read DTO

`GET /reports` lists immutable report identity/version/digest, supplied observation timestamps, reference selection context and unverified review. `GET /reports/{id}/{version}/artifacts` returns that identity plus HTML/Markdown/PDF availability, their hashes and job-specific relative URLs; unknown or stale artifacts are unavailable or return 409 on integrity failure. Relative HTML assets are verified against the report on access. Set `SCOOBY_WEB_ORIGIN` to one exact trusted origin without a trailing slash for GET CORS; unset means disabled. CORS is not authentication, and the operator API must remain local. The web app should sandbox the iframe allowing scripts but not same-origin, forms, top navigation or popups.
