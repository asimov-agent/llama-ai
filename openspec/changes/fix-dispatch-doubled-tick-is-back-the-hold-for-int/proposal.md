# fix-dispatch-doubled-tick-is-back-the-hold-for-int

## Why

The watch-loop dispatcher (`scripts/watchloop_dispatch.py`, host crontab every
20 min) is supposed to run `main()` EXACTLY once per 20-min interval. The
durable "hold-for-interval" tick lock (issue #25/#27/PR #28) is only durable if
the read → decide → write of `TICK_LOCK` is a SINGLE atomic step. The current
reclaim path is NOT atomic (TOCTOU), so a double cron-fire (the same
`*/20` slot firing twice — a real, reproduced symptom) runs `main()` twice:

```python
os.remove(TICK_LOCK)                                    # P1 removes old-bucket lock
fd = os.open(TICK_LOCK, os.O_CREAT | os.O_EXCL | ...)   # P1 creates its lock
os.remove(TICK_LOCK)                                    # P2 removes P1's FRESH lock (same path!)
fd = os.open(TICK_LOCK, os.O_CREAT | os.O_EXCL | ...)   # P2 creates its lock
# => BOTH P1 and P2 proceed to main()  -> two ticks
```

`os.remove(path)` does not compare-and-swap on file contents, so P2 happily
deletes P1's just-created lock. Reproduced live 2026-09-07 18:20→20:20: two
`tick start` + two `tick done` per slot, no `[DEDUP]` lines — a
timing-dependent race (tight window → the second dedups; wide window → both
win).

## What Changes

- **Atomic read-decide-write of the tick lock.** `_tick_lock_acquire` guards the
  entire "read owner → decide (same-bucket ⇒ dedup / older-bucket ⇒ reclaim) →
  write `TICK_LOCK(bucket,pid)`" step with a **short-lived**
  `fcntl.flock(LOCK_EX|LOCK_NB)` meta-lock on a SEPARATE file
  (`TICK_LOCK_META = TICK_LOCK + ".meta"`). The meta-lock is held only for the
  decision (microseconds) and released immediately after the write — it is NOT
  the durable lock. The durable dedup is STILL the bucket recorded inside
  `TICK_LOCK`, exactly as issue #27/#30 require. This removes the
  remove/create TOCTOU entirely.
- **Preserved invariants (non-negotiable):**
  - A FINISHED same-bucket owner (dead pid) STILL dedups a later re-fire
    (issue #30) — the meta-lock does not weaken the "hold for the whole
    interval" guarantee.
  - A NEW interval (different bucket) reclaims an OLDER-bucket lock exactly
    once.
  - A deduped process logs `[DEDUP] tick skipped ...` and does NOT log
    `tick start`.
  - A crash mid-tick leaves the lock held; the NEXT interval (different bucket)
    reclaims it.
- **No fallback.** One acquisition path. There is NO "if the meta-lock is busy
  just run anyway" branch and no second lock scheme. If the atomic decision
  cannot be taken, the tick is SKIPPED (dedup), never double-run.
- **Worktree-aware container mount (Makefile).** A git worktree stores its
  metadata in the parent repo's `.git/worktrees/<name>` dir; mounting only the
  worktree at `/repo` breaks `git ls-files` inside the container (exit 128),
  which fails the hermetic lint regression tests. The Makefile now detects a
  worktree (`gitdir:` in `.git`) and additionally mounts the parent repo at its
  real path so `git` works. A normal checkout (CI) has `.git` as a DIR → the
  extra mount is empty → CI is byte-identical to before.
- **Regression tests** (hermetic, `make test-unit`, no skips) extend
  `tests/test_watchloop_dispatch.py::TestTickDedup` with a
  `test_concurrent_reclaim_single_winner` that simulates the two
  interleavings directly against the lock helpers and asserts exactly ONE
  winner, plus the log-contract assertion.

## User-Visible Impact

No change to user-facing serving/model commands. The autonomous watch-loop
dispatcher becomes reliably idempotent per cron interval even under a double
cron-fire: exactly one `main()` per 20-min slot.

## Non-Goals

- No change to the parallel-worktree model, the serialized-make lock, the
  spawn/merge/cleanup stages, or how issues get their OpenSpec changes.
- No change to the coarse `TICK_INTERVAL_SECONDS` bucketing or to how the
  durable lock is released only on a new interval.
- No change to the crontab cadence (still `*/20`).
