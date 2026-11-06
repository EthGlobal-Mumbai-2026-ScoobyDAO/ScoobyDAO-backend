# Scooby DAO backend — ACTIVE STATE

Checkpoint: **6 November 2026 IST**. A fresh clone passed 2 backend, 21 discovery, 7 investigation and 2 reader tests, plus the worker smoke test. [GitHub CI run 42178733491](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/actions/runs/42178733491) succeeded.

This repository is an **early local integration scaffold**, not a live or production research service. It contains the FastAPI operator API, a Huey/SQLite worker, frozen candidate/report schemas, and a vendored frontend reader. It can import and validate a research bundle and render a visibly pending local draft. It does not yet run continuous discovery, verify the four-concern gate, conduct five-pillar research, generate a report/TL;DR, authenticate human reviewers, or publish reports.

## Active milestone: suspected-honeypot validation (M0–M6)

M0 readiness is in progress; M1 bounded discovery is owned by discovery, with no new case selected in this backend checkpoint. M2 requires separate human selection or a newly approved diagnostic exception. M3 investigates the mechanism and five pillars; M4 integrates the actual selected run into IRC HTML and a complete PDF; M5 compares the locked draft with independent evidence and seeks human sign-off. M6 publication and World ID/AgentKit remain reserved for the **human teammate**. The conclusion is evidence-driven and may be inconclusive. See the [milestones](docs/honeypot-validation-milestones.md) and [readiness/dependency map](docs/honeypot-readiness.md).

Discovery has narrowly scoped G07 and partial G09 verifiers; the backend worker does not have them wired. The corrected IRC reader is integrated for imported reference bundles; the separate research audit remains outside this checkout. The root-curated RAY reference has passed the local API-to-worker-to-HTML/Markdown/PDF path, but automated deep research is not wired and detailed PDF accessibility and typography QA remains. `GET /readiness/honeypot` is a static integration inventory, not a live case gate or health check.

## Reconciliation checkpoint — reference branch

The reference branch provides a [native package read contract](docs/native-package-contract.md): atomic local render installation, digest-bound report/sidecars/evidence and exact-byte responses, alongside the existing HTML/Markdown/PDF drafts. Original report availability and derived download availability stay separate. The imported RAY reference remains unapproved and its current sell trap is unproven; actual live source collection and autonomous research are not performed by this backend. Synthetic fixtures exercise both reasoning/1 and proposed reasoning/2; model generation of /2 and real cross-consumer acceptance remain pending. Private single-host staging assets are provided but have not been locally container-tested; public deployment is **blocked** as detailed in [DEPLOYMENT.md](DEPLOYMENT.md). The World ID publication adapter is separately implemented; its live issuer, frontend hash compatibility and chain path have not been verified. No deployment or live authenticated approval is claimed.

## What works and what remains

- **Implemented locally:** candidate schema validation; diagnostic selection/defer records; queued investigation and five explicit unavailable pillar states; persistent jobs/events and bounded retry; exact-byte report digest and local review records; existing frontend validation and HTML draft; optional browser PDF printout; opt-in Terra Chat Completions reasoning on supplied evidence. The call budget defaults to zero.

- **Partial:** SQLite lease recovery is not fenced; cancellation is not cooperative during work. Review actor labels are unauthenticated local assertions. The draft PDF includes expanded reader details and bound full Markdown but removes link annotations, including internal navigation. PDF generation is disabled by default in private staging; verify the target browser and each actual report before enabling it. Outputs are draft only, including after local approval. The reasoning task is not a research engine and does not establish evidence truth. No central token/rate spend controls exist.
- **Missing:** live feeds, source snapshots/freshness and accepted concern verifiers; production gate qualification; real five-pillar producers, evidence/counterevidence synthesis and source-linked TL;DR authoring; production-verified authenticated sign-off; durable approved export; production publication and AgentKit. World ID device-grant and a publication outbox exist but require live validation and security review. No live model call or production deployment has been verified.


Candidate v0.1 and report v0.2 are frozen shared contracts. The reader validates JSON schema, references and bundle hashes, including the optional `scooby.pillar-tldr/1` profile. Do not change the frozen schemas silently. See [architecture](architecture.md), [contract amendments](contract-amendments.md), [endpoint map](endpoint-schema-map.md), and [OpenAPI](openapi.json).

## Owners and workstreams

- **Backend integration (this checkout):** core lifecycle, worker orchestration, schemas, research integration, local draft generation and durable state.
- **Discovery chat `01a1adf5-c90c-7ec0-9a93-8adb65d9aca6`:** source ingestion and verified screening; portable package imported under `modules/discovery`; not yet wired to the API.
- **Investigation chat `01a1adf5-caef-7e50-9fac-5e344c5a169a`:** five-pillar research and producer interfaces; final portable export imported under `modules/investigation`; not wired to the API.
- **Frontend chat `01a1adf5-cdb8-78e0-b887-625f6ca4e941`:** portable reader/build export and contributor handoff/interface proposal only.
- **Another human teammate:** post-report publication and World ID/AgentKit human sign-off. Implemented in `publication/` on top of this seam (fake-issuer tested; live run pending); see the section below. See [workstreams](docs/workstreams.md) and the [human teammate handoff](docs/post-report-handoff.md) for the seam and exact continuation.

