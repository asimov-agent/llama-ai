# llama-ai

Tooling to serve GGUF models locally via **llama.cpp's `llama-server`** (Metal / 48 GB
unified-memory M-series Mac), plus a resilient Hugging Face downloader and the Python
venv scaffold needed to run them.

This repo bundles three pieces that were built and validated together:

| Piece | File | What it does |
|---|---|---|
| **GGUF launcher + auto-tuner** | `scripts/llama_serve.py` | Scan `~/models/**/*.gguf`, pick a model, auto-tune `llama-server` flags to fit 48 GB unified memory, and serve an OpenAI-compatible endpoint at `127.0.0.1:11434`. |
| **HF downloader** | `scripts/hf_download.py` | Download a GGUF into a tiered models folder with live progress and auto-resume/auto-retry against a throttled Hugging Face CDN. |
| **venv setup** | `tools/` | `gguf`-tooling environment (Python 3.10 venv + pip-compile container), recreatable via `make venv-install`. |

---

## Requirements

- **macOS** with an Apple Silicon GPU (tuned for 48 GB unified memory; edit the constants
  in `scripts/llama_serve.py` for less).
- **llama.cpp** built with Metal support, producing `build/bin/llama-server`. The launcher
  finds it as **`llama-server` on your PATH** (see *Install* — `make install` symlinks it
  into `~/bin`). It terminates with a clear error if the binary is missing.
- **Python 3.10** (Homebrew: `brew install python@3.10`) for the `gguf` tooling venv.
- Optional `hf` CLI (Hugging Face hub) in a venv — used by `scripts/hf_download.py`.

---

## Install (recommended) — one command, no manual venv work

```bash
git clone <this-repo> ~/repository/git/llama-ai
cd ~/repository/git/llama-ai
make install
```

`make install` does the whole setup so you never touch the venv by hand:

1. **venv** — builds the Python 3.10 gguf-tooling venv at `~/llama-gguf-tools/.venv`
   (`numpy` + `gguf==0.19.0`).
2. **launcher** — writes an executable `~/bin/llama-ai` that runs `scripts/llama_serve.py` **with the
   venv's python**, so `gguf`/`numpy` resolve with zero extra steps.
3. **`llama-server` on PATH** — symlinks `~/bin/llama-server` → your llama.cpp
   `build/bin/llama-server` (override the build path with `LLAMA_SERVER_BIN=<path>`).
   `scripts/llama_serve.py` resolves the server as **`llama-server` on PATH** and **terminates with a
   clear error if it isn't found**.
4. **symlink** — `ln -s` `~/bin/llama_ai.py` → this repo's copy of the launcher (`scripts/llama_serve.py`).
5. **verify** — a `--list` smoke run confirms the install.

After `make install`, just run:

```bash
llama-ai                 # interactive model picker
llama-ai --list          # list models
llama-ai qwen            # launch by model-name substring
llama-ai --dry qwen      # print the tuned command without running
```

Other targets: `make venv-install`, `make link`, `make smoke`, `make list`,
`make version`, `make uninstall` (removes the launcher + symlink, keeps the venv), `make help`.

> **Why a wrapper?** `scripts/llama_serve.py` imports the `gguf`/`numpy` packages that live in the
> venv, so it must be launched with the venv python. The `~/bin/llama-ai` wrapper does
> exactly that; the `llama_ai.py` symlink keeps editors/`--list` pointing at the real file (which lives at
> `scripts/llama_serve.py`).

### Manual setup (only if you don't want `make install`)

```bash
# 1. venv
cd tools && make venv-install      # create ~/llama-gguf-tools/.venv + install deps
# 2. run with the venv python
~/llama-gguf-tools/.venv/bin/python scripts/llama_serve.py --list
```

`requirements.in` is the single source of truth; `requirements.txt` is generated with
`pip-compile` inside the `tools/` Dockerfile container (`make generate-requirements`).

## Download a model (`scripts/hf_download.py`)

```bash
python3 scripts/hf_download.py <repo_id> <filename> <dest_dir> <label>
```

