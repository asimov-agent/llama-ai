# feat-dispatch-delete-stale-remote-branches-after-a — spec of record

## ADDED Requirements

### Requirement: cleanup sweep deletes merged REMOTE branches
`cleanup_merged_worktrees` in `scripts/watchloop_dispatch.py` MUST, for every
`feat/*` branch whose worktree it cleans (merged into `origin/main`, worker no
longer alive), also delete the REMOTE branch via
`git push origin --delete <branch>` — only when the remote branch still exists
(checked with `git ls-remote --heads origin <branch>`), and NEVER delete
`main`.

#### Scenario: a merged PR's remote branch is deleted
- **WHEN** a merged `feat/*` branch is cleaned (local worktree + branch removed)
  and `origin` still has that branch
- **THEN** the dispatcher runs `git push origin --delete <branch>` for it

#### Scenario: in-flight branch remote is never deleted
- **WHEN** a `feat/*` branch's HEAD is NOT an ancestor of `origin/main`
  (PR still open / in flight)
- **THEN** no `git push origin --delete` is issued for that branch

#### Scenario: an already-deleted remote branch is not re-deleted
- **WHEN** the remote branch no longer exists (e.g. the merge API already
  deleted it via `delete_branch: true`)
- **THEN** the dispatcher skips the delete (no failing `git push`)

#### Scenario: `main` is never deleted
- **WHEN** the cleanup logic is given `main` as a branch to clean
- **THEN** no `git push origin --delete main` is issued

### Requirement: dry-run reports remote deletions without executing
The dispatcher's `--dry` mode MUST log each would-be remote-branch deletion
without running the actual `git push origin --delete`.

#### Scenario: --dry does not delete the remote branch
- **WHEN** the dispatcher runs with the dry-run flag and a merged branch would
  be cleaned
- **THEN** the remote deletion is logged/reported and no
  `git push origin --delete` is executed

### Requirement: merge_pr requests branch deletion at merge time
`merge_pr` MUST include `delete_branch: true` in the `PUT /pulls/<N>/merge`
request body, so the branch is deleted by GitHub at merge time when supported.

#### Scenario: the merge API body requests deletion
- **WHEN** the dispatcher merges a PR via the GitHub API
- **THEN** the `PUT /pulls/<N>/merge` body contains
  `{"merge_method": "merge", "delete_branch": true}`
