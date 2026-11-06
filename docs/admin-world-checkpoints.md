# Admin World ID checkpoints: implementation and handoff

This implements the backend side of [the two-checkpoint charter](scouting-qualification/WORLD-AGENT-BUILD-CHARTER.md) on the PR #10 branch (`docs/scouting-world-agent-charter`). It is tested with synthetic identities against the fake World issuer (`tests/fake_world.py`). **No live World login, deployment, chain transaction or publication was performed.** A live run must be recorded separately (see [WORLD_FEEDBACK.md](../WORLD_FEEDBACK.md)).

## What is delivered

| Charter requirement | Implementation | Evidence |
|---|---|---|
| World identifies a person; permission is server-side | Reviewer allowlist (`pub_reviewers`, enrolled by CLI World login) plus explicit scopes (`admin_scopes`): `case_investigation`, `report_review`, `publication` | `test_admin_session_needs_an_enrolled_reviewer_with_a_scope` |
| Admin session; consumers and World-verified non-admins cannot operate either checkpoint | World device login issues an opaque bearer session (stored as SHA-256, 4 h). Reviewer status and scopes are re-read on every request | `test_session_restart_cap_permission_changes_and_expiry`, `test_private_reads_need_credentials` |
| Checkpoint 1: case-scoped World confirmation before investigation | The API's World client (`publication.admin.AdminWorldClient`) provides `authorize_case_admin(identity, binding)`, the hook the case bridge (backend PR #12, `case_world.poll`) calls before it starts a run. A path guard puts PR #12's case-checkpoint routes behind an admin session with `case_investigation` | `test_case_authorizer_hook_for_the_case_bridge`, `test_case_checkpoint_routes_need_a_case_admin_session`, and a merged-tree run (below) |
| Checkpoint 2: World-confirmed sign-off of the exact generated report version | `publication/review.py`: review target, per-attempt binding, initiator-bound World confirmation, append-only receipt, approve/reject/revise, revoke, supersession | `test_report_signoff_*`, `test_unsuccessful_confirmations_record_no_decision`, `test_changed_bytes_supersede_*`, `test_revoke_*` |
| Neither receipt substitutes for the other; no automatic publication | Separate tables and scopes. A report approval is only a precondition for publication, which keeps its own chain-bound sign-off and explicit publish request | `test_checkpoints_cannot_stand_in_for_each_other`, `test_publication_needs_a_current_report_approval_and_its_own_signoff` |
| Consumers see only permitted reports and a safe review state | `GET /reports` and `/reports/{id}/{version}/artifacts` add `admin_review` (`scooby.report-review-status/1`); `SCOOBY_REPORT_RELEASE=approved` lists only approved versions | `test_consumers_see_only_released_reports_and_a_safe_status` |
| Private drafts, attempts, user codes and status are protected | Admin routes need a session; `GET /publication/v1/targets/{id}` and `/attempts/{id}` now need the operator token; web publication sign-off needs the `publication` scope and only its requester sees the user code | `test_private_reads_need_credentials`, `test_web_publication_signoff_is_bound_to_the_requesting_admin` |
| No secrets in DTOs, logs or the database | Device codes stay in memory; device-code, session-token and ID-token hashes only | `test_no_tokens_codes_or_subjects_leak` |
| Versioned contract | [`schemas/runtime/admin-checkpoints-v1.schema.json`](../schemas/runtime/admin-checkpoints-v1.schema.json); every DTO in the tests is validated against it. Frozen candidate v0.1 and report v0.2 are unchanged | all tests in `tests/test_admin_checkpoints.py` |

## Checkpoint 2: report sign-off

Every installed report version is in the admin queue: generated, partial, automatic-lane output and imported references. The queue reads the `reports` table, so a report enters it however it was installed. Generation and draft rendering need no prior sign-off.

**Target** (`scooby.report-review-target/1`, digest = SHA-256 of canonical JSON): report ID, version and SHA-256; candidate; lineage (run, selection kind, and case ID and action when the case bridge recorded them, otherwise explicit `null`); evidence manifest (SHA-256 over sorted `{id, path, sha256}`, and every evidence file is re-hashed on disk); and the newest completed render manifest for exactly those bytes, when one exists. Changed report bytes, evidence or rendered artifacts give a new target, so an earlier decision no longer applies.

