# 2026-09-08 — issue #69 follow-up: close the openspec-tasks CI gate gap

## The gap
PR #70 (closes #69) was fully green in CI but its OpenSpec change still had an unticked
task (`- [ ] Commit + push ... open PR`) — the `openspec-tasks-check` step in
`.github/workflows/ci.yml` ran `make openspec-tasks-check NAME=ci-pipeline`, scoping the
scan to ONE always-present change. A feature PR adds its OWN new change dir under
`openspec/changes/<name>`; that dir was never scanned, so an unticked task in the PR's own
change sailed through CI green.

The loop harness already runs the all-active form (`make openspec-tasks-check`, no NAME) —
only the CI job was mis-scoped.

## The fix (on PR #70's branch)
1. `.github/workflows/ci.yml` openspec job: `make openspec-tasks-check NAME=ci-pipeline`
   → `make openspec-tasks-check` (no NAME = scan ALL active changes). A PR adding an
   incomplete change now fails RED.
2. Regression test `tests/test_check_openspec_tasks.py::test_scoping_check_to_one_change_misses_unticked_in_another`:
   proves a NAME-scoped check misses another change's unticked task while the all-active
   scan catches it (returns 1).
3. Ticked the previously-unticked task 14 in `fix-dispatch-stuck-detector-false-liveness/tasks.md`.

## Lesson
`openspec-tasks-check` must run with NO NAME so it walks every active change. Scoping it to
a single change (like `ci-pipeline`, which always exists on main) makes the gate useless for
feature PRs.
