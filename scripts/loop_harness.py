#!/usr/bin/env python3
"""Basic loop harness for llama-ai.

Runs the verification stages in a fixed order and fails closed: if any stage
exits non-zero, the remaining stages still run (to report all failures) but the
final exit code is non-zero.

Stages (order matters):
    1. test      — run the full pytest suite   -> make test
    2. install   — verify make install artifacts + host model run -> make test-install
    3. openspec  — validate the active OpenSpec change            -> make openspec-validate NAME=<active>

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
    # hermetic gates first
    ("unit", ["make", "test-unit"]),
    # host install test (needs ~/bin + ~/models; skips cleanly if absent)
    ("install", ["make", "test-install"]),
    # full suite
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