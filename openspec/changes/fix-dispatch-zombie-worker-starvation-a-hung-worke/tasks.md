# Tasks — fix-dispatch-zombie-worker-starvation-a-hung-worke (issue #63)

- [x] 1. Write OpenSpec proposal.md + specs/llama-ai-tooling/spec.md (Given/When/Then scenarios)
      + tasks.md; validate via `make openspec-validate NAME=fix-dispatch-zombie-worker-starvation-a-hung-worke`; tick.
- [x] 2. Implement activity-based liveness in `scripts/watchloop_dispatch.py`:
      - add `STUCK_LOG_STALE_SECONDS` (default 2400) + `log_stale_seconds(branch_log, now) -> float|None`;
      - add `worker_is_stuck(live_pid, branch_log, now) -> bool` (alive AND log stale; dead/missing-log → not stuck);
      - add `kill_process_tree(pid)` + `_children_of(pid)` (kill bash parent + descendants, /proc+pgrep robust);
      - in `_spawn_worker_for_branch`: live-but-stuck → kill tree + remove lock + respawn; live+fresh log → skip;
        dead PID → existing issue #18 path unchanged.
- [x] 3. Add hermetic tests `TestStuckWorkerResume` (Given/When/Then-marked, no skips):
      - B1 fresh-log-not-killed; B1-2 stale-log-killed-and-respawned; B3 log-staleness-not-wall-clock;
        plus confirm existing alive/dead tests stay green.
- [x] 4. Add REAL CI e2e `tests/test_watchloop_dispatch_e2e.py` + `make test-agents-e2e` target + `dispatch-e2e`
      CI job + loop-harness stage + README sync — a fake worker does README issue-work, a hung worker is
      killed+respawned, README wording is asserted (all <1 min, no GitHub/LLM/network).
- [x] 5. Verify: `make lint` GREEN, `make test-unit` GREEN (156 pass incl. TestStuckWorkerResume),
      `make test-agents-e2e` GREEN (2 e2e), `make openspec-validate NAME=fix-dispatch-zombie-worker-starvation-a-hung-worke`
      GREEN; commit + push each batch; open PR against `main` referencing issue #63 (Closes #63 in PR body).