#!/usr/bin/env bash
# lint-counts: runs the given windows of measure.ps1 with one tag, one at a time, through pesado.sh.
# A window that refuses for RAM (< 4 GB free) is retried after 60 s, up to 5 times.
tag="$1"; shift
ps1='D:\Projects\ld-wt-lint\.sdd\changes\english-names-bilingual-output\evidence\lint-counts\measure.ps1'
for w in "$@"; do
  for try in 1 2 3 4 5; do
    if bash ~/.claude/scripts/pesado.sh pwsh -NoProfile -File "$ps1" -Step "$w" -Tag "$tag"; then
      break
    fi
    echo "[lint-counts] window $w failed (try $try); waiting 60 s"
    sleep 60
  done
done
echo "[lint-counts] batch $tag done"
