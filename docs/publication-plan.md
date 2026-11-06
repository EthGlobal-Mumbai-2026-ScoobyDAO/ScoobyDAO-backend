# Publication boundary and World ID Agent Pass: plan

Scope: the reserved workstream in [post-report-handoff.md](post-report-handoff.md). Protected action: `ReportRegistry.publish` on Sepolia, which opens a market accusing a token. It must only happen after a fresh, validated, single-use human approval for exactly those bytes, followed by a separate explicit publish request.

## Shape

1. **Target** (`scooby.publication-target/1`). Built from an imported report version: report ID/version, exact `report.json` SHA-256 (re-hashed from disk), a human-readable `scooby.claim-manifest/1`, chain/registry, resolver/adjudicator and timing. `target_digest = sha256(canonical(target))`, `claim_hash = sha256(canonical(manifest))`, using `store.dumps` canonical JSON. The contract's timing rules are checked up front (422).
2. **Attempt.** The backend starts an OIDC Device Authorization Grant (RFC 8628) at the World issuer with `private_key_jwt` (RFC 7523) and an essential `acr` claim. The `user_code` is shown on `/approve/[id]` next to the exact claim, because World does not display or sign action terms (`binding_message` is unsupported), so binding is ours: attempt ↔ target digest in our DB. The device code is held only in process memory; only `sha256(device_code)` is stored.
3. **Poll-on-read.** Polling respects `interval` and `slow_down`, under a row lock. On tokens, the ID token is validated against JWKS (RS256 only), iss/aud/exp/iat/auth_time/acr/amr, with `auth_time` inside the attempt window. Then the (iss, sub) allowlist is checked → receipt (decision = the attempt's intent) in the same transaction. Denied, expired, 5xx or timeouts never approve.
4. **Publish request** (explicit operator call). In one `BEGIN IMMEDIATE`, re-check bytes, latest receipt (approve, fresh, unconsumed, unrevoked, no newer reject/revise), reviewer still enabled and no in-flight outbox row. Then consume the receipt, pick a random nonce, set expiry to now + 15 min, have the attestor key sign the contract's `approvalDigest` and queue an outbox row.
5. **Fenced outbox** (`python -m publication.publisher`, a separate process, not Huey). It claims with a fence and lease, re-checks revocation right before broadcast, persists `tx_hash` before broadcast, waits for confirmations and parses `Published`. `reconcile` uses `usedNonce` and the receipt/logs, so a crash never double-publishes.
6. **Revoke.** Stops the outbox before confirmation; after confirmation it is recorded and shown (onchain cannot be undone).

## Surfaces

- `/publication/v1/*`: operator API (bearer token, Idempotency-Key + request hash → 409 on conflict).
- `/web/v1/*`: adapter shaped exactly like `ScoobyDAO-web/src/lib/types.ts` (Report, Approval, ClaimView-free). GET-only for the reviewer page plus `POST /reports/{id}/approve`. It never returns device codes or tokens.
- `python -m publication.cli`: enroll/list/disable/enable reviewers (device login → pairwise `sub`), publish-confirm, reconcile.

## Safety defaults

- Publishing is off unless `SCOOBY_PUBLISH_ENABLED=true`, `SCOOBY_CHAIN_ID` matches the RPC, and the publisher key equals `ReportRegistry.publisher()` (checked by an RPC read at startup).
- No World config → attempts are refused (503).
- A mock issuer is injectable only through a constructor argument used by tests.
- Frozen schemas are checked against HANDOFF digests in a test.
- No changes to `worker.py`; `app.py` only mounts routers and CORS.

## Tests

The fake World issuer (`httpx.MockTransport`) verifies our client assertions and scripts token outcomes. The prompt's §5 cases are each a named test. Optional `@pytest.mark.anvil` tests compile `ReportRegistry` + `Sig` in a temp Foundry project and prove `approval_digest`, recovery and the revert reasons.

## Not in scope

IDKit/REP badges, AgentKit/AgentBook, live Sepolia publishing, app registration and funding keys (human steps, see `publication-demo.md`).

**Security boundary:** World device-grant authentication does not display or sign a report or decision. The backend binds the authenticated identity to a target receipt; that association alone is not cryptographic proof of informed approval. Review the consent and operator-access model before use. Live World and chain behavior remain unverified; publishing is disabled by default.
