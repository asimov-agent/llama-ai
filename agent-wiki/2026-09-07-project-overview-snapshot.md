# 2026-09-07 — project overview snapshot (full-repo survey)

## What
Full survey of the repo at a point when it had just absorbed the top-tier
download + dispatch-reliability waves (PRs #53–#58 merged to `main`).
Method: Diamond fan-out — 4 parallel exploration workers (core app code /
verification+loop infra / watch-loop / OpenSpec+conventions) → skeptic
cross-check of load-bearing claims against the tree → synthesis.

## Repo purpose
Serve GGUF models locally via llama.cpp `llama-server` on an Apple-Silicon
M-series Mac (tuned for 48 GB unified memory), plus a resilient HF downloader,
a top-tier trending model discoverer, and a self-driving background watch loop
that drives GitHub issues to PRs.

## Core application
- `scripts/llama_serve.py` (~1081 lines) — launcher + auto-tuner +
  `--download-top-tier`. Constants (llama_serve.py:68-102):
  `TOTAL_RAM_BYTES = 48 GiB`, `OS_OVERHEAD = 3 GiB`, `KV_QUANT = "q4_0"`,
  `MIN_TOP_TIER_GB = 4.0` (below = toy),
  `TIER_LADDER_GB = (1, 2, 4, 8, 16, 24, 48, 96, 128, 192, 256, 384, 512,
  768, 1024, 1536, 2048, 3072)`, `LLAMA_HEADROOM_MAX_FRAC = 0.45`,
  `SAMPLING = temp 0.6 / top-p 0.9 / top-k 40 / min-p 0.05` (fallback preset;
  model-author sampling preferred — `llama-serving-sampling-defaults` change).
  CLI (llama_serve.py:971-985): `model`, `--list`, `--port` (11434), `--dry`,
  `--download-top-tier`, `--count` (5), `--per-provider` (2),
  `--min-trending-score` (0).
- `pick_tier_folder()` (llama_serve.py:546-565): tier = smallest ladder bucket
  ≥ model size, restricted to buckets ≤ the detected card (`sysctl hw.memsize`
  / `/proc/meminfo`, `LLAMA_RAM_BYTES` override) — a 48 GB card keeps the
  classic 8/16/24/48; a 512 GB card gains large tiers and labels honestly.
- Top-tier discovery (`discover_top_tier`, llama_serve.py:584+):
  time-weighted HF `trendingScore` (filter=gguf) → top-tier family gate
  (`_is_top_tier_repo`, :493) → non-trivial quant filter (drops IQ1-3, MTP
  heads, sub-4 GB, multi-file shards) → fits-with-KV-reserve gate → pre-flight
  ~64 KiB ranged probe per candidate (skips 403/401 gated, 404 dead,
  200-but-HTML fast, then refills the count from the next fitting provider —
  issues #53/#56). Placement is provider-aware:
  `~/models/<owner>/<family>/<TierGB>/<file>.gguf`, verified by GGUF
  metadata before acceptance.
- `scripts/hf_download.py` — official `hf` CLI only (no requests/urllib
  fallback, ever), auto-resume, up to 20 retries, `.progress.log`, and a
  stall-watch that kills a dead 0-MB/s download subprocess and retries
  (PR #58, issue #55). `download_test_model.py` fetches
  Qwen2.5-0.5B → `~/models/Qwen/8GB/` (idempotent) for the health stage.

## Verification / loop / CI
- `make loop` → `scripts/loop_harness.py` runs 9 stages (loop_harness.py:36-69):
  image → download → lint → unit → install (test-install-host) → health →
  top-tier → test → openspec-validate → clean. Fails closed: a failed stage
  still lets later stages run (report all failures) but the overall exit is
  non-zero; `clean` (prune stopped orphan test containers) always runs.
- No-skipped-tests: `tests/conftest.py` report hooks turn any skip into a
  failure in the exit code — a missing prerequisite fails loudly, never skips.
- No-fallback single code path: every stage runs in ONE test image
  (`containers/test/`, python + pytest + deps + in-image CPU `llama-server` +
  `hf` CLI), repo mounted at `/repo`; `RUNTIME` = nerdctl (host) / docker (CI)
  only as engine availability, same command shape.
- CI (`.github/workflows/ci.yml`) = one parallel job per make stage
  (lint / unit / install / openspec / cpu-health / agents-read); `agents-read`
  runs in its own `python:3.12` container with `hermes-agent==0.19.0`.
- OpenSpec CLI is Dockerized (`openspec/` image, repo at `/repo`):
  `make openspec-new|validate|status|shell`; structure validated by the CLI,
  task-completion enforced separately by `scripts/check_openspec_tasks.py`
  (active change with an unticked `- [ ]` → red).
- `scripts/serialized-make.py` — fcntl `LOCK_EX` on
  `.watchloop/run/test.lock`; the ONLY way a watch-loop worker may invoke
  containerized make targets (parallel workers never race nerdctl).
- AGENTS.md rulebook guard: `scripts/scan_agents_md.py` reuses Hermes's
  canonical `tools.threat_patterns.scan_for_threats(content, scope="context")`
  and fails closed if AGENTS.md would be blocked from loading into a worker's
  system prompt; regression fixtures in `tests/fixtures/agents/`
  (happy rulebooks vs. exfil-curl/exfil-wget/role-hijack/invisible-unicode/
  secret-read).

## Watch loop (self-driving)
- Host crontab `*/20 * * * *` → `scripts/watchloop_dispatch.py` (982 lines).
  Per tick: merge gate (CI green + APPROVED review + no open threads + PR head
  NOT behind `main`) → spawn one `project-manager` Hermes worker per open
  issue lacking a live branch/PR, each in its own worktree
  `../llama-ai-wt/<kebab>` off `origin/main` + own log.
- Durable per-interval tick dedup (issue #25/#27): bucket
  `tick-{epoch // TICK_INTERVAL_SECONDS}` (`TICK_INTERVAL_SECONDS = 1200`,
  watchloop_dispatch.py:817-828). The tick lock is deliberately held for the
  WHOLE interval (not released at `main()` end), so a doubled cron re-fire in
  the same bucket is deduped even if the first tick already finished; a new
  bucket reclaims an old-bucket lock; a mid-tick crash is reclaimed next
  interval (never a permanent block). Covered by
  `tests/test_watchloop_dispatch.py::TestTickDedup`.
- Stale `.running` locks (dead PID) are auto-cleaned and the issue re-spawned;
  the merge gate returns the same-tick closed-issue set so it is not
  re-spawned. Merged PRs trigger auto-cleanup: worktree + local branch +
  per-worker artifacts + REMOTE branch (ancestor-of-`origin/main` check).
- Worker model: env `WATCHLOOP_WORKER_MODEL/PROVIDER`, else
  `.watchloop/run/worker-model` (template `scripts/worker-model.template`;
  default `llm-local`, hosted/OpenRouter recommended for speed); local
  providers get a pre-spawn probe of `127.0.0.1:11434/v1/models`
  (issue #37) and a clean skip if the server is down.

## OpenSpec state (at snapshot time)
23 active changes under `openspec/changes/`, ALL tasks ticked (0 open) —
consistent with no open issues/PRs in flight. Themes: top-tier download wave
(#49 discovery, #51 dynamic tiers, #53 skip-dead, #56 skip-summary crash,
#55 stall watch), dispatcher reliability (per-issue workers, tick dedup,
rebase+locks, auto-clean local+remote, repair-stage, worker-model probe),
workflow discipline (PR-gate-never-merge-behind, issue-goal↔OpenSpec sync,
Given/When/Then spec+test rule, linefeed lint, CI pipeline, agents-read
guard), and tooling (llama-ai-tooling, sampling defaults, scripts/ relocation).

## Repo state at snapshot
- `main` at `6eb5cf2` (PR #58 merge); no open PRs, no open issues.
- Worktrees: `llama-ai-wt/feat-read-author-recommended-sampling-defaults-fro`
  (detached), `feat-watchloop-dispatcher-reliability-auto-clean-d`,
  `fix-dispatch-eliminate-the-doubled-cron-tick-prove` (branches) + a prunable
  `/private/tmp/wt-clean-check`.
- Local `main` was 6 commits behind `origin/main` until `git pull`
  (PR #58 merged by the loop while this session was running).
- `gh` CLI unauthenticated in this session (no token) — PR/issue state read
  from git history + API-free sources.

## Lessons
- Diamond workers on `llm-local` (slow ~170 s/call) timed out at the 3600 s
  subagent cap on multi-file exploration scopes — the transcripts still held
  all read data, and re-verifying the load-bearing claims inline (constants,
  stage chain, git state) was cheap and confirmed every claim kept.
- Keep subagent scopes tight on this model: one concern per worker, and
  budget for the slow local LLM (or use a hosted model for fan-out).
