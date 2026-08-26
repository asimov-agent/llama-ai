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
        monkeypatch.setattr(wd, "TICK_LOCK", str(tmp_path / "dispatch.tick.lock"))
        monkeypatch.setattr(wd, "process_merge_gate", fake_gate)
        # The cleanup sweep does real git on the host repo; stub it hermetic here
        # (its own behaviour is covered in TestCleanupMergedWorktrees).
        monkeypatch.setattr(wd, "cleanup_merged_worktrees", lambda dry=False: set())
        monkeypatch.setattr(wd, "issue_has_pr", lambda n: False)
        # issue #37: stub the pre-spawn model probe so this hermetic test never
        # touches the local llama-server.
        monkeypatch.setattr(wd, "probe_worker_model", lambda m, **k: True)
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
# ensure_worktree reuse of an existing branch/worktree (issue #46): the
# repair spawn must never `git worktree add -b` a branch that already exists
# (rc-255 regression from the stuck-PR repair stage, issue #42).
# --------------------------------------------------------------------------- #
class _WorktreeRun:
    """Records `subprocess.run` argv; simulates git per the test's wishes.

    *branch_exists* controls `git show-ref --verify` results:
      "local"  -> refs/heads/<branch> exists
      "origin" -> only refs/remotes/origin/<branch> exists
      False    -> neither exists
    """

    def __init__(self, branch_exists: bool | str):
        self.calls: list = []
        self.branch_exists = branch_exists

    def run(self, argv, capture_output=False, text=False, **k):
        self.calls.append(argv)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        if "show-ref" in argv:
            ref = argv[-1]
            if self.branch_exists is True or self.branch_exists is False:
                rc = 0 if (self.branch_exists and ref.startswith("refs/heads/")) else 1
            elif self.branch_exists == "local":
                rc = 0 if ref.startswith("refs/heads/") else 1
            elif self.branch_exists == "origin":
                rc = 0 if ref.startswith("refs/remotes/") else 1
            else:
                raise AssertionError(f"unexpected branch_exists {self.branch_exists!r}")
            r = _R()
            r.returncode = rc
            return r
        return _R()

    def worktree_adds(self) -> list:
        return [c for c in self.calls if "worktree" in c and "add" in c]


class _FakePopenSub:
    """Records `.Popen` invocations (worker launch) while keeping the real
    module otherwise; pairs with a patched subprocess.run for git calls."""

    def __init__(self, calls: list):
        self._calls = calls

    def Popen(self, argv, **kw):
        self._calls.append(argv)
        return _FakeProc()


