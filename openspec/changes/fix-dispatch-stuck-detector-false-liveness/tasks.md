# Tasks — fix-dispatch-stuck-detector-false-liveness (issue #69)

- [x] OpenSpec change scaffolded (`proposal.md`, `specs/watchloop/spec.md`, `tasks.md`)
- [x] Raise `STUCK_LOG_STALE_SECONDS` default from 2400 s to a long true-hang horizon (4 h)
- [x] Add `WORKER_LOG_HEARTBEAT_SECONDS` (default 300 s), env-injectable
- [x] Wrap the worker spawn command in a heartbeat loop that appends `[hb <epoch>]`
      to the worker's own log while the hermes child is alive
- [x] Add a unit test asserting the spawn command embeds the heartbeat loop +
      `WORKER_LOG_HEARTBEAT_SECONDS`
- [x] Existing hermetic unit tests (`tests/test_watchloop_dispatch.py`) pass
- [x] Existing e2e tests (`tests/test_watchloop_dispatch_e2e.py`) pass
- [x] `make lint`, `make test-unit`, `make openspec-validate` green
- [x] README watch-loop section reflects heartbeat-based liveness
- [x] Fix the openspec CI job to scan ALL active changes (not just `NAME=ci-pipeline`)
      so a PR's own new change with unticked tasks fails RED
- [x] Add a regression test proving a NAME-scoped check misses another change's
      unticked task while the all-active scan catches it
- [x] Commit + push `feat/fix-dispatch-stuck-detector-false-liveness`, open PR
      referencing issue #69
