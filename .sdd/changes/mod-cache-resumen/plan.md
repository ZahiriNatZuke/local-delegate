# Implementation plan: El mod de lectura reutiliza el resumen de un fichero sin cambios (#608)

## Approach

Caché en el mod (JS), no en el servidor. Motivos (evidencia):

- El 82 % de las repeticiones del #608 (129 de 157) son de la misma sesión, que es el mismo proceso
  de Claude Code donde vive el mod: la caché en memoria del mod las cubre sin disco.
- En el mod, un acierto no llega al servidor: no hay `tools/call` ni fila en el log de uso, así que
  el panel y `cost`/`attribution` no lo cuentan como ahorro nuevo sin tocar el esquema del log ni la
  escritura de telemetría (que otro agente está cambiando). El acierto queda en la telemetría de
  hooks por la vía que ya existe (`record-read`) con su propia decisión.
- En el servidor, la caché afectaría también a las llamadas del modelo (otro contrato) y exigiría un
  campo nuevo en el log y cambios en panel y mediciones.

Clave: la ruta normalizada del mod (`ctx.key`) más el texto completo del fichero leído con
`$.fs.read` (comparación exacta: no depende de mtime, de hash ni de `crypto.subtle`). Se lee antes
y después del resumen; solo se guarda si coinciden. Tope: 16 entradas y 4 M caracteres en total; un
fichero de más de 1 M caracteres no se guarda; se desaloja el más antiguo (LRU por reinserción en
`Map`).

No hay caché parecida que reutilizar en el mod; las del servidor (`backend_params._cache`,
`concurrency._RunningCache`) son de configuración y estado, no de resultados.

## Ordered tasks

- [x] T1 — Tests JS nuevos que fallan sin el arreglo (REQ-001, REQ-002, REQ-003, REQ-005, REQ-006)
  - Files or modules: `mod/read.test.ts`
  - Verification: `claude plugin test` falla en los tests nuevos sin el arreglo
  - Depends on: none
- [x] T2 — Caché de resúmenes en `mod/read.js` (estado, reinicio en `register`, lectura antes y después, decisión `summary_reused`) (REQ-001, REQ-002, REQ-004, REQ-005, REQ-006)
  - Files or modules: `mod/read.js`
  - Verification: `claude plugin test` en verde; `build_mod.py --check`
  - Depends on: T1
- [x] T3 — `summary_reused` en `hook_common.MOD_DECISIONS` y test Python de la línea escrita (REQ-003, REQ-004)
  - Files or modules: `resources/hooks/hook_common.py`, `tests/test_read_classifier.py`
  - Verification: pytest del fichero; `test_hook_boundaries` en verde (si pide huellas, `bump_version.py --boundaries`)
  - Depends on: none
- [x] T4 — CHANGELOG y suite completa (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006)
  - Files or modules: `CHANGELOG.md`
  - Verification: suite completa con `pesado.sh`, `ruff`
  - Depends on: T2, T3

## Test strategy

- Unit: `read.test.ts` con el `$` falso (lecturas repetidas, cambio de contenido, diálogo, topes); pytest de `record_decision`.
- Integration: el camino real del hook `tool.call` en los tests JS, no la función suelta.
- End-to-end or manual: no (requiere sesión de Claude Code con backend); queda como riesgo residual.
- Security and secret scanning: `personal-security-check` antes del commit; el texto del fichero no sale de memoria.

## Migration and compatibility

- Sin migración. Una `hook_common` vieja registraría `summary_reused` como `mod_decision` (no
  bloqueada); el mod y los hooks van en el mismo paquete.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
