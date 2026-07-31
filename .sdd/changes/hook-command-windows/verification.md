# Verificación (modo lite): el comando del hook se rompe en Windows

## Entorno

- El trabajo se mergeó el 2026-07-30 (PRs **#55** y **#57**) y se publicó en la **0.14.0**.
- Verificación fresca del **2026-07-31** sobre `main` en `b8c43cd`, Windows 11, Python 3.13 (`uv`).

## Evidencia original (2026-07-30)

Bug **reproducido antes de tocar nada**:

```
$ sh -c 'echo python C:\Users\Yohan\.claude\hooks\x.py'
python C:UsersYohan.claudehooksx.py          # ← se comió las barras
$ sh -c 'echo python "C:/Users/Yohan/.claude/hooks/x.py"'
python C:/Users/Yohan/.claude/hooks/x.py     # ← intacto
```

312 tests, lint, formato y `node --check` verdes.

## Verificación fresca (2026-07-31)

| Requisito | Comprobación | Resultado |
| --- | --- | --- |
| REQ-001 · REQ-002 | `tests/test_install.py::test_hook_command_survives_a_windows_path` | pasa |
| REQ-004 | `tests/test_checks.py::test_backend_401_is_unknown_not_down` | pasa |
| REQ-001 · REQ-002 · REQ-003 | Los dos hooks registrados en el `~/.claude/settings.json` **real** de esta máquina | `python "C:/Users/Yohan/.claude/hooks/local-delegate/suggest_lint_summary.py"` y su par de `UserPromptSubmit`: **citados**, con barras `/` y **cero** barras invertidas |
| REQ-003 | El hook corriendo **en producción** | el `PreToolUse` de `suggest_lint_summary.py` inyectó su `additionalContext` varias veces durante esta misma sesión |

## Comprobaciones de calidad

- [x] Los dos tests citados por el brief pasan hoy.
- [x] Sin dependencias nuevas.
- [x] Secretos: ninguno en juego.

## El pendiente que dejó el brief, ya resuelto

El brief cerraba con: «el usuario tuvo que borrar sus hooks para desbloquearse; hay que volver a
registrarlos». **Está hecho**: los dos hooks aparecen registrados y correctos en el
`settings.json` real, y corren. El `install` end-to-end en Windows también se hizo, contra un HOME
simulado, antes de publicar la 0.14.0.

## Desviaciones y riesgo residual

- **El `state.json` de este cambio se había escrito a mano** con un modo inexistente y cuatro
  gates ausentes, así que `personal-harness` no podía leerlo. Se reparó el 2026-07-31 sin aprobar
  ningún gate a mano: los cuatro que faltaban se añadieron en `pending` y se recorrió la máquina
  con el harness.
- Ningún riesgo residual del código: el arreglo elimina la decisión que fallaba (citar solo a
  veces) en vez de afinarla.
