# fix-dispatch-doubled-tick-is-back-the-hold-for-int — spec of record

Capabilities this change adds to the watch-loop dispatcher's tick-dedup lock.

## ADDED Requirements

### Requirement: atomic read-decide-write of the per-tick lock
`_tick_lock_acquire()` MUST make the read → decide → write of `TICK_LOCK` a
single mutually-exclusive step, so two processes that both see an
OLD-bucket lock can never both delete-and-recreate it (the remove/create
TOCTOU). The decision MUST be taken under a short-lived advisory
`fcntl.flock(LOCK_EX|LOCK_NB)` meta-lock on a separate file; the meta-lock is
held only for the decision and released immediately after the write. The
durable dedup MUST remain the bucket recorded INSIDE `TICK_LOCK` (issue
#27/#30), NOT the meta-lock.

WHEN a process calls `_tick_lock_acquire()`, THEN the read of the recorded
owner, the dedup-vs-reclaim decision, and the write of this tick's
`(bucket, pid)` into `TICK_LOCK` happen atomically with respect to every other
`_tick_lock_acquire()` caller, so at most one caller wins per interval.

#### Scenario: concurrent reclaim yields exactly one winner
- **Given** an existing `TICK_LOCK` recording an OLDER bucket (a finished prior
  interval),
- **When** two processes interleave on the reclaim — one reads the old bucket
  and creates its lock before the other removes the stale lock,
- **Then** exactly ONE of the two returns `True` (the winner),
- **And** the other returns `False` (dedup) and does NOT run `main()`'s
  `tick start`,
- **And** `TICK_LOCK` ends recording the winner's bucket + pid.

#### Scenario: meta-lock is short-lived, not the durable lock
- **Given** a process has won the tick and written `TICK_LOCK(bucket,pid)`,
- **When** a later re-fire in the SAME interval reads the lock,
- **Then** it dedups on the recorded bucket (the meta-lock is no longer held,
  yet the durable bucket still suppresses the re-run),
- **And** the meta-lock file's presence does NOT, by itself, decide the dedup.

### Requirement: durable same-bucket and older-bucket invariants preserved
The atomic acquisition MUST NOT weaken the existing "hold-for-interval"
semantics: a FINISHED same-bucket owner (dead pid) MUST still dedup a re-fire
(issue #30), and a NEW interval MUST reclaim an OLDER-bucket lock exactly once.

WHEN the recorded owner holds THIS interval's bucket, THEN the tick is deduped
regardless of whether that owner is still alive; WHEN the recorded owner holds
an OLDER bucket, THEN the tick reclaims the lock and runs.

#### Scenario: finished same-bucket owner still dedups
- **Given** `TICK_LOCK` records the CURRENT bucket with a dead pid (a completed
  prior invocation of this interval),
- **When** a re-fire in the same interval calls `_tick_lock_acquire()`,
- **Then** it returns `False` (dedup) and the lock is left in place for the
  bucket,
- **And** the tick does NOT re-run (issue #30 invariant held).

#### Scenario: new interval reclaims the older bucket once
- **Given** `TICK_LOCK` records an OLDER bucket (the previous interval),
- **When** the wall clock advances to a new bucket and `_tick_lock_acquire()`
  is called,
- **Then** it returns `True` and rewrites the lock with the new bucket + pid,
- **And** a second call within the same new interval dedups.

### Requirement: deduped tick logs dedup, never tick start
A process whose `_tick_lock_acquire()` returns `False` MUST log
`[DEDUP] tick skipped ...` and MUST NOT log `tick start`.

#### Scenario: deduped main logs the skip line only
- **Given** another invocation has already acquired the current interval's
  tick lock,
- **When** `main()` is called again in the same interval,
- **Then** it logs a `[DEDUP]` skip line,
- **And** it does NOT log `tick start` and does NOT run the merge/spawn stages.

### Requirement: no fallback acquisition path
There MUST be exactly ONE acquisition path for the tick lock. There MUST be no
"if the meta-lock is busy just run anyway" branch and no second lock scheme;
if the atomic decision cannot be taken, the tick is SKIPPED (dedup), never
double-run.

#### Scenario: busy meta-lock skips, never runs
- **Given** the atomic decision cannot be taken because the meta-lock is held
  by another recoverer at the exact moment,
- **When** this process reaches the acquisition step,
- **Then** it dedups (returns `False`, logs the skip) rather than running a
  second tick.

### Requirement: containerized tests work from a git worktree
A git worktree stores its metadata in the PARENT repo's `.git/worktrees/<name>`
directory. The containerized test targets MUST work identically whether the
repo is a normal checkout (`.git` is a DIR) or a git worktree (`.git` is a
FILE containing `gitdir: <parent>/.git/worktrees/<name>`). When the repo is a
worktree, the test container MUST additionally mount the parent repo at its
real path so that `git ls-files` (and other git commands) resolve correctly.
When the repo is a normal checkout, the extra mount MUST be empty (no-op).

WHEN the Makefile computes `TEST_OPTS`, THEN if `.git` contains a `gitdir:`
line, the parent repo path is extracted and added as a second `-v` mount; if
`.git` is a directory (normal checkout), no extra mount is added.

#### Scenario: worktree test run sees git ls-files
- **Given** the repo is a git worktree (`.git` is a file pointing at the
  parent repo's `.git/worktrees/<name>` dir),
- **When** `make test-unit` runs inside the container,
- **Then** the parent repo is mounted at its real path,
- **And** `git ls-files` succeeds inside the container,
- **And** the lint regression tests pass.

#### Scenario: normal checkout has no extra mount
- **Given** the repo is a normal checkout (`.git` is a directory),
- **When** the Makefile computes `TEST_OPTS`,
- **Then** `GIT_WORKTREE_PARENT` is empty,
- **And** no extra `-v` mount is added to `TEST_OPTS`,
- **And** CI behaviour is byte-identical to before.
