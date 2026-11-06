# Discovery deployment readiness

This branch adds a bounded **local pilot**, not a deployment-ready continuous service. The backend worker/API do not invoke this runner or expose its candidate progress. Do not start an unattended discovery worker as part of deployment until integration, operational limits and monitoring are reviewed and tested.

## Implemented here

- GeckoTerminal new-pool discovery, DEX Screener and GoPlus hint captures, persisted local SQLite leads, and a local static review queue.
- Two narrowly scoped, separately counted concern checks: G07 sampled LP-address concentration and the price-move portion of G09, both Ethereum Uniswap V2/WETH only. Other concern groups remain unknown or held. The four-distinct-concern gate and a separate human selection remain mandatory; with only these two checks enabled no candidate can qualify.
- An explicitly started, single-operator foreground loop with a per-database runner lock, bounded source requests, local retry records and queue refresh. It is not a backend worker job, production scheduler, authenticated selection surface, or high-availability service.

## Runtime configuration and dependencies

Python 3.11+, persistent writable storage for the pilot database and evidence directory, and network access to the configured free public sources and Ethereum PublicNode RPC are required. G09's historical collector uses `PUBLICNODE_TOKEN` in the environment of the **actual collector/worker process**, not in source code, frontend configuration, evidence, or logs. A token set in an unrelated PowerShell process is not automatically inherited by a service. No token is needed to render an existing queue. Source availability, quotas, licensing, and actual costs must be checked for the chosen deployment account.

The optional market capture is bounded at 40 RPC calls and no more than one attempt per database per hour in this pilot. LP capture is bounded at 17 RPC calls and no more than one attempt per five minutes per database, with at least one hour before retrying the same pool. Discovery defaults to at most 22 source requests per cycle plus one older-lead hint refresh. The loop waits at least five minutes after each cycle. These are **per-process/database pilot bounds**, not account-wide distributed rate limits, spend caps or production service-level objectives. Other programs, databases or concurrent processes can still consume the same provider quota.

## Before continuous deployment

1. Integrate with the authoritative backend job store and scheduler; give a single owner responsibility for leases, cancellation, retries, crash recovery, startup/shutdown and preventing overlapping workers.
2. Enforce account-wide source and RPC budgets, timeouts, durable backpressure, credential handling and monitoring; record source failures as unknown. Define snapshot retention, disk limits and a recovery procedure.
3. Independently validate enough genuinely distinct concern checks to satisfy the four-group gate. Preserve incomplete/held statuses, source identity and block/time provenance, and make the HITL view explain each result. Never fill a quota with unverified leads.
4. Authenticate human selection and separate it from research/report approval and publication. Local actor strings are not authentication. World ID/publication integration is owned by the designated human teammate and is not implemented here.
5. Agree a backend-owned operational activity DTO and expose real discovery events before displaying token-level live progress on the frontend. A worker heartbeat does not demonstrate that tokens are being scanned.
6. Run end-to-end tests against bounded live sources and local failure scenarios, verify queue/restart behavior and deployment configuration, and obtain the project owners' integration review.

## Current verification

The isolated discovery suite passed 43 tests with the frozen candidate schema and optional test dependencies available. Reference-only live checks exercised authenticated historical PublicNode reads, G09 price methodology and G07 LP balance/supply capture; the latter was compared against a second RPC. These checks do not establish calibrated detection, production availability or a gate-qualified case. No continuous worker or deployment is created by this branch.
