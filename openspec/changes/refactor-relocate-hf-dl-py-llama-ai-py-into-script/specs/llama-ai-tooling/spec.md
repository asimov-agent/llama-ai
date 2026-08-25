# Spec: Relocation of hf_dl.py + llama_ai.py into scripts/

## Why (rationale)

Two launcher/download utilities sit at the repo root (`hf_dl.py`, `llama_ai.py`)
and are not entrypoints. The repo already has a professional `scripts/` folder,
so relocating them there with clean names improves structure and stops them from
looking like importable top-level modules (tests currently `import llama_ai` via
`sys.path.insert(0, REPO_ROOT)`).

This is a **refactor** — behaviour of the scripts must not change beyond the
path/name updates. The one-code-path / no-fallback rule in AGENTS.md still holds:
the downloader keeps using the official `hf` CLI (via `scripts/hf_download.py`),
and the launcher keeps its exact resolution + venv semantics.

---

## RENAMED Requirements

The following capabilities are **renamed** to new file names under `scripts/`.
Behaviour is preserved; only the location/name changes.

### Requirement: R1 — Relocation + rename
WHEN a user runs `python3 scripts/hf_download.py` OR `python3 scripts/llama_serve.py`,
THEN it behaves identically to the former `hf_dl.py` / `llama_ai.py` (same flags,
same resolution, same venv assumption), only located under `scripts/`.

#### Scenario: The GGUF downloader resumes/retries on connection drop and appends a
`.progress.log` next to the destination — unchanged after relocation.

### Requirement: R1b — Stable alias preserved
WHEN `scripts/llama_serve.py` builds a server command, THEN it includes
`--alias llm-local` so OpenAI-compatible clients pin one endpoint name.

#### Scenario: A client requests `model: llm-local`; the served model keeps that
alias regardless of which GGUF is loaded.

---

## MODIFIED Requirements

The following existing capabilities are **modified** by the relocation (Makefile,
tests, docs, and one helper script reference the old path).

### Requirement: M1 — Makefile install/link/uninstall parity
WHEN `make install` runs, THEN it writes an executable `~/bin/llama-ai` launcher
that execs the script with the venv python (`$(VENV)/bin/python`) and references
the new repo path `$(REPO)/scripts/llama_serve.py`; AND it symlinks
`~/bin/llama_ai.py` → the repo copy (symlink name unchanged; only its target
repoints to `$(REPO)/scripts/llama_serve.py`). WHEN `make uninstall` runs, THEN it
removes `$(LAUNCHER)`, `$(BIN)/llama_ai.py`, and `$(BIN)/llama-server`.

#### Scenario: A fresh host runs `make install`, then `~/bin/llama-ai --list` works;
the launcher body still targets the `llama_ai.py` *name* (user-facing behaviour
unchanged) even though the repo copy now lives at `scripts/llama_serve.py`.

### Requirement: M2 — venv assumption preserved
WHEN the launcher or any documented invocation runs, THEN it uses
`~/llama-gguf-tools/.venv/bin/python` so `gguf`/`numpy` resolve.

#### Scenario: `~/llama-gguf-tools/.venv/bin/python scripts/llama_serve.py --list`
imports gguf cleanly.

### Requirement: M3 — download_test_model.py reference
WHEN the loop's `health` stage downloads the test model, THEN
`scripts/download_test_model.py` shells out to `../scripts/hf_download.py` (not
`../hf_dl.py`) and sets `HF_BIN` from PATH — the same official `hf` CLI + relocated
downloader.

#### Scenario: `make download-test-model` fetches Qwen2.5-0.5B via `hf` through the
new downloader path.

### Requirement: M4 — tests reference the relocated module
WHEN the test suite runs, THEN `conftest.py`, `test_llama_ai.py`, `test_health.py`,
and `test_install.py` import / assert against the relocated `scripts/llama_serve.py`
(and `scripts/hf_download.py` where relevant).

#### Scenario: `make test-unit` runs hermetic unit tests against `scripts/llama_serve`
functions and passes.

### Requirement: M5 — docs sync (README + AGENTS.md)
WHEN the relocation changes a user-facing feature or `make` target, THEN
`README.md` and `AGENTS.md` are mirrored in the same change (table rows, install
steps, download section, layout tree, install/hf_dl notes).

#### Scenario: A reader opens README and sees `scripts/llama_serve.py` +
`scripts/hf_download.py` consistently across all sections.

---

## ADDED Requirements

### Requirement: A1 — Root copies removed
WHEN the relocation completes, THEN the root copies `hf_dl.py` and `llama_ai.py`
are deleted (no orphaned duplicate entrypoints at repo root).

#### Scenario: `git ls-files` no longer lists `hf_dl.py` or `llama_ai.py` at root.

---

## REM Requirements — one code path preserved
WHEN the downloader resolves its CLI, THEN it uses only the official `hf`
(huggingface_hub) CLI via `scripts/hf_download.py` — no `requests`/`urllib` fallback.
WHEN the launcher resolves its server, THEN it uses only PATH / `LLAMA_SERVER` /
`~/bin/llama-server`, terminating with a clear error when absent (no dual path).