Use separate topic branches and pull requests for workstreams. `main` is the integration checkpoint; coordinate shared contracts and review/publication interfaces before merging. Avoid concurrent edits to the same integration checkout. Discovery and investigation source exports are imported as isolated modules; neither is connected to the backend worker.

## Run locally

Requires Python 3.11. In a shell at the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

In a second shell, activate the same environment and run `python -m huey.bin.huey_consumer worker.huey -w 1`. Stop each with Ctrl+C. Open `http://127.0.0.1:8000/docs` for the local OpenAPI UI. The vendored reader is the default; `SCOOBY_FRONTEND_DIR` may point to another compatible reader. `SCOOBY_DATA` selects local state; default is the ignored `data/` directory. Set `SCOOBY_BROWSER` to a local headless Chromium-compatible executable for draft PDF. No browser means explicit PDF unavailable. Set secrets in the environment, never in Git. `SCOOBY_MODEL_CALL_BUDGET` defaults to zero; live model calls require a separately authorized bounded budget.

Verify with `python -m pytest -q tests`, `python tests/smoke_worker.py`, `python -m unittest discover -s vendor/reader -p test_export.py -v`, and the discovery tests in its README with `SCOOBY_CANDIDATE_SCHEMA` set to the absolute path of `schemas/candidate.schema.json`. `tests/smoke_worker.py` starts and stops its own local worker. Tests use a historical SHIB fixture and a mock model, not live research. `tests/historical-bundle` is a small historical compatibility fixture, not an assessment; its original local source path was redacted and its hashes recomputed for portability.

## Draft, approval and publication

The operator may render a **pending-review draft** before sign-off. The generated manifest and banner bind the report ID/version and exact report digest; the draft PDF includes expanded reader details and bound full Markdown. A local review receipt records a digest and decision but has no authenticated identity. The separate publication module implements a World ID device-grant and an optional outbox, tested with a fake issuer. Neither this draft nor a local unauthenticated receipt authorizes publication. Live validation and security review remain required.

See [HANDOFF.md](HANDOFF.md) for exact next steps and current limitations. The publication module has optional transaction code, disabled by default.


## Publication and World ID Agent Pass

`publication/` implements the protected action from [docs/post-report-handoff.md](docs/post-report-handoff.md): publishing a reviewed report version with `ReportRegistry.publish` on Sepolia after a fresh World authentication and a backend-created, single-use receipt bound to those bytes, followed by a separate explicit publish request. Read [the plan](docs/publication-plan.md), [decisions](docs/publication-decisions.md) and [demo runbook](docs/publication-demo.md).

- **Sign-off:** OIDC Device Authorization Grant against World (`private_key_jwt`, RS256, essential `acr`). The backend starts it, and the reviewer enters the code shown on the web `/approve/[id]` page in World App. ID tokens are validated against JWKS, and the reviewer must be an allowlisted `(iss, sub)`. The backend receipt binds the exact `scooby.publication-target/1` digest; the World ID token authenticates the person and does not itself sign or display the report or its approval.
- **Publish:** an explicit operator call consumes the receipt and has the attestor key sign `approvalDigest`. It queues a row in a fenced outbox drained by a separate publisher process; `tx_hash` is persisted before broadcast, and reconciliation uses `usedNonce`.
- **Off by default:** nothing broadcasts unless `SCOOBY_PUBLISH_ENABLED=true` and the publisher key equals `ReportRegistry.publisher()` (RPC check). Live chains also need the operator to type a confirmation.

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8000          # API incl. /publication/v1 and /web/v1
python -m publication.publisher                                 # fenced outbox publisher (separate process)
python -m publication.cli enroll --name alice                   # reviewer device login -> allowlist
python -m publication.cli list | disable --name alice | enable --name alice
python -m publication.cli publish-confirm --target <target_id>  # explicit publish request
python -m publication.cli reconcile                             # drive uncertain outbox rows
```

**Trust model (hackathon):** the backend holds two trusted keys. The attestor (`SCOOBY_ATTESTOR_KEY`, which is `report.reviewer`) signs only after a validated World approval. The publisher (`SCOOBY_PUBLISHER_KEY`, which is `ReportRegistry.publisher()`) only broadcasts. A compromised backend could sign without a human, and the production path is a reviewer-held or threshold key. **Revocation** before broadcast stops publication; after broadcast or confirmation it is recorded and the status shows `revoked`, but the onchain record cannot be undone.

**Five-step judge demo:** deny, expire, non-reviewer, approve → tx, replay → spent. See [docs/publication-demo.md](docs/publication-demo.md).

**Tests:** `python -m pytest -q tests` (fake World issuer). `tests/test_publication_anvil.py` additionally deploys `../SmartContracts` `ReportRegistry` on a local anvil when Foundry is installed.


## Reference report integration (in progress)

A separately scoped reference track can import an operator-supplied v0.1 candidate, record a diagnostic selection, create a run, validate a frozen-v0.2 research bundle with the current IRC reader, and enqueue a local review draft. Artifacts include `index.html`, `report.md`, `report.pdf` when browser rendering succeeds, and a manifest binding their SHA-256 to the exact report bytes. This imports an authored or produced bundle: the worker does not independently perform research, certify a mechanism, establish production gate qualification, authenticate a reviewer or publish. Source provenance, date, replay/live/mocked status and known public labels must be explicit. See `docs/reference-integration.md`.
