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
  "OpenSpec is the checklist of record" section): whenever the agent changes the
  **goal** of a work item, it MUST update the **GitHub issue** (issue file) so it
  stays in sync with the OpenSpec change (`proposal.md` + `specs/**/spec.md` +
  `tasks.md`) that was created from it.
- The rule covers the three-way contract: GitHub issue goal, OpenSpec proposal,
  and the task list all derive from the same objective and must not diverge.

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