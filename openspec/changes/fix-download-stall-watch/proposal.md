# Fix `--download-top-tier`: stalled 0-MB/s downloads hang forever (issue #55)

## Problem
`scripts/hf_download.py` (the downloader used by every `--download-top-tier` candidate) has a
**dead stall-watch**:

```python
# stall watch (no growth ~60s)
if total == last_bytes:
    pass  # will accumulate stall detection below   # <-- literal no-op
last_bytes = total   # reassigned every 3s loop iteration — corrupts the signal
```

Because the `while proc.poll() is None:` progress loop never times out and retries fire only on
process *exit*, a download that stalls at 0 MB/s (a known HF/xet failure mode) is **never aborted
and never retried** — the whole sequential batch blocks behind it forever with no log change and
no `SKIPPED` fallback. Verified live 2026-09-07: ~15 no-growth events (up to ~100s) during a
full batch; in every case the code did nothing in response and only advanced when the network
resumed on its own. The batch completed, but a truly dead connection wedges it indefinitely.

## Change
1. **Implement a real stall-watch** in `hf_download.py`'s progress loop: track
   `last_advancing = time` (updated only when `tree_bytes(dest)` *grows*); if a still-alive
   `proc` makes no forward progress for a **stall threshold** (~90 s default), kill the
   subprocess and let the existing retry flow advance to `attempt+1`. Log a clear
   `STALLED → terminating & retrying attempt N`.
2. **Fix the signal:** drop `if total == last_bytes: pass` / `last_bytes = total`; compare
   against an *advancing* marker with a small grace window so tiny/flat start-of-file growth
   doesn't false-trigger.
3. **Preserve the retry/SKIPPED contract:** a stalled run retries (up to `MAX_RETRY`), then is
   reported `SKIPPED` with a `stall` reason by `llama_serve.py` — never an unbounded silent hang.
4. **Make the threshold injectable** (env `HF_STALL_SECONDS`, default 90) so hermetic tests can
   shrink it; keep the production default.

## Verification
- Hermetic test: a subprocess that emits no output and makes no byte growth for `> threshold`
  is **killed and advanced to attempt 2** with `STALLED` logged (proves the fix).
- Hermetic negative guard: a subprocess that *does* grow is **never killed** (no false stall).
- Hermetic: a stalled run beyond `MAX_RETRY` is reported `SKIPPED`/`stall` (retry→skip contract).
- Regression: `make lint`, `make test-unit`, `make test-top-tier`; `make openspec-validate`;
  real CI run green.

## Aligns
- Grader/AGENTS.md NO-SKIPPED-TESTS + every spec scenario has Given/When/Then + a matching test
  wired into the Makefile/CI gate.