# Terra reasoning in the case producer

`case_research.run_case` optionally performs **one shared** `gpt-6.1-terra` Chat Completions request for the five pillars and cross-pillar conclusion, before report validation, digest and installation. This is not five independent agents or five model calls. The application owns source collection and passes bounded evidence; no model tools, web access, model fallback or automatic retry are supplied. The existing `reasoning_v2/output.schema.json`, prompt, legacy math reference and validator are reused; frozen report v0.2 is unchanged. See the official [Terra model page](https://developers.openai.com/api/docs/models/gpt-6.1-terra), [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) and [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## Interface and budget ownership

The existing `run_case` inputs are unchanged. New optional keyword arguments:

```python
run_case(...,
    max_model_calls=0,               # only 0 or 1; default never calls a model
    model_client=None,               # injectable client with chat.completions.create
    max_model_output_tokens=4096,    # 256–8192, includes reasoning tokens
    max_model_context_chars=120000,  # 1000–200000 chars for structured evidence JSON
    stage_callback=None,
    reasoning_checkpoint=None,
)
```

For a real call the backend atomically reserves the authorized model call and spending budget **before** invoking the producer, passes `max_model_calls=1` and a durable stage callback, and ensures the case/run/authorization remains valid. The callback is required for a new model invocation; the default client is `OpenAI(timeout=60, max_retries=0)` and reads `OPENAI_API_KEY` only from the process environment. Injected SDK clients exposing `max_retries` must set it to zero; test clients use synthetic responses. The per-call output cap and source-context character cap are separate from the backend's cross-worker token/cost/rate budget, which this module does not enforce. A one-call budget is an upper bound, not permission to initiate a paid call.

The backend must implement durable exactly-once reservation/recovery. The callback receives JSON-serializable events; its closure should bind case/run/decision and persist safely:

- `sources/started`, `source/<name>` capture/skip/unavailable, and `sources/completed` describe actual source preparation.
- `reasoning/started` identifies the one shared request and input hash. `reasoning/completed` includes a validated `scooby.reasoning-checkpoint/1` with input, prompt and schema hashes, model, usage if provided, and validated output. Persist it privately; it contains model-generated research text. A callback error raises `StagePersistenceError` and prevents bundle install. The caller must not blindly repeat a potentially spent request after an ambiguous failure.
- `reasoning/resumed` means a backend-supplied, trusted stored checkpoint was revalidated against the same evidence, prompt, schema and model; no new model call occurred. Resume with `reasoning_checkpoint=<stored checkpoint>` and `max_model_calls=0`. A mismatched or invalid checkpoint is rejected. The backend must authenticate and bind stored checkpoints to the authorized run; the checkpoint hash is not a signature.
- `pillar/validated_shared_output` or `pillar/unavailable` and `conclusion/validated_shared_output` are validation events emitted after the **single** shared response, not separate model starts or completions. `report/validated` means the complete bundle passed validation before atomic install. Skipped, unavailable, failed and cancelled stages remain explicit.

`run_case` returns `model_status`, `model_calls`, and sanitized reported `model_usage` alongside its usual partial bundle result. Valid usage is also included in completed checkpoints/events and in cancellation or failure events/results when a response exists; absence stays unknown, not zero. A zero budget yields `skipped_budget`; missing key, invalid context, retry-enabled client, refusal, truncation, provider error or invalid response yields an explicit non-success model state and a source-only partial draft. `failed_refused`, `failed_incomplete_output`, `failed_invalid_or_unlinked_output`, `failed_provider_failure`, and `failed_model_identifier_mismatch` distinguish the major cases. The documented Terra snapshot currently identifies as the exact requested `gpt-6.1-terra`; if a response reports any other identifier, this slice rejects it as a mismatch and never silently falls back. An independently documented, explicitly reviewed resolved snapshot can be added later. Cancellation after a spent call returns cancelled without installing the bundle. Model calls cannot be interrupted mid-request. If checkpoint persistence fails, the bundle is not installed; resume from the persisted trusted checkpoint or reconcile the ambiguous call before any retry.

## Evidence, outputs and limits

The prompt treats all evidence and source text as untrusted data, not instructions. Each source byte hash is rechecked; snippets receive a fair bounded share of the remaining JSON budget and disclose truncation, while structured input IDs and values remain in the context. Very long price series retain the first fifty and last one hundred fifty points with an explicit omission note. If structured facts alone exceed the context cap, no model request is made. The original VAE math reference is included only when the identity- and candle-bound 50-reconstruction evidence exists. Missing statistical/VAE pillars are replaced with deterministic unavailable descriptions and derived coverage records; model text cannot populate missing metrics or change pillar statuses, original scores, gate votes, source freshness or raw source bytes.

Responses are parsed against the existing strict schema and reasoning-v2 validator. Each available-pillar paragraph must cite same-pillar input and evidence IDs; conclusion paragraphs and recommendation rationale must cite linked inputs/evidence, and a cross-pillar conclusion must cover at least two available pillars when possible. Known counterevidence must be addressed. Numeric literals in generated prose must already occur in available structured pillar facts, or in the supplied legacy math reference when VAE evidence exists. A proposed conclusion and its uncertainty are required. These checks reject many fabricated identifiers and values but **do not prove semantic entailment or factual truth**; human review remains required.

On success the same bundle gains `reasoning.json` (`scooby.reasoning/2`), `pillar-irc.json` (`scooby.pillar-irc/1`), cited TL;DR findings/interpretations, and readable proposed analysis/conclusion in `report.md`. TL;DR `finding` is drawn from deterministic source observations; model-written summaries and reasoning are labeled `interpretation`. Original deterministic pillar measurements, source bytes and hashes remain intact. Model conclusions are proposed, not human approval or publication. Social content remains subject to the separate deletion/retention boundary and is not persisted by this producer.

## Verification

`python -m pytest -q tests/test_case_terra_reasoning.py` uses only injected synthetic clients and captured synthetic sources. Tests check exact model/transport/schema and one-call cap; five sections and cross-pillar reasoning; valid report/IRC/TL;DR and reader HTML; unlinked or wrong-pillar citations, invented numbers, missing counterevidence, refusal and truncation; zero budget, missing key, retry-enabled clients and context cap; cancellation and callback failure; and checkpoint resume without a second call. A separate synthetic HTML fixture under the investigation workspace is explicitly labeled synthetic and is not a live Terra result. No live paid model, source, World or chain call was made for these tests.