**Attempt** binds `scooby.report-review-binding/1`: target digest, decision, reason, audience (`SCOOBY_ADMIN_AUDIENCE`), resource `report/{id}/{version}/{sha256}`, scope, a 32-byte nonce, issue and expiry times, and the initiating admin (SHA-256 of `iss|sub`). The admin must send the digest they were shown (`expected_target_digest`); a stale digest is refused before World is contacted. There is one pending attempt per target and one decision per target until it is revoked. `Idempotency-Key` makes retries return the same attempt without a second World grant.

**Confirmation:** a fresh device grant. The result counts only if the ID token validates (issuer, audience, signature, `acr`, `amr`, `auth_time` within this attempt, and no actor/delegation claim), the World identity equals the initiating admin, that admin is still an enabled reviewer with `report_review` and the initiating session is still active, the audience is unchanged, and the target on disk still has the same digest. Then an append-only receipt is written (`rev_receipts`; triggers block edits and deletes and allow revocation once). Denied, expired, cancelled, failed, not-permitted and superseded attempts record no decision.

**Revision** is a new immutable report version with its own target. An approval never transfers to it.

## Checkpoint 1: case to investigation

The case bridge is in backend PR #12 (inspected head `b40ad97`, "Fail closed without case administrator authorization"). After validating the World token and the case binding, `case_world.poll` starts a run only if `world.authorize_case_admin(identity, binding)` returns `True`, and it reports the case as unavailable when the hook is absent. This PR supplies that hook. It returns `True` only when the bound action is `diagnostic_research` and the World identity is an enabled reviewer holding `case_investigation` who is signed in to an active admin session. It is read-only, because the bridge calls it inside a write transaction, and it fails closed on any error.

`publication.admin.AdminRouteGuard` requires an admin session with `case_investigation` for `POST /scouting/cases/{id}/challenge`, everything under `/scouting/challenges/` and `/scouting/world-attempts/`, and `POST /investigations/{id}/resume`. The case list read model stays public. The guard works by path, so these routes are protected wherever they are defined.

Known gap: PR #12 does not record which admin started a case attempt. The hook therefore requires the confirming person to be a signed-in case admin, not specifically the initiator. Exact initiator binding needs a small PR #12 change: pass the session principal into `case_world.start`, store it, and compare it in `poll`.

## API

All new DTOs use snake_case and are defined in the runtime schema above. "Admin" means `Authorization: Bearer <session_token>`.

| Route | Auth | Result |
|---|---|---|
| `POST /web/v1/admin/session` | none (capped by `SCOOBY_ADMIN_MAX_PENDING_LOGINS`) | `session`: `session_token` (returned once), `user_code`, `verification_uri`, `interval`, `expires_at` |
| `GET /web/v1/admin/session` | the session token | `session`; polls World while pending → `active` (with `label`, `scopes`) or `denied` / `expired` / `not_permitted` / `failed` |
| `DELETE /web/v1/admin/session` | the session token | `revoked` (or `cancelled` while pending) |
| `GET /web/v1/admin/reviews` | admin, `report_review` | `reviewQueue`, undecided versions first |
| `GET /web/v1/admin/reviews/{report_id}/{version}` | admin, `report_review` | `reviewDetail`: target, recommendation, pillar summaries, limitations, evidence, decision history, own pending attempt |
| `POST /web/v1/admin/reviews/{report_id}/{version}/attempts` | admin, `report_review`, `Idempotency-Key` | body `{decision, reason, expected_target_digest}` → `reviewAttempt` with `user_code` |
| `GET /web/v1/admin/review-attempts/{id}` | the initiating admin | `reviewAttempt`; polls World at most once per interval |
| `POST /web/v1/admin/review-attempts/{id}/cancel` | the initiating admin | `reviewAttempt` (`cancelled`) |
| `POST /web/v1/admin/reviews/{report_id}/{version}/revoke` | admin, `report_review` | withdraws the recorded decisions; the version returns to `pending_review` |
| `POST /web/v1/reports/{id}/approve`, `GET /web/v1/approvals/{id}` | admin, `publication`; only the requester sees an attempt | unchanged `Approval` shape (publication sign-off, not checkpoint 2) |
| `GET /publication/v1/targets/{id}`, `GET /publication/v1/attempts/{id}` | operator token (was open) | unchanged |
| `GET /reports`, `GET /reports/{id}/{version}/artifacts` | public | plus `admin_review` (`reviewStatus`): state, method, decision time, covered digests. No reviewer, reason or attempt |

