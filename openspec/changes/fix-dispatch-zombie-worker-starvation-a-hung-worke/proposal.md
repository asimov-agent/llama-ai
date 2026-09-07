# Fix zombie-worker starvation: a hung worker (alive PID, no progress) holds its lock forever (issue #63)

## Problem

`scripts/watchloop_dispatch.py` decides "a worker is already running" by PID alone:

```python
if pid_alive(live_pid):
    log(f"  {log_prefix}: worker already running (pid={live_pid}, {lk}); skip")
    return False
```

`pid_alive` cannot distinguish *working* from *hung*. A dead-PID lock is auto-cleaned and the worker
respawned (issue #18), but a **live-but-hung** PID is treated as healthy forever, so the issue is never
re-driven. Reproduced live 2026-09-07: issues #61, #62 and #63 each held an alive worker (verified PID, `S`
sleeping, 0.0% CPU) with a **0-byte worker log** for 1.5–3+ hours while every dispatch tick logged
`issue#N: worker already running (pid=…); skip`. The dead-PID resume path never fired because the PID
never died, so all three issues starved indefinitely.

## Change

1. **Activity-based liveness.** Add a `STUCK_LOG_STALE_SECONDS` threshold (default **2400 s = 2 dispatch
   intervals / 40 min**) and a `log_stale_seconds(branch_log, now) -> float | None` helper returning
   seconds since the worker's own log (`.watchloop/logs/feat-<slug>.log`) was last written (`None` when
   no log exists → no evidence of a hang).
2. **One health predicate.** Add `worker_is_stuck(live_pid, branch_log, now) -> bool`: a worker is stuck
   only when its PID is alive **AND** its log has not grown for `> STUCK_LOG_STALE_SECONDS`. A dead PID
   is *not* "stuck" — the existing issue #18 dead-PID path stays unchanged. A missing log is *not*
   stuck (a freshly-started worker with no flush yet must not be killed).
3. **On stuck, kill + resume.** In `_spawn_worker_for_branch`, replace the live-PID skip with the health
   predicate. When a live worker is found stuck, `kill_process_tree(live_pid)` removes it (its own bash
   parent + every descendant), the stale `.running` lock is removed, and the normal orphan spawn issues
   a fresh worker that resumes the issue from its own log.
4. **Tolerate the slow backend.** The threshold is based on *no log growth*, not wall-clock age since
   spawn, so a single slow `llm-local` call (~170 s) or a large-model download that still flushes
   progress is never killed — only a worker whose log goes silent for 40 min is reclaimed.

## Verification

- Hermetic tests in `tests/test_watchloop_dispatch.py` (`TestStuckWorkerResume`, mirroring the existing
  `TestSpawnWorkerLock` style — stub the clock / log mtime / `pid_alive` / `subprocess`):
  1. live PID + fresh log → worker NOT touched (no kill, no respawn);
  2. live PID + stale log → process tree killed, `.running` lock removed, fresh spawn issued;
  3. existing dead-PID path stays green (additive);
  4. stuck detection keys off log staleness (last write), not wall-clock age since spawn.
- Regression: `make lint`, `make test-unit`; `make openspec-validate`; CI unit job green.