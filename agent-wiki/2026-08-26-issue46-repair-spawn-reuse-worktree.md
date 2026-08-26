# 2026-08-26 — issue #46: repair spawn reuses existing branch/worktree

## What was done
- OpenSpec change `feat-dispatch-fix-repair-spawn-reusing-an-existing` created
  FIRST via the containerized CLI (`make openspec-new`), validated
  (`openspec validate` exit 0), all tasks ticked.
- `scripts/watchloop_dispatch.py`:
  - New `_branch_exists(branch)`: `git show-ref --verify --quiet` against
    `refs/heads/<branch>` and `refs/remotes/origin/<branch>` (hermetic, no
    fuzzy match).
  - `ensure_worktree` three-way branch:
    1. worktree dir exists -> reuse + rebase-if-behind (unchanged);
    2. branch exists, no worktree -> `git worktree add <path> <branch>`
       WITHOUT `-b` (the fix — no more rc-255 "branch already exists");
    3. neither exists -> `git worktree add -b <branch> <path> origin/main`
       (fresh orphan-issue spawn, unchanged).
- `tests/test_watchloop_dispatch.py`: 6 new hermetic tests covering all 5
  issue #46 cases (existing worktree no-add; origin-branch attach without -b;
  local-branch attach without -b; fresh `add -b` when neither exists;
  never-`add -b` regression; repair-spawn end-to-end with REPAIR prompt +
  attached worktree path asserted).

## Verified
- Containerized `test-unit`: 66/66 `test_watchloop_dispatch.py` green (6 new).
  The 8 `test_lint_linefeeds.py` failures are the known environmental
  `git ls-files` exit-128 inside the nerdctl worktree bind-mount (same 8
  recorded by sibling workers, not a regression).
- Host lint: `scripts/lint_linefeeds.py` LINT OK; container lint also LINT OK.
- `openspec-validate` exit 0.

## Status
- Branch `feat/feat-dispatch-fix-repair-spawn-reusing-an-existing` pushed;
  PR #47 open against main, references Closes #46; not behind main (issue #9).
