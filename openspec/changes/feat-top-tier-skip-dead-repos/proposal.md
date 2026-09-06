# Verify a top-tier model is downloadable (not 403-gated/404-dead) before download, and fill the count from the next provider

## One-line summary
`--download-top-tier` lists a trending repo that is actually **gated (403 Access denied)** or has **dead files**, so its download exhausts all 3 retries, gets `SKIPPED`, and the batch finishes short — e.g. **8 of the intended 10** (5 providers × 2). The tool should **pre-flight verify** each candidate is downloadable and, when a repo is dead/denied, **advance to the next fitting provider** so the count is filled.

## The problem (why it matters)
The top-tier discovery queries the HF **listing API** (`/api/models`, `tree`) which shows a gated repo's files even when the actual object download is forbidden. So discovery ranks `orcarouter/Qwen3.8-27B-Uncensored-GGUF` as a top-tier fitting candidate, then the real `hf download` fails:

```
Error: Access denied. This repository requires approval.
httpx.HTTPStatusError: Client error '403 Forbidden' for url
  'https://huggingface.co/orcarouter/.../resolve/main/...Q8_0.gguf'
```

The batch loop retries 3×, all fail → `SKIPPED orcarouter...` → only **8 of 10** downloaded. There is no pre-flight check of whether the object is actually downloadable, and no automatic replacement, so the count the user asked for (`count × per_provider`) silently falls short.

## Current behavior
- `_trending_gguf_repos()` returns the highest-trending GGUF repos (listing API only; can include gated/dead repos).
- `discover_top_tier()` picks `count × per_provider` candidates that **fit** (size/headroom) and have a suitable quant file in the listing.
- The batch loop calls `download_top_tier_candidate()` (real `hf`, etag-aware, metadata-verified). On `rc != 0` it retries up to 3, then prints `SKIPPED <repo> after 3 failed attempts` and moves on.
- **No pre-flight check**; no "advance to next provider" refill.

## Change
1. **Pre-flight verify** each candidate is downloadable before committing the batch: download a **real chunk** (~64 KiB, ranged) of the file and verify it is actual GGUF/non-trivial binary — catching **403-gated**, **404-dead**, and **200-HTML/error shells**. This is not just a status-code check; an HTML error page served as 200 must be rejected.
2. **Advance to the next fitting provider** — after removing dead/denied repos, walk further through the trending list until `count × per_provider` valid candidates are collected.
3. Keep transient per-file retry (network blips still retried); only a pre-flight-denied repo is skipped without the heavy triple-retry.
4. Report a summary: `downloaded N/M (+S skipped: access-denied, dead)`.

## Benefits
- Honored count: 5×2 = 10 even when some trending repos are gated/dead — no more silent 8-of-10.
- Fast failure: a gated repo is dropped in one cheap chunk probe, not 3 slow failed downloads.
- Honest output: skips labeled `access-denied` / `dead`, not a bare `SKIPPED`.

## Verification
- Hermetic unit tests: mock a gated (403) + a 200-HTML repo; assert excluded pre-flight (no download) and discovery refills to `limit`; assert the probe verifies a real GGUF chunk and rejects an HTML 200 body.
- Real-HF tests (CI): public `unsloth/...` probes `ok` (fetches a real GGUF chunk → 200 auth-ok); `orcarouter/...` probes `access-denied`; a dead file probes `dead`. No mocks/skips.
- No regression: `make lint`, `make test-unit` (incl. mock-download placement), `make test-top-tier`.

## Notes
- Issue number 53; feature branch `feat/top-tier-skip-dead-repos` off `main` (`2e1cd73`, after PR #52 merges).
