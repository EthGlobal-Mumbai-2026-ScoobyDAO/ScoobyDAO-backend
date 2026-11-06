# Scooby DAO — product flow correction

Authority: direct user clarification, 6 November 2026 IST. This supersedes earlier orchestrator framing that treated Cases as a read-only status board or treated a case-to-report link as the whole workflow. Existing prototype checks remain evidence of individual components, not acceptance of the complete product.

## User intent

The user's words: “the cases is a pane where the live scouts exists ranked in order of actionablity, the one that look most sus are directly go into the investigation workflow and the report is generated and is created in that tab then if there is a human in the loop, the human checks the case, clicks on go for investigation and the workflow continues via a world id comfirmation, this is needed.”

## Required product behavior

1. **Cases is the actionable live scouting queue.** Persist scout/candidate identity and source lineage. Rank by backend-owned investigation actionability. Each card explains why the token was scouted, source-grounded suspicion, deterministic check results, and the reason for its recommended next action. The existing fresh cork/paper/mascot visual design remains the design foundation.
2. **Automatic path:** the strongest candidates satisfying the explicit automatic-admission policy enter investigation directly, without a human click. Durable jobs run the investigation, produce the research bundle and generate report assets. The report appears in Reports and is linked from the originating Case. The Case remains inspectable through its workflow states.
3. **Human path:** a case requiring judgment presents **Go for investigation**. A human reviews the case and initiates that action. World ID confirmation is required before the backend continues the investigation. The verified authorization binds the actual case/candidate, evidence/policy revision, intended action, nonce and expiry; it is consumed once. Denied, expired, cancelled or failed confirmation does not start work. This pre-investigation gate is distinct from final report review/publication.
4. **Shared downstream path:** both paths use the same bounded investigation → report generation → Reports visibility → original-Case report access. Queued/running/partial/failed/completed states and supported retry/recovery are visible. An investigation job that merely marks all pillars unavailable is not this completed product path.
5. **Reports stays available in the same app.** Existing authored reference reports remain readable, while newly produced reports populate automatically. Reference/demo provenance is explicit. A case without a report shows its actual investigation action or progress rather than a dead link.

## Meaning of the correction

The live scouts, deterministic assessment, routing decision, actual research execution and generated report are one product journey. A standalone data feed, a permanently disabled continuation, isolated adapter tests or a report viewer alone does not meet that journey.

The top of the queue reflects investigation actionability across cases. Do not hardcode every human-required case above every automatic candidate or hide global priority behind unrelated lane sections. Lane/status badges explain the workflow; the backend supplies the declared priority and routing reasons. Do not introduce unapproved numeric scam probabilities or change the concern-group policy silently.

The correction does not authorize invented suspicious findings. A new-pool lead with no established red flags must say why it entered the scouting pool and what is unverified. Actual deterministic policy/coverage gaps must be implemented or shown as gaps, not concealed by generic copy or a fabricated qualified example. Older social discussion remains allowed within the agreed provisional 365-day window; current on-chain verification stays separate.

Final report sign-off and publication remain separate from the human authorization to start research. The existing World publication prototype does not automatically implement this candidate-action confirmation. The teammate build charter must include this required pre-investigation integration; a future-only checkbox is insufficient for product acceptance.

## Owner responsibilities

| Owner | Correction required |
|---|---|
| Discovery | Produce genuine scouting reasons, deterministic assessment, actionability and routing rationale with source identity/evidence; preserve unknowns and keep monitoring active under configured bounds |
| Backend | Connect both admission paths to real durable investigation jobs and report generation; expose Case→run→report lineage; make human continuation depend on verified World ID action authorization |
| Investigation | Supply the invoked bounded research/report producer, not only isolated source adapters; preserve evidence, pillar coverage, reasoning and report contracts |
| Web | Restore the established fresh design; put reasons and next actions on cards; implement required World ID launch/pending/result flow; restore Reports and connect generated reports back to Cases |
| Report renderer | Ensure automatically produced bundles render readable HTML/PDF and publish draft artifacts into the report library with correct report/case identity |
| Human World teammate | Implement/review the real case-scoped World ID confirmation adapter and consent binding in the charter; keep it separate from publication authority |
| Root | Correct all briefs/PR charter, reconcile interfaces and validate the whole journey; stop reporting component-level readiness as product completion |

## Acceptance checkpoint

Demonstrate two complete local journeys against the composed implementation:

- Policy-qualified scout → automatic investigation → generated report visible in Reports → opening it from the original Case.
- Human-required scout → human reviews reasons → Go for investigation → World ID confirmation → one investigation → generated report visible and reachable from the Case. Negative confirmation/expiry/replay never starts another run.

Use real source data where available and explicitly labeled synthetic/provider mocks for unavailable external identity or paid dependencies. A mocked World confirmation is an integration test, not live human verification. Record missing configuration/budgets honestly. Do not run more SearchApi calls, paid models, account registration, transactions, publisher or public deployment merely to claim completion; current source-call cap remains exhausted. Those operational boundaries do not excuse leaving the product wiring as disconnected placeholders.
