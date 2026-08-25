# test-agents-read — Tasks

Checklist of record. Each task ticked the moment verified.

## Scanner script (reuse the real Hermes module)

- [x] 1.1 `scripts/scan_agents_md.py` imports the installed `tools.threat_patterns.scan_for_threats(content, scope="context")` (Hermes's canonical scanner); exits non-zero + names pattern on any match; clean error when hermes-agent not installed.
- [x] 1.2 Verified: clean AGENTS.md -> `rc=0`; injected `curl ... ${GITHUB_TOKEN}` -> `rc=1`, names `exfil_curl`.

## CI (standalone job, keeps 3.10 test image intact)

- [x] 1.3 Standalone `agents-read` CI job (`python:3.12-slim`) installs `hermes-agent==0.19.0` (real PyPI dep) + pytest, scans AGENTS.md, runs the corpus.
- [x] 1.4 NOT added to shared `tools/requirements-dev.txt` — adding hermes (requires Python>=3.11) breaks the 3.10 test image build (certifi conflict). It is installed only by the standalone job.

## Makefile + loop

- [x] 1.5 `make test-agents-read` host-side target (uses a Python >=3.11 with hermes-agent; clear error if absent).
- [x] 1.6 `agents-read` stage added to `scripts/loop_harness.py` STAGES.
- [x] 1.7 `test-agents-read` added to Makefile `chained` target.

## Tests (edge cases + permutations)

- [x] 1.8 `tests/test_agents_read.py` corpus: pass-fixtures (current AGENTS.md, empty, legit curl-auth-var, prose mentioning token, normal rulebook) + fail-fixtures (exfil curl/wget, prompt-injection x2, role-hijack, invisible unicode, secret reads, anti-forensic).
- [x] 1.9 Fail-closed + clean subprocess exit-code tests.
- [x] 1.10 Test asserts module imported from site-packages (not a repo copy).

## Verification (final)

- [x] 2.1 `python:3.12` container: `pip install hermes-agent==0.19.0` then `python scripts/scan_agents_md.py AGENTS.md` -> CLEAN rc=0.
- [x] 2.2 `python -m pytest tests/test_agents_read.py --noconftest` in python:3.12 container -> 17 passed.
- [x] 2.3 `make lint` passes; `make openspec-validate NAME=test-agents-read` passes.
- [x] 2.4 Test image still builds (3.10) — no certifi conflict, since hermes not in shared lockfile.
- [ ] 2.5 Rebase branch onto latest origin/main, force-push, confirm agents-read + existing CI pass.
