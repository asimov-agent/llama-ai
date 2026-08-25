#!/usr/bin/env python3
"""Serialize containerized make targets so parallel workers never race nerdctl.

Usage: serialized-make.py <lockfile> -- <make args...>
Runs `make <args>` while holding an exclusive fcntl lock on <lockfile>.

This is the ONLY way a watch-loop worker (or the dispatcher) may invoke the
containerized `make` targets (openspec-*, test-unit, test-install, lint, lint-fix,
test). Use it from ANY worktree; the lock is global to the repo's .watchloop/run.
"""
import fcntl
import os
import subprocess
import sys

if len(sys.argv) < 3 or "--" not in sys.argv:
    print("usage: serialized-make <lockfile> -- <make args...>", file=sys.stderr)
    sys.exit(2)

lockfile = sys.argv[1]
os.makedirs(os.path.dirname(lockfile), exist_ok=True)
make_args = sys.argv[sys.argv.index("--") + 1 :]
if not make_args:
    make_args = ["test"]

with open(lockfile, "w") as lf:
    fcntl.flock(lf, fcntl.LOCK_EX)  # blocks until exclusive lock held
    try:
        rc = subprocess.call(["make"] + make_args)
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN)
sys.exit(rc if "rc" in dir() else 0)
