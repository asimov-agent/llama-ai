# Spec: DYNAMIC tier folders for `--download-top-tier` placement (issue #51)

## Why (rationale)

`--download-top-tier` offers a model only if it fits the **real** card (dynamic fit gate),
but files it under a hardcoded `TIER_LIMITS_GB = (48,24,16,8)` folder taxonomy. On a
large card (256/512 GB) every model > 48 GB is placed in a `48GB/` folder, so the `TierGB`
label contradicts the fit gate: a 400 GB model offered for a 512 GB card is filed as "48GB".
The tier label must be derived from the card it will run on, so it stays truthful at any
hardware size. This change alters only the **placement label** — the (already dynamic)
fit gate, downloader, and serve path are untouched (single code path, no fallbacks).

---

## MODIFIED Requirements

### Requirement: M1 — Tier folder derived from the actual card

WHEN a model is placed by `--download-top-tier`, THEN its `tier_folder` is the smallest
**available** bucket from the card-derived ladder that can hold it, where "available" means
buckets ≤ the card's detected/overridden total RAM.

- A growing ladder replaces the fixed list, e.g.
  `1, 2, 4, 8, 16, 24, 48, 96, 128, 192, 256, 384, 512, 768, ...` — extending **down to
  1/2/4 GB** so small CPU cards and tiny models get truthful folders too, and up past
  48 GB for big cards (a superset of the old `8/16/24/48`).
- `pick_tier_folder(size_bytes)` -> `pick_tier_folder(size_bytes, total_ram_bytes=None)`:
  available buckets = ladder entries `≤ total_ram_bytes`; chosen tier = the smallest
  available bucket `≥ size_bytes`, else the largest available bucket.
- The same `total_ram_bytes` flows through `discover_top_tier` -> `provider_dest_path` ->
  `pick_tier_folder`, so the folder label matches the gate that offered the model.

#### Scenario: small card unchanged
Given a 48 GB card, a 29 GB and 47 GB model both land in `48GB/` — identical to today.
(16/24/48 buckets; no regression.) And the new small tiers are truthful: a 0.43 GB model →
`1GB/`, a 2.5 GB model → `4GB/`, a 7 GB model → `8GB/` (not a catch-all `8GB/`).

#### Scenario: small CPU/container card gets truthful tiers
Given an 8 GB CPU/container card (mocked via `total_ram_bytes`), a real 0.5B model →
`1GB/`, a real 1.5B model → `1GB/` or `2GB/`, a real 3B/7B model → `2GB/` or `4GB/` — each
real model lands in the exact small tier that fits it (verified by a **real-HF** listing).

#### Scenario: big card gets truthful tiers
Given a 512 GB card (`LLAMA_RAM_BYTES=512GB` sim): a 60 GB model → `96GB/`, a 100 GB model →
`128GB/`, a 400 GB model → `512GB/` — and each is still **offered** (fit gate passes) and
**servable** (`scan_models()`/`llama-ai <name>`).

---

## ADDED Requirements

### Requirement: A1 — Placement verified against an assumed VRAM (full ladder sweep)

WHEN `pick_tier_folder(size_bytes, total_ram_bytes)` runs, THEN hermetic unit tests assert
the tier chosen for small + mid + very-large sizes across **every ladder card size** — not
just 48/512 GB — so the dynamic-tier behaviour is proven for any hardware without a real card.

- A **parameterized sweep** drives `pick_tier_folder` (and the full `provider_dest_path`
  **dest_path**) for a representative set of model sizes over **every** card size in
  `TIER_LADDER_GB`, asserting each mocked model lands in the **smallest available bucket ≥ its
  size** (i.e. the folder for the card it fits).
- A **fit-gate ⇄ placement agreement** test asserts, on the **same assumed VRAM**, that a
  model which passes `size + headroom + KV <= total` IS offered AND typed to a fitting
  tier, while a model that can't fit is **not offered at all**.

#### Scenario: parameterised cases
`pick_tier_folder(29GB, 48GB)=="48GB"`, `pick_tier_folder(60GB, 48GB)=="48GB"`,
`pick_tier_folder(60GB, 512GB)=="96GB"`, `pick_tier_folder(400GB, 48GB)=="48GB"` (largest
available bucket — a non-fitting model isn't offered anyway),
`pick_tier_folder(400GB, 512GB)=="512GB"` (never `48GB/`). Plus the full ladder sweep and
the fit-gate/placement agreement above.

#### Scenario: real HF model list, mocked small card (the CI case)
`--download-top-tier` discovery runs with the **real HF trending model list** against a
**mocked small 8 GB container/CPU card**: each real small model (0.5B/1.5B/3B/7B) is placed
in its exact truthful small tier (1/2/4/8 GB) and its `dest_path` embeds that same folder.
This is how the CI pipeline proves small-card placement end-to-end.

#### Scenario: edge-case mock download across card sizes
The **real `discover_top_tier`** (top-5 model list mocked) + **mock downloads** place each
candidate into its discovered `dest_path`, asserted as a real file in the correct tier dir,
for **card sizes 512/256/128/96/64/48/32/16/8/2 GB** — covering big, medium, and tiny edge
cases without any network. Also asserted: the top-5 are picked **by trending** (not file
size) and each lands in the folder for the card it fits.

### Requirement: A2 — Dynamic-tier tests run in the CI pipeline

WHEN the CI `unit` job runs, THEN it executes the full `tests/test_llama_ai.py` suite (which
includes the VRAM-parameterized placement tests) and `make test-top-tier` (acceptance incl.
the real-HF small-card placement test + real-CLI), so the placement guarantee is
continuously verified, not just locally.

#### Scenario: no skips, always run
The `unit` job runs `make test-unit` (the full hermetic suite incl. the placement sweep +
lint-regression + openspec-tasks-check) and `make test-top-tier-ci`; no placement test is
skipped under any runner RAM (they pass an explicit `total_ram_bytes`).

---

## EXISTING Requirements (unchanged)

### Requirement: E1 — Dynamic fit gate preserved
WHEN eligibility is computed, THEN it still reads the real card
(`$LLAMA_RAM_BYTES` → `sysctl hw.memsize` / `/proc/meminfo`) with
`size_bytes + headroom + KV_reserve <= read_total_ram()`. This change does not alter eligibility.

### Requirement: E2 — Serving finds a model by tier folder
WHEN `scan_models()` / `llama-ai <name>` run, THEN they find and serve a model regardless of
its `TierGB` folder name.
