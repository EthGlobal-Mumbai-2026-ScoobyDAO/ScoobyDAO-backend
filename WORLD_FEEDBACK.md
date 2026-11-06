# World ID Agent Pass: integration feedback (skeleton)

Fill in after the live run. Timing comes from the `world_timing` log events (`discovery_ok`, `first_device_request`, `first_token_success`) emitted by `publication/world.py`.

## Time to first successful token

- Discovery OK at: _
- First device request at: _
- First token success at: _
- Wall-clock from app registration to first validated ID token: _

## Integration friction

- _

## Missing or contradictory docs (assumptions made while building against a fake issuer)

1. Exact JSON body of the `device_authorization` response is only described in prose; we rely on RFC 8628 field names (`device_code`, `user_code`, `verification_uri`, `verification_uri_complete`, `expires_in`, `interval`).
2. The default `interval` isn't documented; we use the returned value and assume 5 s when absent (RFC 8628 default).
3. Client-assertion `aud`: both the issuer and "the exact endpoint being called" are accepted, but no preference is stated. We default to the endpoint being called (configurable).
4. Whether the `claims` request parameter is honored on the device endpoint in the same way as browser authorize. The step-up guide says it is accepted as an extension, while also noting that unknown/unsupported extensions are ignored. We validate `acr` ourselves regardless.
5. No documented action-binding / signed approval receipt profile ("keep the operation blocked until you validate one through a profile that advertises support for it"). We bind the action in our own database.
6. ID token `exp` lifetime, access token lifetime, numeric per-client and per-IP rate limits, and JWKS upload/rotation propagation time are not documented.
7. Whether `azp` is ever present (single-audience tokens) is not documented; we check it only for multi-audience tokens.
8. Sandbox rate limits and sandbox credential issuance details ("about one hour") need confirming.

## Top improvement request

- _ (candidate: an action-binding field that is displayed in World App and signed into the ID token, e.g. a short binding message or a hash commitment)

## Environment, SDKs and versions

- Python 3.11, FastAPI, httpx, PyJWT[crypto] 2.x, cryptography, eth-account, web3 7.x (see `requirements.txt`)
- Issuer: `https://auth.world.org` (or sandbox), discovery checked 2026-11-06
- Chain: Ethereum Sepolia, ReportRegistry `0xfb2c164ddb3676d03e1e443f3f2934b8d0df88e5`
- World App version used by the reviewer: _
