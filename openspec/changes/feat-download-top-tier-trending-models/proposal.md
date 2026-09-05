# Download the top-tier trending GGUF models that fit your GPU

## Context (Why)

Issue #49 asks for the `llama-ai` launcher (`scripts/llama_serve.py`, symlinked as
`~/bin/llama_ai.py`) to be able to **download the top-tier trending llama.cpp GGUF
models** — the currently-popular, high-quality community models — that **fit the
user's GPU**. On a 48 GB Apple Silicon (unified-memory) card this means roughly
30B–40B parameter models at a high quant, sized with a buffer so the KV cache still
fits and the model actually runs after download (not just downloads-then-OOMs).

Today the launcher only *serves locally-present* models (argparse: positional
`model`, `--list`, `--port`, `--dry`). There is a solid downloader
(`scripts/hf_download.py`, official `hf` CLI, resume/retry) and a download precedent
(`scripts/download_test_model.py`), plus a GPU-tier folder layout
(`~/{MODELS_ROOT}/<Family>/<TierGB>/`, e.g. 8/16/24/48 GB). This change adds a
`--download-top-tier` path that discovers **trending + top-tier + GPU-fitting**
GGUF models, downloads the chosen one(s) into the right tier folder, and can serve
them — explicitly **not** the low/toy-tier models.

## Change (What Changes)

New launcher interface (all compatible with existing flags):

```
llama-ai --download-top-tier                # interactive: show top-tier models that fit, pick one
llama-ai --download-top-tier --list         # list what would be top-tier + would fit (no download)
llama-ai --download-top-tier <N>            # non-interactive: download the Nth ranked candidate
llama-ai --download-top-tier --count 5      # download the top 5 that fit
```

- **Trending rank**: time-bounded HF signal (trending score / recent downloads on
  official or community quant repos). Evaluated concretely in `design.md` via the
  `huggingface_hub` API (`HfApi.list_models(sort=..., direction=-1)`, `trendingScore`,
  repo `tree`/`siblings` per-file sizes).
- **Top-tier gate**: candidate must be a flagship/large popular family (Qwen3,
  DeepSeek-R1 distill, Mistral Small/Large, Llama 3.3, Gemma 3, gpt-oss, Phi, QwQ,
  etc.) and its chosen quant file must be non-trivial (excludes sub-1B toy quants).
- **Fit + buffer gate (dynamic), from the model's own metadata (two stages)**: the
  real total is read at runtime from the card (`sysctl hw.memsize`, `LLAMA_RAM_BYTES`
  override) with current-pressure headroom (`vm_stat`) — NOT hardcoded. Pre-download:
  HF repo per-file `size` + family parameter count must satisfy
  `size_bytes + headroom + KV_reserve <= read_total_ram()`; post-download:
  `read_model_meta_fast()` + `tuned_context()` re-derive the exact context. Reuse
  `KV_QUANT`/`kv_bytes_per_token()` as the single fit implementation.
- **Download**: delegate to the existing `scripts/hf_download.py` exactly like
  `download_test_model.py` (resolve `HF_BIN` via `shutil.which("hf")`, set
  `HF_HUB_ENABLE_HF_TRANSFER=1`, read `HF_TOKEN` from `~/.zshrc`); abort if `hf`
  absent (no fallback downloader — one code path).
- **Destination/tier folder (provider-aware)**: `~/{MODELS_ROOT}/<owner>/<model-family>/<TierGB>/`
  where `<owner>` is the HF repo owner who created/quantized the model (e.g. `unsloth`,
  `OBLITERATUS`), so provenance is clear; `<TierGB>` is the computed fitting tier
  (8/16/24/48). `scan_models()` (os.walk at any depth) sees the file immediately.
- **Serve after download**: reuse `build_command()` + the existing `main()` flow so
  `--download-top-tier` can fetch and serve in one invocation.

## Verification

- `make openspec-validate NAME=feat-download-top-tier-trending-models` exits 0; all
  `tasks.md` items ticked.
- `make lint` (linefeed) GREEN — every tracked file ends with a trailing newline.
- `make test-unit` GREEN — hermetic unit tests (stubbed HF client + `hf` CLI) assert
  the fit-gate excludes OOM candidates, low/toy quants are excluded, and the fit is
  **dynamic** (reads real RAM at runtime, e.g. `sysctl hw.memsize`).
- Download-placement acceptance (A7): hermetic tests assert the exact filesystem result —
  file at the provider-aware tier path, complete size (== HF `size`, no `.part`/
  `.incomplete`), `.progress.log` present, `--list` sees it, idempotent re-run, tier
  correctness (no cross-tier contamination).
- **Real** host/GPU proof (A6+A8): actually download the top-tier pick via `hf` if absent,
  load it on Metal with a dynamic RAM read, answer "hi", re-measure post-load RAM to prove
  headroom. On a GPU-less CI runner, download/load the top-tier quant that fits the runner's
  CPU/RAM in the container and verify on CPU. Skip-with-reason if the pick would exceed the
  card — never a silent OOM.
- README updated in the same change (new flag + download workflow + layout).

## Sync rule

Per AGENTS.md, this issue IS the root work item; it is mirrored 1:1 by this OpenSpec
change (same goal in `proposal.md`, same interface/behaviour in `spec.md`, same steps
in `tasks.md`). Any edit to one is applied to the others and to the code in the same
commit batch. The PR that closes issue #49 references it.