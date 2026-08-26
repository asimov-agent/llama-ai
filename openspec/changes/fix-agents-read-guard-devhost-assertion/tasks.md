# fix-agents-read-guard-devhost-assertion — Tasks

Checklist of record. Each task ticked the moment verified.

- [x] 1.1 Fix `tests/test_agents_read.py::test_guard_imports_installed_hermes_module`: accept site-packages / .venv / ~/.hermes locations; keep the repo-root rejection.
- [x] 1.2 Verify full guard suite green on the dev host: `python -m pytest tests/test_agents_read.py --noconftest -q` (13/13).
- [x] 1.3 Verify `make lint` and `make openspec-validate NAME=fix-agents-read-guard-devhost-assertion` pass.
