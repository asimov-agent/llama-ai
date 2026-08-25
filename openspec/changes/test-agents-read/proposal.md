# test-agents-read — guard the AGENTS.md rulebook loader

## Why

The repo's `AGENTS.md` was silently BLOCKED from entering spawned workers'
system prompts (incident, fixed in PR #38). Root cause: the repo's own GitHub
workflow examples did `curl -H "Authorization: Bearer ${GITHUB_TOKEN}" ...`,
which Hermes's context-file threat scanner flags as exfiltration (`exfil_curl`)
and blocks wholesale.

The rulebook-loading invariant was only verified manually (a one-off
`scan_for_threats(AGENTS.md, scope="context")` on the dev host). There is no
automated, CI-enforced guard that turns RED if `AGENTS.md` (or `.cursorrules`,
`CLAUDE.md`, `SOUL.md`) ever matches a threat pattern again.

## What Changes

- Add `scripts/scan_agents_md.py` — a small fail-closed scanner that reuses
  Hermes's canonical `tools.threat_patterns.scan_for_threats(content,
  scope="context")` when a Hermes install is reachable (via
  `$HERMES_PYTHON_SRC_ROOT` / `$HERMES_PYTHON` / a probe of the default
  `~/.hermes/hermes-agent` path). If no Hermes install is present (e.g. the
  self-contained CI test container), it falls back to an INLINE copy of the
  same `_PATTERNS` list so CI still runs the genuine guard with no Hermes
  dependency. Never re-implements detection by hand beyond copying the
  authoritative regex list.
- Add `make test-agents-read` — runs the scanner against `AGENTS.md`
  (fail-closed: exits non-zero if any threat matches, so CI turns red).
- Add a CI job `agents-read` in `.github/workflows/ci.yml` (parallel, runs
  `make test-agents-read`).

## Capabilities / Contract

- Fail-closed: any threat match in `AGENTS.md` -> non-zero exit, names the
  pattern + the offending line.
- Reuse-not-reinvent: where Hermes is present, import its real scanner.

## Tasks

- [ ] 1.1 Add `scripts/scan_agents_md.py` (import Hermes scanner when available;
      inline `_PATTERNS` fallback; scan AGENTS.md; fail closed)
- [ ] 1.2 Add `make test-agents-read` target calling the script
- [ ] 1.3 Add `agents-read` job to `.github/workflows/ci.yml`
- [ ] 1.4 Verify locally: `make test-agents-read` exits 0 on current AGENTS.md
- [ ] 1.5 Open a PR via the normal loop flow

## Note

The scanner treats `AGENTS.md` as data. It does not execute anything in
the file; it only regex-scans it.

The guard reuses Hermes's CANONICAL scanner. Hermes **forbids** `pip install
hermes-agent` (its build raises `RuntimeError: Building wheels or sdists for
hermes-agent is not supported` — it is Nix/uv2nix only), so we cannot pip the
package into the CI image. Instead `scripts/scan_agents_md.py`:
  1. imports the installed Hermes module when present (host, via
     `$HERMES_PYTHON_SRC_ROOT` / `$HERMES_PYTHON` / `~/.hermes/hermes-agent`),
     and
  2. otherwise imports the VENDORED canonical copy at
     `scripts/hermes/threat_patterns.py` — a verbatim copy of the
     authoritative stdlib-only module (`re`, `unicodedata`, `typing`), so the
     exact same detection runs in any container with zero install steps.

This is reuse, not reimplementation: the pattern list and scan logic are the
real Hermes code, never re-derived by hand.