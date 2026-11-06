# Invoked case research producer

`modules.investigation.case_research.run_case` is the common downstream research and v0.2 bundle producer for automatic-policy and human-confirmed cases. It does not decide admission, authenticate World ID, consume an authorization, schedule jobs, render HTML/PDF, or approve/publish a report. Backend must enforce the actual policy/World-ID binding, expiry, replay protection and one-time consumption before it calls this function. The supplied authorization fields are lineage references, not authentication.

```python
from modules.investigation.case_research import run_case

case = {
    'case_id': 'case_123', 'run_id': 'run_123',
    'candidate_id': '1:0x' + '12' * 20,
    'mode': 'synthetic_demo',
    'authorization': {'route': 'world_confirmed', 'reference_id': 'verified_auth_record'},
}
# `mock_transport` must be an explicit httpx.MockTransport for synthetic mode.
result = run_case(case, output_dir, max_source_requests=5, transport=mock_transport)
```

The backend must use its real case/run/authorization IDs and an isolated new output path whose parent exists. IDs accept only letters, digits, `_` and `-`; candidates must be canonical lowercase `1:0x...` or `8453:0x...`. `mode` is `live`, `historical_replay` or `synthetic_demo`; non-live test/replay mode requires injected transport rather than calling real providers. `max_source_requests` is an explicit total HTTP-attempt budget, 0–5, default **zero**. The exact ordered sources are DEX Screener pairs, GoPlus token security, Sourcify source, GeckoTerminal token pools, and, if a matching pool is found, GeckoTerminal daily OHLC. No retries, Reddit calls, transactions or hidden background work occur. Model calls default to zero and require a separate explicit budget as described below. HTTP clients have bounded timeouts and no redirects. Source errors are isolated and reported; provider identity is checked against chain/address before mapping content.

For a backend-bound discovery snapshot, use `captured_snapshot={'record': record, 'evidence': evidence}` with `max_source_requests=0` and no transport. `record` is the frozen v0.1 candidate object in the decision snapshot; `evidence` is the same snapshot's `snapshots/<sha256>.json` → base64 exact bytes mapping. The backend must pass the **already authorized, integrity-checked immutable decision snapshot**, not a caller-selected record, and still enforce one-time admission/World confirmation. The producer independently validates candidate schema, candidate ID/chain/address/mode, evidence reference/path/ID/hash, original timestamps, per-snapshot/total size, supported evidence kind, and a restricted source URL/chain/address before mapping. The new-pool feed is accepted only where its token relationship matches the candidate. Daily candles must additionally match the captured pool and token side and explicitly request one-day aggregation without filled empty intervals. Unsupported evidence is listed in `replay_ignored`; missing or invalid data is never converted into risk scores or gate votes. Reddit-derived content is rejected from immutable bundles.

Captured replay does not instantiate an HTTP client or spend source requests. Original `fetched_at`/`observed_at` values are retained, original snapshot hashes are recorded in the source ledger, and the resulting report is `historical_replay` when the stored candidate was live; synthetic evidence remains `synthetic_demo`. That label means reused source evidence, not that its prior provider assertion has been independently verified. `source_attempts` is empty and `replay_sources` counts mapped records. If no accepted source produces a usable pillar, the result is `blocked`. The snapshot contains no permission to collect fresh data and does not change concern-vote rules.

Return states:

- `partial`: a validated, version-bound report bundle exists, with `bundle_path`, `report_id`, `report_version`, `report_sha256`, per-pillar statuses, source attempts and limitations. This is a generated **pending-review draft**, not a successful complete investigation or an authenticated conclusion. Backend may import the bundle using its existing report importer, then generate and register HTML/PDF with its worker; attach the resulting report to the original case.
- `blocked`: no identity-bound usable observation exists; no bundle is installed and backend must not claim a generated report. Retry with a new run and output path after correcting the cause/budget.
- `cancelled`: no bundle is installed. Cancellation is checked before each source request, before VAE execution and before bundle commit; it cannot interrupt a currently running HTTP request or VAE subprocess.

The bundle contains frozen v0.2 `report.json`, exact-byte `digest.json`, `report.md`, `pillar-tldr.json`, source ledger, case lineage, and hashed evidence files. Writes stage in a temporary sibling directory and install by rename after validation. A pre-existing output is rejected rather than overwritten. The backend owns durable idempotency, cross-worker fencing and recovery; caller-supplied IDs or a path alone do not provide authorization or deduplication.

## Actual pillar inputs and limits

Microstructure uses identity-matched DEX Screener pool fields, or a matching GeckoTerminal pool when the former is unavailable; reserve/liquidity and volume are provider snapshots, not executable depth. On-chain maps GoPlus fields as provider reports and Sourcify runtime-match status as a provider assertion. Supply `pinned_contract_capture` for `contract_analysis.analyze` to add line-located potential control mechanisms and a source/runtime evidence copy. Verify its RPC and source provenance separately; lexical findings do not establish execution, permissions, selectivity or a honeypot. Fundamentals currently has only exact-token provider symbol metadata: project attribution, development and social sentiment require further evidence. Price health uses token-side closed daily candles and adjacent returns without filling gaps; these are separate from the legacy technical score.

Statistical risk and legacy technical outputs remain pending unless a valid identity- and daily-candle-hash-bound original VAE run with exactly 50 reconstruction columns is supplied as `legacy_model_dir`, or an explicit `vae_config={'legacy_repo': <local legacy checkout>, 'days': <positive horizon>}` is passed. The latter invokes `legacy_vae.run` only for consecutive daily history with at least two adjacent returns, then verifies the output manifest, hashes, candidate and 50 series. Two returns is a computational minimum, not a validated adequacy rule. The caller must choose the horizon under an existing policy; this module does not choose one. The local VAE subprocess has the legacy 600-second timeout and cannot be cooperatively cancelled while running. Missing dependencies, gapped history or execution failure leave those metrics pending while other pillars proceed. `vae_runner` is an injectable test boundary; never treat mock reconstructions as live output.

