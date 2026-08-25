# feat — read author-recommended sampling defaults from GGUF metadata

## ADDED Requirements

### Requirement: GGUF reader exposes `general.sampling.*` as a `sampling` dict
Both metadata readers in `llama_ai.py` (`read_model_meta_fast` and
`read_model_meta`) MUST populate the returned meta dict with a `sampling` key that
captures the author-recommended sampling defaults published under the
`general.sampling.*` GGUF metadata namespace.

For each known sampling field, the reader MUST read the value from metadata and
store it as a string in the `sampling` dict:

- `general.sampling.temperature` -> `"temperature"`
- `general.sampling.top_p`       -> `"top_p"`
- `general.sampling.top_k`       -> `"top_k"`
- `general.sampling.min_p`       -> `"min_p"`
- `general.sampling.repeat_penalty` -> `"repeat_penalty"`

A field is omitted from the `sampling` dict when it is absent OR unparseable
(string form of the scalar is empty). Missing fields must never raise.

#### Scenario: sampling metadata captured by fast reader
- **WHEN** `read_model_meta_fast` reads a GGUF whose header contains
  `general.sampling.temperature = 0.7` and `general.sampling.top_p = 0.95`
- **THEN** the returned dict contains `sampling == {"temperature": "0.7",
  "top_p": "0.95"}`

#### Scenario: sampling metadata captured by full reader
- **WHEN** `read_model_meta` reads a GGUF whose fields include
  `general.sampling.min_p = 0.03` and `general.sampling.top_k = 50`
- **THEN** the returned dict contains `sampling == {"min_p": "0.03", "top_k": "50"}`

#### Scenario: absent sampling metadata yields no sampling key
- **WHEN** a GGUF has neither `general.sampling.*` field present nor parseable
- **THEN** the returned dict has an empty `sampling` key (`{}`) so the command
  builder falls back to the preset.

## CHANGED Requirements

### Requirement: build_command uses model-specific sampling defaults first
The command builder `build_command` in `llama_ai.py` MUST use the per-model
`sampling` dict from `meta["sampling"]` as the sampling flags, appended in the
same position the global preset previously occupied.

- When `meta["sampling"]` is non-empty, the builder MUST emit one flag per entry:
  `--<key> <value>` for each key/value pair, in insertion order.
- When `meta["sampling"]` is empty (model supplies no author-recommended defaults),
  the builder MUST fall back to the existing global `SAMPLING` preset so behaviour
  for metadata-free models is unchanged.

#### Scenario: model supplies sampling defaults
- **WHEN** `build_command` builds a command for a meta whose `sampling` is
  `{"temperature": "0.7", "top_p": "0.95"}`
- **THEN** the emitted flags are `--temp 0.7 --top-p 0.95` (see mapping below)
  and NOT the default preset's `--temp 0.6`.

#### Scenario: metadata-free model falls back to preset
- **WHEN** `build_command` builds a command for a meta whose `sampling` is `{}`
- **THEN** the emitted sampling flags are exactly the global `SAMPLING` preset.

### Requirement: sampling flag mapping
The builder MUST map each `sampling` dict key to its `llama-server` flag name:

- `temperature`  -> `--temp`
- `top_p`        -> `--top-p`
- `top_k`        -> `--top-k`
- `min_p`        -> `--min-p`
- `repeat_penalty` -> `--repeat-penalty`

#### Scenario: keys map to correct flags
- **WHEN** `sampling` contains all five keys
- **THEN** the emitted flags are `--temp --top-p --top-k --min-p --repeat-penalty`
  in that order.
