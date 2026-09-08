"""Hermetic unit tests for scripts/watch_report.py.

These exercise the pure parsing/classification helpers against fixture-shaped
.watchloop data. All tests are hermetic: they monkeypatch the module's LOGS /
DISPATCH_LOG / gh path to temp fixtures — no real logs, no GitHub, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scripts.watch_report as wr  # noqa: E402


# --------------------------------------------------------------------------- #
# worker-session parsing (WHAT)
# --------------------------------------------------------------------------- #
class TestWorkerSessions:
    def _write_log(self, tmp_path, name, content):
        (tmp_path / "logs").mkdir(exist_ok=True)
        (tmp_path / "logs" / name).write_text(content)
        return tmp_path / "logs" / name

    def test_parses_issue_pr_branch_and_status(self, tmp_path, monkeypatch):
        """A worker log's Issue/Branch/PR/STATUS markers are parsed."""
        # Given a completed worker log with the standard summary markers
        self._write_log(tmp_path, "feat-x.log", (
            "[hb 1788893105]\n"
            "WATCH-LOOP SUMMARY\n"
            "Issue: #61\n"
            "Branch: feat/feat-top-tier-download-top-tier-family-keyword-top\n"
            "PR: #72\n"
            "STATUS: DONE\n"
        ))
        monkeypatch.setattr(wr, "LOGS", tmp_path / "logs")
        # When we collect worker sessions
        sessions = wr.collect_worker_sessions()
        # Then the markers are parsed
        assert len(sessions) == 1
        s = sessions[0]
        assert s["issue"] == "61"
        assert s["pr"] == "72"
        assert s["status"] == "done"
        assert s["hb_count"] == 1
        assert "feat-top-tier" in s["branch"]

    def test_log_without_markers_is_running_blank(self, tmp_path, monkeypatch):
        """A log with only heartbeats (no DONE marker) parses as running/blank."""
        # Given a worker log with only heartbeats (in-flight, no summary yet)
        self._write_log(tmp_path, "feat-y.log", "[hb 1788893105]\n[hb 1788893405]\n")
        monkeypatch.setattr(wr, "LOGS", tmp_path / "logs")
        # When we collect worker sessions
        sessions = wr.collect_worker_sessions()
        # Then it parses with running status and no issue/PR markers
        assert len(sessions) == 1
        s = sessions[0]
        assert s["status"] == "running"
        assert s["issue"] == ""
        assert s["pr"] == ""
        assert s["hb_count"] == 2

    def test_heartbeat_recentcy_classifies_live(self, tmp_path, monkeypatch):
        """A recent heartbeat means LIVE; an old one means STALE.

        # Given a log whose last heartbeat is within 40 minutes of now,
        # When   we apply the liveness rule,
        # Then   it is LIVE; a log with an old last heartbeat is STALE.
        """
        import time
        self._write_log(tmp_path, "live.log", f"[hb {int(time.time())}]\n")
        self._write_log(tmp_path, "old.log", "[hb 1]\n")  # 1970 -> very stale
        monkeypatch.setattr(wr, "LOGS", tmp_path / "logs")
        sessions = wr.collect_worker_sessions()
        now = wr.dt.datetime.now()
        cutoff = (now - wr.dt.timedelta(minutes=40)).timestamp()
        live = [s for s in sessions if s["hb_epochs"] and s["hb_epochs"][-1] >= cutoff and s["status"] != "done"]
        stale = [s for s in sessions if s not in live and s["status"] != "done"]
        # Then live.log is LIVE (recent), old.log is STALE
        assert [s["file"] for s in live] == ["live.log"]
        assert [s["file"] for s in stale] == ["old.log"]


# --------------------------------------------------------------------------- #
# dispatcher timeline parsing + event classification
# --------------------------------------------------------------------------- #
class TestDispatchTimeline:
    def _write_dispatch(self, tmp_path, lines):
        (tmp_path / "run").mkdir(exist_ok=True)
        f = tmp_path / "run" / "dispatch.log"
        f.write_text("\n".join(lines) + "\n")
        return f

    def test_classifies_event_types(self, tmp_path, monkeypatch):
        """dispatch.log lines classify as spawn/repair/merge-wait/clean/tick."""
        # Given a dispatch.log with a mix of event types
        logf = self._write_dispatch(tmp_path, [
            "[dispatch 21:00:00] tick start",
            "[dispatch 21:00:03]   issue#61: PR in flight, no spawn",
            "[dispatch 21:00:04]   issue#61: spawning worker branch=y",
            "[dispatch 21:00:05]   repair-PR#72: spawning worker branch=x",
            "[dispatch 21:00:06]   PR#72: not approved -> NOT merged",
            "[dispatch 21:00:07]   [clean] feat-x: not merged (in flight) — keep",
            "[dispatch 21:00:09] tick done",
        ])
        monkeypatch.setattr(wr, "DISPATCH_LOG", logf)
        # When we parse the timeline
        events = wr.collect_dispatch_timeline(window=60)
        kinds = {e["kind"] for e in events}
        # Then each event type is classified
        assert "spawn" in kinds
        assert "repair" in kinds
        assert "merge-wait" in kinds
        assert "clean" in kinds
        assert "tick-start" in kinds
        assert "tick-done" in kinds

    def test_tick_balance_warning_signal(self, tmp_path, monkeypatch):
        """An unequal tick-start/tick-done count in the window is detectable.

        # Given a dispatch.log with 2 tick starts but 1 tick done (doubled run),
        # When   the report computes the balance,
        # Then   it flags tick-start != tick-done as a possible doubled run.
        """
        logf = self._write_dispatch(tmp_path, [
            "[dispatch 21:00:00] tick start",
            "[dispatch 21:00:00] tick start",  # doubled
            "[dispatch 21:00:09] tick done",
        ])
        monkeypatch.setattr(wr, "DISPATCH_LOG", logf)
        events = wr.collect_dispatch_timeline(window=60)
        from collections import Counter
        kinds = Counter(e["kind"] for e in events)
        starts = kinds.get("tick-start", 0)
        dones = kinds.get("tick-done", 0)
        # Then the imbalance is detected
        assert starts == 2 and dones == 1
        assert starts != dones
