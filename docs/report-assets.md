# Report storage and transfer

Application source and report data have separate lifecycles. Cloning this repo or building its image does not carry local authored reports onto the target.

| Location | Contents |
|---|---|
| Git / container image | FastAPI/worker code, frozen schemas, reader/export adapters, operational files and synthetic/historical test fixtures |
| `SCOOBY_DATA/bundles/<report-sha256>/` | Imported immutable report JSON, evidence, sidecars and bound Markdown |
| `SCOOBY_DATA/artifacts/<job-id>/` | Generated HTML, copied verified assets, Markdown, optional PDF and digest-bound manifest |
| `SCOOBY_DATA/state.sqlite3` and `huey.sqlite3` | Report/job/selection/review records and queue; SQLite WAL companions may also exist |
| Compose volume `scooby-data:/data` | Persistent storage shared by API and worker; Docker usually prefixes the actual volume name with the Compose project name |

The native frontend fetches these through report/package endpoints. It does not need a duplicate copy in web `public/`. PDF source links refer to the version-matched companion bundle; evidence bytes are not embedded. This is local-volume storage, not S3 or a shared multi-host artifact service.

## Seed a fresh target

Use the complete source packet: `candidate.json` plus a `bundle/` directory containing exact `report.json` bytes and every referenced evidence/sidecar/Markdown file. Check the packet's file hashes before import. Preserve frozen bytes; do not reformat JSON or change an existing report version. Keep the source packet outside Git and transfer it through the team's approved private file channel. The orchestrator handoff records the current RAY packet's local location and archive checksum.

1. Start API and worker privately with the same persistent `SCOOBY_DATA`. Leave model budget zero. Create the staging parent with `docker compose exec -T api mkdir -p /data/imports`. Copy the packet into the API container, for example `docker compose cp /private/path/to/seed api:/data/imports/ray-seed`; verify the actual resulting directory before proceeding. The absolute import path must exist **inside** that container. Import snapshots its files; the worker then reads the shared installed bundle.
2. `POST /candidates` with `{"payload": <candidate.json object>}`. For RAY, preserve its diagnostic/reference provenance; do not claim a verified gate.
3. `POST /candidates/{candidate_id}/selection` with a fresh `Idempotency-Key` and `{"kind":"diagnostic_exception","actor":"<operator label>","reason":"Transfer existing user-authorized RAY reference for integration; not gate-qualified"}`. Record the returned selection `id`. Actor labels are unauthenticated and do not count as human sign-off.
4. `POST /investigations` with another idempotency key and `{"candidate_id":"<candidate_id>","selection_id":"<selection id>"}`. Record returned run `id`. This creates lifecycle records; the current worker does not conduct new deep research.
5. `POST /reports/import` with `{"run_id":"<run id>","bundle_path":"/data/imports/ray-seed/bundle"}`. It validates and snapshots bound files into `bundles/<sha256>`. Check the returned report digest against the packet.
6. `POST /reports/{report_id}/{version}/render` with another idempotency key. Poll `GET /jobs/{job_id}` until complete, then check `GET /reports/{report_id}/{version}/artifacts` and the immutable package descriptor/assets. Verify exact digests. A new target render has a new job/package identity; preserve the original report identity and bytes.
7. Set the web's build-time `NEXT_PUBLIC_REPORT_API_URL` to the reachable research origin and API `SCOOBY_WEB_ORIGIN` to the exact web origin. HTTP is accepted only for loopback web development; remote use requires reviewed HTTPS access. Check report cards, all five pillars, evidence downloads, PDF availability and worker status. Keep legacy approval API configuration separate.

No new source collection, model call, approval or publication is part of this transfer. PDF remains unavailable until a compatible browser is explicitly enabled and tested on the target; old draft PDFs are not silently replaced. RAY's old local PDF with temporary URI links should not be distributed; render with the merged portable adapter.

## Move an existing runtime

A stopped, consistent backup must include the **entire** data directory, not just a database or PDF. Report rows currently store absolute bundle paths. A Windows runtime copied to Linux `/data` will therefore require an explicit path migration; raw copying its SQLite files is not a portable seed process. Prefer validated source-bundle import for this first staging deployment. If preserving historical jobs/reviews is required, build and test a deliberate migration before cutover. See [backup/restore and rollback](../DEPLOYMENT.md). Never extract a backup over the active volume.
