# Scooby DAO — SHIB historical replay draft

Report version: historical-replay-v1 | Mode: historical replay | Review: pending

**No current SHIB assessment has been made.** This is a deterministic import of historical, unvalidated samples, not live research. The selected-candidate fixture is simulated and is not a real human selection.

## Scope and identity

Ethereum chain 1; structured address `0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE`. Address syntax and source consistency do not establish live identity. The technical-series window is 2024-09-02T00:00:00 to 2025-09-26T00:00:00; it is not a common window for all five pillars.

## Assessment and decision

Historical input preview. No new Scooby DAO assessment has been made.
No proposed research verdict, calibrated probability, entry score or financial decision is inferred. Human sign-off is pending; approval must bind the exact report and Markdown content.

## Pillar review

### Microstructure

Status: **partial**. The historical pool sample reports zero liquidity and depth, and zero sampled LP positions, while its slippage values and narrative suggest favorable execution and diversity. This is a contradiction requiring fresh source and method checks, not evidence of either condition.

Evidence: legacy-microstructure

Limitations: Historical unvalidated data.; Zero liquidity/depth and zero sampled positions conflict with execution/diversity claims.

### Onchain

Status: **partial**. The structured token address differs from a malformed address in the original thesis (0x95aD61b0a150d79219dCF64E1E6Cc0F0B64C4cE). Historical reserve narrative and raw token ordering/units conflict; verify decimals, block and pool before interpreting ownership, reserves or locks.

Evidence: legacy-onchain

Limitations: Historical unvalidated data.; Textual token identity and reserve explanation need validation.

### Fundamentals

Status: **partial**. The extraction returned an empty repository list. This is missing or incomplete coverage, not proof of no development. Sentiment lacks recovered post-level provenance and its assertions are not adopted.

Evidence: legacy-fundamentals

Limitations: Historical unvalidated data.; Empty GitHub results do not establish no development; sentiment lacks recovered per-post provenance.

### Statistical Risk

Status: **partial**. Values are legacy model outputs, with calibration unestablished. The legacy max_drawdown label is not established as peak-to-trough drawdown; no forecast or probability is inferred.

Evidence: legacy-statistical_risk

Limitations: Historical model-derived values; no calibration established.; Legacy max_drawdown label does not establish peak-to-trough drawdown.

### Technical Health

Status: **partial**. Historical series and indicators are reconstruction-derived. Definitions, data provenance and interpretations need independent review; they do not establish a current trend or prediction.

Evidence: legacy-technical_health

Limitations: Historical reconstruction-derived indicators; not a current price forecast.; Indicator definitions and agreement interpretation need review.

## Evidence and provenance

Hashes refer to the exact copied source bytes in `contract/fixtures/`; snapshots are not independent corroboration. Full imported fields are in report.json; all historical numerical fields remain unvalidated.

- `legacy-microstructure` — `legacy/ma_shib.json`; SHA-256 `a14cdd26010aaa151e3833639a0a17028c4c076f27ee0cf4b0c5439e8f0287f4`; block 23455284; observed None; fetched None.
- `legacy-onchain` — `legacy/ca_shib.json`; SHA-256 `59a220d101b3a3007770655fd4e8fd64a2baa7a54acd49457276c0dfe52a74a4`; block 23455002; observed None; fetched None.
- `legacy-fundamentals` — `legacy/fa_shib.json`; SHA-256 `d716d7351ee96a27f8f242a8e975cfb594908d2b0172291a5268093e48f97544`; block None; observed None; fetched None.
- `legacy-statistical_risk` — `legacy/risk_shib.json`; SHA-256 `b60d5d8a8158b544155a3fcff37faba50dcd2c707aaa2cf1181b6aee800f273a`; block None; observed None; fetched None.
- `legacy-technical_health` — `legacy/tech_shib.json`; SHA-256 `3f6b1e36903e0147c99635c54ff640d2e31ab564b1a10340e6feece048e5d52c`; block None; observed 2025-09-26T00:00:00; fetched None.

## Outstanding work

Verify identity and acquire fresh source snapshots, source coverage and timestamps. Resolve contradictory inputs and reserve units; establish calculation methods and provenance. Specify the research assessment question and method with the user, then produce a proposed assessment for human review. A version-matched PDF is unavailable. No publication is authorized.

## Mapped historical fields

Values and chart series are in report.json and mapping-manifest.json. Source values are unvalidated. Missing coverage remains partial.

### Microstructure

Historical venue reports liquidity "0", upward 5% depth 0.0, and first slippage 2.0000001655807422e-08% (source label). These inputs require reconciliation; execution is unvalidated.

