# llama-serving-sampling-defaults

## Implementation tasks

- [x] 1.1 Add `SAMPLING_FLAG_MAP` and `SAMPLING_KEYS` in `scripts/llama_serve.py`.
- [x] 1.2 Add `_extract_sampling_from_kv` (header reader) that reads
      `general.sampling.*` from a parsed kv dict, storing short-name strings;
      omit absent/empty; never raise.
- [x] 1.3 Add `_extract_sampling_from_fields` (GGUFReader fields reader) with the
      same contract.
- [x] 1.4 Wire `sampling` into `read_model_meta_fast` (from kv).
- [x] 1.5 Wire `sampling` into `read_model_meta` (from fields).
- [x] 1.6 Fix `build_command`: emit model-specific sampling flags when
      `meta["sampling"]` non-empty, else fall back to the `SAMPLING` preset;
      each flag and value as a SEPARATE argv element; never duplicate.

## Tests

- [x] 2.1 `test_build_command_uses_model_sampling_when_present` — model defaults
      emitted, preset values absent, flag/value adjacent.
- [x] 2.2 `test_build_command_falls_back_to_preset_when_no_sampling` — empty
      sampling emits the global preset verbatim.
- [x] 2.3 `test_sampling_flag_map_covers_all_keys` — all five flags present.
- [x] 2.4 `test_extract_sampling_from_kv_picks_present_fields` — parses kv,
      omits absent, never raises.
- [x] 2.5 Verified `read_model_meta`/`read_model_meta_fast` on a REAL gguf
      return `{"sampling": {}}` and the real GGUFReader field path works.

## Verification

- [x] 3.1 `make test-unit` green (18 tests in test_llama_ai.py, incl. new).
- [x] 3.2 `make openspec-validate NAME=llama-serving-sampling-defaults` exit 0.
