# Tasks: Relocate hf_dl.py + llama_ai.py into scripts/

- [ ] 1. Relocate files: `hf_dl.py` → `scripts/hf_download.py`, `llama_ai.py` →
      `scripts/llama_serve.py`. Delete root copies. Preserve behaviour; update
      docstring/usage location references to new path/name.
- [ ] 2. Makefile: repoint `install` launcher-writing `printf` target to
      `$(REPO)/scripts/llama_serve.py` (keep exec-string target name
      `llama_ai.py`), change symlink target to `$(REPO)/scripts/llama_serve.py`
      (keep `$(BIN)/llama_ai.py` symlink name), update `install` echo + `uninstall`
      removal list.
- [ ] 3. tests/conftest.py: import relocated module `scripts/llama_serve` via
      `sys.path`; keep repo-root fixture.
- [ ] 4. tests/test_llama_ai.py: import `scripts/llama_serve` (all function calls
      resolve); header comment may note the relocation.
- [ ] 5. tests/test_health.py: repo fallback argv points at relocated
      `scripts/llama_serve.py`.
- [ ] 6. tests/test_install.py: launcher-text assert `"llama_ai.py"` still holds
      (exec-string target name kept); symlink path assertion stays `BIN /
      "llama_ai.py"; repo-script read points at relocated file.
- [ ] 7. scripts/download_test_model.py: relative downloader path →
      `../scripts/hf_download.py` (keep `hf` CLI + HF_BIN resolution).
- [ ] 8. README.md: table rows, install steps, download section, layout tree —
      reflect `scripts/llama_serve.py` + `scripts/hf_download.py`.
- [ ] 9. AGENTS.md: install-target note + hf_dl note → relocated names.
- [ ] 10. Sync: ensure issue body, OpenSpec change (proposal/spec/tasks), and
      code/files are consistent (no drift).
- [x] 11. Verification (tick the moment done): `make openspec-validate NAME=
      refactor-relocate-hf-dl-py-llama-ai-py-into-script` exits 0, `make lint`
      GREEN, `make test-unit` GREEN.
