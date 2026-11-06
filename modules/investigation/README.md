# Scooby DAO investigation producer — integration export

## ACTIVE STATE

Social and contract analysis adapters are implemented as local, unwired boundaries; see `docs/social-contract-adapters.md`. SearchApi is the selected Reddit provider; it uses a server-side key and a provisional configurable 365-day social lookback. A deletion lifecycle must be reviewed before durable use. Contract source findings are hypotheses until provenance, runtime state and execution are reviewed. Two live scouting calls returned seven dated unresolved context leads each; a RAY-specific call returned HTTP 200 with a provider-declared error of unknown cause. No model calls were made.

This package is a bounded local prototype to integrate into the new backend. Chain ID plus token address is the input. It captures source responses, optionally runs the user's original 50-reconstruction VAE, and emits a v0.2 report, Markdown, evidence and TL;DR sidecar for the existing reader. It does not implement all five research producers, Terra synthesis, authenticated human review, a discovery gate, PDF generation or publication. A direct-token request should be authorized by the backend; discovery must enforce its separate verified gate and selection. Do not deploy as a production service.

## Interfaces

- `history.identity(chain, address)` validates supported chains 1/8453 and canonicalizes identity.
- `history.fetch(chain, address, output, pool=None)` makes two free GeckoTerminal requests, records exact source bytes/hashes/times and token/pool relationships, and returns a history status. By default the first identity-matching pool from the provider's first page is chosen, not a market-wide or best-execution claim. `pool` can select an explicit matching address. It emits pending for missing/gapped daily history. `prepare` uses only consecutive daily closes before the current UTC day and never fills gaps. This is a documented prototype test convention, not a user-approved data adequacy, incomplete-day, horizon or imputation policy. Two adjacent returns are a mathematical minimum for covariance, not a validation threshold.
- `capture.capture(chain, address, output)` captures DEX Screener, GoPlus and Sourcify responses with fetch time, hash and error state. These are unverified provider records, not independent conclusions; no paid source is configured.
- `legacy_vae.run(source, output, days, legacy_repo)` checks candidate identity and captured hashes, then runs `vae.py` from the explicitly supplied user-owned checkout in a new isolated output directory. It executes original functions/classes from `precompute.py` via AST extraction, avoiding unrelated module startup, unrelated credentials and API clients. It preserves all 50 reconstructions and the legacy risk and technical output definitions, labels and thresholds. It records hashes, parameters, dependency versions and the original script's unseeded randomness. The caller must explicitly supply the horizon; the four-day example below is an integration test drawn from the historical SHIB reference, not a default or user-approved future horizon. No pretrained model is supplied. Training only occurs after an explicit command. Do not use SHIB data for BLISS or another token.
- `build_report.build(history_dir, capture_dir, output_dir, model=None)` verifies identities and source hashes; if a model run is given, checks its candidate ID, history and output hashes. It builds a schema-validated v0.2 live-mode partial draft with exact-byte digest, hash-bound raw sources, Markdown, source ledger, 50-reconstruction CSV/legacy metrics when available, and `scooby.pillar-tldr/1` sidecar. Existing claims are deterministic descriptions of source/provider output only; no model-written synthesis or token safety conclusion is implied. Status is partial or unavailable; report review pending, assessment not_assessed. No PDF is emitted.
- `contract_validate.validate(bundle_root, report)` / `verify_digest(bundle_root, expected_sha256)` validate the frozen report v0.2 and path/reference/hash semantics. The repository-level `schemas/` directory is the authoritative accepted contract; future changes require version coordination.

Historical output and VAE figures are unvalidated. The user's proprietary model is retained exactly, but its historical VaR 'maximum loss' interpretation, tail calibration, technical definitions and minimum input suitability are not established. Preserve original labels as requested and show these limitations alongside them; do not invent a new score or turn the legacy output into a financial verdict. This package has no machine-bound credentials, full legacy source, model weights, virtual environment or reference to a specific user's filesystem.

