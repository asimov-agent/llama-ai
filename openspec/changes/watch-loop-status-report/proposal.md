# watch-loop-status-report

## Why

The autonomous watch loop (`scripts/watchloop_dispatch.py`, host crontab every
20 min) drives project-manager worker sessions that implement issues and repair
PRs with red CI. There is currently **no way to see, at a glance, whether the
cron agents are actually working** — what each session did, its output rate, and
how it reacted to red CI. The raw data exists (per-worker logs with
`STATUS`/`WATCH-LOOP SUMMARY` markers and epoch heartbeats; `dispatch.log` with
spawn/repair/merge/clean events; live GitHub PR/issue state), but it is
scattered across files and requires manual grepping.

This change adds a single, host-side command — `make watch-report` — that turns
that scattered data into a human-readable status report answering three
questions:

1. **What work did the cron agents do?** — per-issue session summaries parsed
   from worker logs (issue, PR, branch, heartbeat count, "what this tick did").
2. **What is the output rate?** — live open issues/PRs, merge-gate verdicts,
   spawn/repair counts per dispatch window.
3. **How do they react to red CI?** — repair-stage events in the dispatcher
   timeline plus each open PR's current CI verdict.

It is host-side only (no container, no network beyond `gh` for live state), so
it runs in milliseconds and needs nothing provisioned.

## What Changes

- **New `scripts/watch_report.py`** — a pure-python, stdlib-only report that
  reads `.watchloop/logs/*.log`, `.watchloop/run/dispatch.log`, and live GitHub
  (via `gh`) and prints a report with sections:
  - `## LIVE GitHub state` — open issues + open PRs with `mergeStateStatus`,
    review decision, and a compact CI verdict per PR.
  - `## Worker sessions` — distinguishes LIVE workers (last heartbeat within 40
    min) from STALE/DONE logs (old heartbeats or a `STATUS: DONE` marker), so a
    leftover log from a long-finished branch is not mistaken for an active
    worker.
  - `## Dispatcher timeline` — the most recent N `dispatch.log` events
    classified as spawn / repair / merge-wait / clean / tick, with a
    tick-start-vs-tick-done balance check to flag a doubled/incomplete run.
  - `## CI-red reaction` — repair-stage action count in the window plus any PRs
    currently showing failing CI.
- **`make watch-report` target** — runs `python3 scripts/watch_report.py`
  (host-side, no container), optional `WINDOW=N` to control the dispatch-log
  window (default 60).
- **README section** — document how to run and read the report.

## User-Visible Impact

A maintainer can now answer "are the cron agents working?" with one command and
see: how many workers are live right now, what each session did, which PRs are
open and their CI state, and whether the loop reacted to red CI. No impact on
the serving/model code paths.

## Non-Goals

- No change to the dispatcher, worker spawning, merge gate, or repair logic.
- No new live instrumentation in the workers/dispatcher — this reads existing
  logs; structured event capture (if ever wanted) is a separate change.
- No scheduled/automatic report — this is an on-demand command. Automating a
  periodic report is out of scope.
