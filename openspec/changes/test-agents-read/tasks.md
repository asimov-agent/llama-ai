# test-agents-read — Tasks

Checklist of record. Each task ticked the moment verified.

## Scanner (reuse the REAL Hermes module)

- [x] 1.1 Add `scripts/scan_agents_md.py`: imports installed Hermes `scan_for_threats(content, scope="context")` when reachable (`$HERMES_PYTHON_SRC_ROOT` / `$HERMES_PYTHON` / `~/.hermes/hermes-agent`); otherwise imports the vendored canonical `scripts/hermes/threat_patterns.py`. Fail-closed: exit non-zero + prints pattern + offending line on any match.
- [x] 1.2 Vendor `scripts/hermes/threat_patterns.py` (verbatim copy of Hermes `tools/threat_patterns.py`, stdlib-only). Rationale: Hermes forbids pip install (Nix-only), so the exact real module is vendored rather than reimplemented.
- [x] 1.3 Host verify: clean AGENTS.md -> `rc=0`; injected `curl ... ${GITHUB_TOKEN}` line -> `rc=1`, names `exfil_curl`.

## Makefile + loop + CI

- [x] 1.4 Add `make test-agents-read` target (`$(TEST_RUN) python scripts/scan_agents_md.py AGENTS.md`).
- [x] 1.5 Chain `agents-read` stage into `scripts/loop_harness.py` STAGES (after lint).
- [x] 1.6 Add `test-agents-read` to Makefile `chained` target.
- [x] 1.7 Add `agents-read` job to `.github/workflows/ci.yml` (parallel, runs `make test-agents-read`).

## Verification (final)

- [ ] 2.1 `make test-agents-read` exits 0 on current AGENTS.md (host and in-container).
- [ ] 2.2 Scanner fails closed on a malicious AGENTS.md (verified).
- [ ] 2.3 `make lint` and `make openspec-validate NAME=test-agents-read` pass.
- [ ] 2.4 Open a PR via normal loop flow (OpenSpec change first).