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
- **Fit + buffer gate (reuses the launcher's existing math)**: predicted `size_gb`
  (from HF file metadata) must satisfy `size_bytes + OS_OVERHEAD + kv_budget >= 0`,
  i.e. `size_gb <= TOTAL_RAM_BYTES - OS_OVERHEAD` with the KV-cache allowance
  computed from `kv_bytes_per_token()` × `tuned_context()`. The 48 GB default, 3 GB
  overhead and `KV_QUANT` come from the existing `TOTAL_RAM_BYTES`/`OS_OVERHEAD`
  constants.
- **Download**: delegate to the existing `scripts/hf_download.py` exactly like
  `download_test_model.py` (resolve `HF_BIN` via `shutil.which("hf")`, set
  `HF_HUB_ENABLE_HF_TRANSFER=1`, read `HF_TOKEN` from `~/.zshrc`); abort if `hf`
  absent (no fallback downloader — one code path).
- **Destination/tier folder**: `~/{MODELS_ROOT}/<Family>/<TierGB>/` matching the
  computed fitting tier (8/16/24/48 GB) so `scan_models()` immediately sees it.
- **Serve after download**: reuse `build_command()` + the existing `main()` flow so
  `--download-top-tier` can fetch and serve in one invocation.

## Verification

- `make openspec-validate NAME=feat-download-top-tier-trending-models` exits 0; all
  `tasks.md` items ticked.
- `make lint` (linefeed) GREEN — every tracked file ends with a trailing newline.
- `make test-unit` GREEN — hermetic unit tests (stubbed HF client + `hf` CLI) assert
  the fit-gate excludes OOM candidates, low/toy quants are excluded, the tier folder
  is chosen correctly, and the downloader is invoked with the right
  `repo_id/filename/dest/label`.
- Host/Metal proof: a downloaded top-tier model that "fits" must actually run via the
  GPU health path (`~/bin/llama-server` Metal binary).
- README updated in the same change (new flag + download workflow + layout).

## Sync rule

Per AGENTS.md, this issue IS the root work item; it is mirrored 1:1 by this OpenSpec
change (same goal in `proposal.md`, same interface/behaviour in `spec.md`, same steps
in `tasks.md`). Any edit to one is applied to the others and to the code in the same
commit batch. The PR that closes issue #49 references it.