#!/usr/bin/env python3
"""Download the lightweight health-check model into the right GPU tier.

Ensures the test model used by the loop's `health` stage exists at
~/models/Qwen/8GB/qwen2.5-0.5b-instruct-q4_0.gguf (a ~340 MB Q4 0.5B model that
runs in under 1 GB VRAM). If the tier folder is missing it creates it.

Always downloads through the official `hf`(huggingface_hub) CLI with the resume/
retry-throttle logic in hf_dl.py — no ad-hoc requests fallback. The `hf` binary
is found on PATH first (the test image bundles it), then the host venv path:
    - host:  ~/models/hf-env/bin/hf   (dev machine)
    - CI/container:  `hf` on PATH     (installed into the test image)

Usage:
    make download-test-model            # idempotent; skips if already present
    python3 scripts/download_test_model.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
DEST = os.path.join(HOME, "models", "Qwen", "8GB")
REPO_ID = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
FILENAME = "qwen2.5-0.5b-instruct-q4_0.gguf"
LABEL = "qwen05b-health"

os.makedirs(DEST, exist_ok=True)
final = os.path.join(DEST, FILENAME)
if os.path.isfile(final) and os.path.getsize(final) > 100_000_000:
    print(f"[{LABEL}] already present: {final} ({os.path.getsize(final)/1e9:.2f} GB) -> done")
    sys.exit(0)

# Locate the `hf`(huggingface_hub) CLI. It is bundled into the test image (and
# installed on the host), so `which hf` always resolves it — the download runs
# through the SAME container image on CI and locally, so the binary is the one
# version, found the same way everywhere. NO host-path or ad-hoc fallback.
HF_BIN = shutil.which("hf")
if not HF_BIN or not os.path.isfile(HF_BIN):
    print(
        f"[{LABEL}] ERROR: 'hf' CLI not found on PATH. Install huggingface_hub, "
        f"or set HF_BIN. Aborting (no fallback downloader).",
        file=sys.stderr,
    )
    sys.exit(2)

# The throttled/resumable downloader (hf_dl.py) shells out to $HF_BIN.
os.environ.setdefault("HF_BIN", HF_BIN)
dl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hf_dl.py")
print(f"[{LABEL}] downloading {REPO_ID}::{FILENAME} -> {DEST} (via {HF_BIN})")
sys.exit(subprocess.call([sys.executable, dl, REPO_ID, FILENAME, DEST, LABEL]))
