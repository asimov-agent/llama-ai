# Tasks — fix-top-tier-skip-summary-crash

- [x] 1. Fix `_main_download_top_tier`: unpack the real 3-tuple `(repo, filename, reason)` via
      a pure `_skip_summary_line` helper (report skips grouped by reason); empty-skip path
      stays clean.
- [x] 2. Add hermetic tests:
      - non-empty `skip_summary` (3-tuples) → `3 skipped pre-flight: 2 access-denied, 1 dead`,
        no traceback;
      - empty/None `skip_summary` → `""`.
- [x] 3. Verify: `make lint`, `make test-unit`, `make test-top-tier`; `make openspec-validate
      NAME=fix-top-tier-skip-summary-crash`; commit + push each batch; open PR against `main`
      referencing issue #56.
- [x] 4. Rewrite the spec scenarios in strict **Given / When / Then / And** block format
      (separate lines per step, not inline) per AGENTS.md.
- [x] 5. Add the durable AGENTS.md rule: every spec scenario MUST have Given / When / Then,
      and every scenario implies a matching test wired into the Makefile/CI gate.
- [x] 6. Require (AGENTS.md) + apply: each Python acceptance/behavior test's docstring mirrors
      its spec scenario with the same `Given / When / Then` lines; added G/W/T docstrings to
      the 2 summary tests.
