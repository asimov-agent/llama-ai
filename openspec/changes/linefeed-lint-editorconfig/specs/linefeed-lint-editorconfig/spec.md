# linefeed-lint-editorconfig — spec of record

## ADDED Requirements

### Requirement: .editorconfig standardizes text-file formatting
The system MUST ship a root `.editorconfig` that sets `insert_final_newline = true`
(and `end_of_line = lf`) for tracked text files, so every text file has a trailing
line feed.

#### Scenario: editorconfig present
- **WHEN** a developer opens any text file in this repo
- **THEN** the editor honors the repo's `.editorconfig` and writes a final newline

### Requirement: loop-harness lint stage enforces the trailing line feed
The loop harness MUST include a hermetic lint stage that fails closed if any
tracked text file lacks a trailing newline, and MUST be exposed via a Makefile
target (`make lint`) and included in the `loop`/`loop-harness` chain.

#### Scenario: a file without a trailing newline
- **WHEN** `make lint` runs and some tracked text file does not end with `\n`
- **THEN** the lint stage fails with a non-zero exit and names the offending file

#### Scenario: all files correct
- **WHEN** `make lint` runs and every tracked text file ends with `\n`
- **THEN** the lint stage exits 0

### Requirement: OpenSpec change precedes feature branch/PR
For every change the system MUST create the OpenSpec change (proposal.md +
specs/<cap>/spec.md + tasks.md) BEFORE opening a feature branch and PR, so the
work is spec-tracked from the start.

#### Scenario: starting new work
- **WHEN** the agent begins new work on this repo
- **THEN** it creates/updates the OpenSpec change and ticks its tasks before
  opening the feature branch and PR
