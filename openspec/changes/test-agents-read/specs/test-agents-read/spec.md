# test-agents-read — spec of record

## ADDED Requirements

### Requirement: fail-closed scan of AGENTS.md against the Hermes threat patterns
The repo MUST provide a command (`make test-agents-read` -> `scripts/scan_agents_md.py`) that scans `AGENTS.md` with the same context-file threat patterns Hermes applies to context files (`scope="context"`). If any pattern matches, the command MUST exit non-zero and print the matched pattern id(s), so CI and the local loop turn RED instead of silently dropping the rulebook.

#### Scenario: a clean AGENTS.md passes
- **WHEN** `scripts/scan_agents_md.py` scans an `AGENTS.md` with no threat-pattern matches
- **THEN** it exits 0 and prints `CLEAN`

#### Scenario: a recurrence of the exfil_curl false positive fails closed
- **WHEN** `AGENTS.md` contains a `curl ... ${<SECRETVAR>}` line that Hermes's `exfil_curl` pattern would match
- **THEN** the scanner exits non-zero and names the `exfil_curl` pattern

### Requirement: hermes-agent is a real 3rd-party dependency (not vendored)
The guard MUST import `tools.threat_patterns.scan_for_threats` from the installed `hermes-agent` package — a declared PyPI dependency (`tools/requirements-dev.in`, pinned `==0.19.0`). The module MUST NOT be copied/vendored into the repo.

#### Scenario: import from site-packages
- **WHEN** the scanner runs with `hermes-agent` installed
- **THEN** `tools.threat_patterns` resolves to `site-packages`, not a repo-local copy

### Requirement: CI wiring (standalone python:3.12 job)
A parallel GitHub Actions job `agents-read` MUST install `hermes-agent==0.19.0` on `python:3.12-slim`, run the scanner on `AGENTS.md`, and run the guard's unit-test corpus (`tests/test_agents_read.py`, `--noconftest`). It runs on its own python:3.12 image because the project's 3.10 test image cannot install hermes-agent (requires Python >=3.11) and must not be destabilized.

#### Scenario: CI runs the guard
- **WHEN** any branch or PR pushes
- **THEN** the `agents-read` job installs hermes-agent, scans AGENTS.md, and runs the corpus — failing red if any threat matches or the corpus fails

### Requirement: edge-case / permutation test corpus
`tests/test_agents_read.py` MUST cover a corpus of AGENTS.md variants that must PASS (current AGENTS.md, empty, legit curl-with-auth-var-on-own-line, prose mentioning token, normal rulebook) and variants that MUST FAIL (exfil curl/wget, prompt-injection, role-hijack, invisible unicode, secret reads). It MUST also assert the scanner subprocess exits non-zero on a blocking file and zero on a clean file, and that the module is imported from site-packages.

#### Scenario: corpus passes/fails as expected
- **WHEN** each fixture is scanned
- **THEN** pass-fixtures yield no findings and fail-fixtures yield findings

### Non-goals
The command treats AGENTS.md as data: it only regex-scans the file, never executes content from it, and never modifies it.
