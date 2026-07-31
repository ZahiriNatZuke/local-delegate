# Verification: Borrar scripts/update_to_latest.sh, que el CLI sustituyo

## Environment

- **Revisión:** rama `chore/borrar-update-to-latest`, sobre `main` en `a0a061e`.
- **Suite:** 463 tests, 1 skipped (sin cambio: no se toca código).

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | El fichero deja de existir | OK | `ls scripts/update_to_latest.sh` → *No such file or directory* |
| REQ-002 | Sin referencias vivas | OK | `grep` sobre el árbol (excluyendo `.sdd/`, hallazgo R-2) deja **cuatro** menciones y las cuatro son histórico: la entrada nueva del CHANGELOG, `CHANGELOG.md:92` y `:456` —de versiones ya publicadas— y `docs/wiki/Remote-backend.md:98`, que lo nombra en pasado para explicar la regla del repositorio |
| REQ-003 | CHANGELOG, CRLF | OK | sección `Removed` nueva bajo `Unreleased`; `CRLF=925, LF sueltos=0` |
| REQ-004 | CI verde | OK | los cuatro pasos, abajo |

### AC-2 — la vía que lo sustituye funciona

```
$ local-delegate update --dry-run --home <sim>
local-delegate update — HOME: …\simhome2
  (--home simulado: se repara ese árbol y NO se toca ningún servicio)
```

El envoltorio no tenía lógica propia: hacía `exec local-delegate update "$@"`, así que esto es
literalmente lo mismo que hacía él.

## Quality checks

- [x] **Tests:** `uv run pytest -q` → **463 passed, 1 skipped**.
- [x] **Lint:** `uv run ruff check .` → *All checks passed!*
- [x] **Formato:** `uv run ruff format --check .` → *53 files already formatted*
- [x] **Secretos:** el cambio **retira** un fichero ejecutable del repositorio; reduce superficie.
- [x] **Sin cambios ajenos:** el borrado, `CHANGELOG.md` y la traza SDD.

## Deviations and residual risk

- **La premisa del pendiente era falsa y quedó corregida.** El backlog decía «huérfano»; el
  fichero **documentaba su propia razón de existir** (el hábito de teclear la ruta en la Mac) y su
  fallback a `python3 -m local_delegate update` funciona —verificado antes de borrarlo—. Se
  retiró por decisión explícita del usuario con ese dato delante, no por estar muerto.
- **Las menciones en pasado no se tocaron, a propósito** (hallazgo R-1). Explican de dónde salió
  la regla «lo que ejecuta el usuario va al CLI; lo que ejecuta el repositorio se queda en
  `scripts/`». Borrar el porqué junto con la cosa es justo lo que permitiría que alguien vuelva a
  poner un instalador ahí.
- **Coste aceptado:** quien tenga el hábito verá `No such file or directory`. La wiki documenta
  `local-delegate update` como la vía desde el PR #70.
- **Reversible:** `git revert`, y el contenido queda en el histórico.
- **Verificación al revés:** no aplica —no hay comportamiento que romper para ver si un test lo
  detecta—. Lo equivalente es el `grep` sobre el árbol y el CI en verde.
