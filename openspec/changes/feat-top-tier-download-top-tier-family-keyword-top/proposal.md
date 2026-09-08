# `--download-top-tier --family <keyword>` — top providers of ONE model family, each with high + lower quant

## One-line summary
`llama-ai --download-top-tier --family <keyword>` downloads the **top 5 providers (HF
owners) of ONE chosen model family** (e.g. `qwen`, `ornith`), each with its **HIGH +
LOWER quant** — the exact same "providers × high+lower" logic the existing top-tier
download uses, but **scoped to a family keyword** instead of trending across all
families.

## Why
Today `--download-top-tier` finds 5 trending *providers across all families*. A niche
family (ornith) has 0–2 repos in the trending window, so it never surfaces. There is no
way to say "give me the best 5 Qwen GGUF providers" or "the best 5 Ornith providers".
This change adds that, with NO second code path: family mode is a *filter* fed into the
SAME `discover_top_tier` → probe → placement → `hf`-CLI download pipeline.

## What changes
1. **New flag** `--family <keyword>` on `--download-top-tier`. Everything else
   (`--count`, `--per-provider`, `--dry`) works exactly as today; `--count` still means
   number of **providers (HF owners)**, default 5.
2. **New family repo lookup `_family_gguf_repos(keyword)`** (the one new seam):
   queries the FULL model set for the keyword
   (`{HF_API}?search=<keyword>&filter=gguf&sort=downloads&direction=-1&limit=<large>` —
   `filter=gguf` only, **no** `sort=trendingScore`), keeps only repos whose id matches
   the keyword on a **word boundary** (not substring: `--family qwen` must NOT match
   `Jackrong/Qwopus3.8-27B-Flash-GGUF` or `empero-ai/Qwythos-9B`), keeps only top-tier
   families, and ranks by **trendingScore desc, tie-break downloads desc**.
3. **`discover_top_tier(..., family=None)`** — new optional parameter; `family=None`
   is byte-identical to today. When set, the repo list comes from
   `_family_gguf_repos(keyword)` and **`min_trending_score` is ignored (0)** (a score
   floor on a niche family would filter out everything). Every downstream stage
   (fit gate, high+lower per provider, pre-flight probe + refill, provider-aware
   placement, `hf` download) is the EXISTING code, untouched.
4. **CLI plumbing**: `--family` in `main()`'s parser, passed to
   `_main_download_top_tier`; dry-run readout gains one line
   `[family] <kw> → N providers (M files) match`.
5. **Degenerate families** (no silent surprises):
   - 0 matching repos → clear message `no GGUF repos found for family '<kw>'` + exit 1;
   - fewer providers than `--count` → download what exists, honest `downloaded N/M`
     report (same contract as today).
6. **Worktree lint (relies on main's fix, no new code):** the containerized
   `make lint` used to silently report "LINT OK" without scanning a single file
   inside a git **worktree** (the background-watch-loop case). Root cause: a
   worktree's `.git` is a *pointer file* to the parent repo's
   `.git/worktrees/<name>`, which wasn't mounted, so `git ls-files` failed with
   exit 128 and the lint's empty-file-list path passed. That root-cause fix is
   already on `main` (Makefile: detect a worktree — `.git` is a file — and mount
   the parent repo at its real path so `git` resolves inside the container; a
   normal CI checkout has `.git` as a dir so the mount is empty → byte-identical).
   This change **inherits** that fix; it adds no competing lint mechanism.

## What does NOT change
- `--download-top-tier` **without** `--family` behaves byte-identically to today — all
  existing tests pass unmodified.
- The global trending window, `TOP_TIER_FAMILIES` gate (still applies in family mode),
  placement folders, `TOP_TIER_FAMILIES` contents.
- README gains a `--family` subsection in the same PR.

## NO fallbacks — one code path (mandatory)
Family mode adds exactly one new seam (`_family_gguf_repos`). It reuses the same
`discover_top_tier` → `_probe_file_downloadable` → `pick_tier_folder`/`provider_dest_path`
→ `hf`-CLI download path as trending mode. There is NO second, differently-implemented
path for discovery, download, probe, placement, or model resolution. When `--family`
is absent the exact existing branch runs.

## Verification
- `test_family_scope_mocked` (hermetic, `make test-unit`): word-boundary scope,
  high+lower per provider, gated skip + refill, placement, ranking, degenerate.
- `test_family_dry_run_known_lowend_one_provider` (DRY, `make test-top-tier`): real CLI,
  known low-end family, 1 provider, small card, nothing downloaded.
- `test_family_real_known_lowend_one_provider` (REAL download, `make test-top-tier`):
  smallest live low-end family model downloaded for real through the family path,
  idempotent re-run.
- No regression: `make lint`, `make test-unit`, `make test-top-tier`,
  `make openspec-validate NAME=feat-top-tier-download-top-tier-family-keyword-top`.

## Notes
- Issue #61; feature branch `feat/feat-top-tier-download-top-tier-family-keyword-top`
  off `main`.
