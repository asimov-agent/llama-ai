# 2026-09-05 top-tier-trending-download

## What
Issue #49: `llama-ai --download-top-tier` that finds trending top-tier GGUF models
which fit the user's GPU (48 GB) with KV buffer, downloads them, and serves them.

## Spec-driven state
- OpenSpec change `feat-download-top-tier-trending-models` created + validated
  (proposal.md, spec.md A1–A5/E1/E2/REM, tasks.md 12 items, design.md verified data).
- Mirrored 1:1 into issue #49 body (8.5 KB). Commits `101ea5f`, `968e01a` pushed to
  `feat/make-the-llama-ai-download-the-top-tier-models-bas`.

## Verified findings (live HF API 2026-09-05)
- Trending GGUF signal: `GET /api/models?sort=trendingScore&direction=-1&filter=gguf`.
- Dominant trending top-tier family = **Qwen3.8-27B** (unsloth/ISTA-DASLab/OBLITERATUS/
  orcarouter/JonathanColetti). Fits 48 GB at Q8_0 (29.05 GB, ~15.9 GB KV headroom).
- Negative result: GLM-5.3-Flash (~400 GB) and DeepSeek-V4-Flash (86–164 GB) trend but
  do NOT fit 48 GB => fit-buffer gate mandatory, not optional.

## Status / next
Design + spec done, validated, synced to issue + pushed. Implementation not started
(tasks 2–12 unticked). Next session: implement argparse flag + discover_top_tier + HF
client + fit gate + download + serve + tests, run loop gate, open PR referencing #49.