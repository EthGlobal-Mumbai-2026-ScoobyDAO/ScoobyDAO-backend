# ScoobyDAO × World ID Agent Pass — qualification map

ScoobyDAO's AI agents investigate suspicious tokens and draft reports that accuse a token of being a rug. Publishing one opens a staking market with real money. **No agent can open, approve or publish a report on its own.** A verified human confirms each consequential action in World App, and our backend validates that confirmation before anything happens.

Code is pinned to `ScoobyDAO-backend@53d97ee` and `ScoobyDAO-web@1dc90fc`.

## Requirement → where it's met

| # | World requirement | How ScoobyDAO meets it | Code |
|---|---|---|---|
| 1 | Integrate the official World ID Agent Pass | OIDC at `auth.world.org`: discovery, JWKS, `private_key_jwt` (RS256) client auth, and the Device Authorization Grant, because our agents are headless | [`publication/world.py` L172–L284](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/blob/53d97ee68fd6e08fb7340a77b7543a3eabfab10d/publication/world.py#L172-L284) |
| 2 | Complete journey: request → user completes → validated result → protected action | **Read:** a reviewer opens a private draft with World ID. **Decide:** the reviewer approves, rejects or requests revision, bound to the exact report digest. The approval makes the report public. **Publish:** a separate World sign-off lets the attestor sign `ReportRegistry.publish`, which opens the market | [`review.py` create_attempt L328](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/blob/53d97ee68fd6e08fb7340a77b7543a3eabfab10d/publication/review.py#L328-L388), [`review.py` poll + receipt L388–L490](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/blob/53d97ee68fd6e08fb7340a77b7543a3eabfab10d/publication/review.py#L388-L490), [`service.py` request_publication L408](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/blob/53d97ee68fd6e08fb7340a77b7543a3eabfab10d/publication/service.py#L408) |
| 3 | Denied / expired / cancelled path where the action does not happen | Denied, expired, cancelled, not-permitted (a different World ID confirmed) and superseded (the report changed) all record **no decision** and publish nothing. The UI shows each state | [`review.py` L420–L490](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/blob/53d97ee68fd6e08fb7340a77b7543a3eabfab10d/publication/review.py#L420-L490), web [`ReviewScreen.tsx`](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-web/blob/1dc90fcd29e65986f0758e79c6eaa0720ad72528/src/components/admin/ReviewScreen.tsx) |
| 4 | Secure backend validation, no client secrets | ID tokens are validated server-side: signature against World's JWKS, issuer, audience, expiry, `auth_time` within the attempt, `acr`. Delegation claims (`act`/`may_act`) are rejected. The confirming person must match the reviewer who started. Each approval is bound to target digest + nonce + expiry, single use, with an append-only receipt. Identity ≠ permission: a scoped reviewer allowlist. The client key lives in a server secret; the browser never sees tokens or device codes | [`world.py` validate_id_token L230–L284](https://github.com/EthGlobal-Mumbai-2026-ScoobyDAO/ScoobyDAO-backend/blob/53d97ee68fd6e08fb7340a77b7543a3eabfab10d/publication/world.py#L230-L284) |
| 5 | Integration debrief | [WORLD_FEEDBACK.md](WORLD_FEEDBACK.md) | — |

## Live evidence

Not yet recorded. Each item below is marked TODO until the team supplies it.

| Evidence | Value | Source |
|---|---|---|
| First live World App confirmation | TODO(live) | earliest `active` row in `admin_sessions` on the deployed disk |
| Denied attempt, live | TODO(live) | `rev_attempts` rows with status `denied`; demo video |
| Approved decision recorded | TODO(live) | earliest `rev_receipts.verified_at` |
| `acr` / `amr` on event proofs | TODO(live) | `rev_receipts.acr`, `rev_receipts.amr_json` |
| Demo video timestamps | denied TODO · approved TODO · published TODO | demo video |
| Publish transaction on Sepolia | TODO | Etherscan link for `ReportRegistry.publish` |
| Screenshots | TODO: World code panel, denied state, approved state, report now public | file paths |

Build history (git, 6 November 2026, IST): first World ID code `d42d0e8` at 14:59; checkpoint tests `4c0ca07` at 19:55; issuer diagnostics `8481748` at 20:03; host key loading `4867e65` at 22:13. See [WORLD_FEEDBACK.md](WORLD_FEEDBACK.md).

## Try it

1. Web: https://scoobydao-web.vercel.app → **Review desk** → **Read** on a report.
2. Scan the QR code in World App (event proofs use test identities), then deny once: the report stays closed.
3. Read again and confirm. Choose **Approve** and confirm in World App: the decision is recorded and the report appears in the public library.
4. Reviewers are enrolled server-side (`python -m publication.cli enroll`); an unenrolled World ID is refused.

Synthetic tests: `tests/test_admin_checkpoints.py` and `tests/test_publication.py` run against a fake World issuer, covering positive, negative, replay and cross-action cases.
