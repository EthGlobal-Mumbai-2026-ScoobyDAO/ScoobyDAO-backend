# Scooby DAO backend — ACTIVE STATE

Checkpoint: **6 November 2026 IST — completed workstream PRs merged into main.** The FastAPI/Huey runtime, immutable native packages, offline discovery/investigation modules and portable PDF adapter are merged. Python checks and Linux Compose API/worker smoke passed. See [LIVE-STATE.md](LIVE-STATE.md) for the merge ledger, verification and exact remaining work; [DEPLOYMENT.md](DEPLOYMENT.md) for private staging; and [report storage/transfer](docs/report-assets.md) to carry the local RAY assets to a new target.

The source is ready for **private single-host staging**. No server has been deployed. Continuous discovery and automated five-pillar research are not connected; sign-off is not authenticated. The teammate separately merged the World ID/publication prototype in PR #6 during this checkpoint; live verification remains deferred by user instruction. Public exposure requires a reviewed access boundary.

## Active milestone: suspected-honeypot validation (M0–M6)

M0 readiness is in progress; M1 bounded discovery is owned by discovery, with no new case selected in this backend checkpoint. M2 requires separate human selection or a newly approved diagnostic exception. M3 investigates the mechanism and five pillars; M4 integrates the actual selected run into IRC HTML and a complete PDF; M5 compares the locked draft with independent evidence and seeks human sign-off. M6 includes a World ID and publication prototype contributed by the human teammate; live validation and security review remain. The conclusion is evidence-driven and may be inconclusive. See the [milestones](docs/honeypot-validation-milestones.md) and [readiness/dependency map](docs/honeypot-readiness.md).

Discovery has narrowly scoped G07 and partial G09 verifiers; the backend worker does not have them wired. The corrected IRC reader is integrated for imported reference bundles; offline source helpers and the reasoning/2 producer contract are merged but remain separate from worker execution. The root-curated RAY reference has passed the local API-to-worker-to-HTML/Markdown/PDF path, but automated deep research is not wired and detailed PDF accessibility and typography QA remains. `GET /readiness/honeypot` is a static integration inventory, not a live case gate or health check.

## Merged report pipeline

The [native package contract](docs/native-package-contract.md) binds report, sidecars and evidence to exact bytes, with atomic installation and immutable reads. The standalone reader and native web cards accept reasoning/1 and additive reasoning/2; synthetic cross-consumer checks passed. RAY remains an unchanged reasoning/1 reference, pending review, not gate-qualified, with its current sell trap unproven. No real reasoning/2 model report or autonomous deep research was performed. The separately contributed World ID/publication module is present; its live issuer, frontend hash compatibility and chain path have not been verified here. HTML/Markdown and optional draft PDF are derived assets. PDF source links now resolve to an internal companion-file/hash index; evidence is supplied separately. Target-container PDF rendering and detailed visual/accessibility QA remain.

## Case orchestration workstream (proposed branch)

The local case orchestration slice reads bounded, configured discovery snapshots into a versioned case list, rechecks policy and evidence before an auto-qualified run, and pauses human exceptions until a credential verifier exists. Actual production groups currently number two, so no live auto-qualification is possible. Research producers and Reddit retention/lead ingestion remain unwired; a started run ends incomplete with explicit unavailable pillars. See [case orchestration](docs/case-orchestration.md), discovery PR #9, investigation PR #11 and the separate [qualification charter PR #10](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/10). The API is unauthenticated local prototype; report sign-off/publication remains separate.

## What works and what remains

- **Implemented locally:** candidate schema validation; diagnostic selection/defer records; queued investigation and five explicit unavailable pillar states; persistent jobs/events and bounded retry; exact-byte report digest and local review records; existing frontend validation and HTML draft; optional browser PDF printout; opt-in Terra Chat Completions reasoning on supplied evidence. The call budget defaults to zero.
- **Partial:** SQLite lease recovery is not fenced; cancellation is not cooperative during work. Review actor labels are unauthenticated local assertions. The draft PDF includes expanded reader details, bound full Markdown and internal links to the companion-file/hash index. PDF generation is disabled by default in private staging; verify the target browser and each actual report before enabling it. Outputs are draft only, including after local approval. The reasoning task is not a research engine and does not establish evidence truth. No central token/rate spend controls exist.
- **Missing:** integrated live feed collection and a complete set of independently verified concern groups; production gate qualification; real five-pillar producers, evidence/counterevidence synthesis and source-linked TL;DR authoring; production-verified authenticated sign-off; durable approved export; production publication and AgentKit. World ID device-grant and a publication outbox exist but require live validation and security review. No live model call or production deployment has been verified.


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


## Reference report import and rendering

A separately scoped reference track can import an operator-supplied v0.1 candidate, record a diagnostic selection, create a run, validate a frozen-v0.2 research bundle with the current IRC reader, and enqueue a local review draft. Artifacts include `index.html`, `report.md`, `report.pdf` when browser rendering succeeds, and a manifest binding their SHA-256 to the exact report bytes. This imports an authored or produced bundle: the worker does not independently perform research, certify a mechanism, establish production gate qualification, authenticate a reviewer or publish. Source provenance, date, replay/live/mocked status and known public labels must be explicit. See `docs/reference-integration.md`.
