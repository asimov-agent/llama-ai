# Tasks — fix-download-stall-watch (issue #55)

- [x] 1. Write OpenSpec proposal.md + specs/llama-ai-tooling/spec.md (Given/When/Then scenarios)
      + tasks.md; validate via `make openspec-validate NAME=fix-download-stall-watch`; tick.
- [ ] 2. Implement the real stall-watch in `scripts/hf_download.py`:
      - add `HF_STALL_SECONDS` env (default 90);
      - track `last_advancing` time (update only when `tree_bytes(dest)` grows);
      - if a still-alive `proc` exceeds the threshold with no growth → kill it and
        `write_log("STALLED → terminating & retrying attempt N")`, then let retry advance;
      - remove the dead `if total == last_bytes: pass` + corrupting `last_bytes = total`.
- [ ] 3. Add hermetic tests (no skips) to `tests/`:
      - A1: no-growth subprocess killed + attempt increments + `STALLED` logged;
      - A2: growing subprocess never killed (negative guard);
      - A3: persistent stalls exhaust `MAX_RETRY` → `SKIPPED (stall)`.
      Wire each test with the Given/When/Then code-block markers.
- [ ] 4. Verify: `make lint`, `make test-unit`; `make test-top-tier` (container);


      `make openspec-validate NAME=fix-download-stall-watch`; commit + push each batch; open PR
      against `main` referencing issue #55 (Closes #55 in PR body so it auto-closes).
