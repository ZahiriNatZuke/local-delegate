# Brief: local_commit_msg: repo language from the commit history, not the reflog (#548)

## Problem

From a diff saved inside an agent worktree (`<repo>/.claude/worktrees/<name>/`, root or subfolder),
`local_commit_msg` says the repo's commits are mixed and writes in the product language (es), while
the last commits of `main` are English Conventional Commits.

Evidence (probe run on this very worktree, 2026-11-04): `_git_dir_above` finds the right git dir
(`.git/worktrees/<name>`), `commondir` (`../..`) resolves to the main `.git`, nothing nested is
mis-found. The cause is the source: the main checkout's `logs/HEAD` (724 lines, 160 KB) holds 28
`commit:` lines among the last 200; the rest are `pull … : Fast-forward`, `checkout:`, `rebase`, which
carry no subject. `main` grows by squash merges on GitHub pulled with `git pull`, so the only
`commit:` lines are old local commits, from the time the repo wrote Spanish subjects (2026-10-18 to
10-27). The last 20 give 10 es / 7 en, i.e. `mixed_repo`. The reflog tells what was typed in this
clone, not what the repo's history says.

## Desired outcome

The language comes from the subjects of the last commits reachable from HEAD (first-parent), read
from the object store in pure Python (no `git` subprocess, as #461 chose so nothing in the repo's
config or hooks can run). The reflog stays as fallback when objects cannot be read.

## In scope

- Read HEAD → ref (loose or `packed-refs`, in the common dir for a worktree) → commit objects
  (loose zlib, or pack v2 with `.idx`, including ofs/ref deltas), with size, depth and count caps.
- Tests with the real shape: worktree nested inside the main checkout, diff in root and subfolder,
  reflog with `pull: Fast-forward` / `checkout:` and few stale Spanish `commit:` lines.

## Out of scope

- SHA-256 repos, alternates, shallow boundaries beyond stopping the walk, reftable: they fall back
  to the reflog as today.
- The hooks and `local_summarize` zones (other agents).

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Resolve questions that materially change the specification before implementation.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-04 Original request, verbatim:

  > Issue #548 reopened: from an agent worktree nested in the main checkout, local_commit_msg falls back to the product language although the repo's recent commits are English. Fix the detection with evidence and a test with the real shape.
