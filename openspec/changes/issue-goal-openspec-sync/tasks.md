# issue-goal-openspec-sync — Tasks

Checklist of record. Tasks ticked the moment verified. Delivered per AGENTS.md:
OpenSpec change first, then feature branch, then implementation, then validate.

## AGENTS.md rule

- [x] 1.1 Add a MANDATORY subsection under "OpenSpec is the checklist of record"
      that makes the GitHub issue the root of the whole work lifecycle:
      issue → feature branch → OpenSpec change → code → PR.
- [x] 1.2 When the agent changes the goal of a work item, the change MUST be
      mirrored in the GitHub issue (the issue file), the OpenSpec change
      (`proposal.md`/`specs/**/spec.md`/`tasks.md`), and the code/files — all in
      the same commit batch.
- [x] 1.3 Bidirectional sync-back is continuous even when BOTH an issue and a PR
      already exist: any change to the OpenSpec change MUST update the issue body
      AND the code/files so the implementation reflects the OpenSpec change; the
      OpenSpec change is the referee on conflict.
- [x] 1.4 The PR body MUST reference the issue it closes; issue, branch, OpenSpec
      change, and PR must never diverge.
- [x] 1.5 Background watch loop: poll PRs + CI as the FIRST action each tick; merge
      approved green PRs (green CI + approval + no open threads); reconcile issue↔
      OpenSpec drift.
- [x] 1.6 Every open issue must have a branch + PR in flight; a new issue with no
      live branch/PR is started immediately as an isolated git worktree
      (`git worktree add -b feat/<kebab> ../llama-ai-wt/<kebab> main`) following
      the OpenSpec-first lifecycle inside the worktree, ending at a PR.
- [x] 1.7 The cron job is implemented under the `project-manager` profile with
      `workdir` = this repo (loads AGENTS.md); job prompt stays in sync with the
      AGENTS.md Background watch loop section.
- [x] 1.8 Rule is durable (not a one-off): part of the agent's standing workflow
      contract in AGENTS.md, applicable to every future work item.

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
