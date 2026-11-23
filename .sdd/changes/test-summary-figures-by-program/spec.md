# Specification: Resumen de salidas de tests: totales y versión por programa, y aviso de negación sin falsos positivos

## Summary

Issue #714, dentro de la causa común de `.sdd/changes/text-tools-common-cause/research.md`
(comprobaciones por palabras que se equivocan y cifras que el programa conoce pero se le piden al
modelo). Dos cambios visibles:

1. El aviso del #684 («el resumen niega … pero la salida de tests sí los cuenta») deja de saltar
   sobre resúmenes fieles: la coma corta la negación, una cifra en letras cuenta como cifra, y la
   palabra «errores» solo se compara con los `error`/`errors` del runner, no con los `failed`. El
   aviso cita la línea del runner que cuenta la categoría negada, no la última.
2. Cuando la entrada trae la línea de totales de un runner (pytest, jest, cargo), `local_summarize`
   y `local_lint_summary` terminan con **una línea fija escrita por el programa** con esos totales
   tal como los da el runner y, en pytest, la versión de Python y de pytest de la cabecera. Si el
   resumen nombra otra versión de Python, además sale un aviso.

### Decisión: línea fija, y aviso solo donde la comparación es exacta

- **Línea fija** para totales y versión: el principio de hoy es que lo que el programa sabe
  calcular no se le pide al modelo. La línea no depende de leer la prosa del modelo, así que no
  puede dar un falso positivo ni un falso negativo: siempre dice la cifra buena, al lado de la del
  modelo.
- **Aviso de versión distinta**: la versión es un token exacto (`Python 3.11.5` frente a
  `3.11.15`); compararla es una igualdad de cadenas, sin léxico.
- **Sin aviso por recuentos**: comparar «Veintiocho pruebas» con `216 passed` exige leer cifras en
  letras y saber si la frase habla del total o de un fichero («3 fallos en test_a.py» es legítimo
  en un resumen de lint). Es justo la comprobación por palabras que se equivoca; la línea fija ya
  da la cifra buena. Queda fuera a propósito.

## Requirements

<!-- One block per requirement. Request quotes the literal fragment of the request, or says
"derived: <reason>". Verify starts with one method: test, cmd, manual or review. -->

- **REQ-001** — La coma corta el alcance de una negación: «Sin fallos, con pruebas omitidas»
  sobre `10 passed, 4 skipped` no avisa; salvo la coma de una lista de categorías («No se
  reportaron fallos, saltos ni errores» sigue avisando, como en `main`).
  - Request: "La coma no corta la negación"
  - Verify: test tests/test_test_summary_figures.py::test_a_comma_ends_the_negation
- **REQ-002** — Una cifra escrita en letras entre la negación y la palabra (dos a veinte, treinta a
  noventa, cien, mil; two a ninety, hundred, thousand) cuenta como cifra y corta la negación: «No
  hubo fallos salvo dos omitidas» no avisa. «un/una/uno/one» no cuentan (son también artículo).
  - Request: "una cifra escrita en letras tampoco"
  - Verify: test tests/test_test_summary_figures.py::test_a_figure_in_words_ends_the_negation
- **REQ-003** — `errors` es su propia categoría: «errores»/«errors» solo avisan si el runner contó
  `error`/`errors`; «fallos»/«failures» siguen comparándose con fallos y errores juntos (como hasta
  ahora). «1 falló, sin errores» sobre `1 failed, 10 passed` no avisa; «sin errores» sobre
  `1 error` sí.
  - Request: "`failed` y `errors` van en la misma categoría"
  - Verify: test tests/test_test_summary_figures.py::test_errors_are_their_own_category
- **REQ-004** — El aviso de negación cita la línea del runner que cuenta la categoría negada (F3
  del review del #684), no la última línea encontrada.
  - Request: "derived: F3 del review.md del SDD summarize-test-totals-negation"
  - Verify: test tests/test_test_summary_figures.py::test_the_warning_cites_the_line_that_counts
- **REQ-005** — Con la línea de totales de pytest, jest o cargo en la entrada (y si la respuesta no la cita ya literal), `local_summarize` y
  `local_lint_summary` (llamada única y troceada) añaden tras el resumen, entre sus avisos, una
  línea del programa con esos
  totales (`216 passed, 3 skipped`) y, si hay cabecera de pytest, `Python 3.11.15, pytest 8.3.4`.
  Sin línea de totales, la respuesta no cambia. Textos en es y en.
  - Request: "Con salida de pytest, los totales y la versión salen de la línea de totales y de la cabecera, por programa."
  - Verify: test tests/test_test_summary_figures.py::test_summarize_adds_the_program_line
- **REQ-006** — Si el resumen nombra `Python X.Y[.Z]` distinto del de la cabecera de pytest, sale
  un aviso `[local-delegate warning: …]` con la versión escrita y la de la entrada; la misma
  versión no avisa.
  - Request: "o como verificación con aviso si el resumen da otra cifra. Elige con criterio y justifícalo en el spec."
  - Verify: test tests/test_test_summary_figures.py::test_another_python_version_is_flagged
- **REQ-007** — Sin regresiones ni backtracking: los tests existentes de `local_summarize`,
  `local_lint_summary` y el #684 siguen verdes sin tocarlos; patrones acotados por línea
  (400 caracteres como mucho) y lineales sobre entrada hostil.
  - Request: "hecho: verde, tests existentes intactos"
  - Verify: cmd pytest -n 2 de la suite completa con pesado.sh

## Acceptance scenarios

### Scenario: el resumen del día

- **Given** una salida de pytest con `platform win32 -- Python 3.11.15, pytest-8.3.4` y
  `216 passed, 3 skipped in 12.34s`
- **When** el modelo escribe «Python 3.11.5 … Veintiocho pruebas … dos omitidas … tres omitidas»
- **Then** el resumen vuelve igual, seguido de la línea del programa con `216 passed, 3 skipped` y
  `Python 3.11.15, pytest 8.3.4`, y un aviso de versión distinta.

### Scenario: resumen fiel

- **Given** `10 passed, 4 skipped`
- **When** el modelo escribe «Sin fallos, cuatro pruebas omitidas»
- **Then** sin aviso; solo la línea del programa.

## Edge cases and failure behavior

- Varias líneas de totales: la línea del programa lista hasta 3, separadas por « | », y cuántas
  más hay.
- Go (`--- FAIL:` por test) no tiene línea de totales: no hay línea del programa (sí el aviso de
  negación, como antes).
- Un error del backend no lleva línea ni aviso (son `postprocess`).

## Non-functional requirements

- Determinista, sin llamadas extra al backend ni cambios de prompt.

## Non-goals

- Avisar de recuentos distintos en la prosa (ver «Decisión»); F4 a F7 del review del #684.
- «Ninguna de las dos pruebas fue omitida»: «dos» corta la negación (falso negativo raro, aceptado).
- Un log de pytest sin fallos en `local_lint_summary` sigue respondiéndose por programa
  (`_lint_no_findings`), que ya cita la línea de totales del log.
- Versiones que la entrada nombra en otro sitio (un aviso «removed in Python 3.14», otra sesión de
  tox) cuentan como reales: no avisan.
- `local_extract`, `locate*.py`, `line_check.py`.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
