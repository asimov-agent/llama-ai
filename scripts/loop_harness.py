#!/usr/bin/env python3
"""Basic loop harness for llama-ai.

Runs the verification stages in a fixed order and fails closed: if any stage
exits non-zero, the remaining stages still run (to report all failures) but the
final exit code is non-zero.

Stages (order matters):
    0. image    — build the containerized test image              -> make test-image
    1. download — ensure the lightweight health-test model exists -> make download-test-model
    2. lint     — every tracked text file ends with a newline     -> make lint
    3. unit     — hermetic unit tests                             -> make test-unit
    4. install  — verify make install artifacts + host run        -> make test-install
    5. health   — launch tiny model, answer 'hi' on endpoint      -> make test-health
    6. test     — full fast suite                                 -> make test
    7. openspec — validate the active OpenSpec change             -> make openspec-validate NAME=<active>

Usage:
    python3 scripts/loop_harness.py            # auto-detect active change
    python3 scripts/loop_harness.py NAME=<chg> # validate a specific change
    make loop                                  # equivalent wrapper
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# stages: (name, [command parts])
STAGES = [
    # 0. build the containerized test image (idempotent; needed by all stages).
    ("image", ["make", "test-image"]),
    # 1. ensure the lightweight health-test model is present (idempotent).
    ("download", ["make", "download-test-model"]),
    # linefeed lint: every tracked text file must end with a newline.
    ("lint", ["make", "lint"]),
    # hermetic gates FIRST after lint (cheap, no deps).
    ("unit", ["make", "test-unit"]),
    # host install test (needs ~/bin + ~/models; skips cleanly if absent)
    ("install", ["make", "test-install"]),
    # end-to-end health: launch the tiny model, answer 'hi' on the endpoint
    ("health", ["make", "test-health"]),
    # full fast suite
    ("test", ["make", "test"]),
    # openspec validate of the active (or given) change
    ("openspec", ["make", "openspec-validate", "NAME=%s" % os.environ.get("NAME", "llama-ai-tooling")]),
]


def run_stage(name, cmd):
    print(f"\n=== [{name}] {' '.join(cmd)} ===", flush=True)
    proc = subprocess.run(cmd, cwd=str(REPO))
    status = "PASS" if proc.returncode == 0 else "FAIL"
    print(f"--- [{name}] {status} (rc={proc.returncode}) ---", flush=True)
    return proc.returncode == 0


def main() -> int:
    results = {}
    overall = 0
    for name, cmd in STAGES:
        ok = run_stage(name, cmd)
        results[name] = "PASS" if ok else "FAIL"
        overall |= (0 if ok else 1)
    print("\n================ LOOP SUMMARY ================")
    for name, status in results.items():
        print(f"  {name:<10} {status}")
    print("==============================================")
    print("RESULT:", "GREEN" if overall == 0 else "RED")
    return overall


if __name__ == "__main__":
    raise SystemExit(main())
