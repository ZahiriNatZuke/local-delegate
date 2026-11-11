# Specification: Detector de tablas: GFM sin tuberías externas, |-|-|, CSV, TSV y ARIA; local_summarize sube a long con tabla (#650)

Nivel: lite. Disparador: decisiones que el diff no explica (qué heurística de CSV/TSV, qué se deja
fuera) y una función visible nueva (la subida de rol de `local_summarize`). No cambia ningún prompt.

## Summary

`table_detect` reconoce, además de HTML y Markdown con `--`, las tablas GFM sin tuberías
externas, el separador `|-|-|`, los roles ARIA de tabla, y filas de CSV (coma o punto y coma) y de
TSV, y dice qué formato vio. `local_extract` lo lleva en `role_reason.format`. `local_summarize`
aplica la misma subida a `long` a una entrada pequeña con tabla, con su aviso, su fila de log y su
interruptor.

## Requirements

- **REQ-001** — `table_format` devuelve `markdown` para una tabla GFM sin tuberías externas
  (`a | b` sobre `--- | ---`) y para el separador compacto `|-|-|`, con el mismo número de celdas
  en cabecera y delimitador (dos o más).
  - Request: "ampliar el detector a GFM sin tuberías externas y `|-|-|`"
  - Verify: test tests/test_table_detect.py
- **REQ-002** — `table_format` devuelve `csv` para tres o más líneas seguidas con el mismo número
  (dos o más) de comas o puntos y coma fuera de comillas, y `tsv` para tres o más con el mismo
  número (uno o más) de tabuladores, también con una celda vacía.
  - Request: "CSV y TSV (heurística determinista y barata: p. ej. ≥ 3 líneas consecutivas con el mismo número ≥ 2 de separadores fuera de comillas"
  - Verify: test tests/test_table_detect.py
- **REQ-003** — Prosa con comas o punto y coma, código (llamadas, imports, sangría, `#define`,
  Makefile), logs (Python, pytest), YAML, JSON y JSON lines, listas Markdown y PowerShell no dan
  `csv` ni `tsv`; ningún `.py` de `src/` ni de `tests/` ni ningún `.md` de `docs/` da `csv` o `tsv`.
  - Request: "cuida falsos positivos en prosa con comas, código, logs, YAML/JSON"
  - Verify: test tests/test_table_detect.py
- **REQ-004** — Las rejillas de `<div>` se detectan solo por un rol ARIA de tabla (`table`, `grid`,
  `treegrid`, `row`, con o sin comillas, cualquier caja): formato `aria`. Las clases (`row`, `cell`,
  `grid`) no cuentan y un test lo fija.
  - Request: "Rejillas de `<div>`: decide con criterio si se detectan de forma fiable [...]; si no, déjalo fuera y escríbelo"
  - Verify: test tests/test_table_detect.py
- **REQ-005** — El detector sigue sin expresiones regulares y cada entrada hostil de 1 000 000 de
  caracteres (las cinco de antes y seis nuevas para CSV/TSV, GFM y ARIA) se resuelve en menos de 1 s.
  - Request: "Sin regex con backtracking catastrófico (entrada no confiable)"
  - Verify: test tests/test_table_detect.py
- **REQ-006** — El docstring del módulo describe todos los formatos que ve, lo que no ve y que ya
  lo usan `local_extract` y `local_summarize` (no «cuando se mida»).
  - Request: "Corrige el docstring del detector"
  - Verify: review table_detect.py
- **REQ-007** — `local_extract` con una entrada pequeña con tabla responde
  `_local_delegate.role_reason = {"role": "long", "reason": "table", "format": <formato>, "notice": …}`;
  la fila del log sigue con `role_reason: "table"`.
  - Request: "Que el aviso `_local_delegate.role_reason` diga qué formato vio"
  - Verify: test tests/test_extract_table_routing.py
- **REQ-008** — La descripción de `local_extract` nombra los formatos que ahora ve, `format` y lo
  que sigue sin ver; ya no dice «CSV, TSV and <div> grids are not seen».
  - Request: "actualiza la descripción de la tool `local_extract` [...] para que diga la verdad tras el cambio"
  - Verify: review server.py
- **REQ-009** — `local_summarize` con una entrada por debajo de `LOCAL_DELEGATE_LONG_INPUT_CHARS`
  que trae una tabla llama al modelo `long`, termina con un aviso que nombra el formato y su fila
  del log lleva `role_reason: "table"`; sin tabla, o ya grande por tamaño, nada cambia.
  - Request: "`local_summarize`: aplicar la misma regla de subida a `long` para entradas pequeñas con tabla (mismo detector), con su `role_reason`"
  - Verify: test tests/test_summarize_table_routing.py
