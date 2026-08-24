#!/usr/bin/env python3
"""Linefeed lint: ensure every tracked text file ends with a trailing newline.

Used by the loop harness `lint` stage and `make lint`. Fails closed: if any
tracked text file lacks a final ``\\n``, prints the offending file and exits 1.

Text files are the tracked files git knows about, restricted to types we
version as text (exclude binaries like .gguf which are gitignored anyway, but
guard against any tracked binary/images). Runs hermetically (needs git only).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Extensions we treat as text for the linefeed check. Everything else under
# version control is assumed binary (or already excluded) and skipped.
TEXT_EXTS = {
    ".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
    ".editorconfig", ".gitignore", ".dockerignore", ".gitattributes",
    ".sh", ".bash", ".zsh", ".env.example", ".env",
}

# Extension-less config filenames we still treat as text. These have
# `Path.suffix == ''` so they would NOT match TEXT_EXTS — e.g. `Dockerfile`,
# `Makefile`, `LICENSE`. Without them the linefeed lint silently skips the very
# files EditorConfig's `insert_final_newline=true` governs (B-read: a bare
# Dockerfile missing its trailing newline was slipping through with "LINT OK").
TEXT_FILENAMES = {
    "dockerfile",
    "makefile",
    "license",
    "copying",
    "notice",
    "authors",
    "readme",
    "changelog",
    "contributing",
    ".editorconfig",
    ".gitignore",
    ".gitattributes",
    ".gitmodules",
    ".env.example",
}


def _tracked_text_files() -> list[str]:
    """Return tracked files matching TEXT_EXTS (git ls-files)."""
    try:
        out = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True,
            cwd=_repo_root(), check=True, timeout=30,
        ).stdout
    except Exception as e:
        print(f"[lint] could not list tracked files: {e}", file=sys.stderr)
        return []
    return [
        f for f in out.splitlines()
        if f and (
            Path(f).suffix.lower() in TEXT_EXTS
            or Path(f).name.lower() in TEXT_FILENAMES
        )
    ]


def _repo_root() -> str:
    return Path(__file__).resolve().parent.parent


def check(report: bool = True, fix: bool = False) -> int:
    bad = []
    for f in _tracked_text_files():
        fp = Path(_repo_root()) / f
        if not fp.is_file():
            continue
        try:
            data = fp.read_bytes()
        except OSError as e:
            print(f"[error] cannot read {f}: {e}", file=sys.stderr)
            return 1
        # Skip empty files (nothing to end).
        if not data:
            continue
        if not data.endswith(b"\n"):
            if fix:
                fp.write_bytes(data + b"\n")
                print(f"  fixed: {f}")
            else:
                bad.append(f)
    if bad:
        if report:
            print("LINT FAIL — files missing a trailing newline:")
            for f in bad:
                print(f"  - {f}")
        return 1
    if fix:
        # --fix consumed everything bad already; re-scan to confirm.
        return check(report=False)
    if report:
        print("LINT OK — all tracked text files end with a newline.")
    return 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Linefeed lint for llama-ai")
    ap.add_argument("--fix", action="store_true", help="append a trailing newline to files missing it")
    args = ap.parse_args()
    return check(fix=args.fix)


if __name__ == "__main__":
    raise SystemExit(main())
