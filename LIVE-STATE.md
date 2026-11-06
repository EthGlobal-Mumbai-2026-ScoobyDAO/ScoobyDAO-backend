# Integration state — 6 November 2026

PR #22 consolidates the backend case, investigation, discovery, Terra, Graph, report and admin-checkpoint work on current main. Confirm the PR and merge state in GitHub; this document does not itself assert deployment. The integration intentionally returns the previously merged open-review mode to named-admin authorization. Startup cleanup revokes former automatic grants and quarantines attributable receipts; previously submitted or confirmed on-chain transactions require separate reconciliation.

The full local integration suite at head `6e3f198` passed 418 tests, with 7 skipped and 52 subtests. CI passed at that head. Tests use synthetic issuers and sources. Live World login, same-admin case confirmation, report sign-off and the web experience still require end-to-end verification in the intended environment.

The bounded scout and case worker are connected but scout collection defaults off. The two narrow enabled concern verifiers cannot by themselves establish four independent groups. Source and model budgets default to zero. The scout's durable quota is per discovery database, not a shared account-wide limit; its separate legacy refresh/LP paths are not included. See [bounded scout](modules/discovery/BOUNDED-SCOUT.md).

The seed importer is merged in PR #23 and is documented in [report seed restore](docs/report-seed-restore.md). It imports selected verified local files into a persistent store as pending references or diagnostics, without case admission or publication. The API and worker must share storage. The Render blueprint currently runs only the API; configure and verify a worker separately before depending on queued work. Set `SCOOBY_REPORT_RELEASE=approved` for the API and seed command.

The local diagnostic preview used during development is an operator-only process with historical partial reports; it is not evidence that the secured merged runtime, World issuer, deployed worker or public release has been tested. Source gaps, model validation and independent review remain report-specific. No production deployment or chain publication is implied by this document.
