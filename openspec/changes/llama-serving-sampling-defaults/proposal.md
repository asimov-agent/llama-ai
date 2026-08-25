# llama-serving-sampling-defaults

## Why

`scripts/llama_serve.py` launches `llama-server` with a single fixed sampling
preset (`SAMPLING = ["--temp", "0.6", "--top-p", "0.9", "--top-k", "40",
"--min-p", "0.05", "--repeat-penalty", "1.05"]`) for **every** model, ignoring the
author-recommended sampling defaults each GGUF publishes under the
`general.sampling.*` metadata namespace (`general.sampling.temperature`,
`general.sampling.top_p`, `general.sampling.top_k`, `general.sampling.min_p`,
`general.sampling.repeat_penalty`).

The metadata is read but only architecture facts are extracted, so the launcher
silently drifts one fixed set onto every model — including models whose authors
recommend different defaults. Issue #16 asks the launcher to read
`general.sampling.*` and use it as the sampling defaults, falling back to the
existing preset only when a field is absent or unparseable.

There is also a latent **argv-splitting bug**: `build_command` historically spread
the `*SAMPLING` preset unconditionally. A correct per-model default must be emitted
as **separate argv elements** (`["--temp", value]`, not the single string
`"--temp {value}"`), because llama.cpp treats a `"--temp 0.7"` string as one invalid
argument. The implementation must avoid emitting duplicate flags (model-specific +
preset both appearing) and double-preset.

## What Changes

- `scripts/llama_serve.py` gains `SAMPLING_FLAG_MAP` and `SAMPLING_KEYS` dicts that
  map the GGUF key names to their `llama-server` flag names.
- The readers `read_model_meta_fast` and `read_model_meta` gain helpers
  (``_extract_sampling_from_kv`` / `_extract_sampling_from_fields``) that read the
  `general.sampling.*` keys (as strings, omitting absent/empty, never raising) and
  return a dict keyed by short name. Both readers populate a `sampling` key on the
  returned meta dict (`{}` when none).
- `build_command` consumes `meta["sampling"]`: when non-empty it emits the
  model-specific flags; otherwise it falls back to the existing `SAMPLING` preset.

## Impact

- File: `scripts/llama_serve.py` (metadata reader + command builder).
- Tests: `tests/test_llama_ai.py` (adds sampling-metadata assertions + the argv
  split bug regression).
- Docs: this proposal / spec / tasks.
- README: `SAMPLING` customization note stays accurate (the preset is preserved as
  the fallback).
