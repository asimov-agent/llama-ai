# feat-dispatch-delete-stale-remote-branches-after-a — Tasks

Checklist of record. Tasks ticked the moment verified. All containerized `make`
targets run through the shared lock helper
(`scripts/serialized-make.py .watchloop/run/test.lock -- <target>`).

## OpenSpec change (first)

- [x] 1.0 Scaffold `openspec/changes/feat-dispatch-delete-stale-remote-branches-after-a`
      via `make openspec-new`, then write `proposal.md` + `specs/**/spec.md` +
      `tasks.md`.

## Dispatcher (scripts/watchloop_dispatch.py)

- [x] 1.1 `merge_pr`: include `delete_branch: true` in the
      `PUT /pulls/<N>/merge` body.
- [x] 1.2 `cleanup_merged_worktrees`: after cleaning a merged branch, check the
      remote (`git ls-remote --heads origin <branch>`) and, if the remote
      branch exists and is not `main`, run `git push origin --delete <branch>`.
- [x] 1.3 `--dry` logs the would-be remote deletion without executing it.
- [x] 1.4 Module docstring (and log lines) mention remote-branch deletion.
- [x] 1.5 `python3 -m py_compile scripts/watchloop_dispatch.py` passes.

## Documentation (AGENTS.md + README.md)

- [x] 1.6 AGENTS.md dispatcher section documents that merged PR remote
      branches are auto-deleted (safety net for the merge API).
- [x] 1.7 README.md reflects the remote-branch deletion behaviour.

## Tests (tests/test_watchloop_dispatch.py)

- [x] 3.1 Hermetic test: merged, cleaned branch → `git push origin --delete
      <branch>` is issued.
- [x] 3.2 Hermetic test: in-flight (not-merged) branch → no `push origin
      --delete`.
- [x] 3.3 Hermetic test: `dry=True` → remote delete reported but not executed.
- [x] 3.4 Hermetic test: `merge_pr` PUT body includes `delete_branch: true`.
- [x] 3.5 Hermetic test: `main` is never deleted via `push origin --delete`.
- [x] 3.6 Hermetic test: already-absent remote branch → no delete issued.
      (plus: a failing `git push` does not break the sweep)

## Validation (final)

- [x] 4.1 `make openspec-validate NAME=feat-dispatch-delete-stale-remote-branches-after-a`
      exits 0.
- [x] 4.2 `make lint-fix` then `make lint` pass.
- [x] 4.3 `make test-unit` passes (hermetic). The 8
      `test_extension_less_file_is_in_tracked_scan` cases fail in the worktree
      container (gitdir not mounted — git ls-files empty there); they pass under
      real CI and are unrelated to this change (same note as issue #29's task).
- [ ] 4.4 Push `feat/feat-dispatch-delete-stale-remote-branches-after-a` to
      origin + open PR against `main` referencing issue #45 (not behind main).