- Reads `HF_TOKEN` from `~/.zshrc` at runtime (never stored in the repo).
- Sets `HF_HUB_ENABLE_HF_TRANSFER=1 HF_HUB_DISABLE_XET=1` for speed.
- Auto-retries (up to 20 attempts), resuming the partial file on dropped connections.
- Appends a `.progress.log` next to the destination for live monitoring.

**Example:**

```bash
python3 scripts/hf_download.py Qwen/Qwen3.5-24B-GGUF qwen3.5-24b-q5_k_m.gguf ~/models/Qwen/24GB qwen-q5
```

## 3. Launch a model (`scripts/llama_serve.py`)

Run with the tooling venv's Python so `gguf`/`numpy` are importable:

```bash
~/llama-gguf-tools/.venv/bin/python scripts/llama_serve.py --list     # list models, don't run
~/llama-gguf-tools/.venv/bin/python scripts/llama_serve.py <name>     # run by substring
~/llama-gguf-tools/.venv/bin/python scripts/llama_serve.py            # interactive picker
~/llama-gguf-tools/.venv/bin/python scripts/llama_serve.py --dry qwen # print the command, don't run
```

The launcher will:

- Scan `~/models/**/*.gguf` (fast header-only metadata read for large files).
- Auto-tune the server: context sized to RAM budget minus KV-cache/OS overhead, `-ngl 99`
  (all layers to Metal), `-fa` flash attention, q4_0 KV cache, `--cont-batching`,
  `--metrics`.
- Detect reasoning-capable models from the chat template and enable `--reasoning` /
  `--reasoning-format deepseek` so thoughts are preserved in `message.reasoning_content`.
- Serve **one model at a time**: any existing `llama-server` on the port is stopped before
  launch. Default port `11434`, override with `--port`.
- Serve under a **stable alias `llm-local`** (`--alias llm-local`) so OpenAI-compatible
  clients can pin one endpoint name regardless of which model is loaded.
- Write the exact command to `<model-dir>/.run.log` for audit/replay.

You can customize `TOTAL_RAM_BYTES`, `OS_OVERHEAD`, `KV_QUANT`, and `SAMPLING` at the top
of `scripts/llama_serve.py`. For `--download-top-tier`, the fit is **dynamic**: the total
comes from the actual card (`LLAMA_RAM_BYTES` overrides it), headroom is capped at 45% of
total, and KV reserve applies automatically.

### Test the endpoint

```bash
curl http://127.0.0.1:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"llm-local","messages":[{"role":"user","content":"hi"}]}'
```

## Download the top-tier trending models that fit your GPU (`--download-top-tier`)

Discover and download the **currently-trending, top-tier** GGUF models (from the Hugging
Face community that publishes GGUF for llama.cpp) that **fit the CPU/GPU card you actually
have** — with KV-cache headroom so they *run*, not just download.

```bash
# list the top-tier trending models that fit the actual card (no download)
llama-ai --download-top-tier --list
# download the highest-quality top-tier model that fits, then serve it
llama-ai --download-top-tier
# download the top N that fit, then serve the best
llama-ai --download-top-tier --count 3
# see what it would do without downloading/serving
llama-ai --download-top-tier --dry
```

How it decides "trending + top tier + fits":

- **Trending** — a time-weighted Hugging Face popularity signal (`trendingScore`,
  `filter=gguf`), so you get what's hot *now*, not a lifetime download count.
- **Top tier** — only flagship/large popular families (Qwen3, DeepSeek, Mistral, Llama,
  Gemma, gpt-oss, Phi, QwQ, GLM, ...), and only non-trivial quant files (no sub‑1B toy
  quants, no multi-file shards, no vision projectors).
- **Fits with buffer** — the total memory comes from the **actual card** at runtime
  (`sysctl hw.memsize` on macOS, `/proc/meminfo` on Linux, or `LLAMA_RAM_BYTES`), with
  current-pressure headroom (`vm_stat`). Only models that leave a KV-cache reserve are
  offered — on a 48 GB card that's ~29 GB Q8-class 27B models; on a 16 GB CPU card it
  downshifts to ~12 GB Q3-class.

