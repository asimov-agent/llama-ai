# tasks

## Task: expose `general.sampling.*` in the GGUF readers
- In `llama_ai.py`, add a sampling-field extraction to both `read_model_meta_fast`
  (header parse) and `read_model_meta` (GGUFReader fields).
- Read these metadata keys as strings: `general.sampling.temperature`,
  `general.sampling.top_p`, `general.sampling.top_k`, `general.sampling.min_p`,
  `general.sampling.repeat_penalty`.
- Store them in a `sampling` dict on the returned meta, keyed by the short name
  (`temperature`, `top_p`, `top_k`, `min_p`, `repeat_penalty`). Omit absent/unparseable.
- Both readers return the same dict shape so callers can rely on one key.

## Task: consume sampling defaults in build_command
- In `llama_ai.py` `build_command`, replace the unconditional `*SAMPLING` spread
  with: emit `--<flag> <value>` per entry in `meta["sampling"]` when non-empty,
  else fall back to the global `SAMPLING` preset.
- Map keys to flags: temperature->--temp, top_p->--top-p, top_k->--top-k,
  min_p->--min-p, repeat_penalty->--repeat-penalty.
- Keep the global `SAMPLING` list as the fallback default (do not remove it).

## Task: add unit tests
- In `tests/test_llama_ai.py`, add a GGUF with `general.sampling.*` fields and assert
  `read_model_meta_fast`/`read_model_meta` return the expected `sampling` dict.
- Add a test that a metadata-free GGUF yields an empty `sampling` dict.
- Add tests for `build_command` asserting model-specific flags are emitted when
  sampling metadata is present, and the preset is emitted when it is empty.

## Task: validate + lint + unit
- Run `make openspec-validate NAME=feat-read-author-recommended-sampling-defaults-fro`.
- Run `make lint-fix` then `make lint` (linefeed + flake8), then `make test-unit`.
