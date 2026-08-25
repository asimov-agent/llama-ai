# fix-agents-read-guard-devhost-assertion — spec of record

## ADDED Requirements

### Requirement: guard import-location test is environment-robust
`tests/test_agents_read.py::test_guard_imports_installed_hermes_module` MUST
accept the `tools.threat_patterns` module when it resolves from any of:
`site-packages` (CI pip install), `.venv` (venv install), or `~/.hermes`
(dev-host Hermes install). It MUST still fail when the module resolves from
within the repo root (a vendored/repo-local copy).

#### Scenario: CI pip install
- **WHEN** the test runs after `pip install hermes-agent==0.19.0` (python:3.12 job)
- **THEN** the module path is under site-packages and the test passes

#### Scenario: dev host Hermes install
- **WHEN** the test runs on a dev host where hermes-agent resolves from the
  `~/.hermes` install
- **THEN** the test passes (the invariant — not a repo copy — still holds)

#### Scenario: vendored repo copy regression
- **WHEN** `tools/threat_patterns.py` is copied into the repo and imported from
  there
- **THEN** the test fails (module path starts with the repo root)
