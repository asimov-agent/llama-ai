# GitHub Actions CI pipeline (all branches, parallel stages)

## Why

The local loop harness (`make loop`) is a **sequential, fast** runner meant for
local verification and for the agent to test steps individually. For shared CI,
we want a **parallel** pipeline: each verification step as its own independent
GitHub Actions job, all running concurrently, so failures are isolated and the
whole pipeline is fast. Every stage must include actually running a
**lightweight CPU-only GGUF model** through llama-server and hitting `/health`
and `/v1/chat/completions`.

## What Changes

- Add `.github/workflows/ci.yml` triggered on `push` (all branches) and
  `pull_request`.
- A **build job** builds llama.cpp `llama-server` in CPU mode (GitHub runners
  have no Metal GPU) and uploads it as a build artifact.
- A **model job** downloads the lightweight CPU model `qwen2.5-0.5b-instruct-q4_0.gguf`.
- **Parallel verification jobs** (each needs only the artifacts + model):
  - `limit`: linefeed lint (`make lint`)
  - `unit`: hermetic unit tests (`make test-unit`)
  - `openspec`: validate the active OpenSpec change (`make openspec-validate`)
  - `cpu-health`: launch the CPU llama-server, `/health`, answer "hi" on
    `/v1/chat/completions` (real CPU inference)
- All jobs **run in parallel**, each a separate GitHub Actions job, so a failure
  in one does not block the others and results are fast.

## Capabilities

- **CI-parallel**: each stage is its own parallel job, isolated failures.
- **CPU-model**: end-to-end LLM serving without a GPU.

## Impact

GitHub Actions minutes increase on every branch push. No runtime serving impact.
