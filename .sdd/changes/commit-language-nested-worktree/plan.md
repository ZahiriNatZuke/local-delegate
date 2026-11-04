# Implementation plan: local_commit_msg: repo language from the commit history, not the reflog (#548)

## Approach

A small read-only object reader in `src/local_delegate/git_history.py`, used next to the reflog reader: resolve HEAD (worktree git
dir) and its ref (common dir: loose ref, then `packed-refs`), then walk first parents reading each
commit from `objects/xx/…` (zlib) or from the packs (`.idx` v2 fan-out + binary search, pack entry
header, OFS/REF delta application). Subjects of that walk, when any, replace the reflog's; else the
current reflog path runs unchanged.

## Ordered tasks

- [x] T1 — Object reader and history walk with caps (REQ-002, REQ-004)
  - Files or modules: src/local_delegate/git_history.py, src/local_delegate/server.py
  - Verification: new tests (packed, delta, corrupt, caps)
  - Depends on: none
- [x] T2 — Use the history before the reflog in `_repo_commit_language_lookup` (REQ-001, REQ-003)
  - Files or modules: src/local_delegate/git_history.py, src/local_delegate/server.py
  - Verification: new test with the real shape; existing commit tests
  - Depends on: T1
- [x] T3 — CHANGELOG entry and docs where the reflog source is described (REQ-001)
  - Files or modules: CHANGELOG.md, docs
  - Verification: review
  - Depends on: T2

## Test strategy

- Unit: reader on real repos made with `git` (loose, `gc` packed, aggressive delta), corrupt files.
- Integration: `_commit_language_choice` from a worktree nested in the main checkout.
- End-to-end or manual: probe on this agent worktree before/after.
- Security and secret scanning: no subprocess; caps tested.

## Migration and compatibility

- Describe compatibility boundaries, data migration, and rollout considerations.

## Plan review

- [ ] Every requirement maps to at least one task and verification step.
- [ ] Risky or destructive operations have safeguards and rollback.
- [ ] Dependencies and configuration changes are explicit.
- [ ] The plan does not include unrelated work.
