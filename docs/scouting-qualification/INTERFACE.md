# Proposed shared scouting and qualification interfaces

Status: the read-only local Cases prototype is accepted at the tested schema/commit below; authorization and final integration remain under reconciliation. This document is not a deployed API or an adopted replacement for frozen candidate v0.1/report v0.2. Backend owns the final additive schema and conformance tests; discovery and web must explicitly accept it before runtime adoption.

## Discovery to backend

Discovery's screening result binds a canonical candidate identity to a content-addressed snapshot, generated time and explicit policy version/limits. Concern groups have individual triggered/not-triggered/unknown/held outcomes, measurements, verifier scope and evidence references with hashes, observed/captured times, block identity when applicable and limitations. Each independent concern contributes at most one vote. Coverage/freshness and unknowns are explicit. The proposed `auto_eligible`, `human_review_required` or `monitor` disposition is an assessment, not authority to enqueue a job.

Backend reopens the bound artifacts, recomputes supported concern outcomes and rechecks freshness/identity/policy at dispatch. It rejects a forged eligibility label, stale/tampered evidence and synthetic/historical input from the live automatic lane. Registered current verifiers are G07 and partial G09; real automatic qualification remains unattainable under four groups until additional verifiers are actually implemented and checked.

Reddit search results enter a separate lead boundary before canonical candidate resolution. A lead includes post identity/URL, query/subreddit, creation/capture time, claimed mechanism and extracted identifiers. Unresolved chain or contract remains explicit. Provider status and cursor/budget usage survive failed or unavailable search. Reuse investigation's selected SearchApi transport rather than building another collector. SearchApi provider results use opaque page tokens; enforce the requested observation window locally because the measured smoke returned older posts despite its time filter. Credentials stay server-side; explicit provider call budgets and source/deletion lifecycle remain required. The shared normalized lead profile remains scooby.reddit-leads/1 with provider provenance. The user now permits a provisional365-day social context window; older in-window posts remain useful dated leads, while current onchain verification and normal gate freshness stay separate.

## Backend to Cases UI

The locally tested producer provides `GET /scouting/cases` with an additive `scouting-case-list/1` envelope: generated timestamp, staleness window and bounded cases list. Each record includes candidate identity, source mode/reference context, backend-owned lane/ordering, human-action requirement, summary/uncertainties, observation/capture times and concern/evidence reasons. A successful empty list differs from unavailable or failed source/transport.

Proposed lanes: `human_review_required`, `auto_qualified`, `research_running`, `monitoring`, `unavailable`. Backend owns deterministic attention order with stable candidate-ID ties. Historical references and demo market/case records are separated from live scouting. Return actual research run/report references only when they exist. The UI does not infer completion, probability, sign-off or publication.

Continuation advertises availability, reason and expected revision. It remains unavailable until a configured authenticated verifier and server-enforced action contract exist. The browser cannot follow an arbitrary supplied action URL or claim verification itself. Exact action route/response codes are frozen with the backend owner before enabling mutation.

The scouting transport uses an explicitly configured HTTPS origin or loopback HTTP for local development, exact-origin binding, no foreign redirects or credential-bearing URLs. Public read exposure is not implied; API/operator routes stay private until a reviewed access boundary exists. The report SHA-256 package API and the separately merged `/web/v1` publication adapter remain distinct.

## Contract acceptance ledger

| Boundary | Owner proposal | Acceptance |
|---|---|---|
| Screening result | Discovery: content-bound identity/policy, group outcomes, evidence/freshness, assessment and urgency | Await backend schema mapping and discovery acceptance |
| Cases read model | `scouting-case-list/1`, lane/priority, freshness, reasons, disabled verified continuation | Accepted for local read-only prototype at the exact tested snapshot below; consumer PR #6 commit73f4c02b5f7eb268e238ea861af05b7198d5c493 recorded; dependency merge remains |
| Research authorization | Root build charter: separate scoped candidate action/principal result | Await backend verifier seam and teammate implementation acceptance |
| Social provider | Investigation transport; discovery consumes lead results | Await callable/result contract and consumer acceptance |

Implementation PRs must include positive and negative producer/consumer fixtures, version identifiers, source byte/digest rules and failure semantics. Record acceptance and exact commits here or link the adopted repository contract; do not silently replace field names across workstreams.

## Accepted local read snapshot

Backend PR #12, tested source commit `640e91856f9ea779024bbf3d33f55a190e98de2d`. Canonical additive runtime schema path: `schemas/runtime/scouting-case-list-v1.schema.json`; exact-byte SHA-256 `ef227454cbcf429b15a6b2a268c9b057d83e1e90288cf02a2dea2eae37bfb336`. Frozen candidate/report contracts are unchanged. The orchestrator verified the tested schema bytes and their identity with later local source; that does not independently validate every later runtime revision.

Actual browser proof: web `127.0.0.1:3109` fetched API `127.0.0.1:58448` with the exact matching CORS origin at1440/375. Four existing discovery-pilot snapshots rendered as monitoring, with source dates/ages and all concern reasons accessible; no qualified/urgent case was invented, no overflow/page errors or writes. Mock tests separately cover urgency and disabled continuation. This is private local prototype acceptance, not authenticated/public deployment or full research completion.

The runtime DTO currently permits only live Ethereum/Base identity and `reference:null`; historical catalog is a future separate read model, not fabricated case/report IDs. Symbol can be null. Records include `case_id`, candidate identity, `snapshot_digest`, `policy_digest`, `expires_at`, `verified_triggered_count`, `reasons` (triggered/not_triggered/unknown/held), and optional actual research status, budget, pillars and reason. Counts are backend-reported, not probabilities. Source age is distinct from list TTL. Incomplete research is preserved and cannot remain falsely running.

Backend orders all cases by human-action attention and distinct verified concern count with stable candidate ties before returning up to100. The bounded index limit is5,000; above that the prototype returns503 rather than silently omitting older urgent records. Human continuation remains unavailable until the teammate verifier and action contract exist. The current challenge wire action is `diagnostic_research`; build-charter scope labels describe intended permission and are not additional deployed endpoints.

Social integration separately accepted14 dated context observations across two successful bounded SearchApi queries, with unresolved token identity and zero concern votes. A RAY-specific query returned provider-declared failure of unknown exact cause; no sentiment inference follows. All3 additional request-budget calls are used, with no retries. These social records are not the four pilot cases and do not prove fresh risk. Web consumer PR #6 is pinned at73f4c02b5f7eb268e238ea861af05b7198d5c493 (220 local tests plus build/lint/typecheck). Final dependency merge, full worker invocation and scoped human verification remain separate checkpoints.

### Prototype consumer compatibility posture

The canonical producer v1 schema constrains continuation to unavailable/null and report references to their current supported state. The web parser at the pinned read-only snapshot deliberately accepts a superset, including future availability/action URLs and report identifiers. Its controls remain disabled regardless of supplied availability, it never follows an action URL or sends case/challenge writes, and report IDs alone prove no verified report availability. Tests exercised this defense-in-depth behavior. Acceptance is positive producer/read compatibility, not a claim that the consumer rejects every out-of-schema payload. This posture is recorded for the initial working prototype; enabling actions or broadening producer capabilities still requires a versioned contract and verifier agreement.
