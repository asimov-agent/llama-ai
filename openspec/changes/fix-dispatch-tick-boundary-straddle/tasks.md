# fix-dispatch-tick-boundary-straddle

## Implementation

- [x] 1.1 Fix `_current_tick()` so the bucket boundary is shifted by
      `TICK_INTERVAL_SECONDS // 2` (600s): `f"tick-{(int(time.time()) +
      TICK_INTERVAL_SECONDS // 2) // TICK_INTERVAL_SECONDS}"`. This moves the
      bucket boundary from the cron fire instants (`:00`/`:20`/`:40`) to
      `:10`/`:30`/`:50`, so a same-slot doubled fire always lands in ONE bucket.
- [x] 1.2 Preserve the durable hold-for-interval semantics EXACTLY: a FINISHED
      same-bucket owner (dead pid) still dedups a re-fire (issue #30); a NEW
      interval reclaims an OLDER-bucket lock exactly once; a crash leaves the
      lock held for the next interval to reclaim.
- [x] 1.3 Leave the atomic meta-lock (issue #62) and the ONE acquisition path
      untouched — there is NO "busy ⇒ run anyway" fallback and no second lock
      scheme.

## Tests

- [x] 2.1 Add `test_doubled_fire_straddling_old_boundary_same_bucket`: two
      "processes" firing milliseconds apart on OPPOSITE sides of the old
      `int(T) % 1200 == 0` boundary instant now map to the SAME bucket (the
      case that currently runs `main()` twice). RED before the fix, GREEN after.
- [x] 2.2 Add `test_doubled_fire_straddle_dedups_not_reclaims`: with A holding
      the lock for that straddle bucket, B's `_tick_lock_acquire()` returns
      `False` (dedup) and does NOT reclaim A's lock.
- [x] 2.3 Keep `test_next_interval_reclaims_older_bucket` green (a genuinely
      new slot still reclaims the previous slot).
- [x] 2.4 Keep `test_same_bucket_dead_owner_still_dedups`,
      `test_main_logs_dedup_not_tick_start_when_held`, and the
      `test_concurrent_reclaim_single_winner` meta-lock cases green.

## Verification

- [x] 3.1 `make test-unit` green (all hermetic, no skips) — including the new
      boundary-straddle `TestTickDedup` cases.
- [x] 3.2 `make openspec-validate NAME=fix-dispatch-tick-boundary-straddle`
      exit 0 and `make openspec-tasks-check` clean (all tasks ticked).
- [x] 3.3 `make lint` green (every touched file ends with a trailing newline).
- [x] 3.4 Push to `origin feat/fix-dispatch-tick-boundary-straddle`, open a PR
      against `main` referencing issue #73, and confirm CI (incl. the
      `dispatch-e2e` job) is green on the PR.
