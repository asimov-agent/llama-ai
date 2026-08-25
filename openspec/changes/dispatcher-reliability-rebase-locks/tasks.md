# dispatcher-reliability-rebase-locks

## Dispatcher reliability

- [x] 1.1 Add a helper `pid_alive(pid) -> bool` that returns True only for a
      live process (no exception path).
- [x] 1.2 In `spawn_worker`, read the existing `.running` lock's PID; if present
      and `pid_alive(pid)`, log `worker already running ... skip` and return;
      otherwise (dead PID or no lock) remove any stale lock and spawn a fresh
      worker. Always write the live worker PID into the lock.
- [x] 1.3 Make `process_merge_gate` return the set of issue numbers closed this
      tick (union of `Closes/Fixes/Resolves #N` over the PRs it merged).
- [x] 1.4 In `main`, skip the spawn phase for any issue number in that returned
      set, logging `issue#N: resolved by PR merged this tick; no spawn`.
- [x] 1.5 Reuse a single shared helper `closing_issues(body)` that returns the
      set of issue numbers a PR body explicitly claims to close, used by both
      `issue_has_pr` and `process_merge_gate` (no divergent inline regexes).

## AGENTS.md mandate

- [x] 1.6 Add the mandatory "always rebase onto origin/main on resume" rule to
      AGENTS.md: fetch origin/main; if behind, `git rebase origin/main`,
      resolving conflicts yourself; never sit behind main; sanitize
      `git push --force-with-lease` for your own PR branch, never shared history
      or `main`. Also mirrored in the `worker_prompt` resume block so workers
      actually perform the fetch+rebase.

## Tests

- [x] 2.1 `test_spawn_worker_dead_pid_spawns`: a `.running` file with a dead PID
      is cleaned and a worker is spawned (exactly one).
- [x] 2.2 `test_spawn_worker_live_pid_skips`: a `.running` file with a live PID
      suppresses the spawn (no duplicate).
- [x] 2.3 `test_spawn_worker_no_lock_spawns`: no lock -> spawn + write PID.
- [x] 2.4 `test_merge_gate_returns_closed_issues`: `process_merge_gate` returns
      the closed issue set from merged PR bodies.
- [x] 2.5 `test_main_skips_same_tick_resolved`: an issue closed by a same-tick
      merge is not spawned (`resolved by PR merged this tick`).

## Verification

- [x] 3.1 `make test-unit` green (38 passed, incl. 13 new dispatcher tests).
- [x] 3.2 `make openspec-validate NAME=dispatcher-reliability-rebase-locks` exit 0.
- [ ] 3.3 Tick-off verification that the stale issue-#16 lock (PID dead) no
      longer causes `worker already running ... skip` and a worker is resumed.