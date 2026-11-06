# Deployment-readiness checkpoint — 6 November 2026 IST

**Status: private single-host staging is prepared but not locally container-tested; public deployment is blocked.** There is no verified production authentication, authorization, hardened upload boundary, migration path, production queue or release topology. An exact-origin CORS rule does not prevent direct requests. Binding the current operator API to a public interface or routing all of it through a public reverse proxy would expose candidate import, local file import, review assertions, job mutation and model operations. Do not expose those routes until a reviewed trust boundary is enforced and tested.

## What is implemented

FastAPI exposes a local operator API, immutable report package read endpoints, digest-bound render manifests and exact-byte report, IRC, reasoning, TL;DR and evidence assets. Huey/SQLite executes jobs in a separate process. Artifacts are installed through private staging and an atomic rename, validated before acceptance, and never intentionally replaced at an installed job path. A configured Chromium-compatible headless browser generates a pending draft PDF from expanded reader plus bound Markdown. Original report JSON stays unchanged; a derived PDF's availability is in the outer render manifest, not a retroactive change to the report. The optional Chat Completions provider has a whole-database attempt cap defaulting to zero; token/rate/cost budgets remain incomplete. The RAY reference demonstrates local bundle import, not autonomous deep research or current honeypot confirmation.

## Protected topology required before deployment

A production-reviewed authentication/authorization component must terminate public traffic and enforce a **deny-by-default route allowlist**. Only the specific read endpoints and package assets intended for the web should be exposed, after privacy and abuse review. Keep candidate selection, local-path import, investigation/review writes, scans, reason/model jobs, worker control and raw admin surfaces on a separately authenticated and authorized operator network/interface. Restrict API docs/OpenAPI as appropriate. A gateway is a proposed boundary; it has not been implemented or tested here, and must prevent bypass via direct port access, forwarded headers, path normalization and alternate origins. Apply TLS, request size/rate limits, safe media handling, CSRF/session protections where applicable, logging without secrets, and a review of which source evidence may be public. Current local actor strings and review receipts do not authenticate identity.

Publication and World ID/AgentKit human sign-off are **owned by the human teammate**; no integration is claimed. World ID is out of scope for this checkpoint and is not required for private staging. A future integration requires a reviewed interface and threat model covering callback/redirect URLs and origins, proof verification, nonce/replay protection, report ID/version/digest binding, reviewer authorization, expiry/revocation, failure and re-review semantics, privacy and operator/public route access. Never trust a frontend boolean or equate wallet/agent registration with human approval.

## Local commands for review, not deployment

Requires Python 3.11 and `python -m pip install -r requirements.txt`; the VAE dependencies in `modules/investigation/requirements-vae.txt` are optional, heavy and not needed for API/worker. On a reviewed target, provision a compatible Chromium or Edge executable and usable system fonts; only local Windows Edge was verified for the reference PDF. Linux/browser packaging, font fidelity, resource limits and all-page visual output need target-specific verification. Start from repository root with a persistent `SCOOBY_DATA` directory outside the checkout:

```sh
python -m uvicorn app:app --host 127.0.0.1 --port 8000
python -m huey.bin.huey_consumer worker.huey -w 1
```

Run as separate supervised processes with the same `SCOOBY_DATA`, and explicitly set `SCOOBY_BROWSER` for PDF and `SCOOBY_WEB_ORIGIN` to one exact trusted web origin without trailing slash. `SCOOBY_FRONTEND_DIR` optionally overrides the vendored reader. `SCOOBY_MODEL_CALL_BUDGET=0` is the safe default; `OPENAI_API_KEY` is an environment/secret-store name only and is unnecessary without an authorized live call. No token, host credential, callback URL or external API key is bundled. CORS allows only GET from the configured origin; it is not access control.

`GET /health` proves only process responsiveness. `GET /status` exposes queue and worker heartbeat; `GET /readiness/honeypot` is a static development inventory, not a dependency or production readiness check. Before any launch, build real readiness checks for durable storage, worker freshness, queue, package validation, browser rendering, security gateway and provider budgets. Run `python -m pytest -q tests`, `python tests/smoke_worker.py`, the reader export tests, discovery export tests with `SCOOBY_CANDIDATE_SCHEMA` pointing to root schema, and `python modules/investigation/test_boundaries.py`. Use synthetic data for deployment smoke; do not call an external source or paid model without its own authorized budget. Verify versions, response digests, CORS, denial of operator routes and restart/crash behavior on the actual target.

