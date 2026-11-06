# Live state — 6 November 2026

The completed Scooby DAO source branches are merged into `main`. This is a **private single-host staging checkpoint**, not a deployed public service. World ID integration is deferred by the user; the teammate's separate PR #6 is outside this merge set.

| Workstream | Merged result | Remaining work |
|---|---|---|
| Runtime and contracts | [#1](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/1), [#4](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/4): FastAPI, Huey/SQLite, immutable report packages, exact-byte assets, reasoning/1 and /2 readers, private Compose profile | Authenticated operator boundary, migrations, distributed fencing and production recovery |
| Discovery | [#2](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/2), [#3](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/3): bounded offline pilot, G07/partial G09 checks, experimental local fork tool | Connect runner to durable jobs/events; actual fork execution and remaining concern verifiers. No gate-qualified fresh case |
| Investigation | [#5](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/5): offline source adapters, legacy helpers, mechanism protocol and transport-free reasoning/2 contract | Actual five independently resumable pillar producers and app-owned model/tool orchestration |
| Report assets | [#4](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/4), [#7](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/7): HTML/Markdown and optional draft PDF; PDF links resolve to a companion-file/hash index | Target-container PDF smoke, every-page reading-size/accessibility review. Evidence bytes are in the companion package, not embedded in PDF |
| Web integration | Web [#1](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-web/pull/1), [#2](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-web/pull/2): native five-pillar cards and real worker/queue status | Configure reachable research origin; token-level screening events remain unconnected |

Source checkpoint: backend `5893caa9e3503334145744a29697a4cea95cc01f`, web `fa0b1f0743e18841424ed467bcf8dbf7e374d157`. Later documentation commits may advance `main` without changing this source baseline.

## Verification

- Exact PR #4 head passed Python checks and a Linux Compose image build/API/worker-heartbeat smoke.
- PR #7's final head passed [Python](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/actions/runs/42196275315) and [Compose](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/actions/runs/42196275347) CI. Independent Windows checks passed six PDF/workflow tests with isolated headless Edge, including absence of URI annotations and resolution of internal destinations.
- Discovery #2/#3 together: 55 tests passed. Investigation merged with core: 44 passed, one optional legacy-checkout comparison skipped, 27 subtests passed. These are offline checks; they do not prove live EVM execution or new research.
- Web #1/#2 passed tests, lint, production build and typecheck. Actual app checks covered desktop/mobile and synthetic v1/v2 contract acceptance. See the web handoff for details.

## Report data and deployment handoff

The Git repo/image supplies code, schemas, reader templates and synthetic/historical test fixtures. **It does not include the authored RAY source bundle or the local runtime database/artifacts. A fresh deployment has an empty report library.**

`SCOOBY_DATA` owns `state.sqlite3`, `huey.sqlite3`, `bundles/<report-sha256>/` and `artifacts/<job-id>/`. Compose mounts the persistent named `scooby-data` volume at `/data` in both processes. It is not an object-store service. Keep this volume across restarts and rebuilds. See [asset transfer](docs/report-assets.md) and [deployment commands](DEPLOYMENT.md).

RAY identity is `ethereum-ray-reference` / `2026-11-06-source-curated-1`, report SHA-256 `69712a61331eb414d3eb0ff347c7bec12cb16cccb1f874779f695619d714649a`. It remains a source-curated diagnostic reference, not gate-qualified, pending human review; a current sell trap is unproven. No live reasoning/2 report was generated. Frozen schema hashes remain candidate `9a45955834e66c9a86f8f0e8cd7eb915e03517ee6e601d1c24570bc687ed530b` and report `8a5f793dce8c75c18c3ee8ade4c26e76fe51ee489173ff59299ad85b5963bf55`.

Next: provision a reviewed private single-host target, start the protected Compose stack, transfer/import the matching source packet, render a new immutable package, verify API/worker/storage/restart/digests, and configure the web's research origin. Model budget remains zero and PDF stays opt-in until target rendering is checked. No host, public URL or actual deployment exists from this checkpoint. Public exposure requires a reviewed access boundary; CORS is not authentication. Publication and authenticated human sign-off remain the teammate's separate work.
