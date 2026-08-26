# fix-agents-read-guard-devhost-assertion

## Why

PR #40 (issue #39) added the AGENTS.md rulebook-loading guard
(`scripts/scan_agents_md.py` + `tests/test_agents_read.py` + the `agents-read`
CI job). That work is merged, but the guard's own unit test
`tests/test_agents_read.py::test_guard_imports_installed_hermes_module` is
brittle on a dev host: it asserts the imported
`tools.threat_patterns` module path contains `site-packages` or `.venv`.

On a dev host the guard legitimately runs against the Hermes install itself
(e.g. `~/.hermes/hermes-agent` — a source checkout / Nix-style install with no
site-packages component in the path, and not a `.venv` either), so the test
fails even though the invariant it protects ("import the real 3rd-party
hermes-agent module, never a repo-local copy") holds: the module is NOT under
the repo root. The CI `agents-read` job (python:3.12 + pip install) passes, but
`make test-agents-read`-adjacent local runs (issue #39's "runnable ... locally"
requirement) go red for a false reason.

## What Changes

- Loosen `test_guard_imports_installed_hermes_module` to accept any of:
  - `site-packages` (CI / pip installs),
  - `.venv` (venv installs),
  - `~/.hermes` (the standard Hermes install location on dev hosts),
  while keeping the hard assertion that the module is NOT under the repo root
  (the vendored-copy regression the test was written to catch).
- Update the comment block to explain the three legitimate locations.

Docs/spec-only for the guard's behavior; the guarded behavior (scanner,
fixtures, CI job, Makefile target) is unchanged.

## Capabilities / Contract

- The "imports the installed module, not a repo copy" test passes under CI
  (pip site-packages) AND on a dev host (Hermes install path), and still
  fails when the module resolves to a repo-local copy.

## Tasks (mirror)

- [ ] 1.1 Fix the assertion in tests/test_agents_read.py
- [ ] 1.2 Verify: full guard suite green on the dev host (hermes install path)
- [ ] 1.3 Verify: `make lint` + `make openspec-validate NAME=fix-agents-read-guard-devhost-assertion`
