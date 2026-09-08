# fix-dispatch-tick-boundary-straddle

## Why

The watch-loop dispatcher (`scripts/watchloop_dispatch.py`, host crontab every
20 min) is supposed to run `main()` EXACTLY once per 20-min slot. The durable
"hold-for-interval" tick lock (issues #25/#27/#30, PR #28, atomic meta-lock
#62/PR #71) is sound **within** a bucket, but it is defeated by the bucket
boundary itself.

`_current_tick()` computes `f"tick-{int(time.time()) // 1200}"`. The bucket
boundary is therefore at **every epoch second ≡ 0 (mod 1200)**. Because the
host timezone offset is a whole number of hours (CEST = UTC+2), those epoch
boundaries land EXACTLY on the wall-clock instants `HH:00:00`, `HH:20:00`,
`HH:40:00` — which are precisely the `*/20` cron fire instants:

| cron fire (CEST) | epoch | `int(epoch)//1200` |
|---|---|---|
| 18:00:00.000 | 1788883200 | 1490736 |
| 17:59:59.990 | 1788883199 | 1490735 |

So a doubled cron fire (the real, reproduced `*/20` slot firing twice, issue
#25) that straddles the boundary — process A reads the clock one millisecond
before HH:00:00 (bucket N), process B one millisecond after (bucket N+1) —
computes DIFFERENT buckets. Process B sees A's lock as an OLDER bucket
("finished prior interval") and reclaims it, so **BOTH processes run `main()`**.
This is exactly the observed production symptom (issue #73): a paired
`tick start` → `tick done` twice per slot, with the `.running` lock downstream
masking the double `main()`.

The dedup is correct except at the boundary, and the boundary is exactly where
the cron fires — the worst possible alignment.

## What Changes

- **Shift the tick-bucket boundary OFF the cron fire instants.** `_current_tick()`
  becomes `f"tick-{(int(time.time()) + TICK_INTERVAL_SECONDS // 2) // TICK_INTERVAL_SECONDS}"`.
  This moves the boundary half an interval (600s) forward, so it lands at
  `HH:10:00`/`HH:30:00`/`HH:50:00` — 10 minutes away from every cron fire. A
  same-slot double fire now ALWAYS computes the SAME bucket (it fires 600s from
  the nearest boundary), so the second process dedups on the recorded bucket and
  the durable hold-for-interval logic works as designed. Each cron slot still
  owns exactly one bucket, and a genuinely-new slot still reclaims the previous
  slot's lock.
- **Preserved invariants (non-negotiable):**
  - A FINISHED same-bucket owner (dead pid) STILL dedups a later re-fire
    (issue #30).
  - A NEW interval (different bucket) reclaims an OLDER-bucket lock exactly
    once.
  - A deduped process logs `[DEDUP] tick skipped ...` and does NOT log
    `tick start`.
  - A crash mid-tick leaves the lock held; the NEXT interval reclaims it.
- **No fallback.** One acquisition path. No behavior change to the atomic
  meta-lock (issue #62) — the meta-lock and the durable bucket remain exactly
  as merged in PR #71. This change only corrects WHERE the bucket boundary
  falls.
- **Regression test** (hermetic, `make test-unit`, no skips) extends
  `tests/test_watchloop_dispatch.py::TestTickDedup` with a boundary-straddle
  test that simulates two cron fires landing milliseconds apart on OPPOSITE
  sides of the OLD boundary instant and asserts they now map to the SAME bucket
  (so the second dedups) — the exact case that runs `main()` twice today.

## User-Visible Impact

No change to user-facing serving/model commands. The autonomous watch-loop
dispatcher becomes reliably idempotent per cron interval even when the doubled
`*/20` fire straddles the bucket boundary: exactly one `main()` per 20-min slot
(the case that currently double-runs).

## Non-Goals

- No change to the parallel-worktree model, the serialized-make lock, the
  spawn/merge/cleanup/repair stages, or how issues get their OpenSpec changes.
- No change to the atomic meta-lock design (#62) or the durable hold-for-interval
  semantics (#25/#27/#30) — only the bucket-boundary alignment changes.
- No change to the crontab cadence (still `*/20`).
