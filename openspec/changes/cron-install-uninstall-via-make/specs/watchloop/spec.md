# Spec: Watch-loop cron install/uninstall via make (issue #65)

## Why
Installing the self-driving watch loop on a fresh host requires hand-editing the crontab and hunting
the entry in AGENTS.md — no `make` target, no per-OS guide. This change automates install/uninstall
behind `make` and documents the fresh-host steps for both macOS and Linux.

---

## ADDED Requirements

### Requirement: A1 — `make cron-install` installs the watch-loop entry idempotently
WHEN `make cron-install` is run,
THEN the `*/20 * * * *` watch-loop crontab entry (`HERMES_PROFILE=project-manager ... watchloop_dispatch.py`)
is added exactly once, any unrelated existing crontab lines are preserved, and running it again does
not duplicate the entry.

#### Scenario: double install adds only one entry
Given a host crontab with unrelated lines,
When   `make cron-install` is run twice,
Then   the resulting crontab contains exactly one `*/20 ... watchloop_dispatch.py` line,
And   every pre-existing unrelated line is still present.

### Requirement: A2 — `make cron-uninstall` removes only the watch-loop entry
WHEN `make cron-uninstall` is run,
THEN the `*/20 ... watchloop_dispatch.py` line is removed,
And   all unrelated crontab lines are preserved.

#### Scenario: uninstall preserves unrelated lines
Given a crontab containing one watch-loop line plus unrelated user lines,
When   `make cron-uninstall` is run,
Then   the watch-loop line is gone,
And   the unrelated lines are byte-identical and still present.

### Requirement: A3 — per-OS command generation is deterministic and testable
WHEN the installed command is generated,
THEN it selects the correct python3 and PATH for the platform (macOS `/opt/homebrew` fallback vs
Linux plain `/usr/bin`), and that selection is unit-testable without touching a real crontab.

#### Scenario: macOS path uses homebrew python3 fallback
Given the platform is macOS with no python3 on the base PATH,
When   the install command is generated,
Then   it references `/opt/homebrew/bin/python3` (or an explicit user override) for the dispatcher.

#### Scenario: Linux path uses the base python3
Given the platform is Linux,
When   the install command is generated,
Then   it references plain `python3` from the standard PATH.

### Requirement: A4 — docs cover fresh-host setup for macOS and Linux
WHEN a user wants to set up the watch loop,
THEN the README (and a pointer in AGENTS.md) provides: prerequisites (`make install`, `.env` tokens),
per-OS install steps, the worker-model tuning pointer, a first-tick smoke check, and the uninstall
recipe.

#### Scenario: README documents install and uninstall
Given a fresh checkout on macOS or Linux,
When   the README is read,
Then   it explains how to `make cron-install` and `make cron-uninstall`,
And   lists prerequisites and a first-tick smoke check.

---

## VERIFICATION

### Verification: A1
- Hermetic: install flattening produces exactly one entry (double-install idempotent), unrelated
  lines preserved — `tests/test_install_watchloop_cron.py`, stubbing `crontab`/`subprocess`.
### Verification: A2
- Hermetic: uninstall removes only the watch-loop line, leaves unrelated lines byte-identical.
### Verification: A3
- Hermetic: per-OS command generation returns the expected python3/PATH per platform.
### Verification: A4
- README + AGENTS.md contain the fresh-host install/uninstall documentation.
### Regression
- `make lint`, `make test-unit` green; `make openspec-validate` passes.