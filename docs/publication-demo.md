# Publication demo runbook (live World + Sepolia)

Everything below the "Human authorization required" line needs a person to authorize it. Development and CI never do these things.

## Local, no network side effects (verified)

```bash
python -m pip install -r requirements.txt
python -m pytest -q tests          # fake World issuer; anvil tests run if Foundry is installed
python tests/smoke_worker.py
```

## Human authorization required

1. **Register the World app** (production `https://auth.world.org/portal`, or sandbox `https://sandbox.auth.world.org/portal` first). Choose client authentication `private_key_jwt` and accepted accounts Orb (orb-face if wanted). Register an HTTPS redirect URI even though the device grant doesn't use it.
   ```bash
   mkdir -p secrets && openssl genrsa -out secrets/world_client_key.pem 2048
   python scripts/world_jwk.py secrets/world_client_key.pem --kid scooby-2026-11   # paste the JWKS into the portal
   ```
   Set `WORLD_ISSUER`, `WORLD_CLIENT_ID`, `WORLD_CLIENT_KEY_PATH`, `WORLD_CLIENT_KEY_ID`.
2. **Keys and funding.** Create two Sepolia EOAs: the publisher, which must be `ReportRegistry.publisher()` for `0xfb2c164ddb3676d03e1e443f3f2934b8d0df88e5` (if it isn't, deploy a new registry with your publisher and update `SCOOBY_REPORT_REGISTRY`), and the attestor. Fund only the publisher with Sepolia ETH. Set `SCOOBY_PUBLISHER_KEY`, `SCOOBY_ATTESTOR_KEY`, `SCOOBY_RPC_URL`, `SCOOBY_RESOLVER`, `SCOOBY_ADJUDICATOR`, `SCOOBY_OPERATOR_TOKEN`.
3. **Enroll reviewers** (each does a World App login once):
   ```bash
   python -m publication.cli enroll --name alice --scope report_review --scope publication   # admin scopes: docs/admin-world-checkpoints.md
   python -m publication.cli list
   ```
4. **Run the services** (three shells):
   ```bash
   python -m uvicorn app:app --host 127.0.0.1 --port 8000
   SCOOBY_PUBLISH_ENABLED=true python -m publication.publisher   # types the live confirmation
   # web: NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/web/v1 npm run dev   (in ScoobyDAO-web)
   ```
5. **Prepare a target** for an imported report version that already has a current World-confirmed admin approval (checkpoint 2, below; otherwise 409):
   ```bash
   curl -sX POST localhost:8000/publication/v1/targets -H "Authorization: Bearer $SCOOBY_OPERATOR_TOKEN" \
     -H 'Idempotency-Key: demo-target-1' -H 'Content-Type: application/json' \
     -d '{"report_id":"…","version":"…","params":{"lock_time":…,"cross_chain_cutoff":…,"result_deadline":…,"challenge_period":86400}}'
   ```
6. **First Sepolia publish.** After an approval, either `python -m publication.cli publish-confirm --target <id>` (typed confirmation), or set `SCOOBY_DEMO_AUTOPUBLISH=true` for the stage run. Record the tx hash in README and WORLD_FEEDBACK.md.

## Five-step judge demo (`/approve/[id]` on the projector)

| # | Do | Expect |
|---|---|---|
| 1 | Request sign-off, then **deny** in World App | "Denied — no case opened"; no receipt; publish → 409 |
| 2 | Request sign-off, let the code **expire** (or cancel) | "Expired — no case opened" |
| 3 | Request sign-off; a person **not enrolled** approves | "Not a registered reviewer — nothing published" |
| 4 | Request sign-off; enrolled reviewer **approves** → publish | "Case opened" + Sepolia tx link; `Published` event; report id |
| 5 | **Replay**: publish again / reuse the approval | 409 "approval already used"; the approval shows `spent` |

The web sign-off routes behind `/approve/[id]` (`POST /web/v1/reports/{id}/approve`, `GET /web/v1/approvals/{id}`) are admin actions now. They need an admin session holding the `publication` scope, and only the admin who requested a sign-off can see its code or complete it. Until the web sends the session, run this demo through the operator API (`/publication/v1`, operator token).

## Admin checkpoints (backend PR #10)

Both human checkpoints are admin-only and each needs its own fresh World confirmation. See [admin-world-checkpoints.md](admin-world-checkpoints.md) for the API, states and limits.

1. Grant scopes to enrolled admins (`python -m publication.cli grant --name alice --scope report_review`; `case_investigation` for Cases).
2. The admin signs in: `POST /web/v1/admin/session`, enter the code in World App, then `GET /web/v1/admin/session` until `active`.
3. **Checkpoint 2:** `GET /web/v1/admin/reviews` → detail → `POST .../attempts` with the shown `expected_target_digest` → World App → poll `GET /web/v1/admin/review-attempts/{id}`. Deny, expire or cancel first to show that no decision is recorded; then approve. Consumers see `admin_review` on `GET /reports`.
4. **Checkpoint 1** (after backend PR #12 is merged): Case → challenge → World attempt with the admin session. A World ID without `case_investigation`, or an admin who is not signed in, cannot start a run.
5. Publication (optional) follows a current report approval and still needs its own sign-off and explicit publish request.
