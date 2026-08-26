# feat-dispatch-fix-repair-spawn-reusing-an-existing — Tasks

Checklist of record. Ticked the moment verified.

## Implementation

- [x] 1.1 Add `_branch_exists(branch)` helper (local or origin ref check via `git show-ref --verify --quiet`).
- [x] 1.2 `ensure_worktree`: worktree dir missing + branch exists -> `git worktree add <path> <branch>` (no `-b`); both missing -> `add -b` from origin/main (unchanged); dir present -> reuse + rebase-if-behind (unchanged).
- [x] 1.3 Keep the existing `fetch --all --prune` + `fetch origin main` refresh so the branch-existence check sees the newest remote refs.

## Tests (hermetic, tests/test_watchloop_dispatch.py)

- [x] 2.1 worktree already exists -> no `git worktree add` issued, rebase-if-behind still applies.
- [x] 2.2 branch exists on origin, no worktree -> `git worktree add <path> <branch>` WITHOUT `-b`.
- [x] 2.3 branch AND worktree missing -> `git worktree add -b <branch> <path>` (fresh spawn).
- [x] 2.4 repair spawn end-to-end: red-CI PR with an existing remote branch triggers `spawn_repair_worker`; assert the git add uses NO `-b` and the worker command targets the existing/reused worktree.
- [x] 2.5 never-duplicate regression: when the branch exists, no `add -b` is ever attempted (rc-255 regression, issue #42).

## Verification

- [x] 3.1 All new + existing `tests/test_watchloop_dispatch.py` green in the containerized test image (`test-unit`).
- [x] 3.2 `make lint` green (linefeed + trailing newlines).
- [x] 3.3 `make openspec-validate NAME=feat-dispatch-fix-repair-spawn-reusing-an-existing` exit 0.
- [x] 3.4 Commit + push `feat/feat-dispatch-fix-repair-spawn-reusing-an-existing`; open PR against main referencing issue #46.
