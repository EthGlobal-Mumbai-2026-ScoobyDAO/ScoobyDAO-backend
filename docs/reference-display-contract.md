# Six-reference display contract v1 (`scooby.reference-display/1`)

Owner: orchestrator. Neither session may change this unilaterally; propose amendments to the orchestrator.
Backend PR must commit this file verbatim as `docs/reference-display-contract.md` (amendments via orchestrator only).

## Scope
Display-only. No scouting, case sync, investigation, VAE/model, LLM, provider, or on-chain calls. No render jobs,
no worker needed. No decisions, reviews, World attempts, gate results, approvals or publication are created.

## Seed input
- File: `scooby-six-reference-seed.zip`, SHA-256 `c9fcbf2a32b7c58142389075511989357431b4d457ae89997ebae2261697b8a0`,
  manifest `format: "scooby-six-reference-seed/1"`. Private; never committed. Tests must use a synthetic fixture ZIP
  generated in-test (or env-gated local path), not the real bytes.
- Import code lives on backend main; it MUST NOT execute anything from the ZIP's `backend/` snapshot or `restore.py`.
  Only `manifest.json` and `bundles/**` are consumed; every file is checked against `manifest.files` hashes.
- The six pairs are pinned in code (env cannot substitute identities):

| symbol | candidate_id | case_id | report_id | report_version | report_sha256 |
|---|---|---|---|---|---|
| SHIB | 1:0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce | ac40e79f2e6e1cc2d011d487d8a9d259700591f0f1f85f46bfa22fcd171b25ea | case-shib_reference_research | run-shib_reference_replay_20261107 | 13cfdb303407895cb1c9cf1913a138ac0191c694517606e3f2a3fa5c00bbea99 |
| FET | 1:0xaea46a60368a7bd060eec7df8cba43b7ef41ad85 | 7b460f8e9e93aa02d7c6425b1450ec6e30c97c0beab9539a94261c4ce4daa0b8 | case-reference_fet | run-reference_fet_20261107 | a697d2932eb2b9628229cc4283f1c1d28058953fcfdc20b37f6481ca2d0d923e |
| SPX | 1:0xe0f63a424a4439cbe457d80e4f4b51ad25b2c56c | bbe3daeeccbe5273e4a1f742a6a872dea08e7d8313e99de4ac3ccb6203d04800 | case-reference_spx | run-reference_spx_20261107 | 3f6bea48fd347c4ed8477b12ca10f53d8e06e2714ac4600f96808f78acabc854 |
| YFI | 1:0x0bc529c00c6401aef6d220be8c6ea1667f6ad93e | a7b75ac2adac7deb04fb9b11dacd165eb32a03f49c192b76ae654f6a8ee49e92 | case-reference_yfi | run-reference_yfi_20261107 | 27e70de305585ebac702bcd3c041fe8d952455bbc3d3555de2bad33473d32ef9 |
| GRT | 1:0xc944e90c64b2c07662a292be6244bdf05cda44a7 | 2f156e0056d0629c85967e90b8023ba8f7cbc827462f93a00fb021125ce16b89 | case-reference_grt | run-reference_grt_20261107 | 70de2083725d70dae6874e803667527bf84d4ac303ffb97110ab5530aada7a01 |
| METIS | 1:0x9e32b13ce7f2e80a01932b42553652e053d6ed8e | 72557d92517b2a7e6ac0cea716bc3ca5006c78c8bfc27e3b8eb89fa5ff82b5ab | case-reference_metis | run-reference_metis_20261107 | 8bdbe633a92fdaebb57b7bd68af0dbb9f4f048b844a91f05f28f7fbd1f8541bd |

  YFI and FET are the EARLIER reports; the later incident supplements are NOT in this seed and must not be implied.

## Backend config (new, separate from the existing SCOOBY_SEED_* report seed, which keeps working)
- `SCOOBY_REFERENCE_SEED_ARCHIVE` — path to the ZIP or its base64 (`.b64`, e.g. a Render secret file).
- `SCOOBY_REFERENCE_SEED_SHA256` — must equal the ZIP digest above (also pinned in code); mismatch = import nothing.
- Unset → no-op. Import runs at start (Render free tier has no disk; DB is fresh each boot) and must also be an
  idempotent, transactional merge into an existing nonempty DB: all-or-nothing; identical re-run = no change;
  conflicting existing row (same id/version, different sha/candidate) = refuse, change nothing, log clearly.
