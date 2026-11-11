# Specification: llama-swap: un solo lector del cmd

## Summary

Every read of a llama-swap `cmd` in `llamaswap_config` (model path, context size, cache types) gives
the same answer as `footprint.cmd_flags`: quotes, `--flag=value` and short forms are understood, and
a value that is not a positive integer (a `${macro}`) stays an estimate instead of an invented number.

## Requirements

- **REQ-001** — `model_context_size` returns `(32768, False)` for a `cmd` with `--ctx-size=32768`,
  `-c 32768` or `--ctx-size 32768`, and `(8192, True)` for `-c ${CTX}`.
  - Request: "cmd con --ctx-size=32768 (o -c ${macro}) → model_context_size da (8192, estimado)"
  - Verify: test tests/test_model_context_size.py
- **REQ-002** — `parse_model_gguf_path` returns the whole path for `-m "D:/Mis modelos/x.gguf"` and
  `-m 'D:/m/x.gguf'` (no quotes, no cut), so `estimate_model_vram` finds the file.
  - Request: "Una ruta entre comillas ... hace que init-llamaswap/check-llamaswap/residency --pin digan «fichero no encontrado» con la ruta cortada"
  - Verify: test tests/test_llamaswap_config.py
- **REQ-003** — `_parse_cmd_flags` and `footprint.cmd_flags` agree on `model`, `ctx_size`,
  `cache_type_k` and `cache_type_v` for every case of the repro; existing tests pass unchanged.
  - Request: "que llamaswap_config use un único lector (footprint.cmd_flags u otro común) para todas las lecturas del cmd"
  - Verify: test tests/test_llamaswap_config.py
- **REQ-004** — `doctor` and `local_status` already say when the context is the 8192 estimate
  (`context_estimated`); no change, recorded in the delivery.
  - Request: "Y que doctor y/o local_status digan cuándo el contexto es supuesto (8192 estimado) si no lo hacen ya"
  - Verify: test tests/test_doctor_backend_params.py tests/test_backend_params_status.py

## Acceptance scenarios

### Scenario: context written with `=`

- **Given** a llama-swap config whose model `cmd` has `--ctx-size=32768`
- **When** `model_context_size` reads it
- **Then** it returns `(32768, False)` and `_reasoning_fits` uses 32768

## Edge cases and failure behavior

- `-c ${CTX}`, `-c -1`, `-c` without a value: estimate (8192, True).
- Windows backslashes in an unquoted path are kept (the footprint tokenizer has no escapes).

## Non-functional requirements

- No new dependency; no import cycle (`llamaswap_config` already imports `footprint`).

## Non-goals

- Expanding llama-swap macros to their values.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
