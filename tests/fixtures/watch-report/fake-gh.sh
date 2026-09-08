#!/usr/bin/env bash
# Fake `gh` shim for CI (watch-report job). Returns fixture-shaped JSON for the
# exact `gh pr list` / `gh issue list` / `gh pr checks` invocations that
# scripts/watch_report.py makes, so the make target is exercised end-to-end
# without a real GitHub token or network.
set -euo pipefail

# Resolve the repo root. WATCH_REPORT_FIXTURE_ROOT is set by the CI job; the
# fallback derives it from this shim's in-repo location (tests/fixtures/watch-report).
if [[ -n "${WATCH_REPORT_FIXTURE_ROOT:-}" ]]; then
  root="$WATCH_REPORT_FIXTURE_ROOT"
else
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../.."
fi

if [[ "$1" == "pr" && "$2" == "list" ]]; then
  cat "$root/tests/fixtures/watch-report/gh_pr_list.json"
elif [[ "$1" == "issue" && "$2" == "list" ]]; then
  cat "$root/tests/fixtures/watch-report/gh_issue_list.json"
elif [[ "$1" == "pr" && "$2" == "checks" ]]; then
  cat "$root/tests/fixtures/watch-report/gh_pr_checks.txt"
else
  # Unsupported call -> return empty so the script degrades gracefully.
  echo ""
fi
