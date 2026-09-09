# Spec: `--download-top-tier --family <keyword>` — top 5 providers of ONE model family (issue #61)

## Why
`--download-top-tier` ranks providers across ALL families from the trending window; a
niche family (e.g. ornith) never surfaces, and there is no way to ask for the best
providers of a single family. This adds `--family <keyword>` as a filter into the SAME
top-tier pipeline — no second code path.

---

## ADDED Requirements

### Requirement: F1 — Family keyword matches repos on a word boundary
WHEN `--download-top-tier --family <keyword>` is used,
THEN the family repo list contains only repos whose repo id matches the keyword on a
**word boundary** (case-insensitive; `(?<![a-z0-9])<kw>(?![a-z])` — the keyword may be
followed by a version **digit**, e.g. `qwen2`/`qwen3`, but never by a *letter*, which
would make it the prefix of a different family), AND the repo is a top-tier family;
AND repos that merely *contain* the keyword as a substring (e.g. `qwopus`/`qwythos` for
`qwen`) are excluded.

#### Scenario: family keyword matches on word boundary
Given a family search for keyword `qwen` over repos that include `unsloth/Qwen3.8-27B-GGUF`, `Qwen/Qwen2.5-7B-Instruct-GGUF`, `Jackrong/Qwopus3.8-27B-Flash-GGUF`, `empero-ai/Qwythos-9B`,
When the family repo list is built,
Then the two Qwen repos are included,
And zero returned repo ids contain `qwopus` or `qwythos`.

### Requirement: F2 — Family mode reuses the high + lower per-provider selection
WHEN family mode discovery runs over a family's repos,
THEN each provider contributes its HIGH (best-fitting) quant plus a clearly-LOWER quant
(gap ≥ 25%, same rule as trending mode), never low-fidelity IQ1/2/3 quants, never
vision projectors, and only files that fit the card (size + headroom + KV ≤ total).

#### Scenario: family mode reuses high+lower per-provider selection
Given family `qwen` on a 48 GB card with provider `unsloth` offering Q8 (~29 GB), Q5_K_M (~17 GB), IQ2_XXS (~8 GB), and an mmproj (~0.5 GB),
When family-mode discovery runs with per_provider=2,
Then unsloth yields the Q8 and the Q5 (gap ≥ 25%),
And never the IQ2, never the mmproj.

