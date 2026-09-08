# watch-loop-status-report

## Implementation

- [x] 1.1 Add `scripts/watch_report.py`: a stdlib-only, host-side report that
      reads `.watchloop/logs/*.log` (worker sessions with issue/PR/branch/
      heartbeat-count + `STATUS: DONE`/`WATCH-LOOP SUMMARY` markers),
      `.watchloop/run/dispatch.log` (event timeline), and live GitHub via `gh`
      (open issues, open PRs with merge-state + review + CI verdict).
- [x] 1.2 Worker liveness is determined by heartbeat recency: LIVE if the last
      heartbeat is within 40 minutes and there is no `STATUS: DONE` marker;
      otherwise STALE/DONE — so leftover logs from finished branches are never
      counted as active workers.
- [x] 1.3 Dispatcher timeline classifies events (spawn/repair/merge-wait/
      clean/tick) and warns if tick-start count != tick-done count (possible
      doubled/incomplete run).
- [x] 1.4 CI-red reaction section reports repair-stage action count in the
      window plus any open PR currently showing failing CI.
- [x] 1.5 Support a `--window N` argument controlling how many dispatch.log
      lines are analyzed (default 60) and a `--watchloop <dir>` override
      pointing the report at a fixture `.watchloop` tree (for CI/tests).

## Tests

- [x] 2.1 Add hermetic tests for the report's pure parsing helpers against
      sample `.watchloop`-shaped fixtures: worker-session parsing
      (issue/PR/branch/STATUS), liveness classification (recent heartbeat =
      LIVE, old heartbeat or DONE = STALE/DONE), and dispatch-timeline event
      classification (spawn/repair/merge-wait/clean/tick) including the
      tick-start/tick-done imbalance warning.

## Infrastructure

- [x] 3.1 Add a `make watch-report` target (host-side `python3
      scripts/watch_report.py`, no container), passing through `WINDOW=N` when
      set and `WATCHLOOP=<dir>` when set.
- [x] 3.2 Add a `watch-report` CI job that exercises the REAL `make
      watch-report` target against a committed fixture `.watchloop` tree
      (`.watchloop`-shaped fixtures under `tests/fixtures/watch-report/`) and a
      fake `gh` shim on PATH — asserting the report exits 0 and prints all four
      sections plus the fixture's failing-CI signal. Mirrors the `cron` job's
      fake-crontab pattern; no real loop data / no GitHub token / no network.

## Verification

- [x] 4.1 `python3 scripts/watch_report.py` runs and prints the four report
      sections against the repo's real `.watchloop` data without error.
- [x] 4.2 The new hermetic tests pass via `make test-unit` (no skips).
- [x] 4.3 `make openspec-validate NAME=watch-loop-status-report` exit 0 and
      `make openspec-tasks-check` clean (all tasks ticked).
- [x] 4.4 `make lint` green (every touched file ends with a trailing newline).
- [x] 4.5 Push to `origin feat/watch-loop-status-report`, open a PR against
      `main`, and confirm CI is green on the PR — including the new
      `watch-report` job that exercises the real make target against fixtures.
