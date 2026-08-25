# feat-dispatch-auto-clean-stale-worktrees-branches

## Why

Every merged PR leaves a stale git worktree under `../llama-ai-wt/<kebab>` and a
stale local `feat/<kebab>` branch behind. After PRs #20/#24/#26/#28 merged, the
repo accumulated **14 worktrees**, most on already-merged branches
(`feat/dispatch-tick-dedup`, `feat/fix-dispatch-atomic-lock`,
`feat/watchloop-always-sync-main`, `feat/dispatcher-reliability-rebase-locks`,
etc.) plus their local branches. AGENTS.md says to remove them but nothing
enforces it.

**Impact:**

- Workspace clutter (`git worktree list` is noisy; dead dirs consume disk).
- A stale worktree whose branch was merged risks a future worker resuming it and
  wasting a tick (the dispatcher's `ensure_worktree` sees the dir and skips
  re-creation, but the branch may be gone/merged).
- Accumulating stale branches make `git branch` unreadable.

## What Changes

Add a **stale-worktree cleanup sweep** to the dispatcher (
`scripts/watchloop_dispatch.py`) that runs every tick after the merge gate.

1. **Sweep (auto-clean)** — enumerate every git worktree under
   `../llama-ai-wt/` that is checked out to a local `feat/*` branch whose HEAD
   is an **ancestor of `origin/main`** (i.e. its PR was merged with the
   dispatcher's merge strategy). For each such merged worktree:
   - `git worktree remove --force ../llama-ai-wt/<kebab>` (safe post-worker-exit:
     the worker that drove it already finished, so the merged branch's commits
     live in `main` and there is no in-flight state to lose),
   - `git branch -D feat/<kebab>` (the commits are already in `main`, so force is
     safe),
   - delete the now-unused per-worker artifacts:
     `.watchloop/run/worker-feat_<kebab>.running/.prompt` and
     `.watchloop/logs/feat-<kebab>.log`.
2. **In-flight worktrees are NEVER touched** — an open PR's branch is NOT an
   ancestor of `origin/main`, so it stays.
3. **Live workers are never disturbed** — a merged branch whose
   `.running` PID is still alive is skipped (post-worker-exit cleanup only).
4. `--dry` mode reports what would be cleaned without deleting anything
   (acceptance criterion #3).
5. AGENTS.md documents the automated cleanup step in the dispatcher section.

## Validation

- `make openspec-validate NAME=feat-dispatch-auto-clean-stale-worktrees-branches` exits 0.
- `make lint` passes (all tracked text files end with a newline).
- `make test-unit` passes (hermetic; includes new cleanup-logic tests).
- Dispatcher manual/gate check: after a merge tick, the merged PR's worktree +
  branch + worker artifacts are removed and in-flight ones remain.
- "dry" mode lists what would be cleaned but deletes nothing.
- Delivered via feature branch + PR referencing issue #29.
