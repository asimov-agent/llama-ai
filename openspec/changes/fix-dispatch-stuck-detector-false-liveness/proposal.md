# Fix stuck-detector killing productive workers — hermes chat never streams to the log until exit (issue #69)

## Why

Open issues #61 and #62 produced NO PR after ~5h and 26+19 worker spawns. The dispatcher log showed an endless kill/respawn cycle:

```
issue#62: worker stuck (pid=…, log stale > 2400s); killing tree + resuming
issue#62: spawning worker …
issue#61: worker stuck (pid=…, log stale > 2400s); killing tree + resuming
issue#61: spawning worker …
```

The workers were **not** hung — issue #62's worktree holds a complete OpenSpec change plus a 44-line fix to `watchloop_dispatch.py` (uncommitted), and the profile `agent.log` shows active `llm-local` API calls every 1–2 min.

### Root cause: `hermes chat` does not stream to the worker log until it exits

Issue #63's liveness check (`worker_is_stuck`) reclaims a worker whose PID is alive **and** whose own `feat-<slug>.log` has not grown for `STUCK_LOG_STALE_SECONDS` (2400 s). That check implicitly assumes a working worker's log advances. Controlled experiments (2026-09-08) disprove it:

| launch form | result while running |
|---|---|
| `hermes chat -Q … >> log 2>&1` | log frozen at the startup warning for the whole run |
| `hermes chat --oneshot … >> log` | log frozen at "Initializing agent…" |
| `PYTHONUNBUFFERED=1` + `python3 -u` | identical — still frozen |
| under a PTY via `script` | identical — still frozen |

`hermes chat` buffers its entire stdout in non-interactive/oneshot mode and flushes **only at process exit**. Tool/agent activity goes to the profile `agent.log`, never to the spawn's stdout. So a productive-but-slow worker — which legitimately needs well over 40 min on the slow local `llm-local` to do OpenSpec → implement → validate → lint → test-unit → commit → push → PR — is indistinguishable from a hung one by log mtime and is killed every ~40 min before it can commit. Each respawn restarts from a sparse log; nothing ever reaches a PR.

## What changes

Replace the log-mtime liveness signal with a **worker heartbeat** so a live, working worker is never killed on a short timer, while a genuinely hung worker (process alive but making no forward progress) is still reclaimed on a much longer true-hang horizon.

Specifically:

1. **The spawn wrapper writes a heartbeat.** The worker launch command is wrapped so a small supervisor appends a timestamp to the worker's own `feat-<slug>.log` every `WORKER_LOG_HEARTBEAT_SECONDS` (default 5 min) as long as the hermes child process is alive. A live worker's log therefore advances continuously regardless of hermes stdout buffering.
2. **Stuck detection keys off a much longer true-hang horizon.** `STUCK_LOG_STALE_SECONDS` default rises from 2400 s (40 min) to `WORKER_TRUE_HANG_SECONDS` (default 3 h) so only a worker whose log (now heartbeat-fed) has been silent for a genuinely long time is reclaimed. Because the heartbeat advances a live worker's log every 5 min, a silent log past the horizon now genuinely means "no heartbeat for hours" — i.e. the worker is not making progress.
3. **Dead-PID path unchanged.** A worker whose PID is gone is still cleaned and respawned immediately (issue #18).
4. **Hermes must not need to stream** — the fix is entirely on the dispatcher side, so it works regardless of how `hermes chat` buffers output.

The result: productive workers are never killed mid-work (fixing #69), and a truly hung worker is still reclaimed (keeping issue #63's goal) but only after a horizon that no productive worker can plausibly exceed.

## Out of scope

- Changing how `hermes chat` buffers output (out of this repo's control).
- Making workers commit incrementally (a separate improvement, not required to stop the starvation).
- Any change to the merge gate, tick dedup, or cleanup sweeps.
