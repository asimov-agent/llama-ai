# feat-dispatch-fix-repair-spawn-reusing-an-existing — spec of record

## ADDED Requirements

### Requirement: reuse an existing worktree for a known branch
`ensure_worktree(branch, slug)` MUST reuse the worktree directory when it
already exists, rebasing the branch onto the latest origin/main only when it
is behind (existing behaviour).

#### Scenario: worktree already exists
- **WHEN** the worktree directory for `slug` exists on disk
- **THEN** `ensure_worktree` issues NO `git worktree add` at all and rebases
  the existing branch if (and only if) it is behind origin/main

### Requirement: attach to an existing branch without creating a duplicate
When the worktree directory is missing but the branch already exists (locally
or on `origin`), `ensure_worktree` MUST attach to it with
`git worktree add <path> <branch>` — WITHOUT the `-b` flag — so git never
reports "a branch named ... already exists" (rc 255).

#### Scenario: branch exists on origin, no worktree
- **WHEN** the worktree directory is missing and `refs/heads/<branch>` or
  `refs/remotes/origin/<branch>` exists
- **THEN** `ensure_worktree` runs `git worktree add <path> <branch>` (no `-b`)

#### Scenario: never duplicate an existing branch
- **WHEN** the branch already exists in any form
- **THEN** no `git worktree add` command containing `-b <branch>` is ever
  issued (the rc-255 regression from the stuck-PR repair stage, issue #42)

### Requirement: fresh spawn still creates a new branch
When neither the worktree directory nor the branch exists (orphan-issue
spawn), `ensure_worktree` MUST keep creating the worktree with
`git worktree add -b <branch> <path> origin/main`.

#### Scenario: branch and worktree missing
- **WHEN** the worktree directory is missing and the branch exists neither
  locally nor on origin
- **THEN** `ensure_worktree` runs `git worktree add -b <branch> <path>
  origin/main` (fresh spawn, unchanged behaviour)

### Requirement: repair spawn end-to-end reuses the PR branch/worktree
A repair spawn (`spawn_repair_worker` -> `_spawn_worker_for_branch` ->
`ensure_worktree`) for a PR whose branch exists on the remote MUST actually
launch the worker in the existing/attached worktree.

#### Scenario: repair spawn attaches without -b
- **WHEN** `process_stuck_prs` triggers a repair for a PR whose head ref
  branch exists on origin and whose worktree was deleted
- **THEN** the worker is spawned, the launch command is written against the
  worktree path, and the underlying `git worktree add` contains NO `-b`
  because the branch exists
