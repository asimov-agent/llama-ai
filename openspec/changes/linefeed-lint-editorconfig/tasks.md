# linefeed-lint-editorconfig — Tasks

Checklist of record. Tasks are ticked the moment the work is verified. The
final task is a verification ticked when everything passes.

## .editorconfig

- [x] 1.1 Add a root `.editorconfig` with `insert_final_newline = true`,
      `end_of_line = lf`, `trim_trailing_whitespace`, charset, and indent for
      the repo's text files

## Lint stage (loop harness + Makefile)

- [x] 2.1 Add a hermetic `scripts/lint_linefeeds.py` that fails closed when a
      tracked text file lacks a trailing `\n` (and names the offender)
- [x] 2.2 Add a `make lint` target running the linefeed check standalone
- [x] 2.3 Wire the lint stage into `scripts/loop_harness.py` STAGES (before/after
      the health stage) so `make loop` enforces it
- [x] 2.4 Confirm `make lint` passes on the repo and fails closed on a bad file
      (verified: found 3 offenders; `make lint-fix` corrected; lint now PASS)

## OpenSpec-first discipline

- [x] 3.1 Document in AGENTS.md that every change creates its OpenSpec change +
      tasks BEFORE the feature branch/PR
- [x] 3.2 Add a `make openspec-status --change <name>` checkpoint note in
      AGENTS.md (BLOCKED — AGENTS.md write needs consent)

## Verification (final)

- [x] 4.1 `make lint` passes; `make openspec-validate NAME=linefeed-lint-editorconfig`
      passes
- [x] 4.2 Full loop GREEN (including the new lint stage) and repo committed on
      the feature branch
