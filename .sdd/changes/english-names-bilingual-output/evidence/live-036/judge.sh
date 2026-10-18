#!/usr/bin/env bash
# Juez de idioma «solo prosa» (scripts/judge_response_language.py) sobre las respuestas de
# run_tools.py. Uso: bash judge.sh <es|en> <carpeta de entradas de run_tools.py>
set -u
lang=$1; inputs=$2
here=$(cd "$(dirname "$0")" && pwd); root=$(cd "$here/../../../../.." && pwd); cd "$root"
A=$here/answers/$lang; out=$A/judge.jsonl; : > "$out"; : > "$inputs/empty.txt"
for pair in "local_status:$inputs/empty.txt" "local_summarize:docs/wiki/Daemon.md" \
  "local_lint_summary:$inputs/ruff.log" "local_commit_msg:$inputs/commit.diff" \
  "local_explain_code:src/local_delegate/sections.py" "local_describe_image:$inputs/empty.txt"; do
  t=${pair%%:*}; d=${pair#*:}
  PYTHONIOENCODING=utf-8 uv run --no-sync python scripts/judge_response_language.py \
    --document "$d" --requested "$lang" "$A/$t.txt" | tail -1 | sed "s#^{#{\"tool\": \"$t\", #" >> "$out"
done
cat "$out"
