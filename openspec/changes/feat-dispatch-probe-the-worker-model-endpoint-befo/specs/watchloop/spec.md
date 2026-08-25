# feat-dispatch-probe-the-worker-model-endpoint-befo — spec of record

Capabilities this change adds to the watch-loop dispatcher (`scripts/
watchloop_dispatch.py`) and its docs/tests.

## ADDED Requirements

### Requirement: pre-spawn worker-model endpoint probe

Before spawning a worker, when the effective worker provider is *local*
(provider empty, or `localhost`/`custom`/`llama.cpp`, case-insensitive), the
dispatcher MUST probe the model endpoint `http://127.0.0.1:11434/v1/models`
and confirm the effective model id appears in the returned `data[].id` list.
The probe MUST use `127.0.0.1` (not `localhost`, which can resolve to IPv6
`::1` on some host setups) and MUST be isolated/testable (a single
monkeypatchable function; no real network in unit tests).

#### Scenario: local model reachable and listed
- **WHEN** the effective provider is local and
  `GET http://127.0.0.1:11434/v1/models` returns a body whose `data[]`
  contains an entry whose `id` (or `model`) equals the effective worker model
- **THEN** the probe succeeds and the spawn proceeds exactly as before

#### Scenario: local model unreachable (server down)
- **WHEN** the effective provider is local and the endpoint is unreachable
  (connection refused / timeout / non-JSON body / HTTP error)
- **THEN** the probe fails closed and `spawn_worker` returns without spawning
- **AND** the dispatcher logs `  issue#N: worker model <M> unreachable on
  http://127.0.0.1:11434/v1/models — skipping spawn`
- **AND** no worker is spawned, no `.running` lock file is created, no prompt
  file is written, and no worktree is created for the issue
- **AND** the tick continues to the next issue (the probe must not throw in a
  way that wedges the whole tick)

#### Scenario: endpoint up but model not listed
- **WHEN** the endpoint responds with JSON `data[]` but no entry's `id`/`model`
  equals the effective worker model
- **THEN** the probe fails closed and the spawn is skipped with the same log
  line and side-effect guarantees as the unreachable case

### Requirement: hosted providers are not probed locally

When the effective worker provider is non-local (e.g. `openrouter`, or any
provider not in the local set and non-empty), the dispatcher MUST keep current
behaviour and MUST NOT probe the local `127.0.0.1:11434` port.

#### Scenario: hosted provider skips the probe
- **WHEN** the effective provider is `openrouter` (or any non-local provider)
- **THEN** no local-port probe is attempted and the spawn proceeds exactly as
  before

### Requirement: probe is unit-testable without network

The probe MUST be implemented as a single module-level function that
`tests/test_watchloop_dispatch.py` can monkeypatch, so the three scenarios
above are covered hermetically with no real HTTP calls.

#### Scenario: tests cover reachable / unreachable / hosted
- **WHEN** `tests/test_watchloop_dispatch.py` runs
- **THEN** it asserts (a) a reachable local model lets spawn proceed, (b) an
  unreachable local model skips spawn cleanly with no lock file created, and
  (c) a hosted provider performs no local probe
- **AND** no test performs a real network call (the probe is stubbed)

### Requirement: docs note the pre-spawn probe

`scripts/worker-model.template`'s local-option block MUST note that the
dispatcher probes `http://127.0.0.1:11434` before spawning workers and skips
cleanly (log + no spawn) when the local server is down.

#### Scenario: template documents the probe
- **WHEN** a reader opens the local (llama.cpp) option block of
  `scripts/worker-model.template`
- **THEN** it sees a note that the dispatcher probes `:11434` before spawning
  and skips cleanly when the server is down
