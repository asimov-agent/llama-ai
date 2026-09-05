# Spec: Download the top-tier trending GGUF models that fit your GPU

## Why (rationale)

The launcher (`scripts/llama_serve.py`, symlinked as `~/bin/llama_ai.py`) can only
serve models already present under `~/models`. Issue #49 wants it to also **download
the currently-trending, top-tier GGUF models that fit the user's GPU** — the large,
popular community models (e.g. Qwen3, DeepSeek-R1 distill, Mistral Small/Large, Llama
3.3, Gemma 3, gpt-oss, Phi, QwQ) sized so that, on a 48 GB unified-memory card, a KV
cache still fits and the model runs after download. This is explicitly the *opposite*
of a low-tier picker.

The change reuses the repo's established building blocks: the `hf`
(huggingface_hub) CLI via `scripts/hf_download.py`, the tiered `~/models`
folder layout, and the launcher's existing fit/KV math (`TOTAL_RAM_BYTES`,
`OS_OVERHEAD`, `kv_bytes_per_token()`, `tuned_context()`, `build_command()`). It
adds no second downloader implementation (the repo's "no fallback" rule is preserved).

---

## ADDED Requirements

### Requirement: A1 — `--download-top-tier` discovers trending + top-tier + GPU-fitting models
WHEN a user runs `llama-ai --download-top-tier`, THEN the launcher queries a
time-bounded Hugging Face trending signal (trending score / recent downloads),
filters to flagship/large popular families, filters to candidate `.gguf` files whose
quant file is non-trivial (no sub-1B toy quants), and applies the fit+buffer gate so
only models that fit the machine's unified memory with KV-cache headroom are offered.

#### Scenario: On the 48 GB host, a 35B Q5_K_M (~24 GB) model is offered, but a 70B
Q8 (would exceed `TOTAL_RAM_BYTES - OS_OVERHEAD` with KV) and a 0.5B toy quant are not.

#### Scenario: `llama-ai --download-top-tier --list` prints the ranked candidates that
would fit (repo_id, filename, size_gb, quant, tier) without downloading.

### Requirement: A2 — Fit + buffer gate uses the model's own metadata, in two stages
WHEN a candidate is judged for fit, THEN it is accepted only if it leaves KV-cache
headroom, AND the judgement uses the model's own GGUF metadata (not a guess):
**pre-download** (no local file yet) it used the HF repo per-file **size** + family
parameter count with a conservative KV reserve, i.e.
`predicted_size_bytes + OS_OVERHEAD + KV_reserve <= TOTAL_RAM_BYTES`; **post-download**
it re-derives the exact fitted context from the real GGUF header via
`read_model_meta_fast()` + `tuned_context()`. The constants `TOTAL_RAM_BYTES = 48 GB`,
`OS_OVERHEAD = 3 GB`, `KV_QUANT` and the `kv_bytes_per_token()` function are the same ones
the launcher's auto-tuner already uses (one fit implementation).

#### Scenario: A model whose HF size alone fits but whose size + KV reserve + overhead exceeds
48 GB is rejected pre-download, so it never enters the download queue.

#### Scenario: A downloaded model is re-parsed with `read_model_meta_fast()`; if it still would
not fit (edge case), the launcher reports it clearly instead of serving an OOM launch.

### Requirement: A3 — Download through the existing `hf`-CLI downloader (one code path)
WHEN the user selects a candidate to download, THEN it is fetched via
`scripts/hf_download.py` with the exact mechanics of `download_test_model.py`:
resolve `HF_BIN` via `shutil.which("hf")` (abort with a clear error if absent — no
fallback downloader), set `HF_HUB_ENABLE_HF_TRANSFER=1` + `HF_HUB_DISABLE_XET=1`, read
`HF_TOKEN` from `~/.zshrc`, and resume/retry (max 20) on connection drop.

#### Scenario: `hf` is on PATH; the model downloads into its tier folder with a
`.progress.log` and the existing resume/retry behaviour.

#### Scenario: `hf` is absent; the command fails fast with an actionable error instead
of invoking a second downloader.

### Requirement: A4 — Provider-aware tier-folder placement + immediate serveability
WHEN a model is downloaded via `--download-top-tier`, THEN it lands in
`~/{MODELS_ROOT}/<owner>/<model-family>/<TierGB>/` where `<owner>` is the HF repo owner
(who created/quantized the model, e.g. `unsloth`, `OBLITERATUS`), `<model-family>` is the
family, and `<TierGB>` is the computed fitting tier (8/16/24/48). Because `scan_models()`
uses `os.walk(MODELS_ROOT)` at any depth, the downloaded model is immediately visible to
the existing picker and auto-tuner with no scanner change.

#### Scenario: `unsloth/Qwen3.8-27B-GGUF` Q8_0 is downloaded to
`~/models/unsloth/Qwen3.8-27B/48GB/Qwen3.8-27B-Q8_0.gguf`; `llama-ai --list` shows it as a
selectable model, and the owner is obvious from the path.

### Requirement: A5 — Serve after download (single invocation)
WHEN `--download-top-tier` downloads a model that also serves (not `--list`-only),
THEN the launcher builds the server command with the existing `build_command()`
(tuning, sampling, `--alias llm-local`, reasoning) and runs the normal serve flow,
honoring `--port` and `--dry`.

#### Scenario: `llama-ai --download-top-tier --port 11434` downloads the chosen model
then serves it on port 11434 with the standard tuned flags.

---

## EXISTING Requirements (unchanged, must keep passing)

### Requirement: E1 — Local model serving preserved
WHEN a user runs the existing `llama-ai <name>` / `--list` / `--port` / `--dry`
invocations, THEN behaviour is unchanged from today (scan, pick, tune, serve).

#### Scenario: `llama-ai --list` still lists all local GGUF models exactly as before.

### Requirement: E2 — Stable alias `llm-local`
WHEN `build_command()` builds a server command, THEN it keeps `--alias llm-local`
regardless of which model (local or newly downloaded) is loaded.

#### Scenario: A client requests `model: llm-local` against a server launched from a
`--download-top-tier` run and it resolves.

---

## REM Requirements — one code path preserved
WHEN the download path runs, THEN it uses only the official `hf` (huggingface_hub)
CLI via `scripts/hf_download.py` — no `requests`/`urllib` fallback downloader.
WHEN the launcher resolves its server, THEN it uses only PATH / `LLAMA_SERVER` /
`~/bin/llama-server`, terminating with a clear error when absent (no dual path).
WHEN the fit-gate judges a model, THEN it uses the same `TOTAL_RAM_BYTES` /
`OS_OVERHEAD` / `KV_QUANT` constants as the auto-tuner (no separate fit implementation).