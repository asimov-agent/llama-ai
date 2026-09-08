# Watch-loop dispatcher — spec of record

Capabilities this change adds to the watch-loop dispatcher worker liveness.

## MODIFIED Requirements

### Requirement: B1 — Worker liveness keys off a heartbeat, not hermes stdout

WHEN a dispatch tick evaluates a worker lock whose recorded PID is alive,
THEN the worker is treated as healthy (spawn suppressed) when its own worker log has been
written within the stale threshold; a live worker whose log has been silent for longer than
`STUCK_LOG_STALE_SECONDS` is considered stuck. The worker log is advanced by a **spawn-wrapper
heartbeat** every `WORKER_LOG_HEARTBEAT_SECONDS` as long as the hermes child is alive, so a
productive-but-slow worker (whose hermes `-Q`/`--oneshot` stdout is buffered until exit and never
streams mid-run) never appears stuck.

#### Scenario: live worker + fresh log (heartbeat-fed) → left untouched
Given   a worker was spawned with the heartbeat wrapper,
And     its recorded PID is alive,
And     its worker log was written within `STUCK_LOG_STALE_SECONDS` (the wrapper's heartbeat advances it),
When    the dispatch tick checks the lock,
Then    no new worker is spawned,
And     the process tree is NOT killed,
And     the `.running` lock is left in place,
And     this holds even if the worker's hermes stdout has produced nothing (it is buffered until exit).

#### Scenario: worker process tree dies → dead-PID path reclaims
Given   a worker's process tree has exited (PID no longer alive),
When    the dispatch tick checks the lock,
Then    the existing issue #18 dead-PID path removes the stale lock and spawns a fresh worker,
And     no heartbeat/stuck path is required (the dead PID is reclaimed immediately).

### Requirement: B2 — Stuck detection uses a long true-hang horizon

WHEN a worker's log has been silent longer than the stale threshold,
THEN it is only reclaimed as stuck on a horizon long enough that no productive worker can
plausibly exceed it; a truly hung worker is reclaimed after that horizon, but a productive worker
is never killed mid-work.

#### Scenario: a hung worker is reclaimed only after the long horizon
Given   a worker's recorded PID is alive,
And     its worker log has not been written for more than `STUCK_LOG_STALE_SECONDS` (default 4 h,
        far beyond the 5-min heartbeat cadence),
When    the dispatch tick checks the lock,
Then    the worker is treated as stuck only after that genuine long silence,
And     a productive worker (heartbeat every 5 min) can never reach that silence while alive.

## VERIFICATION

### Verification: B1
- `TestStuckWorkerResume` stays green: a fresh (within-threshold) log on a live PID is not killed.
- e2e `TestDispatchE2E` real-spawn lifecycle stays green.
### Verification: B2
- New unit test asserts the spawn command embeds the heartbeat loop and
  `WORKER_LOG_HEARTBEAT_SECONDS`.
### Verification: B3 (CI-gate hardening)
- `test_check_openspec_tasks.py::test_scoping_check_to_one_change_misses_unticked_in_another`:
  a NAME-scoped `openspec-tasks-check` (the old CI wiring) misses an unticked task in a
  feature PR's own change, while the all-active scan (no NAME — what the openspec CI job now
  runs) returns 1. Guards against re-introducing the CI gap that let #69's unticked task pass.
### Regression
- `make lint`, `make test-unit`, `make openspec-validate`; CI unit job green.
- The openspec CI job runs `make openspec-tasks-check` (all active changes), not
  `NAME=ci-pipeline`, so a PR adding an incomplete change fails RED.
