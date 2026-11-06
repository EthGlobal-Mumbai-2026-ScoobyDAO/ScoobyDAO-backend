# Offline investigation modules

These modules are local, unwired building blocks. They do not start source collection, run a model, select a token, change admission, score a new live token, publish a report, or deploy a service. Their synthetic fixtures are fabricated test inputs. They are not actual provider records or token investigations.

## Legacy source port

`modules/investigation/legacy_source_port/` isolates original legacy pure computation definitions and records source SHA-256 and exported target hashes in `SOURCE-MANIFEST.json`. Numerical behavior and labels remain unchanged. The adapter returns partial/unavailable with missing inputs rather than fabricating data. It reproduces the original V3 depth/slippage and cliffs/active-liquidity arithmetic, owner-level LP concentration aggregation, MEV proxy and market score, contract primitive keyword scan and score, and V2 LP lock percent. An explicit evidence-bound attribution assertion is required before mapping any structured fundamental fields; assertions require independent source review. Ten original-source modules are isolated; no old API/client runner, credential or captured public source data is imported.

Interpretation is limited: the original zero-liquidity slippage fallback can still report a tiny slippage figure; a single-venue cross-spread is hardcoded in the old runner; the `sampledPositions` field counts aggregated owners; an original source-keyword match can be a comment or unrelated function. Original lock % counts configured locker/dead balances, but does not establish ownership, beneficiary or expiry. The module does not connect to the backend worker or complete the project/social fundamental producer.

Parity with the saved historical SHIB output and the VAE 50-reconstruction series was checked in the separate authorized investigation workspace; those captured files and model weights are not included in this repository. The checked-in fixtures here are entirely synthetic. Optional exact source AST verification can use `SCOOBY_LEGACY_AGENTS_DIR` when the original user-owned checkout is available. A missing checkout skips that one optional test and never changes the synthetic fixture results.

## Pinned mechanism evidence

`modules/investigation/mechanism_evidence.py` and `pinned_rpc_capture.py` are experimental offline shape/control helpers. The former detects inconsistency in supplied scenario metadata and reports scoped evidence coverage; it cannot establish authenticated review, semantic trace correctness, independent experiments or a token safety verdict. Wallet and replication counts are observations, not approval thresholds. The latter accepts an injected transport, explicit request cap and recorded candidate selection reference; it whitelists read-only methods, checks chain/block and records request/response hashes. It does not authenticate selection or provide a coherent stateful buy/sell simulator.

The discovery workstream owns G02 execution. Live fork/trace use, actual selection authorization, app-owned request budgets, backend job/state isolation and independent review must be implemented and tested in their own integration work. Successful ordinary sells remain counterevidence to universal blocking, while selective behavior remains separately testable.

## Proposed actionable conclusion contract

`modules/investigation/reasoning_v2/` contains the local analyst-v2 prompt, structured output JSON Schema, an offline validator using the canonical frozen report-v0.2 schema. The additive `scooby.reasoning/2` requires a proposed action, cited rationale, counterevidence and conditions that would change the conclusion. A proportional avoid/defer recommendation can follow a supported material exposure without claiming a universal honeypot. Validation checks schema, bound evidence IDs and relationships; it is not a factual-entailment, calibration, authentication or approval check. The v2 validator intentionally refuses v1; dispatch v1 to the existing v1 reader. Consumer/backend/PDF cross-acceptance is needed before emitting v2 real reports.

No API client is bundled here. The backend's application-owned GPT-6.1 Terra Chat Completions transport, authorization, existing zero-budget default and report artifact binding remain the integration boundary. Original 50-reconstruction code and all scores are not changed. Existing RAY and BLISS report bytes stay unchanged.

## Tests

Run `python -m pytest -q tests/test_legacy_source_port.py tests/test_mechanism_readiness.py tests/test_pinned_rpc_readiness.py tests/test_reasoning_v2_contract.py`. GitHub CI has an explicit offline-module step as well as the normal complete test suite. Synthetic fixtures prove code behavior and boundary handling, not live EVM, source truth or model factual quality. Source-capture wiring, the legacy fundamentals-service implementation, live research/model operation, cross-consumer v2 acceptance, matching complete PDF and human report approval remain separate work.
