# Tasks — feat-top-tier-download-top-tier-family-keyword-top

- [x] 1. OpenSpec change scaffold (proposal.md + specs/llama-ai-tooling/spec.md + tasks.md) —
      VALID — committed + pushed to `feat/feat-top-tier-download-top-tier-family-keyword-top`
      before implementation.
- [x] 2. Add `_family_gguf_repos(keyword)` to `scripts/llama_serve.py`: full model-set search
      (`filter=gguf&sort=downloads&direction=-1&limit=<large>`, NO sort=trendingScore),
      word-boundary keyword match on repo id, top-tier family gate, ranked by
      trendingScore desc with downloads desc tie-break.
- [x] 3. Extend `discover_top_tier(..., family=None)`: when `family` is set, the repo list
      comes from `_family_gguf_repos` and `min_trending_score` is forced to 0; `family=None`
      keeps the exact existing trending path (byte-identical). No other stage changes.
- [x] 4. CLI: add `--family` to `main()`'s parser; pass through in `_main_download_top_tier`;
      dry-run/list readout gains `[family] <kw> → N providers (M files) match`; zero matches
      → `no GGUF repos found for family '<kw>'` + exit 1.
- [x] 5. Hermetic unit tests in `tests/test_llama_ai.py` (`make test-unit`):
      `test_family_scope_mocked` (word-boundary scope, high+lower per provider, gated skip +
      refill, placement, ranking tie-break, degenerate 0-match + 1-provider) and
      `test_discover_family_none_uses_trending` (F7: `family=None` = trending path).
- [x] 6. Acceptance tests in `tests/test_top_tier_acceptance.py` (`make test-top-tier` / CI):
      `test_family_dry_run_known_lowend_one_provider` (real CLI, `--family qwen --count 1
      --dry`, pinned small card, ≤2 rows, nothing downloaded, no server) and
      `test_family_real_known_lowend_one_provider` (smallest live low-end family model ≤2 GB,
      real `hf` download through `download_top_tier_candidate`, provider-aware small tier,
      size tolerance, GGUF metadata verification, idempotent repeat; loud failure if empty).
- [x] 7. README: add a `--family` subsection to the `--download-top-tier` section (flag +
      low-end/1-provider dry and real examples + word-boundary note + degenerate behavior).
- [x] 8. Worktree lint: rely on the root-cause fix already on `main` (Makefile
      detects a worktree — `.git` is a file — and mounts the parent repo at its
      real path so the containerized `make lint`'s `git ls-files` resolves and
      scans every tracked file; a normal CI checkout keeps the mount empty →
      byte-identical). No competing lint mechanism added here.
- [ ] 9. Verify: `make lint`, `make test-unit`, `make test-top-tier-ci`,
      `make openspec-validate NAME=feat-top-tier-download-top-tier-family-keyword-top` all
      GREEN via the serialized-make lock; commit + push; open PR against `main` referencing
      issue #61.
