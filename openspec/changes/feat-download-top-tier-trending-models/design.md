# Design: trending + top-tier + GPU-fitting discovery (verified against live HF API)

This design doc records the **empirically verified** answer to "which top-tier GGUF
models are trending now, and which fit a 48 GB unified-memory card" — captured from
live Hugging Face API calls during the design phase (2026-09-05). The implementation
must query HF at runtime (never hardcode this snapshot), but this validates the
signal chain.

## 1. Trending signal — HF `trendingScore` is the right primary sort

Verified live:

```
GET /api/models?sort=trendingScore&direction=-1&limit=N
```

returns, per model, `id`, `downloads`, `likes`, `trendingScore`, `lastModified`,
`library_name`, `pipeline_tag`, `tags`. This is a **time-weighted** popularity score
(not a lifetime download count), which is exactly the "trending *right now*" signal we
need. It does NOT require an auth token for public models.

Filtering to GGUF-only is done the same way:

```
GET /api/models?sort=trendingScore&direction=-1&filter=gguf&limit=N
```

`library_name` is also `"gguf"` on GGUF quants, which is a second, independent filter.
(Note: `filter=gguf` matches the `library_name` tag; some repos tag only `gguf`+`gsq`
etc. — filter on both `library_name == "gguf"` and the `gguf` tag to be safe.)

**Recommendation:** primary sort = `trendingScore`, direction=-1, filter to models
whose `library_name`/tags include `gguf`. Use `huggingface_hub`:
`HfApi().list_models(sort="trendingScore", direction=-1, filter=("gguf",))`.

## 2. Per-file sizes — repo tree API

Verified live (all sizes in GB, from `GET /api/models/<repo>/tree/main` → `size`):

```
GET /api/models/<repo>/tree/main            # flat
GET /api/models/<repo>/tree/main?recursive=true   # nested (GLM uses subfolders)
```

Each entry has `path` + `size` (bytes). For nested repos (e.g. `unsloth/GLM-5.3-Flash-GGUF`
uses `Q8_0/...` subfolders) `recursive=true` is required. Sizes are real file sizes, the
input to the fit-buffer gate.

## 3. Verified trending top-tier landscape (2026-09-05)

### Ranked GGUF-trending (live `trendingScore`, filter=gguf)

| rank | repo | dl | likes | trend | fits 48 GB? |
|---|---|---|---|---|---|
| 1 | ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF | 297k | 354 | 320 | yes |
| 2 | unsloth/Qwen3.8-27B-GGUF | 10.2M | 3526 | 284 | yes |
| 3 | unsloth/Qwen3.8-Flash-Next-GGUF | 781k | 793 | 230 | check |
| 4 | DavidAU/Qwen3.8-27B-...-MTP-GGUF | 174k | 195 | 185 | yes |
| 5 | HauhauCS/Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP-GGUF | 1.5M | 954 | 184 | yes |
| 6 | OBLITERATUS/Qwen3.8-27B-OBLITERATED | 969k | 1092 | 156 | yes |
| 7 | orcarouter/Qwen3.8-27B-Uncensored-GGUF | 284k | 722 | 123 | yes |
| 8 | orcarouter/Qwen3.8-Flash-Next-Uncensored-GGUF | 107k | 237 | 120 | check |
| 9 | JonathanColetti/Qwen3.8-27B-Uncensored-GGUF | 2.45M | 979 | 116 | yes |
| 10 | peculiar-ragdoll/Tiel-Coder-35B-A3B-GGUF | 226k | 219 | 104 | yes |
| 11 | Jackrong/Qwopus3.8-27B-Flash-GGUF | 11k | 103 | 102 | check |
| 12 | unsloth/GLM-5.3-Flash-GGUF | 91k | 367 | 101 | **no** (~400 GB) |

**Key finding:** the unqualified "top tier / trending GGUF" landscape is dominated by
**Qwen3.8-27B** and its derivates. That's not a small-tier model — it's the LG-27B
flagship, and it **fits a 48 GB card at nearly every quant**.

