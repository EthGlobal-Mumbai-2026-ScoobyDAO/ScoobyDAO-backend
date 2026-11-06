# World ID: two admin approval integrations

Authority: Aditya's clarification, 6 November 2026 IST. Both World ID checkpoints belong to the **admin application**, not consumer/client journeys. This is the human teammate's build charter and integration handoff, not a claim that live verification is complete. See [PRODUCT-FLOW.md](PRODUCT-FLOW.md).

## Scope and ownership

| Checkpoint | Admin action | Protected result |
|---|---|---|
| 1. Before investigation, when human approval is required | Review a scout Case, choose **Go for investigation**, then confirm through World ID | Start one bounded investigation for that exact Case/evidence/policy revision |
| 2. After report generation | Review the generated report and evidence, choose approve, reject or request revision, then confirm through World ID | Record an authenticated sign-off decision for that exact immutable report version and digest |

Policy-qualified automatic investigations bypass checkpoint 1 only. Their generated reports still enter checkpoint 2. A candidate authorization, agent decision or successful report generation cannot count as report sign-off. Approval does not automatically publish anything or broadcast a transaction; publication/release remains a separate explicitly authorized action under its own policy.

Consumers/clients read reports permitted by the release policy and see safe provenance/review status. They do not authorize investigations, operate either World flow, review private drafts or receive admin action controls, user codes, credentials or proof material. Pending reports and review queues belong to admins. Existing local operator prototypes are not a production admin access boundary.

The human teammate owns the real World identity/AgentKit adapter and integration PR. Backend owns authorization, target/receipt persistence, budgets and durable transitions. Web owns both admin journeys and consumer separation. Discovery supplies screening evidence; investigation supplies immutable research output; renderer supplies readable assets without changing report identity. Root reconciles contracts and acceptance.

Deliver both integrations with pinned dependencies/configuration, versioned schemas, tests, setup and a cold-pickup handoff. Reuse reviewed issuer/JWKS primitives where appropriate. Keep case and report target/receipt namespaces distinct; preserve the existing publication implementation rather than introducing a competing one.

## Identity, admin permission and consent

World authentication identifies a person; it does not grant Scooby admin permission, establish token risk or authorize a displayed action. Verify the admin session/permission, reviewer allowlist and action scope on the server as well as the World proof. A World-verified consumer cannot become an admin by completing a flow. AgentKit/delegation cannot impersonate either human decision or fabricate a human receipt.

Display the exact target, gaps, intended decision and consequences before confirmation. Bind consent in server-side records. A frontend Boolean, operator label, wallet registration or identity token alone is insufficient. Raw tokens, private keys, device codes and personal reviewer identifiers stay out of public DTOs, logs and report assets. Server secrets must not become public frontend variables.

## Checkpoint 1: scout Case to investigation

Show source-grounded reasons, deterministic checks, unknowns, candidate identity and allowed research scope. The admin initiates **Go for investigation** and completes case-scoped World confirmation. An unconfigured verifier stays visibly unavailable and starts no job.

The target binds Case ID, canonical chain/address, immutable evidence snapshot/revision, exact policy digest/version, intended investigation action, diagnostic-exception status, allowed work/budget reference, existing run for a supported resume, audience/resource, nonce and issue/expiry times. The verified result binds the permitted admin/reviewer, issuer, decision, verification time and scoped receipt reference.

On approval, reopen evidence, recheck current policy/permissions/budget, then atomically consume authorization, persist audit and enqueue at most one durable investigation. Identical valid retries return the same run. Candidate/evidence/policy/scope changes invalidate the old target. Denial, cancellation, expiry, revocation and failure start no research. Diagnostic approval cannot upgrade gate qualification.

Automatic and approved-human routes use the same producer/worker and Case -> run -> report lineage. An automatic policy decision is a backend authorization record, never a human receipt. The existing four-distinct-verified-group admission policy is unchanged.

## Checkpoint 2: generated report to admin sign-off

Every successfully installed generated report, including partial reports and automatic-lane output, enters an admin pending-review queue. Generation and draft HTML/PDF rendering need no prior report sign-off. Imported references retain their provenance and absent Case lineage; they do not manufacture a live scout or approval.

The report review target binds:

- Report ID, immutable version and exact report SHA-256; candidate and originating Case/run when present. Missing reference lineage stays explicit.
- Evidence/sidecar manifest digest and, when covered by the review, rendered artifact manifest/hashes. Changed report bytes, covered evidence or covered artifacts require a new target and fresh sign-off.
- Intended decision (`approve`, `reject`, `revise`), reason, audience/resource, nonce, issue/expiry times and allowed reviewer scope.

