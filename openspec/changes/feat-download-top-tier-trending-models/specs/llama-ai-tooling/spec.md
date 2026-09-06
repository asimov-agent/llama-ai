# Spec: Download the top-tier trending GGUF models that fit your GPU

## Why (rationale)

The launcher (`scripts/llama_serve.py`, symlinked as `~/bin/llama-ai`) can only serve
locally-present models. Issue #49 adds `--download-top-tier`: fetch the **currently-trending,
top-tier** GGUF models (HF community quants) that **fit the user's GPU** with KV-cache
headroom, so they run after download — the opposite of a low-tier picker. Reuses the existing
`hf`-CLI downloader, tiered `~/models` layout, and launcher fit/KV math (no second downloader —
AGENTS.md "no fallback" rule holds), with a dynamic card-memory read instead of hardcoded
constants.

---

## ADDED Requirements

### Requirement: A1 — Discovers trending + top-tier + GPU-fitting models
WHEN a user runs `llama-ai --download-top-tier`, THEN the launcher queries a time-bounded HF
trending signal (`sort=trendingScore`, `filter=gguf`), filters to flagship/large families
(Qwen3/DeepSeek/Mistral/Llama/Gemma/gpt-oss/Phi/QwQ/GLM...), excludes non-trivial-toy quants
(`MIN_TOP_TIER_GB`, no multi-file shards / vision projectors) AND **drops low-fidelity
IQ1/IQ2/IQ3 quants** (a 27B at ~8-11 GB is poor quality — "no lower models") AND **drops
MTP/mtp-* companion heads** (multi-token-prediction aux files, not the serviceable model).
fit+buffer gate so only models that fit the machine's unified memory with KV-cache headroom are
offered. **Ranking is TRENDING-first**: providers are ordered by HF `trendingScore` (most
popular now first), and each provider offers its HIGH quant plus a clearly-LOWER quant.

**How many / how rated:** `--count N` (default 5) = number of **distinct providers**; each
yields `--per-provider` (default **2**) quants — the best HIGH (Q8, highest fidelity that fits)
plus a clearly-LOWER quant (~25% smaller, Q4/Q5/Q6) so both fit comfortably. So `--count 5` ⇒ up
to 10 models (5 high + 5 lower). `--min-trending-score N` (default 0) sets a rating floor — only
repos with HF `trendingScore >= N` are considered. `--list` prints the ranked candidates (repo,
filename, size, trendingScore, tier) without downloading. Downloads are **batch-resilient**: any
single provider's failure is retried (up to 3×) without aborting the batch, and
already-completed downloads are never re-fetched (etag/refresh idempotent).

#### Scenario: On the dynamic total (48 GB host), the #1-trending provider offering only IQ2/IQ3
#### (8-11 GB) is skipped, and the top provider ordering follows trendingScore (e.g. unsloth 281
#### before a 40-trending 35B). With `--count 5` (per_provider 2), up to 10 picks surface across 5
#### providers, each a high (Q8) + lower (Q6/Q5) pair. `--min-trending-score 250` drops any pick
#### below 250. A download batch with one failing provider still completes the others, then retries
#### the failed one.

### Requirement: A2 — Dynamic memory detection + fit + buffer gate
WHEN judging fit, THEN it reads the machine's real memory at runtime, not a fixed size, leaving
KV-cache headroom:
- **Total**: `sysctl hw.memsize` (macOS) / `MemTotal` from `/proc/meminfo` (Linux) /
  `LLAMA_RAM_BYTES` override.
- **Headroom**: current pressure (`vm_stat` wired + safety), floored at 3 GB, capped at 45% of
  total — stable yet bounded by the real card.
- **Pre-download**: accept iff `predicted_size_bytes + headroom + KV_reserve <= read_total_ram()`.
- **Post-download**: re-derive exact context via `read_model_meta_fast()` + `tuned_context()`.

`KV_QUANT`/`kv_bytes_per_token()`/`tuned_context()` stay the single fit implementation.

#### Scenario: A 48 GB card accepts the 27B Q8 (~29 GB, ~16 GB KV); a 70B Q8 is rejected
pre-download. A 16 GB machine automatically uses 16 GB — no code edit.

