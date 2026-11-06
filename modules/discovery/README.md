# Scooby DAO discovery source export

Portable local source for backend integration, prepared 6 November 2026 and subsequently extended on a topic branch. Python 3.11+. `manifest.json` records the original export and its hashes, not the current modified files. This directory intentionally omits runtime databases, real source snapshots, credentials, vendor libraries and copies of the frozen shared contracts. Import into the backend's chosen module boundary; these files currently use flat sibling imports and should be kept together or adapted consistently.

## Contract

The selected-candidate handoff uses the frozen shared candidate **v0.1** schema under the agreed overall **v0.2** contract release. Expected SHA-256: `9a45955834e66c9a86f8f0e8cd7eb915e03517ee6e601d1c24570bc687ed530b`. The shared report v0.2 schema SHA-256 is `8a5f793dce8c75c18c3ee8ade4c26e76fe51ee489173ff59299ad85b5963bf55`. Resolve these from the backend's authoritative shared contract location; do not create another canonical copy or mutate the release. Candidate evidence paths must resolve within their bundle and match hashes; source truth, identity and human authorization require additional checks.

`candidate_validation.validate(candidate, schema, selected=False, evidence_root=None)` performs JSON Schema validation, chain/address ID consistency, null-score semantics and resolvable trigger references. `selected=True` also requires selected state/status, nonblank actor/reason and a timezone-qualified timestamp. Supplying `evidence_root` checks safe relative paths, rejects symlinks and checks file SHA-256. It does not authenticate a human, prove source accuracy or run the discovery gate.

```sh
python candidate_validation.py --candidate path/to/candidate.json --schema path/to/shared/candidate.schema.json --selected --evidence-root path/to/bundle
```

The validator and full schema test require `jsonschema`; `chainlink_probe.py` requires `pycryptodome`. Test dependencies are in `requirements-test.txt`. Network source adapters otherwise use Python standard libraries.

## Mechanisms and interfaces

- `discovery.py`: SQLite candidates, fixtures, deduplication, selection/defer and JSON selected-array export. `identity(chain,address)`, `connect(path)`, `action(db,id,kind,actor,reason)` are the current callable interfaces. Its CLI refuses selecting a live record directly; use the review queue. The general `action` function is a local mechanism, not a security/authorization boundary.
- `live_pilot.py`: bounded one-shot GeckoTerminal new-pool discovery for Ethereum and Base, followed by DEX Screener and GoPlus captures, SHA-addressed snapshots, and SQLite state. `run(db,root,limit,budget,chain_names)` returns run information. Provider output is a lead/hint, not a verified vote. New-pool discovery is incomplete; the standalone command defaults to a budget of 10 GET calls.
- `continuous_pilot.py`: local single-operator loop that repeats discovery and regenerates the review queue. A database-scoped lock prevents duplicate instances of this runner. Each cycle defaults to at most 22 discovery source calls plus one optional older-lead hint refresh, followed by at least five minutes of rest. LP collection attempts at most one pool per five minutes, up to 17 RPC calls, and retries each pool no sooner than one hour. Optional experimental archive collection reserves at most one pool per hour and caps it at 40 RPC calls. These limits do not coordinate with other programs. It is not wired to the backend worker and is not a production service.
- `review_queue.py`: `queue(db,root,as_of=None)` returns eligible records and concern detail; `render` writes static HTML/JSON; `select` re-evaluates the gate before recording a local user selection. It displays up to five, ranked by count of distinct triggered concerns and candidate ID for ties; the other leads stay monitored. It verifies evidence path/hash and a provisional one-hour observation-age guard, and escapes HTML. Static output is point-in-time and local selection is not authenticated; multi-user/concurrent operation is not implemented.
- `rpc_snapshot.py`, `source_snapshot.py`, `live_source_probe.py`, `chainlink_probe.py`: bounded read-only source tools. RPC captures a finalized block and reports failed calls as unknown. Sourcify match and GoPlus fields are clues, not validated token safety or control semantics. Chainlink probe resolves Ethereum ETH/USD and captures update time; it does not provide all token/security data.
- `lp_concentration.py` and `collect_lp_concentration.py`: G07 pilot verifier for direct LP-token address balances in a single Ethereum Uniswap V2/WETH pool. GoPlus LP/token holder addresses are hints only; block-pinned on-chain balance and total supply form the measurement. A sampled address above 15% of total pool LP supply triggers one group, while a smaller sample stays unknown. Known burn and low reserved addresses are excluded; addresses may represent pooled custody, and this is neither beneficial ownership nor all-pool coverage. Base and other pool versions are unknown. One reference capture was cross-checked against a second RPC provider for chain, block, supply and largest sampled balance; this is a method sanity check, not proof of every provider response.
- `market_activity.py` and `collect_market_activity.py`: experimental G09 Ethereum Uniswap V2/WETH historical price-change method and bounded collection. The verifier's unit tests use synthetic data; unauthenticated historical RPC requests received HTTP 403; an authenticated reference-pool collector run subsequently completed with 31 RPC calls. This narrow price-move condition is enabled for the pilot. The collector binds captured values to the RPC transcript and rejects reserve updates and Chainlink prices older than one hour at either block. It measures a single pool, not a global market price. A below-threshold price move stays unknown because volume change is not evaluated. Base, 24h volume change and other pool protocols are unsupported.

