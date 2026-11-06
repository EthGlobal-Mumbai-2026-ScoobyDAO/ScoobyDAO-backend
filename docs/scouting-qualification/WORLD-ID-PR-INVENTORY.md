# World ID implementation inventory and teammate continuation

Checked against open PR heads on 6 November 2026 IST. This ledger describes committed source, not live verification. Heads can advance; reconcile again before merging. Product requirements are in [the two-admin-checkpoint charter](WORLD-AGENT-BUILD-CHARTER.md).

## Open PRs

| PR and inspected head | World-related work already committed | Remaining boundary |
|---|---|---|
| Backend [#12](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/12), `372a2dbb99ae6d75f8417409ee3e9a511b32c253` | `case_world.py` adds a separate case device-grant attempt using the existing World client, token validation, snapshot/policy/action binding, expiry/backoff/cancel/supersession and atomic single-run continuation. Store, API, runtime v2 schema and worker connect the run to the shared producer/report. Synthetic route and captured-evidence journey tests exercise both lanes. | Local operator prototype, not an admin permission system. The case path validates World identity without a reviewer allowlist/admin session check. Add admin/reviewer authorization and private read protection; review consent/proof binding. No checkpoint-2 report sign-off or live World acceptance. |
| Web [#6](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-web/pull/6), draft, `7c284cea15015737ff90e20ef46a9ea14db60274` | `CaseWorldAction.tsx` and `scouting.ts` implement Case -> challenge -> World attempt/poll/cancel, response binding checks, trusted verification-link checks, unavailable/denied/expired/failed states and retry. The board displays research progress and original-Case report links. | No implemented admin role/session boundary for these controls. Protect them as admin functions and separate consumer reading. No new generated-report review queue/checkpoint-2 integration. World success browser evidence is synthetic. |
| Backend [#11](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/11), `99486539b4aef7cab51e313cf146550c6cdae38c` | `case_research.py` accepts backend authorization/lineage references and creates bounded immutable reports, including hash/provenance-checked no-network replay. Tests exercise synthetic route-shaped inputs and importer/render output. | Deliberately does not authenticate/authorize callers, verify World or sign off reports. Backend must enforce admission first. An authorization reference is not independently verified identity. |
| Backend [#15](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/15), draft, `f1b46dd21beee0a74f0f3aad22da03b9446b27ad` | Renderer/HTML/PDF checks preserve report identity, evidence integrity and pending/partial presentation. | Rendering grants neither investigation permission nor report approval. No World verifier or admin gate added. |
| Backend [#9](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/9), `f29c8fe0461698ff40d79102075ecf611ae9171f` | Source-grounded clues, deterministic checks and routing reasons supply the human/automatic decision boundary. | Screening is not identity, admin permission or consent. Four real pilot cases remain monitoring with no qualifying verified groups. |
| Backend [#10](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/10), this PR | Two-admin-checkpoint charter, bindings, existing API seams, ownership, cross-action tests, consumer separation and this inventory. | Documentation/build contract, not runtime implementation or live security acceptance. |

## Already merged baseline to reuse

Backend [#6: World ID Integration](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/6), merge `96880e7a72fe598d964ab5208960151699a83ea7`, introduced `publication/`: World OIDC discovery/JWKS/device grant, token validation, reviewer allowlist, publication target/receipt binding, explicit publish request and optional fenced publisher/outbox. Operator mutations under `/publication/v1` require the configured operator bearer token; `/web/v1` is a separate adapter boundary to audit. Fake-issuer tests do not establish live sign-off or chain publication. The web approval screen already exists; it is not newly delivered by open web PR #6.

Backend [#16](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/pull/16), already merged, updated the environment template, helper and audit for existing World client/private-key-file settings. It adds no verifier, admin session, enrollment or live verification. Configuration presence does not prove authentication.

The generic report `/review` endpoint still records an unauthenticated local operator decision. It is not a World receipt and must not become a release bypass. Report-list local review state and the publication adapter's receipt state need explicit reconciliation for checkpoint 2.

## Teammate PR: concrete next work

1. Agree/build server-side admin session, reviewer permissions and private draft/attempt/status boundaries. Wire both admin flows and prove consumer/no-session/World-verified non-admin denial. Keep server secrets out of the browser.
2. Finish checkpoint 1 using the case bridge: real configuration, allowed-admin checks, action consent, expiry/revocation/replay, budgets, durable dispatch and restart. Keep case/report receipts separate.
3. Connect generation completion to the admin report queue. Bind exact report/version/digest and covered evidence/artifact manifest; implement approve/reject/revise and safe review state using existing primitives where suitable.
4. Separate off-chain review from optional chain publication: review works with publication disabled, and publication requires a separate explicit request under existing controls.
5. Pin AgentKit/delegation SDK, deployment/network and scopes. No open PR here establishes live AgentKit registration/delegation. Agent admission cannot substitute for human report sign-off.
6. Record exact heads, positive/negative/cross-action tests, mock/live boundaries, secret-free setup and blockers. Synthetic acceptance proves integration only; live World and production permission need their own evidence.

This inventory does not authorize spending, enrollment, deployment, publication or transactions. LLM research is separately bounded and cannot approve either human checkpoint.
