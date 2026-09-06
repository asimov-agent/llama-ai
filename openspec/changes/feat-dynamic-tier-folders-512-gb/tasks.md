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
- [x] 4c. Add small tiers to the ladder (1/2/4 GB) so tiny CPU cards + small models get
      truthful folders, and add a **real-HF small-card test** (`test_real_hf_small_models_placed_in_right_tier`):
      discovery runs with the REAL HF model list on a mocked 8 GB container/CPU card — each
      real small model (0.5B/1.5B/3B/7B) is placed in its exact truthful tier + dest_path.
- [x] 4d. Add **edge-case mock-download placement** tests (`test_mock_download_places_each_model_in_right_tier_dir`,
      `test_mock_download_picks_top5_by_trend_and_places`): the REAL `discover_top_tier`
      (top-5 list mocked) + MOCK downloads place each candidate's file into the discovered
      `dest_path`, asserted as a real file in the correct tier dir for card sizes
      512/256/128/96/64/48/32/16/8/2 GB; also asserts trending-first (not file-size) selection.
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
