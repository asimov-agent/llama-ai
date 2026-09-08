#!/usr/bin/env python3
"""watch_report.py — human-readable observability for the llama-ai watch loop.

Answers three questions about the autonomous cron agents (project-manager
sessions spawned by scripts/watchloop_dispatch.py):
  1. WHAT work did they do?        -> per-issue session summaries from worker logs
  2. OUTPUT RATE?                  -> merges, spawns, PRs per window
  3. CI-RED REACTION?              -> repair-stage events + live PR CI states

Everything is host-side (no container, no network beyond `gh`/git for live
state). It reads:
  - .watchloop/logs/*.log       per-issue worker logs (STATUS/WATCH-LOOP SUMMARY)
  - .watchloop/run/dispatch.log dispatcher tick timeline
  - live GitHub (gh)            open issues/PRs + CI check states

Usage:  python3 scripts/watch_report.py [--window N]
        (--window N = show last N dispatch-log ticks / worker-log entries)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUN = REPO / ".watchloop" / "run"
LOGS = REPO / ".watchloop" / "logs"
DISPATCH_LOG = RUN / "dispatch.log"

NOW = dt.datetime.now()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _ts_to_dt(epoch: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(epoch)


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""


def _gh_json(args: list[str], fields: str) -> list | dict:
    out = _run(["gh", *args, "--json", fields])
    try:
        return json.loads(out)
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# 1) per-issue worker sessions (WHAT)
# --------------------------------------------------------------------------- #
def collect_worker_sessions() -> list[dict]:
    """Parse each worker log into a session record."""
    sessions = []
    if not LOGS.is_dir():
        return sessions
    for logf in sorted(LOGS.glob("*.log")):
        text = logf.read_text(errors="replace")
        # Earliest heartbeat epoch -> session start time (a real clock timestamp)
        epochs = [int(m) for m in re.findall(r"\[hb (\d+)\]", text)]
        started = _ts_to_dt(epochs[0]).strftime("%Y-%m-%d %H:%M") if epochs else "?"
        # Summary markers
        status = "running"
        if "STATUS: DONE" in text or "STATUS: DONE" in text:
            status = "done"
        if re.search(r"STATUS:\s*DONE", text):
            status = "done"
        issue = ""
        m = re.search(r"^Issue:\s*#?(\d+)", text, re.M)
        if m:
            issue = m.group(1)
        pr = ""
        m = re.search(r"(?:PR|Pull request):\s*#?(\d+)", text)
        if m:
            pr = m.group(1)
        branch = ""
        m = re.search(r"^Branch:\s*(\S+)", text, re.M)
        if m:
            branch = m.group(1)
        # Count gates claimed in the log
        gates = len(re.findall(r"\bmake [a-z-]+\b", text))
        # 'What this tick did' snippet
        snippet = ""
        m = re.search(r"(What this tick did[^\n]*\n(?:.*\n){0,6})", text)
        if m:
            snippet = m.group(1).strip()
        sessions.append({
            "file": logf.name,
            "issue": issue,
            "pr": pr,
            "branch": branch,
            "status": status,
            "started": started,
            "hb_count": len(epochs),
            "gates": gates,
            "snippet": snippet[:300],
            "hb_epochs": epochs,
        })
    return sessions


# --------------------------------------------------------------------------- #
# 2) dispatch timeline (OUTPUT RATE + CI-RED reaction)
# --------------------------------------------------------------------------- #
def collect_dispatch_timeline(window: int = 60) -> list[dict]:
    """Parse dispatch.log lines into event records (most recent window)."""
    events = []
    if not DISPATCH_LOG.exists():
        return events
    lines = DISPATCH_LOG.read_text(errors="replace").splitlines()
    for ln in lines[-window:]:
        m = re.match(r"\[dispatch (\d{2}:\d{2}:\d{2})\]\s*(.*)", ln)
        if not m:
            continue
        clock, body = m.group(1), m.group(2)
        kind = "other"
        if "tick start" in body:
            kind = "tick-start"
        elif "tick done" in body:
            kind = "tick-done"
        elif "spawning worker" in body:
            kind = "spawn"
        elif body.startswith("repair-PR"):
            kind = "repair"
        elif body.startswith("[clean]"):
            kind = "clean"
        elif re.match(r"PR#\d+: not approved", body):
            kind = "merge-wait"
        elif "merged" in body and "PR#" in body:
            kind = "merge"
        elif body.startswith("issue#"):
            kind = "issue"
        events.append({"clock": clock, "body": body, "kind": kind})
    return events


def live_github_state() -> dict:
    """Open issues/PRs + CI check states via gh."""
    prs = _gh_json(["pr", "list", "--state", "open", "--base", "main"],
                   "number,title,state,mergeable,mergeStateStatus,reviewDecision,headRefName")
    issues = _gh_json(["issue", "list", "--state", "open"], "number,title,state")
    return {"prs": prs if isinstance(prs, list) else [], "issues": issues if isinstance(issues, list) else []}


def pr_ci_status(pr_num: int) -> str:
    """Return a compact CI verdict for a PR (all-pass / running / has-failures)."""
    out = _run(["gh", "pr", "checks", str(pr_num)])
    if not out:
        return "no-CI-info"
    pass_c = len(re.findall(r"\tpass\t", out))
    fail_c = len(re.findall(r"\tfail\t", out))
    pend_c = len(re.findall(r"\tpending\t", out))
    if fail_c:
        return f"{fail_c} FAIL / {pass_c} pass / {pend_c} pending"
    if pend_c:
        return f"{pass_c} pass / {pend_c} pending"
    return f"{pass_c} pass (all green)"


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def fmt_now() -> str:
    return NOW.strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    window = 60
    for i, a in enumerate(sys.argv):
        if a == "--window" and i + 1 < len(sys.argv):
            window = int(sys.argv[i + 1])

    print("=" * 78)
    print(f"WATCH-LOOP STATUS REPORT   ({fmt_now()})")
    print("=" * 78)

    # ---- live GitHub state ----
    state = live_github_state()
    prs, issues = state["prs"], state["issues"]
    print("\n## LIVE GitHub state")
    print(f"  open issues: {len(issues)}   open PRs: {len(prs)}")
    if issues:
        for i in issues:
            n = i.get("number"); t = i.get("title", "")
            print(f"    #{n}  {t[:70]}")
    if prs:
        print("  open PRs + CI:")
        for p in prs:
            n = p.get("number"); t = p.get("title", "")[:55]
            ms = p.get("mergeStateStatus", "?")
            rd = p.get("reviewDecision") or "no-review"
            ci = pr_ci_status(n)
            print(f"    #{n}  {t}")
            print(f"        mergeState={ms}  review={rd}")
            print(f"        CI: {ci}")

    # ---- worker sessions (WHAT) ----
    sessions = collect_worker_sessions()
    print(f"\n## Worker sessions (from .watchloop/logs, {len(sessions)} logs)")

    # Liveness is determined by the RECENCY of the last heartbeat, not by the
    # absence of a DONE marker: a leftover log from a long-finished branch keeps
    # heartbeats from days ago. A worker is LIVE if its last heartbeat is within
    # ~2 intervals (40 min). 'stale' = old heartbeats, no DONE marker.
    cutoff = (NOW - dt.timedelta(minutes=40)).timestamp()
    live = [s for s in sessions if s["hb_epochs"] and s["hb_epochs"][-1] >= cutoff and s["status"] != "done"]
    stale = [s for s in sessions if s not in live and s["status"] != "done"]
    print(f"  LIVE workers (heartbeat within 40 min): {len(live)}")
    for s in live:
        last = _ts_to_dt(s["hb_epochs"][-1]).strftime("%H:%M")
        print(f"    ▶ {s['started']}  last-hb={last}  issue#{s['issue'] or '?'}  PR#{s['pr'] or '?'}  "
              f"branch={s['branch'] or '?'}")
    print(f"  STALE/DONE logs (no live worker): {len(stale) + len([s for s in sessions if s['status']=='done'])}")
    for s in sessions:
        flag = "DONE" if s["status"] == "done" else "stale"
        if s["status"] == "done" or s in stale:
            print(f"    [{flag}] {s['started']}  issue#{s['issue'] or '?'}  PR#{s['pr'] or '?'}  "
                  f"hb={s['hb_count']}  {s['branch'] or ''}")
            if s["snippet"] and s["status"] == "done":
                print(f"             {s['snippet'].splitlines()[0][:110]}")

    # ---- dispatch timeline (OUTPUT RATE + CI-red reaction) ----
    events = collect_dispatch_timeline(window)
    print(f"\n## Dispatcher timeline (last {window} log lines)")
    kinds = Counter(e["kind"] for e in events)
    print(f"  tick-starts={kinds.get('tick-start',0)}  tick-dones={kinds.get('tick-done',0)} "
          f"  spawns={kinds.get('spawn',0)}  repairs={kinds.get('repair',0)} "
          f"  merge-waits={kinds.get('merge-wait',0)}")
    # dedup sanity: tick starts vs dones
    starts = kinds.get("tick-start", 0); dones = kinds.get("tick-done", 0)
    if starts != dones:
        print(f"  ⚠ tick-start({starts}) != tick-done({dones}) — possible doubled/incomplete run")
    print("  last events:")
    for e in events[-12:]:
        mark = {"spawn": "▶", "repair": "🔧", "merge": "✓", "tick-start": "◆", "tick-done": "◇"}.get(e["kind"], " ")
        print(f"    {mark} {e['clock']}  {e['body'][:90]}")

    # ---- CI-red reaction summary ----
    repairs = [e for e in events if e["kind"] == "repair"]
    red_now = [p for p in prs if "FAIL" in pr_ci_status(p.get("number", 0)) or "fail" in pr_ci_status(p.get("number", 0)).lower()]
    print("\n## CI-red reaction")
    print(f"  repair-stage actions in window: {len(repairs)}")
    if red_now:
        print("  PRs with red CI right now (candidates needing repair):")
        for p in red_now:
            print(f"    #{p.get('number')}  {pr_ci_status(p.get('number', 0))}")
    else:
        print("  No PR currently has failing CI.")

    print("\n" + "=" * 78)
    print("End of report. (data: .watchloop logs + dispatch.log + live gh state)")


if __name__ == "__main__":
    main()
