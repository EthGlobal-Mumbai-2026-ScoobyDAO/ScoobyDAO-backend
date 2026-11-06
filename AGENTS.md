# Repository conventions

- Work on a focused topic branch; `main` is the coordinated integration branch. Do not overwrite another contributor's checkout.
- Candidate v0.1 and report v0.2 under `schemas/` are frozen. The reader's report schema must match byte-for-byte. Propose versioned changes in `contract-amendments.md`, obtain workstream agreement, and add producer/consumer conformance tests before adopting them.
- Preserve unknown, held, unavailable and failed states; do not fabricate gate qualification, live observations, model findings, human approval or publication.
- Secrets, local databases, generated output, caches and personal machine paths do not belong in commits. Use environment variables for secrets. Run tests and inspect diffs before commit.
- Keep model/tool execution, deterministic verification, human review and publication separate. Draft rendering is allowed before sign-off; local actor strings are not authentication. Publication and World ID/AgentKit sign-off are reserved for the human teammate described in `docs/workstreams.md`.
- Vendor updates require provenance, a scoped diff and contract tests; do not patch another workstream's files in its own checkout.
