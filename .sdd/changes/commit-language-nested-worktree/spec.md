# Specification: local_commit_msg: repo language from the commit history, not the reflog (#548)

## Summary

`local_commit_msg` picks the repo's commit language from the subjects of the latest commits on
HEAD's first-parent chain, read from git's object store without running `git`; the reflog is only
a fallback.

## Requirements

- **REQ-001** — A diff saved in the root or in a subfolder of a linked worktree nested inside the
  main checkout, whose HEAD history is English but whose shared reflog has only `pull`/`checkout`
  entries plus a few old Spanish `commit:` lines, gets `("en", "repo")`.
  - Request: "local_commit_msg falls back to the product language although the repo's recent commits are English"
  - Verify: test tests/test_commit_language_history.py
- **REQ-002** — Commits stored in a pack (also as deltas) are read the same as loose ones.
  - Request: derived: a real repo packs its objects (clone, gc), so loose-only would fix nothing.
  - Verify: test tests/test_commit_language_history.py
- **REQ-003** — When the object store cannot be read (no objects, missing ref, unsupported format),
  the behavior of before (reflog, own then common) is kept unchanged.
  - Request: derived: no regressions in #461/#546/#548 behavior.
  - Verify: test tests/test_commit_grounding.py tests/test_commit_language_notice.py
- **REQ-004** — Disk input stays bounded: no `git` subprocess, no network paths, caps on object
  size, delta depth, commits walked and files opened.
  - Request: derived: the reader parses files of an arbitrary repo.
  - Verify: test tests/test_commit_language_history.py

## Acceptance scenarios

### Scenario: agent worktree nested in the main checkout

- **Given** a repo whose last commits are English, pulled into the main checkout (reflog with
  `pull: Fast-forward` and old Spanish `commit:` lines), and a worktree under `.claude/worktrees/`
- **When** `local_commit_msg` gets a diff saved in the worktree root or in `.sdd/changes/x/`
- **Then** the language is English, source `repo`

## Edge cases and failure behavior

- Corrupt object, truncated pack, delta loop, huge object: the walk stops; with no subject read the
  reflog is used.
- A real fresh clone now answers from its history (`repo`) instead of `short_history`.

## Non-functional requirements

- Reads at most 20 commits; each object capped at 1 MiB inflated; delta chain depth ≤ 50.

## Non-goals

- SHA-256 object format, alternates, reftable, commit-graph files.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
