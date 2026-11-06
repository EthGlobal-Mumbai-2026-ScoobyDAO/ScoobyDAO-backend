# Scouting and research qualification milestone

**Product authority correction:** read [PRODUCT-FLOW.md](PRODUCT-FLOW.md) first. Cases is the actionable live scouting queue. Highest-actionability policy-qualified cases automatically run investigation and generate Reports; human-required cases use **Go for investigation → required World ID confirmation → the same investigation/report workflow**. Generated reports appear in Reports and link from their original Case. This supersedes any interpretation below that a passive read-only board, isolated adapters or disabled controls complete the product.

Status: active build charter, 6 November 2026. The user authorizes some policy-qualified candidates to enter bounded research automatically, while other candidates wait for verified human continuation. This supersedes blanket human candidate selection. Final report sign-off and publication remain separate actions.

This PR is an implementation charter and proposed interface agreement. It does not claim the new endpoints, verifiers, Reddit access or automatic research engine are already running. Candidate v0.1 and report v0.2 remain frozen. Read current repository LIVE-STATE before older workstream notes.

## Outcomes and owners

| Workstream | Owner | Concrete result |
|---|---|---|
| Scout to Cases | Discovery + backend + web | A bounded source run persists evidence-bound candidates; `/cases` consumes an agreed versioned read model. Highest-priority cases needing human attention appear first with reasons and freshness |
| Reference corpus | Report/reference owner | Verify user-provided SQUID, AnubisDAO, Luna Yield and Meerkat examples; add useful ETH/Base cases with exact identity, event date, mechanism, source links and uncertainty |
| Investigation | Five-pillar owner | Reusable bounded social-search provider, attributable sentiment evidence and token-contract runtime/source/control analysis; explicit partial/unavailable states |
| Agent/human authorization | Backend + human teammate | Policy-qualified automatic research and a separate verified human-continuation seam, with candidate/snapshot/policy/action binding |
| Coordination | Orchestrator | Reconcile contracts, source standards, PRs and acceptance; maintain a cold-pickup state |

Live scouting stays on Ethereum mainnet and Base. Other chains may enter a labeled historical reference corpus, not the fresh alert queue. Honeypot sell restriction, liquidity rug pull, treasury drain and a scanner allegation are different mechanisms; record what evidence actually establishes. Known historical cases help regression and report generation; they do not complete the fresh unclassified-case objective.

The first [six-case catalog](reference-catalog/README.md) covers the four user examples plus BALD and Magnate on Base, with [machine-readable identities](reference-catalog/catalog.json), claim ledger, source-access limitations and manifest. Its consistency test is offline, not independent chain decoding. BALD is a proposed historical token replay; source-reported transaction and contract roles still need verification before an actual report.

## Qualification and attention

Retain at least four distinct independently verified concern groups for normal gate qualification; five or more retains higher priority under the existing pilot. A count is neither scam probability nor a final verdict. The producer currently has only G07 and partial G09 enabled, so actual current inputs cannot reach the automatic gate. Implementing the path and testing it offline does not create a real qualified case.

The backend owns dispatch policy and recomputes qualification from allowed verifiers and integrity-checked, fresh, candidate-bound evidence. Provider hints, Reddit allegations, stale/missing inputs, unsupported chains, held verifiers and demo/replay data cannot satisfy the live automatic gate. The API does not trust a client-supplied `auto_eligible` label.

Human review can authorize bounded diagnostic research without changing gate qualification. A high-priority human case can therefore have incomplete evidence, with gaps visible. Urgency and research lane are distinct: show cases requiring an immediate human action in the attention row; show automatically admitted research in its own lane. Do not invent a percentage, calibrated risk score or fixed number of alert cards.

## One social provider, two consumers

Targeted Web3 subreddit search supplies candidate leads and investigation context through one provider boundary. Investigation owns transport/access/rate limits and attributable search results; discovery owns extraction, deduplication, chain/address resolution and subsequent checks; backend owns durable run/source state; web owns presentation.

A lead retains post URL/ID, subreddit, query, post and capture times, claimed mechanism and extracted identifiers. Until chain and contract are established, retain an unresolved lead rather than manufacturing a canonical token identity. Search accusations contribute zero verified concern votes. Sentiment is an interpretation over an attributed bounded sample, not evidence of a contract restriction or a representative population estimate.

The user has now selected **SearchApi Reddit Search** as the shared source provider. An authorized one-request live smoke returned HTTP200/Success and7 posts from the requested subreddit. All7 timestamps were older than the requested month (41–356days old). The user subsequently accepted older discussion for initial scouting/sentiment: use a configurable365-day social lookback and any_time provider query, preserving dates and contextual/historical labels. All7 fit that broader context window; token identity and current onchain risk remain separately verified. The shared adapter enforces the declared local window and preserves provider provenance/partial coverage. See [safe smoke summary](searchapi-smoke.json). Investigation owns the single provider; discovery consumes normalized leads. Keep the key server-side as `SEARCHAPI_API_KEY`; no frontend keys, hidden pagination or unbounded scheduled credit usage.

The following direct-Reddit access notes remain background, not prerequisites for the selected SearchApi provider. Official Reddit access has recently changed. Eligible approved free Data API clients have a 100-QPM OAuth quota, but new public access requests stopped on 31 October 2026; remaining public access is scheduled to end in March 2027. An external application must not assume a new free key. Implement a replaceable provider, bounded approved-access adapter, explicit unavailable state and no scraping fallback. See [source notes](SOURCES.md).

## First integrated acceptance

1. One bounded run, its source status and actual candidate/lead records survive process restart and reach the Cases read model. Unresolved identity, stale data, partial failures and empty success differ from a disconnected service.
2. Backend policy fixtures exercise qualified auto admission with one durable investigation per authorization/decision. Actual live admission requires real supported evidence; synthetic positive tests are labeled tests.
3. Human-required input pauses. Without a configured verifier it stays blocked. Approve, reject, revise, expire, cancel, replay and evidence/policy mutation have meaningful continuation tests; no frontend boolean or actor label grants authority.
4. Both lanes invoke the same bounded investigation boundary and preserve source/claim/digest lineage. Unimplemented pillars remain explicit; source-only control findings do not become live honeypot proof.
5. Cases desktop/mobile checks cover attention ordering, lanes, evidence/freshness, failure states and reference separation. Existing research report cards and download integrity remain intact. Demo market/case flows remain visibly separate.
6. Report rendering stays pending final review. Candidate authorization cannot be reused as report sign-off or publication authority.

The source/DTO transition agreement is in [INTERFACE.md](INTERFACE.md); the teammate's implementation scope is in [WORLD-AGENT-BUILD-CHARTER.md](WORLD-AGENT-BUILD-CHARTER.md). Workstream acceptance must be recorded before adopting a new schema. No production deployment, account registration, live World login, chain transaction, new paid model/provider call or indefinite scanner is initiated by this charter.
