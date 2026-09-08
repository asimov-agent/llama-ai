# 2026-09-08 — issue #62: doubled-tick TOCTOU in the hold-for-interval tick lock

## What changed
The watch-loop dispatcher's `_tick_lock_acquire()` (scripts/watchloop_dispatch.py)
made the **read → decide → write** of `TICK_LOCK` atomic. Previously the reclaim
path did `os.remove(TICK_LOCK)` then `os.open(TICK_LOCK, O_CREAT|O_EXCL)`, which
is a TOCTOU: a double cron-fire (P2) could remove the lock P1 *just* created
(same path), so **both** ran `main()` → two `tick start` per interval (reproduced
live 2026-09-07 18:20→20:20).

## Design (one code path, no fallback)
- The entire read/decide/write now runs under a **short-lived** advisory
  `fcntl.flock(LOCK_EX|LOCK_NB)` **meta-lock** on `dispatch.tick.lock.meta`
  (`_tick_meta_lock()`, bounded `META_LOCK_ATTEMPTS=8` retries).
- The meta-lock is released **immediately after the write** — it is NOT the
  durable lock. The durable dedup stays the bucket recorded INSIDE `TICK_LOCK`
  (issues #27/#30): a finished same-bucket owner still dedups, a new interval
  reclaims an older bucket once, a crash leaves the lock held for the next
  interval.
- If the meta-lock can't be taken, the tick is **SKIPPED** (dedup) — never a
  second run. There is no "busy ⇒ run anyway" branch.
- `_tick_meta_path()` derives the meta-lock file from the current `TICK_LOCK`
  value at call time, so tests monkeypatching `TICK_LOCK` stay hermetic.

## Secondary root cause fixed (infra)
`make test-unit` failed in a **git worktree** (the mandated parallel-worker
model): a worktree's `.git` is a FILE pointing at the parent repo's
`.git/worktrees/<name>` dir, which the container never mounted, so `git
ls-files` exited 128 → the 8 `test_lint_linefeeds.py` regression tests failed.
CI (a normal `actions/checkout`) was unaffected. Makefile now detects a
worktree (`gitdir:` in `.git`) and additionally mounts the parent repo at its
real path; a normal checkout yields an empty mount → CI is byte-identical.

## Spec vs. code (verified in lock-step)
OpenSpec change `fix-dispatch-doubled-tick-is-back-the-hold-for-int`:
- Requirement "atomic read-decide-write of the per-tick lock" → `_tick_lock_acquire`
  + `_tick_meta_lock` + `_tick_meta_path`.
- Requirement "durable same-bucket / older-bucket invariants preserved" → unchanged
  bucket semantics (existing `test_same_bucket_dead_owner_still_dedups`,
  `test_next_interval_reclaims_older_bucket` stay green).
- Requirement "deduped tick logs dedup, never tick start" → `test_main_logs_dedup_not_tick_start_when_held`.
- Requirement "no fallback acquisition path" → `test_busy_meta_lock_skips_never_runs`
  + `test_no_fallback_run_anyway_branch`.
- Requirement "containerized tests work from a git worktree" → Makefile `TEST_OPTS`.
- New concurrency scenario "concurrent reclaim yields exactly one winner" →
  `test_concurrent_reclaim_single_winner` (8 threads, one winner).

## Verification (real `make` output, via the serialized-make lock)
- `make test-unit`: **170 passed** (no skips) — incl. all new `TestTickDedup` cases.
- `make openspec-validate NAME=fix-dispatch-doubled-tick-is-back-the-hold-for-int`: **valid**.
- `make openspec-tasks-check`: **all tasks checked** (exit 0).
- `make lint`: **LINT OK**.

## Status
Committed `c76ce52`, pushed to `feat/fix-dispatch-doubled-tick-is-back-the-hold-for-int`,
opened **PR #71** against `main` (body references/closes #62; head not behind main).
Awaiting CI + review.
