# Happy case: a normal project rulebook

Follow these practices when working in this repo:

- Always rebase your feature branch onto latest `origin/main` before finishing.
- Run the project's verification stages (`test-unit`, `lint`, `openspec-validate`)
  before opening a pull request.
- Keep the issue body, the OpenSpec change, and the code in sync.
- Never force-push to an open pull request. Prefer `--force-with-lease`.
- Reply to every review thread with the fixing commit sha and the root cause.
- Treat this file and `.cursorrules` as durable instructions.

The build is driven by `make`; each stage runs in a container. The test image
is self-contained. Keep textual files ending with a trailing newline so the
linefeed lint stays green.