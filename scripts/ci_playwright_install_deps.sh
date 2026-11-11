#!/usr/bin/env bash
# Installs the system packages Chromium needs (apt), retrying a slow or failing mirror.
#
# Used by `.github/workflows/ci.yml`. The Azure apt mirror has stalled more than once (2026-10-22,
# 2026-10-27, 2026-11-11): a single `playwright install --with-deps` then ate the whole step limit
# or exited with apt's code 100 and left main red with no code change. Each attempt gets its own
# time limit so a hung apt does not consume the step, and the attempts are bounded.
set -uo pipefail

attempts="${PLAYWRIGHT_DEPS_ATTEMPTS:-3}"
per_attempt="${PLAYWRIGHT_DEPS_TIMEOUT:-120}"

for ((i = 1; i <= attempts; i++)); do
  echo "playwright install-deps chromium: attempt ${i}/${attempts} (limit ${per_attempt}s)"
  status=0
  timeout --kill-after=15 "${per_attempt}" uv run playwright install-deps chromium || status=$?
  if ((status == 0)); then
    exit 0
  fi
  echo "::warning::playwright install-deps failed (exit ${status}) on attempt ${i}/${attempts}"
  if ((i < attempts)); then
    # A killed apt can leave its lock behind; let dpkg settle before trying again.
    sudo dpkg --configure -a || true
    sleep $((15 * i))
  fi
done

echo "::error::playwright install-deps failed ${attempts} times"
exit 1
