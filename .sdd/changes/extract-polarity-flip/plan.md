# Implementation plan: local_extract: aviso cuando un valor invierte la negacion de la fuente

## Approach

Módulo nuevo `src/local_delegate/polarity.py`, hermano de `cross_fill.py` y con su misma forma
(función pública `flipped(source, fields, data, skip)` con tope de tamaño, presupuesto y frontera
que traga excepciones). `local_extract` lo llama justo después de `cross_fill.cross_filled`, con
los campos de ubicación en `skip`, y añade `polarity_flipped_keys` y su aviso a `late_notices`. El
prompt no cambia: la causa es el modelo, y cambiarlo mueve la huella de afinidad, los corpus
congelados y las fixtures de peticiones sin poder probarlo en vivo desde aquí. El cambio en
`server.py` son diez líneas fuera de los tramos que toca el PR #676.

## Ordered tasks

- [x] T1 — Confirmar la causa con tests que muestran que el valor vuelve tal cual (REQ-001)
  - Files or modules: tests/test_extract_polarity.py
  - Verification: tests con `_run_chat` doblado, con texto y con `path` + campo de ubicación
  - Depends on: none
- [x] T2 — Detector `polarity.py` y su cableado en `local_extract` con aviso es/en (REQ-002, REQ-004)
  - Files or modules: src/local_delegate/polarity.py, src/local_delegate/server.py, src/local_delegate/resources/i18n/es/mcp.json, src/local_delegate/resources/i18n/en/mcp.json
  - Verification: tests unitarios del detector y con backend falso
  - Depends on: T1
- [x] T3 — Puerta de falsos positivos sobre `tests/data/cross_fill/` y casos fieles (REQ-003)
  - Files or modules: tests/test_extract_polarity.py
  - Verification: 0 avisos en 177 respuestas
  - Depends on: T2
- [x] T4 — CHANGELOG, wiki, docstring y suite completa (REQ-005)
  - Files or modules: CHANGELOG.md, docs/wiki/Tools.md, src/local_delegate/server.py
  - Verification: pytest -n 2 con pesado.sh; ruff
  - Depends on: T2

## Test strategy

- Unit: `polarity.flipped` con seis inversiones (añadida y quitada, español, inglés, traducida,
  conjugada) y ocho casos fieles.
- Integration: `local_extract` con `_run_chat` doblado: aviso y valor intacto, silencio con la
  respuesta fiel, orden de avisos, campos de ubicación.
- End-to-end or manual: no hace falta prueba en vivo, el prompt no cambia.
- Control positivo: el test del aviso falla sobre `main` (sin el cableado) por falta de
  `_local_delegate`, que es la razón del issue.
- Security and secret scanning: sin secretos ni datos personales; la fuente del issue no se
  publicó y los tests usan una reconstruida.

## Migration and compatibility

- Solo añade una clave a `_local_delegate` y texto al final de `warning`; nada cambia de los
  valores ni de los avisos existentes.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
