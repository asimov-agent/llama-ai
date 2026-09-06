# Tasks — feat-dynamic-tier-folders-512-gb

- [x] 1. Introduce a growing tier ladder (e.g. `8,16,24,48,96,128,192,256,384,512,768,...`)
      replacing the hardcoded `TIER_LIMITS_GB = (48,24,16,8)`.
- [x] 2. Change `pick_tier_folder(size_bytes)` -> `pick_tier_folder(size_bytes, total_ram_bytes=None)`:
      available buckets = ladder entries ≤ total; chosen = smallest available ≥ size, else largest.
- [x] 3. Thread `total_ram_bytes` through `discover_top_tier` -> `provider_dest_path` ->
      `pick_tier_folder` so the folder label matches the fit gate.
- [x] 4. Add hermetic unit tests for `pick_tier_folder` across small/mid/very-large sizes at
      48 GB and 512 GB card sizes (incl. `pick_tier_folder(400GB, 512GB)=="512GB"`, never `48GB/`).
- [x] 4a. Add a **full VRAM-parameterized placement sweep**: drive `pick_tier_folder` AND the
      full `provider_dest_path` **dest_path** for representative model sizes over **every**
      `TIER_LADDER_GB` card size, asserting each mocked model lands in the smallest
      available bucket ≥ its size (the folder for the card it fits).
- [x] 4b. Add a **fit-gate ⇄ placement agreement** test on the same assumed VRAM: a model
      passing `size+headroom+KV <= total` IS offered + typed to a fitting tier; a model
      that can't fit is NOT offered at all.
- [x] 5. Add/extend a top-tier acceptance test on a big-card sim (`LLAMA_RAM_BYTES=512GB`) proving
      a large model is offered, placed in a non-`48GB` tier, and still served/listed.
- [x] 6. Ensure the dynamic-tier placement tests run in the **CI pipeline** (`make test-unit`
      includes `tests/test_llama_ai.py`; `make test-top-tier-ci` runs acceptance) — no skips,
      explicit `total_ram_bytes` so runner RAM never skips them.
- [x] 7. Update README (tier-folder layout + growth past 48 GB + the placement tests) and keep the
      issue (#51) body, OpenSpec proposal/spec/tasks, and README aligned (AGENTS.md sync-check).
- [x] 8. Verify: `make lint`, `make test-unit` (incl. the new pick_tier_folder + placement tests), and
      `make openspec-validate NAME=feat-dynamic-tier-folders-512-gb` all pass; commit + push
      the feature branch; open PR against `main` referencing issue #51.
