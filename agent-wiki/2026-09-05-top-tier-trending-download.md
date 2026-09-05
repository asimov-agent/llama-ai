# 2026-09-05 top-tier-trending-download

## What
Issue #49: `llama-ai --download-top-tier` finds trending top-tier GGUF models that fit the
actual GPU/CPU card (with KV buffer), downloads them (provider-aware), serves them.

## Implemented (committed on feat/make-the-llama-ai-download-the-top-tier-models-bas)
- `scripts/llama_serve.py`:
  - `read_total_ram_bytes()` dynamic total (sysctl hw.memsize / /proc/meminfo / LLAMA_RAM_BYTES)
  - `read_current_headroom_bytes()` wired+safety, floor=OS_OVERHEAD, cap=45% total
  - `discover_top_tier()` live HF trendingScore (filter=gguf) + top-tier family + fit gate,
    ranks by quality then trend, single-file only (no shards/mmproj)
  - `provider_dest_path()`/`pick_tier_folder()` provider-aware <owner>/<family>/<TierGB>
  - `download_top_tier_candidate()` real hf CLI, idempotent against FULL size (resume partial)
  - `_main_download_top_tier()` + `--download-top-tier/--count` + serve via `_serve_chosen`
- `tests/test_top_tier_acceptance.py` REAL no-mock acceptance (live HF + real hf download)
- pytest.ini `acceptance` marker; Makefile `test-top-tier` target; README section

## Verified for real (no mocks/skips)
- 3 acceptance tests pass: trending query, discover/fit-gate, provider placement.
- 30 hermetic unit tests still pass. Lint green. README synced.
- CPU-only dynamic works: simulate 16GB (LLAMA_RAM_BYTES) -> downshifts to ~12.5GB Q3_K_M.
- REAL 29.3GB top-tier download (unsloth/Qwen3.8-27B Q8_K_XL) in progress to
  ~/models/unsloth/Qwen3.8-27B-GGUF/48GB/ (~6.3MB/s, provider-aware), then serves on :18080.
- Git: feat/make-the-llama-ai-download-the-top-tier-models-bas, rich OpenSpec change
  feat-download-top-tier-trending-models. Duplicate loop scaffold removed.

## Status / next
Download in-flight (host/GPU real proof). Next: let Q8_K_XL finish, run load+"hi"+remaining-RAM
(A6/A8), run openspec-validate + task ticks, open PR referencing #49.