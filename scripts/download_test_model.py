#!/usr/bin/env python3
"""Download the lightweight health-check model into the right GPU tier.

Ensures the test model used by the loop's `health` stage exists at
~/models/Qwen/8GB/qwen2.5-0.5b-instruct-q4_0.gguf (a ~340 MB Q4 0.5B model that
runs in under 1 GB VRAM). If the tier folder is missing it creates it.

Usage:
    make download-test-model            # idempotent; skips if already present
    python3 scripts/download_test_model.py
"""
from __future__ import annotations

import os
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

# Reuse the existing HF downloader (reads HF_TOKEN from ~/.zshrc).
dl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hf_dl.py")
print(f"[{LABEL}] downloading {REPO_ID}::{FILENAME} -> {DEST}")
sys.exit(subprocess.call([sys.executable, dl, REPO_ID, FILENAME, DEST, LABEL]))