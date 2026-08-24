# GitHub issue-goal ↔ OpenSpec sync rule in AGENTS.md

## Why

AGENTS.md is the durable workflow contract for the agent in this repo. It already
mandates that every work request is turned into an OpenSpec change and driven by
it (OpenSpec is "the checklist of record"). But today there is no binding rule
that forces the **GitHub issue** (the issue file that drives a work item) to stay
**in sync** with the OpenSpec change created from it. Over time the goal can drift
between the issue and the proposal/spec, so the single source of truth fragments.

## What Changes

- Add a durable, MANDATORY rule to `AGENTS.md` (new subsection under the existing
  "OpenSpec is the checklist of record" section) that makes the GitHub issue the
  **root of the whole work lifecycle** and binds it to the downstream artifacts:
  - **Issue → feature branch → OpenSpec change → code → PR.** Creating an issue
    means a feature branch is created off `main` for it, that branch carries the
    OpenSpec change (created first) + implementation, and the work ends by opening
    a PR against `main` from that branch that references the issue.
  - **Continuous bidirectional sync-back, even when BOTH an issue and a PR
    already exist.** Any change to the OpenSpec change (`proposal.md`,
    `specs/**/spec.md`, `tasks.md`) MUST be mirrored in the issue body AND the
    code/files so the implementation reflects the OpenSpec change — and the OpenSpec
    change is the referee: on conflict, code and issue conform to it, not the
    reverse.
- The rule covers the four-way contract: GitHub issue goal, feature branch,
  OpenSpec proposal/spec/tasks, and PR — all derived from the same objective and
  never allowed to diverge.

## Capabilities

### New Capabilities

_(none — this is a docs-only change to `AGENTS.md`. No system capability or spec
is introduced.)_

### Modified Capabilities

_(none.)_

skip_specs: true (set in `.openspec.yaml`) — docs/tooling-only change adds no
capability requirement, so validation expects no spec delta.

## Impact

- `AGENTS.md` gains one MANDATORY rule + its `proposal`/`tasks` files in
  `openspec/changes/issue-goal-openspec-sync/`.
- No runtime, built code, Makefile, or CI behaviour changes.
- This change itself is delivered following that workflow: OpenSpec first,
  feature branch, task list, validate, PR.
