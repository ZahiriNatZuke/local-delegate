#!/usr/bin/env bash
# Makes sure Chromium can start on the CI runner, touching apt only when it has to.
#
# Used by `.github/workflows/ci.yml`, after the browser itself is in place (cache or download).
# The Azure apt mirror has stalled more than once (2026-10-22, 2026-10-27, 2026-11-11): a single
# `playwright install --with-deps` then ate the whole step limit or exited with apt's code 100 and
# left main red with no code change. So:
#
# 1. If Chromium already launches (the runner image ships Google Chrome and its libraries), apt is
#    not needed at all and is skipped.
# 2. Otherwise `playwright install-deps` runs with a bounded number of attempts, each with its own
#    time limit. The limit runs as root: `install-deps` starts `apt-get` as root, and a `timeout`
#    running as the runner user cannot kill it, so the stray `apt-get` kept the lock and made every
#    later attempt fail at once (seen on the first run of this script, 2026-11-11).
set -uo pipefail

attempts="${PLAYWRIGHT_INSTALL_ATTEMPTS:-3}"
per_attempt="${PLAYWRIGHT_INSTALL_TIMEOUT:-120}"
venv_bin="${PLAYWRIGHT_VENV_BIN:-$PWD/.venv/bin}"

chromium_launches() {
  "$venv_bin/python" - <<'PY'
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    p.chromium.launch().close()
PY
}

if chromium_launches; then
  echo "Chromium launches with the libraries already on the runner: apt skipped"
  exit 0
fi
echo "Chromium does not launch yet: installing its system dependencies"

for ((i = 1; i <= attempts; i++)); do
  echo "playwright install-deps chromium: attempt ${i}/${attempts} (limit ${per_attempt}s)"
  status=0
  sudo timeout --kill-after=15 "${per_attempt}" "$venv_bin/playwright" install-deps chromium \
    || status=$?
  if ((status == 0)); then
    exit 0
  fi
  echo "::warning::playwright install-deps failed (exit ${status}) on attempt ${i}/${attempts}"
  if ((i < attempts)); then
    # Whatever survived the limit still holds the apt lock: stop it and let dpkg settle.
    sudo pkill -x apt-get || true
    sleep $((15 * i))
    sudo dpkg --configure -a || true
  fi
done

echo "::error::playwright install-deps failed ${attempts} times"
exit 1
