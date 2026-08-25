# feat-dispatch-auto-clean-stale-worktrees-branches — Tasks

Checklist of record. Tasks ticked the moment verified. All containerized `make`
targets run through the shared lock helper
(`scripts/serialized-make.py .watchloop/run/test.lock -- <target>`).

## OpenSpec change (first)

- [x] 1.0 Scaffold `openspec/changes/feat-dispatch-auto-clean-stale-worktrees-branches`
      via `make openspec-new`, then write `proposal.md` + `specs/**/spec.md` +
      `tasks.md`. (Change name drops the dispatcher slug's trailing hyphen —
      `openspec new` rejects names ending in `-`.)

## Dispatcher (scripts/watchloop_dispatch.py)

- [x] 1.1 Add `cleanup_merged_worktrees(dry=False)` that sweeps every `feat/*`
      worktree under `../llama-ai-wt/` whose HEAD is an ancestor of `origin/main`:
      `git worktree remove --force`, `git branch -D`, and delete the per-worker
      `.running`/`.prompt`/`.log` artifacts.
- [x] 1.2 Never touch an in-flight (`HEAD` not merged) worktree.
- [x] 1.3 Skip any merged worktree whose `.running` PID is still alive (live
      worker -> leave alone).
- [x] 1.4 `--dry` mode logs what would be cleaned without deleting.
- [x] 1.5 Call the cleanup sweep from `main()` each tick after the merge gate
      (honoring `--dry`).
- [x] 1.6 Module docstring + the dispatch log mention the cleanup step.
- [x] 1.7 `python3 -m py_compile scripts/watchloop_dispatch.py` passes.

## Documentation (AGENTS.md)

- [x] 1.8 AGENTS.md dispatcher section documents the automated merged-worktree +
      branch cleanup (in-flight + live-worker worktrees untouched).

## Tests (tests/test_watchloop_dispatch.py)

- [x] 3.1 Add hermetic test: a `feat/*` worktree merged into `origin/main` is
      removed (worktree + branch + artifacts).
- [x] 3.2 Add hermetic test: an in-flight (not-merged) worktree is left alone.
- [x] 3.3 Add hermetic test: a merged worktree with a live `.running` PID is kept.
- [x] 3.4 Add hermetic test: dry-run lists without deleting.

## Validation (final)

- [x] 4.1 `make openspec-validate NAME=feat-dispatch-auto-clean-stale-worktrees-branches` exits 0.
- [x] 4.2 `make lint-fix` (repair any trailing newline) then `make lint` pass.
- [x] 4.3 `make test-unit` passes (hermetic); the 8 `test_extension_less_file_is_in_tracked_scan`
      cases are deselected in the worktree container (gitdir not mounted — git
      ls-files empty there); they pass under real CI and are unrelated to this change.
- [x] 4.4 Push `feat/feat-dispatch-auto-clean-stale-worktrees-branches-` (origin)
      + open PR against `main` referencing #29 (PR #36 opened, ahead_by 1 /
      behind_by 0 — not behind main). Merge awaits the loop merge gate.

_Note: the branch/worktree slug is `feat-dispatch-auto-clean-stale-worktrees-branches-`
(trailing hyphen); the OpenSpec change name is the hyphen-stripped
`feat-dispatch-auto-clean-stale-worktrees-branches` because `openspec new change`
rejects trailing-hyphen names.
