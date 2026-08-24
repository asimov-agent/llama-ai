# Verify the background watch loop drives a new issue end-to-end

## Why

`AGENTS.md` mandates a background watch loop (host crontab, every 20 min) that
launches a one-shot `project-manager` Hermes session which polls the project's
GitHub state and drives every open issue to a PR via an isolated git worktree +
OpenSpec-first lifecycle. That loop was documented and its infra landed in
`feat/watchloop-drive-issue`. For that self-driving contract to be trustworthy it
must be exercised end-to-end — not just documented. This change is that
exercise: it proves the loop picks up a brand-new open issue, creates an isolated
worktree feature branch off `main`, follows the OpenSpec-first lifecycle, and
opens a PR against `main` that references the issue.

## What Changes

- A small, safe, low-risk docs note in `README.md`, added to the existing
  "Self-driving development (background watch loop)" subsection: a verification
  paragraph recording that this repository's self-driving contract is exercised
  end-to-end by verification issue
  [#7](https://github.com/asimov-agent/llama-ai/issues/7) — the loop drove a
  brand-new issue through the worktree → OpenSpec → code → PR lifecycle. This is
  the low-risk, user-facing artifact that both references this verification issue
  and stays in sync with `AGENTS.md` (per the repo's sync rule).
- The OpenSpec change `test-watchloop-verify-the-background-watch-loop-dr`
  itself (this change) as the checklist of record for the verification.

## Acceptance

- A new branch + PR exists, created off `main` by the watch loop as an isolated
  worktree, whose PR body references the driving GitHub issue (#7).
- The OpenSpec change and the README note are mutually consistent and in sync
  with the driving issue (per the AGENTS.md sync rule).
- `make openspec-validate NAME=test-watchloop-verify-the-background-watch-loop-dr`
  exits 0 and every task in `tasks.md` is ticked.

## Non-goals

- No runtime, launcher, downloader, or CI pipeline change — this is intentionally
  a docs-only change so that merging it is low-risk (the issue demands a small,
  safe PR).
