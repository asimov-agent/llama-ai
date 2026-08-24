# llama-ai

Tooling to serve GGUF models locally via **llama.cpp's `llama-server`** (Metal / 48 GB
unified-memory M-series Mac), plus a resilient Hugging Face downloader and the Python
venv scaffold needed to run them.

This repo bundles three pieces that were built and validated together:

| Piece | File | What it does |
|---|---|---|
| **GGUF launcher + auto-tuner** | `llama_ai.py` | Scan `~/models/**/*.gguf`, pick a model, auto-tune `llama-server` flags to fit 48 GB unified memory, and serve an OpenAI-compatible endpoint at `127.0.0.1:11434`. |
| **HF downloader** | `hf_dl.py` | Download a GGUF into a tiered models folder with live progress and auto-resume/auto-retry against a throttled Hugging Face CDN. |
| **venv setup** | `tools/` | `gguf`-tooling environment (Python 3.10 venv + pip-compile container), recreatable via `make venv-install`. |

---

## Requirements

- **macOS** with an Apple Silicon GPU (tuned for 48 GB unified memory; edit the constants
  in `llama_ai.py` for less).
- **llama.cpp** built with Metal support, producing `build/bin/llama-server`. The launcher
  finds it as **`llama-server` on your PATH** (see *Install* — `make install` symlinks it
  into `~/bin`). It terminates with a clear error if the binary is missing.
- **Python 3.10** (Homebrew: `brew install python@3.10`) for the `gguf` tooling venv.
- Optional `hf` CLI (Hugging Face hub) in a venv — used by `hf_dl.py`.

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
2. **launcher** — writes an executable `~/bin/llama-ai` that runs `llama_ai.py` **with the
   venv's python**, so `gguf`/`numpy` resolve with zero extra steps.
3. **`llama-server` on PATH** — symlinks `~/bin/llama-server` → your llama.cpp
   `build/bin/llama-server` (override the build path with `LLAMA_SERVER_BIN=<path>`).
   `llama_ai.py` resolves the server as **`llama-server` on PATH** and **terminates with a
   clear error if it isn't found**.
4. **symlink** — `ln -s` `~/bin/llama_ai.py` → this repo's `llama_ai.py`.
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

> **Why a wrapper?** `llama_ai.py` imports the `gguf`/`numpy` packages that live in the
> venv, so it must be launched with the venv python. The `~/bin/llama-ai` wrapper does
> exactly that; the `llama_ai.py` symlink keeps editors/`--list` pointing at the real file.

### Manual setup (only if you don't want `make install`)

```bash
# 1. venv
cd tools && make venv-install      # create ~/llama-gguf-tools/.venv + install deps
# 2. run with the venv python
~/llama-gguf-tools/.venv/bin/python llama_ai.py --list
```

`requirements.in` is the single source of truth; `requirements.txt` is generated with
`pip-compile` inside the `tools/` Dockerfile container (`make generate-requirements`).

## Download a model (`hf_dl.py`)

```bash
python3 hf_dl.py <repo_id> <filename> <dest_dir> <label>
```

- Reads `HF_TOKEN` from `~/.zshrc` at runtime (never stored in the repo).
- Sets `HF_HUB_ENABLE_HF_TRANSFER=1 HF_HUB_DISABLE_XET=1` for speed.
- Auto-retries (up to 20 attempts), resuming the partial file on dropped connections.
- Appends a `.progress.log` next to the destination for live monitoring.

**Example:**

```bash
python3 hf_dl.py Qwen/Qwen3.5-24B-GGUF qwen3.5-24b-q5_k_m.gguf ~/models/Qwen/24GB qwen-q5
```

## 3. Launch a model (`llama_ai.py`)

Run with the tooling venv's Python so `gguf`/`numpy` are importable:

```bash
~/llama-gguf-tools/.venv/bin/python llama_ai.py --list     # list models, don't run
~/llama-gguf-tools/.venv/bin/python llama_ai.py <name>     # run by substring
~/llama-gguf-tools/.venv/bin/python llama_ai.py            # interactive picker
~/llama-gguf-tools/.venv/bin/python llama_ai.py --dry qwen # print the command, don't run
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
of `llama_ai.py`.

### Test the endpoint

```bash
curl http://127.0.0.1:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"llm-local","messages":[{"role":"user","content":"hi"}]}'
```

---

## Layout

```
llama-ai/
├── llama_ai.py        # GGUF launcher + llama-server auto-tuner
├── hf_dl.py           # HF downloader (auto-resume/retry)
├── tools/             # gguf-tooling venv + pip-compile container
│   ├── Makefile
│   ├── requirements.in      # source of truth (numpy, gguf==0.19.0)
│   ├── requirements.txt     # generated by pip-compile
│   └── Dockerfile           # pip-compile resolver (python:3.10-slim)
├── LICENSE           # MIT
└── README.md
```

## License

MIT — see [LICENSE](LICENSE).