Show the recommendation, pillar TL;DRs, limitations, evidence and exact version. Fresh World confirmation creates a server-validated, single-use receipt for that decision/target. Rejection records a reason without release. Revision preserves the old report/decision; the replacement receives a new immutable version and pending-review target. An older approval never approves its replacement. Expired, denied, cancelled, failed or revoked attempts do not approve.

Persist report review separately from generation/rendering and publication. Emit auditable review events and expose only a safe review status to permitted consumers; agree exact serialized names in a versioned DTO. World authentication is not itself a human signature over report bytes: application consent/receipt binding must be explicit. Local unauthenticated `/reviews` receipts cannot satisfy this checkpoint.

Reuse the existing `publication/` target/World reviewer receipt where suitable, followed by its separate explicit publish request. Its target may bind chain/claim parameters: reconcile those with off-chain report sign-off so a chain transaction, publisher key or publication is not a prerequisite for admin review. If a report receipt also authorizes a later publication request, document its exact scope and require that separate request. A case receipt can never substitute for it.

## Backend/web contract handoff

These are existing repository seams to inspect, not a claim that production admin access or live verification is implemented:

| Surface | Existing seam | Required integration |
|---|---|---|
| Case confirmation | `POST /scouting/cases/{case_id}/challenge`, challenge World-attempt, attempt poll/cancel, case/run read model | Admin permission, bound target, v2 states and idempotent dispatch |
| Report sign-off | `/publication/v1/targets`, target attempts, attempt poll/cancel/revoke and `/web/v1` adapter | Generated report review target, admin/reviewer access, review/publication distinction |
| Local report review | `/reports/{id}/{version}/review` prototype | No unauthenticated alternate sign-off or release bypass |
| Browser | Existing Cases, Reports and approval UI | Both mutations behind the admin boundary; consumer report pages have no investigation or approval controls |

Backend/web must agree exact routes, session/principal handling, target/result profiles, safe read DTOs and error semantics. An `/admin` path is an organizational choice; URL naming, hidden buttons, CORS and loopback hosting do not supply server authorization. Protect private drafts, targets and relevant poll/status data as well as mutation routes.

Cover pending, approved, denied, expired, cancelled, failed and superseded with explicit mapping to each existing service's serialized states, poll/backoff and deliberate retry. Preserve frozen candidate/report schemas through additive versioned runtime contracts. Neither checkpoint authorizes payments, wallet registration, relay submission, account enrollment, publication or transactions.

## Acceptance and review evidence

1. Allowed admin confirms an unchanged human-required Case: exactly one investigation and linked generated report. Automatic admission needs no checkpoint-1 receipt, but generated output still waits for checkpoint 2.
2. Allowed report reviewer confirms the exact generated version: one authenticated decision, no repeated research and no automatic publication. Identical retries do not duplicate effects.
3. Reject wrong candidate/report/version/digest, evidence/policy/action/audience/nonce, expired/replayed/revoked proof, disabled reviewers/delegation and changed permission. Concurrent requests and restart preserve consistency.
4. Cross-action tests: case approval cannot sign off/publish a report; report approval cannot start investigation; agent/policy authority cannot impersonate a human; revised output cannot inherit old-target approval.
5. Consumer/no-session/World-verified-but-non-admin requests cannot operate either checkpoint or access private drafts/codes/receipts. Hidden controls alone do not pass.
6. Admin UI covers full review context, decision/reason, unavailable verifier, pending, reject/revise, expiry, cancellation, failure, retry and superseded target. Consumer UI shows only permitted reports and safe provenance/review state.
7. Label synthetic provider/admission proof. Live World acceptance requires a separately recorded configured run; this charter performs no live verification, paid calls, publication or deployment.

## Current state and next handoff

Case orchestration is in backend PR #12, bounded producer in #11, web integration in web PR #6. Synthetic paths and captured historical evidence do not prove production admin authorization or live World. The merged publication prototype is not completion of both admin checkpoints. Reconcile each exact source head with this charter and record remaining admin authentication, report review/release, live verification and dependency gaps in the teammate PR.

The teammate supplies real verifier/delegation integration and security review; backend supplies durable targets, receipts and authorization; web supplies the two admin journeys and consumer separation. Pin AgentKit SDK/network/deployment and delegated permissions before use. Model-enabled research remains separately bounded and cannot approve either human checkpoint.

Existing committed work and exact inspected PR heads: [World ID PR inventory and teammate continuation](WORLD-ID-PR-INVENTORY.md). Start there to reuse the case bridge and publication primitives without duplicating them.

## Backend implementation in this PR

This PR now also carries the backend runtime for both checkpoints: [admin-world-checkpoints.md](../admin-world-checkpoints.md) maps each requirement above to code and tests, and gives the API, states, configuration, setup, judge demo, security limits and merge steps. The evidence is synthetic (fake World issuer). Live World acceptance, the web admin journeys and the merge with `main` and backend #12 remain open.
