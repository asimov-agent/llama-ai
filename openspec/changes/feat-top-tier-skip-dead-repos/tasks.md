# Tasks — feat-top-tier-skip-dead-repos

- [x] 1. OpenSpec change scaffold (proposal.md + specs/llama-ai-tooling/spec.md + tasks.md) —
      VALID — committed + pushed to `feat/top-tier-skip-dead-repos` before implementation.
- [x] 2. Add a **pre-flight downloadability probe** `_probe_file_downloadable(repo, filename)`
      that fetches a real ~64 KiB chunk (ranged) and classifies a candidate as
      `ok` / `access-denied` (401/403) / `dead` (404) / None (transient), rejecting a
      200-HTML/error shell.
- [x] 3. In `discover_top_tier`, run the probe on each candidate's file, **exclude** any that
      fail, and log `[top-tier] skipping <repo>::<file>: <reason>` (no 3× retry).
- [x] 4. **Refill**: when repos are gated/dead, keep walking the trending list (widening the
      window) until `limit` valid candidates are collected.
- [x] 5. Add a **completion summary** `downloaded N/M (+S skipped: access-denied, dead)`.
- [x] 6. Add hermetic unit tests:
      - a gated repo (probe → access-denied) is excluded pre-flight and NOT downloaded;
      - a 200-HTML shell (probe → None) is excluded;
      - discovery refills to `limit` from the next provider when some are gated/dead;
      - the probe verifies a real GGUF chunk and rejects an HTML/error 200 body.
- [x] 7. Add real-HF tests: `unsloth/...` probes `ok` (real GGUF chunk → 200 auth-ok),
      `orcarouter/...` probes `access-denied`, a dead file probes `dead` — no mocks/skips —
      wired into `make test-top-tier-ci` (CI top-tier job).
- [ ] 8. Verify: `make lint`, `make test-unit`, `make test-top-tier`, `make openspec-validate
      NAME=feat-top-tier-skip-dead-repos`; commit + push each batch; open PR against `main`
      referencing issue #53.
