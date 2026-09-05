# 2026-09-05 top-tier-trending-download

## What
Issue #49: `llama-ai --download-top-tier` finds trending top-tier GGUF models that fit the
actual GPU/CPU card (with KV buffer), downloads them (provider-aware), serves them.

## Implemented (committed on feat/make-the-llama-ai-download-the-top-tier-models-bas)
- `scripts/llama_serve.py`: `--download-top-tier/--count/--min-trending-score/--dry/--port`;
  dynamic `read_total_ram_bytes()`/`read_current_headroom_bytes()`; `discover_top_tier()`
  (trending + top-tier family + fit gate + rating floor, single-file); provider-aware
  `provider_dest_path()`/`pick_tier_folder()`; `download_top_tier_candidate()` refresh-aware
  (etag, re-fetches same-name/same-size updates, restores corruption); `_serve_chosen()`.
- `scripts/hf_download.py`: optional `refresh` arg ("1" -> always etag-checks the Hub).
- `tests/test_top_tier_acceptance.py`: 5 REAL no-mock tests (Given/When/Then readable).
- `tests/test_llama_ai.py`: hermetic unit test for min_trending_score filter.
- `Makefile`: `test-top-tier` (host) + `test-top-tier-ci` (containerized, deterministic 16GB).
- `.github/workflows/ci.yml`: added `top-tier` job.
- `loop_harness.py`: `top-tier` stage.

## Verified (REAL, no mocks/skips)
- 5 acceptance tests pass (live HF + real hf download + idempotent + same-size corruption restore).
- 20 worktree unit tests + 103 main unit tests pass; lint green; openspec validate valid.
- Authentic host/GPU proof: 31.46GB Q8_K_XL downloaded (byte-for-byte), served, /health ok, "hi"
  replied, wired RAM 2.8->37GB with headroom remaining.
- PR #50: 14/14 CI checks pass (7 jobs x 2 runs incl. top-tier + cpu-health), OPEN, MERGEABLE.

## Count / rating
- `--count N` (default 1): download top N that fit (ranked highest-fidelity then trending).
- `--min-trending-score N` (default 0): only repos with HF trendingScore >= N (rating floor).

## Status / next
PR #50 green + aligned. Waiting on reviewer approval to merge (AGENTS.md gate). Issue #49
condensed to 3.9KB concise spec (goal, acceptance criteria, manual-run + Makefile/CI commands,
files).