Browser CORS: `/web/v1/admin/*` and the two web sign-off routes accept `Authorization` and `Idempotency-Key` from `SCOOBY_WEB_ORIGIN` only, with no cookies. The rest of `/web/v1` keeps its narrow policy.

## States

| Flow | States | Charter term |
|---|---|---|
| Admin session | `pending` → `active` / `denied` / `expired` / `cancelled` / `not_permitted` / `failed`; `active` → `revoked` / `expired` | pending, approved (= active), denied, expired, cancelled, failed |
| Review attempt | `pending` → `confirmed` / `denied` / `expired` / `cancelled` / `not_permitted` / `failed` / `superseded` | approved = `confirmed` with decision `approve` |
| Report version (admin) | `pending_review`, `awaiting_confirmation`, `approved`, `rejected`, `revision_requested`, `unavailable` (integrity failure) | superseded targets appear in history with `current_target: false` |
| Report version (consumer) | `pending_review`, `approved`, `rejected`, `revision_requested`, `unavailable` | safe subset |
| Publication attempt (unchanged) | `pending`, `approved`, `denied`, `expired`, `cancelled`, `rejected_not_reviewer`, `error` | a web-started attempt completed by someone other than its requester becomes `rejected_not_reviewer` |
| Case attempt (PR #12) | `pending`, `approved`, `denied`, `expired`, `cancelled`, `failed`, `superseded` | `denied` also when this PR's hook refuses |

## Configuration

All settings have safe defaults. Invalid values fail closed (503, or reports hidden).

| Variable | Default | Meaning |
|---|---|---|
| `SCOOBY_ADMIN_SESSION_TTL` | `14400` | Seconds an admin session stays active (60–86400) |
| `SCOOBY_ADMIN_ATTEMPT_TTL` | `600` | Upper bound for one checkpoint-2 confirmation (60–1200; World device codes last 20 min) |
| `SCOOBY_ADMIN_AUDIENCE` | `scooby-admin` | Bound into every review binding. Set it per deployment, for example to the API origin |
| `SCOOBY_ADMIN_MAX_PENDING_LOGINS` | `20` | Cap on unauthenticated login starts that are pending (each calls World) |
| `SCOOBY_REPORT_RELEASE` | `all` | `all` lists every version with its review state; `approved` lists only approved ones |
| `SCOOBY_PUBLICATION_REQUIRES_REVIEW` | `true` | A publication target or publish request needs a current checkpoint-2 approval |

`main` rewrote `.env.example`, so this branch leaves it unchanged. After merging `main`, add this under its World ID section:

```bash
# Admin World ID checkpoints (docs/admin-world-checkpoints.md)
SCOOBY_ADMIN_SESSION_TTL=14400
SCOOBY_ADMIN_ATTEMPT_TTL=600
SCOOBY_ADMIN_AUDIENCE=scooby-admin
SCOOBY_ADMIN_MAX_PENDING_LOGINS=20
# all = list every report with its review state; approved = only World-confirmed approvals
SCOOBY_REPORT_RELEASE=all
SCOOBY_PUBLICATION_REQUIRES_REVIEW=true
```

## Subject-matter-expert review and approved-only release

Reviewers holding `report_review` are the subject-matter experts (SMEs). With `SCOOBY_REPORT_RELEASE=approved`, the public library (`GET /reports`, `/reports/{id}/{version}/artifacts`, `/artifacts/*` and `/packages/*`) serves only versions whose current target has a World-confirmed approval; every other version answers 404 on all of those routes. SMEs read any installed version, released or not, through the admin API:

| Route | Auth | Result |
|---|---|---|
| `GET /web/v1/admin/reviews/{report_id}/{version}/artifacts` | admin, `report_review` | Same listing as the public route, with file URLs under the admin path (`package.url` is null) |
| `GET /web/v1/admin/reviews/{report_id}/{version}/files/{name}` | admin, `report_review` | `index.html`, `report.json`, `report.md`, `report.pdf` or `manifest.json` of the newest completed render of exactly the installed bytes; same integrity checks and CSP headers as the public files |
| `GET /web/v1/admin/reviews/{report_id}/{version}/files/assets/{path}` | admin, `report_review` | A hashed evidence or artifact asset of that render |

`reviewDetail.links.artifacts` points at the admin listing (`links.public_artifacts` keeps the public one). The files need the bearer header, so a browser fetches them and shows a blob URL rather than linking directly. With `SCOOBY_PUBLIC_GATE=true`, anonymous callers may `GET` only the public library routes above; the report detail with local review rows (`GET /reports/{id}/{version}`) and every write stay behind the operator token.

**Reviewers on a host without a persistent disk.** `SCOOBY_REVIEWERS` (a JSON list of `{label, iss, sub, scopes, enabled}`) is reapplied at API startup: each listed `(iss, sub)` is upserted with exactly the listed scopes; unlisted reviewers are untouched; invalid JSON loads nobody and logs no subject. Produce an entry from a real World enrollment with `python -m publication.cli export-reviewer --name <label>` and store it as a host secret. Being listed never approves anything; each decision still needs its own World confirmation.

## Per-report reading (review desk "Read" button)

`POST /web/v1/admin/session` with `{"report_id", "version"}` starts a World login whose session is limited to that installed report version: its review detail, SME files, decisions, revocation and publication sign-off. Any other route answers 403 ("limited to another report"). A per-report session never authorizes an investigation: the case-checkpoint route guard refuses it and `authorize_case_admin` ignores it. The confirmed World ID must still be an enabled reviewer with `report_review` (via `SCOOBY_REVIEWERS` or `enroll`), and each decision still needs its own World confirmation.

`SCOOBY_REVIEW_PER_REPORT=true` makes this mandatory for reading and deciding: an unrestricted admin session then gets 403 ("use Read on this report") on any report-specific review route, though it can still list the queue and use case routes. Off by default.

`GET /web/v1/review-queue` (anonymous) lists `report_id`, `report_version`, `report_sha256`, `created` and `state` for every installed version, so the desk can show a Read button per report without a sign-in. It exposes that pending versions exist and their ids, not their contents.

## Setup and walkthrough

1. Configure World as in [publication-demo.md](publication-demo.md) step 1. Run the API (`python -m uvicorn app:app --host 127.0.0.1 --port 8000`).
2. Enroll each admin by World login and grant only the scopes they need:
   ```bash
   python -m publication.cli enroll --name alice --scope report_review --scope case_investigation
   python -m publication.cli grant --name bob --scope publication      # bob is already enrolled
   python -m publication.cli list                                      # shows scopes
   python -m publication.cli ungrant --name bob --scope publication    # takes effect on the next request
   ```
3. Sign in (the web admin UI will wrap this; with curl):
   ```bash
   curl -sX POST localhost:8000/web/v1/admin/session            # note session_token and user_code
   # enter the code in World App, then:
   curl -s localhost:8000/web/v1/admin/session -H "Authorization: Bearer $SESSION"
   ```
4. Sign off a report: `GET /web/v1/admin/reviews`, then `GET .../reviews/{id}/{version}` and show the admin `target_digest`, the summary and the evidence; then `POST .../attempts` with `{decision, reason, expected_target_digest}` and `Idempotency-Key`. The admin enters the new code in World App; poll `GET /web/v1/admin/review-attempts/{id}` until it leaves `pending`. Consumers then see `admin_review.state` on `GET /reports`.

## Judge demo (World ID Agent Pass)

The prize asks for a meaningful human-approval action, the complete journey, and a failed path where the action does not happen. Admins only.

| # | Do | Expect |
|---|---|---|
| 1 | Admin signs in with World App | session `active`; a non-enrolled World ID gets `not_permitted` |
| 2 | Human-required Case → **Go for investigation** → confirm in World App (needs PR #12 merged) | exactly one investigation; a World ID without `case_investigation`, or an admin who is not signed in, gives `denied` and no run |
| 3 | Generated report → **Approve** → deny in World App | `denied`; the report stays `pending_review` |
| 4 | Approve again and let it expire, or cancel | `expired` or `cancelled`; still `pending_review` |
| 5 | Approve and confirm in World App | `confirmed`; consumers see `approved`; nothing is published and no research starts |
| 6 | Optional publication: operator prepares the target, admin signs off from `/approve/[id]`, explicit publish | publication still needs its own sign-off; revoking the report approval blocks the publish request |

## Security model and limits

- **No action binding in World.** World documents `binding_message` as unsupported, and device-grant ID tokens omit `nonce`. The approval page shows only the requesting app and the user code. The action is therefore bound in our database (target and binding digests on the attempt), shown to the admin before the code, and checked again at confirmation. This is the step-up pattern World recommends.
- **Device-code phishing.** Anyone can start a login and send its code to an admin. Mitigations: admins must enter only codes they started from the admin app; sessions are short; every checkpoint needs its own confirmation by the session's own World ID. Production path: browser authorization-code flow with PKCE and `max_age=0` for admin sign-in and step-up (World supports `authorization_code` with S256).
- **Passkeys.** World's baseline `acr` classes can be satisfied by a passkey (`amr` `["pop","user","mfa"]`), which asserts no fresh World proof. Receipts record the method (`world_proof` or `passkey`). Set `WORLD_ACCEPTED_ACR=https://world.org/oidc/acr/orb-face` to require a fresh proof with Face Auth.
- **Delegation.** World documents no delegation claim for ID tokens. Tokens carrying an RFC 8693 `act` or `may_act` claim are rejected for every human checkpoint. AgentKit is not used; agent or policy authority cannot create a human receipt.
- **Event proofs.** The ETHGlobal prize page says World proofs use fake identities during the event. Treat them as integration evidence, not production identity.
- **Legacy local operator routes** (`/candidates/{id}/selection`, `/investigations`, `/reports/{id}/{version}/review`) remain loopback plumbing. Their records are labelled unverified and never count as a checkpoint receipt. On a public host, `main`'s `SCOOBY_PUBLIC_GATE` keeps them behind the operator token.
- **Trusted backend.** The backend holds the World client key and decides admin permission. A compromised backend could forge decisions. The production path is a reviewed private admin gateway and a reviewer-held signing key.

## Merging this branch

This branch was cut from `main` at `ebfcdee` and is six commits behind (V2 registry and keccak256 claim-hash default `bd6f82a`, Render blueprint and `SCOOBY_PUBLIC_GATE` `ae6b837`, environment setup `e588a47`). A read-only three-way merge of every code and test file changed here reported **no textual conflicts** with `main` or with PR #12 (`b40ad97`). Then:

1. Merge `main` into this branch, add the `.env.example` block above, and regenerate `openapi.json` (generated; PR #12 also changes it).
2. `main`'s public gate already passes `/web/v1/admin/*`. Add `/scouting/` to `PUBLIC_PREFIXES` only if the web must reach the case routes on a public host; their checkpoint routes are guarded by this PR.
3. With PR #12: add `'Authorization'` to `CaseWebCORS` `allow_headers`, so the browser can send the admin session. Eight PR #12 tests call guarded routes without a session; give their clients one, for example in `test_cases.py`'s autouse fixture:
   ```python
   from admin_support import session_headers
   client.headers.update(session_headers('synthetic-issuer', 'synthetic-human', 'case_investigation'))
   yield
   client.headers.pop('Authorization', None)
   ```
   and `client.headers.update(session_headers('synthetic', 'synthetic', 'case_investigation'))` after each `TestClient(app)` in `test_case_journey.py`.
4. Optional: exact initiator binding for case attempts (see the known gap above).

Evidence from a scratch tree (`main` + PR #12 + this branch + step 3): **209 passed, 4 skipped**. That includes an end-to-end synthetic run in which an admin session leads to a challenge and a World confirmation by the right admin, then exactly one run; the generated report enters the admin queue with case lineage and render coverage, and a World-confirmed sign-off follows, with nothing published. A confirmation by a signed-in admin without `case_investigation` produced `denied` and no run.

## Web work (ScoobyDAO-web; not part of this backend PR)

- Admin sign-in: start, show `user_code` and `verification_uri`, poll `GET /web/v1/admin/session`. Keep the token in memory or `sessionStorage`, never in `NEXT_PUBLIC_*`. Show `not_permitted`, `denied`, `expired` and `failed`.
- Send `Authorization` on Cases controls (PR #6 `CaseWorldAction.tsx` / `scouting.ts`), on `/approve/[id]` (`/web/v1/reports/{id}/approve`, `/web/v1/approvals/{id}`) and on the new review routes.
- Review queue and detail: show the target digest, the report summary, evidence and limitations before starting an attempt. Send `expected_target_digest`. Cover every attempt state and retry.
- Consumer pages: show `admin_review` only (`pending_review` → "Pending admin review", `approved` → "Approved by an admin with World ID"). No admin controls or codes.

## Not done here

A live World run and the timing debrief; the web admin UI; merging `main` and PR #12; exact initiator binding for case attempts; production admin access (gateway, browser OIDC with PKCE, reviewer-held keys).
