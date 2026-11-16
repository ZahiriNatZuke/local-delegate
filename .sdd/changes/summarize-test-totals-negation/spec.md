# Specification: local_summarize: aviso cuando el resumen niega una categoria que el runner de tests conto

## Summary

Cuando la entrada de `local_summarize` trae la línea de totales de un runner de tests y una frase
del resumen niega una categoría (fallos o errores, saltos) que ese runner cuenta por encima de
cero, la respuesta termina con un aviso que cita la frase y la línea del runner. El resumen no
cambia.

## Requirements

- **REQ-001** — La línea de totales de pytest (con o sin marco de `=`), jest, `cargo test` y las
  líneas `--- FAIL:`/`--- SKIP:` de `go test -v` se leen por programa y dan los recuentos de
  fallos (failed, error, errors) y saltos (skipped, ignored); la prosa sin duración ni formato de
  runner no cuenta como totales.
  - Request: "detectar en la fuente los totales de un runner de tests (pytest `N passed, M skipped/failed/errors`, y si es barato jest/cargo/go)"
  - Verify: test tests/test_summarize_runner_totals.py::test_the_totals_of_each_runner_are_read
- **REQ-002** — Un resumen que niega una categoría con recuento > 0 («No se reportaron fallos ni
  saltos», «sin saltos», «Ningún test fue omitido», «No failures or skips», «0 skipped»,
  «Without any skipped test») recibe un aviso `[local-delegate warning: …]` en es o en, con la
  frase, la línea del runner y la sugerencia de `local_lint_summary`; el resumen se devuelve tal
  cual. Vale con `path` y con `text`.
  - Request: "si el resumen niega una categoría con recuento > 0 («sin/no se reportaron … saltos/fallos», también en inglés), avisar con un warning claro"
  - Verify: test tests/test_summarize_runner_totals.py::test_the_summary_of_the_issue_comes_with_one_warning
- **REQ-003** — No avisa un resumen fiel: dice bien «2 saltados», niega solo lo que el runner no
  contó, pone una cifra entre la negación y la palabra, o separa con «y»/«pero»; ni una entrada
  sin línea de totales.
  - Request: "Tests: casos positivo, negativo (resumen que dice bien «2 saltados» no avisa)"
  - Verify: test tests/test_summarize_runner_totals.py::test_a_faithful_summary_is_not_flagged
- **REQ-004** — Sin backtracking catastrófico: patrones anclados por línea o por palabra, líneas
  de más de 400 caracteres y textos de más de 2 MB fuera; tiempo lineal sobre una entrada hostil.
  - Request: "Sin regex con backtracking catastrófico."
  - Verify: test tests/test_summarize_runner_totals.py::test_the_check_is_linear_on_hostile_input
- **REQ-005** — Los tests existentes siguen intactos y los nuevos fallan sin el cableado en
  `server.py`; CHANGELOG y wiki al día; textos en los catálogos es y en.
  - Request: "un control que demuestre que el test falla sin el fix. Los tests existentes deben seguir intactos."
  - Verify: cmd pytest de los ficheros de `local_summarize`, i18n y guardianes con pesado.sh

## Acceptance scenarios

### Scenario: el caso del issue

- **Given** una salida de `pytest -q` que termina en `750 passed, 2 skipped in 81.33s`
- **When** el modelo resume «… omitiendo 2 … No se reportaron fallos ni saltos.»
- **Then** el resumen vuelve igual y con un aviso que cita «ni saltos» y la línea de pytest

### Scenario: resumen fiel

- **Given** la misma entrada
- **When** el modelo resume «pasó 750 casos y saltó 2; no hubo fallos ni errores»
- **Then** no hay aviso

## Edge cases and failure behavior

- Varias líneas de totales: se suman. Go: se cuentan las líneas `--- FAIL:`/`--- SKIP:`.
- Una categoría se avisa una sola vez aunque el resumen la niegue varias veces.

## Non-functional requirements

- Determinista, sin llamadas extra al backend; sin cambios en el prompt.

## Non-goals

- Reescribir el resumen o cambiar el prompt.
- Runners sin línea de totales reconocible.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
