# stuck-pr-repair-stage — spec of record

## ADDED Requirements

### Requirement: repair actionable stuck open PRs each tick
After the merge gate and the orphan-issue spawner, the dispatcher (`scripts/watchloop_dispatch.py`) MUST, each tick, identify open PRs that are NOT mergeable for an actionable, worker-fixable reason and respawn the PR's dedicated worker to repair them. Actionable reasons are: **unresolved review-thread comments** or **red CI**.

#### Scenario: red-CI PR gets a repair worker
- **WHEN** an open PR has no approval issue but CI is red (a required check failed) and the PR is NOT behind main and its body closes an issue
- **THEN** the dispatcher respawns a worker bound to the PR's existing branch, writes a REPAIR prompt and lock, and logs that it is spawning a repair worker

#### Scenario: PR with unresolved review threads gets a repair worker
- **WHEN** an open PR has one or more unresolved review-thread comments, is NOT behind main, and its body closes an issue
- **THEN** the dispatcher respawns a repair worker bound to the PR's branch

### Requirement: never repair a non-actionable PR
The repair stage MUST NOT touch a PR that is: (a) behind main (the merge gate owns syncing, issue #9), (b) blocked only on "not approved" (a human decision), or (c) lacking a closing-issue keyword (cannot map to a worker).

#### Scenario: behind PR is skipped by repair
- **WHEN** `pr_is_behind(pr)` is true
- **THEN** the repair stage skips it (never spawns a worker)

#### Scenario: clean/not-approved-only PR is skipped
- **WHEN** a PR is green with no open threads (regardless of approval state)
- **THEN** the repair stage does nothing (only the merge gate decides on approval)

#### Scenario: PR with no closing issue is skipped
- **WHEN** a PR's body has no `Closes/Fixes/Resolves #N` keyword
- **THEN** the repair stage skips it (no issue -> no worker identity)

### Requirement: malformed entries never crash the tick
An incomplete or non-dict PR entry (missing head/base, non-dict) MUST be skipped without raising, so a malformed API response never wedges the dispatcher tick.

#### Scenario: dict missing head/base
- **WHEN** the open-PR list contains a dict without a `head.ref` or `base`
- **THEN** the repair stage skips it and the tick continues (no exception)

### Requirement: respect live-worker lock and local-model availability
The repair spawn MUST reuse the atomic `.running` PID lock (never duplicate a live worker) and MUST skip cleanly if the configured local worker model is unreachable (same fail-closed behavior as the pre-spawn probe, issue #37).

#### Scenario: live worker suppresses duplicate repair
- **WHEN** the PR branch's `.running` lock records a live PID
- **THEN** the repair stage does not spawn a duplicate

#### Scenario: local model down -> repair skipped
- **WHEN** the effective provider is local and the local llama-server does not list the worker model
- **THEN** the repair stage logs and skips (no lock, no spawn)

### Requirement: dry-run reports without spawning
The repair stage MUST support the existing `--dry` flag: it logs which PRs would be repaired but spawns nothing.

#### Scenario: --dry lists would-repair PRs
- **WHEN** the dispatcher runs with `--dry` and a stuck PR exists
- **THEN** it logs `would spawn a repair worker for PR#N` and spawns nothing

## Non-goals
- Not a replacement for human approval; never changes review approval.
- Not a replacement for the merge gate's behind-main sync (issue #9).
- Not creating a NEW branch/PR — always repairs the existing PR branch.