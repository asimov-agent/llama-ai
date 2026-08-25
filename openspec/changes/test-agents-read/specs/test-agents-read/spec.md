# test-agents-read — spec of record

## ADDED Requirements

### Requirement: fail-closed scan of AGENTS.md against the Hermes threat patterns
The repo MUST provide a command (`make test-agents-read` -> `scripts/scan_agents_md.py`) that scans `AGENTS.md` with the same context-file threat patterns Hermes applies to context files (`scope="context"`). If any pattern matches, the command MUST exit non-zero and print the matched pattern id(s) and the matching line, so CI and the local loop turn RED instead of silently dropping the rulebook.

#### Scenario: a clean AGENTS.md passes
- **WHEN** `scripts/scan_agents_md.py` scans an `AGENTS.md` with no threat-pattern matches
- **THEN** it exits 0 and prints `AGENTS.md: CLEAN (no threat patterns)`

#### Scenario: a recurrence of the exfil_curl false positive fails closed
- **WHEN** `AGENTS.md` contains a `curl ... ${<SECRETVAR>}` line that Hermes's `exfil_curl` pattern would match
- **THEN** the scanner exits non-zero, names the `exfil_curl` pattern, and prints the offending line

### Requirement: reuse Hermes's canonical scanner when present
When a Hermes install is reachable (its `tools/threat_patterns.py` importable), the script MUST import and call that real `scan_for_threats(content, scope="context")` rather than maintain a fork. Reachability is resolved via `$HERMES_PYTHON_SRC_ROOT`, `$HERMES_PYTHON`, or a probe of the default `~/.hermes/hermes-agent` path.

#### Scenario: Hermes present on the host
- **WHEN** the script runs where `~/.hermes/hermes-agent` exists
- **THEN** it imports and uses `.hermes/hermes-agent/tools/threat_patterns.scan_for_threats`

#### Scenario: Hermes absent (self-contained CI container)
- **WHEN** no Hermes install is reachable
- **THEN** the script falls back to an INLINE copy of the same `_PATTERNS` list and still performs the same scan, exiting non-zero on any match

### Requirement: CI wiring
The scan MUST run automatically on every branch push via a parallel GitHub Actions job (`agents-read`) in `.github/workflows/ci.yml` invoking `make test-agents-read`.

#### Scenario: CI runs the guard
- **WHEN** any branch or PR pushes
- **THEN** the `agents-read` job runs `make test-agents-read` and fails (red) if the AGENTS.md scan finds a threat

### Non-goals
The command treats AGENTS.md as data: it only regex-scans the file, never executes content from it, and never modifies it.