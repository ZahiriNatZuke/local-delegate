# Implementation plan: El check del daemon compara versiones por desigualdad

## Approach

Aplicar en `_probe_daemon` el patrón que `_probe_published` ya usa dos funciones más arriba en el
mismo módulo: `_compare_versions` en vez de `!=`, y una rama por sentido. No se inventa nada — las
dos piezas necesarias (`_compare_versions` y `_upgrade_hint`) existen y están probadas.

El estado se queda en `warn` en los tres caminos de diferencia: difieran como difieran, hay algo que
atender, y así el exit code de `doctor` no cambia para nadie.

## Ordered tasks

1. **Distinguir los dos sentidos en `_probe_daemon`**
   - Files: `src/local_delegate/checks.py`
   - `order = _compare_versions(version, installed)`; `None` → aviso sin `fix_hint`; `< 0` → daemon
     viejo (`RESTART_HINT`); resto → instalación atrasada (`_upgrade_hint()`).
   - Requirements: REQ-002 a REQ-006
   - Rollback: revertir el bloque; no hay estado persistido.

2. **Tests de los dos sentidos y del incomparable**
   - Files: `tests/test_checks.py`
   - Requirements: todos
   - Verification: `uv run pytest -q`

3. **CHANGELOG**
   - Files: `CHANGELOG.md` (sección `Unreleased`, **editar con la herramienta de edición**: es CRLF)
   - Requirements: n/a

## Test strategy

- **Unit**: los tres caminos nuevos más el `ok` de versiones iguales, con `_installed_version` y
  `daemon_status` doblados. El test del orden numérico usa `0.9.0` vs `0.18.0`, que comparadas como
  texto darían el resultado contrario.
- **Verificar al revés**: dejar `!=` en su sitio debe romper el test del caso nuevo, y comparar como
  texto debe romper el del orden.
- **Manual**: `local-delegate doctor` desde el CLI de `uv tool` (0.17.0) contra el daemon en 0.18.0
  — que es el caso que lo destapó.
- **Security**: sin dependencias, red ni escritura nuevas.

## Migration and compatibility

Aditivo sobre el mensaje: ninguna otra pieza lee el `detail` (es texto de interfaz, y hay regla
escrita de no parsearlo). El exit code no cambia.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback — no hay: cambio de mensaje y de
      rama en un probe de solo lectura.
- [x] Dependencies and configuration changes are explicit — ninguna.
- [x] The plan does not include unrelated work — el CLI de `uv tool` y `cli.published` quedan fuera.
