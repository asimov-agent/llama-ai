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
  `8, 16, 24, 48, 96, 128, 192, 256, 384, 512, 768, ...` (a superset of the old `8/16/24/48`).
- `pick_tier_folder(size_bytes)` -> `pick_tier_folder(size_bytes, total_ram_bytes=None)`:
  available buckets = ladder entries `≤ total_ram_bytes`; chosen tier = the smallest
  available bucket `≥ size_bytes`, else the largest available bucket.
- The same `total_ram_bytes` flows through `discover_top_tier` -> `provider_dest_path` ->
  `pick_tier_folder`, so the folder label matches the gate that offered the model.

#### Scenario: small card unchanged
Given a 48 GB card, a 29 GB and 47 GB model both land in `48GB/` — identical to today.
(8/16/24/48 buckets; no regression.)

#### Scenario: big card gets truthful tiers
Given a 512 GB card (`LLAMA_RAM_BYTES=512GB` sim): a 60 GB model → `96GB/`, a 100 GB model →
`128GB/`, a 400 GB model → `512GB/` — and each is still **offered** (fit gate passes) and
**servable** (`scan_models()`/`llama-ai <name>`).

---

## ADDED Requirements

### Requirement: A1 — Unit-tested across hardware sizes

WHEN `pick_tier_folder(size_bytes, total_ram_bytes)` runs, THEN hermetic unit tests assert
the tier chosen for small + mid + very-large sizes at **at least** the 48 GB and 512 GB card
sizes, so the dynamic-tier behaviour is covered without a real big card.

#### Scenario: parameterised cases
`pick_tier_folder(29GB, 48GB)=="48GB"`, `pick_tier_folder(60GB, 48GB)=="48GB"`,
`pick_tier_folder(60GB, 512GB)=="96GB"`, `pick_tier_folder(400GB, 512GB)=="512GB"`,
`pick_tier_folder(400GB, 512*2^30)=="512GB"` (never `48GB/`).

---

## EXISTING Requirements (unchanged)

### Requirement: E1 — Dynamic fit gate preserved
WHEN eligibility is computed, THEN it still reads the real card
(`$LLAMA_RAM_BYTES` → `sysctl hw.memsize` / `/proc/meminfo`) with
`size_bytes + headroom + KV_reserve <= read_total_ram()`. This change does not alter eligibility.

### Requirement: E2 — Serving finds a model by tier folder
WHEN `scan_models()` / `llama-ai <name>` run, THEN they find and serve a model regardless of
its `TierGB` folder name.