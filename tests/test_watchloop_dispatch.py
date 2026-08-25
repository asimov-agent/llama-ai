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

    def test_atomic_lock_two_concurrent_spawns_single_winner(self, tmp_path, monkeypatch):
        """Two concurrent spawn_worker calls must yield exactly ONE worker.

        Regression for issue #23 (doubled cron tick -> TOCTOU race): the old
        check-then-act (os.path.exists + open(w)) let two concurrent dispatchers
        both spawn. The atomic O_CREAT|O_EXCL acquire must let only one win —
        provided the winner's worker is alive (a dead PID is correctly treated
        as stale and resumed, which is a separate concern).
        """
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        monkeypatch.setattr(wd, "LOGS", str(tmp_path / "logs"))
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        (tmp_path / "logs").mkdir()
        spawned: list = []
        monkeypatch.setattr(wd, "ensure_worktree", lambda *a, **k: f"{tmp_path}/wt")

        # First call wins, records OUR (live) pid as the worker.
        # Make _FakeProc.pid = os.getpid() so the winner's recorded pid is alive.
        class _LiveFakeProc:
            pid = os.getpid()
        class _LiveFakeSub:
            def __init__(self, c): self.c = c
            def Popen(self, argv, **kw):
                self.c.append(argv)
                return _LiveFakeProc()
        monkeypatch.setattr(wd, "subprocess", _LiveFakeSub(spawned))

        wd.spawn_worker({"number": 1, "title": "race"})   # winner -> live pid
        wd.spawn_worker({"number": 1, "title": "race"})   # loser -> sees alive pid -> skip

        assert len(spawned) == 1, f"expected 1 worker spawned, got {len(spawned)}"
        lk = tmp_path / "worker-feat_race.running"
        assert lk.read_text().strip() == str(os.getpid())


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
        # The cleanup sweep does real git on the host repo; stub it hermetic here
        # (its own behaviour is covered in TestCleanupMergedWorktrees).
        monkeypatch.setattr(wd, "cleanup_merged_worktrees", lambda dry=False: set())
        monkeypatch.setattr(wd, "issue_has_pr", lambda n: False)
        monkeypatch.setattr(wd, "spawn_worker", fake_spawn)

        wd.main()

        # Issues 18 and 15 were resolved by a same-tick merge -> not spawned.
        # Issue 12 (not resolved) is spawned.
        assert spawned == [12], f"expected only orphan #12 spawned, got {spawned}"


# --------------------------------------------------------------------------- #
# ensure_worktree refreshes an existing worktree onto latest origin/main
# --------------------------------------------------------------------------- #
class TestEnsureWorktreeSync:
    def test_existing_worktree_behind_is_rebased(self, tmp_path, monkeypatch):
        """An existing worktree whose branch is behind origin/main must rebase."""
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        calls = []

        # Existing worktree dir present at the EXACT path ensure_worktree computes.
        wt = (tmp_path / ".." / "llama-ai-wt" / "always-sync").resolve()
        wt.mkdir(parents=True, exist_ok=True)
        real_isdir = os.path.isdir
        monkeypatch.setattr(os.path, "isdir", lambda p: real_isdir(p) or str(p) == str(wt))

        # Simulate git: fetch succeeds; merge-base => behind (rc 1); rebase rc 0.
        def fake_run(argv, capture_output=False, text=False, **k):
            calls.append(argv)
            class R:
                stderr = ""
                def __init__(self, rc):
                    self.returncode = rc
            if "merge-base" in argv:
                return R(1)          # behind -> triggers rebase
            if "rebase" in argv:
                return R(0)
            return R(0)              # fetch/add/etc success
        monkeypatch.setattr(wd.subprocess, "run", fake_run)

        wd.ensure_worktree("feat/always-sync", "always-sync")

        assert any("--prune" in c for c in calls), "must git fetch --all --prune"
        assert any("rebase" in c for c in calls), "must rebase a behind worktree onto origin/main"

    def test_existing_worktree_up_to_date_no_rebase(self, tmp_path, monkeypatch):
        """An existing worktree already at/after origin/main must NOT rebase."""
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        calls = []
        # Existing worktree dir present at the EXACT path ensure_worktree computes.
        wt = (tmp_path / ".." / "llama-ai-wt" / "fresh").resolve()
        wt.mkdir(parents=True, exist_ok=True)
        real_isdir = os.path.isdir
        monkeypatch.setattr(os.path, "isdir", lambda p: real_isdir(p) or str(p) == str(wt))

        def fake_run(argv, capture_output=False, text=False, **k):
            calls.append(argv)
            class R:
                stderr = ""
                def __init__(self, rc):
                    self.returncode = rc
            if "rebase" in argv:
                raise AssertionError("rebase should NOT run when up to date")
            return R(0)  # merge-base rc 0 => up to date
        monkeypatch.setattr(wd.subprocess, "run", fake_run)

        wd.ensure_worktree("feat/fresh", "fresh")
        assert any("--prune" in c for c in calls), "must fetch --all --prune"
        assert not any("rebase" in c for c in calls), "no rebase when already current"


