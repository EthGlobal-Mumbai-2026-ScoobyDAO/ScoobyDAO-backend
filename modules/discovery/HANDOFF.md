# Backend continuation

Import scope: this directory's Python source, synthetic fixture and tests. `README.md` is the interface and policy guide. There are no databases, credentials, copied shared contracts or live observations in this export. The outer discovery workspace and its historical SHIB/BLISS research files are not included.

Verification: 21 isolated tests passed against the agreed shared candidate schema with jsonschema and pycryptodome available; no live calls were made for the export test. An authenticated reference-only G09 collector smoke test succeeded after an earlier unauthenticated archive request failed with HTTP 403; the collector now checks its values against the recorded transcript. A reference-only comparison against dRPC and DEX Screener checked the method; G09 price-move and G07 sampled LP-address concentration are enabled for the narrowly supported Ethereum V2/WETH scope. Other concern verifiers remain disabled or held. No live qualified candidate is provided.

Important integration constraints: preserve the candidate-v0.1/report-v0.2 shared boundary; enforce the 4-group gate and human selection, keep unselected candidates monitored, preserve hash/provenance and unknown data, and do not turn GoPlus or other provider hints into verified votes. Avoid importing `action()` as an authenticated endpoint; it is caller-trusted local state code. The explicit BLISS diagnostic exception was a user-authorized one-off and is not an ordinary gate result.

Next: adapt the flat source module and CLI for the new backend's structure; ensure the authoritative schema is used; run all tests and integration checks; validate real source/RPC behavior and implement independent concern checks; register only proven verifiers. No deployment or publication is implied.

Local continuation: `continuous_pilot.py` adds an explicitly started, bounded single-operator loop and refreshes the local review queue. It is not integrated into the backend worker; only G07 and the price-move portion of G09 are enabled and no candidate has qualified. See README for rate, retention, authentication and source-coverage limits.
