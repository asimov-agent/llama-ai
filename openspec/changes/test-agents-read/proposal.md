# test-agents-read — proposal

Guard AGENTS.md against Hermes context-file threat-pattern blocking.

## Why

The repo's `AGENTS.md` was silently BLOCKED from entering spawned workers'
system prompts (incident, fixed in PR #38): a `curl -H "Authorization: Bearer
${GITHUB_TOKEN}"` line matched Hermes's `exfil_curl` context-file threat
pattern, and the loop ran "successfully" without its rulebook. There was no
automated guard — only a manual `scan_for_threats(AGENTS.md)` on the dev host.

## What Changes

- Add `scripts/scan_agents_md.py` — a fail-closed scanner importing Hermes's
  CANONICAL `tools.threat_patterns.scan_for_threats(content, scope="context")`.
  Exits non-zero + names the pattern + offending line on any match.
- Add a standalone `agents-read` CI job (python:3.12) that installs
  `hermes-agent==0.19.0` (a real PyPI dependency), runs the scanner, and runs
  the guard's unit-test corpus.
- Add `make test-agents-read` (host-side) and chain it into the loop harness.

## Why standalone job (not the test image, not the shared lockfile)

`hermes-agent` requires Python >=3.11, but the project's test image is
`python:3.10`. Adding it to the shared `tools/requirements-dev.txt` breaks the
3.10 image build (`certifi` pins conflict with `requirements.txt`). So
`hermes-agent` is installed ONLY by the standalone `agents-read` job's own
`python:3.12` container, keeping the 3.10 test image and its lockfile intact.
`hermes-agent` is a genuine PyPI dependency of the guard, declared inline in
the CI job and the Makefile target's install guidance.

## Capabilities / Contract

- Fail-closed: any threat match in `AGENTS.md` -> non-zero exit, names pattern.
- Reuse: `hermes-agent` is a genuine dependency; `tools.threat_patterns` is
  imported from installed site-packages, never copied.
- Edge-case corpus: unit tests cover legitimate AGENTS.md + threat variants
  (exfil curl/wget, prompt-injection, role-hijack, invisible unicode, etc.).

## Notes

The scanner treats AGENTS.md as data: it regex-scans, never executes.
