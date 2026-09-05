# Tasks: Download the top-tier trending GGUF models that fit your GPU

- [ ] 1. OpenSpec change + issue body created and in sync (proposal.md, spec.md,
      tasks.md written; issue #49 body mirrors this goal). All three describe the
      same `--download-top-tier` objective.
- [ ] 2. `scripts/llama_serve.py` argparse: add `--download-top-tier`, `--count`
      (default 1), and wire `--list`/`--port`/`--dry` to compose with it.
- [ ] 3. Add `discover_top_tier(target_ram_bytes, os_overhead, min_gb, limit)`
      module function (near `scan_models()`/tuning helpers): ranked candidates
      `{repo_id, filename, size_gb, family, rank, tier_folder}` from a time-bounded
      HF trending signal.
- [ ] 4. HF metadata client using the `hf` CLI conventions in `hf_download.py` /
      `download_test_model.py` (resolve `HF_BIN` via `shutil.which("hf")`, transfer
      env, token from `~/.zshrc`); per-file sizes from HF repo tree/siblings. No new
      downloader implementation.
- [ ] 5. Top-tier gate: flagship/large family allow-list + non-trivial quant file
      rule (excludes sub-1B toy quants).
- [ ] 6. Fit + buffer gate (two-stage, model's own metadata): pre-download accept only if
      `size_bytes + OS_OVERHEAD + KV_reserve <= TOTAL_RAM_BYTES` (size from HF per-file
      metadata + family param count); post-download re-derive exact context via
      `read_model_meta_fast()` + `tuned_context()`; reuse launcher `TOTAL_RAM_BYTES`/
      `OS_OVERHEAD`/`KV_QUANT` constants.
- [ ] 7. Download path: delegate to `scripts/hf_download.py` exactly like
      `download_test_model.py`; abort with clear error if `hf` absent. Place into
      provider-aware `~/{MODELS_ROOT}/<owner>/<model-family>/<TierGB>/` (owner = HF repo
      owner who created/quantized it).
- [ ] 8. Serve-after-download: reuse `build_command()` + existing `main()` flow so
      `--download-top-tier` can fetch and serve in one invocation (honor `--port`,
      `--dry`; keep `--alias llm-local`).
- [ ] 9. Hermetic unit tests (`tests/test_llama_ai.py`): stub HF client + `hf` CLI
      (follow existing `LLAMA_MODELS_ROOT` / subprocess-stub conventions); assert
      fit-gate rejects OOM candidates, excludes toy quants, picks the tier folder,
      and calls the downloader with the right `repo_id/filename/dest/label`.
- [ ] 10. README.md: add `--download-top-tier` workflow, the trend/fit/download
      behaviour, and the tier-folder layout entry for downloaded models.
- [ ] 11. Sync PASS: issue body, OpenSpec change (proposal/spec/tasks), and code/files
      are consistent — any drift resolved before push.
- [ ] 12. Verification (tick the moment done): `make openspec-validate
      NAME=feat-download-top-tier-trending-models` exits 0, every task here ticked,
      `make lint` GREEN, `make test-unit` GREEN, and a hosted downloaded model that
      "fits" actually runs via the host/Metal health path.