## Run (local, read-only sources)

Use Python 3.11. Install `requirements.txt` for capture/report and `requirements-vae.txt` when actually running the VAE. CPU Torch may be installed from the official CPU wheel index. The original user-owned RiskFi-VAE checkout is a separate runtime dependency, supplied with `--legacy-repo`; keep it outside this package and do not import the full legacy web app. Replace all placeholders with actual paths and the chosen chain/address.

```
python history.py --chain 1 --address <token-address> --output <new-history-dir>
python capture.py --chain 1 --address <token-address> --output <new-source-dir>
python legacy_vae.py --source <history-dir> --output <new-model-dir> --days <chosen-days> --legacy-repo <legacy-checkout>
python build_report.py --history <history-dir> --sources <source-dir> --vae <model-dir> --output <new-bundle-dir>
```

Omit `--vae` to create a partial report with statistical/technical VAE sections unavailable. A new token with insufficient history remains pending while other pillars proceed, per user decision. Model run refuses gapped or fewer than two consecutive daily returns; that check prevents a numerical error, not a user-approved sufficiency rule. Choose a new output directory for every report or model run; no background process starts automatically.

## Verification performed

- `python test_boundaries.py`: seven offline tests passed: chain/address identity, token-side pool mapping, gaps/current-day handling, source failure and safe paths.
- On this workstation, current public SHIB data returned 183 closed daily candles / 182 consecutive returns; the original VAE produced 50 columns, and original risk/technical functions generated output. A separate SHIB fixture comparison reproduced every saved legacy risk output and technical-health object exactly. This is integration evidence, not a new approved SHIB assessment. BLISS returned zero closed daily candles and the adapter correctly left VAE pending; no SHIB numbers were used for BLISS.
- `build_report.py` consumed the SHIB test data and 50-reconstruction run; schema/hash validation passed and the existing one-case frontend builder packaged it into HTML. Reader browser QA, PDF completeness and approval were not verified for this prototype.

## Integration gaps

Backend owns queue/actor state, discovery and human review. It must isolate workspaces, verify evidence references, map partial failure, bind outputs to its authoritative run and expose progress. Existing builder has no automatic Terra-based five-pillar investigation, model provider call, complete project/sentiment or finalized on-chain verification, control/counterevidence synthesis, error-retry orchestration, real approval authentication, complete PDF, live discovery ingestion or durable worker integration. Its raw legacy output is not a report sign-off. Report source fetches are snapshots with differing times, not a single block. Source selection and daily-price conventions require user confirmation before being treated as production policy. Independent end-to-end tests must cover BLISS pending and another selected token with adequate history; the decision on adequacy belongs to the user.

`pillars.run_pillars(context, producers)` is an optional explicit five-pillar callable boundary that isolates missing and failing producers. It is not yet wired into `build_report` or the backend; it does not itself fetch data or establish evidence validity.

## Social and contract investigation adapters

`reddit_search.search_leads`, `reddit_search.collect`, and `reddit_search.summarize` provide bounded SearchApi-backed source capture and auditable literal-language counts. `contract_analysis.rpc_plan`, `from_pinned_capture`, `source_from_sourcify`, and `analyze` support identity-bound code navigation with explicit proxy, provenance and live-verdict gaps. See `docs/social-contract-adapters.md` for exact contracts, Reddit access retirement and mandatory deletion-lifecycle caveats. These are not wired into backend jobs or immutable reports.

## Case research producer

`case_research.run_case` invokes bounded source collection, optional original 50-reconstruction VAE/legacy scores, per-pillar partial handling and a validated v0.2 report bundle for either backend-authorized route. See `docs/case-research-producer.md` for exact arguments, budget/authorization boundary and remaining report-reasoning limitations. Backend must wire durable authorization/jobs/import/render; passing route-shaped references here does not verify a World confirmation.
