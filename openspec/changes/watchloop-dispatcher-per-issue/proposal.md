# watchloop-dispatcher-per-issue

## Why

The background watch loop must drive each open issue/PR with **its own dedicated
Hermes `project-manager` session** running in **parallel** — never serialize all
issues behind a single all-in-one session, and never let one issue's work crowd
out or block the others. Concurrent workers must also never corrupt the shared
test harness (nerdctl container / loop-harness) or each other's logs.

## What Changes

- Replace the single per-tick `hermes chat` loop with a **dispatcher**
  (`scripts/watchloop_dispatch.py`, run by the host crontab every 20 min) that:
  1. **Merge gate:** merges a PR to `main` only when CI is green AND an approved
     review exists AND no open review threads AND the PR head is **not behind
     `main`** (never merge an out-of-sync/behind PR — issue #9).
  2. **Parallel issue workers:** for every open issue with no live branch/PR,
     creates an isolated git worktree (`git worktree add -b
     feat/<kebab> ../llama-ai-wt/<kebab> origin/main`) and spawns a DEDICATED
     background `project-manager` Hermes session whose cwd is that worktree
     (loads AGENTS.md), driving ONLY that issue to a PR. Workers run in parallel;
     a worker that doesn't finish in one tick resumes from its own log next tick.
- Add `scripts/serialized-make.py` — the shared fcntl lock helper that
  serializes every containerized `make` target used by the loop
  (`openspec-*`, `test-unit`, `test-install`, `lint`, `lint-fix`, `test`) so
  parallel workers never race the nerdctl container. Uses a lock at
  `.watchloop/run/test.lock`. `flock` is not available on macOS, so use fcntl.
- `scripts/watchloop_dispatch.py` and `scripts/serialized-make.py` are committed
  (infrastructure — versioned with the Config).
- AGENTS.md "The host crontab that runs this" section rewritten to document the
  dispatcher + per-issue parallel-worker model, the parallel-safety rules, and
  the per-worker logs. `.watchloop/{run,logs,prompt.txt}` remain gitignored at
  runtime but `scripts/` is tracked.

## Validation

- `make openspec-validate NAME=watchloop-dispatcher-per-issue` exits 0.
- `make lint` passes (all tracked text files end with a newline).
- `make test-unit` passes (hermetic).
- Dry run shows dispatcher correctly reports issues/PRs without mutating
  (except the merge gate, which is intentional).