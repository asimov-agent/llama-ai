# fix-dispatch-tick-boundary-straddle — spec of record

Capabilities this change adds to the watch-loop dispatcher's tick-dedup lock.

## ADDED Requirements

### Requirement: tick-bucket boundary does not fall on a cron fire instant
`_current_tick()` MUST return a bucket whose boundary falls at least
`TICK_INTERVAL_SECONDS // 2` away from every `*/20` cron fire instant, so a
same-slot doubled fire (which fires milliseconds apart at the `:00`/`:20`/`:40`
wall-clock minute) ALWAYS computes the SAME bucket and the second process dedups
on the recorded bucket instead of reclaiming it as a "finished prior interval".

WHEN `_current_tick()` is called at any moment within a 20-min cron slot,
THEN the returned bucket is stable across the WHOLE slot INCLUDING the old
epoch-`//1200` boundary instant that previously split a single slot into two
buckets, AND a re-fire milliseconds away on either side of that old boundary
maps to the SAME bucket.

#### Scenario: doubled fire straddling the old boundary dedups
- **Given** the old bucket boundary instant `T` where `int(T) % 1200 == 0`
  (which the `*/20` cron fire lands on),
- **When** process A fires one millisecond before `T` and process B fires one
  millisecond after `T` (the same cron slot firing twice),
- **Then** `_current_tick()` returns the SAME bucket for both A and B,
- **And** when B calls `_tick_lock_acquire()` it returns `False` (dedup) and
  does NOT reclaim A's lock,
- **And** `main()` runs exactly once for that slot (no paired `tick start`).

#### Scenario: a genuinely new slot still reclaims the previous slot
- **Given** `TICK_LOCK` records the bucket for the PREVIOUS cron slot,
- **When** the wall clock advances to a new cron slot (20 minutes later),
- **Then** `_tick_lock_acquire()` returns `True` and rewrites the lock with the
  new slot's bucket + pid,
- **And** a second call within the same new slot dedups.

### Requirement: preserved durable hold-for-interval invariants
The boundary-offset change MUST NOT weaken any existing durable tick-lock
semantics from issues #25/#27/#30/#62: a FINISHED same-bucket owner (dead pid)
still dedups a later re-fire; a deduped process logs `[DEDUP]` and never
`tick start`; a crash mid-tick leaves the lock held for the next interval; and
the atomic read→decide→write meta-lock (issue #62) is unchanged.

WHEN the recorded owner holds THIS interval's bucket, THEN the tick is deduped
regardless of whether that owner is still alive; WHEN the recorded owner holds
an OLDER bucket, THEN the tick reclaims the lock and runs.

#### Scenario: finished same-bucket owner still dedups
- **Given** `TICK_LOCK` records the CURRENT bucket with a dead pid (a completed
  prior invocation of this interval),
- **When** a re-fire in the same interval calls `_tick_lock_acquire()`,
- **Then** it returns `False` (dedup) and the lock is left in place,
- **And** the tick does NOT re-run (issue #30 invariant held).

#### Scenario: deduped main logs the skip line only
- **Given** another invocation has already acquired the current interval's tick
  lock,
- **When** `main()` is called again in the same interval,
- **Then** it logs a `[DEDUP]` skip line,
- **And** it does NOT log `tick start` and does NOT run the merge/spawn stages.

#### Scenario: no fallback acquisition path
- **Given** the module defines `_tick_lock_acquire`,
- **When** the atomic decision cannot be taken because the meta-lock is held by
  another recoverer at the exact moment,
- **Then** it dedups (returns `False`, logs the skip) rather than running a
  second tick — there is NO "busy ⇒ run anyway" branch.
