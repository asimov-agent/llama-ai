# Issue #73 — doubled tick boundary straddle (fixed)

Date: 2026-09-08

## Symptom (production)
The `*/20` cron dispatcher ran `main()` TWICE per slot — paired
`tick start`→`tick done` in `.watchloop/run/dispatch.log`, e.g. at 19:40 both
runs independently logged `stale lock pid dead; removing + resuming worker`
and both logged `spawning worker`. The `.running` lock masked it downstream
(one live worker), but the merge gate / cleanup / repair all ran 2× per slot.

## Root cause
`_current_tick() = f"tick-{int(time.time()) // 1200}"`. The bucket boundary
landed EXACTLY on the `*/20` cron fire instants (`:00`/`:20`/`:40`) because the
host TZ offset is a whole number of hours. A doubled fire straddling the
boundary computed DIFFERENT buckets, so process B saw A's lock as an OLDER
bucket ("finished prior interval") and reclaimed it → both ran `main()`.
Confirmed by table: 17:59:59.99 → bucket 1490735, 18:00:00.01 → bucket 1490736.

## Fix
Shift the boundary forward by `TICK_INTERVAL_SECONDS // 2` (600s) so it lands
at `:10`/`:30`/`:50`, 10 min from every cron fire. A same-slot doubled fire
always maps to ONE bucket and dedups. Durable hold-for-interval semantics
(#25/#27/#30) and the atomic meta-lock (#62) unchanged.

## Verification
- New tests `test_doubled_fire_straddling_old_boundary_same_bucket` +
  `test_doubled_fire_straddle_dedups_not_reclaims`: RED on old code
  (log shows the exact `reclaiming finished interval tick-1788882 for
  tick-1788883` bug), GREEN on fix.
- `make lint` GREEN · `make test-unit` 172 passed · `make test-agents-e2e`
  2 passed · `make openspec-validate` exit 0 · `make openspec-tasks-check` OK.
- Real CI on PR #74: all 9 jobs GREEN (dispatch-e2e, unit, lint, top-tier,
  install, cpu-health, cron, openspec, agents-read). mergeStateStatus CLEAN.

## Status
PR #74 open against main, Closes #73, awaiting review/merge.
