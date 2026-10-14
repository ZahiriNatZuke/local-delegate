# Controles positivos de B2b-2 (tras quitar package_version)

## M5 fila sin versión al tramo «después»
- fichero: `scripts/measurement_boundaries.py`
- test: `tests/test_response_language.py::test_the_boundary_is_decided_by_version_not_by_date`
- resultado: FALLA (bien)
- assert: `>       assert mb.usage_side({"ts": late}, boundaries) == mb.BEFORE`
- primera línea E: `E       AssertionError: assert 'after' == 'before'`

## M9 el lector mira package_version y no v
- fichero: `scripts/measurement_boundaries.py`
- test: `tests/test_response_language.py::test_the_boundary_is_decided_by_version_not_by_date`
- resultado: FALLA (bien)
- assert: `>       assert mb.usage_side({"ts": early, "v": "0.36.0"}, boundaries) == mb.AFTER`
- primera línea E: `E       AssertionError: assert 'before' == 'after'`

## M10 la fila vuelve a llevar package_version
- fichero: `src/local_delegate/server.py`
- test: `tests/test_response_language.py::test_usage_rows_carry_the_version_in_v`
- resultado: FALLA (bien)
- assert: `>       assert "package_version" not in row`
- primera línea E: `E       AssertionError: assert 'package_version' not in {'ts': '2026-10-14T21:09:10+00:00', 'tool': 'local_summarize', 'model': 'm', 'source': 'inline', ...}`
