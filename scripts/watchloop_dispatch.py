#!/usr/bin/env python3
"""llama-ai watch-loop DISPATCHER — host crontab entrypoint.

Model: each crontab tick runs THIS dispatcher, which:
  1. finalizes merge-ready PRs (green CI + APPROVED review + no open threads +
     NOT behind main), and
  2. for every open issue with no live branch/PR, spawns ONE dedicated background
     `project-manager` hermes worker in that issue's own worktree + own log, so
     issues are worked in PARALLEL and never serialize behind one another.

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


def process_merge_gate(prs) -> None:
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        n = pr["number"]
        if pr_is_behind(pr):
            log(f"  PR#{n}: behind main (or unverifiable) -> NOT merged")
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


# ------------------------------------------------------------------ spawner
def issue_has_pr(issue_num: int) -> bool:
    """True if some open PR's body CLOSES this issue (Closes/Fixes/Resolves #N).

    Uses a deliberate closing keyword, NOT a bare `#N` substring — a PR may mention
    another issue in prose (e.g. "the issue #9 guard") without closing it, and a
    substring match would wrongly suppress spawning a worker for that issue.
    """
    import re

    prs = api("/pulls?state=open&per_page=100")
    if not isinstance(prs, list):
        return False
    closes_re = re.compile(r"(?i)(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s*#\s*(\d+)")
    for pr in prs:
        body = pr.get("body") or ""
        for m in closes_re.finditer(body):
            if int(m.group(2)) == issue_num:
                return True
    # Fall back to the title: `Closes #N`-style is not the norm; require keyword too.
    return False


def ensure_worktree(branch: str, slug: str) -> str:
    subprocess.run(["git", "-C", REPO, "fetch", "origin", "main"], capture_output=True)
    wd = f"{REPO}/../llama-ai-wt/{slug}"
    if not os.path.isdir(wd):
        r = subprocess.run(
            ["git", "-C", REPO, "worktree", "add", "-b", branch, wd, "origin/main"],
            capture_output=True,
            text=True,
        )
        log(f"  worktree {wd} add rc={r.returncode}: {r.stderr.strip()[:120]}")
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
it (read {branch_log}); do not restart wasted. End final answer with a
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

    if os.path.exists(lk):
        log(f"  issue#{num}: worker already running ({lk}); skip")
        return
    ensure_worktree(branch, slug)
    prompt_file = f"{RUN}/worker-{branch.replace('/', '_')}.prompt"
    with open(prompt_file, "w") as f:
        f.write(worker_prompt(num, title, slug, branch, wd, branch_log))
    open(lk, "w").write(str(os.getpid()))
    cmd = (
        f"cd {wd} && HERMES_PROFILE=project-manager {HERMES} chat "
        f"--query-file {prompt_file} -t terminal,file,web --yolo -Q "
        f">> {branch_log} 2>&1"
    )
    log(f"  issue#{num}: spawning worker branch={branch} log={branch_log}")
    subprocess.Popen(["/bin/bash", "-lc", cmd], env=dict(os.environ))


# ---------------------------------------------------------------------- main
def main() -> None:
    log("tick start")

    prs = api("/pulls?state=open&per_page=100")
    if isinstance(prs, list):
        if "--dry" in sys.argv:
            log(f"  [DRY] skipping merge gate ({len(prs)} open PRs)")
        else:
            process_merge_gate(prs)
    else:
        log("  could not list PRs (API error); skipping merge gate")

    issues = api("/issues?state=open&per_page=100")
    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, dict) or "pull_request" in issue:
                continue
            num = issue["number"]
            if issue_has_pr(num):
                log(f"  issue#{num}: PR in flight, no spawn")
                continue
            if "--dry" in sys.argv:
                log(f"  issue#{num}: [DRY] would spawn worker for '{issue['title']}'")
                continue
            spawn_worker(issue)
    log("tick done")


if __name__ == "__main__":
    main()
