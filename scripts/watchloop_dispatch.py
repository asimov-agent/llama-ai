#!/usr/bin/env python3
"""llama-ai watch-loop DISPATCHER — host crontab entrypoint.

Model: each crontab tick runs THIS dispatcher, which:
  1. finalizes merge-ready PRs (green CI + APPROVED review + no open threads +
     NOT behind main), and
  2. for every open issue with no live branch/PR, spawns ONE dedicated background
     `project-manager` hermes worker in that issue's own worktree + own log, so
     issues are worked in PARALLEL and never serialize behind one another.

NEVER-MERGE-BEHIND GATE (issue #9): a PR whose head is behind `main` is NEVER
merged out of sync. The dispatcher does NOT merely skip such a PR — it
forward-merges `origin/main` into the PR branch (rebase/merge-and-resolve), then
re-attempts the gate after CI re-runs. Merge conflicts are surfaced to the
branch's worker, never silently auto-resolved or force-deleted.

PARALLEL-SAFETY:
  * every containerized `make` step inside a worker runs under a shared flock keyed
    on .watchloop/run/test.lock, so only one worker drives nerdctl at a time.
  * the loop-harness uses a dedicated image + orchestration; the dispatcher never
    starts/invokes it and workers are forbidden from running it.
  * each worker uses its OWN git worktree and writes its OWN log.
No worker time limit => a big issue may span ticks and resume from its own log.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = "/Users/andy/repository/git/llama-ai"
LOGS = f"{REPO}/.watchloop/logs"
RUN = f"{REPO}/.watchloop/run"
API = "https://api.github.com/repos/asimov-agent/llama-ai"
HERMES = "/Users/andy/.local/bin/hermes"

os.makedirs(LOGS, exist_ok=True)
os.makedirs(RUN, exist_ok=True)


def load_token() -> str:
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    try:
        with open(f"{REPO}/.env") as f:
            for line in f:
                line = line.strip()
                for var in ("GITHUB_TOKEN", "GH_TOKEN"):
                    if line.startswith(f"{var}="):
                        return line.split("=", 1)[1].strip().strip("\"'")
    except FileNotFoundError:
        pass
    raise SystemExit("[dispatch] no GITHUB_TOKEN found")


TOK = load_token()
HEADER = {"Authorization": f"Bearer {TOK}", "Accept": "application/vnd.github+json"}


def api(path: str, method: str = "GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, headers=HEADER, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError:
        return None  # fail closed: any API problem -> don't act


def log(msg: str) -> None:
    line = f"[dispatch {time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(f"{RUN}/dispatch.log", "a") as f:
        f.write(line + "\n")


# ------------------------------------------------------------------ helpers
def pr_is_behind(pr) -> bool:
    """True if PR head is BEHIND main / unverifiable (never merge those)."""
    cmp = api(f"/compare/{pr['base']['sha']}...{pr['head']['sha']}")
    if not isinstance(cmp, dict):
        return True
    return cmp.get("status") not in ("identical", "ahead")


def pr_approved(pr_num: int) -> bool:
    rv = api(f"/pulls/{pr_num}/reviews")
    if not isinstance(rv, list):
        return False
    return any(r.get("state") == "APPROVED" for r in rv)


def pr_open_threads(pr_num: int) -> bool:
    comments = api(f"/pulls/{pr_num}/comments")
    reviews = api(f"/pulls/{pr_num}/reviews/comments")
    if not isinstance(comments, list):
        comments = []
    if not isinstance(reviews, list):
        reviews = []
    return any(not c.get("resolved", True) for c in comments + reviews)


def ci_green(pr) -> bool:
    checks = api(f"/commits/{pr['head']['sha']}/check-runs")
    if not isinstance(checks, dict) or "check_runs" not in checks:
        return False  # no checks data -> not green
    runs = checks["check_runs"]
    if not runs:
        return True  # no checks configured
    for cr in runs:
        if cr.get("status") == "completed" and cr.get("conclusion") in (
            "failure",
            "cancelled",
            "timed_out",
        ):
            return False
        if cr.get("status") in ("queued", "in_progress"):
            return False
    return True


def merge_pr(pr) -> None:
    n = pr["number"]
    log(f"MERGING PR #{n} ({pr['head']['ref']} -> main)")
    res = api(f"/pulls/{n}/merge", method="PUT", body={"merge_method": "merge"})
    log(f"  merge result: {str(res)[:160]}")


def run_git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)


def sync_pr_with_main(pr) -> bool:
    """Bring a behind PR's head up to date with latest origin/main (issue #9).

    issue #9: a PR that is behind main MUST NOT be merged out of sync. Instead of
    merely skipping it, forward-merge origin/main into the PR branch so it no longer
    drifts, then let CI re-run so the gate re-attempts on a later tick. Conflicts are
    never auto-resolved — if a merge conflict arises, leave the branch for its worker
    to resolve and return False (the PR stays NOT merged).
    Returns True if the PR head is now in sync with origin/main, False otherwise.
    """
    head_ref = pr["head"]["ref"]
    head_sha = pr["head"]["sha"]
    n = pr["number"]
    r = run_git("fetch", "origin", f"+refs/heads/{head_ref}:refs/remotes/origin/{head_ref}")
    if r.returncode != 0:
        log(f"  PR#{n}: sync fetch failed for {head_ref}: {r.stderr.strip()[:120]}")
        return False
    run_git("branch", "-D", "_dispatch_sync")  # clear any stale temp branch
    r = run_git("branch", "_dispatch_sync", f"origin/{head_ref}")
    if r.returncode != 0:
        log(f"  PR#{n}: cannot create temp sync ref: {r.stderr.strip()[:120]}")
        return False
    r = run_git(
        "merge", "origin/main", "--no-ff",
        "-m", f"chore: sync to latest origin/main before merge (issue #9, PR #{n})",
    )
    if r.returncode != 0:
        run_git("merge", "--abort")
        run_git("branch", "-D", "_dispatch_sync")
        log(f"  PR#{n}: merge conflict syncing {head_ref} onto origin/main -> needs manual "
            f"resolution, NOT merged (issue #9)")
        return False
    # Advance the PR branch to the synced head. force-with-lease pins to the known sha
    # so we never clobber newer commits a worker pushed concurrently.
    r = run_git(
        "push", "origin", "_dispatch_sync:" + head_ref,
        f"--force-with-lease={head_ref}:{head_sha}",
    )
    run_git("branch", "-D", "_dispatch_sync")
    if r.returncode != 0:
        log(f"  PR#{n}: sync push failed for {head_ref}: {r.stderr.strip()[:160]}")
        return False
    log(f"  PR#{n}: {head_ref} synced to origin/main (merge forward); CI must re-run, "
        "re-attempting gate next tick")
    return True


def process_merge_gate(prs) -> set:
    """Merge merge-ready PRs; return the set of issue numbers closed this tick."""
    resolved_this_tick: set = set()
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        n = pr["number"]
        if pr_is_behind(pr):
            log(f"  PR#{n}: behind main (or unverifiable) -> NEVER merge as-is (issue #9)")
            if sync_pr_with_main(pr):
                log(f"  PR#{n}: synced to origin/main; will re-attempt gate after CI ")
            continue
        if not pr_approved(n):
            log(f"  PR#{n}: not approved -> NOT merged")
            continue
        if pr_open_threads(n):
            log(f"  PR#{n}: open threads -> NOT merged")
            continue
        if not ci_green(pr):
            log(f"  PR#{n}: CI not green -> NOT merged")
            continue
        merge_pr(pr)
        resolved_this_tick |= closing_issues(pr.get("body") or "")
    return resolved_this_tick


# ------------------------------------------------------------------ spawner
def closing_issues(body) -> set:
    """Return the set of issue numbers a PR body explicitly claims to close.

    Uses a deliberate closing keyword (Closes/Fixes/Resolves #N), NOT a bare
    `#N` substring — a PR may mention another issue in prose (e.g. "the issue
    #94 guard") without closing it, and a substring match would wrongly suppress
    spawning a worker for that issue.
    """
    if not body:
        return set()
    closes_re = re.compile(r"(?i)(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s*#\s*(\d+)")
    return {int(m.group(2)) for m in closes_re.finditer(body)}


def pid_alive(pid: int) -> bool:
    """True only if *pid* is a live process on this host."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def issue_has_pr(issue_num: int) -> bool:
    """True if ``some open PR's body CLOSES this issue (Closes/Fixes/Resolves #N).``"""
    prs = api("/pulls?state=open&per_page=100")
    if not isinstance(prs, list):
        return False
    return any(issue_num in closing_issues(pr.get("body") or "") for pr in prs)


def ensure_worktree(branch: str, slug: str) -> str:
    wd = f"{REPO}/../llama-ai-wt/{slug}"
    # Always refresh the remote tip first so BOTH new and existing worktrees
    # branch/resume from the newest origin/main, not a stale one.
    subprocess.run(["git", "-C", REPO, "fetch", "--all", "--prune"], capture_output=True)
    subprocess.run(["git", "-C", REPO, "fetch", "origin", "main"], capture_output=True)

    def rebase_if_behind():
        """Rebase <branch> onto the latest origin/main if it is behind."""
        r = subprocess.run(
            ["git", "-C", wd, "merge-base", "--is-ancestor", "origin/main", "HEAD"],
            capture_output=True,
        )
        if r.returncode == 0:
            return  # already at/after main
        subprocess.run(["git", "-C", wd, "rebase", "origin/main"], capture_output=True)
        log(f"  rebased {branch} onto latest origin/main (was behind)")

    if not os.path.isdir(wd):
        r = subprocess.run(
            ["git", "-C", REPO, "worktree", "add", "-b", branch, wd, "origin/main"],
            capture_output=True,
            text=True,
        )
        log(f"  worktree {wd} add rc={r.returncode}: {r.stderr.strip()[:120]}")
    else:
        # Existing worktree: bump the branch to the current remote tip before
        # the worker resumes — never let an approved/PR branch sit behind main.
        rebase_if_behind()
    return wd


def worker_prompt(num: int, title: str, slug: str, branch: str, wd: str, branch_log: str) -> str:
    return f"""You are the DEDICATED worker for llama-ai issue #{num} ("{title}").

Context: repo={REPO}, worktree={wd}, branch={branch}. AGENTS.md is loaded (cwd)
and is your durable rulebook — follow its Background watch loop + OpenSpec-first
+ continuous sync rules. Work ONLY this one issue.

PARALLEL-SAFETY (MANDATORY, non-negotiable): this worker runs in PARALLEL with
other issue workers on the SAME machine. To avoid any collision on the shared
nerdctl test container or the loop-harness:
  * Run EVERY containerized `make` target (openspec-*, test-unit, test-install,
    lint, lint-fix, test) through the shared lock via the helper (macOS has no
    `flock` command):
        python3 {REPO}/scripts/serialized-make.py {REPO}/.watchloop/run/test.lock -- <target> <args>
    This blocks until the lock is free, so only one worker drives the container
    at a time.
  * NEVER run `make loop-harness`, `make test-install-host`, or `make test` — those
    are the harness's own orchestrated steps.
  * Work ONLY in {wd} on {branch}. Push only {branch} to origin.
  * If a run is interrupted, the lock auto-releases when the helper process ends.

Per the issue body + AGENTS.md:
1) OpenSpec change FIRST: cd {wd} && make openspec-new NAME={slug}. Write
   proposal.md/spec/tasks describing the change (docs-only => skip_specs:true).
2) Implement in {wd} on {branch}.
3) STAGE FIRST, then Validate (all via flock): git -C {wd} add -A; then
   openspec-validate NAME={slug} exit 0; lint-fix (scripts/lint_linefeeds.py --fix so
   any fresh file's missing trailing newline is repaired NOW); lint; test-unit. Run lint
   AGAIN after staging so freshly-written files are picked up by git ls-files.
4) Keep issue body, OpenSpec change, and code/files in sync.
5) Push: git -C {wd} push origin {branch} (use URL-embedded token from {REPO}/.env
   if the keyring token is revoked).
6) Open a PR against main referencing issue #{num} (curl, token from {REPO}/.env).
   PR body MUST reference it, and per issue #9 never merge if behind main.
7) APPEND your progress to {branch_log} (your own log only).

Resume: if a prior tick already scaffolded OpenSpec or opened partial work, continue
it (read {branch_log}); do not restart wasted. ALWAYS first bring the branch up to
date: run `git -C {wd} fetch origin main` and, if your branch tip is BEHIND
origin/main (`git merge-base --is-ancestor origin/main HEAD` fails), run
`git -C {wd} rebase origin/main` and resolve any conflicts yourself before
continuing work — never sit behind main (issue #9). If you rebased a branch that
already has an open PR, update it with `git push --force-with-lease`, never a
plain force-push and never push to main. End final answer with a
'WATCH-LOOP SUMMARY'. No time limit.
"""


def spawn_worker(issue) -> None:
    num = issue["number"]
    title = issue["title"]
    slug = (re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or f"issue-{num}")[:50]
    branch = f"feat/{slug}"
    wd = f"{REPO}/../llama-ai-wt/{slug}"
    branch_log = f"{LOGS}/feat-{slug}.log"
    lk = f"{RUN}/worker-{branch.replace('/', '_')}.running"

    # ATOMIC lock acquire: os.open with O_CREAT|O_EXCL is an atomic
    # check-and-create — exactly one of N concurrent dispatchers wins, the
    # rest get EEXIST. This closes the TOCTOU race where two dispatchers both
    # pass os.path.exists(lk) and both spawn a worker (issue #23 doubled tick).
    # We hold the lock file open until the worker's real PID is recorded.
    lk_fd = None
    try:
        lk_fd = os.open(lk, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        lk_fd = None  # lock already exists -> owned by a (live or stale) worker

    if lk_fd is None:
        # Lock exists. Check whether the owner PID is alive.
        try:
            live_pid = int((open(lk).read() or "0").strip() or 0)
        except (ValueError, OSError):
            live_pid = 0
        if pid_alive(live_pid):
            log(f"  issue#{num}: worker already running (pid={live_pid}, {lk}); skip")
            return
        # Stale lock from a dead worker: someone must reclaim it. Remove then
        # re-create with O_EXCL. If another dispatcher wins the race, skip.
        try:
            os.remove(lk)
            lk_fd = os.open(lk, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            log(f"  issue#{num}: lock re-acquired elsewhere; skip")
            return
        log(f"  issue#{num}: stale lock pid={live_pid} dead; removing + resuming worker")

    ensure_worktree(branch, slug)
    prompt_file = f"{RUN}/worker-{branch.replace('/', '_')}.prompt"
    with open(prompt_file, "w") as f:
        f.write(worker_prompt(num, title, slug, branch, wd, branch_log))
    cmd = (
        f"cd {wd} && HERMES_PROFILE=project-manager {HERMES} chat "
        f"--query-file {prompt_file} -t terminal,file,web --yolo -Q "
        f">> {branch_log} 2>&1"
    )
    log(f"  issue#{num}: spawning worker branch={branch} log={branch_log}")
    proc = subprocess.Popen(["/bin/bash", "-lc", cmd], env=dict(os.environ))
    # Record the worker child PID (bash that waits on hermes chat), not our own,
    # so the lock reflects a real worker and a dead PID is detectable next tick.
    os.write(lk_fd, str(proc.pid).encode())
    os.close(lk_fd)


# ---------------------------------------------------------------------- main
TICK_LOCK = f"{RUN}/dispatch.tick.lock"

# The cron slot fires every */20 minutes. Two cron fires in the same coarse
# interval bucket are "the same tick". A plain O_CREAT|O_EXCL lock that is
# released synchronously at main()'s end only catches a *tight* overlap window:
# once the first invocation finishes (and its finally-release deletes the lock),
# a re-fire in the same interval re-acquires and runs again -- the phantom
# double-fire. Holding the lock for the whole interval (released only when the
# bucket changes) is what makes "exactly one main() per cron tick" durable.
TICK_INTERVAL_SECONDS = 20 * 60


def _current_tick() -> str:
    """Coarse cron-interval bucket for the current wall-clock moment.

    Two cron fires in the same bucket are the 'same tick'. A monotonic string
    bucket (rather than a raw O_CREAT|O_EXCL file) is what makes the dedup
    durable: a finished invocation's lock-release no longer lets a re-fire in
    the same interval re-acquire -- the interval owns the lock until it changes.
    """
    return f"tick-{int(time.time()) // TICK_INTERVAL_SECONDS}"


def _read_lock_owner() -> tuple[str, int]:
    """Return (bucket, pid) recorded in the tick lock, or ('', 0) if absent."""
    try:
        with open(TICK_LOCK) as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return "", 0
    bucket = lines[0] if len(lines) >= 1 else ""
    try:
        pid = int(lines[1]) if len(lines) >= 2 else 0
    except ValueError:
        pid = 0
    return bucket, pid


def _tick_lock_acquire() -> bool:
    """Acquire the per-tick dedup lock for THIS cron interval.

    Robust against the phantom double-fire (issue #25): unlike a plain
    O_CREAT|O_EXCL lock that is released synchronously at main()'s end, this
    holds the lock for the whole interval so a phantom re-fire in the same bucket
    dedups EVEN IF the first invocation already finished. The lock is only
    released when a NEW interval (bucket) starts.

    Returns True if THIS tick should run:
      * fresh lock (no owner) -> win, write our bucket+PID
      * owner holds THIS bucket AND live -> dedup (return False, no tick start)
      * owner holds an OLDER bucket (finished previous interval) -> reclaim
      * owner stale/foreign -> remove + recreate atomically
    """
    bucket = _current_tick()

    # Reclaim a finished previous interval: an older-bucket lock is stale for
    # THIS tick, so clear it before the atomic create.
    old_bucket, old_pid = _read_lock_owner()
    if old_bucket and old_bucket != bucket and pid_alive(old_pid):
        log(f"  [DEDUP] reclaiming finished interval {old_bucket} for {bucket}")

    fd = None
    try:
        fd = os.open(TICK_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        # Lock exists. Is its owner THIS interval and live?
        owner_bucket, owner_pid = _read_lock_owner()
        if owner_bucket == bucket and pid_alive(owner_pid):
            return False  # THIS interval already running -> dedup, no tick start
        # Stale/foreign lock: remove + recreate atomically (race on recoverer).
        try:
            os.remove(TICK_LOCK)
            fd = os.open(TICK_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return False  # raced with another recoverer

    os.write(fd, f"{bucket}\n{os.getpid()}\n".encode())
    os.close(fd)
    return True


def _tick_lock_release(current_bucket: str) -> None:
    """Release the tick lock ONLY when a NEW interval (current_bucket) starts.

    An older-bucket holder is a finished previous interval; clear it so the new
    interval acquires cleanly. A same-bucket holder means we are mid-tick -- do
    NOT release (that would permit a phantom re-fire to steal this tick). The
    lock is intentionally NOT released at main()'s end, unlike the fragile
    version it replaces: durability for the whole interval is the point.
    """
    held_bucket, held_pid = _read_lock_owner()
    if held_bucket and held_bucket != current_bucket:
        try:
            os.remove(TICK_LOCK)
        except OSError:
            pass


def main() -> None:
    bucket = _current_tick()
    if not _tick_lock_acquire():
        log("[DEDUP] tick skipped: a previous invocation is already running this interval")
        return
    try:
        log("tick start")
        prs = api("/pulls?state=open&per_page=100")
        resolved_this_tick: set = set()
        if isinstance(prs, list):
            if "--dry" in sys.argv:
                log(f"  [DRY] skipping merge gate ({len(prs)} open PRs)")
            else:
                resolved_this_tick = process_merge_gate(prs)
        else:
            log("  could not list PRs (API error); skipping merge gate")

        issues = api("/issues?state=open&per_page=100")
        if isinstance(issues, list):
            for issue in issues:
                if not isinstance(issue, dict) or "pull_request" in issue:
                    continue
                num = issue["number"]
                if num in resolved_this_tick:
                    log(f"  issue#{num}: resolved by PR merged this tick; no spawn")
                    continue
                if issue_has_pr(num):
                    log(f"  issue#{num}: PR in flight, no spawn")
                    continue
                if "--dry" in sys.argv:
                    log(f"  issue#{num}: [DRY] would spawn worker for '{issue['title']}'")
                    continue
                spawn_worker(issue)
        log("tick done")
    except Exception:
        # Intentionally NO finally-release: the lock stays held for this interval
        # so a phantom re-fire in the same bucket dedups. A crash mid-tick leaves
        # a live-PID lock that the NEXT interval (different bucket) reclaims via
        # _tick_lock_acquire(), which removes it atomically.
        log("[DEDUP] tick crashed mid-run; lock stays held until next interval")
        raise


if __name__ == "__main__":
    main()
