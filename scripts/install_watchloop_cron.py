#!/usr/bin/env python3
"""Install / uninstall the llama-ai watch-loop host crontab entry (issue #65).

The watch loop is a `*/20 * * * *` crontab entry that launches the dispatcher
(`scripts/watchloop_dispatch.py`) as a `project-manager` Hermes session so the
repo keeps driving issues/PRs between interactive sessions.

This helper makes install/uninstall idempotent and per-OS aware (macOS vs Linux
`python3`/PATH), guarding against duplicate entries and preserving every unrelated
crontab line. It shells out to the real `crontab` binary (the only authority for
the host's crontab); the hermetic tests stub `subprocess.run`/`platform` so no
real crontab, network, or container is touched.

Usage:
    python3 scripts/install_watchloop_cron.py install
    python3 scripts/install_watchloop_cron.py uninstall
    python3 scripts/install_watchloop_cron.py snapshot   # print the entry (no write)
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import subprocess
import sys

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DISPATCHER = f"{REPO}/scripts/watchloop_dispatch.py"
LOG = f"{REPO}/.watchloop/run/dispatch.log"

# A regex that matches the watch-loop crontab line regardless of how its PATH /
# python colon-separator changed over time, so uninstall is robust across edits.
WATCHLINE_RE = re.compile(
    # Standard 5-field cron: `*/20 * * * *` then the dispatcher command.
    r"^\s*\*/20\s+\*\s+\*\s+\*\s+\*.*watchloop_dispatch\.py\b.*$",
    re.MULTILINE,
)


def _platform() -> str:
    """Return the normalized platform name; injectable via env for hermetic tests."""
    return os.environ.get("_WATCHLOOP_TEST_PLATFORM") or platform.system().lower()


def _python_candidates() -> list[str]:
    """Ordered python3 candidates for this platform (first found wins)."""
    sysp = _platform()
    if sysp == "darwin":
        # macOS: prefer a real python3 (often keg-only in /opt/homebrew); fall back
        # to a plain `python3` resolved from the caller's PATH.
        if os.environ.get("WATCHLOOP_CRON_PYTHON"):
            return [os.environ["WATCHLOOP_CRON_PYTHON"]]
        return ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "python3"]
    # Linux and everything else: resolve python3 from PATH.
    return [os.environ.get("WATCHLOOP_CRON_PYTHON", "python3")]


def resolve_python() -> str:
    """Pick the python3 to embed in the crontab line (deterministic per platform)."""
    for cand in _python_candidates():
        if cand.startswith("/"):
            if os.path.exists(cand):
                return cand
        else:
            # bare name: trust PATH (don't probe; crontab runs with a restricted PATH).
            return cand
    return "python3"


def render_entry(python_bin: str | None = None) -> str:
    """The canonical `*/20` watch-loop crontab line.

    Includes the repo PATH prefix so `llama-server`/`hf` resolve in cron's minimal
    environment, and `HERMES_PROFILE=project-manager` so the dispatcher runs under
    the project-manager profile.
    """
    py = python_bin or resolve_python()
    path = ("/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            ":${HOME}/.local/bin")
    return (
        f"*/20 * * * * cd {REPO} && export PATH={path} && "
        f"HERMES_PROFILE=project-manager {py} {DISPATCHER} >> {LOG} 2>&1"
    )


def _current_lines() -> list[str]:
    """Read the current crontab as a list of lines (empty list => no crontab/error)."""
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except OSError:
        print("ERROR: `crontab` binary not found on PATH.", file=sys.stderr)
        return []
    if out.returncode != 0:
        # `crontab -l` returns non-zero when no crontab exists yet (some platforms);
        # treat as empty rather than failing.
        return []
    return out.stdout.splitlines()


def _write_lines(lines: list[str]) -> None:
    """Replace the entire crontab with *lines*."""
    text = "\n".join(lines)
    if text and not text.endswith("\n"):
        text += "\n"
    subprocess.run(["crontab", "-"], input=text, text=True, capture_output=True)


def install(dry_run: bool = False) -> int:
    """Add the watch-loop entry iff absent. Returns 0 on success."""
    lines = _current_lines()
    entry = render_entry()
    already = any(WATCHLINE_RE.match(ln) for ln in lines)
    if dry_run:
        print(f"[dry-run] would append: {entry}")
        return 0
    if already:
        print("watch-loop crontab entry already present; nothing to do.")
        return 0
    lines.append(entry)
    _write_lines(lines)
    print(f"installed watch-loop crontab entry:\n  {entry}")
    return 0


def uninstall(dry_run: bool = False) -> int:
    """Remove the watch-list entry, preserving unrelated lines. Returns 0."""
    lines = _current_lines()
    kept = [ln for ln in lines if not WATCHLINE_RE.search(ln)]
    removed = len(lines) - len(kept)
    if dry_run:
        return 0
    if removed == 0:
        print("no watch-loop crontab entry found; nothing to remove.")
        return 0
    _write_lines(kept)
    print(f"removed {removed} watch-loop crontab line(s); {len(kept)} unrelated line(s) preserved.")
    return 0


def render_snapshot() -> str:
    """A human-readable preview of the canonical entry (no side effects)."""
    return f"# llama-ai watch loop (crontab)\n{render_entry()}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Install/uninstall the llama-ai watch-loop crontab entry")
    ap.add_argument("action", choices=["install", "uninstall", "snapshot"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--python", default=None, help="python3 to embed (overrides per-OS auto)")
    args = ap.parse_args(argv)
    if args.python:
        os.environ["WATCHLOOP_CRON_PYTHON"] = args.python
    if args.action == "snapshot":
        print(render_snapshot())
        return 0
    if args.action == "install":
        return install(dry_run=args.dry_run)
    return uninstall(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
