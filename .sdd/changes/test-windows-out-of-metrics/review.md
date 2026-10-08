# Result review: Las pruebas fuera de las métricas: ventanas de prueba y una sola regla de exclusión en todo el panel

## Verdict

`conforms-with-notes` (revisor `personal-sdd-result-reviewer`, 2026-10-08; revisión parcial: dejó
sin mirar el detalle de los tests, la documentación y las evidencias).

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 a REQ-019, REQ-026 | sí | sí | `find` con bisect y `_max_end` revisado en bordes, abiertas y solapadas |
| REQ-020 | sí | sí | D8 abierta: solo ventanas en `medir_enfriamiento.py` |
| REQ-021 | sí (tras corregir) | sí | faltaba apartar las filas de banco: corregido |
| REQ-022 | parcial | sí | ver D8 |
| REQ-023 | preparado | no | T9 sin ejecutar en la PC |
| REQ-024, REQ-025 | sí | parcial | el revisor no miró la documentación |

## Findings

1. Media — `medir_adopcion.py` no apartaba las filas de banco (filas sin fundir). **Corregido** con
   `coste.fundir` y test con su control positivo.
2. Media — `medir_enfriamiento.py` aplica solo ventanas, no la regla común (REQ-022). **Abierto**:
   anotado como D8 en `spec.md` para que decida el usuario.
3. Baja — `test-window list` no contaba el log de nombre fijo (`config.USAGE_LOG`). **Corregido**,
   con test.
4. Baja — siembra no verificada en la PC (REQ-023). **Abierto**: pasos en `evidencias/T9.md`.
5. Baja — el índice de `Windows` se arma una vez. **Documentado** en el docstring.

## Required follow-up

- D8 (decisión del usuario).
- T9 en la PC real y sus cifras antes/después.
