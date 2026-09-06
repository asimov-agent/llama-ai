# Tasks — fix-top-tier-skip-summary-crash

- [x] 1. Fix `_main_download_top_tier`: unpack the real 3-tuple `(repo, filename, reason)` via
      a pure `_skip_summary_line` helper (report skips grouped by reason); empty-skip path
      stays clean.
- [x] 2. Add hermetic tests:
      - non-empty `skip_summary` (3-tuples) → `3 skipped pre-flight: 2 access-denied, 1 dead`,
        no traceback;
      - empty/None `skip_summary` → `""`.
- [ ] 3. Verify: `make lint`, `make test-unit`, `make test-top-tier`; `make openspec-validate
      NAME=fix-top-tier-skip-summary-crash`; commit + push each batch; open PR against `main`
      referencing issue #56.