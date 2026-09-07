"""Real end-to-end test of the dispatcher worker spawn / stuck-reclaim (issue #63).

Unlike the hermetic unit tests (which stub `subprocess`), this drives the REAL
`_spawn_worker_for_branch` against a REAL `/bin/bash -lc` subprocess, so the full
mechanism is exercised:

  * a worker is actually launched (its PID is recorded in the `.running` lock),
  * its own log file actually grows as it writes to stdout (the activity signal),
  * a hung-but-alive worker (PID alive, log stale) is actually killed via
    `kill_process_tree`, the lock removed, and a fresh worker spawned, and
  * the fresh worker actually completes "issue work" — editing a file that the
    test asserts on.

No GitHub API, no LLM, no nerdctl, no network: the worker is a tiny fake script
(acting as the hermes agent) and `ensure_worktree`/`api` are stubbed to the temp
dir. All of it runs in under a minute — this is the CI gate for issue #63.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# The dispatcher reads a token at import time; make collection hermetic.
os.environ.setdefault("GITHUB_TOKEN", "test-token-hermetic")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scripts.watchloop_dispatch as wd  # noqa: E402

MARKER = "ISSUE_63_E2E_WORK_DONE"


def _patch_paths(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """Point the dispatcher at a temp RUN/LOGS/REPO, return (run, logs)."""
    (tmp_path / "logs").mkdir()
    (tmp_path / "worktree").mkdir()
    monkeypatch.setattr(wd, "RUN", str(tmp_path))
    monkeypatch.setattr(wd, "LOGS", str(tmp_path / "logs"))
    monkeypatch.setattr(wd, "REPO", str(tmp_path))
    monkeypatch.setattr(wd, "ensure_worktree", lambda *a, **k: f"{tmp_path}/worktree")
    # Skip the pre-spawn probe entirely: the fake worker needs no local model.
    monkeypatch.setattr(wd, "probe_worker_model", lambda *a, **k: True)
    return tmp_path, tmp_path / "logs"


def _make_fake_worker(tmp_path: Path, marker_rel: str) -> Path:
    """Write a tiny fake 'agent' script that does README issue-work.

    First invocation: creates `$E2E_RESUME` and then SLEEPS forever with no further
    output (a hung worker whose log goes stale after one line). A later invocation
    (after the dispatcher kills + respawns it) sees `$E2E_RESUME` already present
    and instead appends the MARKER line to the target file, then exits — proving
    the fresh worker completed real work.
    """
    script = tmp_path / "fake_agent.sh"
    script.write_text(
        '#!/bin/bash\n'
        'if [ ! -f "$E2E_RESUME" ]; then\n'
        '  touch "$E2E_RESUME"\n'
        '  echo "agent started (will hang)"\n'
        '  exec sleep 3600\n'
        'else\n'
        '  echo "agent resumed: doing issue work"\n'
        f'  echo "{MARKER}" >> "$WORKTREE/{marker_rel}"\n'
        '  exit 0\n'
        'fi\n'
    )
    script.chmod(0o755)
    return script


# --------------------------------------------------------------------------- #
# REAL spawn lifecycle: a healthy worker is left alone (no false kill)
class TestDispatchE2EHealthyWorker:
    def test_healthy_worker_log_grows_and_is_not_killed(self, tmp_path, monkeypatch):
        """A freshly-spawned, progressing worker is never reclaimed."""

        # Given a dispatcher on temp paths and a fake worker that edits README
        run, logs = _patch_paths(tmp_path, monkeypatch)
        worktree = tmp_path / "worktree"
        readme = worktree / "README.md"
        readme.write_text("# llama-ai\n")
        worker = _make_fake_worker(tmp_path, "README.md")
        monkeypatch.setattr(wd, "HERMES", str(worker))
        branch = "feat/e2e-healthy"
        slug = "e2e-healthy"
        branch_log = str(logs / f"feat-{slug}.log")
        lk = str(run / f"worker-{branch.replace('/', '_')}.running")
        prompt = str(run / "worker-prompt")
        with open(prompt, "w") as f:
            f.write("do work")

        # When we spawn the worker (REAL /bin/bash -lc subprocess)
        monkeypatch.setenv("E2E_RESUME", str(tmp_path / "resume"))
        monkeypatch.setenv("WORKTREE", str(worktree))
        ok = wd._spawn_worker_for_branch(branch, slug, str(worktree), branch_log,
                                         lk, prompt, "issue#1")
        assert ok is True

        # Wait for the worker to write to its own log (activity signal)
        deadline = time.time() + 15
        while time.time() < deadline:
            if os.path.exists(branch_log) and os.path.getsize(branch_log) > 0:
                break
            time.sleep(0.2)
        assert os.path.getsize(branch_log) > 0, "worker's own log must have grown"

        # The recorded PID is alive (bash parent of the sleeping fake agent)
        recorded = int(open(lk).read().strip())
        assert wd.pid_alive(recorded), "spawned worker PID must be alive"

        # Then a young log means the worker is NOT stuck (no kill, no respawn)
        killed: list[int] = []
        monkeypatch.setattr(wd, "kill_process_tree", lambda p: killed.append(p))
        assert wd.worker_is_stuck(recorded, branch_log, now=time.time()) is False
        assert killed == [], "a healthy worker must not be killed"

        # Cleanup: kill the sleeping fake agent tree so no stray process lingers
        wd.kill_process_tree(recorded)


# --------------------------------------------------------------------------- #
# REAL reclaim lifecycle: a hung-but-alive worker is killed and re-driven
class TestDispatchE2EStuckReclaim:
    def test_hung_worker_is_killed_and_respawned_does_readme_work(self, tmp_path, monkeypatch):
        """A hung worker is killed; the fresh worker completes README issue-work."""

        # Given a dispatcher on temp paths + a stale threshold of 2s
        run, logs = _patch_paths(tmp_path, monkeypatch)
        worktree = tmp_path / "worktree"
        readme = worktree / "README.md"
        readme.write_text("# llama-ai\n")
        worker = _make_fake_worker(tmp_path, "README.md")
        monkeypatch.setattr(wd, "HERMES", str(worker))
        monkeypatch.setattr(wd, "STUCK_LOG_STALE_SECONDS", 2)

        branch = "feat/e2e-stuck"
        slug = "e2e-stuck"
        branch_log = str(logs / f"feat-{slug}.log")
        lk = str(run / f"worker-{branch.replace('/', '_')}.running")
        prompt = str(run / "worker-prompt")
        with open(prompt, "w") as f:
            f.write("do work")
        monkeypatch.setenv("E2E_RESUME", str(tmp_path / "resume"))
        monkeypatch.setenv("WORKTREE", str(worktree))

        # When the first spawn launches a worker that hangs (logs once, then sleeps)
        assert wd._spawn_worker_for_branch(branch, slug, str(worktree), branch_log,
                                           lk, prompt, "issue#2") is True
        first_pid = int(open(lk).read().strip())
        # wait for it to write its one log line, then confirm it's still alive-but-silent
        deadline = time.time() + 15
        while time.time() < deadline:
            if os.path.exists(branch_log) and os.path.getsize(branch_log) > 0:
                break
            time.sleep(0.2)
        assert os.path.getsize(branch_log) > 0
        assert wd.pid_alive(first_pid), "hung worker must still be alive (not dead)"

        # After the stale threshold with no further log growth, it is STUCK
        time.sleep(2.5)
        assert wd.worker_is_stuck(first_pid, branch_log, now=time.time()) is True

        # When the next tick re-evaluates the lock, it kills the tree + respawns
        ok = wd._spawn_worker_for_branch(branch, slug, str(worktree), branch_log,
                                         lk, prompt, "issue#2")
        assert ok is True, "stuck worker must be reclaimed + respawned"

        # Then the fresh worker actually does the README issue-work
        deadline = time.time() + 15
        while time.time() < deadline:
            if MARKER in readme.read_text():
                break
            time.sleep(0.2)
        assert MARKER in readme.read_text(), \
            "respawned worker must have completed the README issue-work"

        # And the original hung worker's tree is gone (was killed)
        assert not wd.pid_alive(first_pid), "original hung worker must be dead"
        # The lock now points at the fresh worker (or the fresh worker already exited cleanly)
        new_pid = int(open(lk).read().strip())
        assert new_pid != first_pid

        # Cleanup: ensure nothing lingers
        wd.kill_process_tree(new_pid)
