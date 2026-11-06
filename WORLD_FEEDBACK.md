# World ID Agent Pass: integration feedback (skeleton)

Fill in after the live run. Timing comes from the `world_timing` log events (`discovery_ok`, `first_device_request`, `first_token_success`) emitted by `publication/world.py`. Items marked *build-time* were found while building against the docs and the fake issuer on 6 November 2026; they are not live-run results.

## Where Scooby uses World ID Agent Pass

All of these are admin actions. Each is an OIDC device grant with `private_key_jwt`, validated in the backend; see [docs/admin-world-checkpoints.md](docs/admin-world-checkpoints.md).

- **Admin sign-in:** an enrolled reviewer holding a server-side scope gets a short admin session.
- **Checkpoint 1:** "Go for investigation" on a human-required scout Case. The agents' research starts only after the admin confirms that exact case, evidence and policy revision. Policy-qualified cases start automatically, but their reports still need checkpoint 2.
- **Checkpoint 2:** sign-off on an agent-generated report version (approve, reject or revise), bound to the exact report, evidence and render digests.
- **Publication sign-off:** a separate confirmation before the attestor signs `ReportRegistry.publish`.

The judge demo is designed to show denied, expired, cancelled and not-permitted attempts as well, in which no research starts, no decision is recorded and nothing is published. These paths are covered by synthetic tests; the live run is still to be recorded.

## Time to first successful token

- Discovery OK at: _
- First device request at: _
- First token success at: _
- Wall-clock from app registration to first validated ID token: _

## Integration friction

- _ (live run)
- *Build-time:* the approval page shows only the requesting app and the user code, so every protected action needs its own server-side binding: target and binding digests, display of the action before the code, and a re-check on confirmation.
- *Build-time:* device-grant ID tokens omit `nonce`. We tie a token to an attempt through our own device-code record and an `auth_time` window.
- *Build-time:* matching the confirmer to the admin who asked is application work. We compare the validated `(iss, sub)` with the session's. The documented `claims.id_token.sub` request could enforce this in World, but there is no device example.
- *Build-time:* a device grant for an admin action can be phished: anyone can start one and send its code to an admin. A browser authorization-code flow with PKCE looks safer for an admin UI.
- *Build-time:* a passkey satisfies the baseline Orb `acr` without a fresh proof (`amr` includes `mfa`). We record the method and use `orb-face` when a fresh proof is required.
- *Build-time:* 429 on a poll "can end the attempt", while a 429 on start carries `Retry-After: 60`. There are no numeric quotas, so retry logic has to guess.

## Missing or contradictory docs (assumptions made while building against a fake issuer)

1. Exact JSON body of the `device_authorization` response is only described in prose; we rely on RFC 8628 field names (`device_code`, `user_code`, `verification_uri`, `verification_uri_complete`, `expires_in`, `interval`).
2. The default `interval` isn't documented; we use the returned value and assume 5 s when absent (RFC 8628 default).
3. Client-assertion `aud`: both the issuer and "the exact endpoint being called" are accepted, but no preference is stated. We default to the endpoint being called (configurable).
4. Whether the `claims` request parameter is honored on the device endpoint in the same way as browser authorize. The step-up guide says it is accepted as an extension, while also noting that unknown/unsupported extensions are ignored. We validate `acr` ourselves regardless.
5. No documented action-binding / signed approval receipt profile ("keep the operation blocked until you validate one through a profile that advertises support for it"). We bind the action in our own database.
6. ID token `exp` lifetime, access token lifetime, numeric per-client and per-IP rate limits, and JWKS upload/rotation propagation time are not documented.
7. Whether `azp` is ever present (single-audience tokens) is not documented; we check it only for multi-audience tokens.
8. Sandbox rate limits and sandbox credential issuance details ("about one hour") need confirming.
9. No ID-token claim distinguishes a delegated or agent-held authentication from a direct human one; only the XAA ID-JAG covers delegation. We reject RFC 8693 `act` / `may_act` claims defensively.
10. The sandbox discovery `acr_values_supported` are not documented ("Orb-level test credential" only).
11. The ETHGlobal prize page says proofs are mocked with fake identities during the event; the auth.world.org docs do not describe that mode or how to recognize such tokens.

## Top improvement request

- _ (confirm after the live run. Candidate: an action-binding field that is displayed in World App and signed into the ID token, such as a short binding message or a hash commitment. All four of our protected actions had to rebuild this binding in the backend, and the human still cannot see in World App what they are approving.)

## Environment, SDKs and versions

- Python 3.11, FastAPI, httpx, PyJWT[crypto] 2.x, cryptography, eth-account, web3 7.x (see `requirements.txt`)
- Issuer: `https://auth.world.org` (or sandbox), discovery checked 2026-11-06
- Chain: Ethereum Sepolia, ReportRegistry `0xfb2c164ddb3676d03e1e443f3f2934b8d0df88e5`
- World App version used by the reviewer: _
