# feat-dispatch-delete-stale-remote-branches-after-a

## Why

`cleanup_merged_worktrees` (issue #29) removes the LOCAL worktree and LOCAL
branch of a merged PR, but does NOT delete the REMOTE branch: `merge_pr` calls
the GitHub merge API without `delete_branch: true`, and the cleanup sweep only
runs `git worktree remove` + `git branch -D`. So a remote `feat/*` branch
survives on `origin` after its PR merges via the API (observed:
`feat/feat-dispatch-auto-clean-stale-worktrees-branches-` from PR #36 still on
`origin`). GitHub's `delete_branch_on_merge: true` auto-delete only applies to
UI-button merges, NOT API merges.

## What Changes

`scripts/watchloop_dispatch.py`:

1. **`cleanup_merged_worktrees` also deletes the REMOTE branch** of every merged
   + cleaned branch: after removing the local worktree/branch/artifacts, it runs
   `git push origin --delete <branch>` — but only when the remote branch still
   exists (checked with `git ls-remote --heads origin <branch>`), only for
   `feat/*` branches whose HEAD is already an ancestor of `origin/main`
   (merged), and never for `main`.
2. **`merge_pr` requests deletion at merge time**: the `PUT /pulls/<N>/merge`
   body now includes `delete_branch: true`, so the branch dies at merge time when
   the API supports it; the cleanup sweep is the safety net for anything that
   slips through (e.g. UI merges, older API behaviour).
3. **Dry-run reports remote deletions**: `--dry` logs each would-be remote
   branch deletion without executing it.
4. Module docstring + AGENTS.md + README document the remote-branch deletion.

## Validation

- `make openspec-validate NAME=feat-dispatch-delete-stale-remote-branches-after-a` exits 0.
- `make lint` passes (all tracked text files end with a newline).
- `make test-unit` passes (hermetic; includes the 5 new remote-deletion test
  cases in `tests/test_watchloop_dispatch.py`, run by the `unit` CI job).
- Delivered via feature branch + PR referencing issue #45.
