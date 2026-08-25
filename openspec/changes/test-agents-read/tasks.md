# test-agents-read — Tasks

Checklist of record. Each task ticked the moment verified.

## Dependency (real 3rd-party, not vendored)

- [x] 1.1 Declare `hermes-agent==0.19.0` in `tools/requirements-dev.in`.
- [x] 1.2 Compile `tools/requirements-dev.txt` (pip-compile, Python 3.12) including hermes-agent + transitive deps.
- [x] 1.3 Verify `hermes-agent==0.19.0` installs on Python 3.12 and `tools.threat_patterns.scan_for_threats` is importable from site-packages.
- [x] 1.4 REMOVED all vendored copy (`scripts/hermes/`) and the standalone reimplementation.

## Scanner script

- [x] 1.5 `scripts/scan_agents_md.py` imports the installed `tools.threat_patterns.scan_for_threats(content, scope="context")`; exits non-zero + names pattern on any match; clean error when hermes-agent not installed.
- [x] 1.6 Host/container verify: clean AGENTS.md -> `rc=0`; injected `curl ... ${GITHUB_TOKEN}` -> `rc=1`, names `exfil_curl`.

## Makefile + CI

- [x] 1.7 `make test-agents-read` host-side target (uses Python >=3.11 with hermes-agent; clear error if absent).
- [x] 1.8 `agents-read` stage added to `scripts/loop_harness.py` STAGES.
- [x] 1.9 `test-agents-read` added to Makefile `chained` target.
- [x] 1.10 Standalone `agents-read` CI job (`python:3.12-slim`) installs hermes-agent, scans AGENTS.md, runs the test corpus.

## Tests (edge cases + permutations)

- [x] 1.11 `tests/test_agents_read.py` corpus: pass-fixtures (current AGENTS.md, empty, legit curl-auth-var, prose, normal rulebook) + fail-fixtures (exfil curl/wget, prompt-injection x2, role-hijack, invisible unicode, secret reads, anti-forensic).
- [x] 1.12 Fail-closed + clean subprocess exit-code tests.
- [x] 1.13 Test asserts module imported from site-packages (not a repo copy).

## Verification (final)

- [x] 2.1 `python:3.12` container: `pip install hermes-agent==0.19.0` then `python scripts/scan_agents_md.py AGENTS.md` -> CLEAN rc=0.
- [x] 2.2 `python -m pytest tests/test_agents_read.py --noconftest` in python:3.12 container -> 17 passed.
- [x] 2.3 `make lint` passes; `make openspec-validate NAME=test-agents-read` passes.
- [ ] 2.4 Rebase branch onto latest origin/main, force-push, reply to PR review comment.
