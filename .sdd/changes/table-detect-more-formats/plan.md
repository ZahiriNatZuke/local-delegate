# Implementation plan: Detector de tablas: GFM sin tuberías externas, |-|-|, CSV, TSV y ARIA; local_summarize sube a long con tabla (#650)

## Approach

`table_detect.table_format(text)` devuelve el primer formato que encuentra (`html`, `aria`,
`markdown`, `csv`, `tsv`) o `None`; `has_table` queda como `table_format(...) is not None`. El
aviso de cifras de #630 pasa a preguntar el formato y se queda en HTML, ARIA y Markdown (REQ-013),
para no abrirlo en logs de CI con tabuladores. Cada regla es una pasada
lineal con `str.find`/`split`/`count`, sin `re`.

- GFM: una línea con `|` sobre una fila delimitadora con `|` y `-`, cuyas celdas son `-` con `:`
  opcional en los extremos, en igual número que la cabecera (dos o más). La regla de #586 sigue
  delante, así ninguna tabla que viera antes se pierde.
- CSV/TSV: tres o más líneas seguidas que son «filas» con el mismo número de separadores fuera de
  comillas dobles. Una línea no es fila si empieza con blanco, marca de lista, cita o comentario;
  si lleva `{ } [ ] ; =` (salvo el separador), `: ` o un `(` pegado; si una celda pasa de 8
  palabras (3 cuando todos los separadores van seguidos de blanco, como escribe la prosa); o si
  acaba en separador con ese estilo de prosa (lista partida) o en `;` (sentencia). Calibrado contra
  todo el árbol del repo (fuentes, docs, SDD, benchmarks): cero CSV/TSV en `.py`, `.md`, `.json`,
  `.log`, `.yaml`; los aciertos nuevos son `.csv`, `.tsv` y salidas tabulares de git.
- ARIA: `role=` seguido de `table`/`grid`/`treegrid`/`row`; las clases no cuentan (Bootstrap usa
  `row`/`col` para maquetar cualquier página).
- `server`: `_table_role(probe_len, content, enabled)` comparte la subida; `_extract_role` la usa
  con su interruptor y su mínimo de campos; `local_summarize` decide el rol después de leer, marca
  `_ROLE_REASON` y el token con `_mark_role_reason`, va envuelta en `_role_reason_scope` (movido
  delante de `local_summarize`, sin cambios) y añade `_with_table_role_notice` en su postproceso.
  El camino estructurado queda atado al tamaño.

## Ordered tasks

- [x] T1 — Detector ampliado y su docstring (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006)
  - Files or modules: src/local_delegate/table_detect.py, tests/test_table_detect.py
  - Verification: pytest tests/test_table_detect.py; barrido del árbol con un script de scratchpad
  - Depends on: none
- [x] T2 — `format` en `role_reason` de `local_extract` y su descripción (REQ-007, REQ-008)
  - Files or modules: src/local_delegate/server.py, tests/test_extract_table_routing.py
  - Verification: pytest tests/test_extract_table_routing.py
  - Depends on: T1
- [x] T3 — Subida de rol de `local_summarize`, aviso, interruptor y descripción (REQ-009, REQ-010, REQ-011)
  - Files or modules: src/local_delegate/server.py, src/local_delegate/config.py, i18n es/en mcp.json, tests/test_summarize_table_routing.py, tests/test_summarize_grounding.py
  - Verification: pytest tests/test_summarize_table_routing.py tests/test_summarize_grounding.py
  - Depends on: T1
- [x] T5 — Hallazgos de la revisión del plan: cifras de #630 en sus formatos, celda final vacía, camino de error (REQ-013, REQ-014, REQ-015)
  - Files or modules: src/local_delegate/server.py (`_FIGURE_TABLE_FORMATS`), src/local_delegate/table_detect.py, tests/test_summarize_grounding.py, tests/test_table_detect.py, tests/test_summarize_table_routing.py
  - Verification: pytest de esos tres ficheros
  - Depends on: T1, T3
- [x] T4 — Documentación (REQ-012)
  - Files or modules: CHANGELOG.md, README.md, docs/wiki/Tools.md, docs/wiki/Configuration.md, docs/wiki/Architecture.md, docs/wiki/Savings-and-metrics.md, docs/recipes/claude-code-integration.md
  - Verification: pytest tests/test_extract_table_routing_docs.py; suite entera
  - Depends on: T2, T3

## Test strategy

- Unit: positivos por formato (con celda vacía, comillas, `;`, CRLF), negativos de prosa, código,
  logs, YAML, JSON, listas, PowerShell; barrido de `src/`, `tests/` y `docs/`; once entradas
  hostiles de 1 MB en proceso hijo.
- Integration: las dos tools contra un backend falso; filas del log en `tmp_path`.
- End-to-end or manual: no cambia prompts; la prueba en vivo de latencia/modelo la decide la sesión principal.
- Security and secret scanning: entrada no confiable sin `re`; sin secretos en el diff.

## Migration and compatibility

- `role_reason` gana una clave (`format`); quien lea `reason` sigue igual. La fila del log no cambia.
- Cambia el enrutado por defecto de `local_summarize` para entradas pequeñas con tabla; se apaga
  con `LOCAL_DELEGATE_SUMMARIZE_TABLE_LONG=0`.
- Tests existentes modificados a propósito: la lista de «las otras tres tools siguen en
  mecánico» pierde `local_summarize`; `_expected_reason` gana `format`; los tests de #630 apagan la
  regla para seguir contando solo su aviso; los casos «no ve» de CSV, TSV, GFM y `|-|-|` pasan a «ve».

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
