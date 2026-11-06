# One-case TL;DR presentation profile — proposal v1

Frozen report v0.2 is unchanged. The report producer should include one version-bound, SHA-256-bound local artifact with kind `pillar_tldr` and media type `application/json`. The report artifact's existing path/hash/availability/report_id/report_version rules apply. Suggested artifact path: `pillar-tldr.json`. A missing or unavailable sidecar renders an explicit no-TL;DR state, never fabricated findings. The sidecar is external to report JSON to avoid changing frozen schema.

Sidecar shape:
```
{"profile":"scooby.pillar-tldr/1", "report_id":"...", "report_version":"...", "pillars":{
 "microstructure":[{"role":"finding", "text":"...", "claim_ids":["..."], "evidence_ids":["..."]}],
 "onchain":[], "fundamentals":[], "statistical_risk":[], "technical_health":[]}}
```
Allowed roles: finding, support, interpretation, caveat. Each bullet is concise plain text, has at least one claim or evidence reference, and references IDs in the SAME report. Use 3–5 per covered pillar if evidence supports them; for unavailable or sparse evidence fewer bullets and explicit unknown are appropriate. Empty arrays mean no supported summary, not zero risk. A claim may point to supporting or counterevidence; qualify interpretations and uncertainty. Sidecar report ID/version must match report, and report artifact hash must bind the sidecar. No unreferenced external URL/HTML; text remains untrusted. Bullet source links should open in-page claim/evidence details; IDs must resolve without executing source content.

Reader slots: each pillar starts with bullet TL;DR above cards and charts, followed by coverage status, observations, specific limitations and full details. Show finding/support/caveat role labels and clickable claim/evidence links. The historical SHIB demonstration may derive bullets from its existing source-backed claims only and must remain marked historical; it is not the new case.

Please write a report and sidecar conforming to this shape, or specify any necessary modification before integration. If v0.2 payload cannot express a required finding, propose a new shared contract version rather than adding keys silently. One-case research must await qualified selection and use only observed evidence.

## Generic one-case field expectations

For a non-SHIB historical profile, the reader uses each producer `pillar.summary`, then the first three supplied measurements in producer order as key cards and the first supplied series as the main plot; all other values remain in the inventory. Supply descriptive, stable measurement/series IDs and explicit units, method, quality and evidence IDs. Do not assume VaR, RSI or any legacy ID is available. Order the producer's most important measurements and series first. Unknown or empty values must be null/empty with an explanation, never synthetic zeros. Four TL;DR roles—finding, support, qualified interpretation and caveat—are the preferred default where evidence supports them; use fewer rather than invent claims or counterevidence. This is a presentation convention over v0.2, not an alteration to the frozen report schema.

## Selected diagnostic case context

The orchestrator records BLISS as an explicitly selected one-off diagnostic exception, not gate-qualified; selection does not approve the report. Please copy its exact `selection.json` as a version-bound `selection_context` JSON artifact in the v0.2 report (or an equivalent hash-bound sidecar retaining `candidate_id`, `admission_qualified: false`, and `gate_exception.kind: one_off_diagnostic_reference`). The reader validates candidate ID and artifact hash before showing “Diagnostic case — manual exception, not gate-qualified.” Review remains pending/unverified separately. Do not infer this status from ticker or address, or use selection as report sign-off.
