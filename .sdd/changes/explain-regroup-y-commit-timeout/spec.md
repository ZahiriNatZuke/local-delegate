# Specification: Regroup cortado en explain_code y diff grande en commit_msg (#598, #596)

## Summary

Two failures of the chunked (map/reduce) path, both in `src/local_delegate/server.py`:

- #598: in `_chat_map_reduce`, a regroup step cut by `max_tokens` whose split retry cannot shrink
  its group (`_regroup_split_shrinks` false) is accepted as it is (`_regroup`, last `return
  [out]`). The answer of `local_explain_code` then states a negative conclusion («no se observan
  escrituras…») that may come from the notes lost in the cut, and nothing in the answer says so.
- #596: `local_commit_msg` maps every chunk of a large diff in series (125 KB → 7 chunks, 8 calls,
  124 s with the model load) and the client cancels it at ~120 s. Nothing limits the number of
  map calls.

## Requirements

- **REQ-001** — In `local_explain_code` chunked WITH a question, a regroup step cut by `length`
  that cannot be split (the split would not halve its group) is retried ONCE with twice its output
  cap — within `CHUNK_MAX_TOKENS` and the room the prompt leaves in the model's context — when
  the widened output still shrinks the group (`2 × cut ≤ REGROUP_MIN_SHRINK × group`) and
  the retry budget of #497 allows one more call; the cut output is replaced by the retry. A context
  overflow of that retry keeps the cut output and does not fail the operation. Other tools and
  explain without a question keep today's behaviour (flag `widen_cut_regroup`, off by default).
  - Request: "#598: local_explain_code acepta regroup cortados por max_tokens tras el reintento"
  - Verify: test `tests/test_explain_regroup_cut.py`
- **REQ-002** — Under the same flag, when a cut stays in the result, the truncation notice says how
  many of the cut calls left are regroup steps (right after the main sentence), and the widened retries
  are named apart, so the notice adds up to the `length` steps of the log.
  - Request: "#598: … acepta regroup cortados por max_tokens tras el reintento"
  - Verify: test `tests/test_explain_regroup_cut.py`
- **REQ-003** — The note-combining tail of REQ-002 says expressly that a statement that something
  does NOT happen may come from the cut. (Revised after the independent review: the first design, a
  program that detected denials in the answer, flagged ordinary conditionals and missed «None of the
  functions write»; it was removed.)
  - Request: "#598: … y saca una conclusión negativa que contradice el fichero"
  - Verify: test `tests/test_explain_regroup_cut.py`
- **REQ-004** — A chunked `local_commit_msg` stops its map before a chunk when the time since the
  tool call started plus twice the slowest chunk after the first would pass
  `server.COMMIT_TIME_BUDGET_S` (95 s; the client cancels at ~120 s); the reduce drafts the message
  from the chunks read and the whole inventory. With fewer than two chunks read it never stops,
  and outside a tool call (no cancellation token: a measurement script) there is no budget. The
  estimate is per backend call (the slowest after the first), and it is also checked before a
  split retry of a cut chunk (#455), before a regroup level of the reduce and before the widened
  regroup retry: when they do not fit, the cut output is kept, or the reduce gets the notes that
  fit it, and the answer says so (`time_budget_retries`). Worst case (a chunk split twice near the
  end plus a regroup) stays under 110 s.
  - Request: "#596: local_commit_msg con un diff de ~125 KB supera los 120 s de la tool y acaba cancelado"
  - Verify: test `tests/test_commit_large_diff_budget.py`
- **REQ-005** — When the map stopped, the answer carries a warning with the parts and chars read
  of the total, the scope receipt does not claim the diff was read whole, and the log row says
  `truncated_in: true`. A diff with time to spare keeps every prompt and its answer byte for byte
  (the versioned corpus `techo-commit-156k` and `test_map_reduce` keep passing).
  - Request: "#596: … acaba cancelado" (derived: no silent cut, per the orchestrator's brief)
  - Verify: test `tests/test_commit_large_diff_budget.py`

## Acceptance scenarios

### Scenario: cut regroup widened (#598)

- **Given** a chunked `local_explain_code` whose last regroup group is cut and too small to split
- **When** the regroup is retried with twice the cap and answers `stop`
- **Then** the log row has that step `retried`, no truncation notice is added and `truncated_out` is false

### Scenario: cut kept (#598)

- **Given** a regroup still cut after the widened retry
- **Then** the answer carries the truncation notice naming the combining steps and saying a «does not happen» may come from the cut

### Scenario: 125 KB diff (#596)

- **Given** a diff of ~125 000 chars (7 chunks), a first call of 36 s (model load) and 14 s per call after it
- **When** `local_commit_msg(diff=…)` runs
- **Then** the map stops after 4 chunks, the call ends under 120 s and the answer says what was read

## Edge cases and failure behavior

- The widened retry counts against the shared retry budget of #497; past it, today's behaviour.
- A model that fills any cap gets cut again in the widened retry: it is kept and counted, as today.

## Non-functional requirements

- No change to the single-call paths. Existing tests unchanged. No new env var or option (a module
  constant), so no public contract changes.
- The budget is measured on the wall clock of the tool call (queue, model load and every call);
  the estimate is the slowest chunk after the first, so a slower backend stops earlier.

## Non-goals

- Changing the client's 120 s limit or the progress heartbeat (#479).
- A time budget for the other chunked tools (summarize, lint, explain): follow-up if they hit it.
- Reducing the diff (dropping context lines or capping files): tried first and dropped, because it
  changes the prompts of every large diff and breaks the versioned corpus and `test_map_reduce`.
- Changing the map, regroup or reduce prompts.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