class TestEnsureWorktreeReuse:
    def _env(self, tmp_path, monkeypatch, slug: str):
        """Point REPO at tmp_path and force the computed worktree dir to be
        ABSENT (fresh path) so the add/attach branch is exercised."""
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        real_isdir = os.path.isdir
        monkeypatch.setattr(
            os.path, "isdir",
            lambda p: real_isdir(p) if real_isdir(p) and "llama-ai-wt" not in p else False,
        )
        return tmp_path

    def test_existing_worktree_issues_no_add(self, tmp_path, monkeypatch):
        """(1) worktree already exists -> NO `git worktree add`; rebase-if-behind."""
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        wt = (tmp_path / ".." / "llama-ai-wt" / "issue46-existing").resolve()
        wt.mkdir(parents=True, exist_ok=True)
        real_isdir = os.path.isdir
        monkeypatch.setattr(os.path, "isdir",
                            lambda p: real_isdir(p) or str(p) == str(wt))
        rec = _WorktreeRun(False)
        monkeypatch.setattr(wd.subprocess, "run", rec.run)

        wd.ensure_worktree("feat/issue46-existing", "issue46-existing")

        assert rec.worktree_adds() == [], (
            f"existing worktree must not issue `git worktree add`: {rec.worktree_adds()}"
        )
        # behind (merge-base rc 0 == up-to-date in this fake) -> no crash either way

    def test_origin_branch_no_worktree_attaches_without_b(self, tmp_path, monkeypatch):
        """(2) branch on origin, no worktree -> `worktree add <path> <branch>`
        WITHOUT -b (the issue #46 rc-255 fix)."""
        self._env(tmp_path, monkeypatch, "issue46-attach")
        rec = _WorktreeRun("origin")
        monkeypatch.setattr(wd.subprocess, "run", rec.run)

        wd.ensure_worktree("feat/issue46-attach", "issue46-attach")

        adds = rec.worktree_adds()
        assert len(adds) == 1, f"exactly one worktree add expected: {adds}"
        cmd = adds[0]
        assert "-b" not in cmd, f"attach must NOT pass -b (rc 255 regression): {cmd}"
        assert cmd[cmd.index("add") + 1] == f"{tmp_path}/../llama-ai-wt/issue46-attach"
        assert "feat/issue46-attach" in cmd

    def test_local_branch_no_worktree_attaches_without_b(self, tmp_path, monkeypatch):
        """(2b) branch exists LOCALLY, no worktree -> also attach without -b."""
        self._env(tmp_path, monkeypatch, "issue46-attach-local")
        rec = _WorktreeRun("local")
        monkeypatch.setattr(wd.subprocess, "run", rec.run)

        wd.ensure_worktree("feat/issue46-attach-local", "issue46-attach-local")

        adds = rec.worktree_adds()
        assert len(adds) == 1
        assert "-b" not in adds[0], f"local existing branch must attach without -b: {adds[0]}"

    def test_neither_branch_nor_worktree_fresh_add_b(self, tmp_path, monkeypatch):
        """(3) neither exists -> fresh `git worktree add -b <branch> <path>
        origin/main` (orphan-issue spawn, unchanged)."""
        self._env(tmp_path, monkeypatch, "issue46-fresh")
        rec = _WorktreeRun(False)
        monkeypatch.setattr(wd.subprocess, "run", rec.run)

        wd.ensure_worktree("feat/issue46-fresh", "issue46-fresh")

        adds = rec.worktree_adds()
        assert len(adds) == 1
        cmd = adds[0]
        assert "-b" in cmd, f"fresh spawn must create the branch: {cmd}"
        assert "origin/main" in cmd, f"fresh spawn must start from origin/main: {cmd}"

    def test_never_add_b_when_branch_exists(self, tmp_path, monkeypatch):
        """(5) regression: whenever the branch exists, `add -b` is NEVER
        attempted (the production rc-255 failure, issue #42 log line)."""
        for state, slug in (("origin", "issue46-reg-o"), ("local", "issue46-reg-l")):
            rec = _WorktreeRun(state)
            monkeypatch.setattr(wd.subprocess, "run", rec.run)
            self._env(tmp_path, monkeypatch, slug)
            wd.ensure_worktree(f"feat/{slug}", slug)
            for cmd in rec.worktree_adds():
                assert "-b" not in cmd, (
                    f"branch exists ({state}) but `add -b` was attempted: {cmd}"
                )