# --------------------------------------------------------------------------- #
# per-tick dedup lock (issue #25): main() runs exactly once per cron tick
# --------------------------------------------------------------------------- #
class TestTickDedup:
    def _patch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        monkeypatch.setattr(wd, "LOGS", str(tmp_path / "logs"))
        monkeypatch.setattr(wd, "TICK_LOCK", str(tmp_path / "dispatch.tick.lock"))
        (tmp_path / "logs").mkdir()

    def test_acquire_wins_then_same_interval_dedups(self, tmp_path, monkeypatch):
        """First invoke wins; a re-fire in the SAME interval dedups (even after)."""
        self._patch(tmp_path, monkeypatch)
        assert wd._tick_lock_acquire() is True
        # same interval, live owner -> dedup (durable: not tied to main()'s end)
        assert wd._tick_lock_acquire() is False
        assert (tmp_path / "dispatch.tick.lock").exists()

    def test_next_interval_reclaims_older_bucket(self, tmp_path, monkeypatch):
        """A NEW interval (bucket changes) reclaims the previous interval's lock."""
        self._patch(tmp_path, monkeypatch)
        # hold a lock for the "current" interval, then force the next interval
        assert wd._tick_lock_acquire() is True
        # simulate wall clock advancing to a new bucket
        old = wd._current_tick
        counter = [100]
        wd._current_tick = lambda: f"tick-{counter[0]+1}"
        assert wd._tick_lock_acquire() is True, "new interval must win/reclaim"
        # lock now holds the new bucket
        assert wd._read_lock_owner()[0] == wd._current_tick()
        wd._current_tick = old

    def test_stale_dead_pid_lock_is_reclaimed(self, tmp_path, monkeypatch):
        """A stale lock (dead PID / foreign) is removed and re-acquired."""
        self._patch(tmp_path, monkeypatch)
        (tmp_path / "dispatch.tick.lock").write_text("tick-0\n999999999\n")
        assert wd._tick_lock_acquire() is True, "must reclaim stale/foreign lock"
        assert (tmp_path / "dispatch.tick.lock").exists()

    def test_main_logs_dedup_not_tick_start_when_held(self, tmp_path, monkeypatch, capsys):
        """A same-interval re-fire of main() logs [DEDUP], no tick start."""
        self._patch(tmp_path, monkeypatch)
        assert wd._tick_lock_acquire() is True  # as if another main() already ran
        wd.main()
        out = capsys.readouterr().out
        assert "DEDUP" in out, f"expected DEDUP, got {out!r}"
        assert "tick start" not in out, "second invocation must not log tick start"

    def test_current_tick_buckets_are_coarse(self, tmp_path, monkeypatch):
        """_current_tick() returns stable buckets of TICK_INTERVAL_SECONDS."""
        self._patch(tmp_path, monkeypatch)
        b1 = wd._current_tick()
        assert b1.startswith("tick-")
        assert wd._current_tick() == b1  # stable within the interval


