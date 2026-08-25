# feat-dispatch-auto-clean-stale-worktrees-branches — spec of record

## ADDED Requirements

### Requirement: auto-clean merged worktrees and branches
The dispatcher (`scripts/watchloop_dispatch.py`) MUST, every tick after the
merge gate, remove the git worktree and local branch (and the now-unused
per-worker `.running`/`.prompt`/`.log` artifacts) of every `feat/*` branch whose
HEAD has merged into `origin/main`.

#### Scenario: a merged PR's worktree and branch are cleaned
- **WHEN** a PR merges to `main` and the merged branch's HEAD is an ancestor of
      `origin/main`
- **THEN** the dispatcher removes the branch's worktree under `../llama-ai-wt/`,
      deletes the local `feat/<kebab>` branch, and deletes its worker
      `.running`/`.prompt` and `.log` artifacts

#### Scenario: worktree that is not yet a git worktree to remove
- **WHEN** a `feat/*` worktree's HEAD is NOT an ancestor of `origin/main`
      (branch in flight / PR still open)
- **THEN** the dispatcher leaves the worktree, branch, and worker artifacts
      untouched

### Requirement: never disturb a live worker
The cleanup MUST NOT delete a worktree/branch whose per-worker `.running` lock
records a live (running) PID. Cleanup is strictly post-worker-exit.

#### Scenario: a merged branch with a live worker is kept
- **WHEN** a merged branch's `.running` lock holds a live PID
- **THEN** the dispatcher skips cleaning it (no deletion of worktree, branch, or
      artifacts)

### Requirement: dry-run mode reports without deleting
The dispatcher MUST support a dry-run/list mode that reports what stale
worktrees/branches would be cleaned WITHOUT deleting anything.

#### Scenario: --dry lists but does not delete
- **WHEN** the dispatcher runs with the dry-run flag
- **THEN** it logs each would-be-cleaned worktree/branch and does not remove
      anything

### Requirement: AGENTS.md documents the cleanup step
AGENTS.md MUST document that the background dispatcher auto-cleans merged
worktrees and branches after a PR merges (so the clean-up is enforced, not left
to an ad-hoc command).

#### Scenario: the dispatcher section documents auto-clean
- **WHEN** a developer reads the AGENTS.md dispatcher section
- **THEN** they see that merged PR worktrees and branches are automatically
      removed by the loop and in-flight ones are left untouched