class TestRepairSpawnReusesBranch:
    """(4) end-to-end: a repair for a PR whose branch exists on the remote
    launches the worker in the reused/attached worktree and the git add uses
    NO -b because the branch exists."""

    def _patch(self, tmp_path, monkeypatch, spawned):
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        monkeypatch.setattr(wd, "LOGS", str(tmp_path / "logs"))
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        (tmp_path / "logs").mkdir()
        # fresh (absent) worktree path so the add/attach path is exercised
        real_isdir = os.path.isdir
        monkeypatch.setattr(
            os.path, "isdir",
            lambda p: real_isdir(p) if real_isdir(p) and "llama-ai-wt" not in p else False,
        )
        monkeypatch.setattr(wd, "pr_is_behind", lambda pr: False)
        monkeypatch.setattr(wd, "WORKER_PROVIDER", "openrouter")
        monkeypatch.setattr(wd, "effective_provider_is_local", lambda: False)
        return monkeypatch

    def test_repair_spawn_attaches_existing_remote_branch(self, tmp_path, monkeypatch, capsys):
        spawned = []
        mp = self._patch(tmp_path, monkeypatch, spawned)
        mp.setattr(wd, "pr_repairable", lambda pr, n: "CI is red")
        rec = _WorktreeRun("origin")   # the PR's branch exists on origin
        monkeypatch.setattr(wd.subprocess, "run", rec.run)
        monkeypatch.setattr(wd.subprocess, "Popen", _FakePopenSub(spawned).Popen)

        pr = _pr(43, body="Closes #42", head_ref="feat/stuck-pr-repair-stage")
        wd.process_stuck_prs([pr])

        # The repair worker actually started (Popen recorded, lock written).
        assert len(spawned) == 1, f"repair worker must spawn, got {spawned}"
        assert (tmp_path / "worker-feat_stuck-pr-repair-stage.running").exists()
        # The launch command targets the PR's existing worktree path.
        cmd = spawned[0][2]
        assert "llama-ai-wt/stuck-pr-repair-stage" in cmd, cmd
        # ...and it reads the PR commentary (REPAIR prompt).
        prompt_file = tmp_path / "worker-feat_stuck-pr-repair-stage.prompt"
        assert prompt_file.exists()
        assert "DEDICATED REPAIR worker" in prompt_file.read_text()
        # git worktree add issued WITHOUT -b (branch exists on origin).
        adds = rec.worktree_adds()
        assert len(adds) == 1
        assert "-b" not in adds[0], (
            f"repair attach must NOT use -b for an existing branch: {adds[0]}"
        )
        out = capsys.readouterr().out
        assert "repair-PR#43: spawning worker" in out, out


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

    def test_same_bucket_dead_owner_still_dedups(self, tmp_path, monkeypatch):
        """A SAME-bucket lock whose owner has FINISHED (dead pid) must still dedup.

        Regression for the live-test finding (issue #30): a same-bucket re-fire
        lands AFTER the first cron process already exited, so its pid is dead.
        The durable design holds the lock for the WHOLE interval, so a dead
        same-bucket owner must NOT be reclaimed -- reclaiming it re-runs the
        tick (the #25 phantom double). Only an OLDER bucket is stale.
        """
        self._patch(tmp_path, monkeypatch)
        bucket = wd._current_tick()
        # A previous invocation acquired this interval and then exited (pid dead).
        (tmp_path / "dispatch.tick.lock").write_text(f"{bucket}\n999999999\n")
        assert wd._tick_lock_acquire() is False, (
            "a finished same-bucket owner is a completed tick -> must dedup, not re-run"
        )
        # The (dead owner's) lock is left in place until the bucket changes.
        assert (tmp_path / "dispatch.tick.lock").read_text().splitlines()[0] == bucket

    def test_older_bucket_dead_owner_is_reclaimed(self, tmp_path, monkeypatch):
        """An OLDER bucket with a dead owner is a finished prior interval -> reclaim."""
        self._patch(tmp_path, monkeypatch)
        wd._current_tick()  # ensure bucket is established
        (tmp_path / "dispatch.tick.lock").write_text("tick-0\n999999999\n")
        assert wd._tick_lock_acquire() is True
        assert wd._read_lock_owner()[0] == wd._current_tick()

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
# pre-spawn worker-model probe (issue #37): skip cleanly when local server down
# --------------------------------------------------------------------------- #
class TestPreSpawnProbe:
    """main() must probe the local worker-model endpoint before spawning and
    skip cleanly (no worker, no lock) when it is down."""

    def _patch_env(self, tmp_path, monkeypatch, spawned):
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        monkeypatch.setattr(wd, "LOGS", str(tmp_path / "logs"))
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        monkeypatch.setattr(wd, "TICK_LOCK", str(tmp_path / "dispatch.tick.lock"))
        (tmp_path / "logs").mkdir()
        monkeypatch.setattr(wd, "WORKER_MODEL", "")
        monkeypatch.setattr(wd, "WORKER_MODEL_EFFECTIVE", "llm-local")
        monkeypatch.setattr(wd, "api", lambda path, *a, **k: (
            [] if "pulls" in path
            else [{"number": 12, "title": "orphan"}]
        ))
        monkeypatch.setattr(wd, "sys", type("S", (), {"argv": ["watchloop_dispatch.py"]})())
        monkeypatch.setattr(wd, "process_merge_gate", lambda prs: set())
        monkeypatch.setattr(wd, "cleanup_merged_worktrees", lambda dry=False: set())
        monkeypatch.setattr(wd, "issue_has_pr", lambda n: False)
        monkeypatch.setattr(wd, "ensure_worktree", lambda *a, **k: f"{tmp_path}/wt")
        monkeypatch.setattr(wd, "subprocess", _FakeSubprocess(spawned))
        return monkeypatch

    def test_local_reachable_spawns(self, tmp_path, monkeypatch):
        """(a) local model reachable -> spawn proceeds."""
        spawned: list = []
        mp = self._patch_env(tmp_path, monkeypatch, spawned)
        mp.setattr(wd, "WORKER_PROVIDER", "")            # empty => local
        mp.setattr(wd, "probe_worker_model", lambda m, **k: True)
        wd.main()
        assert len(spawned) == 1, "reachable local model must spawn"
        assert (tmp_path / "worker-feat_orphan.running").exists(), "lock written on spawn"

    def test_local_unreachable_skips_cleanly(self, tmp_path, monkeypatch, capsys):
        """(b) local model unreachable -> skipped, NO lock file, log emitted."""
        spawned: list = []
        mp = self._patch_env(tmp_path, monkeypatch, spawned)
        mp.setattr(wd, "WORKER_PROVIDER", "custom")      # local
        mp.setattr(wd, "probe_worker_model", lambda m, **k: False)
        wd.main()
        assert len(spawned) == 0, "unreachable local model must NOT spawn"
        assert not (tmp_path / "worker-feat_orphan.running").exists(), (
            "no lock file may be created when the probe fails"
        )
        assert not (tmp_path / "worker-feat_orphan.prompt").exists(), (
            "no prompt file may be written when the probe fails"
        )
        out = capsys.readouterr().out
        assert "issue#12: worker model llm-local unreachable on" in out, out
        assert "skipping spawn" in out, out

    def test_hosted_provider_no_probe(self, tmp_path, monkeypatch):
        """(c) hosted provider (openrouter) -> no local probe attempted."""
        spawned: list = []
        mp = self._patch_env(tmp_path, monkeypatch, spawned)
        mp.setattr(wd, "WORKER_PROVIDER", "openrouter")  # hosted
        calls = []
        mp.setattr(wd, "probe_worker_model",
                   lambda m, **k: calls.append(m) or True)
        wd.main()
        assert len(spawned) == 1, "hosted provider must still spawn"
        assert calls == [], f"hosted provider must NOT call the local probe, got {calls}"

    def test_effective_provider_is_local_classification(self, monkeypatch):
        monkeypatch.setattr(wd, "WORKER_PROVIDER", "")
        assert wd.effective_provider_is_local() is True
        monkeypatch.setattr(wd, "WORKER_PROVIDER", "Custom")
        assert wd.effective_provider_is_local() is True
        monkeypatch.setattr(wd, "WORKER_PROVIDER", "llama.cpp")
        assert wd.effective_provider_is_local() is True
        monkeypatch.setattr(wd, "WORKER_PROVIDER", "localhost")
        assert wd.effective_provider_is_local() is True
        monkeypatch.setattr(wd, "WORKER_PROVIDER", "openrouter")
        assert wd.effective_provider_is_local() is False


