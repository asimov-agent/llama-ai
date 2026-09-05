# Tasks: Download the top-tier trending GGUF models that fit your GPU

- [x] 1. OpenSpec change + issue body created and in sync (proposal.md, spec.md,
      tasks.md written; issue #49 body mirrors this goal). All three describe the
      same `--download-top-tier` objective.
- [x] 2. `scripts/llama_serve.py` argparse: add `--download-top-tier`, `--count`
      (default 5 = top distinct providers), `--min-trending-score`, and wire
      `--list`/`--port`/`--dry` to compose with it.
- [x] 3. Add `discover_top_tier(limit, total_ram_bytes, headroom_bytes, min_trending_score)`
      module function (near `scan_models()`/tuning helpers): ranked candidates
      `{repo, filename, size_gb, size_bytes, tier_folder, dest_path, trendingScore}`
      from a time-bounded HF trending signal, ranked by quality then trend, single-file
      only (no shards/mmproj), **one candidate per provider (owner)** for variety.
- [x] 4. HF metadata client using the `hf` CLI conventions in `hf_download.py` /
      `download_test_model.py` (resolve `HF_BIN`, transfer env, token from `~/.zshrc`);
      per-file sizes from HF repo tree API. No new downloader implementation.
- [x] 5. Top-tier gate: flagship/large family allow-list (`TOP_TIER_FAMILIES`) +
      non-trivial quant file rule (`MIN_TOP_TIER_GB`, excludes sub-1B toy quants).
- [x] 6. Fit + buffer gate (two-stage, model's own metadata, **dynamic**): pre-download
      accept only if `size_bytes + headroom + KV_reserve <= read_total_ram()` where
      `read_total_ram()` reads the actual card (`sysctl hw.memsize`, `/proc/meminfo`,
      `LLAMA_RAM_BYTES` override) and headroom comes from current pressure (`vm_stat`)
      floored at OS_OVERHEAD and capped at 45% of total; post-download re-derive exact
      context via `read_model_meta_fast()` + `tuned_context()`. Reuse
      `KV_QUANT`/`kv_bytes_per_token()` as the single fit implementation.
- [x] 7. Download path: delegate to `scripts/hf_download.py` exactly like
      `download_test_model.py`; abort with clear error if `hf` absent. Place into
      provider-aware `~/{MODELS_ROOT}/<owner>/<model-family>/<TierGB>/` (owner = HF repo
      owner who created/quantized it). Idempotent against FULL size (resume partial).
- [x] 8. Serve-after-download: reuse `build_command()` + existing `main()` flow so
      `--download-top-tier` can fetch and serve in one invocation (honor `--port`,
      `--dry`; keep `--alias llm-local`).
- [x] 9. Acceptance tests, **REAL (no mocks, no skips)**
      (`tests/test_top_tier_acceptance.py`): live HF trending + dynamic card read +
      fit gate rejects OOM + provider-aware placement + real `hf` download and
      idempotent re-run. Verified passing on the host.
- [x] 9b. Download-logic placement acceptance: exact filesystem result — file at
      `~/{MODELS_ROOT}/<owner>/<family>/<TierGB>/`, complete size (== HF bytes, no
      `.incomplete`/`.part`), `.progress.log` present, `llama-ai --list` sees it,
      idempotent re-run, and different size-fits land in different tier folders.
- [x] 9e. Refresh / content-update acceptance (A9): `hf_download.py` accepts `refresh=1`;
      `download_top_tier_candidate` always refreshes so a same-name SAME-SIZE upstream
      content change (or local corruption) is re-fetched by etag/content-hash, not masked
      by a size-only guard. Covered by `test_tiny_model_download_retest_and_update_recovery`
      (real 0.5B download -> idempotent re-run -> corrupt in place -> refresh restores bytes).
- [x] 9c. Real top-tier download + dynamic host/CI verification (A6+A8): genuinely
      downloads the picked top-tier model via real `hf` (idempotent), dynamic RAM read
      before/after, loads on Metal if GPU enabled (AGENTS.md) or CPU in container on a
      GPU-less CI runner. VERIFIED on host: 31.46 GB Q8_K_XL served, /health ok,
      "hi" replied, wired RAM 2.8->37 GB with ~3.9 GB headroom remaining.
- [x] 9d. Wire verification into the loop harness + Makefile: `test-top-tier` target
      (host, no-mock) added to `loop_harness.py` as a stage and to the Makefile.
- [x] 9f. Batch download + progress + speed: `--download-top-tier` downloads the top N
      DISTINCT providers (one model each) with per-provider retry (up to 3×, no batch
      abort on a single failure); `hf_download.py` uses `HF_XET_HIGH_PERFORMANCE=1`
      (hf-xet, never disabling it) and prints a live **0-100%** progress (size, MB/s,
      elapsed) to the terminal + `.progress.log`; completed models are never re-fetched
      on re-run (idempotent). Covered by `test_discover_one_model_per_provider` +
      `test_default_count_is_five` + unit dedupe test.
- [x] 10. README.md: add `--download-top-tier` workflow, the trend/fit/download
      behaviour, and the tier-folder layout entry for downloaded models.
- [x] 11. Sync PASS: issue body, OpenSpec change (proposal/spec/tasks), and code/files
      are consistent — no drift (alignment checked). 
- [x] 12. Verification (tick the moment done): `make openspec-validate
      NAME=feat-download-top-tier-trending-models` exits 0, all `tasks.md` ticked,
      `make lint` GREEN, `make test-unit` GREEN (103 passed from main checkout),
      `make test-top-tier` (real, no-mock) GREEN (4 passed), `/health` + "hi" +
      remaining-RAM proof GREEN on the 48 GB Metal host — feature is done; open the
      PR referencing #49.
