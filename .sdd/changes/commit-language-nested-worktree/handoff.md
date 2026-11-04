# Handoff: local_commit_msg takes the repo language from HEAD's commits, not the reflog (#548)

## Current state

- SDD status: closed (closing PR `chore/close-sdd-2026-11-04`)
- Last completed gate: memory
- Current revision: merged in `main` as `5b305b5d` (PR #562, closes #548)

## What changed

- New `src/local_delegate/git_history.py`: walks HEAD's first-parent chain and reads subjects from the object store (loose, v2 packs, ofs/ref deltas) in pure Python, no `git` subprocess, with caps and a per-call budget (32 MiB, 1.5 s).
- `server._repo_commit_language_lookup`: history first; the reflog fills when it gives fewer than 5 votes; a subject in both votes once.
- i18n `short_history` warning now talks about the history read.

## Decisions

- Not supported (reflog fallback as before): SHA-256 repos, `objects/info/alternates`, reftable refs.
- A read error ends the walk keeping what was read (CodeQL empty-except alert fixed with an explaining comment).

## Next action

- None.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: `projects/local-delegate` journey index (main session)
