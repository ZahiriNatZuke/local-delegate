# Specification: El check del daemon compara versiones por desigualdad, no por cuál es más nueva

## Summary

Cuando la versión que sirve el daemon y la instalada difieren, `doctor` dice **cuál de las dos está
atrasada** y ofrece el comando que arregla **esa**, en vez de asumir siempre que la vieja es la del
daemon.

## Requirements

- **REQ-001:** Versiones **iguales** → el check sigue en `ok`.
- **REQ-002:** Daemon **más viejo** que la instalada → `warn`, el detalle dice «el daemon sirve la
  vieja» y el `fix_hint` es `RESTART_HINT`.
- **REQ-003:** Daemon **más nuevo** que la instalada → `warn`, el detalle dice que **la instalación
  está atrasada** y el `fix_hint` es `_upgrade_hint()`, **no** el de reiniciar.
- **REQ-004:** Las versiones se comparan **como números**, no como texto (`0.9.0` < `0.18.0`),
  reutilizando `_compare_versions`.
- **REQ-005:** Si no se pueden ordenar → `warn`, el detalle lo dice y el `fix_hint` queda **vacío**.
- **REQ-006:** El exit code de `doctor` no cambia: los tres caminos de diferencia siguen en `warn`.

## Acceptance scenarios

### Scenario: el caso encontrado en producción

- **Given** el daemon sirviendo `0.18.0` desde un venv editable y el CLI instalado en `0.17.0`
- **When** el usuario ejecuta `local-delegate doctor`
- **Then** la línea dice que **la instalación** está atrasada y ofrece el comando de upgrade,
  **no** «reinicia el daemon»

## Edge cases and failure behavior

- Versión del daemon ausente (`"?"`) → como hasta ahora: no se compara y el check sale `ok`.
- Versión instalada desconocida (`None`) → igual, no se compara.
- Formato no numérico en cualquiera de las dos → REQ-005.

## Non-functional requirements

- Sin dependencias ni llamadas nuevas: `_compare_versions` y `_upgrade_hint` ya existen.
- `_upgrade_hint()` importa `update` de forma **diferida** (ciclo `update` → `checks`): no
  introducir un import a nivel superior.

## Non-goals

- Que `update` actualice el CLI de `uv tool` — descartado con motivo (hacerlo desde el propio
  entorno destruye la instalación en Windows).
- Tocar `cli.published`, que ya compara bien.

## Traceability

| Requisito | Verificación |
| --- | --- |
| REQ-001 | `test_daemon_on_the_installed_version_is_ok` |
| REQ-002 | `test_daemon_running_an_older_version_is_warn` |
| REQ-003 | `test_daemon_mas_nuevo_que_lo_instalado_manda_actualizar_no_reiniciar` |
| REQ-004 | `test_las_versiones_del_daemon_se_comparan_como_numeros_no_como_texto` |
| REQ-005 | `test_versiones_del_daemon_incomparables_avisan_sin_ofrecer_arreglo` |
| REQ-006 | los tres caminos devuelven `WARN`; `is_warning` sin cambios |
