# Project Instructions for Hermes Agent in llama-ai

You are working in a small, self-contained repository that serves GGUF models
locally via llama.cpp's `llama-server`. This file defines the agent's durable
workflow. Follow it for any change.

## Execution environment

- **Foreground `terminal` calls run on the real host** (`~/repository/git/llama-ai`).
  This is a plain macOS host with `node`/`npm`, `nerdctl` (Colima containerd),
  a gguf Python 3.10 venv at `~/llama-gguf-tools/.venv`, and a populated
  `~/models/**/*.gguf` tree. There is no separate sandbox — the host is canonical.
- Verify through the Makefile with real output. Prefer `make <target>` over
  hand-running the underlying tools so the defined gates are exercised.

## OpenSpec is the checklist of record (MANDATORY)

Before implementing/answering a work request, convert it into an OpenSpec change
in this repo and drive it with the Dockerized CLI:

```bash
make openspec-new NAME=<kebab-name>        # openspec new change <name> via the container
# write proposal.md[/design.md] + specs/<cap>/spec.md + tasks.md
make openspec-validate NAME=<kebab-name>   # must pass before you claim done
```

Rules:

- **OpenSpec change + tasks FIRST, then implementation.** For every change,
  create the OpenSpec change (`make openspec-new NAME=<name>`) and write
  `proposal.md` + `specs/<cap>/spec.md` + `tasks.md` BEFORE implementing any code
  and BEFORE creating the feature branch or opening the PR. This keeps every
  change spec-tracked from its start (review-required discipline).
- **Create/validate through the CLI, never by hand-writing the change dir.**
  The CLI runs inside the `openspec/` container with the repo mounted at `/repo`
  (RUNTIME auto-detected: nerdctl → docker). `openspec/` Dockerfile +
  `docker-compose-files/openspec.yaml` define it; `make openspec-image` builds it.
- **Every implemented step maps to a task.** Keep `openspec/changes/<name>/tasks.md`
  as a tracked `- [ ]` checklist. **Tick each task the moment the work is verified** —
  never complete work while leaving the checklist item unticked.
