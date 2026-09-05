# 2026-09-05 top-tier-trending-download

## What
Issue #49: `llama-ai --download-top-tier` finds trending top-tier GGUF models that fit the
actual GPU/CPU card (with KV buffer), downloads them (provider-aware), serves them.

## Implemented (committed on feat/make-the-llama-ai-download-the-top-tier-models-bas)
- `scripts/llama_serve.py`:
  - `read_total_ram_bytes()` dynamic total (sysctl hw.memsize / /proc/meminfo / LLAMA_RAM_BYTES)
  - `read_current_headroom_bytes()` wired+safety, floor=OS_OVERHEAD(3GB), cap=45% total
  - `discover_top_tier()` live HF trendingScore (filter=gguf) + top-tier family + fit gate,
    ranks by quality then trend, single-file only (no shards/mmproj)
  - `provider_dest_path()`/`pick_tier_folder()` provider-aware <owner>/<family>/<TierGB>
  - `download_top_tier_candidate()` real hf CLI, idempotent against FULL size (resume partial)
  - `_main_download_top_tier()` + `--download-top-tier/--count/--dry/--port` + serve `_serve_chosen`
- `tests/test_top_tier_acceptance.py` REAL no-mock acceptance (live HF + real hf download)
- pytest.ini `acceptance` marker; Makefile `test-top-tier` target; README section

## REAL end-to-end proof (host, 48 GB Metal) — completed
Command: `llama-ai --download-top-tier --count 1 --port 18080`
1. Discovered top-tier pick via live HF trending + dynamic fit:
   `unsloth/Qwen3.8-27B-GGUF` -> `Qwen3.8-27B-UD-Q8_K_XL.gguf`.
2. REAL download (73 min @6.5MB/s) -> `~/models/unsloth/Qwen3.8-27B-GGUF/48GB/`.
   Byte-for-byte match vs HF tree size (31,457,991,680 bytes). Provider-aware path OK.
3. Second run: skipped re-download (idempotent, size==expected), served on :18080.
   `llama_server: model loaded`, listening on :18080. /health {"status":"ok"}.
4. POST "hi" -> reply "Hi there! How" . Load proof: wired RAM 2.8GB -> 37GB (model resident),
   FREE+INACTIVE ~3.9GB headroom remained (NOT exhausted).
5. `--list` now shows it: 29.30 GiB /Users/andy/models/unsloth/.../48GB/Q8_K_XL.gguf [ctx=262144].

Also verified: dynamic CPU-only (simulate 16GB -> downshifts to ~12.5GB Q3_K_M);
30 hermetic unit tests pass; lint green; openspec validate passes; README+wiki synced.

## Commander-bug fixed mid-test
`_main_download_top_tier` used bare `Path` but aliased `pathlib.Path as _P` -> NameError on
serve-after-download. Fixed to use `_P` (commit ba3ea88). This surfaced ONLY because the real
end-to-end serve path actually ran.

## Status / next
Implementation + real host proof DONE. Remaining: tick openspec tasks.md, run full `make loop`
(container) + openspec-tasks-check, open PR referencing #49.
