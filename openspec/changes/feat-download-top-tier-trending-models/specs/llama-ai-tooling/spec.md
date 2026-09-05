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

### Requirement: A2 — Dynamic memory detection + fit + buffer gate (from the actual GPU/CPU card)
WHEN the launcher judges whether a candidate fits, THEN it **reads the machine's real
memory at runtime** instead of assuming a fixed size, AND it leaves KV-cache headroom,
using the model's own GGUF metadata in two stages:

- **Dynamic total & headroom.** Total unified memory is read from the host (macOS:
  `sysctl -n hw.memsize`; fallback to an `LLAMA_RAM_BYTES` env override). OS/reserved
  headroom is derived from **current memory pressure** (macOS `vm_stat`: wired + a safety
  margin), not a hardcoded `3 GB`, so the decision tracks the state of the actual card.
- **Pre-download** (no local file): accept only if HF per-file `size` + dynamic KV reserve
  fit the real total, i.e. `predicted_size_bytes + headroom + KV_reserve <= read_total_ram()`.
- **Post-download**: re-derive exact context from the real GGUF header via
  `read_model_meta_fast()` + `tuned_context()` against the same dynamic total.

`KV_QUANT`, `kv_bytes_per_token()`, and `tuned_context()` stay the single fit
implementation the auto-tuner already uses.

#### Scenario: On the 48 GB M5 Pro, `sysctl hw.memsize` reports 51,539,607,552 B; the
35B Q5_K_M (~24 GB) is accepted, but a 70B Q8 (would exceed `read_total_ram() − headroom − KV`) is rejected pre-download.

#### Scenario: A machine with a different card (e.g. 16 GB) automatically uses 16 GB as
the total — no code edit — because the value is read at runtime, not hardcoded.

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

### Requirement: A6 — Dynamic GPU load + "hi" verification with remaining-RAM proof
WHEN `--download-top-tier` (or the verification step) loads a downloaded model on the
real GPU, THEN the launcher **dynamically measures the machine, loads the model, asks it
"hi", and confirms there is still headroom after load** — so "fits" is proven, not assumed:

1. **Measure before load**: read total RAM from the card (`sysctl hw.memsize`) and current
   usage; compute available headroom at run time (not a hardcoded value).
2. **Load the model**: launch onto the GPU (Metal), wait for `/health`.
3. **Ask "hi"**: POST to `/v1/chat/completions` and assert a real text reply.
4. **Measure after load**: re-read available memory and assert the loaded model left the
   documented headroom (i.e. it physically loaded and didn't consume everything / didn't
   swap). If the post-load free memory is below the safety margin, the check fails and
   reports the numbers instead of claiming success.

#### Scenario: After launching `Qwen3.8-27B-Q8_0` (~29 GB) the `/health` is ok, "hi" returns
a reply, and post-load `vm_stat` still shows several GB free — the download+load passes.

#### Scenario: A model that fits on disk but would consume all headroom on load is detected
by the post-load memory check and reported (with before/after numbers), not silently
accepted.

### Requirement: A7 — Download-logic placement acceptance (high-quality criteria)
WHEN automated tests verify the download placement logic, THEN they assert the **exact
filesystem result** so mis-placement is caught, not just "the CLI returned 0":

- The `.gguf` lands at exactly
  `~/{MODELS_ROOT}/<owner>/<model-family>/<TierGB>/<file>.gguf` (owner + family + tier all
  from the HF repo metadata).
- The file is the **complete** download (size equals the HF `size`, no `.incomplete` /
  `.part` / lock remnants).
- A `.progress.log` exists next to it (the downloader's contract).
- `scan_models()` picks it up immediately: `llama-ai --list` lists it, and the owner/family
  are derivable from the path (provenance preserved).
- A re-run is idempotent: `--download-top-tier` does not re-download when the file is
  already present at the correct path.
- A *different* size fit chooses a *different* tier folder (e.g. 24 GB fit → `24GB/`,
  48 GB fit → `48GB/`) — no cross-tier contamination.

#### Scenario: A hermetic test stubs `hf` and asserts the exact destination path prior to
invocation, then a post-invocation file assertion confirms the file + `.progress.log` exist
at that path with the correct size.

#### Scenario: Two runs against stubs with different sizes land in `24GB/` and `48GB/`
respectively, and neither leaks into an adjacent tier.

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