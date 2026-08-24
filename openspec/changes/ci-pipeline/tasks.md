# ci-pipeline — Tasks

Checklist of record. Each stage is a separate parallel CI job. Tasks ticked the
moment verified. All CI stages drive Makefile targets so CI and local loop are
identical.

## CI workflow

- [x] 1.1 Add `.github/workflows/ci.yml` triggering on `push` (all branches) and
      `pull_request`
- [x] 1.2 Add a `cpu-health` job: build llama.cpp llama-server in CPU-only mode,
      `make download-test-model` (stores model into ~/models/Qwen/8GB), then
      `make test-health` (launch, /health, answer "hi"). No GPU.
- [x] 1.3 Each stage is its own parallel job wired to Makefile targets:
      `make lint`, `make test-unit`, `make test-install`,
      `make openspec-validate NAME=ci-pipeline`, `make download-test-model` +
      `make test-health`
- [x] 1.4 All verification jobs run in parallel (separate `job:` keys, not
      chained)

## CI-reproducibility (same command as local loop)

- [x] 1.5 `test-health` falls back to running repo llama_ai.py directly (with
      $LLAMA_SERVER) when ~/bin/llama-ai isn't installed, so the SAME health
      check runs on a bare CI runner and on the host
- [x] 1.6 `download-test-model` stores the lightweight CPU model into
      ~/models/Qwen/8GB (same path local loop uses)

## Verification (final)

- [x] 2.1 `make lint` passes; `make openspec-validate NAME=ci-pipeline` passes
- [x] 2.2 `.github/workflows/ci.yml` committed on a feature branch with the
      OpenSpec change first
- [x] 2.3 Full local loop GREEN (download, lint, unit, install, health, test,
      openspec all PASS; health answers "hi")
