# Especificación (modo lite): el comando del hook se rompe en Windows y bloquea cada prompt

> **Reconstruida a posteriori el 2026-07-31.** Este cambio se trabajó en un modo ligero anterior
> que solo escribía `brief.md` y un `state.json` **hecho a mano**, con un `mode` (`lightweight`)
> que no existe en el esquema y cuatro gates ausentes: `personal-harness` no podía ni leerlo. El
> `brief.md` original sí es completo y es la fuente de esta reconstrucción, junto con el diff
> mergeado y verificación fresca.

## Resumen

`local-delegate install` deja el cliente **usable** en los tres sistemas: el comando que registra
en los hooks sobrevive a una ruta de Windows.

## Requisitos

- **REQ-001:** El comando que `hook_command` registra **cita siempre** la ruta del script, no solo
  cuando tiene espacios.
- **REQ-002:** La ruta se escribe en forma POSIX (`as_posix()`), así que ningún `\` puede ser
  interpretado como escape por el shell.
- **REQ-003:** El comando resultante funciona en `sh`, `cmd` y PowerShell, en los tres sistemas.
- **REQ-004:** `doctor` **no da por caído** un backend que responde `401`/`403`: eso es «responde y
  rechaza la credencial», no «no responde».

## Escenarios de aceptación

### Escenario: el usuario escribe un prompt en Windows

- **Dado** un `install` sobre un HOME de Windows
- **Cuando** Claude Code dispara el hook `UserPromptSubmit`
- **Entonces** el script corre y emite su `additionalContext` con exit 0, en vez de bloquear el
  prompt

### Escenario: el backend responde 401

- **Dado** un llama-swap vivo que rechaza la credencial del entorno
- **Cuando** corre `doctor`
- **Entonces** lo reporta como desconocido con el motivo, y no manda a arrancar un servicio que ya
  está corriendo

## Comportamiento en los bordes

- Un hook `UserPromptSubmit` que falla **no degrada: bloquea**. No hay modo parcial — o el comando
  es correcto o el usuario no puede escribir.

## No objetivos

- Cambiar el formato de los hooks (`args` vs string de shell): el formato heredado con `args` es
  válido y funciona.

## Trazabilidad

- REQ-001 · REQ-002 · REQ-003 → `install.py` (`hook_command`, `_quote`) +
  `tests/test_install.py::test_hook_command_survives_a_windows_path`
- REQ-004 → `checks.py` (`backend_probe`) +
  `tests/test_checks.py::test_backend_401_is_unknown_not_down`
