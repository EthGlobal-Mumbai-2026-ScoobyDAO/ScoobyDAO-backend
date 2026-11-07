# World ID Agent Pass — integration debrief (ScoobyDAO)

> **Status:** times below come from git history. Items marked **TODO(live)** wait on the live-run record (the `admin_sessions` / `rev_receipts` rows on the deployed disk) and the team's portal and World App details.

## What we built
AI agents investigate suspicious tokens. A verified human must confirm in World App before a draft report is opened, before a decision (approve, reject or revise) is recorded on that exact report version, and before a report is published onchain. Each confirmation uses the OIDC device grant with `private_key_jwt` and is validated in our FastAPI backend; denied, expired and cancelled attempts do nothing.

## Time to first success
All times IST (UTC+5:30) on 6 November 2026.

| Milestone | Time | Evidence |
|---|---|---|
| First World ID code committed | 14:59 | commit `d42d0e8` |
| Synthetic tests for the admin checkpoints added | 19:55 | commit `4c0ca07` |
| Issuer error diagnostics added; sandbox discovery compared with production | 20:03 | commit `8481748`, `docs/publication-demo.md` |
| Private key accepted from `WORLD_CLIENT_KEY`, with clear load errors | 22:13 | commit `4867e65` |
| App registered in the World developer portal | TODO(live) | portal app page |
| First validated live ID token | TODO(live) | earliest `active` row in `admin_sessions` |
| First protected action (report decision recorded) | TODO(live) | earliest `rev_receipts.verified_at` |

- First code → issuer diagnostics: **5 h 4 min**. First code → host key loading fixed: **7 h 14 min**.
- Portal registration → first validated ID token: **TODO(live)**. Registration → first protected action: **TODO(live)**.

## Friction we hit
- **World App shows only the requesting app and a code, not what the person is approving.** For each of our four protected actions we bound the approval to the exact target on our server (target and binding digests, re-checked on confirmation) and showed the action in our own UI before the code.
- **Failed logins were hard to diagnose.** We added the issuer's `error_description` and the rejected `acr` value to our errors, plus a mode that omits the `claims` request to isolate assurance-level problems (`8481748`).
- **Supplying the client private key on the host.** A mounted PEM file was awkward on our host, so we accept the key from an environment variable and say exactly why a key fails to load (`4867e65`).
- **Device-grant ID tokens carry no `nonce`.** We tie a token to its attempt through our own device-code record and an `auth_time` window.

TODO(live): add any friction from the live run.

## Missing capability or documentation
- **Requiring a fresh face check.** A passkey satisfies the baseline Orb `acr` (`amr` `["pop","user","mfa"]`), and it isn't documented whether the `claims` request is honoured on the device endpoint. We validate `acr` ourselves and use `orb-face` when a fresh proof is required.
- **Device-flow details.** The `device_authorization` response body, the default polling `interval`, 429 behaviour, numeric rate limits and token lifetimes are not documented.
- **Event mock proofs.** The prize page says proofs use test identities during the event, but the auth.world.org docs don't describe that mode or how to recognise those tokens.

## The one improvement with the greatest impact
**Action binding shown in World App and included in the ID token:** a short message or hash commitment that the person sees before confirming and that World signs into the token. Human approvals of agent actions would be safer, because the person sees what they approve, and apps would stop rebuilding this binding server-side, as we did for four actions.

## Environment
- Python 3.11, FastAPI, httpx, PyJWT[crypto] 2.x, cryptography (see `requirements.txt`)
- Issuer `https://auth.world.org`; sandbox discovery compared on 2026-11-06
- World App version: **TODO(live)**
- Ethereum Sepolia, ReportRegistry `0x805d681383f580403b979bf1d017cff045dc7ebd`

---

## Appendix: build-time notes
Found while building against the docs and our fake issuer (`tests/fake_world.py`) on 6 November 2026.

**Where we use it.** All are admin actions; see [docs/admin-world-checkpoints.md](docs/admin-world-checkpoints.md).
- Admin sign-in: an enrolled reviewer with a server-side scope gets a short admin session.
- Checkpoint 1: "Go for investigation" on a human-required case, bound to that case, evidence and policy revision.
- Checkpoint 2: sign-off on a report version, bound to the report, evidence and render digests.
- Publication sign-off: a separate confirmation before the attestor signs `ReportRegistry.publish`.

**More friction.**
- Matching the confirmer to the admin who started is application work; we compare the validated `(iss, sub)` with the session's. The documented `claims.id_token.sub` request could enforce this in World, but there is no device-grant example.
- Anyone can start a device grant and send its code to an admin, so it can be phished. A browser authorization-code flow with PKCE looks safer for an admin UI.

**More documentation gaps and the assumptions we made.**
- Device response fields: we rely on RFC 8628 names; when `interval` is missing we assume 5 s.
- Client-assertion `aud`: both the issuer and the endpoint are accepted; we default to the endpoint being called (configurable).
- No action-binding or signed-approval-receipt profile is documented, so we bind the action in our database.
- Not documented: `azp` presence (we check it only for multi-audience tokens), JWKS upload/rotation propagation time, sandbox rate limits and credential issuance time ("about one hour"), and sandbox `acr_values_supported`.
- No ID-token claim distinguishes delegated or agent-held authentication from a direct human one. We reject RFC 8693 `act` / `may_act` claims defensively.
