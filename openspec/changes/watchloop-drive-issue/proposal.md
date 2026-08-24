# Verify the background watch loop drives a new issue end-to-end

## Why

AGENTS.md mandates a background watch loop (host crontab, every 20 min) that
launches a one-shot `project-manager` Hermes session which polls the project's
GitHub state and drives open issues to PRs. For this self-driving contract to be
trustworthy it must be exercised, not just documented. This change is that
exercise: it proves the loop picks up a brand-new issue, creates an isolated git
worktree feature branch off `main`, follows the OpenSpec-first lifecycle, and
opens a PR against `main` that references the issue.

## What Changes

- A small, safe, merged-able docs note in `README.md`: a new "Self-driving
  development (background watch loop)" subsection that tells a human reader the
  repo is self-driving — a host crontab watch loop polls PRs/CI, merges approved
  green PRs, and drives every open issue to a PR via an isolated worktree + PR —
  and points at `AGENTS.md` for the durable rules. This is the low-risk,
  user-facing artifact that both references this verification issue and stays in
  sync with `AGENTS.md` (per the repo's sync rule).
- The OpenSpec change `watchloop-drive-issue` itself (this change) as the
  checklist of record for the verification.

## Acceptance

- The repository gains a new branch + PR, created off `main` by the watch loop
  as an isolated worktree, whose PR body references the driving GitHub issue.
- The OpenSpec change and the README note are mutually consistent and in sync
  with the driving issue (per the AGENTS.md sync rule).
- `make openspec-validate NAME=watchloop-drive-issue` exits 0 and every task in
  `tasks.md` is ticked.

## Non-goals

- No runtime, launcher, downloader, or CI pipeline change — this is intentionally
  a docs-only change so that merging it is low-risk (the issue demands a small,
  safe PR).