- Cases inserted with the manifest's snapshot (digest re-verified), `state='unavailable'`, snapshot expired.
  Run status `reference_only`. No `jobs` rows enqueued. Association table `case_reference_reports` (additive).

## Public (anonymous) reads — identifiers and labels only, no report body
`GET /scouting/cases` and `GET /scouting/cases/{case_id}`: each of the six case items gains
```
"reference": {"kind":"historical_reference","label":"Historical reference — unreviewed",
  "reports":[{"report_id":..., "report_version":..., "report_sha256":..., "association":"historical_reference",
              "review_state":"pending_review", "world_verified":false, "gate_effect":"none"}]}
```
(`reference` is `null` for non-reference cases, as today). For reference cases: `lane` = `unavailable`,
`continuation.availability` = `unavailable`, `continuation.action_url` = null, `research` = null. Never a gate count
or qualification claim. `review_state` comes from the real review tables (so a future genuine approval shows).
`GET /web/v1/review-queue` (existing) lists the six as `pending_review` like any other report.

## Admin reads — real World ID `report_review` session (per-report sessions accepted), Authorization: Bearer
Under `/web/v1/admin/` so existing AdminWebCORS + AdminRouteGuard apply.
1. `GET /web/v1/admin/reference-reports/{report_id}/{version}` →
```
{"schema":"scooby.reference-display/1","report_id","report_version","report_sha256","case_id","candidate_id",
 "symbol","identity":{chain_id,address,symbol},"mode":"historical_replay","review_state":"pending_review",
 "world_verified":false,"gate_effect":"none","association":"historical_reference",
 "labels":["historical","unreviewed","synthetic_lineage","uncalibrated_var","snapshot_expired"],
 "description": <manifest description>,
 "pillars":{name:{"status","quality_issues"}},
 "files":{"report.json":sha256, "<path>":sha256, ...},   // exactly report.json + evidence[]/artifacts[] with path
 "file_base":"/web/v1/admin/reference-reports/{report_id}/{version}/files/"}
```
2. `GET /web/v1/admin/reference-reports/{report_id}/{version}/files/{path:path}` → raw bytes of a path in `files`,
   sha re-verified on every request, path containment enforced. Content types: `.json` application/json,
   `.csv` text/csv; charset=utf-8, `.md` text/plain; charset=utf-8. Headers: `X-Content-Type-Options: nosniff`,
   `Cache-Control: no-store`, `Content-Security-Policy: default-src 'none'; sandbox`, `X-Report-SHA256`, `X-File-SHA256`.
   Frontend recomputes SHA-256 of each fetched file and refuses to chart on mismatch.
3. `GET /web/v1/admin/cases/{case_id}/reference-reports` → `{case_id,candidate_id,association,gate_effect,reports:[item 1 metadata]}`.

## Errors (all endpoints, FastAPI `{"detail": ...}`)
401 no/invalid session · 403 wrong scope or per-report session for another report · 404 unknown or not a linked
reference · 409 integrity failure (bundle/report hash mismatch) — frontend shows "integrity unavailable", never data.

## Chart inputs (frontend parses from files; backend does not compute)
- Price: `evidence/graph/token_daily.json` (+ `graph/manifest.json` for source/subgraph/window). Daily close, USD.
- VAE: `evidence/legacy_metrics.json`, `evidence/legacy_reconstructions.csv` (50 reconstructions; plot 5),
  `evidence/graph_model/risk-metrics.json`, `run-manifest.json`. Four-day horizon, in-sample, unseeded, NOT backtested or
  calibrated; never "maximum loss" or raw "Low" risk label as a claim. SPX fundamentals unavailable.
- Pillar text: `pillar-tldr.json`, `pillar-irc.json`, `report.json.pillars`; sources: `source-ledger.json`.
- Missing/unavailable files or `availability:"unavailable"` artifacts (e.g. pdf) render as explicit gaps.

## Frontend journey
Case board (public) shows six reference cards with historical/unreviewed label and rationale → "Read report"
→ review desk per-report World ID session → graphical five-pillar reader. No agent/model/investigation/on-chain
action is reachable from these cards or the reader (challenge/continue/World-attempt buttons hidden or disabled for
reference cases; review sign-off remains the existing separate desk action and is not triggered by reading).