Downloads go into a **provider-aware** folder so you always know who made the model:

```
~/models/<owner>/<family>/<TierGB>/<file>.gguf
~/models/unsloth/Qwen3.8-27B/48GB/Qwen3.8-27B-UD-Q8_K_XL.gguf
```

Re-runs are **idempotent**: the real `hf` (huggingface_hub) CLI content-addresses its cache
by etag, and the launcher skips entirely when the target file is already complete — so you
never re-download the whole model.

---

## Verification, loop & CI (containerized — same everywhere)

Every verification stage runs **inside the test container** so behaviour is
byte-identical on your local host (nerdctl/Colima or docker) and on GitHub
Actions CI. Stages are driven **only through `make`** — the container is never
started directly.

```bash
make loop              # == make loop-harness: run ALL stages in order, GREEN gate
make test-image        # build the test image (python+pytest+deps + CPU llama-server)
make lint              # linefeed/editorconfig lint (fail-closed)
make test-unit         # hermetic unit tests
make test-install      # install tests (run in-container; host-artifact asserts skip)
make test-install-host # verify the REAL host install: ~/bin/llama-ai + symlinks + ~/models (runs on host)
make test-health       # end-to-end CPU LLM check: downloads tiny model, answers "hi"
make download-test-model  # fetch Qwen2.5-0.5B into ~/models/Qwen/8GB (via `hf` CLI)
make openspec-validate NAME=<change>   # validate an OpenSpec change
make test-clean        # prune stopped orphaned test containers (always)
```

The `make loop` harness runs these stages in order (each in its own `--rm`
container), then **always** prunes orphaned containers:

```
image → download → lint → unit → install → health → test → openspec → clean
```

- The **`health` stage** is a real end-to-end check: it downloads the
  lightweight `Qwen2.5-0.5B` model and asserts `/health` + a chat "hi" reply
  from the **CPU-built `llama-server`** bundled in the image.
- **`RUNTIME`** defaults to `nerdctl` and resolves to `docker` on non-Colima
  hosts — the same `make` target runs under either engine.
- **CI** (`.github/workflows/ci.yml`) triggers on every branch/PR and runs each
  stage as its own **parallel** job: `lint`, `unit`, `install`, `openspec`,
  and `cpu-health`. Every job is a `make` command, so CI == your local loop.

### No-fallback rule

The repo has **one** code path per resource, running through the same container
on CI and locally. In particular the model download always uses the official
`hf`(huggingface_hub) CLI (bundled in the test image) — never a `requests`/
`urllib` fallback.

### Local GPU (Metal) verification is mandatory

CI exercises only the **CPU** path (bare runners, no GPU). Before reporting a
change that touches the launcher/health/serving as done, you must also run the
health check against the **host GPU (Metal)** via `~/bin/llama-ai` with the
`Qwen/8GB` model and record the reply.

### Self-driving development (background watch loop)

This repository is **self-driving** when its background watch loop is installed
on the host. A `*/20 * * * *` host crontab entry launches a one-shot
`project-manager` Hermes session (cwd = this repo, so `AGENTS.md` loads as its
durable rulebook) that, each tick:

- **Polls PRs + CI first** and merges any PR whose CI is fully green AND has an
  approval AND no open review threads, then cleans up the merged branch — the
  local worktree + local branch + per-worker artifacts **and the REMOTE branch**
  (`git push origin --delete feat/<kebab>`; the merge itself also requests
  `delete_branch: true`, so no stale `origin` branches accumulate after a merge).
- **Drives every open issue to a PR**: for any open issue lacking a live branch/
  PR it creates an isolated git worktree feature branch off `main`
  (`../llama-ai-wt/<kebab>`), follows the OpenSpec-first lifecycle
  (change/proposal/spec/tasks first, then implementation), validates, then opens
  a PR against `main` that references the issue.
- **Keeps the issue body, OpenSpec change, and code in sync** (bidirectional,
  continuous).

