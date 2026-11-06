# Proposed shared scouting and qualification interfaces

Status: owner proposals under reconciliation. This document is not a deployed API or an adopted replacement for frozen candidate v0.1/report v0.2. Backend owns the final additive schema and conformance tests; discovery and web must explicitly accept it before runtime adoption.

## Discovery to backend

Discovery's screening result binds a canonical candidate identity to a content-addressed snapshot, generated time and explicit policy version/limits. Concern groups have individual triggered/not-triggered/unknown/held outcomes, measurements, verifier scope and evidence references with hashes, observed/captured times, block identity when applicable and limitations. Each independent concern contributes at most one vote. Coverage/freshness and unknowns are explicit. The proposed `auto_eligible`, `human_review_required` or `monitor` disposition is an assessment, not authority to enqueue a job.

Backend reopens the bound artifacts, recomputes supported concern outcomes and rechecks freshness/identity/policy at dispatch. It rejects a forged eligibility label, stale/tampered evidence and synthetic/historical input from the live automatic lane. Registered current verifiers are G07 and partial G09; real automatic qualification remains unattainable under four groups until additional verifiers are actually implemented and checked.

Reddit search results enter a separate lead boundary before canonical candidate resolution. A lead includes post identity/URL, query/subreddit, creation/capture time, claimed mechanism and extracted identifiers. Unresolved chain or contract remains explicit. Provider status and cursor/budget usage survive failed or unavailable search. Reuse investigation's transport rather than building another collector.

## Backend to Cases UI

Web proposes `GET /scouting/cases` with an additive `scouting-case-list/1` envelope: generated timestamp, staleness window and bounded cases list. Each record includes candidate identity, source mode/reference context, backend-owned lane/ordering, human-action requirement, summary/uncertainties, observation/capture times and concern/evidence reasons. A successful empty list differs from unavailable or failed source/transport.

Proposed lanes: `human_review_required`, `auto_qualified`, `research_running`, `monitoring`, `unavailable`. Backend owns deterministic attention order with stable candidate-ID ties. Historical references and demo market/case records are separated from live scouting. Return actual research run/report references only when they exist. The UI does not infer completion, probability, sign-off or publication.

Continuation advertises availability, reason and expected revision. It remains unavailable until a configured authenticated verifier and server-enforced action contract exist. The browser cannot follow an arbitrary supplied action URL or claim verification itself. Exact action route/response codes are frozen with the backend owner before enabling mutation.

The scouting transport uses an explicitly configured HTTPS origin or loopback HTTP for local development, exact-origin binding, no foreign redirects or credential-bearing URLs. Public read exposure is not implied; API/operator routes stay private until a reviewed access boundary exists. The report SHA-256 package API and the separately merged `/web/v1` publication adapter remain distinct.

## Contract acceptance ledger

| Boundary | Owner proposal | Acceptance |
|---|---|---|
| Screening result | Discovery: content-bound identity/policy, group outcomes, evidence/freshness, assessment and urgency | Await backend schema mapping and discovery acceptance |
| Cases read model | Web: `scouting-case-list/1`, lane/priority, freshness, reasons, disabled verified continuation | Await backend exact DTO and web acceptance |
| Research authorization | Root build charter: separate scoped candidate action/principal result | Await backend verifier seam and teammate implementation acceptance |
| Social provider | Investigation transport; discovery consumes lead results | Await callable/result contract and consumer acceptance |

Implementation PRs must include positive and negative producer/consumer fixtures, version identifiers, source byte/digest rules and failure semantics. Record acceptance and exact commits here or link the adopted repository contract; do not silently replace field names across workstreams.
