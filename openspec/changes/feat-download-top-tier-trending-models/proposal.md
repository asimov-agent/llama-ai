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
llama-ai --download-top-tier                # download best fit, then serve
llama-ai --download-top-tier --list         # list what fits (no download)
llama-ai --download-top-tier --count N      # download top N, serve best
llama-ai --download-top-tier --dry          # preview only
```

**Selection = three gates.**
- **Trending**: time-bounded HF `trendingScore` (`filter=gguf`); not lifetime downloads.
- **Top-tier**: flagship-family allow-list + non-trivial quant (no sub-1B toys, no multi-file
  shards, no vision projectors).
- **Fits (dynamic)**: total RAM read at runtime from the real card
  (`sysctl hw.memsize`/`/proc/meminfo`/`LLAMA_RAM_BYTES`), headroom from `vm_stat`
  (floor 3 GB, cap 45%). Accept iff `size_bytes + headroom + KV_reserve <= read_total_ram()`,
  using launcher's `KV_QUANT`/`kv_bytes_per_token()`/`tuned_context()`.

**Download**: delegate to `scripts/hf_download.py` (resolve `HF_BIN`, transfer env, token from
`~/.zshrc`; abort if `hf` absent). In `refresh=1` mode it always etag-checks the Hub — so an
upstream file updated **even same name + same size** is re-fetched, and a corrupted local copy is
restored (never masked by a size/name guard).

**Placement / serve**: down to `~/models/<owner>/<family>/<TierGB>/<file>.gguf` (owner = HF repo
owner; tier 8/16/24/48), `scan_models()` sees it immediately; serve reuses `build_command()`
(`--alias llm-local`, `--port`, `--dry`).

## Verification
- `make lint`, `make test-unit` GREEN (103 hermetic: fit-gate OOM/toy exclusion, dynamic read,
  placement, downloader invocation).
- `make test-top-tier` GREEN — real, no-mock acceptance: live HF query + dynamic fit-gate +
  provider placement + real download (idempotent) + same-size-corruption → restored refresh test.
- Real host/GPU proof (AGENTS.md): a downloaded top-tier model loads on Metal, `/health`, POST
  "hi", post-load RAM shows headroom not exhausted; CI cpu-health covers the CPU path.
- README mirrors the flag/workflow/layout; issue + OpenSpec stay in sync (AGENTS.md).
