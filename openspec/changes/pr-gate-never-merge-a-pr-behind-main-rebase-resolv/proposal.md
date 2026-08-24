# pr-gate-never-merge-a-pr-behind-main-rebase-resolv

## Why

PRs were merging while their branch was **behind** `main` (`main` moved on after the
branch was cut). That left merges that silently overwrote or clashed with newer
`main` state. The merge gate must **close the drift hole**: a PR that is behind
`main` may never be merged as-is.

## What Changes

Introduce a durable, three-layer **never-merge-behind** gate:

1. **AGENTS.md** — make it MANDATORY behavior, stated in three places:
   - the Background watch loop section,
   - the PR review/merge flow, and
   - the dispatcher merge gate.
   Before merging any PR to `main`, verify the PR head is **not behind** `main`. If
   it is behind, do NOT merge: **rebase** the PR branch onto latest `origin/main`,
   resolve any merge conflicts (in the branch — never force-push-delete work),
   re-run CI/validation, re-verify green + approved + no open threads, and only then
   merge.
2. **Dispatcher (`scripts/watchloop_dispatch.py`)** — replace the current
   *skip-behind* behavior with an active *rebase-and-retry* behavior. When the
   merge gate finds a PR behind `main` or unverifiable, it must not merely log
   "NOT merged" and move on — it must rebase/merge the PR head onto `origin/main`,
   resolve conflicts, wait for CI to re-run, and re-attempt the gate (subject to
   approval / threads / green).
3. **GitHub branch protection on `main`** — enable required status checks with
   `strict: true` (branches must be up to date before merging) and keep the
   required approving review count at 1, so GitHub blocks behind-PR merges at the
   platform layer.

Also documents the effect in `scripts/watchloop_dispatch.py` module docstring.

## Validation

- `make openspec-validate NAME=pr-gate-never-merge-a-pr-behind-main-rebase-resolv` exits 0.
- `make lint` passes (all tracked text files end with a newline).
- `make test-unit` passes (hermetic).
- Dispatcher unit/manual check: gate reports a behind PR as *rebase&retry*, not just
  *skip*.
- AGENTS.md contains the explicit never-merge-behind gate in all three locations.
- Branch protection on main has `strict: true` status checks + required approvals=1
  (verified via GitHub API).
- Delivered via feature branch + PR referencing issue #9.