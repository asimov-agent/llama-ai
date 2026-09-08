# Tasks — cron-install-uninstall-via-make (issue #65)

- [x] 1. Write OpenSpec proposal.md + specs/watchloop/spec.md (Given/When/Then scenarios) + tasks.md;
      validate via `make openspec-validate NAME=cron-install-uninstall-via-make`; tick.
- [x] 2. Implement `scripts/install_watchloop_cron.py`:
      - `render_entry(platform, python_override) -> str` — builds the `*/20` watch-loop line with the
        correct python3/PATH per OS (macOS `/opt/homebrew` fallback vs Linux plain python3);
      - `current_crontab() / write_crontab(lines)` — read/write via `subprocess` (`crontab -l` / `crontab -`);
      - `install()` — append the entry iff absent (idempotent), preserve unrelated lines;
      - `uninstall()` — remove ONLY the watch-loop line, preserve unrelated lines;
      - CLI `install` / `uninstall` / `snapshot` subcommands; guard against a missing `crontab` binary.
- [x] 3. Add `make cron-install`, `make cron-uninstall`, `make cron-snapshot` targets (wired into `.PHONY` + help).
- [x] 4. Add hermetic tests `tests/test_install_watchloop_cron.py` (#Given/#When/#Then, no skips):
      - A1 double-install → exactly one entry, unrelated lines preserved;
      - A2 uninstall → watch-loop line gone, unrelated lines byte-identical;
      - A3 per-OS command generation (macOS homebrew vs Linux plain python3);
      - stub `subprocess`/`platform` — no real crontab/network/container.
      Wired into `make test-unit` (162 total pass).
- [x] 5. Docs: README fresh-host install/uninstall section.
- [x] 6. Verify: `make lint` GREEN, `make test-unit` GREEN (162 incl. new tests), `make openspec-validate` GREEN;
      commit + push each batch; open PR against `main` referencing issue #65 (Closes #65 in PR body).
