# Handoff: Detectar y retirar los scripts de hooks huerfanos de instalaciones anteriores

## Current state

- **SDD status:** cerrado.
- **Último gate:** `memory`.
- **Revisión:** PR **#79** mergeado el 2026-07-30, `main` en `ac9a736`. Los 12 checks del PR y el
  CI completo de `main` en verde. **En `Unreleased`, sin publicar.**

## What changed

Check nuevo (`scaffold.hook_orphans`, el decimocuarto) que detecta los scripts nuestros sueltos en
la raíz de `~/.claude/hooks/`, e `install`/`update` los retiran con borrado quirúrgico.
463 tests (+12).

## Decisions

1. **El pendiente estaba mal diagnosticado y se corrigió con ejecución.** No hay entradas
   duplicadas en `settings.json`: los dos instaladores desregistran las versiones anteriores por
   el **nombre** del script (`install._is_ours` y el `existing_entries()` del `.sh` retirado). El
   problema son los **ficheros**, no el registro.
2. **La lista de «qué es nuestro» sale de `resources/hooks/*.py`**, no de `_SCRIPT_NAMES` — que
   tiene tres nombres y no incluye `hook_common.py`, uno de los huérfanos reales. Una constante
   paralela habría dejado un fichero atrás en todas las máquinas.
3. **Borrado quirúrgico:** fichero a fichero, por nombre exacto, solo en la raíz, solo si
   `is_file()`. Sin `.bak`, y es consciente: lo borrado son copias de recursos empaquetados que
   `install` repone, no configuración del usuario.
4. **`hook_orphans` nunca puede ser `missing`.** Pregunta si **sobra** algo, no si falta; en un
   HOME vacío la respuesta correcta es `ok`. Por eso está excluido de
   `test_empty_home_reports_missing_with_fix_hint`, junto a `scaffold.memory`.
5. **`__pycache__` y `telemetry.jsonl` no se tocan.** El segundo es dato del usuario y el backlog
   quiere **encender** esa telemetría, no borrarla.

## Gotchas que costaron tiempo aquí

- **`ctx.hooks_dir` YA es `hooks/local-delegate/`, no la raíz.** Un probe que mire ahí reportaría
  como huérfanos los scripts recién instalados e `install` los borraría acto seguido: la máquina
  se quedaría sin hooks y en bucle. Está a un identificador de distancia; hay un test dedicado.
- **Un test puede no probar nada aunque el código esté bien.** El del directorio homónimo pasaba
  igual con el `is_file()` quitado, porque `unlink` sobre un directorio lanza `OSError` y el
  `except` del retirado se lo traga. Solo lo destapó la verificación al revés. **Si al romper el
  código el test no falla, el test sobra o está mal escrito.**

## Next action

**Pendiente en esta máquina:** los cuatro huérfanos siguen ahí. Se limpian con
`local-delegate install`, pero borra ficheros del HOME real y esa autorización se pide aparte.
`--dry-run` ya se ejecutó contra el HOME de verdad y no tocó nada (mismo SHA-256).

Siguiente del backlog: punto 5, subir el `rev` de ruff en `.pre-commit-config.yaml` (0.6.9 contra
el 0.16 del proyecto).

## Memory

- **Nota canónica:** pendiente de la nota de jornada en el vault (`projects/local-delegate/`).
- **Índices actualizados:** `CHANGELOG.md` y `docs/wiki/Integration-install.md`.
- Sin secretos, credenciales ni datos personales.
