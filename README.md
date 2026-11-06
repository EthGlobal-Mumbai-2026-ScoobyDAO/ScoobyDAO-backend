# Scooby DAO backend — ACTIVE STATE

Checkpoint: **6 November 2026 IST**. A fresh clone passed 2 backend, 21 discovery, 7 investigation and 2 reader tests, plus the worker smoke test. [GitHub CI run 42178733491](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/actions/runs/42178733491) succeeded.

This repository is an **early local integration scaffold**, not a live or production research service. It contains the FastAPI operator API, a Huey/SQLite worker, frozen candidate/report schemas, and a vendored frontend reader. It can import and validate a research bundle and render a visibly pending local draft. It does not yet run continuous discovery, verify the four-concern gate, conduct five-pillar research, generate a report/TL;DR, authenticate human reviewers, or publish reports.

## What works and what remains

- **Implemented locally:** candidate schema validation; diagnostic selection/defer records; queued investigation and five explicit unavailable pillar states; persistent jobs/events and bounded retry; exact-byte report digest and local review records; existing frontend validation and HTML draft; optional browser PDF printout; opt-in Terra Chat Completions reasoning on supplied evidence. The call budget defaults to zero.
- **Partial:** SQLite lease recovery is not fenced; cancellation is not cooperative during work. Review actor labels are unauthenticated local assertions. The PDF prints the reader and omits collapsed content; it is not a full research PDF. Outputs are draft only, including after local approval. The reasoning task is not a research engine and does not establish evidence truth. No central token/rate spend controls exist.
- **Missing:** live feeds, source snapshots/freshness and accepted concern verifiers; production gate qualification; real five-pillar producers, evidence/counterevidence synthesis and source-linked TL;DR authoring; authenticated sign-off; durable approved export; publication and World ID/AgentKit. No live model call or production deployment has been verified.

Candidate v0.1 and report v0.2 are frozen shared contracts. The reader validates JSON schema, references and bundle hashes, including the optional `scooby.pillar-tldr/1` profile. Do not change the frozen schemas silently. See [architecture](architecture.md), [contract amendments](contract-amendments.md), [endpoint map](endpoint-schema-map.md), and [OpenAPI](openapi.json).

## Owners and workstreams

- **Backend integration (this checkout):** core lifecycle, worker orchestration, schemas, research integration, local draft generation and durable state.
- **Discovery chat `01a1adf5-c90c-7ec0-9a93-8adb65d9aca6`:** source ingestion and verified screening; portable package imported under `modules/discovery`; not yet wired to the API.
- **Investigation chat `01a1adf5-caef-7e50-9fac-5e344c5a169a`:** five-pillar research and producer interfaces; final portable export imported under `modules/investigation`; not wired to the API.
- **Frontend chat `01a1adf5-cdb8-78e0-b887-625f6ca4e941`:** portable reader/build export and contributor handoff/interface proposal only.
- **Another human teammate:** post-report publication and World ID/AgentKit human sign-off. This is reserved work; there is no World ID integration or publication adapter here. See [workstreams](docs/workstreams.md) and the [human teammate handoff](docs/post-report-handoff.md) for the seam and exact continuation.

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

The operator may render a **pending-review draft** before sign-off. The generated manifest and banner bind the report ID/version and exact report digest; a PDF is a draft reader printout. A local review receipt records a digest and decision but has no authenticated identity. There is no approved or published state in this implementation. The human teammate must define and implement an authenticated sign-off and publication seam; neither this draft nor an unauthenticated receipt authorizes publication or financial action.

See [HANDOFF.md](HANDOFF.md) for exact next steps and current limitations. No wallet, transaction, settlement, treasury or financial eligibility work is included.
