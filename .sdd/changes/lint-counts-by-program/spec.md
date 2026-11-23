# Specification: local_lint_summary: recuentos por fichero y por código por programa, con aviso si el resumen da otra cifra (#717)

Nivel `lite`: cambia la salida de `local_lint_summary` (una línea añadida y un aviso nuevo) en
los dos caminos (llamada única y troceado), sin llamadas nuevas al backend. Regla del análisis
`.sdd/changes/text-tools-common-cause/research.md`: lo que el programa sabe calcular no se le pide
al modelo.

## Summary

Para los logs cuyo formato ya reconoce `lint_patterns.per_file_code_counts` (ruff/flake8 conciso,
ruff completo, tsc), la respuesta lleva, tras el resumen del modelo, una línea fija con el
recuento por fichero y por código leído por el programa. Si el resumen da otra cifra para un
fichero o un código, o le pone a un fichero un código que el log no le da, sale un aviso que lo
nombra. Sin formato reconocido (eslint stylish, biome, pytest, CI), la salida es la de hoy.

## Requirements

- **REQ-001** — Con un log de formato reconocido, la respuesta lleva, tras el resumen y antes de los avisos, una línea del
  programa que da, por fichero, su total y su recuento por código, y el recuento por código del
  log entero; las cifras son las del log.
  - Request: "Que el programa añada una línea fija con el recuento por fichero y por código para los formatos que ya reconoce"
  - Verify: test tests/test_lint_counts_by_program.py
- **REQ-002** — Si una entrada del resumen da a un fichero otro total, otra cifra para un código,
  o un código que ese fichero no tiene en el log, o una línea fuera de las entradas da otra cifra
  para un código, la respuesta lleva un aviso que nombra cada discrepancia con la cifra del log.
  - Request: "Y que avise si el resumen del modelo da otra cifra para un fichero o un código"
  - Verify: test tests/test_lint_counts_by_program.py
- **REQ-003** — Un resumen con las cifras correctas no lleva aviso (sin falsos positivos con
  números de línea, de columna ni con el `Found N errors` del log).
  - Request: derived: un aviso que salta siempre no distingue nada
  - Verify: test tests/test_lint_counts_by_program.py
- **REQ-004** — Con un log sin formato reconocido (eslint stylish, pytest), no se añade línea ni
  aviso: la salida es la de antes.
  - Request: "Sin formato reconocido, se queda como hoy"
  - Verify: test tests/test_lint_counts_by_program.py
- **REQ-005** — La línea y el aviso van en los dos roles de la llamada única y en el troceado.
  - Request: derived: el formato del log no depende del tamaño
  - Verify: test tests/test_lint_counts_by_program.py

## Acceptance scenarios

### Scenario: el caso de la prueba de humo

- **Given** un log de ruff conciso con 4 avisos en dos ficheros (`core.py` con E501 ×2 y E741 ×1,
  `util.py` con F401 ×1) y `Found 4 errors.`
- **When** el modelo responde que `core.py` tiene un F401 y 3 errores, y `util.py` 2
- **Then** la respuesta trae la línea del programa con `core.py 3 (E501 2, E741 1)` y
  `util.py 1 (F401 1)`, y un aviso que nombra el F401 de `core.py` y el total de `util.py`

### Scenario: resumen correcto

- **Given** el mismo log
- **When** el modelo da las cifras correctas, con números de línea y columna
- **Then** hay línea del programa y no hay aviso

## Edge cases and failure behavior

- Muchos ficheros o códigos: la línea lista los primeros 10 de cada uno y dice cuántos más hay.
- Un fichero nombrado por su nombre base (`core.py` por `pkg/core.py`) cuenta como el mismo.
- Una entrada sin cifras no da aviso de cifras; sí uno de código ajeno si nombra un código que el
  fichero no tiene.

## Non-functional requirements

- Expresiones regulares acotadas y lineales sobre la línea (entrada no fiable).
- Textos de salida en es y en (claves i18n nuevas), código en inglés.

## Non-goals

- Reconocer formatos nuevos (eslint stylish o unix, biome): queda como hoy.
- Pytest: ya tiene sus hechos de fallos (#641) y de totales (#714/#715).
- Cambiar el prompt del modelo.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