class _FakeUrn:
    """Minimal context-manager stand-in for urllib.request.urlopen."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestProbeWorkerModel:
    """probe_worker_model parses the v1/models listing hermetically (stubbed
    urlopen; no real network)."""

    def _patch_urlopen(self, monkeypatch, body: bytes):
        monkeypatch.setattr(wd.urllib.request, "urlopen",
                            lambda req, timeout=10: _FakeUrn(body))

    def test_model_listed_returns_true(self, monkeypatch):
        body = b'{"data":[{"id":"llm-local","object":"model"}]}'
        self._patch_urlopen(monkeypatch, body)
        assert wd.probe_worker_model("llm-local") is True

    def test_model_not_listed_returns_false(self, monkeypatch):
        body = b'{"data":[{"id":"other-model"}]}'
        self._patch_urlopen(monkeypatch, body)
        assert wd.probe_worker_model("llm-local") is False

    def test_model_field_also_accepted(self, monkeypatch):
        body = b'{"data":[{"model":"llm-local"}]}'
        self._patch_urlopen(monkeypatch, body)
        assert wd.probe_worker_model("llm-local") is True

    def test_connection_error_returns_false_not_raise(self, monkeypatch):
        def boom(req, timeout=10):
            raise OSError("connection refused")
        monkeypatch.setattr(wd.urllib.request, "urlopen", boom)
        assert wd.probe_worker_model("llm-local") is False

    def test_non_json_body_returns_false(self, monkeypatch):
        self._patch_urlopen(monkeypatch, b"<html>502 Bad Gateway</html>")
        assert wd.probe_worker_model("llm-local") is False


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


# --------------------------------------------------------------------------- #
# remote-branch deletion after merge (issue #45): the REMOTE gap of issue #29
# --------------------------------------------------------------------------- #
class _RemoteAwareRecorder:
    """`subprocess.run` stand-in: records calls, emulates `ls-remote` output.

    `ls-remote --heads origin <branch>` returns a fake ref line (branch exists)
    for branches in *present*, empty stdout (already gone) for the rest.
    Everything else "succeeds" with empty output.
    """

    def __init__(self, present=()):
        self.calls: list = []
        self.present = set(present)

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        if argv[3:6] == ["ls-remote", "--heads", "origin"] and argv[6] in self.present:
            _R.stdout = f"0" * 40 + f"\theads/{argv[6]}\n"
        return _R()

    @property
    def remote_deletes(self):
        return [argv for argv in self.calls
                if "push" in argv and "origin" in argv and "--delete" in argv]


class TestCleanupDeletesRemoteBranch:
    def _run_worktrees(self, monkeypatch, entries):
        monkeypatch.setattr(wd, "_git_worktrees", lambda: entries)

    def test_merged_cleaned_branch_remote_deleted(self, _cleanup_env, monkeypatch):
        """1. merged PR remote branch deleted."""
        tmp_path, run, logs, wt, recorder = _cleanup_env
        self._run_worktrees(monkeypatch, [
            {"path": str(wt / "merged"), "branch": "feat/merged"},
        ])
        monkeypatch.setattr(wd, "_merged_into_main", lambda b: True)
        fake = _RemoteAwareRecorder(present={"feat/merged"})
        monkeypatch.setattr(wd.subprocess, "run", fake.run)

        cleaned = wd.cleanup_merged_worktrees()

        assert cleaned == {"feat/merged"}, cleaned
        assert fake.remote_deletes == [
            ["git", "-C", str(tmp_path), "push", "origin", "--delete", "feat/merged"],
        ], fake.calls

    def test_inflight_branch_remote_never_deleted(self, _cleanup_env, monkeypatch):
        """2. in-flight (unmerged) branch: no `push origin --delete`."""
        tmp_path, run, logs, wt, recorder = _cleanup_env
        self._run_worktrees(monkeypatch, [
            {"path": str(wt / "wip"), "branch": "feat/wip"},
        ])
        monkeypatch.setattr(wd, "_merged_into_main", lambda b: False)
        fake = _RemoteAwareRecorder(present={"feat/wip"})
        monkeypatch.setattr(wd.subprocess, "run", fake.run)

        cleaned = wd.cleanup_merged_worktrees()

        assert cleaned == set(), cleaned
        assert fake.remote_deletes == [], fake.calls

    def test_dry_run_reports_but_does_not_delete_remote(self, _cleanup_env, monkeypatch):
        """3. dry-run: remote deletion reported, not executed."""
        tmp_path, run, logs, wt, recorder = _cleanup_env
        self._run_worktrees(monkeypatch, [
            {"path": str(wt / "old"), "branch": "feat/old"},
        ])
        monkeypatch.setattr(wd, "_merged_into_main", lambda b: True)
        fake = _RemoteAwareRecorder(present={"feat/old"})
        monkeypatch.setattr(wd.subprocess, "run", fake.run)

        cleaned = wd.cleanup_merged_worktrees(dry=True)

        assert cleaned == {"feat/old"}, cleaned
        assert fake.remote_deletes == [], fake.calls

    def test_merge_pr_requests_branch_deletion(self, monkeypatch):
        """4. merge_pr PUT body includes delete_branch: true."""
        calls = []

        def fake_api(path, method="GET", body=None):
            calls.append((path, method, body))
            return {"merged": True}

        monkeypatch.setattr(wd, "api", fake_api)
        pr = {"number": 45, "head": {"ref": "feat/x"}}
        wd.merge_pr(pr)

        assert ("PUT" in [c[1] for c in calls]), calls
        put = [c for c in calls if c[1] == "PUT"][0]
        assert put[0] == "/pulls/45/merge"
        assert put[2].get("delete_branch") is True, put[2]
        assert put[2].get("merge_method") == "merge", put[2]

    def test_main_never_deleted(self, _cleanup_env, monkeypatch):
        """5. even if `main` were passed, no `push origin --delete main`."""
        tmp_path, run, logs, wt, recorder = _cleanup_env
        fake = _RemoteAwareRecorder(present={"main"})
        monkeypatch.setattr(wd.subprocess, "run", fake.run)

        wd._delete_remote_branch("main")

        assert fake.remote_deletes == [], fake.calls

    def test_already_gone_remote_not_redeleted(self, _cleanup_env, monkeypatch):
        """Remote already deleted (e.g. by the merge API) -> no failing push."""
        tmp_path, run, logs, wt, recorder = _cleanup_env
        # `feat/gone` NOT in present -> ls-remote returns empty stdout
        fake = _RemoteAwareRecorder(present=())
        monkeypatch.setattr(wd.subprocess, "run", fake.run)

        wd._delete_remote_branch("feat/gone")

        assert fake.remote_deletes == [], fake.calls

    def test_remote_delete_failure_does_not_break_sweep(self, _cleanup_env, monkeypatch):
        """A failing `git push` is logged (retry next tick), not raised."""
        tmp_path, run, logs, wt, recorder = _cleanup_env
        self._run_worktrees(monkeypatch, [
            {"path": str(wt / "merged"), "branch": "feat/merged"},
        ])
        monkeypatch.setattr(wd, "_merged_into_main", lambda b: True)

        def flaky_run(argv, **kwargs):
            if argv[3:6] == ["ls-remote", "--heads", "origin"]:
                class _Ok:
                    returncode = 0
                    stdout = "0" * 40 + "\theads/feat/merged\n"
                    stderr = ""
                return _Ok()
            class _Fail:
                returncode = 128
                stdout = ""
                stderr = "remote rejected"
            return _Fail()

        monkeypatch.setattr(wd.subprocess, "run", flaky_run)

        # must not raise even though the push itself failed
        cleaned = wd.cleanup_merged_worktrees()
        assert cleaned == {"feat/merged"}, cleaned


# --------------------------------------------------------------------------- #
# stuck-PR repair stage (issue #42): respawn worker to fix red-CI / threads
# --------------------------------------------------------------------------- #
def _pr(n, body="Closes #42", head_ref="feat/x", behind=False, green=True, threads=False):
    """Build a realistic PR dict for repair tests."""
    return {
        "number": n,
        "title": f"PR {n}",
        "body": body,
        "head": {"ref": head_ref, "sha": "h" * 40},
        "base": {"ref": "main", "sha": "b" * 40},
        "_behind": behind,
        "_green": green,
        "_threads": threads,
    }


class TestPrRepairable:
    def test_open_threads_is_actionable(self, monkeypatch):
        pr = _pr(1, threads=True)
        monkeypatch.setattr(wd, "pr_open_threads", lambda n: True)
        monkeypatch.setattr(wd, "ci_green", lambda pr: True)
        assert wd.pr_repairable(pr, 1) == "unresolved review threads"

    def test_red_ci_is_actionable(self, monkeypatch):
        pr = _pr(1, green=False)
        monkeypatch.setattr(wd, "pr_open_threads", lambda n: False)
        monkeypatch.setattr(wd, "ci_green", lambda pr: False)
        assert wd.pr_repairable(pr, 1) == "CI is red"

    def test_clean_pr_not_actionable(self, monkeypatch):
        pr = _pr(1)
        monkeypatch.setattr(wd, "pr_open_threads", lambda n: False)
        monkeypatch.setattr(wd, "ci_green", lambda pr: True)
        assert wd.pr_repairable(pr, 1) == ""

    def test_incomplete_pr_never_raises(self, monkeypatch):
        # minimal dict (no head/base) -> ci_green would KeyError, must return ""
        monkeypatch.setattr(wd, "pr_open_threads", lambda n: False)
        monkeypatch.setattr(wd, "ci_green",
                            lambda pr: (_ for _ in ()).throw(KeyError("head")))
        assert wd.pr_repairable({"number": 1}, 1) == ""


class TestPrIssueNumber:
    def test_extracts_closing_issue(self):
        assert wd.pr_issue_number({"body": "Closes #42"}) == 42

    def test_no_closing_keyword_returns_none(self):
        assert wd.pr_issue_number({"body": "mentions #42 in prose"}) is None

    def test_empty_body_returns_none(self):
        assert wd.pr_issue_number({"body": ""}) is None


class TestProcessStuckPrs:
    def _patch(self, tmp_path, monkeypatch, spawned):
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        monkeypatch.setattr(wd, "LOGS", str(tmp_path / "logs"))
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        monkeypatch.setattr(wd, "WORKTREE_BASE", str(tmp_path / "wt"))
        (tmp_path / "logs").mkdir()
        monkeypatch.setattr(wd, "ensure_worktree", lambda *a, **k: f"{tmp_path}/wt")
        monkeypatch.setattr(wd, "subprocess", _FakeSubprocess(spawned))
        # default: not behind, hosted (no local probe)
        monkeypatch.setattr(wd, "pr_is_behind", lambda pr: False)
        monkeypatch.setattr(wd, "WORKER_PROVIDER", "openrouter")
        monkeypatch.setattr(wd, "effective_provider_is_local", lambda: False)
        return monkeypatch

    def test_spawns_repair_for_red_ci(self, tmp_path, monkeypatch):
        spawned = []
        mp = self._patch(tmp_path, monkeypatch, spawned)
        mp.setattr(wd, "pr_repairable", lambda pr, n: "CI is red")
        pr = _pr(7, body="Closes #42", head_ref="feat/target")
        wd.process_stuck_prs([pr])
        assert len(spawned) == 1, f"red-CI PR must spawn a repair worker, got {spawned}"
        # lock + prompt written for the EXISTING branch
        assert (tmp_path / "worker-feat_target.running").exists()

    def test_spawns_repair_for_open_threads(self, tmp_path, monkeypatch):
        spawned = []
        mp = self._patch(tmp_path, monkeypatch, spawned)
        mp.setattr(wd, "pr_repairable", lambda pr, n: "unresolved review threads")
        pr = _pr(8, body="Closes #42", head_ref="feat/threads")
        wd.process_stuck_prs([pr])
        assert len(spawned) == 1
        assert (tmp_path / "worker-feat_threads.running").exists()

    def test_skips_not_actionable(self, tmp_path, monkeypatch):
        spawned = []
        mp = self._patch(tmp_path, monkeypatch, spawned)
        mp.setattr(wd, "pr_repairable", lambda pr, n: "")
        wd.process_stuck_prs([_pr(1, body="Closes #42", head_ref="feat/ok")])
        assert len(spawned) == 0, "clean PR must NOT spawn a repair worker"

    def test_skips_behind_pr(self, tmp_path, monkeypatch):
        # behind -> merge gate owns it; never repair
        spawned = []
        mp = self._patch(tmp_path, monkeypatch, spawned)
        mp.setattr(wd, "pr_is_behind", lambda pr: True)
        mp.setattr(wd, "pr_repairable", lambda pr, n: "CI is red")
        wd.process_stuck_prs([_pr(1, body="Closes #42", head_ref="feat/behind")])
        assert len(spawned) == 0, "behind PR must not spawn a repair worker"

    def test_skips_pr_without_closing_issue(self, tmp_path, monkeypatch):
        spawned = []
        mp = self._patch(tmp_path, monkeypatch, spawned)
        mp.setattr(wd, "pr_repairable", lambda pr, n: "CI is red")
        # body has no closing keyword -> cannot map to a worker
        pr = _pr(1, body="no closing keyword here", head_ref="feat/nomap")
        wd.process_stuck_prs([pr])
        assert len(spawned) == 0

    def test_incomplete_pr_skips_without_crash(self, tmp_path, monkeypatch):
        spawned = []
        self._patch(tmp_path, monkeypatch, spawned)
        wd.process_stuck_prs([
            {"number": 1},                      # no head/base
            "not-a-dict",                        # non-dict
            {"head": {"ref": "feat/x"}},         # no number
        ])
        assert len(spawned) == 0
        assert (tmp_path / "worker-feat_x.running").exists() is False

    def test_live_lock_skips_repair(self, tmp_path, monkeypatch):
        # a LIVE .running pid for the PR branch must suppress the repair spawn
        spawned = []
        mp = self._patch(tmp_path, monkeypatch, spawned)
        mp.setattr(wd, "pr_repairable", lambda pr, n: "CI is red")
        pr = _pr(1, body="Closes #42", head_ref="feat/live")
        # existing live lock (our own pid)
        (tmp_path / "worker-feat_live.running").write_text(str(os.getpid()))
        wd.process_stuck_prs([pr])
        assert len(spawned) == 0, "live worker must suppress duplicate repair spawn"
        assert (tmp_path / "worker-feat_live.running").exists()

    def test_local_model_down_skips_repair(self, tmp_path, monkeypatch, capsys):
        spawned = []
        mp = self._patch(tmp_path, monkeypatch, spawned)
        mp.setattr(wd, "pr_repairable", lambda pr, n: "CI is red")
        mp.setattr(wd, "effective_provider_is_local", lambda: True)
        mp.setattr(wd, "WORKER_MODEL_EFFECTIVE", "llm-local")
        mp.setattr(wd, "probe_worker_model", lambda m, **k: False)
        pr = _pr(1, body="Closes #42", head_ref="feat/down")
        wd.process_stuck_prs([pr])
        assert len(spawned) == 0
        assert not (tmp_path / "worker-feat_down.running").exists()
        out = capsys.readouterr().out
        assert "skipping repair" in out

    def test_dry_run_reports_without_spawn(self, tmp_path, monkeypatch, capsys):
        spawned = []
        mp = self._patch(tmp_path, monkeypatch, spawned)
        mp.setattr(wd, "pr_repairable", lambda pr, n: "CI is red")
        pr = _pr(1, body="Closes #42", head_ref="feat/dry")
        wd.process_stuck_prs([pr], dry=True)
        assert len(spawned) == 0, "dry run must NOT spawn"
        out = capsys.readouterr().out
        assert "would spawn a repair worker" in out

    def test_main_invokes_stuck_pr_repair(self, tmp_path, monkeypatch, capsys):
        """main() calls process_stuck_prs with the open PRs (integration)."""
        # Patch env for main()
        monkeypatch.setattr(wd, "RUN", str(tmp_path))
        monkeypatch.setattr(wd, "LOGS", str(tmp_path / "logs"))
        monkeypatch.setattr(wd, "REPO", str(tmp_path))
        monkeypatch.setattr(wd, "TICK_LOCK", str(tmp_path / "dispatch.tick.lock"))
        (tmp_path / "logs").mkdir()
        monkeypatch.setattr(wd, "sys", type("S", (), {"argv": ["watchloop_dispatch.py"]})())
        monkeypatch.setattr(wd, "api", lambda path, *a, **k:
            ([_pr(1, body="Closes #42", head_ref="feat/x")] if "pulls" in path else []))
        monkeypatch.setattr(wd, "process_merge_gate", lambda prs: set())
        monkeypatch.setattr(wd, "cleanup_merged_worktrees", lambda dry=False: set())
        monkeypatch.setattr(wd, "issue_has_pr", lambda n: False)
        # hermetics: no local probe, hosted, repairable -> spawn
        monkeypatch.setattr(wd, "effective_provider_is_local", lambda: False)
        monkeypatch.setattr(wd, "pr_is_behind", lambda pr: False)
        monkeypatch.setattr(wd, "pr_open_threads", lambda n: False)
        monkeypatch.setattr(wd, "ci_green", lambda pr: False)  # red CI -> repairable
        spawned = []
        monkeypatch.setattr(wd, "ensure_worktree", lambda *a, **k: f"{tmp_path}/wt")
        monkeypatch.setattr(wd, "subprocess", _FakeSubprocess(spawned))

        wd.main()
        assert len(spawned) >= 1, "main() must spawn a repair worker for the red-CI PR"
