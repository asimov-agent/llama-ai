"""Hermetic unit tests for scripts/watchloop_dispatch.py.

These test the three reliability guarantees that issue #18 covers:
  1. stale-lock auto-clean: a `.running` lock whose recorded PID is dead is
     removed and a worker is (re)spawned; a live PID suppresses spawn.
  2. same-tick resolved-issue skip: the merge gate returns the issue numbers it
     closed this tick, and `main` skips spawning those.
  3. the shared `closing_issues` / `pid_alive` helpers used across the logic.

All tests are hermetic: no GitHub API calls and no real worker processes. We stub
the module's `api()`/`log()`/`subprocess.Popen`/`ensure_worktree` and only exercise
pure control flow.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# The dispatcher reads a token at import time (load_token). Make it hermetic:
# provide a dummy GITHUB_TOKEN so collection never depends on a real token or
# .env existing inside the container.
os.environ.setdefault("GITHUB_TOKEN", "test-token-hermetic")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scripts.watchloop_dispatch as wd  # noqa: E402


# --------------------------------------------------------------------------- helpers
class TestClosingIssues:
    def test_parses_common_keywords(self):
        assert wd.closing_issues("Closes #18 and fixes #15; Resolves #3") == {18, 15, 3}

    def test_respects_spacing(self):
        assert wd.closing_issues("resolves  #4, fixes   #9") == {4, 9}

    def test_plain_mention_without_keyword_is_ignored(self):
        # A bare `#N` mention (e.g. "the issue #9 guard") must NOT count as closing.
        assert wd.closing_issues("the issue #99 guard rejects behind-main PRs") == set()

    def test_empty_body(self):
        assert wd.closing_issues("") == set()
        # typing: passing None is allowed at runtime; helper guards it.
        assert wd.closing_issues(None) == set()


class TestPidAlive:
    def test_current_process_is_alive(self):
        assert wd.pid_alive(os.getpid()) is True

    def test_impossible_pid_is_dead(self):
        assert wd.pid_alive(2**31 - 1) is False

    def test_zero_and_negative_are_dead(self):
        assert wd.pid_alive(0) is False
        assert wd.pid_alive(-1) is False


# --------------------------------------------------------------------------- #
# spawn_worker stale-lock / alive-lock behavior (hermetic, monkeypatched)
class TestSpawnWorkerLock:
    def test_dead_pid_lock_is_removed_and_spawned(self, tmp_path, monkeypatch):
        """A lock whose PID is dead must be cleaned and a fresh worker spawned."""
        # Fake module paths so worker artifacts land in a temp dir.
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        monkeypatch.setattr(wd, "LOGS", str(tmp_path / "logs"))
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        (tmp_path / "logs").mkdir()

        spawned = []
        monkeypatch.setattr(wd, "ensure_worktree", lambda b, s: f"{tmp_path}/wt/{s}")
        monkeypatch.setattr(wd, "subprocess", _FakeSubprocess(spawned))

        # A lock with a DEAD pid exists (e.g. leftover from a dead worker).
        # spawn_worker derives the slug from the title, so match that filename.
        lk = tmp_path / "worker-feat_something.running"
        lk.write_text("999999999")  # impossible pid => dead

        issue = {"number": 18, "title": "something"}
        wd.spawn_worker(issue)

        # The stale lock is replaced (not left pointing at the dead PID), a fresh
        # worker spawned, and the lock now holds the NEW child PID.
        assert lk.read_text().strip() == "4242", "lock must hold the new worker PID"
        assert len(spawned) == 1, "a fresh worker must be spawned"

    def test_alive_pid_lock_skips_spawn(self, tmp_path, monkeypatch):
        """A lock whose PID is alive must suppress the spawn (no duplicate)."""
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        monkeypatch.setattr(wd, "LOGS", str(tmp_path / "logs"))
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        (tmp_path / "logs").mkdir()

        spawned: list = []
        monkeypatch.setattr(wd, "ensure_worktree", lambda *a, **k: f"{tmp_path}/wt")
        monkeypatch.setattr(wd, "subprocess", _FakeSubprocess(spawned))

        # A lock whose PID is the current (alive) process.
        lk = tmp_path / "worker-feat_alive.running"
        lk.write_text(str(os.getpid()))

        wd.spawn_worker({"number": 99, "title": "alive"})
        assert len(spawned) == 0, "alive-PID lock must NOT spawn a duplicate"
        # The live lock is still present (not cleaned).
        assert lk.exists()

    def test_no_lock_spawns(self, tmp_path, monkeypatch):
        """No lock => spawn one worker and write the child PID."""
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        monkeypatch.setattr(wd, "LOGS", str(tmp_path / "logs"))
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        (tmp_path / "logs").mkdir()

        spawned: list = []
        monkeypatch.setattr(wd, "ensure_worktree", lambda *a, **k: f"{tmp_path}/wt")
        monkeypatch.setattr(wd, "subprocess", _FakeSubprocess(spawned))

        wd.spawn_worker({"number": 7, "title": "fresh"})
        assert len(spawned) == 1
        # lock written with the child pid returned by the fake Popen
        lk = tmp_path / "worker-feat_fresh.running"
        assert lk.exists()
        assert lk.read_text().strip() == "4242"


class _FakeSubprocess:
    """Stand-in exposing `.Popen` that records invocations and yields a proc."""

    def __init__(self, calls):
        self._calls = calls

    def Popen(self, argv, **kwargs):
        self._calls.append(argv)
        return _FakeProc()


class _FakeProc:
    pid = 4242


# --------------------------------------------------------------------------- #
# merge-gate returns closed issues
# --------------------------------------------------------------------------- #
class TestMergeGate:
    def test_merges_and_reports_closed_issues(self, monkeypatch):
        merged = []  # record which PR numbers get merged
        closed: set = set()

        def fake_merge(pr):
            merged.append(pr["number"])
            nonlocal closed
            closed |= wd.closing_issues((pr.get("body") or ""))

        monkeypatch.setattr(wd, "pr_is_behind", lambda pr: False)
        monkeypatch.setattr(wd, "pr_approved", lambda n: True)
        monkeypatch.setattr(wd, "pr_open_threads", lambda n: False)
        monkeypatch.setattr(wd, "ci_green", lambda pr: True)
        monkeypatch.setattr(wd, "merge_pr", fake_merge)

        prs = [
            {"number": 1, "body": "Closes #18"},
            {"number": 2, "body": "Fixes #15 and resolves  #7"},
            {"number": 3, "body": "mentions #9 but no keyword"},
        ]
        result = wd.process_merge_gate(prs)
        assert merged == [1, 2, 3]
        # The merge gate must report exactly the keyword-closed issues this tick.
        assert result == {18, 15, 7}, f"expected {{18,15,7}}, got {result}"

    def test_behind_or_not_green_not_merged(self, monkeypatch):
        monkeypatch.setattr(wd, "pr_is_behind", lambda pr: True)
        # base main's issue-#9 path calls sync_pr_with_main when behind; stub it
        # to fail so the PR is NOT merged and nothing is recorded.
        monkeypatch.setattr(wd, "sync_pr_with_main", lambda pr: False)
        monkeypatch.setattr(wd, "merge_pr", lambda pr: (_ for _ in ()).throw(AssertionError))
        prs = [{"number": 5, "body": "Closes #55", "head": {"ref": "x"}}]
        # behind -> not merged, nothing recorded
        assert wd.process_merge_gate(prs) == set()


# --------------------------------------------------------------------------- #
# main() skips issues resolved in the same tick
# --------------------------------------------------------------------------- #
class TestMainSameTickSkip:
    def test_skips_issue_closed_by_merged_pr_in_same_tick(self, monkeypatch, tmp_path):
        """An issue whose PR was merged this tick must not be re-spawned."""
        spawned: list = []

        # Merge gate returns {18, 15} (merged PRs closed these issues this tick).
        def fake_gate(prs):
            return {18, 15}

        def fake_spawn(issue):
            spawned.append(issue["number"])

        monkeypatch.setattr(wd, "api", lambda path, *a, **k: (
            [{"number": 100, "body": "Closes #18"}]  # the merged PR (open list still stale)
            if "pulls" in path else
            [{"number": 18, "title": "sampling"}, {"number": 15, "title": "reloc"},
             {"number": 12, "title": "orphan"}]
        ))
        monkeypatch.setattr(wd, "sys", type("S", (), {"argv": ["watchloop_dispatch.py"]})())
        monkeypatch.setattr(wd, "process_merge_gate", fake_gate)
        monkeypatch.setattr(wd, "issue_has_pr", lambda n: False)
        monkeypatch.setattr(wd, "spawn_worker", fake_spawn)

        wd.main()

        # Issues 18 and 15 were resolved by a same-tick merge -> not spawned.
        # Issue 12 (not resolved) is spawned.
        assert spawned == [12], f"expected only orphan #12 spawned, got {spawned}"
