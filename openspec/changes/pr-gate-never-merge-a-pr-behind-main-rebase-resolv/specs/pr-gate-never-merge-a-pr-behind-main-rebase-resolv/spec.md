# pr-gate-never-merge-a-pr-behind-main-rebase-resolv — spec of record

## ADDED Requirements

### Requirement: never merge a PR that is behind main
The system MUST NOT merge a PR to `main` when the PR head is behind `main` (i.e.
`origin/main` has commits the PR branch does not contain) or its synchronization
state cannot be verified. This rule is enforced in AGENTS.md, in the dispatcher
(`scripts/watchloop_dispatch.py`), and in GitHub branch protection on `main`.

#### Scenario: behind PR is never merged out of sync
- **WHEN** a PR head is behind `main` or its sync state cannot be verified
- **THEN** the PR is NOT merged until its branch is brought up to date with `main`

### Requirement: rebase-and-resolve instead of mere skip
When the dispatcher's merge gate finds a PR that is behind `main` or unverifiable,
it MUST NOT merely skip it. It MUST rebase the PR head onto the latest
`origin/main` (or merge `main` in), resolve any merge conflicts within the branch,
then re-attempt the merge gate once CI has re-run — still subject to approval, no
open review threads, and green CI.

#### Scenario: behind PR is rebased, not skipped
- **WHEN** the dispatcher merge gate inspects a PR whose head is behind `main`
- **THEN** the dispatcher rebases/merges the PR head onto `origin/main`, resolves
      conflicts, and re-attempts the gate instead of simply logging "not merged"
      and continuing

#### Scenario: unverifiable comparison is treated as behind
- **WHEN** the API comparison of PR head vs `main` cannot be determined
- **THEN** the dispatcher treats the PR as behind (never merges) and applies the
      rebase-and-retry path

### Requirement: AGENTS.md MANDATORY merge gate in three locations
AGENTS.md MUST state the never-merge-behind gate as MANDATORY behavior in three
places: the Background watch loop section, the PR review/merge flow, and the
dispatcher merge gate. All three must instruct: verify the PR head is not behind
`main`; if behind, rebase onto latest `origin/main`, resolve conflicts, re-run
CI/validation, re-verify green + approved + no open threads, then merge.

#### Scenario: watch loop documents the gate
- **WHEN** a developer reads the AGENTS.md Background watch loop section
- **THEN** they see the explicit "never merge a PR behind main: rebase+resolve
      first" rule

#### Scenario: PR review/merge flow documents the gate
- **WHEN** a developer reads the AGENTS.md PR review/merge flow
- **THEN** they see that a behind PR must be rebased and conflict-resolved before
      merge, and never merged out of sync

### Requirement: GitHub branch protection enforces up-to-date-before-merge
The repository's branch protection on `main` MUST enable required status checks
with `strict: true` (branches must be up to date before merging) and keep the
required approving review count at 1. GitHub then blocks merges of behind PRs at
the platform layer.

#### Scenario: GitHub blocks behind-PR merge
- **WHEN** a PR behind `main` is submitted for merge
- **THEN** GitHub branch protection rejects it because branches must be up to date
      with `main` (strict status checks)
