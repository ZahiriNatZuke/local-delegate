#!/usr/bin/env bash
# Runs a slice of the suite in series, and once more with only its failures (SDD ci-root-cause).
#
#   bash scripts/ci_pytest_retry.sh -m real_io
#   bash scripts/ci_pytest_retry.sh -m perf
#
# Used by `.github/workflows/ci.yml` for the tests that measure a cost (`perf`) or wait for real
# processes, sockets and clocks with a ceiling (`real_io`). Without `-n`: no other worker shares the
# cores while they run. One retry and only of what failed (`--lf`), so a real regression still
# fails: it fails both times. Any exit that is not "tests failed" (1) is final: 5 means the marker
# selected nothing, which is a regression of the split, not noise.
set -uo pipefail

status=0
uv run pytest -q "$@" || status=$?
if ((status == 0)); then
  exit 0
fi
if ((status != 1)); then
  echo "::error::pytest $* exited with ${status} (not a test failure): no retry"
  exit "${status}"
fi

echo "::warning::pytest $*: failures on the first try; running only those once more (--lf)"
uv run pytest -q "$@" --last-failed --last-failed-no-failures none
