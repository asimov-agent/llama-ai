# feat-dispatch-fix-repair-spawn-reusing-an-existing — proposal

## Why

The stuck-PR repair stage (issue #42) respawns a worker for an open PR whose
branch/worktree ALREADY EXIST. But `ensure_worktree` unconditionally runs
`git worktree add -b <branch> <path>` whenever the worktree dir is missing —
which fails with `rc 255: fatal: a branch named 'feat/...' already exists`
because the repair branch exists on origin. The repair worker never starts
even though the repair stage correctly detected the PR.

Observed in the production dispatch log:

```
worktree ... add rc=255: fatal: a branch named 'feat/stuck-pr-repair-stage' already exists
repair-PR#43: spawning worker ... (then cd fails, no worktree)
```

## What Changes

- `ensure_worktree` (scripts/watchloop_dispatch.py) reuses an existing
  branch/worktree instead of always `add -b`-ing a new one:
  - **worktree dir exists** -> reuse it (existing `rebase_if_behind` path).
  - **branch exists (on origin or locally), no worktree** -> `git worktree
    add <path> <branch>` (attach WITHOUT `-b`, so no duplicate branch).
  - **neither branch nor worktree** -> `git worktree add -b <branch> <path>
    origin/main` (fresh orphan-issue spawn, unchanged behaviour).
- Branch-existence check is hermetically testable via a `_branch_exists`
  helper (`git show-ref --verify --quiet refs/heads/<branch>` or
  `refs/remotes/origin/<branch>`).
- Hermetic unit tests in `tests/test_watchloop_dispatch.py` covering all
  three reuse paths, the repair-spawn end-to-end (attach without `-b`), and
  the rc-255 regression (no `add -b` when the branch exists).

## Non-Goals

- No change to the merge gate, tick dedup, or cleanup sweep.
- No change to how orphan issues are spawned (they still `add -b`).