- depth_up_pct2: 0.0 (quote token (USDC), source notional); historical, unvalidated.
- depth_up_pct5: 0.0 (quote token (USDC), source notional); historical, unvalidated.
- depth_up_pct10: 0.0 (quote token (USDC), source notional); historical, unvalidated.
- depth_down_pct2: 0.0 (quote token (USDC), source notional); historical, unvalidated.
- depth_down_pct5: 0.0 (quote token (USDC), source notional); historical, unvalidated.
- depth_down_pct10: 0.0 (quote token (USDC), source notional); historical, unvalidated.
- legacy_microstructure_score: 7 (legacy score (scale unverified)); historical, unvalidated.
- legacy_mev_score: 68 (legacy score (scale unverified)); historical, unvalidated.
- sampled_positions: 0.0 (positions); historical, unvalidated.
- slippage_0_notionalQuote: 1000.0 (quote token (USDC), source notional); historical, unvalidated.
- slippage_0_slippagePct: 2.0000001655807422e-08 (percent as labeled by source); historical, unvalidated.
- slippage_1_notionalQuote: 5000.0 (quote token (USDC), source notional); historical, unvalidated.
- slippage_1_slippagePct: 2.0000001655807422e-08 (percent as labeled by source); historical, unvalidated.
- slippage_2_notionalQuote: 10000.0 (quote token (USDC), source notional); historical, unvalidated.
- slippage_2_slippagePct: 2.0000001655807422e-08 (percent as labeled by source); historical, unvalidated.
- slippage_3_notionalQuote: 25000.0 (quote token (USDC), source notional); historical, unvalidated.
- slippage_3_slippagePct: 2.0000001655807422e-08 (percent as labeled by source); historical, unvalidated.
- slippage_4_notionalQuote: 50000.0 (quote token (USDC), source notional); historical, unvalidated.
- slippage_4_slippagePct: 2.0000001655807422e-08 (percent as labeled by source); historical, unvalidated.
- slippage_5_notionalQuote: 100000.0 (quote token (USDC), source notional); historical, unvalidated.
- slippage_5_slippagePct: 2.0000001655807422e-08 (percent as labeled by source); historical, unvalidated.
- Historical source raw liquidity: "0".

Quality: Historical unvalidated data.; Zero liquidity/depth and zero sampled positions conflict with execution/diversity claims.

### Onchain

The historical extraction reports role-based controls; roles are listed. It reports no liquidity lock, and pause status is unknown. These source findings are unverified.

- pct_locked: 0.0 (unit unknown); historical, unvalidated.
- Historical source flags: [{"code": "LP_NOT_LOCKED", "severity": "med", "evidence": {"pair": "0x811beEd0119b4AfCE20D2583EB608C6F7AF1954f", "locker": null}}].
- Historical source roles: ["DEFAULT_ADMIN_ROLE"].
- Historical source lpLocked: false.
- Historical source pauseStatus: "unknown".
- Historical source ownershipModel: "AccessControl".
- Historical source raw totalSupply: "999982338526316511947999622632193".
- Historical source raw reserve r0: "48564515213896973554796138070".
- Historical source raw reserve r1: "142720766384044171653".

Quality: Historical unvalidated data.; Textual token identity and reserve explanation need validation.

### Fundamentals

Historical 24-hour price change: up (2.434950751331977%, source-labeled); volume change: down (-27.574333806143404%, source-labeled). Repository extraction coverage remains incomplete.

- latest_price: 1.1911031638896355e-05 (USD per token); historical, unvalidated.
- price_change_24h: 2.434950751331977 (percent as labeled); historical, unvalidated.
- volume_change_24h: -27.574333806143404 (percent as labeled); historical, unvalidated.
- Historical source repository extraction: []. Null or empty source result does not establish absence in the real world.
- daily_returns: 7 historical observations (fractional return (multiply by 100 for percent display)); full points and provenance in report.json.

Quality: Historical unvalidated data.; Empty GitHub results do not establish no development; sentiment lacks recovered per-post provenance.

### Statistical Risk

The historical model reports VaR 95 1.0845, expected shortfall 95 -3.4631, and horizon 4 days. Values are source-labeled percentages; model calibration remains unverified.

- var_90: 0.845 (percent, legacy model output); historical, unvalidated.
- var_95: 1.0845 (percent, legacy model output); historical, unvalidated.
- var_99: 1.5338 (percent, legacy model output); historical, unvalidated.
- var_custom: 1.0845 (percent, legacy model output); historical, unvalidated.
- time_horizon_days: 4 (days); historical, unvalidated.
- confidence_level: 0.95 (fraction); historical, unvalidated.
- average_daily_volatility: 1.8505 (percent, legacy model output); historical, unvalidated.
- expected_shortfall_95: -3.4631 (percent, legacy model output); historical, unvalidated.
- max_drawdown: -42.7684 (percent, legacy model output); historical, unvalidated.
- portfolio_volatility_annualized: 29.3758 (percent, legacy model output); historical, unvalidated.

Quality: Historical model-derived values; no calibration established.; Legacy max_drawdown label does not establish peak-to-trough drawdown.

### Technical Health

The historical reconstruction labels trend "bearish" and reports RSI mean 49.05164466825245. Indicator definitions and interpretations remain unverified.

- legacy_overall_health_score: 50.54716986407557 (legacy score (scale unverified)); historical, unvalidated.
- rsi_latest: 49.05164466825245 (RSI source scale); historical, unvalidated.
- macd_histogram: -0.0001456603176673645 (unit unknown); historical, unvalidated.
- volatility_mean: 1.4528301359244293 (unit unknown); historical, unvalidated.
- bullish_macd_ratio: 0.48 (ratio); historical, unvalidated.
- Historical source legacy overall health grade: "D".
- series_overall_health_scores: 30 historical observations (legacy score (scale unverified)); full points and provenance in report.json.
- series_rsi_mean: 30 historical observations (RSI source scale); full points and provenance in report.json.
- series_rsi_std: 30 historical observations (RSI source scale); full points and provenance in report.json.
- series_volatility_mean: 30 historical observations (unit unknown); full points and provenance in report.json.
- series_bullish_consensus: 30 historical observations (ratio); full points and provenance in report.json.

Quality: Historical reconstruction-derived indicators; not a current price forecast.; Indicator definitions and agreement interpretation need review.
