# Tasks — cron-make-targets-ci-job (issue #67)

- [x] 1. Write OpenSpec proposal.md + specs/watchloop/spec.md + tasks.md; validate via
      `make openspec-validate NAME=cron-make-targets-ci-job`; tick.
- [x] 2. Add `CRONTAB_CMD` override to `scripts/install_watchloop_cron.py`: `_crontab_cmd()` returns
      `$CRONTAB_CMD` split (or `["crontab"]`), used by `_current_lines()` and `_write_lines()`.
- [x] 3. Add a new `cron` CI job in `.github/workflows/ci.yml` that, with `CRONTAB_CMD` set to a fake
      shim: runs `make cron-snapshot`, drives `make cron-install` twice (assert one entry), then
      `make cron-uninstall` (assert unrelated preserved).
- [x] 4. Add the fake `crontab` shim fixture (`tests/fixtures/fake-crontab.sh`) + hermetic tests
      (`TestMakeTargetsViaFakeCrontab`) exercising the REAL make targets against the fake crontab;
      wired into `make test-unit` (164 total pass).
- [x] 5. Verify: `make lint` OK, `make test-unit` 164 pass (incl. new make-layer tests), `make
      openspec-validate` valid; commit + push each batch; open PR against `main` referencing issue
      #67 (Closes #67 in PR body).