## Persistence, backup and rollback

`SCOOBY_DATA` contains `state.sqlite3`, Huey's SQLite queue and report bundles/render artifacts. SQLite is a single-host local prototype: no distributed fencing, safe multi-host queue, lease renewal or production recovery guarantee. Schema initialization is `CREATE TABLE IF NOT EXISTS`, not a versioned migration system. Before upgrade or rollback, stop API and worker, take a consistent backup of the entire data directory including SQLite/WAL state and artifacts, record code/config versions and test restoration into an isolated directory; never copy only one SQLite file while running. There is no automated migration or downgrade. Create and test versioned migrations, rollback strategy, backup encryption/access/retention and restore drills before deployment. Roll back by stopping processes, restoring a known-compatible complete backup and previous code/config, restarting privately, and verifying the digest manifest and queue; do not overwrite current user data without an approved recovery procedure.

## Verified and remaining

- Local tests and exact commands/results are recorded in `HANDOFF.md`; current branch work includes offline v1/v2 and atomic package checks. Fresh CI/PR evidence must be attached to the actual commit.
- No production host, domain, TLS, approved callback, secret manager, IAM, persistent volume, load test, safe external-access configuration or authenticated sign-off has been selected or validated. World ID contract and owner inputs are pending. No deployment or infrastructure spend is authorized by this checkpoint.

## Two distinct web API contracts — do not conflate

The native research adapter uses `NEXT_PUBLIC_REPORT_API_URL` for this backend's report/version/package DTO and exact-byte **SHA-256** digests. The web's existing legacy World ID flow in `src/lib/api.ts` uses `NEXT_PUBLIC_API_URL` (default `http://localhost:8080`), a different `GET /reports` payload with canonical **keccak** `manifestHash`, `POST /reports/:id/approve`, and `GET /approvals/:id` device-code/status routes. This backend does not implement that legacy API or a World ID verifier. Do not point both variables at this base or equate SHA-256 report digests with keccak manifest hashes. `GET /health` cannot prove either contract compatible. World ID lookup and integration are deferred; no real approval or deployment is claimed.

## Private single-host staging package

`Dockerfile` and `compose.yaml` define one API and one Huey worker sharing a named `/data` volume. Compose binds the host port only to `127.0.0.1:8000`. A non-root user owns the data directory. The image installs Chromium and DejaVu fonts; target rendering and browser sandbox behavior still need verification. CORS defaults to `http://localhost:3000`, and the model-call budget is zero. Docker network peers can reach the container, so the host and Docker daemon must be trusted. This is not an internet-facing authorization boundary.

```sh
docker compose build
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/status
docker compose exec -T worker python /app/ops/worker_health.py
```

The API check is process-only. The worker heartbeat can take two minutes to appear. Use a synthetic bundle to smoke-test rendering, hashes and CORS on the target. Stop with `docker compose stop`; do not remove the data volume. With both processes stopped, identify the actual named volume using `docker volume ls` and `docker volume inspect`, take an encrypted, access-controlled backup of its complete contents through a read-only mount, and test restoration to a separate empty volume. For example, after creating a workspace `backups` directory and replacing `<actual-volume>` with the inspected volume name:

```sh
docker run --rm -v <actual-volume>:/data:ro -v "$(pwd)/backups:/backup" alpine tar -czf /backup/scooby-data.tar.gz -C /data .
```

Restore into a separate empty recovery volume and test in an isolated stack; validate SQLite, queue, digests and ownership before cutover. For rollback, stop both services, preserve current state, restore a compatible complete backup and prior image/config privately, then verify before resuming. SQLite migration and downgrade tooling is not implemented.

CI defines a Compose build and process/worker-heartbeat smoke; it does not establish PDF quality or public security. Docker is unavailable on the authoring workstation, so this image and stack are **not locally built or run**. Check the actual PR CI result before calling the private-stage image verified. World ID is not a prerequisite for private staging; publication remains outside this checkpoint.
