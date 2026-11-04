# Handoff: A mod decision record is reported as written even when it is not

## Current state

- SDD status: closed (closing PR `chore/close-sdd-2026-11-04`)
- Last completed gate: memory
- Current revision: merged in `main` as `3e826b56` (PR #559)

## What changed

- `hook_common.record_or_raise`: the `record-read` road re-raises the write `OSError` instead of swallowing it; normal `hooks.json` hooks stay best effort.
- `POST /api/hook/record-read` answers 500 and `classify`/`record-read` exit 1 when the line was not written; `hook-failures.jsonl` gains `decision` and `via` (allow-listed short names).
- `mod/read.js` unchanged: it already retries and reports `ModRecordLost` on 500 or a non-zero exit.

## Decisions

- Each road (daemon, process, mod) reports its own failure, so one lost decision can leave up to three failure lines (review F5, accepted).

## Next action

- None. Watch the failure lines in the next adoption measurement.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: `projects/local-delegate` journey index (main session)
