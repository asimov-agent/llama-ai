#!/usr/bin/env python3
"""test-agents-read auxiliary: guard AGENTS.md against Hermes rulebook blocking.

Fail-closed scanner proving the repo's AGENTS.md would load into a Hermes
worker's system prompt (i.e. does NOT match a context-file threat pattern).

Mechanism (reuse, never reimplement): it imports Hermes's CANONICAL scanner,
``tools.threat_patterns.scan_for_threats(content, scope="context")`` — exactly
the function ``agent/prompt_builder.py`` uses to decide whether a context file
(AGENTS.md, CLAUDE.md, .cursorrules, ...) is blocked.

``hermes-agent`` is a real PyPI dependency of this project
(tools/requirements-dev.in -> requirements-dev.txt, pinned ==0.19.0, Python
>=3.11), so ``from tools.threat_patterns import scan_for_threats`` resolves from
the installed site-packages in the test container, CI, and the dev host. We do
NOT vendor or copy the module — it is maintained as a 3rd-party dependency.

Treats AGENTS.md strictly as DATA: it is regex-scanned, never executed.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    targets = [a for a in sys.argv[1:] if a.endswith((".md",))] or ["AGENTS.md"]
    try:
        from tools.threat_patterns import scan_for_threats  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        print(
            "[test-agents-read] ERROR: hermes-agent not installed. Install it via "
            "tools/requirements-dev.in (`pip install -r tools/requirements-dev.txt`). "
            f"({exc})",
            flush=True,
        )
        return 2

    any_fail = False
    for rel in targets:
        path = Path(rel)
        if not path.is_file():
            print(f"[test-agents-read] {rel}: MISSING", flush=True)
            any_fail = True
            continue
        content = path.read_text(encoding="utf-8").replace("\ufeff", "", 1)
        findings = scan_for_threats(content, scope="context")
        if findings:
            any_fail = True
            print(
                f"[test-agents-read] BLOCKED: {rel} contains threat pattern(s): "
                + ", ".join(findings),
                flush=True,
            )
            for ln in content.splitlines():
                low = ln.lower()
                if "curl" in low or "wget" in low or "ignore" in low or "${" in ln:
                    print(f"  ~ {ln.strip()}", flush=True)
                    break
        else:
            print(f"[test-agents-read] CLEAN: {rel} (no threat patterns)", flush=True)
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
