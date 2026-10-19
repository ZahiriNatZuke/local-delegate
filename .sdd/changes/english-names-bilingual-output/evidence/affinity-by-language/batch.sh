#!/usr/bin/env bash
# affinity-by-language: the 6 windows (3 models x 2 languages) of measure.ps1, one at a time,
# through pesado.sh. A window that refuses for RAM (< 4 GB free) is retried after 60 s, up to 5
# times; at the end the launcher is restored ('restore').
ps1='D:\Projects\ld-wt-lint\.sdd\changes\english-names-bilingual-output\evidence\affinity-by-language\measure.ps1'
for lang in es en; do
  for model in gemma3-4b qwen35-2b gemma4-26b-a4b; do
    for try in 1 2 3 4 5; do
      if bash ~/.claude/scripts/pesado.sh pwsh -NoProfile -File "$ps1" -Step run -Model "$model" -Lang "$lang"; then
        break
      fi
      echo "[affinity] window $lang/$model failed (try $try); waiting 60 s"
      sleep 60
    done
  done
done
bash ~/.claude/scripts/pesado.sh pwsh -NoProfile -File "$ps1" -Step restore
echo "[affinity] batch done"
