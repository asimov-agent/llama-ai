# llama-ai-tooling — Tasks

Checklist of record. Each implement step is ticked (`- [x]`) the moment it is
verified. The final task is a verification, ticked only when everything passes.

## Install & launcher

- [x] 1.1 Make `llama_ai.py` resolve `llama-server` from `PATH` (with `LLAMA_SERVER`
      env override), and terminate with a clear error + non-zero exit if missing
- [x] 1.2 Add a root Makefile `install` target that builds the gguf venv, writes
      `~/bin/llama-ai`, symlinks `~/bin/llama_ai.py` and `~/bin/llama-server`
- [x] 1.3 Add `uninstall` (removes launcher + symlinks, keeps venv)
- [x] 1.4 Remove any hardcoded llama-server path dependency; use PATH resolution

## Test suite

- [x] 2.1 Add `tests/` pytest suite (unit tests for llama_ai.py + install host test)
- [x] 2.2 Add `tools/requirements-dev.in`/`.txt` (pytest) and `venv-dev-install` /
      `generate-requirements-dev` targets
- [x] 2.3 Make `make test-unit` green under the venv python (13 passed)
- [x] 2.4 Make `make test-install` green (installed `~/bin/llama-ai` runs a host model; 7 passed)

## Loop harness

- [x] 3.1 Write `scripts/loop_harness.py` (basic loop runner)
- [x] 3.2 Wire `make loop` / `make loop-harness` to run tests + openspec validate
- [x] 3.3 Confirm a green loop passes (unit/install/test/openspec all PASS, RESULT GREEN) and
      a failing stage fails closed (per-stage FAIL + non-zero exit)

## OpenSpec Dockerized CLI

- [x] 4.1 Add `openspec/Dockerfile` (node:22-alpine + @fission-ai/openspec)
- [x] 4.2 Add `docker-compose-files/openspec.yaml`
- [x] 4.3 Add Makefile `openspec-image|new|validate|status|shell` targets
- [x] 4.4 Create this change via `make openspec-new NAME=llama-ai-tooling` (CLI)
- [x] 4.5 Write proposal.md + specs/<cap>/spec.md + this tasks.md

## AGENTS.md

- [x] 5.1 Author AGENTS.md documenting the OpenSpec-driven agent workflow
      (record steps in tasks.md, run loop before claiming done)

## Verification (final)

- [x] 6.1 `make openspec-validate NAME=llama-ai-tooling` passes (verified in the loop)
- [x] 6.2 Full loop green (unit/install/test/openspec all PASS) and repo committed on branch `main` (bd92f23)