## Historical RPC authentication

The experimental market-activity collector reads the optional `PUBLICNODE_TOKEN` environment variable and sends it as a URL path component to Ethereum PublicNode. Keep the token in the process environment; do not commit it or include it in evidence. Without a token, the collector uses the public endpoint, which may reject historical calls. Authentication is recorded without the token.

To check the full collector from the shell that holds the token, run `python smoke_publicnode.py --scratch <temporary-work-directory>` from this directory. The read-only test uses a known reference pool, a temporary database and snapshots, up to 40 RPC calls, and one pool metadata request; it cleans up the temporary data. A pass does not qualify a candidate or start an investigation.

## Pilot policy and honest readiness

User endorsed a pilot gate of at least **four independently verified concern groups**, with five or more higher priority. Show up to five qualified cases; never fill remaining positions with unverified/below-gate leads. Each group contributes at most one vote; do not count correlated signals as independent concerns or treat the count as probability. The broad initial discovery stack remains monitored separately, with selected state retained. User subsequently granted a one-off BLISS diagnostic exception outside the normal gate; it does not authorize an automatic bypass or change this code's rules.

**Two narrowly scoped metric-specific verifiers are enabled:** G07 for sampled Ethereum V2/WETH pool LP balances and the price-move portion of G09 for Ethereum V2/WETH. Their sources and scopes are described above. With only two enabled groups, no live case can meet the four-group gate yet. G01 control, G02 transfer restrictions, G03 holder concentration, G04 LP removal and G05 execution depth still require validated source-backed implementations. G06 liquidity shape, G08 venue divergence, G10 statistical risk, G11 trend and G12 indicator extremes remain held pending method/data validation. `live_pilot.evaluate()` illustrates counting on supplied inputs and is not trusted by the live queue. Provider output, source-code keyword matches, failed calls and missing data do not cast votes.

Live observations require source and observation times, chain/address identity, block/finality where relevant, provenance, documented coverage and explicit unknowns. The current first-hand source feeds lack per-result observation timestamps and are not gate inputs. The one-hour guard in `review_queue.py` is a provisional local safety check, not a finalized production SLA. No production fraud, probability or financial judgment is claimed.

## Local usage

From this directory:

```sh
python discovery.py --db runtime/state.sqlite replay --file fixtures.json
python discovery.py --db runtime/state.sqlite status
python live_pilot.py --db runtime/live.sqlite --output runtime --limit-per-chain 2 --budget 10
python review_queue.py --db runtime/live.sqlite --root runtime render --output runtime/review-queue.html --json-output runtime/review-queue.json
```

Create `runtime/` first. Live scan performs external read-only calls. `fixtures.json` is entirely synthetic and its test actor is not a real approval. For an eligible case only, use `review_queue.py --db runtime/live.sqlite --root runtime select --candidate-id <id> --actor <name> --reason <reason>`; then `discovery.py --db runtime/live.sqlite export-selected`. The HTML is a snapshot and must be refreshed; selection recomputes the gate. The local loop must be started explicitly; the backend worker does not run it.

## Local continuous pilot

From this directory, start a foreground loop with `python continuous_pilot.py --db runtime/live.sqlite --output runtime`. Stop it with Ctrl+C. The loop samples one eligible LP pool per cycle by default; use `--skip-lp` to disable that collection. Add `--collect-market` to attempt experimental historical market captures using `PUBLICNODE_TOKEN` from the same shell; without the token, that capture is skipped. The loop waits at least 300 seconds **after each cycle**, reserves at most one market attempt per hour and one LP attempt per five minutes, and retries an LP pool no sooner than one hour. It refreshes at most one older lead’s provider hints per five minutes. `--once` runs one cycle and exits; `--budget` and `--limit-per-chain` bound each scan. Failures are reported without provider exception text; `partial` and `unavailable` are not successful verification. The lock and attempt records persist per database, but other scripts and other databases can still call providers independently. Snapshots and the database grow over time; this prototype does not implement retention, account-wide rate limits, authentication, monitoring, or a production scheduler.

