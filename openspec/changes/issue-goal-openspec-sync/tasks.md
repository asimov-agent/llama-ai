# issue-goal-openspec-sync — Tasks

Checklist of record. Tasks ticked the moment verified. Delivered per AGENTS.md:
OpenSpec change first, then feature branch, then implementation, then validate.

## AGENTS.md rule

- [x] 1.1 Add a MANDATORY subsection under "OpenSpec is the checklist of record"
      that binds the GitHub issue goal to the OpenSpec change: any change to a
      work item's goal MUST be mirrored in the GitHub issue (the issue file),
      and the issue MUST stay in sync with the OpenSpec `proposal.md` +
      `specs/**/spec.md` + `tasks.md` created from it.
- [x] 1.2 Rule is durable (not a one-off): it is part of the agent's standing
      workflow contract in AGENTS.md, applicable to every future work item.

## Change lifecycle (this change)

- [x] 2.1 GitHub issue created for the work (issue-goal ↔ OpenSpec sync).
- [x] 2.2 OpenSpec change scaffolded via `make openspec-new NAME=issue-goal-openspec-sync`
      (through the containerized CLI, not hand-written).
- [x] 2.3 `proposal.md`, `tasks.md` written; `.openspec.yaml` sets
      `skip_specs: true` (docs-only change — no spec delta required).
- [x] 2.4 Delivered on dedicated feature branch `feat/issue-goal-openspec-sync`.

## Verification (final)

- [x] 3.1 `make openspec-validate NAME=issue-goal-openspec-sync` exits 0.
- [x] 3.2 `make lint` passes (trailing newline on every tracked text file,
      including the new OpenSpec files).
- [x] 3.3 All tasks above ticked (`- [x]`); change includes BOTH the AGENTS.md
      edit AND the OpenSpec files (never split).