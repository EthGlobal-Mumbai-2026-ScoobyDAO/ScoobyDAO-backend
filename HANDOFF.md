# Handoff — initial integration checkpoint

## Active milestone

M0–M6 and acceptance evidence are recorded in [the milestone charter](docs/honeypot-validation-milestones.md); actual wiring and the next vertical slice are in [the readiness map](docs/honeypot-readiness.md). No new case has been selected in this backend checkpoint. Discovery owns bounded scouting; investigation owns mechanism and controls; backend and frontend own M4 integration; root and user own M5; the human teammate owns publication and World ID/AgentKit (M6). Do not duplicate case requests or treat the prior BLISS exception as a new selection. The newer G07/G09 worktree and corrected IRC reader are not merged or wired here. Next: review the workstream patches and wire separately selected input through durable pillar jobs and the validated report/IRC reader/full-PDF path, using offline tests and separately authorized model budgets.

## Current state

`main` starts with a local-only scaffold. Read README, architecture, endpoint-schema-map and contract-amendments before extending it. The frontend reader and its schema are vendored under `vendor/reader`; the shared schemas and contract semantics are under `schemas`. Historical fixtures are compatibility data only. The source is not a complete automated research system and does not authenticate operators.

## Continue in order

1. Clone the repository and create a topic branch. Run `python -m pip install -r requirements.txt`, `python -m pytest -q tests`, and `python tests/smoke_worker.py` with Python 3.11. Run the API and worker separately as in README. Verify no process is left running after a smoke test.
2. Discovery's final portable export is imported at `modules/discovery` and is not wired to the API. Investigation's final portable export is imported at `modules/investigation`; neither package is wired to the API. Integrate the packages behind worker boundaries, preserve provenance, keep held/missing verifiers unknown, and enforce the four distinct verified concern groups plus separate human selection. Do not treat an exception as gate-qualified or duplicate the current BLISS diagnostic research.
3. Implement durable source snapshots, feed freshness, meaningful retry/fencing/cancellation, actual independently resumable five-pillar tasks, source/counterevidence validation and source-linked TL;DRs. Keep app-owned tool execution separate from Terra Chat Completions. Add call/token/rate budgets and failure tests before authorized live calls.
4. Produce complete, version-bound full-report PDF and validate all pages; current PDF is a reader printout with collapsed details omitted. Maintain the pending draft path before review.
5. Coordinate the versioned review/publication interface in `docs/workstreams.md` and `docs/post-report-handoff.md`; a separate human teammate owns publication and World ID/AgentKit human sign-off. Frontend chat supplies reader export and interface proposal only. Do not invent an authenticated or published status before that work is integrated.
6. Add authentication and authorization, migrations, production security/observability and a durable approved export; test review revocation, digest mismatch and crash recovery. Re-run shared contract acceptance across the workstreams before changing schema versions.

## Evidence and limitations

Checkpoint: **6 November 2026 IST**. A fresh clone passed 2 backend, 21 discovery, 7 investigation and 2 reader tests, plus the worker smoke test. [GitHub CI run 42178733491](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/actions/runs/42178733491) succeeded.

Prior local test: two pytest cases passed, a separate worker processed an empty bounded scan and was stopped, and a historical reader generated a seven-page PDF via isolated headless Edge (page one inspected at reading size; all pages as thumbnails). The PDF omitted collapsed sections. Model transport was mocked; no live API call, billable infrastructure, or new token research occurred. No real feed, human authentication, complete long-form PDF, production reliability or deployment is claimed. The BLISS one-off diagnostic is not gate-qualified and remains separate.

Source-of-truth schema digests: candidate `9a45955834e66c9a86f8f0e8cd7eb915e03517ee6e601d1c24570bc687ed530b`; report `8a5f793dce8c75c18c3ee8ade4c26e76fe51ee489173ff59299ad85b5963bf55`. The reader's copy of the report schema must match. Record any future accepted version explicitly rather than changing these bytes.

## Publication and World ID Agent Pass: status (6 November 2026)

**Implemented and tested with a fake issuer (`tests/fake_world.py`) and fake or anvil chains:** service-owned `scooby.publication-target/1` and `scooby.claim-manifest/1` records; device-grant sign-off with `private_key_jwt`; ID-token validation (alg, iss, aud, exp, iat, auth_time window, acr, amr, kid refresh); `(iss, sub)` allowlist with CLI enrollment; append-only receipts and audit events; explicit publish with TTL, consumption, reviewer re-check and byte re-hash; attestor signature over the contract's `approvalDigest`; fenced outbox publisher with crash reconciliation; revoke before and after confirmation; `/publication/v1` operator API and the `/web/v1` adapter matching `ScoobyDAO-web` types. Frozen schemas are unchanged (digest test).

**Not yet verified live:** World app registration, a real device login against `auth.world.org` (or the sandbox), and any Sepolia publish. Anvil tests run only where Foundry is installed. **Still missing:** IDKit/REP, AgentKit, durable approved export, multi-process device-code storage, `/claims` and `/deployments` read models for the web.
