# Workstreams and integration boundary

| Owner | Scope | Current integration state |
|---|---|---|
| Backend integration chat | Core API, orchestration, data/contract lifecycle, local draft artifacts | Prototype in this repository; incomplete |
| Discovery chat `01a1adf5-c90c-7ec0-9a93-8adb65d9aca6` | Sources, snapshots, concern verifiers and admission | Portable export imported as `modules/discovery`; not wired to API; all live verifiers disabled |
| Investigation chat `01a1adf5-caef-7e50-9fac-5e344c5a169a` | Five-pillar producer, evidence, claims and TL;DR | Portable export imported as `modules/investigation`; not wired to workers; partial producer only |
| Frontend chat `01a1adf5-cdb8-78e0-b887-625f6ca4e941` | Reader/build export and contributor handoff/interface proposal | Reader vendored; no publication implementation |
| Another human teammate | Post-report publication and World ID/AgentKit human sign-off | Reserved; not implemented |

See the detailed [human teammate handoff](post-report-handoff.md).

## Isolated seam for the human teammate

Use a separate branch and introduce a self-contained publication/sign-off module, with no assumed implementation in the existing reader. Backend owns immutable report version/digest, draft artifacts, and local review state. The teammate owns authentication and authorization for human sign-off, verification of a signed receipt bound to the exact report ID/version/digest, publication policy, and public lifecycle/version revocation. No current local review record proves identity or grants publication. Do not wire any World ID provider, wallet or publication endpoint without a reviewed interface and its own implementation and tests.

Proposed next steps: (1) inspect `GET /reports/{report_id}/{version}`, review and render endpoints plus `schemas/CONTRACT.md`; (2) propose a versioned receipt and publication interface specifying identity, nonce/replay prevention, digest binding, decisions, revocation and idempotency; (3) agree ownership and threat model with backend; (4) implement an isolated adapter with mock provider/contract tests; (5) integrate only after end-to-end validation and explicit publishing authorization. This is a proposed seam, not an accepted shared schema.

Topic branches and reviewed pull requests prevent overlapping edits. The orchestrator coordinates portable workstream handoffs. Schema changes require acceptance across discovery, investigation, frontend and backend.

## Active M0–M6 validation milestone

[Milestone protocol](honeypot-validation-milestones.md) and [backend readiness](honeypot-readiness.md) govern this work. Discovery owns M1 scouting and gate evidence; the user owns M2 selection or a scoped exception; investigation owns M3 neutral mechanism evidence; backend and frontend jointly own M4 integration and full PDF; root and user own M5 assessment/review; the **human teammate** owns M6 publication and World ID/AgentKit. Two narrow discovery verifiers exist in a separate unmerged worktree; the committed backend worker remains unwired. Do not convert a source-code presence claim into operational readiness.