- **REQ-010** — `LOCAL_DELEGATE_SUMMARIZE_TABLE_LONG=0` devuelve `local_summarize` al enrutado
  solo por tamaño; por defecto está encendida, está registrada en `ENVIRONMENT_VARIABLES` y no
  depende de `LOCAL_DELEGATE_EXTRACT_TABLE_LONG`.
  - Request: "variable para apagarlo análoga a `LOCAL_DELEGATE_EXTRACT_TABLE_LONG`"
  - Verify: test tests/test_summarize_table_routing.py
- **REQ-011** — La descripción de `local_summarize` nombra la regla y su interruptor; el motivo no
  se filtra a la operación siguiente; la entrada subida por la tabla no toma el camino por secciones.
  - Request: "descripción de la tool actualizada"
  - Verify: test tests/test_summarize_table_routing.py
- **REQ-012** — CHANGELOG, README y wiki (Tools, Configuration, Architecture, Savings-and-metrics)
  y la receta de Claude Code describen los formatos nuevos, `format` y el interruptor nuevo.
  - Request: derived: regla del repo «una release toca CHANGELOG, README y docs/wiki»
  - Verify: test tests/test_summarize_table_routing.py
- **REQ-013** — La revisión de cifras del aviso de #630 sigue solo en los formatos que #630 midió
  (HTML y Markdown, más ARIA, que es HTML): un CSV o un TSV pequeño (p. ej. un log de CI con
  tabuladores) no la abre.
  - Request: derived: revisión adversarial del plan; el detector ampliado cambiaría #630 sin medirlo
  - Verify: test tests/test_summarize_grounding.py
- **REQ-014** — Una fila TSV cuya última celda está vacía (tabulador final) cuenta como fila; un
  CSV sin blancos tras las comas con la última celda vacía también.
  - Request: derived: revisión adversarial del plan (REQ-002 pide «también con una celda vacía»)
  - Verify: test tests/test_table_detect.py
- **REQ-015** — Si el backend falla después de subir el rol, cada fila de la operación de
  `local_summarize` lleva `role_reason: "table"` y la primera llamada es al modelo largo.
  - Request: derived: revisión adversarial del plan (camino de error)
  - Verify: test tests/test_summarize_table_routing.py

## Acceptance scenarios

### Scenario: un CSV pequeño con una celda vacía

- **Given** `plan,seats,price\nbasic,,9\npro,20,29\n`
- **When** se pide `local_extract(fields=["seats"])` o `local_summarize`
- **Then** la llamada va a `long`; extract dice `format: "csv"`, summarize termina con el aviso «(csv)»

### Scenario: prosa con comas

- **Given** tres líneas de un párrafo con dos o más comas cada una
- **When** se llama cualquiera de las dos tools
- **Then** va por tamaño (mecánico) y no lleva `role_reason`

## Edge cases and failure behavior

- Celdas entre comillas con comas dentro: las comas no cuentan. Comillas sin cerrar en la línea:
  no es fila.
- Enumeración corta en prosa (`Rojo, verde, azul y rosa.` en tres líneas): sube; fijado por test
  como error conocido del lado de subir.
- `\r\n`: se trata como `\n`.
- Fila TSV con la primera celda vacía (empieza por tabulador, como el código sangrado) y CSV con
  blanco tras cada coma y última celda vacía (`pro, 20,`, igual que una lista partida): no son
  filas; escrito en el docstring y fijado por test.
- Error del backend: el aviso de formato va solo en un resumen (postproceso); el error no lo
  lleva, pero sus filas sí llevan `role_reason`. El aviso dice «fue al modelo de contexto largo»
  aunque responda el respaldo (`code`), igual que el de `local_extract`; `fallback` en el log dice
  quién respondió.
- Un log de CI con tabuladores (`gh run view --log`) se lee como TSV: un resumen pequeño de uno va
  a `long`. Es una tabla de verdad; su revisión de cifras no se abre (REQ-013).

## Non-functional requirements

- Lineal en la longitud de la entrada, sin `re`; puro e importable sin `server`.
- No cambia ningún prompt ni parámetro de modelo: no necesita prueba en vivo de prompt.

## Non-goals

- El aviso de valor cruzado de `local_extract` (otro agente, otra parte de `server.py`).
- El caso grande del #586.
- El espejo de `summary_model` en los hooks (`hook_common.py`): solo decide si el modelo está en
  enfriamiento para ficheros que el hook bloquea, que pasan de `LD_HOOK_READ_SUGGEST_KB` (8 KB por
  defecto, por encima de los 6000 de `LOCAL_DELEGATE_LONG_INPUT_CHARS`) y ya van a `long` por tamaño.
  Límite conocido: con `LD_HOOK_READ_SUGGEST_KB` por debajo del umbral, o el umbral por encima, el
  hook puede mirar el enfriamiento del mecánico para un fichero con tabla que el servidor manda al
  largo; solo afecta a si se bloquea una lectura, no al resultado.
- Medir el volumen de resúmenes pequeños que subirán: lo hace la sesión principal con el log de
  uso real (que este agente no debe tocar); el riesgo queda en `verification.md`.
- CSV de dos columnas, celdas multilínea, tablas alineadas con espacios, rejillas por clases.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
