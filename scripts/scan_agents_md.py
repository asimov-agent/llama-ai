#!/usr/bin/env python3
"""test-agents-read auxiliary: guard AGENTS.md against Hermes rulebook blocking.

Fail-closed scanner proving the repo's AGENTS.md would load into a Hermes
worker's system prompt (i.e. does NOT match a context-file threat pattern).

Mechanism (reuse, never reimplement): it imports Hermes's CANONICAL scanner,
``tools.threat_patterns.scan_for_threats(content, scope="context")``, exactly
the function ``agent/prompt_builder.py`` uses to decide whether a context file
(AGENTS.md, CLAUDE.md, .cursorrules, ...) is blocked. Locating the module:

  1. ``$HERMES_PYTHON_SRC_ROOT`` — the site-packages / source root of the
     installed hermes-agent (set in the test container Dockerfile, and present
     as ``HERMES_PYTHON_SRC_ROOT``/``HERMES_PYTHON`` in cron workers);
  2. ``$HERMES_PYTHON`` — path of the hermes venv python (its dirname is added);
  3. ``~/.hermes/hermes-agent`` — the default checkout on the dev host.

If none of these yield an importable hermes-agent, exit non-zero with a clear
message (we refuse to "reinvent the wheel" with a local copy).

Treats AGENTS.md strictly as DATA: it is regex-scanned, never executed.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    for var in ("HERMES_PYTHON_SRC_ROOT", "HERMES_PYTHON"):
        raw = os.environ.get(var, "").strip()
        if not raw:
            continue
        p = Path(raw)
        if var == "HERMES_PYTHON":  # path to a python binary
            p = p.parent.parent.parent if p.name.startswith("python") else p
        if p not in roots:
            roots.append(p)
    # default dev-host checkout
    default = Path.home() / ".hermes" / "hermes-agent"
    if default not in roots:
        roots.append(default)
    # pip-installed site-packages fallback (contains tools/threat_patterns.py)
    for sp in sys.path:
        cand = Path(sp)
        if (cand / "tools").is_dir():
            if cand not in roots:
                roots.append(cand)
    return roots


def _load_scan_for_threats():
    """Import the REAL Hermes scanner. Returns callable or raises.

    Resolution order:
      1. an installed hermes-agent (via $HERMES_PYTHON_SRC_ROOT /
         $HERMES_PYTHON / ~/.hermes/hermes-agent / site-packages);
      2. the vendored canonical copy at scripts/hermes/threat_patterns.py
         (a verbatim copy of the authoritative module — Hermes forbids
         `pip install hermes-agent` ("Building wheels or sdists is not
         supported"), so we vendor the single stdlib-only file instead of
         reimplementing detection).
    """
    for root in _candidate_roots():
        try:
            sys.path.insert(0, str(root))
            from tools.threat_patterns import scan_for_threats  # noqa: PLC0415

            return scan_for_threats
        except ModuleNotFoundError:
            continue
    # Vendored canonical copy (stdlib-only; works in any container). Load by
    # absolute path via importlib so it resolves regardless of how sys.path was
    # scrubbed (robust under `-c`, cron workers, and any cwd).
    vendored = Path(__file__).resolve().parent / "hermes" / "threat_patterns.py"
    if vendored.is_file():
        import importlib.util

        spec = importlib.util.spec_from_file_location("hermes_threat_patterns", vendored)
        if spec and spec.loader:  # pragma: no branch - both set for a real file
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            sys.modules["hermes_threat_patterns"] = mod
            return mod.scan_for_threats
    raise RuntimeError(
        "Hermes threat-pattern module not found. Install hermes-agent, set "
        "HERMES_PYTHON_SRC_ROOT, or ensure scripts/hermes/threat_patterns.py "
        "(the vendored canonical copy) is present."
    )


def _offending_line(content: str, pattern) -> str:
    """Return the first line matching *pattern*, or '' if none."""
    for ln in content.splitlines():
        if pattern.search(ln):
            return ln.strip()
    return ""


def main() -> int:
    targets = [a for a in sys.argv[1:] if a.endswith((".md",))] or ["AGENTS.md"]
    scan = _load_scan_for_threats()
    any_fail = False
    for rel in targets:
        path = Path(rel)
        if not path.is_file():
            print(f"[test-agents-read] {rel}: MISSING", flush=True)
            any_fail = True
            continue
        content = path.read_text(encoding="utf-8").replace("\ufeff", "", 1)
        try:
            findings = scan(content, scope="context")
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[test-agents-read] {rel}: SCAN ERROR {exc}", flush=True)
            any_fail = True
            continue
        if findings:
            any_fail = True
            print(f"[test-agents-read] BLOCKED: {rel} contains threat pattern(s):", flush=True)
            for pid in findings:
                print(f"  - {pid}", flush=True)
            # map first finding to a line for debugging
            import importlib

            tp_src = None
            try:
                import tools.threat_patterns as tp  # noqa: PLC0415

                tp_src = tp
            except ModuleNotFoundError:
                pass
            if tp_src is not None:
                for pid in findings:
                    m = pid.split("_U+")[0] if pid.startswith("invisible_unicode") else pid
                    # print line for the most prominent exfil/injection pids
                    if any(m == x or m in x for x in ("exfil_curl", "prompt_injection")):
                        ln = next(
                            (
                                l.strip()
                                for l in content.splitlines()
                                if "curl" in l.lower() or "${" in l
                            ),
                            "",
                        )
                        if ln:
                            print(f"  ~ line: {ln}", flush=True)
        else:
            print(f"[test-agents-read] CLEAN: {rel} (no threat patterns)", flush=True)
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())