### Requirement: A3 — Download through the existing `hf`-CLI downloader (one code path)
WHEN a candidate is downloaded, THEN it is fetched via `scripts/hf_download.py` exactly like
`download_test_model.py`: resolve `HF_BIN` via `shutil.which("hf")` (abort with a clear error if
absent — no fallback), use `HF_XET_HIGH_PERFORMANCE=1` (hf-xet chunked parallel; never
`HF_HUB_DISABLE_XET`, which forced the slow single-stream path), read `HF_TOKEN` from `~/.zshrc`,
resume/retry (max 20) on connection drop, and show a live **0-100%** progress readout (size,
MB/s, elapsed) on the terminal and in the `.progress.log`.

#### Scenario: `hf` on PATH → downloads into the tier folder with a live % progress + resume/retry.
The terminal shows `NN.N% (X.XX/Y.YY GB) | MB/s | attempt | running` every ~5s. `hf` absent → fails
fast with an actionable error (no second downloader).

### Requirement: A9 — Refresh detects same-name content updates (etag/content-hash aware)
WHEN a downloaded model's `--download-top-tier` run happens again, THEN the path runs
`hf_download.py` with `refresh=1`, which always consults the Hub and decides freshness by the
file's **etag = content hash**, never by filename or size:
- unchanged → `hf` no-ops fast;
- upstream changed the file **even same name + same size** → etag differs, `hf` re-fetches just
  that file;
- a corrupted local copy (same name+size) is detected and restored.

The top-tier path must NOT skip on existence/size alone (that would mask an update). Partial
downloads still resume by byte offset from the recorded etag.

#### Scenario: Upstream re-uploads `Qwen3.8-27B-UD-Q8_K_XL.gguf` (same name+size, new weights) →
a re-run re-fetches and serves the new bytes. A locally corrupted copy is restored on re-run.

### Requirement: A4 — Provider-aware tier-folder placement + immediate serveability
WHEN downloaded, THEN the model lands in `~/{MODELS_ROOT}/<owner>/<model-family>/<TierGB>/<file>.gguf`
(owner = HF repo owner, family = repo family, tier 8/16/24/48). `scan_models()` (`os.walk` at any
depth) sees it immediately — no scanner change.

#### Scenario: `unsloth/Qwen3.8-27B-GGUF` Q8_0 → `~/models/unsloth/Qwen3.8-27B/48GB/...`; `--list`
shows it and the owner is obvious from the path.

### Requirement: A5 — Download ONLY; never auto-start llama-server
WHEN `--download-top-tier` runs, THEN it downloads/places the selected model(s) and
**never** launches llama-server — the download command has no serving side-effect. To
serve a downloaded model you use the normal launch path (`llama-ai <name>`), which reuses
`build_command()` (tuning, sampling, `--alias llm-local`, reasoning) honoring `--port`
and `--dry`.

#### Scenario: `llama-ai --download-top-tier --count 5` downloads up to 5 providers × 2
#### quants (high + lower) and exits WITHOUT starting a server. Serving any of them is a
#### separate, explicit command.

### Requirement: A6 — Dynamic GPU load + "hi" verification with remaining-RAM proof
WHEN verification loads a downloaded model, THEN it **proves** "fits" (does not assume it):
measure RAM **before** load → load onto the GPU (Metal), wait for `/health` → POST "hi", assert a
reply → re-measure RAM **after**; fail + report before/after numbers if the post-load headroom is
below the safety margin (never claim success on a swap/OOM).

#### Scenario: `Qwen3.8-27B-Q8_0` (~29 GB) loads, `/health` ok, "hi" replies, post-load `vm_stat`
still shows several GB free → passes. A model that would consume all headroom is caught by the
post-load check and reported.

### Requirement: A8 — Real top-tier download + verification (host GPU vs CI CPU)
WHEN the verification runs, THEN it is a **real end-to-end test (no mocks/stubs)**:
- **Actually download** via the real `hf`/downloader if not already present (idempotent).
- Dynamic target per environment (AGENTS.md): host with GPU → Metal path (`~/bin/llama-server`,
  `-ngl 99`, the fitting GPU model); GPU-less CI runner → CPU path in the containerized test image,
  fitting the runner's CPU/RAM.