The durable rules and the exact crontab entry live in `AGENTS.md` (the
"Background watch loop" section); the loop prompt and its output log are
`.watchloop/prompt.txt` and `.watchloop/watchloop.log` (both gitignored). You can
review past loop runs with `grep 'WATCH-LOOP SUMMARY' .watchloop/watchloop.log`.

This contract is exercised end-to-end by verification issue
[#7](https://github.com/asimov-agent/llama-ai/issues/7), which the loop drove to a
real worktree → OpenSpec → code → PR lifecycle on the branch
`feat/test-watchloop-verify-the-background-watch-loop-dr` — proof the loop is not
just documented but actually drives a brand-new issue to a PR.

### Choosing the worker model the loop uses

Each cron-spawned worker is a `project-manager` Hermes session that drives one open
issue to a PR. It uses an LLM whose choice defaults to the local GGUF model
(`llm-local` on `:11434`, good for serving) but is **configurable** so the loop runs
fast when you want it to.

**Where it is set — two places (resolution order, first wins):**

1. **Environment variables** (in the crontab / exported): `WATCHLOOP_WORKER_MODEL`
   and `WATCHLOOP_WORKER_PROVIDER`.
2. **The config file** `.watchloop/run/worker-model` — two lines, line 1 = model id,
   line 2 = provider (blank = profile provider). This is a **local, gitignored** file.

If both are empty, workers use the profile default (`llm-local`).

**How to configure (recommended, uses the template):**

```bash
# copy the versioned template into the live (gitignored) config, then edit it
cp scripts/worker-model.template .watchloop/run/worker-model
```

A built-in template lives at **`scripts/worker-model.template`** (tracked in git) and
documents both options in place:

- **llama.cpp / local GGUF** — set line 1 to `llm-local`, leave line 2 empty. Good
  for offline/private jobs; slower for agentic driving (~170s/call on the 35B).
- **Hosted / OpenRouter (recommended for speed)** — e.g. line 1
  `deepseek/deepseek-v4-flash-0731`, line 2 `openrouter`. Makes the autonomous loop
  drive issues to a PR quickly.

The dispatcher reads this at startup and launches each worker with
`hermes chat ... -m <MODEL> --provider <PROVIDER>`. Change the file (or the env vars)
and the next cron tick picks it up.

---

## Layout

```
llama-ai/
├── tools/             # gguf-tooling venv + pip-compile container
│   ├── Makefile
│   ├── requirements.in      # source of truth (numpy, gguf==0.19.0)
│   ├── requirements.txt     # generated by pip-compile
│   └── Dockerfile           # pip-compile resolver (python:3.10-slim)
├── containers/test/   # test image: python+pytest+deps + CPU llama-server + hf CLI
│   └── Dockerfile
├── docker-compose-files/test.yaml   # hermetic test container (documented)
├── scripts/
│   ├── llama_serve.py    # GGUF launcher + llama-server auto-tuner + --download-top-tier
│   ├── hf_download.py    # HF downloader (auto-resume/retry, throttled)
│   ├── __init__.py       # package marker for hermetic unit tests
│   ├── loop_harness.py       # `make loop` orchestrator (9 stages)
│   ├── download_test_model.py# fetch Qwen2.5-0.5B into ~/models/Qwen/8GB via hf
│   └── lint_linefeeds.py     # linefeed/editorconfig lint (--fix)
├── tests/
│   ├── test_llama_ai.py      # hermetic unit tests (imports scripts.llama_serve)
│   ├── test_top_tier_acceptance.py # REAL (no-mock) top-tier download acceptance
│   ├── test_install.py       # host-install tests (skip cleanly in container)
│   └── test_health.py        # e2e CPU LLM health check (downloads + "hi")
├── .github/workflows/ci.yml  # parallel per-stage CI (all branches/PRs)
├── openspec/            # OpenSpec change tracking (spec-driven)
├── LICENSE           # MIT
└── README.md
```

## License

MIT — see [LICENSE](LICENSE).
