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
| GET /reports | List report versions with digest, reference context and unverified review |
| GET /reports/{id}/{version}/artifacts | Version-bound HTML, Markdown and PDF availability, hashes and job-specific URLs |
| GET /reports/{id}/{version} | Report version and external review status |
| POST /reports/{id}/{version}/review | Request review, approve, revise or reject exact digest |
| POST /reports/{id}/{version}/render | Queue a visibly pending frontend HTML/PDF draft for exact version |
| POST /investigations/{id}/reason, GET /reasoning/{id} | Optional budgeted model reasoning on operator-supplied evidence |
| GET /artifacts/{job_id}/{name} | Download exact generated artifact |

OpenAPI DTOs are implementation-owned. Frozen candidate v0.1 and report v0.2 are copied byte-for-byte; the frontend validator is the integration authority for bundle semantics. The proposed TL;DR sidecar remains `scooby.pillar-tldr/1`.
