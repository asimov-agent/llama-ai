"""Hermetic unit tests for scripts/check_openspec_tasks.py.

The OpenSpec `validate` command checks a change's STRUCTURE but NOT task
checkbox completion. This script is the missing half. These tests cover the
checkbox-parsing edge cases: happy (all checked) and unhappy (any unchecked)
cases, nested/sub bullets, fenced code blocks (a literal `- [ ]` inside a code
block must NOT count as a task), comments, prose, empty files, and the
active-vs-archived scoping.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = str(REPO_ROOT / "scripts" / "check_openspec_tasks.py")
_spec = importlib.util.spec_from_file_location("check_openspec_tasks", _SRC)
assert _spec and _spec.loader, f"cannot load {_SRC}"
CT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CT)  # type: ignore[attr-defined]
sys.modules["check_openspec_tasks_under_test"] = CT


# --------------------------------------------------------------------------- #
# unchecked_tasks: parsing edge cases
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "content,expected_lines",
    [
        # --- happy: all checked ---
        ("- [x] do a\n- [X] do b\n", []),
        ("## Tasks\n\n- [x] step 1\n- [X] step 2\n- [x] step 3\n", []),
        ("no checkbox here\nplain text\n", []),
        ("", []),                                   # empty file
        ("# heading\n\njust prose\n", []),
        # bare bullet, not a checkbox -> ignored (not a task)
        ("- just a bullet\n* another bullet\n+ plus bullet\n", []),
        # a checkbox inside a fenced code block -> NOT a task
        ("```\n- [ ] this is literal code\n```\n- [x] real task\n", []),
        # nested/indented but all checked
        ("- [x] top\n  - [x] sub\n  - [X] sub2\n", []),
        # --- unhappy: any unchecked ---
        ("- [ ] open task\n", [1]),
        ("- [x] done\n- [ ] todo\n", [2]),
        ("- [ ] first\n- [ ] second\n", [1, 2]),
        # indented unchecked sub-bullet is still a task
        ("- [x] parent\n  - [ ] child\n", [2]),
        # '*' and '+' list markers
        ("* [ ] star-open\n", [1]),
        ("+ [ ] plus-open\n", [1]),
    ],
)
def test_unchecked_tasks(tmp_path, content, expected_lines):
    f = tmp_path / "tasks.md"
    f.write_text(content)
    assert CT.unchecked_tasks(f) == expected_lines


def test_unchecked_ignores_lines_after_fence_until_closed(tmp_path):
    # a fence opens and never closes -> everything after is inside it
    f = tmp_path / "tasks.md"
    f.write_text("```\n- [ ] literal\n```\n- [x] real\n- [ ] outer\n")
    assert CT.unchecked_tasks(f) == [5]


def test_missing_file_returns_empty(tmp_path):
    assert CT.unchecked_tasks(tmp_path / "nope.md") == []


# --------------------------------------------------------------------------- #
# active vs archived scoping
# --------------------------------------------------------------------------- #
def _make_change(base: Path, name: str, tasks: str) -> None:
    (base / name).mkdir(parents=True, exist_ok=True)
    (base / name / "tasks.md").write_text(tasks)


def test_active_change_tasks_file_found(tmp_path):
    _make_change(tmp_path, "chg-a", "- [x] ok\n")
    f = CT.tasks_file_for("chg-a", tmp_path)
    assert f is not None and f.name == "tasks.md"


def test_archived_change_excluded(tmp_path):
    (tmp_path / "archive" / "old").mkdir(parents=True)
    (tmp_path / "archive" / "old" / "tasks.md").write_text("- [ ] leftover\n")
    assert CT.tasks_file_for("old", tmp_path) is None


def test_active_change_names_excludes_archive(tmp_path):
    _make_change(tmp_path, "new-one", "- [x] ok\n")
    (tmp_path / "archive" / "old").mkdir(parents=True)
    (tmp_path / "archive" / "old" / "tasks.md").write_text("- [x]\n")
    names = CT.active_change_names(tmp_path)
    assert "new-one" in names
    assert "old" not in names


# --------------------------------------------------------------------------- #
# check_all: end-to-end exit-code semantics
# --------------------------------------------------------------------------- #
def test_check_all_fails_change_with_unchecked(tmp_path):
    _make_change(tmp_path, "bad", "- [x] a\n- [ ] b\n")
    _make_change(tmp_path, "good", "- [x] a\n")
    failures = CT.check_all(base=tmp_path, verbose=False)
    assert failures == 1, f"expected exactly 1 failing change, got {failures}"


def test_check_all_zero_when_all_checked(tmp_path):
    _make_change(tmp_path, "good", "- [x] a\n- [X] b\n")
    assert CT.check_all(base=tmp_path, verbose=False) == 0


def test_check_all_specific_change(tmp_path):
    _make_change(tmp_path, "good", "- [x] a\n")
    _make_change(tmp_path, "bad", "- [ ] a\n")
    assert CT.check_all("good", base=tmp_path, verbose=False) == 0
    assert CT.check_all("bad", base=tmp_path, verbose=False) == 1


def test_check_all_missing_change_returns_failure(tmp_path):
    assert CT.check_all("does-not-exist", base=tmp_path, verbose=False) == 1