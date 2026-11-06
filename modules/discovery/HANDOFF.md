# Backend continuation

Import scope: this directory's Python source, synthetic fixture and tests. `README.md` is the interface and policy guide. There are no databases, credentials, copied shared contracts or live observations in this export. The outer discovery workspace and its historical SHIB/BLISS research files are not included.

Verification: 21 isolated tests passed against the agreed shared candidate schema with jsonschema and pycryptodome available; no live calls were made for the export test. A prior live G09 collection smoke attempt failed HTTP 403 and is not proof of availability. All metric verifiers remain disabled. No live qualified candidate is provided.

Important integration constraints: preserve the candidate-v0.1/report-v0.2 shared boundary; enforce the 4-group gate and human selection, keep unselected candidates monitored, preserve hash/provenance and unknown data, and do not turn GoPlus or other provider hints into verified votes. Avoid importing `action()` as an authenticated endpoint; it is caller-trusted local state code. The explicit BLISS diagnostic exception was a user-authorized one-off and is not an ordinary gate result.

Next: adapt the flat source module and CLI for the new backend's structure; ensure the authoritative schema is used; run all tests and integration checks; validate real source/RPC behavior and implement independent concern checks; register only proven verifiers. No deployment or publication is implied.
