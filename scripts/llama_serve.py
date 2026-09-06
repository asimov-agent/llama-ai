#!/usr/bin/env python3
"""
llama_serve.py - GGUF model launcher + auto-tuner for llama.cpp llama-server (Metal).

Serves an OpenAI-compatible endpoint via llama.cpp's llama-server. GGUF metadata
is read by the `gguf` package from the 3.10 venv set up by ~/llama-gguf-tools
(make venv-install). Run with that venv's python:

    ~/llama-gguf-tools/.venv/bin/python ~/scripts/llama_serve.py --list

- Scans ~/models/**/*.gguf
- Lets you pick a model from a numbered list (or pass substring/alias as argv)
- Auto-tunes llama-server flags to fit 48 GB unified memory:
    * KV cache sized to target context (q4_0 K+V, FlashAttention, all layers to GPU)
    * context = min(train-ctx, bytes-available / kv-bytes-per-token) with margin
    * -np slots: 2 for small (<10 GB) models, 1 for large
- Writes the exact command to <dest>/.run.log and launches llama-server

Usage:
    python3 ~/scripts/llama_serve.py            # interactive picker
    python3 ~/scripts/llama_serve.py --list     # list models, no run
    python3 ~/scripts/llama_serve.py <name>     # run by substring of filename
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Interpreter bootstrap: the `gguf`/`numpy` deps live in the 3.10 venv built by
# `make install` (~/llama-gguf-tools/.venv). This file is symlinked into ~/bin
# as `llama_ai.py` and its shebang (#!/usr/bin/env python3) often resolves to the
# SYSTEM python, which lacks gguf -> "No module named 'gguf'". If the imports
# below are missing in the current interpreter, re-exec this same file with the
# venv python so it works however it is launched (directly or via `llama-ai`).
# ---------------------------------------------------------------------------
try:
    import gguf  # noqa: F401
    import numpy  # noqa: F401
except ImportError:
    _venv_py = os.path.expanduser("~/llama-gguf-tools/.venv/bin/python")
    if os.path.isfile(_venv_py):
        if sys.executable != _venv_py:
            args = [_venv_py, __file__] + sys.argv[1:]
            os.execv(_venv_py, args)  # replaces this process in place
    print(
        "[ERROR] gguf/numpy not importable in current python and the gguf venv was not "
        "found.\n"
        "        Install it first:  cd ~/repository/git/llama-ai && make install\n"
        "        Then run:          ~/llama-gguf-tools/.venv/bin/python ~/scripts/llama_serve.py\n"
        "        (or use the 'llama-ai' launcher on your PATH)",
        file=sys.stderr,
    )
    raise SystemExit(1)
from gguf import GGUFReader
import numpy as np

HOME = os.path.expanduser("~")
# MODELS_ROOT overridable for hermetic tests (and for custom model dirs).
# Falls back to ~/models so local host behaviour is unchanged.
MODELS_ROOT = os.environ.get("LLAMA_MODELS_ROOT") or os.path.join(HOME, "models")
TOTAL_RAM_BYTES = 48 * 1024 * 1024 * 1024  # M5 Pro unified 48 GB
OS_OVERHEAD = 3 * 1024 * 1024 * 1024       # keep headroom for macOS/Metal
KV_QUANT = "q4_0"                           # K and V cache quant type
# ---------------------------------------------------------------------------
# Top-tier trending download (`--download-top-tier`)
# ---------------------------------------------------------------------------
# Flagship / large popular families considered "top tier". A trending GGUF whose
# repo id matches any of these (case-insensitive substring) is eligible; toy/
# tiny quantizations are then excluded by MIN_TOP_TIER_GB.
TOP_TIER_FAMILIES = (
    "qwen3", "qwen", "deepseek", "mistral", "llama-3", "llama3",
    "gemma", "gpt-oss", "phi-4", "phi-3", "qwq", "glm", "olmo",
    # additional trending LLM families observed in the live gguf trending query but
    # wrongly dropped (they're real LLMs, not TTS/image/audio):
    "ornith",          # ornith-ai/Ornith-1.5-{9B,35B-A3B}-GGUF (3.5M downloads, trend ~40)
    "qwopus",          # Jackrong/Qwopus3.8-27B-Flash-GGUF (trend ~121)
    "qwythos",         # empero-ai/Qwythos-9B (trend ~39)
    "tiel-coder",      # peculiar-ragdoll/Tiel-Coder-35B-A3B-GGUF (trend ~87)
    "minimax",         # unsloth/MiniMax-H3-GGUF (trend ~27)
    "k2-", "mova",     # IFM/K2-Horizon-MoVA-36B-A4B-GGUF (trend ~74)
)
MIN_TOP_TIER_GB = 4.0          # below this the quant file is treated as a toy/small
# Growing tier ladder for the `TierGB` placement folder. Extends DOWN to 1/2/4 GB so
# tiny CPU cards and small models get truthful folders too, and UP past 48 GB so big
# cards (256/512 GB+) get truthful tiers instead of everything-capped-at-48GB.
# Availability is bounded by the detected/overridden card in pick_tier_folder().
TIER_LADDER_GB = (1, 2, 4, 8, 16, 24, 48, 96, 128, 192, 256, 384, 512, 768, 1024, 1536, 2048, 3072)
HF_API = "https://huggingface.co/api/models"
HF_UA = "llama-ai/1.0 (top-tier-download)"
LLAMA_RAM_ENV = "LLAMA_RAM_BYTES"
LLAMA_HEADROOM_ENV = "LLAMA_HEADROOM_BYTES"
LLAMA_HEADROOM_MAX_FRAC = 0.45   # max OS reserve as a fraction of total RAM
# sampling defaults from user's usual invocation (fallback preset when a model
# supplies no author-recommended defaults). Kept as the fallback default.
SAMPLING = ["--temp", "0.6", "--top-p", "0.9", "--top-k", "40", "--min-p", "0.05",
            "--repeat-penalty", "1.05"]
# Map short sampling dict keys to llama-server flags (see build_command).
SAMPLING_FLAG_MAP = {
    "temperature": "--temp",
    "top_p": "--top-p",
    "top_k": "--top-k",
    "min_p": "--min-p",
    "repeat_penalty": "--repeat-penalty",
}
# Short name -> GGUF metadata key for author-recommended sampling defaults.
SAMPLING_KEYS = {
    "temperature": "general.sampling.temperature",
    "top_p": "general.sampling.top_p",
    "top_k": "general.sampling.top_k",
    "min_p": "general.sampling.min_p",
    "repeat_penalty": "general.sampling.repeat_penalty",
}


def _extract_sampling_from_kv(kv):
    """Author-recommended sampling defaults from a parsed header kv dict."""
    out = {}
    for short, full in SAMPLING_KEYS.items():
        if full in kv:
            s = str(kv[full]).strip()
            if s != "":
                out[short] = s
    return out


def _extract_sampling_from_fields(fields):
    """Author-recommended sampling defaults from a GGUFReader fields mapping."""
    out = {}
    for short, full in SAMPLING_KEYS.items():
        if full in fields:
            s = str(_gget(fields[full])).strip()
            if s != "":
                out[short] = s
    return out

from gguf import GGUFReader
import numpy as np


# ----------------------------------------------------------------------------
# GGUF metadata reader — uses the `gguf` package from the 3.10 venv
# (~/llama-gguf-tools/.venv, see `make venv-install`). No stdlib fallback.
# ----------------------------------------------------------------------------
def _gget(f):
    """Return the scalar/string value of a GGUFReader field."""
    raw = f.parts[f.data[0]]  # uniform: data[0] indexes the value part
    a = np.asarray(raw)
    if a.dtype == np.uint8 and a.ndim == 1:
        try:
            return bytes(a).decode("utf-8", "replace")
        except Exception:
            return a
    flat = a.reshape(-1)
    items = [x.item() for x in flat]
    return items[0] if len(items) == 1 else items


def read_model_meta_fast(path):
    """Read ONLY the GGUF metadata header (no full-file mmap).

    Returns the same dict as read_model_meta but ~1000x faster for large
    models (reads the header K/V section rather than mapping all weights).
    Returns None if the header can't be decoded (caller falls back).
    """
    import struct
    try:
        with open(path, "rb") as fh:
            if fh.read(4) != b"GGUF":
                return None
            fh.read(4)  # version
            fh.read(8)  # tensor_count
            kv_count = struct.unpack("<Q", fh.read(8))[0]
            kv = {}

            def rkey():
                n = struct.unpack("<Q", fh.read(8))[0]
                return fh.read(n).decode("utf-8", "replace")

            for _ in range(kv_count):
                k = rkey()
                vt = struct.unpack("<I", fh.read(4))[0]
                if vt == 8:  # string
                    n = struct.unpack("<Q", fh.read(8))[0]
                    kv[k] = fh.read(n).decode("utf-8", "replace")
                elif vt == 9:  # array
                    evt = struct.unpack("<I", fh.read(4))[0]
                    n = struct.unpack("<Q", fh.read(8))[0]
                    if evt == 8:  # array of length-prefixed strings (e.g. tokenizer vocab)
                        for _ in range(n):
                            slen = struct.unpack("<Q", fh.read(8))[0]
                            fh.read(slen)
                    else:
                        fmts = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i",
                                6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
                        if evt in fmts:
                            sz = struct.calcsize("<" + fmts[evt])
                            fh.read(sz * n)
                else:
                    fmts = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i",
                            6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
                    if vt in fmts:
                        kv[k] = struct.unpack("<" + fmts[vt],
                                              fh.read(struct.calcsize("<" + fmts[vt])))[0]
    except Exception:
        return None

    arch = str(kv.get("general.architecture", "").lower())
    if not arch:
        return None
    name = str(kv.get("general.name", os.path.basename(path)))
    n_head = int(kv.get(f"{arch}.attention.head_count", 0) or 0)
    n_head_kv = int(kv.get(f"{arch}.attention.head_count_kv", 0) or 0)
    if n_head_kv <= 0:
        n_head_kv = n_head
    return {
        "file": path, "name": name, "arch": arch,
        "n_layer": int(kv.get(f"{arch}.block_count", 0) or 0),
        "n_embd": int(kv.get(f"{arch}.embedding_length", 0) or 0),
        "n_head": n_head,
        "n_head_kv": n_head_kv,
        "ctx_train": int(kv.get(f"{arch}.context_length", 0) or 0),
        "chat_template": str(kv.get("tokenizer.chat_template", "") or ""),
        "sampling": _extract_sampling_from_kv(kv),
        "size_gb": os.path.getsize(path) / (1024 ** 3),
    }


def read_model_meta(path):
    """Return dict of arch facts for a GGUF. Tolerant of missing fields."""
    r = GGUFReader(path)
    f = r.fields
    arch = str(_gget(f["general.architecture"])).lower()
    name = str(_gget(f.get("general.name"))) if "general.name" in f else os.path.basename(path)
    n_head = 0
    n_head_kv = 0
    for hk in ("attention.head_count", "attention.head_count_kv"):
        key = f"{arch}.{hk}"
        if key in f:
            v = _gget(f[key])
            v = int(v) if v != "" else 0
            if hk == "attention.head_count":
                n_head = v
            else:
                n_head_kv = v
    if n_head_kv <= 0:
        n_head_kv = n_head
    return {
        "file": path, "name": name, "arch": arch,
        "n_layer": int(_gget(f.get(f"{arch}.block_count", "0")) or 0),
        "n_embd": int(_gget(f.get(f"{arch}.embedding_length", "0")) or 0),
        "n_head": n_head,
        "n_head_kv": n_head_kv,
        "ctx_train": int(_gget(f.get(f"{arch}.context_length", "0")) or 0),
        "chat_template": str(_gget(f.get("tokenizer.chat_template", "0")) or ""),
        "sampling": _extract_sampling_from_fields(f),
        "size_gb": os.path.getsize(path) / (1024 ** 3),
    }


def is_reasoning_model(meta):
    """Detect a reasoning/thinking-capable model from its chat template.

    A template that routes user prompts through a hidden chain-of-thought block
    (e.g. DeepSeek/Ornith <|start_of_fim|>-style fim or 'cot' / 'reasoning'
    tokens) is treated as a reasoning model. Non-reasoning chat templates return
    False.
    """
    tpl = (meta.get("chat_template") or "").lower()
    reasoning_markers = (
        "fim", "reasoning", "cot", "chain-of-thought", "think",
        "<|start_of_fim|>", "r1", "slash_thinking",
    )
    return any(m in tpl for m in reasoning_markers)


# ----------------------------------------------------------------------------
# Scan + pick
# ----------------------------------------------------------------------------
def scan_models():
    out = []
    for root, _, files in os.walk(MODELS_ROOT):
        for fn in files:
            if fn.endswith(".gguf") and not fn.endswith(".incomplete"):
                p = os.path.join(root, fn)
                try:
                    # fast path: read only GGUF header (no 27GB mmap)
                    meta = read_model_meta_fast(p)
                    if meta is None:
                        meta = read_model_meta(p)  # fallback to full reader
                    out.append(meta)
                except Exception as e:
                    print(f"  (skip {fn}: {e})")
    out.sort(key=lambda m: -m["size_gb"])
    return out


# ----------------------------------------------------------------------------
# Auto-tuning
# ----------------------------------------------------------------------------
def kv_bytes_per_token(meta, quant=KV_QUANT):
    """Approx K+V cache bytes/token. head_dim = n_embd/n_head."""
    head_dim = (meta["n_embd"] // meta["n_head"]) if meta["n_head"] else 128
    f16_bytes = 2.0 * meta["n_layer"] * meta["n_head_kv"] * head_dim * 2.0
    # q4_0 KV is ~0.5 byte per element vs 2 for fp16 => ~4x smaller; be conservative
    if quant in ("q4_0", "q4_1", "q5_0", "q5_1"):
        return f16_bytes / 4.0
    return f16_bytes


def tuned_context(meta, target_bytes):
    """Context that fits in `target_bytes` of KV, capped by train ctx."""
    if meta["ctx_train"]:
        hard = int(meta["ctx_train"])
    else:
        hard = 32768
    per_tok = kv_bytes_per_token(meta)
    if per_tok > 0:
        by_budget = int(target_bytes / per_tok)
    else:
        by_budget = hard
    ctx = min(hard, by_budget)
    # nice round number, power-of-two-ish
    ctx = max(2048, (ctx // 1024) * 1024)
    return ctx


# ---------------------------------------------------------------------------
# Dynamic memory detection (from the actual GPU/CPU card)
# ---------------------------------------------------------------------------
def read_total_ram_bytes():
    """Read TOTAL physical/unified memory from the real card (not hardcoded).

    Resolution order:
      1. $LLAMA_RAM_BYTES env override (explicit, e.g. for CI/container)
      2. macOS `sysctl -n hw.memsize`
      3. Linux /proc/meminfo MemTotal
      4. fallback: TOTAL_RAM_BYTES (48 GB) with a warning
    """
    env = (os.environ.get(LLAMA_RAM_ENV) or "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            if out.isdigit() and int(out) > 0:
                return int(out)
        except Exception:
            pass
    else:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb * 1024
        except Exception:
            pass
    print(f"[warn] could not detect total RAM; using {TOTAL_RAM_BYTES//(1024**3)} GB (set "
          f"{LLAMA_RAM_ENV} to override).", file=sys.stderr)
    return TOTAL_RAM_BYTES


def read_current_headroom_bytes(total_bytes=None):
    """Current-pressure OS/safety reserve for the fit gate.

    We must leave room for the OS + app runtime (on macOS unified memory this is
    the wired/unswappable portion plus a safety margin). Wired memory is measured
    from `vm_stat`, but it fluctuates heavily moment to moment, so a stable,
    meaningful reserve is `max(current_wired + 1GB, HEADROOM_MIN)` CAPPED at
    `LLAMA_HEADROOM_MAX_FRAC` of total (default 45%). HEADROOM_MIN (default
    OS_OVERHEAD = 3 GB) ensures a card never gets an absurdly tiny reserve just
    because wired is momentarily low, while the cap prevents over-reserving a big
    card. `$LLAMA_HEADROOM_BYTES` overrides for CI/containers.
    """
    env = (os.environ.get(LLAMA_HEADROOM_ENV) or "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    total = total_bytes or TOTAL_RAM_BYTES
    cap = int(total * LLAMA_HEADROOM_MAX_FRAC) if total else OS_OVERHEAD
    measured = None
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            wired = None
            page_size = None
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("Pages wired down:"):
                    wired = int(line.split(":")[1].strip().rstrip("."))
                if "page size of" in line and "(" in line:
                    page_size = int(line.split("page size of")[1].split()[0])
            if wired is not None and page_size:
                measured = wired * page_size + (1024 * 1024 * 1024)  # wired + 1 GB safety
        except Exception:
            pass
    if measured is None:
        measured = OS_OVERHEAD
    # floor + cap so the reserve is stable yet bounded by the real card.
    return min(max(measured, OS_OVERHEAD), cap)


# ---------------------------------------------------------------------------
# llama-server resolution
# ---------------------------------------------------------------------------
def resolve_llama_server():
    """Locate the llama-server binary.

    Resolution order:
      1. $LLAMA_SERVER env var (explicit override; must be an executable file)
      2. `llama-server` found on PATH
      3. ~/bin/llama-server (the symlink make install creates) — covers
         non-interactive shells where ~/bin is not on PATH

    If none yields a usable binary, raise SystemExit with a clear, actionable
    error so the launcher terminates instead of silently failing.
    """
    env = (os.environ.get("LLAMA_SERVER") or "").strip()
    if env:
        if os.path.isfile(env) and os.access(env, os.X_OK):
            return env
        raise SystemExit(
            f"[ERROR] LLAMA_SERVER='{env}' is not an executable llama-server.\n"
            "        Fix LLAMA_SERVER, or make 'llama-server' available on your PATH."
        )
    found = shutil.which("llama-server")
    if found:
        return found
    # Fall back to ~/bin/llama-server (installed/symlinked by `make install`).
    home_bin = os.path.join(os.path.expanduser("~"), "bin", "llama-server")
    if os.path.isfile(home_bin) and os.access(home_bin, os.X_OK):
        return home_bin
    raise SystemExit(
        "[ERROR] llama-server binary not found on PATH.\n"
        "        Make llama.cpp's llama-server reachable as 'llama-server', e.g.:\n"
        "          ln -s ~/repository/git/llama.cpp/build/bin/llama-server ~/bin/llama-server\n"
        "        (or set LLAMA_SERVER=/full/path/to/llama-server).\n"
        "        Build it first if needed: cmake -B build -DGGML_METAL=ON && cmake --build build --target llama-server"
    )


# ----------------------------------------------------------------------------
# HF top-tier trending discovery + download placement
# ----------------------------------------------------------------------------
def _hf_get(url, timeout=30):
    """GET a HF API url and return parsed JSON (list or dict).

    Raises SystemExit on non-200 so the CLI fails fast with a clear reason
    rather than silently returning nothing.
    """
    req = urllib.request.Request(url, headers={"User-Agent": HF_UA,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"[ERROR] HF API {e.code} for {url}")
    except urllib.error.URLError as e:
        raise SystemExit(f"[ERROR] HF API unreachable: {e.reason}")


def _trending_gguf_repos(limit=25):
    """Top trending GGUF repos from HF (time-weighted trendingScore), no auth.

    Returns a list of dicts with id, downloads, likes, trendingScore.
    """
    url = (f"{HF_API}?sort=trendingScore&direction=-1&filter=gguf"
           f"&limit={limit}")
    data = _hf_get(url)
    out = []
    for m in data:
        rid = m.get("id", "")
        if not _is_top_tier_repo(rid):
            continue
        out.append({
            "repo": rid,
            "downloads": m.get("downloads", 0),
            "likes": m.get("likes", 0),
            "trendingScore": m.get("trendingScore", 0),
        })
    # Guard against API order drift: ALWAYS rank trendingScore desc, top first.
    # (We request sort=trendingScore&direction=-1 but never trust the wire order.)
    return sorted(out, key=lambda r: r["trendingScore"], reverse=True)


def _is_top_tier_repo(repo):
    rl = repo.lower()
    return any(f in rl for f in TOP_TIER_FAMILIES)


def _repo_gguf_files(repo):
    """List .gguf files in a repo with real byte sizes (tree API)."""
    url = f"{HF_API}/{repo}/tree/main?recursive=true"
    data = _hf_get(url)
    files = []
    for f in data:
        path = f.get("path", "")
        size = f.get("size", 0) or 0
        if path.lower().endswith(".gguf") and size > 0:
            files.append({"path": path, "size": size, "size_bytes": size,
                          "size_gb": size / (1024 ** 3)})
    return files


def pick_tier_folder(size_bytes, total_ram_bytes=None):
    """Smallest GPU tier folder that holds this model, bounded by the card that runs it.

    The tier ladder (TIER_LADDER_GB) is a growing superset of the old 8/16/24/48
    buckets. Only ladder entries <= the card's total (detected or overridden) are
    "available"; a model's tier is the smallest AVAILABLE bucket >= its size, else
    the largest available bucket. So a 48 GB card keeps 8/16/24/48 exactly, while a
    512 GB card also has 96/128/.../512 and can label a 400 GB model truthfully.
    """
    total = total_ram_bytes if total_ram_bytes is not None else read_total_ram_bytes()
    card_gb = total / (1024 ** 3)
    available = [b for b in TIER_LADDER_GB if b <= card_gb]
    if not available:
        # degenerate tiny card: fall back to the smallest bucket
        return f"{TIER_LADDER_GB[0]}GB"
    gb = size_bytes / (1024 ** 3)
    for bucket in available:
        if gb <= bucket:
            return f"{bucket}GB"
    return f"{available[-1]}GB"  # bigger than any available bucket -> largest


def provider_dest_path(repo, filename, size_bytes, models_root=None, total_ram_bytes=None):
    """Provider-aware destination: ~/{MODELS_ROOT}/<owner>/<family>/<TierGB>/<file>."""
    root = models_root or MODELS_ROOT
    owner, family = _split_repo(repo)
    tier = pick_tier_folder(size_bytes, total_ram_bytes)
    return os.path.join(root, owner, family, tier, filename)


def _split_repo(repo):
    """'unsloth/Qwen3.8-27B-GGUF' -> ('unsloth', 'Qwen3.8-27B-GGUF')."""
    if "/" in repo:
        a, b = repo.split("/", 1)
        return a, b
    return repo, repo


def discover_top_tier(limit=10, total_ram_bytes=None, headroom_bytes=None,
                      min_trending_score=0, per_provider=2):
    """Ranked top-tier GGUF candidates that FIT the card, with real file sizes.

    Combines the three signals (trending + top-tier family + fit gate) using the
    dynamic total/headroom read from the card. For each trending provider (owner)
    it offers `per_provider` candidates at DIFFERENT quant sizes: the best
    (highest-fidelity that still fits comfortably) plus a lighter quant — so you
    get variety of BOTH provider and quantization quality, and the lower quants
    fit with comfortable margin instead of "barely fits". Returns a list of dicts:
      {repo, filename, size_gb, size_bytes, downloads, likes,
       trendingScore, tier_folder, dest_path}
    ranked best-quality first, then trending. `limit` = total candidates to return;
    `min_trending_score` = rating floor.
    """
    total = total_ram_bytes if total_ram_bytes is not None else read_total_ram_bytes()
    head = headroom_bytes if headroom_bytes is not None else read_current_headroom_bytes(total)
    kv_reserve = 1 * 1024 ** 3  # conservative KV headroom for the fit gate

    def candidate_files(repo):
        try:
            files = _repo_gguf_files(repo)
        except SystemExit:
            return []
        return sorted(
            [f for f in files
             # top-tier: real model file, big enough to be non-trivial
             if f["size_gb"] >= MIN_TOP_TIER_GB
             and not os.path.basename(f["path"]).startswith(("mmproj", "Qwen_VL"))
             and "-multi-of-" not in os.path.basename(f["path"])
             and "-00001-of-" not in os.path.basename(f["path"])
             and "0000" not in os.path.basename(f["path"])
             # MTP/mtp-* files are multi-token-prediction COMPANION heads, not the
             # main serviceable model — never offer them as a "top-tier" pick.
             and "mtp-" not in os.path.basename(f["path"]).lower()
             # "no lower models": skip low-fidelity IQ1/IQ2/IQ3 quants even when a
             # trending provider only offers those (a 27B at ~8-11 GB is poor quality).
             and not re.search(r"(?:-|_)(IQ[123]_|IQ[12]XS|IQ[123][0-9])", os.path.basename(f["path"]), re.I)
             ],
            key=lambda f: f["size_gb"], reverse=True,
        )

    # Per provider: take the best-fit (largest = highest quant) and then a clearly
    # LOWER quant (Q4/Q5/Q6 class, ~30%+ smaller) so you get high + lower quality
    # variety from each provider, and the lower quants fit with comfortable margin.
    # Both must fit comfortably.
    cands = []
    for repo_info in _trending_gguf_repos(limit=limit * 3):
        if repo_info["trendingScore"] < min_trending_score:
            continue
        repo = repo_info["repo"]
        files = candidate_files(repo)
        owner_picks = []
        best = None
        for f in files:
            if f["size_bytes"] + head + kv_reserve > total:
                continue  # doesn't fit comfortably -> skip
            if best is None:
                best = f["size_bytes"]
                owner_picks.append(f)
                continue
            # 2nd+ pick: must be a clearly-different (lower) quant tier (~25% smaller)
            if best - f["size_bytes"] >= 0.25 * best:
                owner_picks.append(f)
                best = f["size_bytes"]  # allow a further-lower quant after this one
            if len(owner_picks) >= per_provider:
                break
        for chosen in owner_picks:
            cands.append({
                "repo": repo,
                "filename": os.path.basename(chosen["path"]),
                "size_bytes": chosen["size_bytes"],
                "size_gb": chosen["size_gb"],
                "downloads": repo_info["downloads"],
                "likes": repo_info["likes"],
                "trendingScore": repo_info["trendingScore"],
                "tier_folder": pick_tier_folder(chosen["size_bytes"], total),
                "dest_path": provider_dest_path(repo, os.path.basename(chosen["path"]),
                                                chosen["size_bytes"], total_ram_bytes=total),
            })
    # Rank so a provider's high + lower quants stay together (group by provider).
    # Order PROVIDERS by what's TRENDING now (highest trendingScore first) — this is
    # "top-tier trending": the most popular models right now surface first, each with
    # its high + lower quant. (NOT by file size, which would surface the biggest file
    # of a niche provider over a genuinely trending one.)
    cands.sort(key=lambda c: (c["repo"], -c["size_gb"]))              # group by provider, high first
    providers = {}
    for c in cands:
        providers.setdefault(c["repo"], []).append(c)
    ordered = []
    for repo in sorted(providers, key=lambda r: -providers[r][0]["trendingScore"]):
        ordered.extend(providers[repo])
    return ordered[:limit]


def download_top_tier_candidate(cand, models_root=None):
    """Download a top-tier candidate via the real hf CLI (etag-aware, idempotent).

    ALWAYS delegates to scripts/hf_download.py in REFRESH mode, which runs
    `hf download`. That command etag/content-hashes the file against the Hub:
      - unchanged local file  -> hf no-ops fast, returns existing path
      - file UPDATED upstream (even SAME filename + SAME size, new bytes)
        -> the etag differs, hf re-fetches that one file
    We deliberately do NOT skip on mere existence/size, because a size-only
    guard would mask a same-name content update.
    """
    dest_dir = os.path.dirname(cand["dest_path"])
    final = cand["dest_path"]
    hf = (os.environ.get("HF_BIN") or "").strip() or shutil.which("hf")
    if not hf or not os.path.isfile(hf):
        # hf-env fallback used on the host (downloader also reads HF_BIN), then the
        # launcher's own venv (make install now bundles huggingface_hub[cli]).
        for _hf_cand in (os.path.expanduser("~/models/hf-env/bin/hf"),
                         os.path.join(os.path.dirname(sys.executable), "hf")):
            if os.path.isfile(_hf_cand):
                hf = _hf_cand
                break
        if not hf:
            raise SystemExit("[ERROR] 'hf' CLI not found. Install huggingface_hub "
                             "(or set HF_BIN) — top-tier download aborts (no fallback).")
    os.makedirs(dest_dir, exist_ok=True)
    os.environ["HF_BIN"] = hf   # downloader (hf_download.py) resolves HF_BIN to find hf
    dl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hf_download.py")
    label = f"top-tier-{os.path.basename(final)}".replace(".gguf", "")[:40]
    cmd = [sys.executable, dl, cand["repo"], cand["filename"], dest_dir, label, "1",
       str(cand.get("size_bytes", ""))]
    print(f"[top-tier] downloading {cand['repo']}::{cand['filename']} -> {dest_dir} "
          f"({cand['size_gb']:.2f} GB, tier {cand['tier_folder']})")
    rc = subprocess.call(cmd)
    if rc != 0 or not os.path.isfile(final) or os.path.getsize(final) < 100_000_000:
        raise SystemExit(f"[ERROR] top-tier download failed (rc={rc}); file missing/incomplete: {final}")
    # VERIFY the downloaded file by its GGUF metadata header (not just size/existence):
    # the file must actually be a readable GGUF model, not an HTML error page or a
    # truncated/corrupt stub that happens to have the right filename+size.
    meta = read_model_meta_fast(final)
    if meta is None:
        try:
            meta = read_model_meta(final)   # full reader fallback (handles unusual GGUFs)
        except Exception:
            meta = None                     # corrupt/non-GGUF -> reject, never raise
    if meta is None:
        raise SystemExit(f"[ERROR] downloaded file is not a valid GGUF model "
                         f"(metadata unreadable): {final}")
    print(f"[top-tier] verified downloaded model via GGUF metadata: "
          f"arch={meta.get('arch')}, name={meta.get('name')}, "
          f"layers={meta.get('n_layer')}, ctx_train={meta.get('ctx_train')}", flush=True)
    return final


def build_command(meta, ctx, port):
    global LLAMA_SERVER
    cmd = [LLAMA_SERVER,
           "-m", meta["file"],
           "--host", "0.0.0.0",
           "--port", str(port),
           "-c", str(ctx),
           "-ngl", "99",            # offload every layer to Metal
           "-fa", "on",             # flash attention
           "--jinja",               # use model chat template
           "-ctk", KV_QUANT, "-ctv", KV_QUANT,
           "-b", "2048", "-ub", "512",
           "--cont-batching",
           "--metrics"]
    # Sampling flags: use the model's author-recommended defaults
    # (general.sampling.*) when present, else fall back to the global preset.
    # Each flag and value is a SEPARATE argv element (llama.cpp treats one
    # "--temp 0.7" string as a single invalid argument). Emit EITHER model
    # defaults OR the preset, never both, never a flag twice.
    sampling = meta.get("sampling") or {}
    if sampling:
        for key, value in sampling.items():
            flag = SAMPLING_FLAG_MAP.get(key)
            if flag is None:
                continue  # unknown key: ignore, never raise
            cmd += [flag, value]
    else:
        cmd += list(SAMPLING)
    # reasoning-capable model: enable reasoning + return thoughts in
    # `message.reasoning_content` (deepseek format) so thinking is preserved.
    if is_reasoning_model(meta):
        cmd += ["--reasoning", "on", "--reasoning-format", "deepseek"]
    # parallel slots: 2 for small models, 1 for big
    np_slots = 2 if meta["size_gb"] < 10 else 1
    cmd += ["-np", str(np_slots)]
    # FIXED alias so the serving endpoint keeps the SAME name across model
    # switches. Clients (Hermes server, agent CLIs) pin one name and keep
    # working no matter which model is loaded. The real model id is still
    # served under the per-model filename alias as well.
    STABLE_ALIAS = "llm-local"
    cmd += ["--alias", STABLE_ALIAS]
    return cmd


def pretty(cmd):
    return " \\\n  ".join(cmd)


def stop_server_on_port(port):
    """Stop any llama-server already listening on `port` (one model at a time)."""
    try:
        out = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        out = ""
    if not out:
        return 0
    pids = [p for p in out.split() if p]
    for p in pids:
        subprocess.run(["kill", "-9", p], capture_output=True)
    return len(pids)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def _main_download_top_tier(args):
    """Discover + download currently-trending top-tier GGUFs that fit the card.

    --list   -> print the ranked candidates that fit, then exit (no download).
    --dry    -> download nothing; just report what would be downloaded/served.
    default  -> download the top `--count` candidates that fit, then serve the
                highest-ranked one (unless --list). Honors --port/--dry.
    """
    limit = max(1, args.count)
    per_provider = max(1, args.per_provider or 2)   # high + lower quant per provider
    print(f"[top-tier] detecting memory on the actual card ...")
    total = read_total_ram_bytes()
    head = read_current_headroom_bytes()
    print(f"[top-tier] total RAM = {total/(1024**3):.0f} GB, headroom (wired+safety) = "
          f"{head/(1024**3):.1f} GB")
    # `--count` = number of PROVIDERS; each yields per_provider quants (high+lower).
    cands = discover_top_tier(limit=max(1, limit * per_provider),
                              total_ram_bytes=total, headroom_bytes=head,
                              min_trending_score=args.min_trending_score,
                              per_provider=per_provider)
    if not cands:
        print("[top-tier] no trending top-tier GGUF model fits the available card right now. "
              "Nothing downloaded.")
        return
    total_str = f"top {limit} trending top-tier models that fit {total/(1024**3):.0f} GB:"
    if args.list:
        print(f"\n{total_str}\n")
        for i, c in enumerate(cands, 1):
            print(f"{i:2d}. [{c['trendingScore']:>4} trend] {c['size_gb']:7.2f} GB  "
                  f"{c['repo']}::{c['filename']}  -> {c['dest_path']}")
        print()
        return
    # --dry: print what would be downloaded, do NOT download or serve.
    if args.dry:
        print(f"\n[dry] would download top {len(cands)} top-tier provider(s):\n")
        for i, c in enumerate(cands, 1):
            print(f"{i:2d}. [{c['trendingScore']:>4} trend] {c['size_gb']:7.2f} GB  "
                  f"{c['repo']}::{c['filename']}  -> {c['dest_path']}")
        print("\n[dry] nothing was downloaded or served (--dry).")
        return
    # Download the top `limit` candidates (idempotent per provider). Any single
    # failure is retried (up to RETRIES); already-completed downloads are never
    # re-fetched (download_top_tier_candidate etag-checks the Hub), so a retry
    # only resumes/completes the failed one. A persistent failure doesn't abort
    # the batch — remaining providers are still attempted.
    RETRIES = 3
    completed = []
    for i, c in enumerate(cands, 1):
        print(f"\n[{i}/{len(cands)}] downloading top-tier candidate: {c['repo']}::{c['filename']}")
        ok = False
        for attempt in range(1, RETRIES + 1):
            try:
                download_top_tier_candidate(c)
                ok = True
                break
            except SystemExit as e:
                print(f"  attempt {attempt}/{RETRIES} failed for {c['repo']}: "
                      f"{str(e).splitlines()[0] if str(e) else 'download error'}",
                      file=sys.stderr)
                if attempt < RETRIES:
                    time.sleep(2)
        if ok:
            completed.append(c)
        else:
            print(f"  SKIPPED {c['repo']} after {RETRIES} failed attempts.", file=sys.stderr)
    if not completed:
        print("[top-tier] nothing could be downloaded.")
        sys.exit(1)
    print(f"\n[top-tier] completed {len(completed)}/{len(cands)} provider(s).")
    print("[top-tier] downloaded models are available to serve. Use the normal "
          "launch path (e.g. `llama-ai <model-name>`) to start llama-server — "
          "`--download-top-tier` only downloads; it never auto-starts the server.")
    for i, c in enumerate(completed, 1):
        print(f"  {i}. {c['repo']}::{c['filename']}  -> {c['dest_path']}")


def _serve_chosen(chosen, args):
    """Tune + print + optionally launch llama-server for a chosen local meta dict."""
    kv_budget = read_total_ram_bytes() - OS_OVERHEAD - int(chosen["size_gb"] * 1024 ** 3)
    if kv_budget < 0:
        kv_budget = 512 * 1024 * 1024
    ctx = tuned_context(chosen, kv_budget)
    global LLAMA_SERVER
    LLAMA_SERVER = resolve_llama_server()
    cmd = build_command(chosen, ctx, args.port)

    print(f"\nModel : {chosen['name']} ({chosen['arch']})")
    print(f"File  : {chosen['file']}")
    print(f"Layers: {chosen['n_layer']}, dim={chosen['n_embd']}, heads={chosen['n_head']}, kv_heads={chosen['n_head_kv']}")
    print(f"Train ctx: {chosen['ctx_train']}, KV/tok ~= {kv_bytes_per_token(chosen)/1e6:.1f} MB")
    print(f'Serving at http://127.0.0.1:{args.port}, context = {ctx} tokens\n')
    print("Command:\n  " + pretty(cmd) + "\n")
    print("Log: " + os.path.join(os.path.dirname(chosen["file"]), ".run.log"))
    print("Stop with Ctrl-C.\n")

    if args.dry:
        return

    stopped = stop_server_on_port(args.port)
    if stopped:
        print(f"Stopped {stopped} existing listener(s) on port {args.port} (one model at a time).")
        time.sleep(1)

    with open(os.path.join(os.path.dirname(chosen["file"]), ".run.log"), "a") as lf:
        lf.write(f"\n[{time.ctime()}] launching {os.path.basename(chosen['file'])}\n")
        lf.write(" ".join(cmd) + "\n")
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nStopped.")
    except FileNotFoundError:
        print(f"\n[ERROR] llama-server binary disappeared after resolution ({LLAMA_SERVER}).\n"
              "        Reinstall or put 'llama-server' on PATH and retry.")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Pick a GGUF model and launch llama-server tuned for it")
    ap.add_argument("model", nargs="?", help="substring of model filename to select")
    ap.add_argument("--list", action="store_true", help="just list models")
    ap.add_argument("--port", type=int, default=11434)
    ap.add_argument("--dry", action="store_true", help="print command without running")
    ap.add_argument("--download-top-tier", action="store_true",
                    help="discover + download the currently-trending top-tier GGUF model(s) "
                         "that fit the actual GPU/CPU card. DOWNLOAD ONLY — never auto-starts "
                         "llama-server; serve a downloaded model separately with `llama-ai <name>`.")
    ap.add_argument("--count", type=int, default=5,
                    help="with --download-top-tier: number of distinct PROVIDERS to download "
                         "(each yields high + lower quants, default 5 = variety of what's popular)")
    ap.add_argument("--per-provider", type=int, default=2,
                    help="with --download-top-tier: quants per provider (default 2 = best + a "
                         "lower Q4/Q5/Q6 so each fits comfortably, not just Q8)")
    ap.add_argument("--min-trending-score", type=int, default=0,
                    help="with --download-top-tier: only consider repos whose HF trendingScore "
                         "is >= this (0 = any trending that fits). A rating floor so niche/"
                         "unrated models don't show.")
    args = ap.parse_args()

    # --download-top-tier path (trending + top-tier family + dynamic fit gate).
    if args.download_top_tier:
        _main_download_top_tier(args)
        return

    models = scan_models()
    if not models:
        print(f"No .gguf models found under {MODELS_ROOT}")
        sys.exit(1)

    if args.list:
        for i, m in enumerate(models, 1):
            print(f"{i:2d}. {m['size_gb']:7.2f} GB  {m['file']}  [ctx={m['ctx_train']}]")
        return

    # selection
    chosen = None
    if args.model:
        cands = [m for m in models if args.model.lower() in os.path.basename(m["file"]).lower()]
        if not cands:
            print(f"No model matches '{args.model}'. Use --list")
            sys.exit(1)
        if len(cands) > 1:
            print(f"'{args.model}' matches {len(cands)} models. Pick exactly one:\n")
            for i, m in enumerate(cands, 1):
                print(f"  {i}. {m['size_gb']:7.2f} GB  {os.path.basename(m['file'])}")
            print()
            try:
                sel = int(input("Pick number (or 0 to cancel): "))
            except (EOFError, ValueError):
                sel = -1
            if sel < 1 or sel > len(cands):
                print("cancel"); sys.exit(2)
            chosen = cands[sel - 1]
        else:
            chosen = cands[0]
        print(f"Selected: {chosen['file']}")
    else:
        print(f"\nModels under {MODELS_ROOT}:\n")
        for i, m in enumerate(models, 1):
            print(f"{i:2d}. {m['size_gb']:7.2f} GB  {os.path.basename(m['file'])}")
        try:
            sel = int(input("\nPick number: "))
        except (EOFError, ValueError):
            print("cancel"); sys.exit(2)
        chosen = models[sel - 1]

    # tune
    kv_budget = TOTAL_RAM_BYTES - OS_OVERHEAD - int(chosen["size_gb"] * 1024 ** 3)
    if kv_budget < 0:
        kv_budget = 512 * 1024 * 1024
    ctx = tuned_context(chosen, kv_budget)
    # resolve llama-server (LLAMA_SERVER override, then PATH) BEFORE building the
    # command — terminates with a clear error if the binary is missing.
    global LLAMA_SERVER
    LLAMA_SERVER = resolve_llama_server()
    cmd = build_command(chosen, ctx, args.port)

    print(f"\nModel : {chosen['name']} ({chosen['arch']})")
    print(f"File  : {chosen['file']}")
    print(f"Layers: {chosen['n_layer']}, dim={chosen['n_embd']}, heads={chosen['n_head']}, kv_heads={chosen['n_head_kv']}")
    print(f"Train ctx: {chosen['ctx_train']}, KV/tok ~= {kv_bytes_per_token(chosen)/1e6:.1f} MB")
    print(f"Serving at http://127.0.0.1:{args.port}, context = {ctx} tokens\n")
    print("Command:\n  " + pretty(cmd) + "\n")
    print("Log: " + os.path.join(os.path.dirname(chosen["file"]), ".run.log"))
    print("Stop with Ctrl-C.\n")

    if args.dry:
        return

    # one model at a time: stop anything already on the target port
    stopped = stop_server_on_port(args.port)
    if stopped:
        print(f"Stopped {stopped} existing listener(s) on port {args.port} (one model at a time).")
        time.sleep(1)

    with open(os.path.join(os.path.dirname(chosen["file"]), ".run.log"), "a") as lf:
        lf.write(f"\n[{time.ctime()}] launching {os.path.basename(chosen['file'])}\n")
        lf.write(" ".join(cmd) + "\n")
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nStopped.")
    except FileNotFoundError:
        print(f"\n[ERROR] llama-server binary disappeared after resolution ({LLAMA_SERVER}).\n"
              "        Reinstall or put 'llama-server' on PATH and retry.")
        sys.exit(1)


if __name__ == "__main__":
    main()
