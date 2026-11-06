# IRC reader integration snapshot

The five files listed in MANIFEST.json were copied from the frontend workstream IRC reader after its audited-v3 implementation. The frozen report schema is unchanged. The backend additionally falls back to the report assessment label and unknowns when a conclusion omits them. This snapshot is used for local bundle validation and draft generation; reader provenance and accepted sidecar semantics are documented in PROFILE.md and the backend reference integration notes. It does not implement publication or authenticated approval.

This branch additionally supports `scooby.reasoning/2`, checking proposed-action references and input-to-evidence links and rendering rationale, counterevidence and reversal conditions; v1 remains supported. These checks establish traceability, not entailment or approval. Real /2 generation through Chat Completions is not implemented.
