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
a window parameter controlling how many `dispatch.log` lines are analyzed, plus
a `--watchloop <dir>` override pointing it at a fixture `.watchloop` tree (used
by CI and tests so the command is exercised without the host-only real loop
data).

WHEN the report runs with no arguments, THEN it analyzes a default window of the
most recent 60 `dispatch.log` lines; WHEN run with `--window N`, THEN it
analyzes the most recent N lines; WHEN run with `--watchloop <dir>`, THEN it
reads `.watchloop`-shaped data from `<dir>` (fixtures) instead of the repo's
real `.watchloop`.

#### Scenario: default and custom windows
- **Given** `scripts/watch_report.py` exists,
- **When** run with no window argument,
- **Then** it uses the default window of 60 lines,
- **And** when run with `--window 200` it uses 200 lines.

#### Scenario: fixture .watchloop override
- **Given** a directory containing `.watchloop`-shaped fixture data (a `logs/`
  dir and a `run/dispatch.log`),
- **When** the report runs with `--watchloop <that dir>`,
- **Then** it reads the worker logs and dispatch timeline from `<that dir>`
  instead of the repo's real `.watchloop`,
- **And** the report still prints all sections (used by CI/tests without real
  loop data).

### Requirement: the make target is exercised in CI
`make watch-report` MUST be executed by a CI job (against fixture `.watchloop`
data and a fake `gh` shim on PATH) so the actual command — not just its unit
tests — is gate-checked and fails CI if it errors.

WHEN the CI `watch-report` job runs, THEN it puts a fixture `gh` shim on PATH,
sets `WATCH_REPORT_FIXTURE_ROOT`, runs `make watch-report WATCHLOOP=<fixtures>`,
and asserts the output contains all four report sections and the fixture's
failing-CI signal; any missing section or non-zero exit fails the job.

#### Scenario: watch-report CI job asserts sections
- **Given** the fixture `.watchloop` tree and fake `gh` shim are committed,
- **When** the CI `watch-report` job runs `make watch-report` against them,
- **Then** the job passes only if the report exits 0,
- **And** prints `## LIVE GitHub state`, `## Worker sessions`,
  `## Dispatcher timeline`, and `## CI-red reaction`,
- **And** surfaces the fixture's failing CI check.