Optional `legacy_capture_root` plus `legacy_records` for `microstructure` and/or `onchain` invoke the preserved legacy arithmetic and attach both hash-checked input and result evidence. Original scores, labels and known limitations are retained; they are not recast as calibrated safety claims. The input capture record includes `id`, `path`, `candidate_id` and exact `sha256`; unsupported record kinds are rejected. The VAE outputs retain their full 50-series CSV and original metric JSON.

Social search remains a separate transient provider; this producer does not embed social text/hashes or claim sentiment until the backend's applicable retention and derived-artifact deletion lifecycle is reviewed. Optional one-call Terra reasoning can add a proposed, evidence-linked cross-pillar conclusion when the backend explicitly reserves a model budget and supplies the required durable callback. The default is zero model calls and the assessment stays `not_assessed`. See [Terra reasoning](terra-case-reasoning.md) for its contract and limitations.

## Verification

`python -m pytest -q tests/test_case_research.py` uses synthetic HTTP, authorization references and a mocked VAE runner to test both routes, generated v0.2/reader HTML, source failure isolation, blocked/cancelled behavior, independent retry, original score fixtures, VAE input binding and 50-reconstructions rejection. It also imports each generated bundle into the existing backend's report library and exercises its render worker. Those route tests use diagnostic selections and do not verify real World ID confirmation, case routing or the new backend job integration. The existing captured RAY source/RPC material was replayed with injected transport and rendered into a new historical draft: four pillars partial, statistical risk pending because daily history had gaps; no new provider request was made. This is component integration evidence, not the full case→authorization→job→report-library acceptance journey.

## Token-level The Graph evidence (captured replay)

`run_case(..., graph_capture_dir=<trusted capture>, graph_model_dir=<trusted saved run>, graph_technical_sha256=<optional exact digest>)` accepts the explicitly identified legacy Ethereum V3 `tokenDayDatas` capture as a separate token-level source. It does not perform a Graph request or choose a model horizon. This path preserves and verifies the original response pages, exact query and per-page variables, token identity, subgraph ID, bounded 30-day windows, closed UTC dates, priceUSD, no-fill gaps, normalized-row hash and equality with the original pages. It rejects credential-bearing gateway URLs/authorization material rather than editing source bytes. Caller must choose and authenticate the capture and any source-selection/discovery records; this slice does not claim the subgraph covers a chosen pool, the entire market, or another protocol. The V3 source returns zero rows for the supplied BLISS/RAY windows; that result says nothing about their selected V2 pools or trading elsewhere.

The optional saved Graph model is verified separately against that token-level capture: source manifest, normalized history, return CSV and values recomputed from original priceUSD rows, candidate, original risk output, run manifest, and actual 50 distinct finite reconstruction columns and dates. If `graph_technical_sha256` is provided, the original supplemental technical manifest must bind that exact technical output to the saved reconstruction, precompute code hash and original run manifest. Original pages and model files are copied unchanged as hash-checked evidence; a separately identified derived wrapper maps their existing fields into the frozen v0.2 pillar contract. User-owned legacy math and horizons are unchanged. Hash bindings are not proof of source truth, model calibration, statistical adequacy, execution safety, or faithful independent recomputation of the model. Graph inputs require a Graph model bound to those same inputs; they cannot be passed off as GeckoTerminal selected-pool candles, and Graph model input cannot be combined with the existing model/runner arguments. Empty capture with no other usable source yields blocked, not a risk score. Optional technical results stay absent unless their supplemental provenance is supplied.

Example (paths are backend-owned and access-controlled; no live source/model calls):

```python
result = run_case(case, out,
    max_source_requests=0, max_model_calls=0,
    graph_capture_dir=authorized_capture_dir,
    graph_model_dir=authorized_graph_vae_dir,
    graph_technical_sha256=trusted_supplemental_digest,
)
```

The report remains a partial pending-review draft. Historical replay retains Graph's capture time and labels it as token-level, not as a fresh pool quote. Four days in the captured SHIB run is a historical test horizon, not an adopted default. `tests/test_graph_history.py` covers native source/model binding, evidence preservation, UTC cutoff, identity and page/query tampering, credentials, duplicate dates, absent data, 50-series/model/supplemental mismatches, and leaves the original GeckoTerminal path covered by the existing suite.

The result includes `graph_capture` with source type, subgraph ID, requested date window, capture time, row and missing-day counts, and a token-level coverage limitation. For a zero-row Graph-only run, the result is blocked but still includes this source-specific status; it does not claim the token or pool is absent. Source-selection and discovery evidence, including the separate RAY V2/V3 indexing discrepancy and on-chain factory cross-check, remain the backend's authoritative selection lineage and are not inferred by this adapter.

## Base Uniswap v4 provider pool identifiers

GeckoTerminal's Base Uniswap v4 pool records can identify a pool with a 32-byte ID instead of a 20-byte contract address. The history selector accepts that form only when the captured provider record labels the DEX `uniswap-v4-base`, its `base_<pool-id>` record ID matches, and the candidate token matches the provider's base or quote relationship. Captured OHLC replay still requires the selected pool ID and token side to match its source URL, with no empty-interval filling. This is a provider-reported association, not independent on-chain verification of a pool key or proof that OHLC data exists. Other protocols, chains and arbitrary 32-byte identifiers remain unsupported unless separately verified. Uniswap's [PoolId implementation](https://github.com/Uniswap/v4-core/blob/main/src/types/PoolId.sol) defines the v4 ID as `bytes32` derived from a pool key.
