# Automate + document watch-loop install/uninstall via make (macOS + Linux) (issue #65)

## Problem
The self-driving watch loop (host crontab `*/20 * * * *` -> `scripts/watchloop_dispatch.py`) is the
backbone of this repo, but installing it on a fresh host is neither automated nor fully documented.
Today "setup" means hand-editing `crontab -e` with the entry buried in AGENTS.md. There is **no `make`
target** for cron install/uninstall and no step-by-step fresh-host guide. Confirmed: the Makefile has
zero `cron*` targets and there is no dedicated installer script in `scripts/` (only
`watchloop_dispatch.py` itself).

## Change
1. **`make cron-install`** — install the `*/20 * * * *` watch-loop entry idempotently via a small
   helper (`scripts/install_watchloop_cron.py`) that calls `crontab`, guarding against duplicate
   entries and preserving unrelated crontab lines. The command written resolves the correct
   python3/PATH per OS (macOS `/opt/homebrew` fallback vs plain `/usr/bin`) and sets
   `HERMES_PROFILE=project-manager`.
2. **`make cron-uninstall`** — remove ONLY the watch-loop entry, leaving every other crontab line
   untouched.
3. **Fresh-host docs** — a README subsection + AGENTS.md pointer covering prerequisites
   (`make install`, `.env` tokens), per-OS install steps (macOS pkill/Colima vs Linux
   systemd-cron/PATH), the worker-model tuning pointer, a first-tick smoke check, and the
   uninstall recipe.
4. **Hermetic tests** — in `tests/test_install_watchloop_cron.py`: entry flattening, idempotency
   (no duplicates on double install), uninstall-preserves-other-lines, and per-OS command
   generation. Stub `subprocess`/`platform` — no real crontab, no container, no network.

## Verification
- `make cron-install` run twice → exactly ONE `*/20` watch-loop line (idempotent, no dupes).
- `make cron-uninstall` → watch-loop line removed, unrelated lines preserved (unit-tested).
- Per-OS install command generation is unit-tested (macOS vs Linux PATH/python).
- README + AGENTS.md document install/uninstall + prerequisites.
- `make lint`, `make test-unit` green (hermetic); `make openspec-validate` passes.

> Note: docs + a small script/make change — does NOT alter the running loop's behavior. It makes the
> existing (already-merged, issue #63) watch loop installable on any mac/Linux host.