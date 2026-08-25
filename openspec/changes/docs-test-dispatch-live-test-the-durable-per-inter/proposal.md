# docs+test(dispatch): live-test the durable per-interval tick dedup + document the hold-for-interval design

## Why

The watch-loop dispatcher (`scripts/watchloop_dispatch.py`, host crontab every
20 min) dedups the doubled cron tick (#25) with a **durable, per-interval** lock
(#27 / PR #28): the tick lock is deliberately HELD for the whole 20-min interval
bucket and released / reclaimed only when a NEW interval starts — NOT released at
`main()`'s end. A naive `O_CREAT|O_EXCL` lock released in a `finally` only catches
a *tight* overlap; once the first invocation finished and deleted the lock, a
phantom re-fire in the same 20-min bucket re-acquired and re-ran — the doubled
tick.

The problem today (#30):

1. **Not live-tested.** The durable hold-for-interval behavior is only covered by
   hermetic unit tests (`tests/test_watchloop_dispatch.py::TestTickDedup`). There
   is no end-to-end proof through a real new-issue → worker → PR cycle that
   `dispatch.log` records exactly one `tick start`→`tick done` per scheduled
   slot, including a re-fire in the SAME interval AFTER the first tick finished.
2. **Not documented.** The reason the lock is intentionally NOT released at the
   end of `main()` is non-obvious; a future dev could "clean it up" into a
   `finally`-released lock and silently reintroduce the #25 doubled-tick bug.

## What Changes

- **Document the design in AGENTS.md** (new subsection under the "Background
  watch loop" section, "Durable per-interval tick dedup"):
  - WHY the lock is held for the whole interval (not released at `main()`'s end):
    the phantom double-fire is a re-fire in the same coarse bucket, often seconds
    AFTER the first tick already finished — a synchronous end-of-`main()` release
    has already deleted the lock by then, so the re-fire re-acquires and runs.
  - HOW a re-fire in the same bucket is dedup'd: `_tick_lock_acquire()` compares
    the recorded owner bucket to the current `tick-<n>` bucket; a live owner
    holding THIS bucket → `[DEDUP] tick skipped`, no tick start — a durable
    answer unrelated to `main()`'s end.
  - HOW a new interval reclaims: when the wall clock crosses a 20-minute
    `TICK_INTERVAL_SECONDS` boundary, the bucket string changes; `_tick_lock_acquire`
    sees the old-bucket (finished) owner and reclaims it atomically (`[DEDUP]
    reclaiming finished interval`), so `main()` runs exactly once for the new slot.
  - WHY a crash mid-tick is NOT a permanent block: `main()` deliberately does not
    release on exception (`[DEDUP] tick crashed mid-run; lock stays held until
    next interval`); the next interval's bucket differs, so its `_tick_lock_acquire`
    reclaims the stale lock; a dead-PID owner is likewise swept by the reclaim.
- Verify the durable dedup **through a real issue on the live loop**: the very
  work item doing this change (issue #30) runs across ≥2 scheduled cron slots as
  an in-flight worker; `dispatch.log` is inspected and must show **one tick block
  per slot** (no `[DEDUP]`-multiples doubling a tick start, no phantom double
  tick), closing issue #30's goal 1.

## Capabilities

### New Capabilities

_(none — this is a docs + live-verification change. No system capability, runtime
code, Makefile target, or CI behaviour changes. The documentation-only nature is
declared via `skip_specs: true`.)_

### Modified Capabilities

_(none.)_

## User-Visible Impact

No change to serving / model commands. Improves the autonomous watch-loop's
operability: a future maintainer can read WHY the lock is intentionally held for
the interval and must not "simplify" it back to a synchronous release, and the
hold-for-interval behavior gains a record of a real, live-tested run against the
background loop.

## Non-Goals

- No change to `scripts/watchloop_dispatch.py`'s tick-dedup behaviour (it shipped
  in PR #28) — only its durable design is DOCUMENTED and LIVE-VERIFIED here.
- No change to the parallel-worktree model, the serialized-make lock, or worker
  spawn / merge-gate logic.
- `.watchloop/run/dispatch.log` (the verification source) is gitignored and is
  NOT committed.