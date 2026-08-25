# test-watchloop — Verify the background watch loop drives a new issue end-to-end

Checklist of record. Tasks ticked the moment verified. Delivered per AGENTS.md:
OpenSpec change first, then implementation, then validate, then PR.

## Driving issue

- [x] 1.1 The driving GitHub issue (#7) is open, no live branch/PR existed for it
      at the start of this tick, and the watch loop picks it up as a new issue.
- [x] 1.2 An isolated git worktree feature branch is created off `main` via
      `git worktree add -b feat/<kebab> ../llama-ai-wt/<kebab> main`.

## OpenSpec change (docs)

- [x] 2.1 OpenSpec change scaffolded via `make openspec-new
      NAME=test-watchloop-verify-the-background-watch-loop-dr` via the
      containerized CLI.
- [x] 2.2 `proposal.md` written describing the verification-only docs change;
      `.openspec.yaml` sets `skip_specs: true` (docs-only, no spec delta).
- [x] 2.3 `tasks.md` written as this checklist of record.
- [x] 2.4 The issue body, proposal, and README note stay in sync (same goal).

## Implementation (small, safe docs note)

- [x] 3.1 Add a short verification paragraph to the existing "Self-driving
      development (background watch loop)" subsection of `README.md` recording
      that issue #7 exercises this contract end-to-end (worktree → OpenSpec →
      code → PR), referencing `AGENTS.md` for the durable rules.
- [x] 3.2 README change is user-facing and matches the AGENTS.md behaviour it
      describes.

## Validation (final)

- [x] 4.1 `make openspec-validate NAME=test-watchloop-verify-the-background-watch-loop-dr`
      exits 0.
- [x] 4.2 `make lint` passes (trailing newline on every tracked text file,
      including the new OpenSpec files).
- [x] 4.3 `make test-unit` passes (hermetic unit tests).
- [x] 4.4 Feature branch pushed to `origin`, and a PR opened against `main` that
      references the driving issue #7.
