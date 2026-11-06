# Handoff — initial integration checkpoint

## Current checkpoint

All completed source slices are merged: backend PRs #1–5 and #7, web PRs #1–2. See [LIVE-STATE.md](LIVE-STATE.md) for exact source commits, checks and workstream gaps. The separate teammate World ID PR #6 is deferred and untouched. Root owns cross-repo reconciliation; backend owns runtime/packages; discovery owns screening/fork tools; investigation owns producers/mechanism protocol; web owns native cards; standalone reader owns presentation/export; the human teammate owns post-report publication and authenticated sign-off.

Private Compose builds and API/worker-heartbeat smoke passed in CI. No actual deployment exists. Use [DEPLOYMENT.md](DEPLOYMENT.md), preserving loopback host binding, one API/worker and the persistent volume. PDF stays opt-in pending target-container rendering. Public exposure needs a reviewed access boundary. Docker was unavailable on the authoring workstation; local PDF regression used isolated headless Edge.

The RAY authored bundle and local runtime are **not included in the repository/image**. Use the complete source packet and [asset transfer/import procedure](docs/report-assets.md) to seed the target; a fresh volume is empty. Do not transplant Windows SQLite absolute paths into Linux without migration. The web fetches packages from the backend and needs no copied report assets in its public directory.

The native package preserves report and sidecar bytes and keeps mutable review separate. Synthetic reasoning/1 and /2 producer/standalone/native compatibility checks passed; no real /2 report or app-owned /2 model synthesis is wired. Existing RAY remains a diagnostic source-curated reference, pending review, with current sell trap unproven. The fresh gate-qualified honeypot milestone remains open. Discovery tools and offline investigation adapters are merged source, not an always-on research engine.

## Continue in order

1. Clone the repository and create a topic branch. Run `python -m pip install -r requirements.txt`, `python -m pytest -q tests`, and `python tests/smoke_worker.py` with Python 3.11. Run the API and worker separately as in README. Verify no process is left running after a smoke test.
2. Discovery's final portable export is imported at `modules/discovery` and is not wired to the API. Investigation's final portable export is imported at `modules/investigation`; neither package is wired to the API. Integrate the packages behind worker boundaries, preserve provenance, keep held/missing verifiers unknown, and enforce the four distinct verified concern groups plus separate human selection. Do not treat an exception as gate-qualified or duplicate the current BLISS diagnostic research.
3. Implement durable source snapshots, feed freshness, meaningful retry/fencing/cancellation, actual independently resumable five-pillar tasks, source/counterevidence validation and source-linked TL;DRs. Keep app-owned tool execution separate from Terra Chat Completions. Add call/token/rate budgets and failure tests before authorized live calls.
4. The reference PDF now includes expanded reader details and hash-bound Markdown; verify each case, improve pagination/accessibility and retain explicit missing/failure states. Maintain the pending draft path before review.
5. Coordinate the versioned review/publication interface in `docs/workstreams.md` and `docs/post-report-handoff.md`; a separate human teammate owns publication and World ID/AgentKit human sign-off. Frontend chat supplies reader export and interface proposal only. Do not invent an authenticated or published status before that work is integrated.
6. Add authentication and authorization, migrations, production security/observability and a durable approved export; test review revocation, digest mismatch and crash recovery. Re-run shared contract acceptance across the workstreams before changing schema versions.

## Evidence and limitations

Current verification is in [LIVE-STATE.md](LIVE-STATE.md). PDF/workflow regression passed with isolated headless Edge, including zero URI annotations, resolving internal destinations and companion-index text. The adapter does not embed evidence bytes. Detailed every-page reading-size, keyboard, screen-reader, target-viewer and target-container rendering review remains open. Old local PDF artifacts are immutable and should not be silently overwritten or promoted as the corrected portable output.

No new source/model call, authenticated review, production hosting or spend occurred during reconciliation. Original historical fixtures and optional legacy-checkout comparisons remain offline evidence only. RAY and the earlier BLISS exception do not establish the four-group gate. The legacy approval API and native research API have distinct routes and hash domains; do not point both frontend environment variables at this service.

Source-of-truth schema digests: candidate `9a45955834e66c9a86f8f0e8cd7eb915e03517ee6e601d1c24570bc687ed530b`; report `8a5f793dce8c75c18c3ee8ade4c26e76fe51ee489173ff59299ad85b5963bf55`. The reader's copy of the report schema must match. Record any future accepted version explicitly rather than changing these bytes.
