"""Linefeed lint tests: the lint MUST pick up extension-less config files.

Regression guard for the PR-review bug where `containers/test/Dockerfile`
(and bare `Makefile`/`LICENSE`/`.editorconfig`) never entered the lint's
tracked-file scan. Root cause: lint matched ONLY by path suffix, and an
extension-less ``Dockerfile`` has ``suffix == ''``, so the missing trailing
newline slipped through with "LINT OK" and the CI lint stage stayed green.

These tests assert the two things that must hold so a lint violation turns
the CI/lint stage RED (exit code != 0):

1. ``_tracked_text_files()`` includes extension-less config filenames
   (``containers/test/Dockerfile``, ``Makefile``, ``LICENSE``, ...), not just
   dotted-extension files.
2. ``check()`` returns a non-zero code (and names the file) when any picked-up
   tracked text file lacks a trailing newline — the fail-closed mechanism that
   drives the CI stage red.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Load scripts/lint_linefeeds.py by path so the test exercises the REAL script
# regardless of how pytest resolves sys.path inside the test container.
_LINT_SRC = str(REPO_ROOT / "scripts" / "lint_linefeeds.py")
_spec = importlib.util.spec_from_file_location("lint_linefeeds", _LINT_SRC)
assert _spec and _spec.loader, f"cannot load {_LINT_SRC}"
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)  # type: ignore[attr-defined]
sys.modules["lint_linefeeds_under_test"] = L


@pytest.mark.parametrize("path", [
    "containers/test/Dockerfile",
    "openspec/Dockerfile",
    "tools/Dockerfile",
    "Makefile",
    "tools/Makefile",
    "LICENSE",
    ".editorconfig",
    ".gitignore",
])
def test_extension_less_file_is_in_tracked_scan(path: str) -> None:
    """Every extension-less tracked config file we care about must be scanned."""
    files = L._tracked_text_files()
    assert path in files, (
        f"{path} must be in the lint scan list (got {len(files)} files). "
        "When extension-less files are skipped, a missing trailing newline "
        "silently stays green instead of turning the CI lint stage red."
    )


def test_check_returns_nonzero_on_missing_newline(repo_root: Path, tmp_path: Path) -> None:
    """Fail-closed: a scanned file without a final newline yields exit code 1.

    This is the exact exit-code contract the CI lint job relies on: when the
    lint flags a file, it must exit non-zero so the stage turns RED (GitHub
    marks a step failed on nonzero exit). We monkeypatch the file list to one
    tiny offender so the test stays hermetic (pytest runs in the container).
    """
    offender = tmp_path / "offender.py"
    offender.write_bytes(b"x = 1")  # no trailing newline

    origin_path = offender.resolve()
    orig = L._tracked_text_files

    def _one() -> list[str]:
        return [str(origin_path)]  # absolute path; check() joins onto _repo_root()

    L._tracked_text_files = _one  # type: ignore[assignment]
    try:
        rc = L.check(report=False)
        assert rc == 1, (
            "check() must return 1 (non-zero) when a scanned file lacks a "
            "trailing newline. A zero here is what let the Dockerfile slip "
            "through as a green lint."
        )
    finally:
        L._tracked_text_files = orig  # type: ignore[assignment]
