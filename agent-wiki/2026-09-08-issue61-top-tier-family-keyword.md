# 2026-09-08 — issue #61: `--download-top-tier --family <keyword>`

## What shipped
`llama-ai --download-top-tier --family <keyword>` downloads the **top `--count`
providers (HF owners) of ONE model family** (e.g. `qwen`, `ornith`), each with a
HIGH + clearly-lower quant — the SAME "providers × high+lower" logic the existing
trending top-tier download uses, scoped to a family keyword instead of trending
across all families.

## Design (one new seam, no second code path)
- `_family_gguf_repos(keyword)` — the only new function. Queries the **complete**
  family (`{HF_API}?search=<kw>&filter=gguf&sort=downloads&direction=-1&limit=300`,
  NO `sort=trendingScore`), keeps only repos matching the keyword on a **word
  boundary** (`(?<![a-z0-9])<kw>(?![a-z])` — a trailing version digit like `qwen2`
  is allowed, a trailing *letter* is not, so `qwen` never matches `qwopus`/`qwythos`),
  gates on `TOP_TIER_FAMILIES`, ranks by trendingScore desc with downloads desc
  tie-break.
- `discover_top_tier(..., family=None, family_repos=None)` — new optional params.
  `family=None` is byte-identical to today; when set, the repo list comes from the
  family search and `min_trending_score` is forced to 0 (a score floor would filter a
  niche family out entirely). Every downstream stage (fit gate, high+lower per
  provider, pre-flight probe + refill, provider-aware placement, `hf` download) is
  the EXISTING code, untouched.
- CLI: `--family` in the parser, passed through; dry-run gains a `[family] <kw> → N
  providers (M files) match` line. Zero matches → `no GGUF repos found for family
  '<kw>'` + exit 1 (loud, never a silent success).

## Key decisions during implementation
- **Worktree lint** (a blocker for the background-watch-loop workers): the
  containerized `make lint` silently reported OK without scanning a single file
  inside a git worktree — a worktree's `.git` is a pointer file to the parent repo's
  `.git/worktrees/<name>`, which isn't mounted, so `git ls-files` exited 128 and the
  lint's empty-list path passed. That root-cause fix landed on `main` first (Makefile:
  detect a worktree and mount the parent repo at its real path); this branch was
  rebased onto `main` and **inherits** it rather than adding a competing mechanism
  (the earlier in-branch `/maindotgit` + `GIT_DIR`/`GIT_INDEX_FILE` mount was dropped
  to keep one code path).
- **F5 test single-file filter**: the `(?i)(q[2-8]_)` quant selector also matched
  `IQ*` / letter-prefixed quants that must be excluded. Tightened to
  `(?i)(?<!i)(?<![a-z0-9])q[2-8]_` and skip sub-200 MB shard fragments so the
  resolved low-end file is genuinely a single-file plain quant.

## Verification (all via the serialized-make lock, containerized)
- `make lint` OK · `make test-unit` 178 passed · `make test-top-tier-ci` 15 passed
  (real ~430 MB `Qwen/Qwen2.5-0.5B-Instruct-GGUF::qwen2.5-0.5b-instruct-q4_0.gguf`
  family download + dry-run + idempotent repeat) · `make openspec-validate` valid.
- **Host Metal proof**: downloaded the 0.5B model and served it through the host
  `~/bin/llama-ai` launcher (Metal `llama-server`, `-ngl 99`); `/health` → `{"status":"ok"}`,
  chat `"hi"` → `"Hi there! How can I assist you?"` (~238 tok/s).

## Status
OpenSpec change `feat-top-tier-download-top-tier-family-keyword-top` valid, tasks
ticked. PR opened against `main` referencing issue #61.
