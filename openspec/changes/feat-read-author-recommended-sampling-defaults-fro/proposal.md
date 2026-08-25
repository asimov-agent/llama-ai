# feat-read-author-recommended-sampling-defaults-fro

## Why

`llama_ai.py` launches `llama-server` with a single fixed sampling preset
(`SAMPLING = ["--temp", "0.6", "--top-p", "0.9", "--top-k", "40", "--min-p",
"0.05", "--repeat-penalty", "1.05"]`) for **every** model. This ignores the
author-recommended sampling defaults that each GGUF publishes under the
`general.sampling.*` metadata namespace (e.g. `general.sampling.temperature`,
`general.sampling.top_p`, `general.sampling.top_k`, `general.sampling.min_p`,
`general.sampling.repeat_penalty`).

Because the metadata is read but only architecture facts are extracted, the
launcher silently drifts one fixed set onto every model — including models whose
authors recommend different defaults. The fix reads `general.sampling.*` and uses
it as the sampling defaults, falling back to the existing preset only when a field
is absent or unparseable.

## What Changes

- `read_model_meta_fast` / `read_model_meta` gain a `sampling` key populated from
  `general.sampling.*` metadata (string form of each scalar).
- `build_command` consumes `meta["sampling"]` as the first sampling flags,
  falling back to the existing `SAMPLING` preset when the model supplies none.
- The fixed global `SAMPLING` list stays as a fallback default (not removed), so
  existing behaviour for models without metadata is unchanged.

## Impact

- File: `llama_ai.py` (metadata reader + command builder).
- Tests: `tests/test_llama_ai.py` (adds sampling-metadata assertions).
- Docs: this proposal / spec / tasks.
