# Linefeed / EditorConfig lint in the loop harness

## Why

A review of the health-check PR requested two durability guarantees:

1. **Always a trailing line feed (newline) on text files** — so diffs stay
   clean, POSIX tools behave, and git doesn't complain about "No newline at end
   of file". This must be enforced by a lint stage in the loop harness so no
   change can land without it.
2. **OpenSpec tasks-first discipline** — for every change, create the OpenSpec
   change (proposal + specs + tasks.md) BEFORE implementing and opening a feature
   branch/PR, so the work is spec-tracked from the start.

## What Changes

- Add `.editorconfig` (root) standardizing line endings (LF), final newline,
  charset, and indent style for the project's text files.
- Add a lightweight, hermetic lint stage to the loop harness that checks every
  tracked text file ends with a newline (and fails closed if not) — wired in via
  the Makefile and documented in AGENTS.md.
- Provide a Makefile target (`make lint`) to run the check standalone, and add it
  to the `loop`/`loop-harness` chain.
- Document in AGENTS.md that every change must have its OpenSpec change + tasks
  created first, then a feature branch + PR.

## Capabilities

- **linefeed-lint**: editorconfig + lint stage -> consistent text files.
- **openspec-first**: OpenSpec tasks precede the feature branch/PR.

## Impact

No runtime impact on llama-ai serving; purely a development/loop-harness
hygiene change.