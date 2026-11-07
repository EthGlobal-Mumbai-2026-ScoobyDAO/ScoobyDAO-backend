# Scooby DAO backend

This branch integrates case orchestration, captured-source research, the report library, and two separate admin World ID checkpoints. See [LIVE-STATE.md](LIVE-STATE.md) for the current integration status and [admin checkpoints](docs/admin-world-checkpoints.md) for the authentication contract. The integration is under review in PR #22; do not assume it is deployed or merged until the repository confirms that state.

A candidate is automatically queued only after four distinct, fresh, independently verified concern groups pass server-side revalidation. The available verifiers cover narrow G07 and G09 checks, not a complete twelve-group screening system. Provider hints do not count as votes. Actionable non-qualified cases require a scoped admin session and a separate World confirmation bound to the initiating session, candidate, snapshot and policy; stale or unavailable evidence does not authorize a run. Report sign-off and publication are separate actions. The checkpoints have synthetic-issuer coverage, but no live World end-to-end confirmation has been established.

The worker invokes the shared case producer with immutable decision budgets. It replays bound evidence, preserves missing and contradictory sources, and can generate a partial report with at most one explicitly authorized Terra call. Source and model budgets default to zero; no paid call follows simply from starting the service. Historical diagnostics and reference reports are not policy-qualified cases, World confirmations, final approval or publication. Local operator previews are not a public security boundary.

## World ID Agent Pass

A verified human confirms each consequential agent action in World App: opening a draft report, recording a decision on it, and publishing it onchain. See [WORLD_ID_QUALIFICATION.md](WORLD_ID_QUALIFICATION.md) for how each prize requirement is met, with code links, and [WORLD_FEEDBACK.md](WORLD_FEEDBACK.md) for the integration debrief.

## Run and configure

Use Python 3.11, install `requirements.txt`, then start the API and a separate worker on the **same persistent** `SCOOBY_DATA` directory:

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8000
python -m huey.bin.huey_consumer worker.huey -w 1
```

The Render blueprint currently starts the API only; it does not provision a worker. Configure an explicitly managed worker with access to the same durable storage before relying on queues or renders. `SCOOBY_BROWSER` enables optional PDF rendering. Set `SCOOBY_WEB_ORIGIN` to the exact trusted browser origin. CORS is not authentication.

Scout collection is **off by default**. To enable the bounded worker path, configure `SCOOBY_SCOUT_ENABLED=true`, `SCOOBY_DISCOVERY_DB`, `SCOOBY_DISCOVERY_ROOT`, and explicit `SCOOBY_SCOUT_CYCLE_BUDGET` and `SCOOBY_SCOUT_HOURLY_BUDGET` (each 1–30); `SCOOBY_SCOUT_LIMIT_PER_CHAIN` limits each cycle. Collection has a five-minute minimum interval, persistent request reservations and 429 cooldown. Its quota is per discovery database, not account-wide; it excludes the separate refresh, LP and archive collectors. Local reconciliation alone is not live scouting. See [bounded scout](modules/discovery/BOUNDED-SCOUT.md).

`SCOOBY_CASE_MODEL_MAX_CALLS` defaults to `0` and can be `1` only for an explicitly authorized case decision. `SCOOBY_MODEL_CALL_BUDGET` also defaults to `0` for the legacy reasoning path. Supply `OPENAI_API_KEY` securely only where an authorized model call is made. Other source integrations may use `SEARCHAPI_API_KEY` or optional `PUBLICNODE_TOKEN`; the bounded new-pool collector does not require either. Do not put keys or source URLs containing secrets in Git, logs or report packages.

World configuration uses `WORLD_ISSUER`, `WORLD_CLIENT_ID`, a private PEM supplied through `WORLD_CLIENT_KEY_PATH`, and the configured accepted ACR/audience. Enroll named reviewers and scopes via the documented admin CLI or `SCOOBY_REVIEWERS`; do not treat World identity alone as permission. Set `SCOOBY_REPORT_RELEASE=approved` on the API for approved-only consumer access. The branch retires former open-review grants and quarantines attributable receipts; already submitted or confirmed chain transactions cannot be undone by local revocation and require separate reconciliation. Publication stays disabled unless explicitly configured and authorized.

## Reports and storage

`SCOOBY_DATA` contains SQLite state, copied bundles and generated artifacts. A fresh deployment has no authored reports. [Seed restore](docs/report-seed-restore.md) is an explicit private CLI that verifies selected seed identities and hashes, requires approved-only configuration, and queues renders; it does not restore authenticated approvals, perform research or publish. Seed content must be transferred separately and kept out of the image and Git. A worker must share the same persistent volume. Restored drafts remain private pending exact-version admin approval, even if the release setting later changes.

Candidate v0.1 and report v0.2 are frozen contracts. The reader and native package preserve hashes and evidence lineage; HTML, Markdown and optional PDF are derived drafts. Inspect per-pillar status and source limitations rather than treating a partial report as complete. See [architecture](architecture.md), [endpoint map](endpoint-schema-map.md), [native package contract](docs/native-package-contract.md), and [deployment](DEPLOYMENT.md).

Run `python -m pytest -q` for the backend suite. Tests use synthetic identities and issuers, not real World authorization, on-chain publication or validation of source truth.
