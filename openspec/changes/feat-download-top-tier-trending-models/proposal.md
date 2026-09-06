# Download the top-tier trending GGUF models that fit your GPU

## Context (Why)

LLMs trend fast. The launcher (`scripts/llama_serve.py`, symlinked as `~/bin/llama-ai`)
today only *serves locally-present* models. Users want `--download-top-tier`: fetch the
**currently-trending, top-tier** GGUF models (HF community quants, e.g. Qwen3/DeepSeek/
Mistral/Llama/Gemma/gpt-oss/Phi/QwQ/GLM) that **fit the actual GPU/CPU card** with KV
headroom, then serve them. Explicitly the opposite of a low-tier picker.

Reuses existing building blocks: `hf`-CLI downloader (`scripts/hf_download.py`), tiered
`~/models` layout, launcher fit/KV math. One code path, no fallback downloader.

## Change

```
llama-ai --download-top-tier                # download top-5 PROVIDERS x 2 quants (high + lower) — DOWNLOAD ONLY
llama-ai --download-top-tier --list         # list what fits (no download)
llama-ai --download-top-tier --count N      # download N providers' high + lower quants
llama-ai --download-top-tier --per-provider N  # quants per provider (default 2 = high + lower)
llama-ai --download-top-tier --min-trending-score N  # rating floor (only well-rated)
llama-ai --download-top-tier --dry          # preview only
```

**Selection = three gates.**
- **Trending**: time-bounded HF `trendingScore` (`filter=gguf`); not lifetime downloads.
- **Top-tier**: flagship-family allow-list (`TOP_TIER_FAMILIES`: Qwen3, DeepSeek, Mistral, Llama,
  Gemma, gpt-oss, Phi, QwQ, GLM, Olmo + trending additions Ornith/Qwopus/Qwythos/Tiel-Coder/
  MiniMax/K2 so popular trending LLMs aren't dropped) + non-trivial quant (no sub-1B toys, no
  multi-file shards, no vision projectors) AND **drops low-fidelity IQ1/IQ2/IQ3 quants** (an
  8-11 GB 27B is poor quality) AND **drops MTP/mtp-* companion heads** (multi-token-prediction
  aux files, not the serviceable model). Still excludes non-LLM repos (TTS, image/audio encoders).
- **Fits (dynamic)**: total RAM read at runtime from the real card
  (`sysctl hw.memsize`/`/proc/meminfo`/`LLAMA_RAM_BYTES`), headroom from `vm_stat`
  (floor 3 GB, cap 45%). Accept iff `size_bytes + headroom + KV_reserve <= read_total_ram()`,
  using launcher's `KV_QUANT`/`kv_bytes_per_token()`/`tuned_context()`.

**How many / how rated**: `--count N` (**default 5**) = number of **distinct providers**; each
yields `--per-provider` (**default 2**) quants — the best HIGH (Q8) plus a clearly-LOWER
(~25% smaller, Q4/Q5/Q6). So `--count 5` ⇒ up to 10 models (5 high + 5 lower). **Ranking is
trending-first** (providers ordered by `trendingScore` desc, most popular now first — NOT by file
size); `--min-trending-score N` (default 0) is a rating floor.

**Download**: delegate to `scripts/hf_download.py` (resolve `HF_BIN`, transfer env, token from
`~/.zshrc`; abort if `hf` absent). Uses **hf-xet** for chunked parallel transfer and shows a live
**0-100%** progress readout of the CURRENT file (size, MB/s, elapsed) on the terminal + `.progress.log`
(resets to 0% per model). In `refresh=1` mode it always etag-checks the Hub — so an upstream file
updated **even same name + same size** is re-fetched, and a corrupted local copy is restored (never
masked by a size/name guard). The batch is **resilient**: a failing provider is retried up to 3×
without aborting the batch, and completed downloads are never re-fetched (idempotent).

**Placement / metadata-verify / serve**: down to `~/models/<owner>/<family>/<TierGB>/<file>.gguf`
(owner = HF repo owner; tier 8/16/24/48), `scan_models()` sees it immediately. After download the
file is **verified by its GGUF metadata** (`read_model_meta_fast` + full-reader fallback) — a
non-GGUF/corrupt/HTML file is rejected, not trusted by filename+size. `--download-top-tier` is
**DOWNLOAD-ONLY — it never auto-starts llama-server**; serving a downloaded model is a separate
explicit command (`llama-ai <name>`), which reuses `build_command()` (`--alias llm-local`,
`--port`, `--dry`). A dedicated `test_top_tier_serve.py` proves a downloaded model loads, answers
"hi", and leaves RAM headroom.

## Verification
- `make lint`, `make test-unit` GREEN (hermetic: fit-gate OOM/toy exclusion, dynamic read,
  placement, downloader invocation, metadata-verify, openspec-tasks-check).
- **NO-SKIP harness**: every test runs and passes — a skip is a red exit (conftest guard);
  `make test-install-ci` (REAL `make install` + model seed, ONE container, 7 tests run) and
  `make test-unit` (ALL python test files incl. the folded-in `test_check_openspec_tasks.py`)
  are GREEN in CI. AGENTS.md carries the durable "NO SKIPPED TESTS" rule.
- `make test-top-tier` GREEN — real, no-mock acceptance: live HF query + dynamic fit-gate +
  provider placement + real download (idempotent) + same-size-corruption → restored refresh test.
- `make test-top-tier-serve` GREEN — downloads a **lightweight** top-tier model for real, loads
  llama-server, waits /health, POSTs "hi" (asserts reply), re-measures RAM for headroom. Runs on
  local (GPU/CPU) and in CI (`test-top-tier-serve-ci`).
- Real host/GPU proof (AGENTS.md): a downloaded top-tier model loads on Metal, `/health`, POST
  "hi", post-load RAM shows headroom not exhausted; CI cpu-health covers the CPU path.
- README mirrors the flag/workflow/layout; issue + OpenSpec stay in sync (AGENTS.md).