- **Validate before declaring done:** `make openspec-validate NAME=<name>` must exit 0.
- **A change is "done" only after the loop gate is green** (see below). The final
  task in `tasks.md` MUST be a verification you can tick the moment the work is
  done — never a command like "run make phase7-archive" (which doesn't exist here)
  and never the loop command itself.
- **All changes MUST be committed and pushed to the current feature branch.** Do
  NOT wait for a human to ask. Commit each batch of completed work with a typed
  Conventional Commit message and push it to `origin feat/<branch>` as you go, so
  work never sits uncommitted. Never force-push / rewrite history, never commit
  `.env` or real secrets, and never push directly to `main`.
- **Every work item's GOAL lives in the GitHub issue; the issue drives the whole
  lifecycle (MANDATORY).** Each work item starts as a GitHub issue (the *issue
  file*). The issue's goal, the feature branch, the OpenSpec change, and the PR
  that closes it are one pipeline — the issue is the root, and every downstream
  artifact must trace back to it and describe the SAME objective:
  - **Issue → feature branch → OpenSpec change → code → PR.** Creating an issue
    means a feature branch will be created off `main` for it, that branch carries
    the OpenSpec change (created first) + the implementation, and the work ends
    by opening the PR against `main` from that branch. The PR body MUST reference
    the issue so the issue and PR are linked.
  - **Sync-back is bidirectional and continuous — even when BOTH an issue and a
    PR already exist.** If you change the OpenSpec change (`proposal.md`,
    `specs/**/spec.md`, `tasks.md`), you MUST update the issue body AND the code /
    files accordingly so the implementation reflects the OpenSpec change — and
    vice-versa. The OpenSpec change is the checklist of record and the driver of
    the code; the issue is what a reviewer reads to understand the PR. They must
    NEVER contradict each other. Any change to one MUST be mirrored in the others
    in the same commit batch:
    - change **goal** (scope/objective/acceptance, the `Why`/`What Changes` of
      the proposal) → update the issue body AND the OpenSpec change AND the code
      it implies, together;
    - change **code** (implementation) → make sure it matches the OpenSpec spec
      and is reflected in the issue;
    - change **OpenSpec** (proposal/spec/tasks) → update the issue and, where the
      spec implies a code change, the code.
  - Treat any drift between the issue, the OpenSpec change, and the code/files as
    a workflow defect. The OpenSpec change is the referee: if there is a conflict,
    the code and the issue must conform to the OpenSpec change, not the reverse.
  - When starting/resuming work, if the issue's goal and the OpenSpec change are
    out of sync, reconcile them FIRST (update whichever is behind to match the
    intended goal) before implementing.
  - If a work request arrives without an issue (e.g. ad-hoc chat), create the
    GitHub issue as part of converting it into an OpenSpec change and a feature
    branch, so every OpenSpec change and PR trace to a GitHub issue that mirrors
    the goal.

## Background watch loop — poll PRs/CI and drive new issues (MANDATORY)

This repo runs an autonomous background loop so nothing sits un-driven between
interactive sessions. The loop is a **host crontab** entry (not the in-process
Hermes scheduler, whose ~3-min hard interrupt is too short for a full issue
pipeline). Every 20 minutes, it launches a fresh one-shot **`project-manager`
Hermes session** with cwd set to this repo (`cd` to the repo before invoking),
which loads THIS file as the session's durable rules. The first thing that session
always does is poll the project's GitHub state, so the repo is self-driving:

1. **Poll PRs + CI first, every tick.** On session start (and on each loop tick),
   list all open PRs against `main`, read every review/comment thread on each,
   and check every PR's CI checks:
   ```bash
   gh pr list --state open --base main
   # per PR: gh pr view <N> --json reviews,comments,statusCheckRollup
   ```
   Whenever a PR's CI is fully GREEN **and** it has an approval **and** no open
   review threads, merge it to `main` and clean up both branches and the merged
   PR locally. This is the only way approved work moves to `main` — never push
   to `main` directly.
2. **Every open issue must have a branch + PR in flight.** List all open issues;
   for each, confirm a feature branch exists and a PR references it. If an issue
   has NO live branch/PR yet (or is new), **start work on it immediately** — see
   the worktree workflow below — because every issue must end at a PR against
   `main`.
3. **Reconcile drift as part of the loop.** Any issue whose goal does not match
   its OpenSpec change and code is reconciled (per the sync rule above) before
   doing anything else on it.

### Issue → git worktree (MANDATORY for background work)

Because the cron loop may start several issues' work concurrently, do NOT branch
the checked-out working tree. For each new issue you start, create an isolated
**git worktree** off `main`:

```bash
git worktree add -b feat/<kebab-name> ../llama-ai-wt/<kebab-name> main
# work inside ../llama-ai-wt/<kebab-name>: OpenSpec change first, then implement
```

- The worktree lives OUTSIDE the main checkout (sibling dir), so parallel issues
  don't collide and `make`/existing state in the main checkout is untouched.
- Inside the worktree, follow this whole file: create the OpenSpec change first
  (`make openspec-new NAME=<kebab-name>`), write `proposal.md` +
  `specs/<cap>/spec.md` + `tasks.md`, implement, tick tasks, validate, then push
  and open the PR referencing the issue from that worktree's branch.
- When you must merge an approved green PR whose branch was created in a
  worktree, you may do so with `gh pr merge <N> --merge --delete-branch` from the
  main checkout and remove the worktree:
  ```bash
  git worktree remove ../llama-ai-wt/<kebab-name>
  ```
- The main checkout's branch should stay on `main` (or the active PR branch of
  whatever you're interactively helping on), with concurrency handled by
  worktrees.

### The host crontab that runs this (DISPATCHER + per-issue parallel workers)

The loop lives in the user's host crontab, runs every 20 minutes (`*/20 * * * *`),
and has NO time limit — it is intentionally NOT the in-process Hermes cron
scheduler (which imposes a ~3-min hard interrupt per run). The crontab runs the
**dispatcher**, which is a thin Python entrypoint (`scripts/watchloop_dispatch.py`)
that each tick:

1. **Finalizes merge-ready PRs** — merges a PR to `main` ONLY if ALL of:
   CI fully green, an APPROVED review, no open review threads, and the PR head is
   **NOT behind** `main` (never merge an out-of-sync / behind PR — see issue #9).
2. **Spawns ONE dedicated parallel worker per orphaned issue** — for every open
   issue with no live branch/PR, it creates its own isolated git worktree (`git
   worktree add -b feat/<kebab> ../llama-ai-wt/<kebab> origin/main`) and spawns a
   dedicated background `project-manager` Hermes session **whose cwd is that
   worktree** (so AGENTS.md loads) that drives ONLY that issue to a PR
   (OpenSpec-first → implement → validate → push → PR). Issues run in PARALLEL —
   they never serialize behind each other, and a worker resumes from its own log
   on later ticks.

Parallel-safety rules (so concurrent workers never collide):
- Every containerized `make` target (`openspec-*`, `test-unit`, `test-install`,
  `lint`, `lint-fix`, `test`) is run through the shared fcntl lock helper
  `scripts/serialized-make.py <lockfile> -- <target>` with the lock at
  `.watchloop/run/test.lock`, so only ONE worker drives the nerdctl container at a
  time. Workers NEVER run `make loop-harness`, `make test`, or `make
  test-install-host` — those are the harness's own orchestrated steps.
- Each worker uses its OWN worktree + its OWN log (no branch/container/log races).

Logs:
- Dispatcher run log: `.watchloop/run/dispatch.log`.
- Per-issue/log worker logs: `.watchloop/logs/feat-<kebab>.log` (one per PR;
  never corrupted, never interleaved with other workers').
- Inspect: `tail .watchloop/run/dispatch.log`, `grep -i merg .watchloop/run/dispatch.log`,
  or read any PR's own `.watchloop/logs/<branch>.log`.

Crontab / env / ops:
- View: `crontab -l`; edit: `crontab -e`. Software + prompts live in `scripts/`.
- If a worker is interrupted, its fcntl lock releases automatically and the next
  dispatcher tick resumes it from its own log.
- Do NOT recreate an in-process Hermes cron job for this — it would reintroduce the
  3-min kill.

## Git workflow — feature branch + PR (MANDATORY)

Every piece of work (bug fix, feature, tooling, docs) MUST be developed on a
**dedicated feature branch** off `main`, never directly on `main`. Work is only
merged into `main` through a **pull request**. This matches the remote's branch
protection (direct pushes to `main` are not allowed for new work).

1. **Before starting, branch off the latest `main`:**
   ```bash
   git checkout main && git pull origin main
   git checkout -b feat/<kebab-name>     # one branch per change/PR
   ```
2. **Do the work on that branch** — create/update the OpenSpec change, write
   `proposal.md` + `specs/<cap>/spec.md` + `tasks.md`, implement the code, and
   tick each task as it's verified.
3. **Run the loop gate** (`make loop`) — it must be GREEN, and
   `make openspec-validate NAME=<name>` must pass, and every task in
   `tasks.md` must be ticked (`- [ ]` → `- [x]`), before the branch is ready.
4. **When all tasks are completed AND verified**, push the branch and open a PR
   against `main`:
   ```bash
   git push -u origin feat/<kebab-name>
   gh pr create --base main --head feat/<kebab-name> \
       --title "feat: <kebab-name>" --body "Completes OpenSpec change <name>.<br>Loop gate GREEN, openspec validate passes, all tasks ticked."
   ```
5. **Never push directly to `main`.** If you need `main` updated, merge via the PR.
6. Keep each PR to one change/OpenSpec change. Rebase or merge `main` in when the
   PR goes stale; never force-push shared branches.

## PR review comments — check them and reply yourself (MANDATORY, durable)

When a feature branch has an OPEN PR, review commentary is a first-class source
of work. You MUST proactively read every comment/review thread on the PR for the
current branch, act on each one, and reply to it — WITHOUT waiting for the human
to paste the comment into chat.

1. **Check the PR for the current branch at the START of the session.** When work
   begins (or resumes) on a branch with an open PR, read its comments and review
   threads first:
   ```bash
   gh pr list --head <current-branch>            # find the PR number
   gh pr view <N> --json reviews,comments        # PR-level comments + review summaries
   # all inline (diff) review threads + any replies:
   curl -s -H "Authorization: Bearer ${GITHUB_TOKEN}" \
     "https://api.github.com/repos/<owner>/<repo>/pulls/<N>/comments" | python3 -m json.tool
   ```
   Review threads live in the **pull-request comments endpoint** (inline
   `diff_hunk` comments), not just PR-level comments — check BOTH.

2. **Every comment is a work item.** Treat each review thread as an obligation:
   - Reproduce/verify what the comment flags (run the relevant `make` gate). The
     comment may be a genuine defect even when the CI stage is green — e.g. a
     lint that silently skips a file (an extension-less `Dockerfile`) and thus
     never turns red. Find the root cause, don't dismiss it.
   - Fix the root cause, add a regression test if applicable, verify with real
     `make` output, and **commit + push** the fix as a NORMAL (non-squashed)
     Conventional Commit — never a squash/rebase/force-push on an open PR.

3. **Reply to each thread yourself (B29a).** After the fix is pushed, post a
   reply on the SAME thread (`in_reply_to` the original comment) that states the
   fixing commit sha, the root cause, the change, and the verification:
   ```bash
   curl -s -X POST -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
     "https://api.github.com/repos/<owner>/<repo>/pulls/<N>/comments/<COMMENT_ID>/replies" \
     -d '{"body":"Fixed in <sha>: ..."}'
   ```
   Reply to EVERY comment/thread — including informational questions — with a
   direct answer. Do not wait for the human to relay them.

4. **Push / API auth.** The `gh` keyring token may lack push + private-write
   scopes. Use the repo's gitignored `.env` `GITHUB_TOKEN` (from `LLM-AI-TOKEN`
   in `~/zshrc`) for `git push` and `gh api`/`curl` calls — load it in-memory,
   never print it, never commit `.env`.

5. **CI must reflect the resolution.** If a review thread points at a violation
   that should have gone red, verify the *exit-code contract* end-to-end (broken
   file → non-zero → job RED; fixed → zero → job GREEN) and confirm the
   re-push triggers CI. Report the actual CI job result, not an assumption.

6. **An APPROVED PR is merged.** When the PR for the current branch is reviewed
   and **approved** (a reviewer's `APPROVED` review, or an explicit human
   approval phrase), do NOT leave it sitting open — merge it to `main` once the
   merge prerequisites hold, and clean up the branch:
   ```bash
   # prerequisites first — loop gate green, all jobs on the PR pass, no
   # unresolved review threads:
   make loop
   gh pr checks <N>                       # every job must be green
   # merge (squash or merge as the repo policy prefers) then delete both branches:
   gh pr merge <N> --merge --delete-branch
   git branch -D feat/<branch>           # local clean-up
   ```
   Do NOT merge a red PR, a PR with open/unresolved review threads, or a PR whose
   CI is still running — approval is a green light, not a waiver of the gate.
   Verify the merge landed on `main` (e.g. `git fetch origin && git log origin/main -1`)
   and report the merge commit sha. If the reviewer engaged but did NOT approve,
   keep resolving threads (see above); only a genuine approval triggers the merge.
   This mirrors the obsidian-timestamp-utility B32 (review-approved squash +
   finalise): "once a reviewer has approved, the agent may finalise".

## Loop gate (run before claiming done — B20-equivalent)

Never report a change done without running the loop:

```bash
make loop            # runs: download-test-model -> lint -> test-unit -> test-install
                     #      -> test-health -> test -> openspec-validate
# or the explicit runner:
python3 scripts/loop_harness.py
```

- `scripts/loop_harness.py` runs the seven stages in a fixed order and **fails
  closed** (any failed stage → non-zero exit even if later stages run and pass).
- **`lint` stage (`make lint`) is mandatory:** every tracked text file must end
  with a trailing newline. `make lint-fix` appends the missing newlines
  reproducibly. (.editorconfig enforces this in-editor.)
- **`health` stage (`make test-health`) is mandatory and end-to-end real:** it
  launches the installed `~/bin/llama-ai` with a lightweight model
  (`~/models/Qwen/8GB/qwen2.5-0.5b-instruct-q4_0.gguf`, auto-fetched by
  `make download-test-model`), waits for `/health`, POSTs `"hi"` to
  `/v1/chat/completions`, and asserts a real text reply. This proves the host
  install serves a model from ~/bin.
- The hermetic gates (`make test-unit`) need no external dependency and MUST be
  green before any "done" claim.

### NO fallback implementations — one code path through the container, everywhere

There are NO fallback/dual implementations in the repo. Each stage has exactly
ONE code path that runs through the **same test container image** on CI and on
the local host, so behaviour is byte-identical in both. Concretely:

- **Model download** = the official `hf`(huggingface_hub) CLI with the
  resume/retry-throttle logic in `hf_dl.py`. `hf` is bundled into the test image
  (`huggingface_hub[cli]`) and found via `shutil.which("hf")` — never a
  `requests`/`urllib` downloader, never a host-path or secondary-CLI branch.
  `download_test_model.py` resolves `hf` from PATH only and aborts if absent
  instead of falling back.
- **Runtime (`RUNTIME`)** is `nerdctl` by default but resolves to `docker` only
  because that's a *tool-availability* check for the same container engine on
  non-Colima hosts (CI uses docker). This is not a second implementation of a
  *stage*; the command shape is identical via either.

Anything that adds a second, differently-implemented path for the SAME resource
(downloader, HEALTH check, model resolution) is a regression and will be
rejected, even when it "would just work" as a fallback.

### README must always be kept in sync

Any change that adds, renames, or alters a user-facing feature, `make` command,
target, or workflow MUST be mirrored in `README.md` **in the same change** —
document how to navigate and use it (commands, layout, behaviour). The README
is the user's navigation/usage doc, so it must never drift from the code. When
you add a make target, feature, or stage, update the README's corresponding
section in the same commit before the PR is ready. A "done" report that makes a
code change without an accompanying README update is incomplete.
- If the full loop can't complete, still run `make test-unit` + `make
  openspec-validate` and report their real results. Never hand-edit artifacts to
  fake green; fix the root cause and re-run.

### Local GPU verification is MANDATORY (the "exercise the GPU" rule)

The CI pipeline runs a **CPU-only** health check (bare GitHub runner, no GPU).
That alone does NOT fully verify the real hardware path. Before you report any
change that touches the model launcher / health / serving as "done", YOU must
also run the check **on the host with the actual GPU (Metal)** and record it:

- The host's Metal `llama-server` (built by `~/repository/git/llama.cpp`) backs
  the `~/bin/llama-ai` launcher. Run the qwen lightweight model's health check
  through the GPU path, not just the container/CPU path:
  ```bash
  # 1. the full containerized loop (fast, CPU+container proof):
  make loop            # == make loop-harness (download->lint->unit->install->health->test->openspec)

  # 2. the GPU/Metal proof — launch the host launcher (which uses the REAL
  #    Metal llama-server at ~/bin) with the Qwen/8GB model and curl its
  #    /health + a chat "hi":
  "$HOME/bin/llama-ai" 0.5b --port 18080 &      # uses the Metal (GPU) binary
  curl -s "http://127.0.0.1:18080/health"
  curl -s -X POST "http://127.0.0.1:18080/v1/chat/completions" -H 'Content-Type: application/json' \
       -d '{"messages":[{"role":"user","content":"hi"}],"max_tokens":16}'
  ```
  Even simpler: `tests/test_health.py` already launches the **host**
  `~/bin/llama-ai` launcher, which uses the **Metal llama-server** (GPU) — so on
  a host with the venv installed, `make test-health` IS the GPU/Metal
  verification.
- **Mandatory, not optional:** do NOT declare "green/done" from the container
  loop alone. You must additionally run the host/Metal `test-health` (the one
  that uses `~/bin/llama-ai` with the Metal binary) against the `Qwen/8GB`
  model and see the GPU reply. Record the GPU/Metal result in the loop summary.
- If the host GPU (Metal) backend is genuinely absent, state that explicitly and
  report the CPU/container result Honesty instead of pretending the GPU path ran.

## Makefile targets (source of truth)

Each verification step is an independent target; `make loop`/`loop-harness`
chains them all.

- `make install` — build gguf venv, write `~/bin/llama-ai` launcher, symlink
  `~/bin/llama_ai.py` + `~/bin/llama-server`, smoke-test (needs `~/models`).
- `make uninstall` — remove launcher + symlinks (keeps venv).
- `make venv-install` / `make -C tools venv-install` — build the gguf venv.
- `make download-test-model` — fetch the lightweight health-check model
  (`Qwen/Qwen2.5-0.5B-Instruct-GGUF` q4_0, ~340MB) into `~/models/Qwen/8GB` (idempotent).
- `make lint` — linefeed lint: fail closed if any tracked text file lacks a trailing newline.
- `make lint-fix` — append the missing trailing newline to tracked text files.
- `make test-unit` — hermetic unit tests only (no `~/bin`/`~/models` needed).
- `make test-install` — host install tests (verify installed launcher runs a model).
- `make test-health` — **end-to-end**: launch the tiny model from `~/bin`, answer
  `"hi"` on `/v1/chat/completions`, assert a healthy reply.
- `make test` — fast suite (unit + install; health excluded from `test` — run
  `test-health` in the chain).
- `make loop` / `make loop-harness` — run the chained `scripts/loop_harness.py`.
- `make chained` — run each verification step explicitly in sequence, fail-fast.
- `make generate-requirements` — recompile `tools/requirements.in` →
  `tools/requirements.txt` (container or venv pip-compile).
- `make openspec-image|new|validate|status|shell` — Dockerized OpenSpec CLI.

## Dependencies & lockfiles

- `tools/requirements.in` (numpy, gguf==0.19.0) and `tools/requirements-dev.in`
  (pytest) are the single sources of truth. **Never hand-edit** the compiled
  `requirements[-dev].txt`; regenerate via `make -C tools generate-requirements`
  / `generate-requirements-dev`. `make -C tools venv-dev-install` installs
  runtime + dev deps into the venv.
- `.venv`, `*.gguf`, `.run.log`, `*.progress.log`, `__pycache__` are gitignored.

## Model downloads & secrets

- `hf_dl.py` reads `HF_TOKEN` from `~/.zshrc` at runtime — never store a token in
  the repo or commit one. Prefer documented example shapes in docs/tests.

## Record of work

Track progress in `agent-wiki/` as dated `YYYY-MM-DD-<name>.md` entries (what was
verified against the spec, key decisions, current status). Keep entries concise;
don't over-engineer.
