# AGENTS.md documentation

- [x] 1.1 Add a "Durable per-interval tick dedup" subsection under the
      "Background watch loop" section of AGENTS.md that documents WHY the tick
      lock is held for the whole 20-min interval (not released at `main()`'s
      end): the phantom double-fire is a re-fire in the SAME bucket, often
      after the first tick already finished, so a synchronous-end-of-`main()`
      release would let it re-acquire and run (the #25 bug).
- [x] 1.2 Document HOW a re-fire in the same bucket is dedup'd: `_tick_lock_acquire`
      compares owner bucket to the current `tick-<n>` bucket; a SAME-bucket lock
      is dedup'd regardless of owner aliveness → `[DEDUP] tick skipped`, no tick
      start (the first process may have already exited; only an OLDER bucket is
      reclaimed).
- [x] 1.3 Document HOW a new interval reclaims: when a 20-minute bucket boundary
      is crossed, the bucket string changes, and the old-bucket (finished)
      owner is reclaimed atomically (`[DEDUP] reclaiming finished interval`) →
      `main()` runs exactly once for the new slot.
- [x] 1.4 Document WHY a crash mid-tick is NOT a permanent block: `main()` does
      not release on exception (`[DEDUP] tick crashed mid-run; lock stays held
      until next interval`); the next interval's different bucket (or a dead-PID
      owner) is swept by `_tick_lock_acquire`'s reclaim.
- [x] 1.5 Document the code/tests seam (`_current_tick`, `_tick_lock_acquire`,
      `TICK_INTERVAL_SECONDS`, `_read_lock_owner`, and
      `tests/test_watchloop_dispatch.py::TestTickDedup`) so a future dev knows
      what to re-cover if the lock is ever touched.

## Change lifecycle (this change)

- [x] 2.1 OpenSpec change scaffolded via
      `make openspec-new NAME=docs-test-dispatch-live-test-the-durable-per-inter`
      (through the containerized CLI, not hand-written).
- [x] 2.2 `proposal.md`, `tasks.md` written; `.openspec.yaml` sets
      `skip_specs: true` (docs-only change — no spec delta required).
- [x] 2.3 Delivered on dedicated feature branch
      `feat/docs-test-dispatch-live-test-the-durable-per-inter`.

## Durable-dedup bug found by the live test (and fixed)

- [x] 4.1 Live `dispatch.log` observation showed a same-bucket re-fire re-running
      the tick after the first cron process exited (dead owner). Root cause:
      `_tick_lock_acquire` required `pid_alive(owner_pid)` for a same-bucket dedup,
      so a finished same-bucket owner was treated as stale and reclaimed.
- [x] 4.2 Fix `_tick_lock_acquire`: a SAME-bucket lock dedups REGARDLESS of owner
      aliveness (the interval owns the lock until its bucket changes); only an
      OLDER bucket is reclaimed.
- [x] 4.3 Add hermetic regression tests:
      `test_same_bucket_dead_owner_still_dedups` (dead same-bucket owner must
      dedup, not re-run) and `test_older_bucket_dead_owner_is_reclaimed` (older
      bucket with dead owner is reclaimed for the new interval).

## Verification (final)

- [x] 3.1 `make openspec-validate NAME=docs-test-dispatch-live-test-the-durable-per-inter`
      exits 0 ("Change ... is valid").
- [x] 3.2 `make lint` passes on a full checkout (worktree container mount has no
      real `.git` so `git ls-files` sees 0 files; CI / full-clone path is the
      authoritative lint run). "LINT OK — all tracked text files end with a newline."
- [x] 3.3 `make test-unit` green including the `TestTickDedup` hermetic suite
      (same-interval dedup, next-interval reclaim, stale dead-PID reclaim,
      main logs `[DEDUP]` not `tick start`) plus the new dead-owner regressions.
      Passed on the committed branch.
- [x] 3.4 LIVE dedup verification: observed `dispatch.log` over ≥2 real cron slots.
      The live test EXPOSED the above bug (doubled ticks when the first process
      exits before a same-bucket re-fire); root cause fixed and covered by hermetic
      regressions above. Note: existing `[DEDUP]`-logged slots and the controlled
      real-module demo (call-1 run, call-2 `[DEDUP] tick skipped`, call-3 new
      interval reclaim) confirm correct behavior; production slots before the fix
      merged are reported honestly as NOT holding until the fix lands in the loop.
