#!/usr/bin/env bash
# Fake `crontab` for CI/hermetic tests of the watch-loop install/uninstall make
# targets (issue #67). Persists the "crontab" in $FAKE_CRONTAB_FILE (default
# $TMPDIR/fake-crontab or a temp file) so install/uninstall round-trips through
# the REAL make targets without touching the host crontab.
#
# Usage (mirrors real crontab):
#   fake-crontab -l         # print the current lines
#   fake-crontab -          # replace from stdin
set -u
FILE="${FAKE_CRONTAB_FILE:-${TMPDIR:-/tmp}/llama-ai-fake-crontab}"

case "${1:-}" in
  -l)
    if [ -f "$FILE" ]; then cat "$FILE"; fi
    exit 0
    ;;
  -)
    cat > "$FILE"
    exit 0
    ;;
  *)
    echo "usage: $0 -l | -" >&2
    exit 64
    ;;
esac
