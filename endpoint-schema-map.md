# Endpoint and schema map, v0.1 (local operator API)

All routes below are local operator routes; no authentication or production authorization is asserted. The service binds loopback by default. Idempotency keys and names record local test intent, not authenticated identity.

| Route | Purpose |
|---|---|
| GET /readiness/honeypot | Static milestone integration inventory, not a live gate |
| GET /health, /status, /schemas | Health, worker queue and frozen schema hashes |
| POST /candidates, GET /candidates, /candidates/{id} | Import schema-validated candidate, monitor and inspect |
| POST /candidates/{id}/selection | Human selection or diagnostic exception; immutable audit |
| POST /investigations, GET /investigations/{id} | Start only after selection; durable pillar statuses |
| POST /investigations/{id}/cancel, /resume | Stop or resume incomplete work |
| POST /scans, GET /jobs/{id} | Schedule a bounded scan or inspect work |
| GET /investigations/{id}/events | Audit progress |
| POST /reports/import | Validate a complete producer bundle using frontend adapter; bind exact bytes |
| GET /packages/{sha}, /packages/{sha}/manifest.json, /packages/{sha}/report.json, /packages/{sha}/assets/{path} | Immutable package descriptor, exact root manifest, report and source-bound assets |
| GET /reports | List report versions with digest, reference context and unverified review |
| GET /reports/{id}/{version}/artifacts | Version-bound HTML, Markdown and PDF availability, hashes and job-specific URLs |
| GET /reports/{id}/{version} | Report version and external review status |
| POST /reports/{id}/{version}/review | Request review, approve, revise or reject exact digest |
| POST /reports/{id}/{version}/render | Queue a visibly pending frontend HTML/PDF draft for exact version |
| POST /investigations/{id}/reason, GET /reasoning/{id} | Optional budgeted model reasoning on operator-supplied evidence |
| GET /artifacts/{job_id}/{name} | Download exact generated artifact |

OpenAPI DTOs are implementation-owned. Frozen candidate v0.1 and report v0.2 are copied byte-for-byte; the frontend validator is the integration authority for bundle semantics. The proposed TL;DR sidecar remains `scooby.pillar-tldr/1`.

## Publication v1 (operator; bearer `SCOOBY_OPERATOR_TOKEN` on mutating routes)

| Route | Purpose |
|---|---|
| POST /publication/v1/targets | `{report_id, version, params}` → `scooby.publication-target/1` + claim manifest; Idempotency-Key; timing rules → 422 |
| GET /publication/v1/targets/{id} | Target, manifest and current status projection |
| POST /publication/v1/targets/{id}/attempts | `{decision: approve\|reject\|revise, reason}` → World device grant; one pending per target |
| GET /publication/v1/attempts/{id} | Poll-on-read; at most one World poll per interval |
| POST /publication/v1/attempts/{id}/cancel | Pending → cancelled; later World success is ignored and audited |
| POST /publication/v1/targets/{id}/publish | Explicit publish request → outbox id; 503 unless publishing is enabled and preflight passes |
| POST /publication/v1/targets/{id}/revoke | Stop before broadcast; record after confirmation |

## Web v1 (shapes from `ScoobyDAO-web/src/lib/types.ts`)

| Route | Purpose |
|---|---|
| GET /web/v1/health | `{ok: true}` |
| GET /web/v1/reports, /web/v1/reports/{report_id@version} | `Report` (manifest = claim manifest, manifestHash = 0x+claim_hash) + reportSha256, targetDigest, publicationState |
| GET /web/v1/reports/{id}/raw | Exact `report.json` bytes |
| POST /web/v1/reports/{id}/approve | Start (or reuse) an approve attempt → `Approval` |
| GET /web/v1/approvals/{id} | `Approval` (pending/approved/denied/expired/rejected_not_reviewer/spent); never returns device codes or tokens |

## Case orchestration (runtime proposal)

`GET /scouting/cases` (alias `/cases`), `GET /scouting/cases/{id}`, `GET /scouting/schema`, `GET /scouting/sources`, `GET /scouting/leads`, `GET /scouting/social-candidate-status`; `POST /scouting/cases/refresh`; `POST /scouting/cases/{id}/challenge`; `GET /scouting/challenges/{id}`. Human continuation/deny/revoke/revise remain unavailable (503) until a verifier exists. `POST /reference-runs` is a no-research reference import lane. See `docs/case-orchestration.md`.
