#!/usr/bin/env bash
# Safely load the GitHub token into .env and verify it has write access.
# Never prints the token value.
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="$HOME/.zshrc"
ENVFILE=".env"
PROBE="_probe_file.txt"

# 1. Extract token value from .zshrc (strip export prefix and surrounding quotes).
TOK="$(grep 'LLM-AI-TOKEN' "$SRC" | head -1 | sed -E 's/^export[[:space:]]+LLM-AI-TOKEN=//; s/^["'"'"']//; s/["'"'"']$//' | tr -d '[:space:]')"
if [ -z "$TOK" ]; then
  echo "ERROR: no LLM-AI-TOKEN found in $SRC" >&2; exit 1
fi
printf 'GITHUB_TOKEN=%s\n' "$TOK" > "$ENVFILE"
chmod 600 "$ENVFILE"
echo "Wrote $ENVFILE (value length: ${#TOK} chars)."

# 2. Confirm .env is ignored and untracked.
git check-ignore -v "$ENVFILE"
if git ls-files --error-unmatch "$ENVFILE" >/dev/null 2>&1; then
  echo "ERROR: $ENVFILE is TRACKED (must never be)" >&2; exit 1
fi
echo "$ENVFILE is gitignored and untracked (good)."

# 3. Verify write access via Contents API (create + delete a probe).
curl -s -X PUT -H "Authorization: Bearer $TOK" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/asimov-agent/llama-ai/contents/$PROBE" \
  -d '{"message":"write-probe","content":"'"$(printf 'probe' | base64)"'"}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('WRITE OK sha',d.get('content',{}).get('sha')) if d.get('content') else print('WRITE DENIED:',d.get('message'))"

# 4. Cleanup probe.
SHA="$(curl -s -H "Authorization: Bearer $TOK" "https://api.github.com/repos/asimov-agent/llama-ai/contents/$PROBE" | python3 -c "import sys,json;print(json.load(sys.stdin).get('sha',''))")"
if [ -n "$SHA" ]; then
  curl -s -X DELETE -H "Authorization: Bearer $TOK" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/asimov-agent/llama-ai/contents/$PROBE" \
    -d '{"message":"probe cleanup","sha":"'"$SHA"'"}' >/dev/null
  echo "Probe cleaned up."
fi