# Spec: Skip dead/gated top-tier repos + refill from the next provider (issue #53)

## Why (rationale)

The HF **listing API** shows a gated (403) or dead (404) repo's files, so `discover_top_tier`
ranks and counts it normally; only the **object download** hits the 403/404. The batch loop
then wastes 3 retries, prints `SKIPPED`, and leaves the batch short (e.g. 8 of intended 10).
We add a **pre-flight downloadability probe** (fetch a real small chunk, not just a status
code) per candidate and **refill** the count from the next fitting provider, so the requested
`count × per_provider` is honored and gated/dead repos fail fast. The real `hf` downloader,
idempotency, and metadata-verify are unchanged.

---

## ADDED Requirements

### Requirement: A1 — Pre-flight check that a candidate is downloadable
WHEN a top-tier candidate is being prepared for download, THEN a real probe verifies the
object is genuinely downloadable BEFORE the heavy transfer.

- The probe downloads a **real chunk** of the file (a ranged request, e.g. the first ~64 KiB),
  NOT just a status-code check — it must return real GGUF model bytes (or non-trivial binary),
  so a 200-serving HTML/error shell is rejected too.
- A candidate that fails the probe is **excluded** and logged with a clear reason —
  `[top-tier] skipping <repo>::<file>: access-denied (403)` / `dead (404)` — and is NOT
  dragged through the 3 × slow download retries.

#### Scenario: gated repo is skipped, not triple-retried
Given `orcarouter/...` returns 401/403 on the file probe, when the batch runs, THEN the
repo is reported as `access-denied` and skipped after ONE probe (no heavy transfer, no 3×
retry); the batch continues with the remaining providers.

#### Scenario: a 200-but-HTML shell is not accepted
Given a server returns HTTP 200 with an HTML error body (not real GGUF bytes), THEN the
probe does NOT return `ok` — the candidate is not treated as downloadable.

#### Scenario: real downloadable repo is kept
Given a public repo (`unsloth/...`), THEN the probe returns `ok` because it fetched a real
GGUF chunk (auth-ok).

### Requirement: A2 — Advance to the next fitting provider (refill the count)
WHEN one or more trending repos are gated/dead, THEN `discover_top_tier` keeps walking the
trending list (beyond the initial rolling window) until `limit` valid candidates are
collected, so the count the user asked for is honored.

#### Scenario: count is filled despite gated repos
Given 5 providers but one is gated/dead, THEN `discover_top_tier(limit=10)` returns 10 from
the remaining + next providers (not 8).

### Requirement: A3 — Honest completion summary
WHEN the batch finishes, THEN it reports downloads, and separately the skips with a reason:
`downloaded N/M (+S skipped: access-denied, dead)`.

#### Scenario: skips are reported, not hidden
Given a batch where one gated repo is skipped, THEN the final line is
`downloaded 8/10 (+2 skipped: access-denied)` — the reason is visible, and the report shows
both the completed count and the skipped count with reason.

---

## EXISTING Requirements (unchanged)

### Requirement: E1 — Real hf download, idempotent, metadata-verified
The downloader still delegates to the real `hf` CLI (etag-aware), and verifies the file by
GGUF metadata post-download. Pre-flight is an addition, not a replacement.

### Requirement: E2 — Transient retries preserved
Transient (network) failures in the batch loop are still retried up to `RETRIES`; only a
**pre-flight-denied** repo is skipped immediately without the heavy retry.

---

## Verification

- Hermetic unit test: mock the probe to fail (403-gated / 200-HTML) for a repo; assert it is
  excluded pre-flight (no download attempted) and discovery refills to `limit` from the next
  provider. Another unit test asserts the probe verifies a REAL GGUF chunk and rejects an
  HTML/error 200 body.
- **Real-HF tests (CI)**: `test_real_probe_ok_on_public_downloadable_repo` (a public repo is
  probed `ok` after fetching a real GGUF chunk — auth-ok), `test_real_probe_gated_repo_is_access_denied`
  (`orcarouter/...` is `access-denied`), `test_real_probe_dead_file_is_dead` — all run in
  `make test-top-tier-ci` (the CI top-tier job).
- `make lint`, `make test-unit` (incl. skip/refill + probe-chunk tests), `make test-top-tier` green.