# llama-ai Tooling — spec of record

The capabilities this change adds to the `llama-ai` repository.

## ADDED Requirements

### Requirement: PATH-based llama-server resolution
The system MUST resolve the llama.cpp `llama-server` binary from the `LLAMA_SERVER`
environment variable (if set and executable) or from the user's PATH as
`llama-server`, and MUST terminate with a clear, actionable error message and
non-zero exit when no executable binary can be found.

#### Scenario: server found on PATH
- **WHEN** `llama_ai.py` runs and an executable `llama-server` is on the user's PATH
- **THEN** the launcher resolves and uses that binary to build the server command

#### Scenario: server missing
- **WHEN** `llama_ai.py` runs and no executable `llama-server` is on PATH and
  `LLAMA_SERVER` is unset
- **THEN** the launcher terminates with exit code 1 and prints a message explaining
  how to make `llama-server` available (symlink or `LLAMA_SERVER`)

### Requirement: one-command install into ~/bin
The system MUST provide a `make install` target that creates the gguf venv,
installs an executable `~/bin/llama-ai` launcher that runs `llama_ai.py` with the
venv's Python, symlinks `~/bin/llama_ai.py` to the repo copy, symlinks
`~/bin/llama-server` to the llama.cpp binary, and runs a smoke test.

#### Scenario: install produces a runnable launcher
- **WHEN** `make install` completes successfully
- **THEN** `~/bin/llama-ai` exists, is executable, and `~/bin/llama-ai --list`
  returns a non-zero-exit listing of models (or a clear empty result)

### Requirement: runnable test suite
The system MUST provide a pytest test suite that (a) unit-tests `llama_ai.py`
logic hermetically and (b) verifies the `make install` host flow, and MUST expose
it through `make test`.

#### Scenario: unit tests
- **WHEN** `make test-unit` runs
- **THEN** the hermetic unit tests for `llama_ai.py` pass without launching a server

#### Scenario: install test on a host with models
- **WHEN** `make test-install` runs on a host that has `~/models` populated and
  the `make install` artifacts in `~/bin`
- **THEN** the installed `~/bin/llama-ai` launcher runs and lists at least one model

### Requirement: basic loop harness
The system MUST provide a loop harness (`make loop` / `scripts/loop_harness.py`)
that runs verification in a fixed order and fails closed if any step fails.

#### Scenario: green loop
- **WHEN** `make loop` runs and every stage passes
- **THEN** the harness reports PASS per stage and exits 0

#### Scenario: failing stage fails the loop
- **WHEN** `make loop` runs and any stage fails
- **THEN** the harness reports FAIL for that stage and exits non-zero

### Requirement: Dockerized OpenSpec CLI
The system MUST provide an OpenSpec CLI container (`openspec/` Dockerfile +
`docker-compose-files/openspec.yaml`) and Makefile targets (`make openspec-image`,
`make openspec-new`, `make openspec-validate`, `make openspec-status`) so OpenSpec
changes are created and validated through the CLI with the repo mounted.

#### Scenario: create and validate a change
- **WHEN** `make openspec-new NAME=<name>` then `make openspec-validate NAME=<name>`
  run with a valid change present
- **THEN** the CLI creates `openspec/changes/<name>/` and `openspec validate <name>`
  exits 0

### Requirement: AGENTS.md agent-work tracking
The system MUST ship an AGENTS.md that instructs the agent to record every
implemented step as an OpenSpec change task (tasks.md checklist) and to run the
loop harness before declaring work complete.

#### Scenario: agent records steps in tasks.md
- **WHEN** the agent implements a step of an OpenSpec change
- **THEN** it ticks the corresponding `- [ ]` task in `openspec/changes/<name>/tasks.md`
  and the change validates before completion is claimed