The queue remains empty until enough separate metric-specific checks are independently validated and enabled. Even both currently enabled concern checks cannot satisfy the four-group threshold.

See [deployment readiness](DEPLOYMENT-READINESS.md) for process-owned credentials, current per-run limits and the blockers to unattended operation.

## Tests and integration next step

Install test dependencies in your chosen environment, set `SCOOBY_CANDIDATE_SCHEMA` to the backend's authoritative shared candidate schema, then run `python -m unittest discover -s . -v`. Without the variable or jsonschema, shared-schema tests skip; without pycryptodome, Chainlink tests skip. The export was tested with both dependencies and the exact shared schema: **21 tests passed, no skips**. Test inputs and simulated decisions are not observations or human selections.

Integrate these files under a backend-owned module, resolve imports and dependency pinning, use the agreed shared schema, and make the source/persistence interfaces fit the backend's operational boundaries. Then build source-backed checks for enough additional distinct groups to apply the four-concern gate. Preserve 4/5 gating, monitored remainder, and explicit human selection. Automated authentic authorization, safe concurrency, complete retry/checkpoint behavior, evidence retention and operational limits remain future work.

Reference-only validation on 6 November 2026: a 31-call dRPC pool calculation produced a 24-hour USD move of -3.5617%, compared with DEX Screener’s -3.4% for the same pool; windows and sources differ. A separate LP capture was compared with dRPC at the same block, with chain, block hash/time, LP supply and largest sampled balance agreeing. The reference queue check produced one G07 vote and zero qualified candidates; no reference token was selected. Raw live responses from these transient checks were not retained in this branch.

The revised G09 freshness guard was separately exercised against a finalized reference-pool history from dRPC: reserve update ages were 2,352 seconds and 156 seconds at the historical and latest blocks, respectively. Both checks are bounded to one pool and one reference case; they are not calibrated risk scores.

## Proposed screening snapshot adapter

`screening_result.screening_result(record, evidence_root, run_id, as_of=None)` produces a **proposed**, additive `scooby.discovery-screening/1-proposal` result from a live candidate and the two pinned local verifiers. It does not mutate candidate/report schemas, publish a backend API, start research, authenticate a person, or decide report approval. See [screening result handoff](SCREENING-RESULT.md) for fields, limitations, and the backend integration boundary. The backend owns the final Cases read model and any job/authorization decision.

The user has since authorized a bounded automatic-research lane for candidates that pass a versioned policy and the unchanged four-independent-concern gate. Earlier references here to mandatory human selection describe the current local CLI, not a restriction on the future authorized auto lane. With only G07 and partial G09 enabled, this adapter cannot identify any currently auto-eligible candidate. Human-authorized diagnostic research does not change gate qualification.

## Reddit lead adapter (provider integration proposed)

`reddit_leads.adapt(result, allowed_subreddits=..., allowed_queries=...)` consumes the investigation team's `scooby.reddit-leads/1` shared-provider result in memory. It performs no HTTP calls and writes no storage. It keeps minimal short-lived source references, query/window, extracted identifiers, scope states and provider cursors, while excluding excerpts and content hashes from the returned object. Limit one call to five requests, 40 examined posts and three configured subreddits. Expiry is at most one hour after capture and seven days after posting; a caller-supplied deletion list removes source references immediately. The backend must implement authorized deletion checks and TTL enforcement, and must not put Reddit data in immutable candidate evidence, reports or snapshots. The adapter alone cannot detect later source deletion.

Repeated post IDs and matching address/chain mentions are grouped without treating posts as independent corroboration. `resolve_identity` requires an explicit unambiguous Ethereum/Base chain mention, a matching full address, a live server-owned candidate and fresh chain-bound evidence accepted by a pinned verifier; this validates token identity, not the Reddit allegation or association. Currently only Ethereum V2/WETH has such verifiers, so Base resolution remains unavailable. `deduplicate_resolutions` groups resolved references by canonical chain/address without adding votes. Tickers, missing/ambiguous chains and unsupported chains stay unresolved. The source association must never add a concern vote. The backend owns the actual durable candidate bridge, source retention/deletion handling and dispatch-time revalidation.

The provider currently returns per-community exhaustion/failure/truncation and next cursors, but its callable does not accept a resume cursor; the adapter exposes that limitation. Missing approved Reddit access stays unavailable and there is no scraper fallback. Synthetic historical fixture `fixtures/reddit-lead-synthetic.json` is invented and is not live data. A separate unauthenticated Reddit smoke request returned HTTP 403; the exact cause is unknown, and authorized access has not been proven.
