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
- [ ] 6. Fit + buffer gate (two-stage, model's own metadata, **dynamic**): pre-download
      accept only if `size_bytes + headroom + KV_reserve <= read_total_ram()` where
      `read_total_ram()` reads the actual card (`sysctl hw.memsize`, `LLAMA_RAM_BYTES`
      override) and headroom comes from current pressure (`vm_stat`), NOT hardcoded
      constants; post-download re-derive exact context via `read_model_meta_fast()` +
      `tuned_context()`. Reuse `KV_QUANT`/`kv_bytes_per_token()` as the single fit
      implementation.
- [ ] 7. Download path: delegate to `scripts/hf_download.py` exactly like
      `download_test_model.py`; abort with clear error if `hf` absent. Place into
      provider-aware `~/{MODELS_ROOT}/<owner>/<model-family>/<TierGB>/` (owner = HF repo
      owner who created/quantized it).
- [ ] 8. Serve-after-download: reuse `build_command()` + existing `main()` flow so
      `--download-top-tier` can fetch and serve in one invocation (honor `--port`,
      `--dry`; keep `--alias llm-local`).
- [ ] 9. Hermetic unit tests (`tests/test_llama_ai.py`): stub HF client + `hf` CLI
      (follow existing `LLAMA_MODELS_ROOT` / subprocess-stub conventions); assert
      fit-gate rejects OOM candidates, excludes toy quants, and is **dynamic**
      (reads real RAM from `sysctl hw.memsize`, rejects models that exceed the 
      *actual* total), picks the tier folder, and calls the downloader with the right
      `repo_id/filename/dest/label`.
- [ ] 9b. Download-logic placement acceptance tests (A7): hermetic tests assert the
      **exact filesystem result** — file at `~/{MODELS_ROOT}/<owner>/<family>/<TierGB>/`,
      complete size (== HF size, no `.incomplete`/`.part`), `.progress.log` present,
      `llama-ai --list` sees it, re-run is idempotent (no re-download), and different
      size-fits land in different tier folders (no cross-tier contamination).
- [ ] 9c. Real top-tier download + dynamic host/CI verification (A6+A8): a test that
      **actually downloads** the chosen top-tier model via the real `hf`/`hf_download.py`
      if absent (idempotent), then reads RAM (`sysctl hw.memsize` + `vm_stat`) before load,
      loads it on Metal if the host GPU is enabled (AGENTS.md), or on **CPU** in the test
      container on a GPU-less CI runner using a top-tier quant that fits the runner's RAM;
      waits for `/health`, POSTs "hi", asserts a reply, and re-measures post-load available
      memory to prove real headroom remained (fail + report before/after numbers if not).
- [ ] 9d. Wire the A6/A8 verification into the loop harness (`scripts/loop_harness.py` /
      Makefile) as a `test-top-tier` stage that selects the dynamic target per environment
      (host GPU vs CI CPU) and skips-with-reason if the pick would exceed the available card.
- [ ] 10. README.md: add `--download-top-tier` workflow, the trend/fit/download
      behaviour, and the tier-folder layout entry for downloaded models.
- [ ] 11. Sync PASS: issue body, OpenSpec change (proposal/spec/tasks), and code/files
      are consistent — any drift resolved before push.
- [ ] 12. Verification (tick the moment done): `make openspec-validate
      NAME=feat-download-top-tier-trending-models` exits 0, every task here ticked,
      `make lint` GREEN, `make test-unit` GREEN, download-placement tests
      (A7) all pass, and a **real** top-tier download + dynamic load + "hi" +
      remaining-RAM check (A6+A8) runs on the host/GPU and on the CI/CPU path.
