# dispatcher-reliability-rebase-locks — spec of record

Capabilities this change adds to the watch-loop dispatcher and AGENTS.md.

## ADDED Requirements

### Requirement: dead-PID stale-lock auto-clean
`spawn_worker` MUST treat a `.running` lock as stale — and remove it — when the
PID recorded inside it is no longer a live process, so an orphaned issue is never
permanently starved by a dead worker's leftover lock. A `.running` whose recorded
PID IS alive MUST still suppress spawning (no duplicate workers).

#### Scenario: dead PID => spawn again
- **WHEN** `spawn_worker(issue)` runs for an issue whose
  `.watchloop/run/worker-<branch>.running` exists and holds a PID that is not a
  live process
- **THEN** the dispatcher removes the stale lock and spawns a fresh worker,
  continuing from the existing worktree + log
- **AND** exactly one worker runs for the issue afterward

#### Scenario: live PID => skip (no duplicate)
- **WHEN** `spawn_worker(issue)` runs for an issue whose
  `.watchloop/run/worker-<branch>.running` exists and holds a PID that IS alive
- **THEN** the dispatcher logs `worker already running ... skip` and does NOT
  spawn another worker (no duplicate work)

#### Scenario: no lock => spawn
- **WHEN** `spawn_worker(issue)` runs for an issue with no `.running` file
- **THEN** the dispatcher spawns one worker and writes a `.running` file holding
  the live worker PID (checked alive)

### Requirement: same-tick resolved-issue skip
The merge gate MUST report the set of issue numbers it closed this tick (via the
merged PRs' `Closes/Fixes/Resolves #N` bodies), and the spawn phase MUST skip any
issue whose PR was merged in the same tick so a just-closed issue is never given
a redundant worker.

#### Scenario: issue closed by same-tick merge
- **WHEN** the merge gate merges a PR whose body closes issue #N in the current
  tick
- **THEN** the spawn phase logs `issue#N: resolved by PR merged this tick; no
  spawn` and spawns no worker for #N

#### Scenario: open issue with no same-tick merge
- **WHEN** no PR merged this tick closes issue #M
- **THEN** the spawn phase proceeds normally for #M (subject to lock + PR rules)

### Requirement: mandatory rebase/resolve-on-resume in AGENTS.md
AGENTS.md MUST mandate that on session start / resume a worker fetches
`origin/main` and, if its branch is behind, rebases onto it — resolving any
merge conflicts itself — before continuing work; and MUST permit
`git push --force-with-lease` on one's own PR branch after such a rebase while
prohibiting force-push of shared history or `main`.

#### Scenario: resume on a stale branch
- **WHEN** a worker resumes in its worktree and `origin/main` is not an ancestor
  of `HEAD`
- **THEN** AGENTS.md directs it to `git fetch origin main` + `git rebase
  origin/main`, resolve conflicts, and continue; never leave the branch behind
  `main`

#### Scenario: updating a published PR branch after rebase
- **WHEN** a worker rebased its own branch that already has an open PR
- **THEN** AGENTS.md permits `git push --force-with-lease` for that branch and
  forbids force-pushing `main` or shared history