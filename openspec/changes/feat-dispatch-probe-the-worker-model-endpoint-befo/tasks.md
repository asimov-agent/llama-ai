# feat-dispatch-probe-the-worker-model-endpoint-befo

## Implementation (scripts/watchloop_dispatch.py)

- [x] 1.1 Add a `LOCAL_PROVIDERS` constant (empty string, `localhost`,
      `custom`, `llama.cpp`) and a helper `effective_provider_is_local() -> bool`
      that classifies the effective worker provider (env/config resolved
      `WORKER_PROVIDER`).
- [x] 1.2 Add a probe function `probe_worker_model(model, url=
      "http://127.0.0.1:11434/v1/models", timeout=10) -> bool` using
      `urllib.request` (already imported): GET the endpoint, parse JSON, return
      True iff the effective model id appears in `data[].id`/`model`. Any
      exception / bad body / missing model → False. Never raises.
- [x] 1.3 In `main`'s spawn loop, BEFORE `spawn_worker(issue)`: if
      `effective_provider_is_local()`, run `probe_worker_model(WORKER_MODEL or
      profile-default "llm-local")`; on failure log `  issue#N: worker model
      <M> unreachable on <url> — skipping spawn` and `continue` (no worker, no
      lock, no prompt file, no worktree). Non-local provider → no probe.
- [x] 1.4 Ensure the probe result does not wedge the tick: wrap so a
      per-issue probe failure only skips that issue, and the loop continues.

## Unit tests (tests/test_watchloop_dispatch.py)

- [x] 2.1 Test (a): local provider + reachable model (probe stubbed True) →
      spawn proceeds (Popen invoked, lock written).
- [x] 2.2 Test (b): local provider + unreachable model (probe stubbed False) →
      spawn skipped cleanly, no `.running` lock file created, log emitted.
- [x] 2.3 Test (c): hosted provider (e.g. `openrouter`) → probe function not
      called at all, spawn proceeds.
- [x] 2.4 Hermeticity: monkeypatch the probe fn (and `urllib` where testing the
      probe itself) so no real network call happens; optionally cover
      `probe_worker_model` parsing with a stubbed `urlopen` (listed model →
      True, unlisted model → False, connection error → False).

## Docs

- [x] 3.1 Update `scripts/worker-model.template` local (llama.cpp) option block:
      note the dispatcher probes `http://127.0.0.1:11434/v1/models` before
      spawning and skips cleanly (log + no spawn) when the local server is down.

## Verification

- [x] 4.1 `make openspec-validate NAME=feat-dispatch-probe-the-worker-model-endpoint-befo`
      exits 0 (via the serialized-make lock).
- [x] 4.2 `make lint-fix` + `make lint` (via lock) pass after staging.
- [x] 4.3 `make test-unit` (via lock) passes, including the new probe tests.
