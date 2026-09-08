# Exercise the make cron-* targets in a CI job (issue #67)

## Problem
PR #66 merged `make cron-install` / `make cron-uninstall` / `make cron-snapshot` (and
`scripts/install_watchloop_cron.py`) into main, and the hermetic logic is covered by `make test-unit`.
But **no CI job actually executes a `make cron-*` target**. The make layer ships with zero pipeline
coverage that it runs — confirmed: main's `.github/workflows/ci.yml` has no `cron` job (0 matches).

## Change
1. **`CRONTAB_CMD` override** in `scripts/install_watchloop_cron.py`: when set, the script runs
   `$CRONTAB_CMD -l` / `$CRONTAB_CMD -` instead of the real `crontab`. This points the script (and
   therefore the `make` targets) at a fake/sandboxed crontab so CI can drive the real make targets
   safely — no real crontab mutated.
2. **New CI job `cron`** in `.github/workflows/ci.yml` that:
   - runs `make cron-snapshot` (a REAL `make` invocation of the new machinery; no mutation);
   - drives `make cron-install` twice against a fake `crontab` (via `CRONTAB_CMD`) and asserts exactly
     one entry (idempotency, A1) and that unrelated lines are preserved;
   - drives `make cron-uninstall` and asserts the watch line is gone while unrelated lines remain (A2).
   All through the **make** targets, not just the hermetic Python functions.
3. **Fixture** `tests/` fake `crontab` shim + a hermetic test that exercises the real
   `make cron-install`/`cron-uninstall` via the make target against the fake crontab (so the CI gate
   and the local `make test-unit` both cover the make layer).

## Verification
- `make test-unit` — 162 existing + new make-layer tests green (hermetic).
- New CI `cron` job green: runs the real `make cron-*` targets against the fake crontab.
- `make lint`, `make test-unit`, `make openspec-validate` all green.
