# docs(agent-wiki): project overview snapshot entry (process-violation remediation)

## Why

The agent-wiki record `agent-wiki/2026-09-07-project-overview-snapshot.md` — a
full-repo survey written via Diamond fan-out (4 parallel workers: core app /
verification+loop / watch-loop / OpenSpec+conventions, then a skeptic
cross-check and a synthesis) — was committed as `d1a8d49` and **pushed directly
to `main`**, skipping the mandatory workflow: GitHub issue → OpenSpec change →
feature branch → PR, with the loop gate green before merge. That is a
process violation of this repo's AGENTS.md ("Never push directly to `main`";
"OpenSpec change + tasks FIRST, then implementation").

This change is the **remediation record** for that violation. The content
itself is docs-only (one new agent-wiki file, 127 lines, no code, no `make`
target, no behaviour change), so the code on `main` is already correct and
final; what was missing was the spec-tracked, PR-merged delivery path.

## What Changes

- Record the remediation in an OpenSpec change (this one) created and
  validated through the containerized CLI, with a tasks checklist and the
  `skip_specs: true` flag (docs-only, no spec delta required).
- Deliver the record on a dedicated feature branch
  `feat/docs-agent-wiki-project-overview-snapshot-entry-pr` and open a PR
  against `main` that references GitHub issue #59, so the (already-landed)
  agent-wiki entry is now backed by the required issue → OpenSpec → branch →
  PR pipeline and the loop gate.
- No source, Makefile, or spec files are touched. The agent-wiki file already
  exists on `main` (commit `d1a8d49`) and is NOT re-added or modified by this
  PR — the PR carries only the OpenSpec remediation record.

## Impact

- Docs / process only. No runtime, no test, no build impact.
- Closes the process-violation gap for issue #59: the snapshot entry is now
  traceable to a GitHub issue, an OpenSpec change, and a merged PR.
- README: no user-facing feature, `make` target, or workflow was added, so no
  README change is required (the change is an internal process record).
