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
import os
import shutil
import subprocess
import sys
import time

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


# ----------------------------------------------------------------------------
# llama-server resolution
# ----------------------------------------------------------------------------
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
            cmd += [SAMPLING_FLAG_MAP[key], value]
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
def main():
    ap = argparse.ArgumentParser(description="Pick a GGUF model and launch llama-server tuned for it")
    ap.add_argument("model", nargs="?", help="substring of model filename to select")
    ap.add_argument("--list", action="store_true", help="just list models")
    ap.add_argument("--port", type=int, default=11434)
    ap.add_argument("--dry", action="store_true", help="print command without running")
    args = ap.parse_args()

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
