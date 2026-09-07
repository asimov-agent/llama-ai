# Spec: Activity-based worker liveness in the dispatch loop (issue #63)

## Why
A worker whose PID is alive but whose log never advances is indistinguishable from a healthy worker by
`pid_alive`, so a hung worker holds its `.running` lock forever and its issue is never re-driven. We add
an *activity* signal (log growth) folded into one "is this worker healthy" predicate.

---

## MODIFIED Requirements

### Requirement: B1 — The alive-lock check is activity-based, not PID-only
WHEN a dispatch tick evaluates a worker lock whose recorded PID is alive,
THEN the worker is treated as healthy and the spawn suppressed **only if** its own worker log has been
written within the stale threshold; a live worker whose log has been silent for longer than the threshold
is considered stuck.

#### Scenario: live PID + fresh log → worker left untouched
Given   the recorded worker PID is alive,
And     its worker log (`feat-<slug>.log`) was written within `STUCK_LOG_STALE_SECONDS`,
When    the dispatch tick checks the lock,
Then    no new worker is spawned,
And     the process tree is NOT killed,
And     the `.running` lock is left in place.

#### Scenario: live PID + stale log → worker killed and issue re-driven
Given   the recorded worker PID is alive,
And     its worker log has not grown for more than `STUCK_LOG_STALE_SECONDS`,
When    the dispatch tick checks the lock,
Then    the worker's process tree is killed,
And     the stale `.running` lock is removed,
And     a fresh worker is spawned for the issue (resuming from its own log).

### Requirement: B2 — The dead-PID path is unchanged
WHEN a dispatch tick evaluates a worker lock whose recorded PID is dead,
THEN the existing issue #18 behavior runs unchanged: the stale lock is removed and a fresh worker is
spawned (the stuck path is purely additive).

#### Scenario: dead PID → existing clean + respawn
Given   the recorded worker PID is dead,
When    the dispatch tick checks the lock,
Then    the `.running` lock is removed,
And     a fresh worker is spawned,
And     no "stuck" kill path is taken.

### Requirement: B3 — Stuck detection keys off log staleness, not wall-clock age
WHEN a worker's log was recently written and then goes quiet,
THEN it is only flagged as stuck once the quiet window since its **most recent** log write exceeds the
stale threshold — not immediately based on how long the worker has existed.

#### Scenario: quiet after a write is only fatal past the threshold
Given   a worker wrote to its log (mtime advances) and then becomes quiet,
When    the elapsed time since the most recent log write is still under `STUCK_LOG_STALE_SECONDS`,
Then    the worker is NOT killed,
And    only after that quiet window exceeds the threshold is the worker treated as stuck.

---

## VERIFICATION

### Verification: B1
- `TestStuckWorkerResume.test_live_pid_with_fresh_log_not_killed`: live PID + mtime within threshold →
  no kill, no respawn, lock preserved.
- `TestStuckWorkerResume.test_live_pid_with_stale_log_is_killed_and_respawned`: live PID + mtime past
  threshold → tree killed, lock removed, fresh spawn issued.
### Verification: B2
- Existing `TestSpawnWorkerLock.test_alive_pid_lock_skips_spawn` stays green (live + no stale log) and
  `test_dead_pid_lock_is_removed_and_spawned` stays green (dead PID → clean + respawn).
### Verification: B3
- `TestStuckWorkerResume.test_stuck_detection_uses_log_growth_not_wall_clock`: a worker whose mtime is
  within the threshold is not flagged regardless of when it started.
### Regression
- `make lint`, `make test-unit`; `make openspec-validate`; CI unit job green.
