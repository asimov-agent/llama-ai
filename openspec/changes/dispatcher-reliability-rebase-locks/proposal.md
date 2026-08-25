# dispatcher-reliability-rebase-locks

## Why

The watch-loop dispatcher (`scripts/watchloop_dispatch.py`, host crontab every
20 min) has three reliability gaps that let issues stall or re-spawn clumsily:

1. **Stale `.running` lock starves orphaned issues.** `spawn_worker` skips an
   issue if its `.watchloop/run/worker-<branch>.running` file exists, but that
   file is never removed when the worker exits. A dead worker leaves its lock
   behind, so the dispatcher logs `worker already running ... skip` forever and
   the issue is never worked again — even though it still needs work. (Real
   incident: issue #16, ~90% done, starved for hours by a lock whose PID is
   long dead.)
2. **Same-tick redundant spawn.** When the dispatcher's merge gate merges a PR
   that CLOSES an issue in the same tick, the spawn phase then still spawns a
   fresh worker for that just-closed issue. (Real: at 05:00 it merged PR #17,
   closing issue #15, then spawned a new #15 worker at 05:00:08.)
3. **Workers don't rebase onto origin/main on resume.** AGENTS.md requires that
   a PR not sit behind `main` (issue #9 rejects behind-main PRs), but a
   long-lived worker resumes from a stale worktree tip and falls behind as other
   PRs merge. There is no enforced fetch+rebase on resume.

## What Changes

- **Dead-PID lock auto-clean.** `spawn_worker` first reads the recorded PID from
  the `.running` lock. Only if that PID is actually alive (process still
  running) does it skip. If the PID is dead, it removes the stale lock and
  spawns a fresh worker that continues from the existing worktree/log. The
  `.running` file is held for the entire worker lifetime, so a live PID still
  suppresses duplicates.
- **Same-tick resolved skip.** `process_merge_gate` returns the set of issue
  numbers it closed this tick (via the merged PRs' `Closes/Fixes/Resolves #N`
  bodies). `main()` skips the spawn phase for any issue in that set.
- **Mandatory rebase/resolve-on-resume.** AGENTS.md gains a hard rule: on session
  start / resume, a worker MUST `git fetch origin main` and, if its branch tip is
  behind, `git rebase origin/main` — resolving any conflicts itself — before
  continuing work. `git push --force-with-lease` is the sanctioned way to update
  an already-published PR branch after such a rebase; never force-push shared
  history or `main`.
- **Thorough dispatcher unit tests** covering all three behaviors.

## User-Visible Impact

No change to user-facing serving/model commands. Improves the autonomous
watch-loop's reliability: orphaned issues stop stalling, and closing an issue in
a tick no longer wastes a worker on it. Workers keep PR branches current with
`main` so the merge gate accepts them.

## Non-Goals

- No change to the parallel-worktree model, the serialized-make lock, or how
  issues get their OpenSpec changes.
- No change to serving/model launcher behavior.
