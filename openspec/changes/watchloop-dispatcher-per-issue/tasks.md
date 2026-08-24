# watchloop-dispatcher-per-issue

## Dispatcher + per-issue parallel workers

- [x] 1.1 Add `scripts/watchloop_dispatch.py` — crontab entrypoint that each tick
      (a) finalizes merge-ready PRs and (b) spawns ONE dedicated background
      `project-manager` worker per open issue lacking a live branch/PR.
- [x] 1.2 Workers run in PARALLEL from their own git worktrees
      (`../llama-ai-wt/<kebab>`), each with its OWN log
      (`.watchloop/logs/feat-<kebab>.log`) — no branch/log races; an unfinished
      worker resumes from its log on a later tick.
- [x] 1.3 Merge gate is strict: merge only when CI green AND approved AND no open
      review threads AND PR head NOT behind `main` (issue #9 guard).
- [x] 1.4 Add `scripts/serialized-make.py` — fcntl lock helper
      (`serialized-make <lockfile> -- <make target>`) so every containerized
      `make` target across parallel workers is serialized via
      `.watchloop/run/test.lock`; never race the nerdctl container or the
      loop-harness.
- [x] 1.5 Workers never run `make loop-harness`, `make test`, or `make
      test-install-host` (harness-owned steps).
- [x] 1.6 AGENTS.md "The host crontab that runs this" rewritten to document the
      dispatcher + worker model, parallel-safety, and per-worker logs; `scripts/`
      committed.
- [x] 1.7 Dry-run (`watchloop_dispatch.py --dry`) reports issues/PRs without
      spawning workers or merging.
- [x] 1.8 `openspec-validate`, `lint`, `test-unit` all pass.