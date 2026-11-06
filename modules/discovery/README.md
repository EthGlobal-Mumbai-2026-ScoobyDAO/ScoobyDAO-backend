# Scooby DAO discovery source export

Portable local source for backend integration, prepared 6 November 2026. Python 3.11+. This directory intentionally omits runtime databases, real source snapshots, credentials, vendor libraries and copies of the frozen shared contracts. Import into the backend's chosen module boundary; these files currently use flat sibling imports and should be kept together or adapted consistently.

## Contract

The selected-candidate handoff uses the frozen shared candidate **v0.1** schema under the agreed overall **v0.2** contract release. Expected SHA-256: `9a45955834e66c9a86f8f0e8cd7eb915e03517ee6e601d1c24570bc687ed530b`. The shared report v0.2 schema SHA-256 is `8a5f793dce8c75c18c3ee8ade4c26e76fe51ee489173ff59299ad85b5963bf55`. Resolve these from the backend's authoritative shared contract location; do not create another canonical copy or mutate the release. Candidate evidence paths must resolve within their bundle and match hashes; source truth, identity and human authorization require additional checks.

`candidate_validation.validate(candidate, schema, selected=False, evidence_root=None)` performs JSON Schema validation, chain/address ID consistency, null-score semantics and resolvable trigger references. `selected=True` also requires selected state/status, nonblank actor/reason and a timezone-qualified timestamp. Supplying `evidence_root` checks safe relative paths, rejects symlinks and checks file SHA-256. It does not authenticate a human, prove source accuracy or run the discovery gate.

```sh
python candidate_validation.py --candidate path/to/candidate.json --schema path/to/shared/candidate.schema.json --selected --evidence-root path/to/bundle
```

The validator and full schema test require `jsonschema`; `chainlink_probe.py` requires `pycryptodome`. Test dependencies are in `requirements-test.txt`. Network source adapters otherwise use Python standard libraries.

## Mechanisms and interfaces

- `discovery.py`: SQLite candidates, fixtures, deduplication, selection/defer and JSON selected-array export. `identity(chain,address)`, `connect(path)`, `action(db,id,kind,actor,reason)` are the current callable interfaces. Its CLI refuses selecting a live record directly; use the review queue. The general `action` function is a local mechanism, not a security/authorization boundary.
- `live_pilot.py`: bounded one-shot GeckoTerminal new-pool discovery for Ethereum and Base, followed by DEX Screener and GoPlus captures, SHA-addressed snapshots, and SQLite state. `run(db,root,limit,budget,chain_names)` returns run information. Provider output is a lead/hint, not a verified vote. New-pool discovery is incomplete; default budget is 10 GET calls, no unattended service, durable global rate limiter, cost billing or robust retry scheduler.
- `review_queue.py`: `queue(db,root,as_of=None)` returns eligible records and concern detail; `render` writes static HTML/JSON; `select` re-evaluates the gate before recording a local user selection. It displays up to five, ranked by count of distinct triggered concerns and candidate ID for ties; the other leads stay monitored. It verifies evidence path/hash and a provisional one-hour observation-age guard, and escapes HTML. Static output is point-in-time and local selection is not authenticated; multi-user/concurrent operation is not implemented.
- `rpc_snapshot.py`, `source_snapshot.py`, `live_source_probe.py`, `chainlink_probe.py`: bounded read-only source tools. RPC captures a finalized block and reports failed calls as unknown. Sourcify match and GoPlus fields are clues, not validated token safety or control semantics. Chainlink probe resolves Ethereum ETH/USD and captures update time; it does not provide all token/security data.
- `market_activity.py` and `collect_market_activity.py`: experimental G09 Ethereum Uniswap V2/WETH historical price-change method and bounded collection. The verifier's unit tests use synthetic data; a live archive-RPC smoke attempt received HTTP 403. It is **not registered/enabled** in the queue. The collector, provider provenance and freshness need independent live validation before activation; Base, 24h volume change and other pool protocols are unsupported.

## Pilot policy and honest readiness

User endorsed a pilot gate of at least **four independently verified concern groups**, with five or more higher priority. Show up to five qualified cases; never fill remaining positions with unverified/below-gate leads. Each group contributes at most one vote; do not count correlated signals as independent concerns or treat the count as probability. The broad initial discovery stack remains monitored separately, with selected state retained. User subsequently granted a one-off BLISS diagnostic exception outside the normal gate; it does not authorize an automatic bypass or change this code's rules.

**No metric-specific live verifiers are currently enabled.** `review_queue.VERIFIERS` is empty. Consequently no live case qualifies through the current implementation. G01 control, G02 transfer restrictions, G03 holder concentration, G04 LP removal, G05 execution depth, G07 LP concentration and G09 market activity each require validated source-backed implementations; G09 is experimental as described above. G06 liquidity shape, G08 venue divergence, G10 statistical risk, G11 trend and G12 indicator extremes remain held pending method/data validation. `live_pilot.evaluate()` illustrates counting on supplied inputs and is not trusted by the live queue. Provider output, source-code keyword matches, failed calls and missing data do not cast votes.

Live observations require source and observation times, chain/address identity, block/finality where relevant, provenance, documented coverage and explicit unknowns. The current first-hand source feeds lack per-result observation timestamps and are not gate inputs. The one-hour guard in `review_queue.py` is a provisional local safety check, not a finalized production SLA. No production fraud, probability or financial judgment is claimed.

## Local usage

From this directory:

```sh
python discovery.py --db runtime/state.sqlite replay --file fixtures.json
python discovery.py --db runtime/state.sqlite status
python live_pilot.py --db runtime/live.sqlite --output runtime --limit-per-chain 2 --budget 10
python review_queue.py --db runtime/live.sqlite --root runtime render --output runtime/review-queue.html --json-output runtime/review-queue.json
```

Create `runtime/` first. Live scan performs external read-only calls. `fixtures.json` is entirely synthetic and its test actor is not a real approval. For an eligible case only, use `review_queue.py --db runtime/live.sqlite --root runtime select --candidate-id <id> --actor <name> --reason <reason>`; then `discovery.py --db runtime/live.sqlite export-selected`. The HTML is a snapshot and must be refreshed; selection recomputes the gate. No deployed or continuously running process is included.

## Tests and integration next step

Install test dependencies in your chosen environment, set `SCOOBY_CANDIDATE_SCHEMA` to the backend's authoritative shared candidate schema, then run `python -m unittest discover -s . -v`. Without the variable or jsonschema, shared-schema tests skip; without pycryptodome, Chainlink tests skip. The export was tested with both dependencies and the exact shared schema: **21 tests passed, no skips**. Test inputs and simulated decisions are not observations or human selections.

Integrate these files under a backend-owned module, resolve imports and dependency pinning, use the agreed shared schema, and make the source/persistence interfaces fit the backend's operational boundaries. Then independently verify the experimental G09 path and build source-backed checks for enough distinct groups before enabling any verifier. Preserve 4/5 gating, monitored remainder, and explicit human selection. Automated authentic authorization, safe concurrency, complete retry/checkpoint behavior, evidence retention and operational limits remain future work.