- Run A6 checks (load → `/health` → "hi" → post-load RAM) on whichever backend exists. If the pick
  would exceed the card: skip-with-reason — never a silent OOM.

#### Scenario: Host (48 GB Metal) verifies the 27B Q8 on GPU; CI CPU runner verifies the quant
that fits ~16 GB on CPU; already-downloaded → no re-download, loads immediately.

### Requirement: A7 — Download-logic placement acceptance (high-quality criteria)
WHEN automated tests verify download placement, THEN they assert the **exact filesystem result**,
not just exit 0:
- `.gguf` at exactly `~/{MODELS_ROOT}/<owner>/<family>/<TierGB>/<file>.gguf` (owner/family/tier from
  HF metadata);
- file **complete** (size == HF bytes, no `.incomplete`/`.part`/lock remnants) with a `.progress.log`;
- `scan_models()`/`--list` sees it; re-run is idempotent; different size-fits land in different tier
  folders (24 GB → `24GB/`, 48 GB → `48GB/`; no cross-tier contamination).
- **metadata-verified**: after download, the file's GGUF header is read (`read_model_meta_fast`)
  and must decode to a real model (arch/name/layers) — an HTML error page, truncated/corrupt stub,
  or wrong-file-under-right-name is rejected, not just accepted by filename+size.

#### Scenario: Stub `hf`, assert the exact destination path pre-invocation, then assert the file +
`.progress.log` at that path with the right size. Two size-fits land in `24GB/` and `48GB/` without
leaking across tiers. A valid GGUF passes metadata verification; an HTML/non-GGUF file does not.

### Requirement: A8 — NO-SKIP test harness (durable; mirrored in AGENTS.md)
WHEN the test suite runs (host or CI container), THEN **no test may be skipped** — every test runs
and passes, or the run is a loud failure:
- all `pytest.skip`/`skipif` are removed; the conftest `pytest_report_teststatus` /
  `pytest_runtest_logreport` hooks turn any skipped test into a red exit with a clear
  "provision the prerequisite" message (never silent-green CI on a missing prerequisite);
- prerequisites are provisioned so tests genuinely run: `make test-install-ci` performs a REAL
  `make install` + seeds a model and runs `tests/test_install.py` in ONE container (7 tests run,
  no skip); `make test-health` / `make test-top-tier-serve` download their model/server first;
- **all python test files are integrated into CI**: `tests/test_install.py` runs via
  `test-install-ci` (install job); `tests/test_check_openspec_tasks.py` is folded into
  `make test-unit` (unit job — it was previously orphaned, running nowhere).

#### Scenario: Run `make test-unit` / `make test-install-ci` / `make test-health` in the CI
container — assert the run reports 0 skipped (any skip -> non-zero exit and a "TEST SKIPPED — no
skips allowed (AGENTS.md)" failure). Probe: a throwaway `pytest.skip()` test is turned into FAILED.

---

## EXISTING Requirements (unchanged)

### Requirement: E1 — Local model serving preserved
WHEN the existing `llama-ai <name>` / `--list` / `--port` / `--dry` invocations run, THEN behaviour
is unchanged (scan, pick, tune, serve). `--list` still lists all local GGUFs.

### Requirement: E2 — Stable alias `llm-local`
WHEN `build_command()` runs, THEN it keeps `--alias llm-local` for any local or newly-downloaded
model, so OpenAI-compatible clients pin one endpoint name.

---

## REM Requirements — one code path preserved
- Download: only the official `hf` CLI via `scripts/hf_download.py` — no `requests`/`urllib`
  fallback.
- Launcher server resolution: only PATH / `LLAMA_SERVER` / `~/bin/llama-server` — clear error when
  absent, no dual path.
- Fit-gate: same `KV_QUANT`/`kv_bytes_per_token()`/`tuned_context()` as the auto-tuner, plus a
  dynamic total read from the card — no separate fit implementation, no hardcoded fixed-memory
  constants.