### The other "big specs that trend" do NOT fit 48 GB (important negative result)

- `unsloth/GLM-5.3-Flash-GGUF` is **~400 GB** (BF16 14 × ~49 GB shards, or Q8_0 8 shards).
- `unsloth/DeepSeek-V4-Flash-0731-GGUF` is **86–164 GB** (MoE).
- `huihui-ai/Huihui-DeepSeek-V4-Flash-0731-abliterated-GGUF` similar.

So a naive "just grab whatever is trending" would pick models that **cannot load on
48 GB**. This is exactly why the **fit + buffer gate is mandatory**, not optional.

### Verified Qwen3.8-27B quant sizes (`unsloth/Qwen3.8-27B-GGUF`) + 48 GB fit math

Launcher constants: `TOTAL_RAM_BYTES = 48 GB`, `OS_OVERHEAD = 3 GB`. "fits" = the model
leaves ≥ 1 GB of KV allowance (`48 − 3 − size_bytes = kv_alloc`).

| quant (file) | size | kv_alloc | verdict |
|---|---|---|---|
| Q4_0 | 16.06 | 28.9 | FITS |
| Q4_K_M | 16.46 | 28.5 | FITS |
| Q5_K_M | 19.77 | 25.2 | FITS |
| Q5_K_XL | 20.88 | 24.1 | FITS |
| Q6_K | 21.98 | 23.0 | FITS |
| Q6_K_L | 24.19 | 20.8 | FITS |
| Q6_K_XL | 25.30 | 19.7 | FITS |
| Q8_0 | 29.05 | 15.9 | FITS |
| Q8_K_L | 28.05 | 16.9 | FITS |
| Q8_K_XL | 31.46 | 13.5 | FITS |

**Conclusion:** `Qwen3.8-27B-Q8_0.gguf` (29.05 GB, ≈15.9 GB KV headroom) is the "top
tier + fits-with-buffer" sweet spot for the user's 48 GB card. Unsloth and qwen variants
use the same family; the quant selector should prefer `Q8_0`/`Q8_K_L`/`Q6_K_XL` for max
quality that still leaves KV room.

## 4. Fit + buffer gate (as implemented in this change)

Reuse the launcher's existing constants/functions so there is ONE fit implementation:

```
kv_alloc = TOTAL_RAM_BYTES - OS_OVERHEAD - size_bytes           # size from HF tree API
accept        iff kv_alloc >= tuned_context() * kv_bytes_per_token()
                             (or, simpler, kv_alloc >= KV_MIN_ALLOC = 1 GB)
```

The block-buffer margin is the gap between the accepted model's `kv_alloc` and what
`tuned_context()` actually needs — i.e. "downloaded yet still runs" is guaranteed by
reusing `kv_bytes_per_token()` + `tuned_context()` on the *predicted* size before
download.

## 5. Example `hf` download commands (verified repo_ids + exact filenames)

```bash
# Top-tier trending for 48 GB — Qwen3.8-27B @ Q8_0 (great quality + KV buffer)
hf download unsloth/Qwen3.8-27B-GGUF Qwen3.8-27B-Q8_0.gguf --local-dir ~/models/Qwen/48GB
# Same family, higher-quality binned quant:
hf download unsloth/Qwen3.8-27B-GGUF Qwen3.8-27B-UD-Q8_K_XL.gguf --local-dir ~/models/Qwen/48GB
# Uncensored trending variant (OBLITERATUS)
hf download OBLITERATUS/Qwen3.8-27B-OBLITERATED Qwen3.8-27B-OBLITERATED-Q8_0.gguf --local-dir ~/models/Qwen/48GB
```

All `hf download` invocations should go through `scripts/hf_download.py` (resume/retry,
`HF_HUB_ENABLE_HF_TRANSFER=1`, token from `~/.zshrc`) per the repo's one-code-path rule.

## 6. Runtime, not static

The shortlist above is the *validation snapshot*. Production `--download-top-tier`
queries HF at runtime (trendingScore → filter gguf → per-file sizes → fit gate), so it
stays current without code changes.