### Requirement: F3 — Gated family providers are skipped pre-flight and the count refilled
WHEN a family-mode candidate's file probes `access-denied` (401/403) or `dead` (404),
THEN that file is recorded in the skip summary and discovery refills from the next
matching provider (the issues #53/#56 contract, reused unchanged).

#### Scenario: gated family provider is skipped and count refilled
Given family `qwen` includes gated repo `orcarouter/Qwen3.8-27B-Uncensored-GGUF` (probe → access-denied) plus two fitting providers,
When family-mode discovery runs with a count that the gated provider would have filled,
Then `orcarouter/...` is absent from the download list,
And the skip_summary records it,
And the count is refilled from the next matching provider.

### Requirement: F4 — Family dry-run previews a known low-end family without downloading
WHEN the real CLI runs `--download-top-tier --family qwen --count 1 --dry` on a pinned
small card,
THEN exit 0, stdout shows a `[family] qwen → ... match` line and the dynamic memory
readout, at most `1 provider × per_provider(2) = 2` candidate rows
(`owner/repo -> <TierGB>/<file>`), nothing is downloaded, and no server is spawned.

#### Scenario: family dry-run previews a known low-end family, 1 provider, without downloading
Given the real CLI and LLAMA_RAM_BYTES pinned to a small card,
When `llama-ai --download-top-tier --family qwen --count 1 --dry` runs,
Then it exits 0 and prints the `[family] qwen` match line,
And at most 2 candidate rows each `owner/repo -> <TierGB>/<file>`,
And stdout says nothing was downloaded or served, and no `llama-server` is spawned.

### Requirement: F5 — Smallest low-end family model downloads for real through the family path
WHEN family mode resolves the smallest single-file, non-sharded, non-projector,
non-MTP quant (q2..q8) ≤ 2 GB from the live family search,
THEN `download_top_tier_candidate` (the same function the family path calls) fetches it
into the provider-aware path with the correct small tier folder, size within tolerance
of the real HF size (not a stub), GGUF metadata verification passes, and a repeat run
is idempotent (same path, no clobber).
AND if the family list is empty (HF unreachable / family vanished) the run FAILS
loudly — never a skip.

#### Scenario: smallest low-end family model downloads for real through the family path
Given the live `qwen` family search on a small card,
When the smallest fitting family file is downloaded through `download_top_tier_candidate`,
Then the file exists at `<root>/<owner>/<family>/<TierGB>/<file>` with the small tier,
And its size is within tolerance of the real HF size,
And its GGUF metadata verifies,
And a second run returns the same path without clobbering.

### Requirement: F6 — Family providers are ranked trendingScore desc, downloads desc tie-break
WHEN family-mode candidates are returned,
THEN providers are ordered by `trendingScore` desc with `downloads` desc breaking ties
(trendingScore is sparse — many family repos report 0).

#### Scenario: family ranking uses trendingScore then downloads tie-break
Given two family providers with identical trendingScore but different downloads,
When family-mode discovery returns them,
Then the higher-downloads provider is ordered first.

### Requirement: F7 — No `--family` flag = unchanged trending behavior
WHEN `--download-top-tier` is run WITHOUT `--family`,
THEN discovery uses the exact existing trending path (`_trending_gguf_repos`) and all
existing top-tier tests pass unmodified (byte-identical behavior).

#### Scenario: no family flag = unchanged trending behavior
Given `discover_top_tier` called with `family=None` (the default),
When discovery runs,
Then the trending repo source is used, `min_trending_score` still applies,
And the existing unmodified top-tier test suite passes.

### Requirement: F8 — Unknown family fails with a clear message
WHEN the family search returns zero matching repos (typo or non-GGUF family),
THEN the command prints `no GGUF repos found for family '<kw>'` and exits non-zero —
never a silent success.

#### Scenario: unknown family fails with a clear message
Given a family keyword with zero matching GGUF repos,
When the family download is attempted,
Then the message `no GGUF repos found for family '<kw>'` is printed,
And the exit code is non-zero.

### Requirement: F9 — Transient HF API errors are retried; permanent errors fail fast
WHEN any top-tier HF API call (search, per-repo tree, or pre-flight probe) is issued
through `_hf_get`,
THEN transient failures (HTTP 429/500/502/503/504 and plain network/socket-timeout
errors) are retried with bounded exponential backoff (honouring `Retry-After`), up to a
fixed attempt budget, and permanent HTTP errors (401/403/404, …) are NOT retried — they
fail fast so a genuinely gated/dead repo is still reported loudly (the F3 skip path and
the F8 "no repos" path rely on that). This is what makes the family dry-run robust to
the hundreds-of-calls fan-out hitting a rate-limit: a single 429 on one repo tree must
not silently drop that repo and turn a valid match into a false "no model fits".

#### Scenario: a transient 429 on one call is retried until it succeeds
Given a transient 429 (rate-limit) response followed by a successful response,
When `_hf_get` is called,
Then the 429 is retried with backoff and the eventual successful payload is returned.

#### Scenario: a permanent error fails fast without retry
Given a permanent HTTP error (e.g. 404 for a dead repo/file),
When `_hf_get` is called,
Then it fails fast on the first attempt (no retry) so the caller's gated/dead skip path
still fires.

#### Scenario: a persistent transient error is budget-bounded
Given a transient 429 that never clears,
When `_hf_get` is called,
Then it stops after the fixed attempt budget and raises (never an infinite retry loop).

---

## Verification
- Hermetic (`make test-unit`): `test_family_scope_mocked` covers F1, F2, F3, F6, F8 and
  the 1-provider degenerate case; `test_discover_family_none_uses_trending` covers F7;
  `test_hf_get_retries_transient_and_fails_permanent` covers F9 (transient 429 retried,
  permanent 404 fails fast, persistent 429 budget-bounded).
- DRY + real download (`make test-top-tier` / CI top-tier job):
  `test_family_dry_run_known_lowend_one_provider` (F4) and
  `test_family_real_known_lowend_one_provider` (F5).
- Placement asserts reuse `provider_dest_path`'s contract
  (`test_provider_placement_specific` style).
- No regression: `make lint`, `make test-unit`, `make test-top-tier`,
  `make openspec-validate`.
