# watch-loop-status-report — spec of record

Capabilities this change adds to the llama-ai repo for observing the autonomous
watch loop.

## ADDED Requirements

### Requirement: on-demand human-readable watch-loop status report
`make watch-report` MUST produce a human-readable report, from the repo's own
`.watchloop` logs and live GitHub state, that answers whether the cron agents
are working. It MUST run host-side (no container) and use only the Python
standard library plus the `gh` CLI.

WHEN a user runs `make watch-report`, THEN it prints a report with all of:
(a) open issues and open PRs with each PR's merge-state, review decision, and
compact CI verdict; (b) the worker sessions found in `.watchloop/logs`, each
with its issue, PR, branch, heartbeat count, and a "what this tick did" snippet
when present; (c) a dispatcher timeline of the most recent events classified by
type (spawn / repair / merge-wait / clean / tick); and (d) a CI-red-reaction
summary (repair-stage actions in the window plus any PR currently showing
failing CI).

#### Scenario: live GitHub state is listed
- **Given** the repo has open issues and open PRs,
- **When** `make watch-report` runs,
- **Then** it lists each open issue and open PR,
- **And** for each open PR it shows `mergeStateStatus`, the review decision,
- **And** a compact CI verdict (e.g. "17 pass / 1 fail / 0 pending").

#### Scenario: live vs stale worker sessions are distinguished
- **Given** `.watchloop/logs` contains both a currently-running worker log
  (recent heartbeats) and a leftover log from a long-finished branch (old
  heartbeats) and a log carrying a `STATUS: DONE` marker,
- **When** the report runs,
- **Then** the worker with a heartbeat within the last 40 minutes is labelled
  LIVE,
- **And** logs with older heartbeats or a `STATUS: DONE` marker are labelled
  STALE/DONE (not mistaken for active workers).

#### Scenario: dispatcher timeline flags a doubled run
- **Given** `dispatch.log` contains an unequal number of `tick start` and
  `tick done` lines in the report window,
- **When** the report runs,
- **Then** it prints a warning that tick-starts != tick-dones (possible
  doubled/incomplete run).

#### Scenario: CI-red reaction is surfaced
- **Given** an open PR currently has at least one failing CI check,
- **When** the report runs,
- **Then** it lists that PR under "PRs with red CI right now" with its CI
  verdict,
- **And** it reports the number of repair-stage actions in the dispatch
  window.

### Requirement: report is host-side and parameterized
The report MUST run on the host (no container, nothing to provision) and accept
a window parameter controlling how many `dispatch.log` lines are analyzed.

WHEN the report runs with no arguments, THEN it analyzes a default window of the
most recent 60 `dispatch.log` lines; WHEN run with `--window N`, THEN it
analyzes the most recent N lines.

#### Scenario: default and custom windows
- **Given** `scripts/watch_report.py` exists,
- **When** run with no window argument,
- **Then** it uses the default window of 60 lines,
- **And** when run with `--window 200` it uses 200 lines.
