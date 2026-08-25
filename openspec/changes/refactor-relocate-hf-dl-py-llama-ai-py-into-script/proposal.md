# Relocate hf_dl.py + llama_ai.py into scripts/ with clean naming

## Context (Why)

Two launcher/download utility scripts currently sit at the **repo root**:
`hf_dl.py` (Hugging Face GGUF downloader with resume/retry) and `llama_ai.py`
(GGUF model launcher + llama-server auto-tuner). They are launcher/download
utilities, not entrypoints, and the repo already has a professional `scripts/`
folder for such things. Placing them at root muddies the repo's structure and
makes them look like importable top-level modules (the tests already
`sys.path.insert(0, REPO_ROOT)` and `import llama_ai`, which is a smell).

The goal is to move them into an organised `scripts/` location with **clear,
conventional names**, and update every reference so nothing breaks. This is a
**refactor only** — behaviour of the scripts themselves must not change beyond
the path/name updates.

## Change (What Changes)

### Relocation + rename (exact names per issue #15)

| Old (repo root) | New (scripts/) | Purpose |
|---|---|---|
| `hf_dl.py` | `scripts/hf_download.py` | Hugging Face GGUF download with resume/retry |
| `llama_ai.py` | `scripts/llama_serve.py` | llama.cpp launcher + auto-tuner (stable alias `llm-local`) |

- Delete the root copies after moving.
- The new files keep their full behaviour; only the docstring/usage location
  references change to point at the new path/name.

### Behaviour preserved (the contract — see spec)

The user-facing launcher/symlink names **stay the same** even though the repo
copy moves:

- `make install` still writes an executable `~/bin/llama-ai` that execs the
  script **with the venv python** (`~/llama-gguf-tools/.venv/bin/python`).
- `make install` still symlinks `~/bin/llama_ai.py` → the repo copy. **The
  symlink *name* is unchanged**; only its target repoints from `$(REPO)/
  llama_ai.py` to `$(REPO)/scripts/llama_serve.py`.
- The venv assumption (`~/llama-gguf-tools/.venv/bin/python`) is preserved.

### References that must be updated (refactor all references so nothing breaks)

1. **Makefile** — the `install` target's launcher-writing `printf` (references
   `$(REPO)/llama_ai.py`), the `ln -sfn` symlink (`$(BIN)/llama_ai.py` →
   `$(REPO)/llama_ai.py`), the `install` echo, the `uninstall` removal list, and
   the `test-unit`/`test` targets that name `tests/test_llama_ai.py`.
2. **tests/** — `conftest.py` (`import llama_ai` via `sys.path` + repo-root
   comment), `test_llama_ai.py` (`import llama_ai`), `test_health.py` (repo
   `llama_ai.py` fallback argv), `test_install.py` (launcher text asserts
   `"llama_ai.py"`, symlink path, `$(REPO_ROOT)/llama_ai.py` read).
3. **docs** — `README.md` (table + install + download + layout sections),
   `AGENTS.md` (install target + hf_dl note).

### download_test_model.py — no change required

`scripts/download_test_model.py` shells out to a **relative** path
(`../hf_dl.py`) and sets `HF_BIN` from PATH. After the move it must point at
`../scripts/hf_download.py`. Update this single reference so the `health` stage
downloads through the same official `hf` CLI + the relocated downloader.

## Verification

- `make openspec-validate NAME=refactor-relocate-hf-dl-py-llama-ai-py-into-script`
  must exit 0.
- `make lint` (linefeed — fail closed on any tracked file missing a trailing
  newline).
- `make test-unit` — hermetic unit tests (`tests/test_llama_ai.py`) pass against
  the relocated `scripts/llama_serve.py`.

## Sync rule

This change is a pure refactor: no new behaviour. The issue, OpenSpec change,
and code/files must stay in sync — every reference update is reflected in the
tasks checklist.
