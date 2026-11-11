# Handoff: doctor: cada rol tiene su modelo servido

## Current state

- SDD status: closed on delivery of the PR; the merge and the live check are the main session's
- Last completed gate: memory
- Current revision: branch `fix/doctor-role-models-served`

## What changed

- New `doctor` check `service.role_models` (35 checks), `BackendView.models` and `role_models`,
  `/api/backend` sends `role_models`, es/en texts, wiki row, CHANGELOG.

## Decisions

- Vision missing alone is `ok` with a note; a text role missing is `warn`.
- The roles are the daemon's when it sends them; an older daemon falls back to the console, said in the detail.
- An untagged id matches `<id>:latest` (Ollama); llama-swap aliases count only if listed.

## Next action

- Restart the daemon with this version and run `local-delegate doctor` to see the row live.

## Memory

- Canonical note: none apart; the CHANGELOG, the PR and review.md hold it
- Indexes updated: none
