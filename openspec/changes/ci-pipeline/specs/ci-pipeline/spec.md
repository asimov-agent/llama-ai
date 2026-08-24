# ci-pipeline — spec of record

## ADDED Requirements

### Requirement: CI pipeline triggers on all branches and PRs
The system MUST provide a GitHub Actions workflow `.github/workflows/ci.yml` that
triggers on `push` to any branch and on `pull_request`, running the project's
verification.

#### Scenario: any branch push
- **WHEN** a commit is pushed to any branch (not just `main`)
- **THEN** the CI workflow runs

#### Scenario: pull request
- **WHEN** a pull request is opened or updated
- **THEN** the CI workflow runs on the PR head

### Requirement: each stage is a separate parallel job
The CI pipeline MUST run each verification stage as its own independent,
concurrently-running GitHub Actions job (not one sequential job), so a failure in
one stage does not block the others.

#### Scenario: parallel execution
- **WHEN** the pipeline runs
- **THEN** the lint, unit, openspec, and cpu-health jobs execute in parallel

### Requirement: CPU-only lightweight LLM health check
The CI pipeline MUST include a job that builds llama-server in CPU mode,
downloads the lightweight model `qwen2.5-0.5b-instruct-q4_0.gguf` (CPU-only, no
GPU), launches llama-server with it, waits for `/health`, POSTs `"hi"` to
`/v1/chat/completions`, and asserts a real completion.

#### Scenario: CPU inference works
- **WHEN** the cpu-health job runs
- **THEN** llama-server answers a chat message on a CPU-only runner

### Requirement: linefeed lint in CI
The pipeline MUST run `make lint` and fail if any tracked text file lacks a
trailing newline.

#### Scenario: linefeed regression
- **WHEN** a branch pushes a text file without a trailing newline
- **THEN** the lint job fails the pipeline
