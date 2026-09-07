# Spec: Fix `--download-top-tier` stalled-download hang (issue #55)

## Why
The downloader's progress loop never times out and its stall-watch is a dead `pass`, so a
0-MB/s download hangs the whole sequential batch forever with no retry and no `SKIPPED`.

---

## ADDED Requirements

### Requirement: A1 — A stalled subprocess is terminated and retried
WHEN a download subprocess makes no forward byte-progress for the stall threshold while still
alive,
THEN it is killed, a `STALLED → terminating & retrying attempt N` line is logged, and the
existing retry loop advances to the next attempt (up to `MAX_RETRY`).

#### Scenario: 0-MB/s download is killed + retried
Given `hf download` is alive but `tree_bytes(dest)` does not advance,
When  the no-growth window reaches the stall threshold,
Then  the subprocess is killed,
And   the attempt counter increments,
And   a `STALLED → terminating & retrying attempt 2` line is written to the progress log.

### Requirement: A2 — A healthy download is never spuriously killed
WHEN a download subprocess is making forward progress (bytes advancing),
THEN it is left untouched, even if it has brief flat windows shorter than the grace window.

#### Scenario: growing download stays running
Given `hf download` is alive and `tree_bytes(dest)` is advancing,
When  the stall-watch samples the tree,
Then  the subprocess is NOT terminated,
And   no `STALLED` line is logged.

### Requirement: A3 — Retry-then-skip contract preserved
WHEN the same stall recurs across attempts up to `MAX_RETRY`,
THEN the run gives up on that candidate and `llama_serve.py` reports it `SKIPPED` with a stall
reason — it never hangs unboundedly and never silently passes.

#### Scenario: persistent stall reports SKIPPED
Given a candidate stalls on every attempt up to `MAX_RETRY`,
When  the retry budget is exhausted,
Then  the candidate is reported `SKIPPED (stall)` by `--download-top-tier`
And   `llama_serve.py` does not block the rest of the batch.

---

## VERIFICATION

### Verification: A1
- Hermetic test with an `HF_STALL_SECONDS`-shrunk threshold: a subprocess with no growth is
  killed and the attempt counter increments; `STALLED` appears in the log.
### Verification: A2
- Hermetic negative guard: a growing subprocess survives the stall-watch (no false kill).
### Verification: A3
- Hermetic test: repeated stalls exhaust `MAX_RETRY` and yield `SKIPPED (stall)`.
### Regression
- `make lint`, `make test-unit`, `make test-top-tier`; `make openspec-validate`; CI green.
