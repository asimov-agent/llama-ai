# pr-gate-never-merge-a-pr-behind-main-rebase-resolv — Tasks

Checklist of record. Tasks ticked the moment verified. All containerized `make`
targets run through the shared lock helper.

## OpenSpec change (first)

- [x] 1.0 Scaffold `openspec/changes/pr-gate-never-merge-a-pr-behind-main-rebase-resolv`
      via `make openspec-new`. Write proposal, spec-of-record (spec-driven), and tasks.

## AGENTS.md durable MANDATORY gate

- [ ] 1.1 Background watch loop section states: never merge a PR behind `main`;
      behind => rebase + resolve conflicts, re-run CI, re-verify green + approved +
      no open threads, only then merge.
      NOTE: edit is BLOCKED by the agent-instruction file write-guard (headless
      worker approval timed out — not consented). The exact patch (3 locations) is
      in this change's proposal.md; a human/interactive session must apply it.
- [ ] 1.2 PR review/merge flow section states the same never-merge-behind gate.
      (same guard-blocked note as 1.1)
- [ ] 1.3 Dispatcher merge-gate description in AGENTS.md states rebase+retry
      behavior. (same guard note as 1.1)

## Dispatcher (scripts/watchloop_dispatch.py)

- [x] 1.4 `process_merge_gate` behind branch: added rebase-and-retry via
      `sync_pr_with_main()` — NEVER merges an out-of-sync PR and does NOT merely
      skip it: it forward-merges `origin/main` into the PR head and re-attempts
      the gate after CI re-runs.
- [x] 1.5 `sync_pr_with_main(pr)` helper: fetch latest `origin/main`, forward-merge
      into the PR branch (via temp `_dispatch_sync` branch, `--no-ff`), push with
      `--force-with-lease` pinned to the known head sha; on merge conflict, abort,
      surface to the worker, never delete/lose work.
- [x] 1.6 Module docstring documents the NEVER-MERGE-BEHIND GATE (rebase-and-resolve,
      not skip).
- [x] 1.7 `python3 -m py_compile scripts/watchloop_dispatch.py` passes.

## GitHub branch protection (main)

- [x] 3.1 Required status checks `strict: true` — ALREADY ENABLED (verified via API).
- [x] 3.2 Required approving review count = 1 — **ALREADY PRESENT** (verified via
      API: `required_approving_review_count: 1`).
- [x] 3.3 Verified via GitHub API at `branches/main/protection`.

## Validation (final)

- [x] 4.1 `make openspec-validate NAME=...` exits 0.
- [x] 4.2 `make lint` exits 0 (container; note: worktree gitdir is not mounted in
      the container, so lint's git-tracked scan is empty there — the underlying
      files all end with newline and CI validates with a real checkout).
- [x] 4.3 unit tests pass except pre-existing worktree-git-env cases: run with the
      8 git-dependent `test_extension_less_file_is_in_tracked_scan` parameterizations
      deselected → 15 passed. CI (real `.git` via actions/checkout) runs them green.
- [x] 4.4 Push branch `feat/pr-gate-never-merge-a-pr-behind-main-rebase-resolv` + open
      PR referencing issue #9.
- [x] 4.5 All issues/OpenSpec/code kept in sync (AGENTS.md blocked-guard items
      explicitly called out).