# Specification: Panel: queued chunked rows say which chunk waits and for how long

## Summary

A queued chunked delegation reads as waiting for its next chunk, says why and for how long it has waited, and rows in «In progress» never split their time and characters across lines.

## Requirements

<!-- One block per requirement. Request quotes the literal fragment of the request, or says
"derived: <reason>". Verify starts with one method: test, cmd, manual or review. -->

- **REQ-001** — A queued row of a chunked delegation in the map phase shows «Waiting chunk n/total» («Espera trozo n/total»), never the processing label «Chunk n/total»; a queued reduce shows «Waiting to combine total pieces». Rows that are not queued keep their labels.
  - Request: "que se distinga el trozo que espera de los ya hechos"
  - Verify: test tests/test_inflight_state.py::test_panel_queued_chunk_says_it_waits
- **REQ-002** — A queued row carries a title that says why it waits: a backend place (`slot`), its turn (`turn`, with the position when known), or not started yet; the chunk chip's title says how many chunks are done. No machine value (`slot`, `turn`) is shown as text.
  - Request: "que el título (tooltip) diga por qué espera: plaza (slot) o turno (turn, con su puesto si lo hay)"
  - Verify: test tests/test_inflight_state.py::test_panel_queued_row_title_says_why
- **REQ-003** — `/api/inflight` adds `wait_s` (seconds since the current local wait began) to entries with `local_wait`, and only to them; existing fields are unchanged.
  - Request: "Si /api/inflight no expone algún dato que necesites (p. ej. desde cuándo espera), añádelo en la API"
  - Verify: test tests/test_inflight_state.py::test_inflight_reports_how_long_it_waits
- **REQ-004** — A queued row with `wait_s` shows the waited time with a short label next to the total time, with the explanation in the title.
  - Request: "Mostrar cuánto lleva esperando la fila en cola, además del total, sin añadir prosa"
  - Verify: test tests/test_inflight_state.py::test_panel_queued_row_shows_the_wait
- **REQ-005** — Time and characters of an «In progress» row stay on one line and right-aligned at desktop width, whatever the width of the numbers.
  - Request: "Arreglar la fila de Processing que parte tiempo y caracteres a otra línea según el ancho del número"
  - Verify: test tests/test_dashboard_ui.py::test_inflight_rows_keep_time_and_chars_on_one_line

## Acceptance scenarios

### Scenario: expected path

- **Given** a `local_summarize` split in 3 whose chunk 1 is done and chunk 2 waits for a place for 40 s
- **When** the panel polls `/api/inflight`
- **Then** the row under «Queued» shows «Waiting chunk 2/3», «waiting 40 s» and the total time, with «1/3 done» and «waiting for a free backend place» in the titles

## Edge cases and failure behavior

- An entry without `wait_s` (older daemon, or queued before its first place) shows only the total.
- A daemon without `state` keeps the single list, unchanged.
- Values from `/api/inflight` are escaped in text and titles.

## Non-functional requirements

- Compatibility: only an added optional field; consumers (panel, mod, hooks) ignore unknown fields.
- Panel rules: dashboard, no paragraphs; same tokens and fonts; verified in light and dark.

## Non-goals

- The mod's status band.
- Changing how chunks queue for places.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
