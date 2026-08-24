# llama-ai Tooling OpenSpec Change

## Why

`llama-ai` is a standalone repo that serves GGUF models via llama.cpp's
`llama-server` and provides a Python launcher (`llama_ai.py`), a Hugging Face
downloader (`hf_dl.py`), and a recreatable Python 3.10 gguf venv (`tools/`).
The goal of this change is to make the tooling **installable and testable from
the repo** and to introduce **OpenSpec change tracking** as the checklist of
record for all agent work in this repository.

## What Changes

- `llama_ai.py` resolves `llama-server` from PATH (or `LLAMA_SERVER` env), and
  terminates with a clear error if the binary is missing.
- Root `Makefile` adds `make install` (venv + `~/bin/llama-ai` launcher +
  `~/bin/llama-server` symlink + smoke), `make test`, `make loop`, and
  Dockerized OpenSpec targets (`make openspec-*`).
- `tools/` gains dev/test dependencies (`requirements-dev.in/.txt`) with
  `pip-compile` regeneration (`make -C tools generate-requirements[-dev]`).
- A pytest suite (`tests/`) exercises `llama_ai.py` unit logic, the `make
  install`→`~/bin/llama-ai` host flow, and is run by the loop harness.
- `scripts/loop_harness.py` is a basic loop runner that verifies tests +
  OpenSpec validation + install in a fixed order.
- `openspec/` container + `docker-compose-files/openspec.yaml` run the official
  `@fission-ai/openspec` CLI inside a container with the repo mounted.

## Capabilities

- **install**: one-command install from the repo (venv + launcher + symlinks).
- **test**: unit + host-install pytest suite, runnable via `make test`.
- **loop**: basic loop harness + Dockerized OpenSpec CLI + AGENTS.md tracking.

## Impact

No impact on downstream consumers of the obsidian-timestamp-utility repo; this
change is self-contained to the `llama-ai` repository.