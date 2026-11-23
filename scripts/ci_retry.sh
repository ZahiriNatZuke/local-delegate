#!/usr/bin/env bash
# Runs a command with a bounded number of attempts, each with its own time limit.
#
#   bash scripts/ci_retry.sh <attempts> <seconds per attempt> <command...>
#
# Used by `.github/workflows/ci.yml` for the download of the Playwright browser (SDD ci-root-cause):
# the CDN or the network of the runner stalls now and then, and a single attempt left `lint` red
# with no code change. The worst case is attempts * (limit + 10) + the pauses, which
# `tests/test_ci_gate.py` keeps under the limit of the step.
set -uo pipefail

attempts="$1"
per_attempt="$2"
shift 2

for ((i = 1; i <= attempts; i++)); do
  echo "$1: attempt ${i}/${attempts} (limit ${per_attempt}s)"
  status=0
  timeout --kill-after=10 "${per_attempt}" "$@" || status=$?
  if ((status == 0)); then
    exit 0
  fi
  echo "::warning::$* failed (exit ${status}) on attempt ${i}/${attempts}"
  if ((i < attempts)); then
    sleep $((10 * i))
  fi
done

echo "::error::$* failed ${attempts} times"
exit 1
