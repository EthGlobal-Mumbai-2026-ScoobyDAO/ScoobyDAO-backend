# World Agent: two-way investigation authorization handoff

**Required product gate:** a human reviews a scouted Case, clicks **Go for investigation**, completes World ID confirmation, and only then may the backend continue that Case through investigation and generated report creation. This is required for the human lane; it is distinct from final report sign-off/publication. Policy-qualified strongest scouts use the automatic lane without a human click. See [PRODUCT-FLOW.md](PRODUCT-FLOW.md). An unavailable verifier is an unfinished integration, not the target behavior.

Owner: human teammate. Integrators: backend and web. Status: implementation build charter; live provider verification is not performed by this PR.

## Protected action and two deliverables

The action is **start or resume one bounded investigation for a particular candidate and evidence/policy revision**. It grants no report approval, scam certification, publication or financial action. There are two handoffs:

**A — Our system to the agent.** Backend/discovery publish a deterministic, versioned qualification decision, safe read model, dispatch/resume API and verifier interface. A delegated authenticated agent can request automatic admission only when all policy/evidence/budget conditions hold. Backend rechecks those conditions immediately before committing a job. The request carries no authority to change its own policy, claim new verified concern groups or broaden a budget.

**B — Teammate to our system.** Implement and test AgentKit/delegation verification and explicit human verification for blocked cases behind that interface. Return a server-verifiable, scope-bound principal/decision result; the backend consumes it transactionally to resume the correct workflow. Supply provider config, pinned versions/network, failure semantics, consent UI requirements, test vectors and a reviewed integration PR. An unconfigured or failed verifier leaves the case waiting.

## Separate identity, permission and decision

AgentKit proves a relationship between an agent and a World ID-verified human. It does not prove a suspicious token, a satisfied Scooby concern group or informed consent to a specific investigation. World device-grant authentication similarly identifies a reviewer; the application must display and bind the action the person intends to authorize. The currently merged `publication/` module concerns report publication targets and is not automatically a candidate authorization service.

The teammate may reuse reviewed issuer/JWKS/allowlist primitives from `publication/`, but must keep candidate-action targets, receipts, nonces and consumption separate from publication targets/receipts. Keep proof acquisition and app authorization separate. Do not interpret an agent wallet registration, frontend `verified: true`, local operator actor string or old publication receipt as this action's authorization.

## Proposed binding (freeze with backend)

Use an additive versioned target/receipt profile rather than editing frozen candidate/report schemas. Each authorization target binds:

- Canonical candidate ID, chain ID and contract address; immutable screening/evidence snapshot digest and revision; qualification decision ID and exact policy ID/version/digest.
- Action `investigation:start` or a separately permitted `investigation:resume`; selected lane and diagnostic-exception status; applicable run ID on resume; explicit allowed bounded work/budget reference.
- Service audience/resource, nonce, issued/expiry times and a human-readable explanation of evidence, gaps and what continuation does.

The server-side verifier result additionally binds principal type (`agent` or `human`), verified issuer/principal reference, delegation/action scope where relevant, decision (`approve`, `reject`, `revise`), verification time, validity/revocation state and proof/receipt reference. Keep raw credentials, proof secrets and personal identifiers out of public DTOs, logs and report assets. Pseudonymous references still need appropriate access control.

An agent auto decision is an agent/policy authorization record. It must never be labeled as a human sign-off. Human consent is for the displayed candidate/snapshot/action; changes to candidate, evidence, policy or allowed scope invalidate continuation and require re-evaluation. Diagnostic approval records the exception and cannot promote its gate status.

## API and state contract

Backend owns exact route/JSON naming in [INTERFACE.md](INTERFACE.md). Required behavior:

1. Read candidate/screening decision and allowed next action without triggering research. Expose source/verification availability and why human action is required.
2. Begin a bound verification/consent attempt under authenticated access. Permit pending polling/cancel without leaking provider secrets; enforce expiry and provider backoff.
3. Accept a verified principal+decision at a private server boundary. Browser assertions or caller-supplied snapshot hashes are not trusted. Verify audience, nonce, exact binding, allowlist/delegation, freshness and revocation.
4. In one transaction, recheck current evidence/policy/budget, consume the correct unspent authorization, persist audit and enqueue at most one investigation. Replays return the existing result only for an identical idempotent request; conflicts/tampering fail. Do not consume authority without a recoverable committed dispatch record.
5. Rejection/revision/expiry/revocation never starts work. An expired or changed case can begin a new attempt without reviving the old authorization. Retry/restart must not create duplicate research runs.

The common workflow is `observed → screened → auto-qualified / waiting-for-human / monitored`. Auto-qualified plus valid delegated authority and budget can enqueue research. Waiting-for-human plus a fresh verified authorization can enqueue diagnostic or qualified research as recorded. Both lead through the same investigation/report path and still require separate final report review before publication.

## AgentKit integration choices the teammate must pin

Pin the SDK/package and challenge protocol, exact AgentBook chain/deployment and RPC/finality assumptions, signer/audience validation, storage/replay strategy, registration/delegation revocation and principal rate limits. The current World integration guide resolves AgentBook on World Chain, while the GitHub README still describes a Base relay default; resolve this against the pinned package and canonical deployment rather than mixing defaults. This infrastructure chain is distinct from token research scope (Ethereum/Base).

The reference SDK integrates x402. This workflow does not authorize payments, payment fallback, wallet registration, relay submission or publication. Choose an identity/delegation boundary without an automatic payment side effect; any future paid/on-chain operation needs its own explicit authorization. Use fake provider transport or local test vectors for this build. Backend keys remain server-side and are not frontend config.

## Definition of done and review evidence

- Backend and web accept one target/result contract and one declared authentication/authorization boundary. Provide source, dependency lock/version and setup/handoff docs without secrets.
- Positive tests: scoped delegated agent plus actual policy eligibility dispatches exactly once; fresh allowed human consent resumes the exact blocked case once; correct request retries return the same result.
- Negative tests: wrong token/chain/snapshot/policy/action/audience; expired/replayed/revoked result; disabled reviewer/delegation; unregistered signer; unavailable or timeout provider; changed evidence between approval and dispatch; concurrent retries; restart between consumption/enqueue. All preserve bounded and nonduplicated work.
- UI shows candidate identity, evidence/gaps, scope and decision before consent, plus pending/deny/revise/expire/cancel/retry states. Authentication alone does not silently approve.
- Cross-action tests prove investigation authorization cannot approve/publish a report and publication receipts cannot start investigations. Auto agents cannot manufacture human receipts.
- A live acceptance run is separately documented only after appropriate configuration/authorization. Mock tests are labeled; no live claims from this charter.

## Handoff checklist

Our backend owner supplies state/read API, immutable revision/policy bindings, idempotency, queue/budget enforcement and an injectable verifier seam. Discovery supplies source-grounded concern assessment; investigation supplies bounded tools; web consumes backend state. The teammate supplies the real identity/delegation/human-verification adapter and its threat-model/test evidence. Root coordinates contract acceptance and PR integration. Do not replace the current publication module or start its publisher as a shortcut.
