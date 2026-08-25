# feat-dispatch-probe-the-worker-model-endpoint-befo

## Why

The watch-loop dispatcher (`scripts/watchloop_dispatch.py`, host crontab every
20 min) spawns a dedicated `project-manager` hermes worker for every orphaned
open issue WITHOUT ever checking that the configured worker model endpoint is
actually reachable. With the worker model pointed at the **local llama.cpp
server** (`llm-local` on `localhost:11434`, custom provider), that server is a
single point of failure:

- If `llama-server` is down or hasn't finished loading, every spawned worker
  dies on its first LLM call. A full 20-min cron tick is burned per issue doing
  nothing useful.
- For N orphaned issues you get N doomed workers → stale `.running` locks and
  log noise in `.watchloop/logs/`.
- The `worker-model` template's documented "local" option makes this the
  default-mode footgun, not an edge case.

The dispatcher must be robust to a down model endpoint: fail closed and
cleanly (log + skip), exactly like the existing fail-closed paths in `api()`.

## What Changes

- **Pre-spawn probe.** Before `spawn_worker`, when the effective worker
  provider is *local* (provider empty, or `localhost`/`custom`/`llama.cpp`),
  the dispatcher GETs the model endpoint
  `http://127.0.0.1:11434/v1/models` (127.0.0.1, not `localhost`, which can
  resolve to IPv6 `::1` on some hosts) and confirms the effective model id is
  present in the returned `data[].id` list.
- **Fail closed.** Unreachable endpoint, bad/absent response, or model-not-in-
  list → `log("  issue#N: worker model <M> unreachable on <url> — skipping
  spawn")` and `continue`: no worker, no lock, no prompt file, no worktree.
  The probe must not throw in a way that wedges the whole tick.
- **Hosted mode unaffected.** When the effective provider is `openrouter`
  (or any other non-local provider), the dispatcher keeps current behaviour —
  no local-port probe.
- **Unit tests.** `tests/test_watchloop_dispatch.py` covers (a) local model
  reachable → spawn proceeds, (b) local model unreachable → spawn skipped
  cleanly + no lock file created, (c) hosted provider → no local probe
  attempted. The HTTP probe is monkeypatched so no real network is needed.
- **Docs.** `scripts/worker-model.template`'s local-option block notes that the
  dispatcher probes `:11434` before spawning and skips cleanly when down.

## User-Visible Impact

No change to serving/model commands. A down local `llama-server` no longer
spawns doomed workers: the dispatcher logs one line per orphaned issue and
skips, retrying on the next tick when the server is back.

## Non-Goals

- No change to the parallel-worktree model, serialized-make lock, tick dedup,
  or stale-worktree cleanup.
- No probe for hosted providers (OpenRouter etc.).
- No change to how the worker model is *configured* (env/file resolution stays
  as-is).
