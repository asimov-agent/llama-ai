# stuck-pr-repair-stage — proposal

## Why

The watch-loop's merge gate (`process_merge_gate`) merges ready PRs and skips
non-ready ones, and the spawner (`spawn_worker`) only spawns a worker for an
issue with NO open PR. So once a worker opens a PR, the loop's LLM stops driving
that issue. If the PR turns CI-red, gets reviewer fix comments (open threads),
or falls behind and conflicts, **no agent is ever spawned to resolve it** — it
sits until a human acts. There is no "PR doctor" stage (issue #42).

This is the gap: the local LLM authors work, but the loop cannot autonomously
**repair** an existing PR so it reaches the merge gate and is merged.

## What Changes

- Add a third stage to the dispatcher's per-tick flow: **stuck-PR repair**.
- For each open PR that is NOT mergeable due to an actionable, worker-fixable
  reason (`unresolved review threads` or `CI is red`), respawn the PR's dedicated
  worker (configured model) bound to the PR's **EXISTING branch/worktree** with a
  REPAIR prompt: read review comments, fix root cause, add regression tests,
  commit + push (force-with-lease), reply to threads, until CI is green and
  threads resolve.
- Reuses the atomic `.running` lock and the pre-spawn local-model probe, so it
  never duplicates a live worker and fails closed if the local llama.cpp server
  is down.

## Non-actionable / never touched by repair

- **Behind main**: the merge gate (issue #9) owns syncing via `sync_pr_with_main`.
- **Not approved**: approval is a human decision, never auto-driven.
- **No closing-issue keyword in the PR body**: cannot map back to a worker.

## Notes

Runs every tick, after the merge gate and orphan-issue spawner. A stuck PR gets
a repair attempt each tick until it reaches the merge gate. The repair worker is
bounded: it should say "cannot fix" and stop rather than loop forever on the
local model.

## Files touched

- `scripts/watchloop_dispatch.py`: `process_stuck_prs`, `spawn_repair_worker`,
  `pr_repairable`, `pr_issue_number`, `slug_from_branch`, `repair_prompt`,
  `_spawn_worker_for_branch` (refactor of `spawn_worker`), and a call in
  `main()`.
- `tests/test_watchloop_dispatch.py`: new edge-case tests.