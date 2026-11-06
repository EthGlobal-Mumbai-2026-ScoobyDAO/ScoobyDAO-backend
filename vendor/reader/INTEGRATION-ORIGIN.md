# IRC reader integration snapshot

The five files listed in MANIFEST.json were copied from the frontend workstream IRC reader after its audited-v3 implementation. The frozen report schema is unchanged. The backend additionally falls back to the report assessment label and unknowns when a conclusion omits them. This snapshot is used for local bundle validation and draft generation; reader provenance and accepted sidecar semantics are documented in PROFILE.md and the backend reference integration notes. It does not implement publication or authenticated approval.

This branch additionally supports `scooby.reasoning/2`, checking proposed-action references and input-to-evidence links and rendering rationale, counterevidence and reversal conditions; v1 remains supported. These checks establish traceability, not entailment or approval. Real /2 generation through Chat Completions is not implemented.

Captured-producer acceptance follow-up: `app.js` was locally updated from SHA-256 `1e8a299ffbd615244cfb1a7282a64bf44fe1d33ca83118a131dba622f4bc8cce` to `cda8c38b9c4606e068e3b4881d8564d89a9403904a828ff7d41da13513b94ea6` to expose partial coverage, distinguish fallback source summaries from IRC, label claim/evidence citations, and render the supplied assessment summary when reasoning is absent. No schema or report bytes changed. The vendor manifest tracks the revised file.
