# Specification: local_explain_code sobre un diff troceado: índice completo y líneas del patch (#582)

## Summary

Con `path` a un diff unificado que se trocea, `local_explain_code` entrega el índice completo de
ficheros con su rango de líneas en el patch, calculado por programa, y los prompts no confunden
las cabeceras `@@` con líneas del patch. Toda respuesta troceada avisa de que lo es.

## Requirements

- **REQ-001** — `line_check.diff_file_ranges(content)` devuelve, para un diff unificado, un
  `(inicio, fin, ruta)` por fichero: inicio = línea de su cabecera (`diff --git`, o `--- ` seguida
  de `+++ ` y `@@` sin `diff --git`), fin = línea anterior a la cabecera siguiente o última línea no
  vacía; líneas contadas desde 1 cortando solo en `\n`. Ruta de `+++ b/`, o de `--- a/` si es un
  borrado, o de la cabecera `diff --git`. Para lo que no es diff, lista vacía.
  - Request: "el índice de ficheros con sus rangos de línea en el patch se puede sacar sin modelo"
  - Verify: test tests/test_explain_code_diff_index.py
- **REQ-002** — Con `path`, diff troceado: cada trozo del map lleva, por programa, los ficheros del
  diff que contiene con sus líneas; el map pide una viñeta por fichero (no por función); el reduce
  recibe el índice completo y no se le prohíbe enumerar.
  - Request: "que el reduce no tire trozos en preguntas de enumeración"
  - Verify: test tests/test_explain_code_diff_index.py
- **REQ-003** — Con `path` y diff (troceado o no), el system dice que los números válidos son los
  del prefijo `N| ` (líneas del patch) y que los de las cabeceras `@@ -a,b +c,d @@` son del
  fichero, no del patch; e incluye la nota de lectura de diffs (`_DIFF_NOTE`).
  - Request: "¿el modelo cita números de las cabeceras `@@ -a,b +c,d @@` del propio diff en vez de los del fichero?"
  - Verify: test tests/test_explain_code_diff_index.py
- **REQ-004** — Con `path`, diff troceado: la respuesta termina con el índice completo calculado por
  programa (ruta: inicio–fin), hasta 200 ficheros y «…y N más».
  - Request: "O el índice completo de los 32 ficheros con sus rangos reales"
  - Verify: test tests/test_explain_code_diff_index.py
- **REQ-005** — Toda respuesta troceada de `local_explain_code` con pregunta o sobre un diff lleva
  un aviso con el número de trozos, aunque `FEEDBACK_ENABLED` esté apagado. La explicación simple
  de un fichero sin pregunta queda byte a byte (su salida está congelada por hash en
  `test_without_a_question_the_prompts_are_unchanged`, que no se toca).
  - Request: "Que una respuesta construida desde trozos lo diga siempre"
  - Verify: test tests/test_explain_code_diff_index.py
- **REQ-006** — Sin diff, los prompts de `local_explain_code` quedan byte a byte; con `code=` nada
  cambia; los tests existentes pasan sin tocarlos.
  - Request: "tests existentes intactos"
  - Verify: cmd pytest tests/test_explain_code_*.py y suite completa

## Acceptance scenarios

### Scenario: diff de 32 ficheros troceado

- **Given** un diff sintético de 32 ficheros > 20 000 chars y un backend falso
- **When** `local_explain_code(path=..., question="Lista los ficheros del diff con su rango de líneas")`
- **Then** la respuesta trae los 32 ficheros con sus líneas reales y el aviso de troceado

## Edge cases and failure behavior

- Diff sin `diff --git` (`diff -u`): cabeceras `--- `/`+++ ` seguidas de `@@`.
- Más de 200 ficheros: se corta la lista con «…y N más».
- Error del backend: sin índice ni aviso (el postprocess solo corre en éxito).

## Non-functional requirements

- Determinista, lineal, sin llamadas extra al modelo.

## Non-goals

- Responder sin modelo cuando la pregunta es solo el índice: detectarlo pide una heurística de
  idioma frágil, y el índice exacto ya va siempre al final.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
