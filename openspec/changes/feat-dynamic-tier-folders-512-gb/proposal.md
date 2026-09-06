# Dynamic tier folders for the `--download-top-tier` placement (issue #51)

## Problem

`--download-top-tier` picks a model by whether it **fits the real card** (the fit gate
reads `read_total_ram_bytes()`, so a 400 GB model is offered on a 512 GB card), but it
**files the download under a hardcoded `TIER_LIMITS_GB = (48,24,16,8)` taxonomy**. Any
model bigger than 48 GB lands in a `48GB/` folder:

```
60 GB  -> 48GB/    100 GB -> 48GB/   256 GB -> 48GB/   400 GB -> 48GB/
```

The `TierGB` folder is meant to say "which card runs this model". A hardcoded cap of 48
makes that label **lie** for anyone with a big card: a `48GB/` folder on a 400 GB model
invites copying it to a 48 GB machine where it OOMs; different-sized big models collide
in one folder; and the folder contradicts the very fit gate that offered the model.

## What already works (do not regress)

- The **fit gate is dynamic** — eligibility is decided by the real card, and
  `discover_top_tier(..., total_ram_bytes=..., headroom_bytes=...)` is unit-testable.
- `scan_models()` / `llama-ai <name>` serve a model regardless of its folder tier.

## Change

Make `pick_tier_folder` derive the tier from the card it will run on:

1. Introduce a growing **tier ladder** (bounded by the current card), e.g.
   `1, 2, 4, 8, 16, 24, 48, 96, 128, 192, 256, 384, 512, 768, ...` — a superset that extends
   **down to 1/2/4 GB** (truthful folders for small CPU cards and tiny models) and adds large
   tiers past 48 for big cards.
2. `pick_tier_folder(size_bytes)` -> `pick_tier_folder(size_bytes, total_ram_bytes=None)`:
   the buckets available on a machine = ladder entries **≤ the card's detected/overridden
   total**; the model's tier = the **smallest available bucket ≥ its size**, else the
   largest bucket. A 48 GB card keeps exactly `8/16/24/48`; a 512 GB card adds `96...512`.
3. Pass the same `total` through `discover_top_tier` -> `provider_dest_path` ->
   `pick_tier_folder`, so the folder label matches the gate that offered the model.
4. `TIER_LIMITS_GB` is replaced by the ladder (the folded-in unit tests keep the
   `--download-top-tier` behavior honest).

Behavior ladder (unchanged on small cards):

| card | model | tier folder (was) | tier folder (now) |
|---|---|---|---|
| 48 GB | 29 GB | `48GB/` | `48GB/` (unchanged) |
| 48 GB | 47 GB | `48GB/` | `48GB/` (unchanged) |
| 512 GB | 60 GB | `48GB/` | `96GB/` |
| 512 GB | 100 GB | `48GB/` | `128GB/` |
| 512 GB | 400 GB | `48GB/` | `512GB/` |

## Benefits

- **Truthful, self-describing folders**: `TierGB` = the real card size a model needs.
- **Consistent with the fit gate**: folder label and eligibility agree.
- **Clean organization for big cards**: large models stop colliding in `48GB/`.
- **Backward compatible**: `8/16/24/48` cards see zero change.
- **Future-proof**: growing cards get growing tiers with no code change.

## Open question (resolved by this change)

Folder semantics = **the card that runs it, bounded by this machine** (matches the fit
gate), not an unbounded per-model "smallest card anywhere".

## Verification

- Unit tests drive `pick_tier_folder(size, total_ram)` across small + mid + very large
  sizes and **every** `TIER_LADDER_GB` card size (full VRAM-parameterized sweep via mocked
  VRAM) — each mocked model lands in the folder for the card it fits; the full
  `provider_dest_path` `dest_path` is asserted too. Includes the down-extended small tiers
  (1/2/4 GB on tiny CPU cards).
- A **fit-gate ⇄ placement agreement** test proves, on the same assumed VRAM, a model that
  fits IS offered + correctly tiered and one that can't fit is NOT offered.
- A **real-HF small-card test**: discovery runs with the REAL HF trending model list
  (0.5B/1.5B/3B/7B) against a mocked 8 GB container/CPU card — each real model is placed in
  its exact truthful small tier and `dest_path`; the HF CLI list is real, the card is mocked.
- Acceptance: on a 512 GB sim (`LLAMA_RAM_BYTES`), a large model lands in a non-`48GB`
  tier and is still offered; `--list`/`scan_models()`/serve still find it.
- **CI**: `make test-unit` (includes the placement sweep in `tests/test_llama_ai.py`) and
  `make test-top-tier-ci` (acceptance incl. real-HF small-card + real download) both run in
  the pipeline — no skips, explicit `total_ram_bytes` so runner RAM never skips them.
- `make lint`, `make test-unit`, `make test-top-tier` GREEN.
- Issue number 51; this is a spec-tracked OpenSpec change with `proposal.md` +
  `specs/.../spec.md` + `tasks.md`, all committed and pushed to the feature branch.
