# Spec: Exercise the make cron-* targets in a CI job (issue #67)

## Why
The `make cron-install` / `make cron-uninstall` / `make cron-snapshot` targets merged in #66 ship
without any CI job executing a `make cron-*` command — the make layer is untested in the pipeline.
This adds a first-class CI job that runs the real make targets against a sandboxed crontab, plus the
`CRONTAB_CMD` override that makes that safe.

---

## ADDED Requirements

### Requirement: A1 — CRONTAB_CMD overrides the crontab binary for safe testability
WHEN the `CRONTAB_CMD` environment variable is set,
THEN `scripts/install_watchloop_cron.py` invokes `$CRONTAB_CMD` (for both `-l` and `-`) instead of the
real `crontab`, so install/uninstall can be driven against a fake crontab without mutating a live one.

#### Scenario: CRONTAB_CMD is honored
Given a `CRONTAB_CMD` pointing at a fake `crontab` shim,
When   the script reads or writes the crontab,
Then   it shells out to `$CRONTAB_CMD` and never touches the real crontab.

### Requirement: A2 — make cron-* targets are driven through CRONTAB_CMD
WHEN the make targets run with `CRONTAB_CMD` set,
THEN `make cron-install` / `make cron-uninstall` operate on the fake crontab, and the CI `cron` job can
exercise the real make layer safely.

#### Scenario: make cron-install is exercised in CI
Given a CI job with `CRONTAB_CMD` set to a fake crontab shim,
When   it runs `make cron-install` twice,
Then   the fake crontab contains exactly one watch-loop line,
And   unrelated seeded lines are preserved.

#### Scenario: make cron-uninstall is exercised in CI
Given a fake crontab with one watch-loop line plus unrelated lines,
When   the CI job runs `make cron-uninstall`,
Then   the watch-loop line is removed,
And   the unrelated lines are byte-identical.

### Requirement: A3 — a CI cron job runs the make targets
WHEN CI runs,
THEN a `cron` job exists that executes `make cron-snapshot` and drives `make cron-install` /
`make cron-uninstall` against the fake crontab, and the job passes.

#### Scenario: CI cron job is green
Given the `cron` job in `.github/workflows/ci.yml`,
When   CI runs the job,
Then   it invokes the make cron-* targets against the fake crontab and exits 0.

---

## VERIFICATION

### Verification: A1
- A new hermetic test (and the CI job) sets `CRONTAB_CMD` to a fake shim and confirms the script uses it.
### Verification: A2
- The CI `cron` job runs `make cron-install` twice + `make cron-uninstall` against the fake crontab and
  asserts A2 idempotency / preservation behavior through the make layer.
### Verification: A3
- `.github/workflows/ci.yml` has a `cron` job; it is green in CI.
### Regression
- `make lint`, `make test-unit` (162 existing + new), `make openspec-validate`.
