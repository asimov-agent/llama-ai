# stuck-pr-repair-stage — Tasks

Checklist of record. Ticked the moment verified.

## Dispatcher implementation

- [x] 1.1 Refactor `spawn_worker` -> `_spawn_worker_for_branch` (shared atomic lock + spawn).
- [x] 1.2 Add `process_stuck_prs`, `spawn_repair_worker`, `pr_repairable`, `pr_issue_number`, `slug_from_branch`, `repair_prompt`.
- [x] 1.3 Call `process_stuck_prs(prs, dry=...)` in `main()` after the spawner loop.
- [x] 1.4 Fail-closed on malformed/incomplete PR dicts (never crash the tick).
- [x] 1.5 Reuse the atomic `.running` lock + local-model probe for repair spawns.
- [x] 1.6 `from __future__ import annotations` so `int | None` parses on Python 3.9.

## Tests (edge cases, hermetic)

- [x] 2.1 `pr_repairable`: open-threads actionable, red-CI actionable, clean not-actionable, incomplete never raises.
- [x] 2.2 `pr_issue_number`: extracts closing issue, no-keyword -> None, empty -> None.
- [x] 2.3 `process_stuck_prs`: spawns for red CI, spawns for open threads, skips clean, skips behind, skips no-closing-issue, skips malformed entries, live-lock suppresses, local-model-down skips, dry-run reports only.
- [x] 2.4 `main()` integration: spawns a repair worker for a red-CI PR.

## Verification

- [x] 3.1 `tests/test_watchloop_dispatch.py` ALL green in the containerized test image (60 passed).
- [x] 3.2 `make lint` passes (linefeed + trailing newlines).
- [x] 3.3 `make openspec-validate NAME=stuck-pr-repair-stage` passes.
- [x] 3.4 Commit + push a feature branch; open the PR; CI (incl. `agents-read`) green.
