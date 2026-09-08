# fix-dispatch-doubled-tick-is-back-the-hold-for-int

## Implementation

- [x] 1.1 Add a short-lived advisory meta-lock helper for the tick decision:
      `TICK_LOCK_META = TICK_LOCK + ".meta"` and a small context manager
      (or open/flock/close pair) that takes `fcntl.flock(LOCK_EX|LOCK_NB)` on
      the meta-lock file, retrying a bounded number of times; on exhaustion it
      signals "could not take the decision" (→ skip/dedup), never run anyway.
- [x] 1.2 Rewrite `_tick_lock_acquire()` so the ENTIRE read owner → decide
      (same-bucket ⇒ dedup / older-or-stale ⇒ reclaim) → write
      `TICK_LOCK(bucket,pid)` step executes UNDER the meta-lock. The meta-lock
      is released immediately after the write (it is NOT the durable lock).
- [x] 1.3 Keep the durable semantics EXACTLY as before: a FINISHED same-bucket
      owner (dead pid) still dedups a re-fire (issue #30); a NEW interval
      reclaims an OLDER-bucket lock exactly once; a crash leaves the lock held
      for the next interval to reclaim.
- [x] 1.4 Ensure there is NO fallback / "busy ⇒ run anyway" branch: exactly one
      acquisition path; a failed atomic decision SKIPS (dedup), never runs.
- [x] 1.5 Make the meta-lock path derive from the CURRENT `TICK_LOCK` value at
      call time (`_tick_meta_path()`) so tests that monkeypatch `TICK_LOCK`
      onto a tmp dir keep the meta-lock hermetic (never touch the real
      `.watchloop/run`), and so a worktree's mount of the parent repo does not
      affect the decision path.

## Tests

- [x] 2.1 `test_concurrent_reclaim_single_winner`: two callers both see an
      OLD-bucket lock; interleave so P1 creates before P2's remove; assert
      EXACTLY one returns `True` and `TICK_LOCK` ends with the winner's
      bucket+pid (no real threads — drive the lock helpers directly).
- [x] 2.2 `test_meta_lock_is_short_lived_not_durable`: after a winner releases
      the meta-lock, a same-interval re-fire STILL dedups on the recorded
      bucket (proves the meta-lock is not the durable lock).
- [x] 2.3 Keep `test_same_bucket_dead_owner_still_dedups` and
      `test_next_interval_reclaims_older_bucket` green (issue #27/#30
      invariants not weakened).
- [x] 2.4 `test_main_logs_dedup_not_tick_start_when_held` stays green
      (deduped process logs `[DEDUP]`, never `tick start`).
- [x] 2.5 `test_busy_meta_lock_skips_never_runs`: when the meta-lock cannot be
      taken, `_tick_lock_acquire()` returns `False` (skip), never `True`.
- [x] 2.6 `test_no_fallback_run_anyway_branch`: exactly ONE acquisition path;
      no "busy ⇒ run anyway" branch exists in the source.

## Infrastructure

- [x] 3.1 Make the containerized test targets work from a GIT WORKTREE: a
      worktree's `.git` is a FILE pointing at the parent repo's
      `.git/worktrees/<name>` dir, so mounting only the worktree at `/repo`
      breaks `git ls-files` inside the container (exit 128), which fails the
      hermetic lint regression tests. Detect a worktree (`gitdir:` in `.git`)
      and additionally mount the parent repo at its real path so `git` works
      inside the container. A normal checkout (CI) has `.git` as a DIR → the
      extra mount is empty → CI is byte-identical to before.

## Verification

- [x] 4.1 `make test-unit` green (all hermetic, no skips) — including the new
      `TestTickDedup` cases; the pre-fix remove/create TOCTOU test is RED
      before the fix and GREEN after.
- [x] 4.2 `make openspec-validate
      NAME=fix-dispatch-doubled-tick-is-back-the-hold-for-int` exit 0 and
      `make openspec-tasks-check` clean (all tasks ticked).
- [x] 4.3 `make lint` green (every touched file ends with a trailing newline).
