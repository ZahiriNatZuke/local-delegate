# Verification: El check del daemon compara versiones por desigualdad

## Environment

- Base: `main` en `9d2c242` (0.18.0 publicada). Rama `fix/daemon-version-al-reves`.
- Windows 11, Python 3.11 (uv), pytest, ruff.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | versiones iguales → `ok` | OK | `test_daemon_on_the_installed_version_is_ok` |
| REQ-002 | daemon viejo → `warn` + `RESTART_HINT` | OK | `test_daemon_running_an_older_version_is_warn` |
| REQ-003 | daemon nuevo → `warn` + upgrade, **no** reiniciar | OK | `test_daemon_mas_nuevo_que_lo_instalado_manda_actualizar_no_reiniciar` |
| REQ-004 | comparación numérica (`0.9.0` < `0.18.0`) | OK | `test_las_versiones_del_daemon_se_comparan_como_numeros_no_como_texto` |
| REQ-005 | incomparables → `warn` sin `fix_hint` | OK | `test_versiones_del_daemon_incomparables_avisan_sin_ofrecer_arreglo` |
| REQ-006 | exit code sin cambios | OK | los tres caminos siguen en `WARN` |

### El caso real que lo destapó

```
[WARN] daemon: local-delegate 0.18.0 · pid 32660 — pero la versión instalada es 0.17.0:
       el daemon sirve la vieja
       arréglalo con: reinicia el daemon para que sirva la versión instalada
```

El daemon corría del venv editable (0.18.0) y el CLI de `uv tool` estaba en 0.17.0. El mensaje decía
lo contrario de lo que pasaba y el arreglo ofrecido no arreglaba nada.

### Verificación de los tests al revés

Tres defectos introducidos uno a uno; **los tres rompen el test que dice cubrirlos**:

| Defecto | Test que se pone rojo |
| --- | --- |
| vuelve a asumir que el viejo es siempre el daemon (`if True`) | `test_daemon_mas_nuevo_que_lo_instalado_…` |
| compara las versiones como texto | `test_las_versiones_del_daemon_se_comparan_como_numeros_…` (+ el de incomparables, esperado: comparar texto nunca da `None`) |
| las incomparables ofrecen reiniciar (`if False`) | `test_versiones_del_daemon_incomparables_…` |

El script de mutación trabaja con **bytes crudos** a propósito: `read_text`/`write_text` en Windows
convertirían el fichero de LF a CRLF entero, que es justo lo que ensució el diff en el change
anterior. Comprobado que `checks.py` queda restaurado **byte a byte**.

## Quality checks

- [x] Project-native tests pass — **556 passed, 1 skipped** (eran 553).
- [x] Lint and formatting — `ruff check .` y `ruff format --check .` en verde.
- [x] Secret scanning — sin credenciales; el change solo toca un mensaje y una comparación.
- [x] No unrelated changes — `checks.py`, `tests/test_checks.py` y `CHANGELOG.md`.

## Deviations and residual risk

- **No se prueba end-to-end el caso nuevo en esta máquina** después del arreglo, porque para verlo
  haría falta dejar el CLI atrasado a propósito. El caso quedó reproducido **antes** del fix con la
  salida real de arriba, y los tests cubren los tres sentidos.
- El defecto simétrico en `cli.published` **no existe**: esa función ya comparaba con
  `_compare_versions`. Comprobado leyéndola, no asumido.