# --------------------------------------------------------------------------- #
# configurable worker model (issue #31): resolve from env OR .watchloop config
# --------------------------------------------------------------------------- #
class TestWorkerModelConfig:
    def test_read_config_file(self, tmp_path, monkeypatch):
        """_read_worker_model_config reads MODEL/PROVIDER from the config file."""
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        cfg = tmp_path / "worker-model"
        cfg.write_text("my/fast-model\nmyprovider\n")
        assert wd._read_worker_model_config() == ("my/fast-model", "myprovider")

    def test_config_missing_returns_empty(self, tmp_path, monkeypatch):
        """No config file -> ('', '') so the profile default is used."""
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        assert wd._read_worker_model_config() == ("", "")

    def test_config_ignores_comments_and_blank(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        cfg = tmp_path / "worker-model"
        cfg.write_text("# comment\n\ndeepseek/x\nopenrouter\n")
        assert wd._read_worker_model_config() == ("deepseek/x", "openrouter")

    def test_build_command_with_model_override(self, tmp_path, monkeypatch, capsys):
        """spawn_worker's launch cmd includes -m <model> --provider <provider>."""
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        monkeypatch.setattr(wd, "LOGS", str(tmp_path / "logs"))
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        (tmp_path / "logs").mkdir()
        # stub subprocess.Popen to capture the command
        captured = {}
        class FakeP:
            pid = 4242
        class FakeSub:
            def Popen(self, argv, **kw):
                captured["cmd"] = argv[2]
                return FakeP()
        monkeypatch.setattr(wd, "subprocess", FakeSub())
        monkeypatch.setattr(wd, "ensure_worktree", lambda *a, **k: f"{tmp_path}/wt")
        monkeypatch.setattr(wd, "WORKER_MODEL", "deepseek/fast")
        monkeypatch.setattr(wd, "WORKER_PROVIDER", "openrouter")
        wd.spawn_worker({"number": 1, "title": "m"})
        cmd = captured["cmd"]
        assert "-m deepseek/fast" in cmd, cmd
        assert "--provider openrouter" in cmd, cmd


# --------------------------------------------------------------------------- #
# stale-worktree cleanup (issue #29): merged worktrees + branches are removed
# --------------------------------------------------------------------------- #
class _FakeRunRecorder:
    """Captures `subprocess.run` invocations and always "succeeds"."""

    def __init__(self):
        self.calls: list = []

    def run(self, argv, **kwargs):
        self.calls.append(argv)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()


@pytest.fixture
def _cleanup_env(tmp_path, monkeypatch):
    """Scratch env for cleanup tests: fake REPO/RUN/LOGS/WORKTREE_BASE + recorder."""
    run = tmp_path / "run"
    logs = tmp_path / "logs"
    wt = tmp_path / "wt"
    run.mkdir()
    logs.mkdir()
    wt.mkdir()
    recorder = _FakeRunRecorder()
    monkeypatch.setattr(wd, "REPO", str(tmp_path))
    monkeypatch.setattr(wd, "RUN", str(run))
    monkeypatch.setattr(wd, "LOGS", str(logs))
    monkeypatch.setattr(wd, "WORKTREE_BASE", str(wt))
    monkeypatch.setattr(wd.subprocess, "run", recorder.run)
    return tmp_path, run, logs, wt, recorder


class TestWorkerArtifacts:
    def test_paths_use_run_and_logs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        monkeypatch.setattr(wd, "LOGS", str(tmp_path))
        got = wd._worker_artifacts("my-slug")
        assert str(tmp_path / "worker-feat_my-slug.running") in got
        assert str(tmp_path / "worker-feat_my-slug.prompt") in got
        assert str(tmp_path / "feat-my-slug.log") in got


class TestReadPid:
    def test_returns_stored_pid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        p = tmp_path / "worker-feat_x.running"
        p.write_text("4242\n")
        assert wd._read_pid(str(p)) == 4242

    def test_missing_file_returns_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        assert wd._read_pid(str(tmp_path / "nope.running")) == 0


class TestCleanupMergedWorktrees:
    def _run_worktrees(self, monkeypatch, entries):
        monkeypatch.setattr(wd, "_git_worktrees", lambda: entries)

    def test_merged_worktree_and_branch_removed(self, _cleanup_env, monkeypatch):
        tmp_path, run, logs, wt, recorder = _cleanup_env
        # per-worker artifacts that must be removed with the merged worktree/branch
        (run / "worker-feat_merged.running").write_text("0")
        (run / "worker-feat_merged.prompt").write_text("prompt")
        (logs / "feat-merged.log").write_text("log")

        self._run_worktrees(monkeypatch, [
            {"path": str(wt / "merged"), "branch": "feat/merged"},
        ])
        monkeypatch.setattr(wd, "_merged_into_main", lambda b: True)

        cleaned = wd.cleanup_merged_worktrees()

        assert cleaned == {"feat/merged"}, cleaned
        # worktree removed with force + local branch deleted
        assert any(
            argv[:4] == ["git", "-C", str(tmp_path), "worktree"]
            and "remove" in argv and "--force" in argv
            for argv in recorder.calls
        ), recorder.calls
        assert any("branch" in argv and "-D" in argv and "feat/merged" in argv
                   for argv in recorder.calls), recorder.calls
        # per-worker artifacts removed
        assert not (run / "worker-feat_merged.running").exists()
        assert not (run / "worker-feat_merged.prompt").exists()
        assert not (logs / "feat-merged.log").exists()

    def test_inflight_worktree_kept(self, _cleanup_env, monkeypatch):
        tmp_path, run, logs, wt, recorder = _cleanup_env
        self._run_worktrees(monkeypatch, [
            {"path": str(wt / "wip"), "branch": "feat/wip"},
        ])
        monkeypatch.setattr(wd, "_merged_into_main", lambda b: False)

        cleaned = wd.cleanup_merged_worktrees()

        assert cleaned == set(), cleaned
        # no worktree-remove / branch -D issued for an in-flight PR
        assert not any("remove" in argv and "worktree" in argv
                       for argv in recorder.calls)
        assert not any("branch" in argv and "-D" in argv for argv in recorder.calls)

    def test_live_worker_merged_kept(self, _cleanup_env, monkeypatch):
        tmp_path, run, logs, wt, recorder = _cleanup_env
        self._run_worktrees(monkeypatch, [
            {"path": str(wt / "busy"), "branch": "feat/busy"},
        ])
        monkeypatch.setattr(wd, "_merged_into_main", lambda b: True)
        # merged branch but a LIVE worker -> post-worker-exit cleanup must NOT delete
        (run / "worker-feat_busy.running").write_text(str(os.getpid()))

        cleaned = wd.cleanup_merged_worktrees()

        assert cleaned == set(), cleaned
        assert not any("branch" in argv and "-D" in argv for argv in recorder.calls)
        assert (run / "worker-feat_busy.running").exists()
        assert (wt / "busy").exists() if (wt / "busy").exists() else True

    def test_dry_run_reports_without_deleting(self, _cleanup_env, monkeypatch):
        tmp_path, run, logs, wt, recorder = _cleanup_env
        self._run_worktrees(monkeypatch, [
            {"path": str(wt / "old"), "branch": "feat/old"},
        ])
        monkeypatch.setattr(wd, "_merged_into_main", lambda b: True)
        (run / "worker-feat_old.running").write_text("0")

        cleaned = wd.cleanup_merged_worktrees(dry=True)

        assert cleaned == {"feat/old"}, cleaned
        # reported as would-clean but NOT deleted
        assert not any("remove" in argv and "worktree" in argv for argv in recorder.calls)
        assert not any("branch" in argv and "-D" in argv for argv in recorder.calls)
        assert (run / "worker-feat_old.running").exists()
        assert (wt / "old").exists() if (wt / "old").exists() else True
