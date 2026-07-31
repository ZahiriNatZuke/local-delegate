# Handoff: Un gate que mire los steps para que el job fantasma no bloquee un merge

## Current state

- SDD status: `closed`
- Último gate: `memory`
- Revisión: PR **#90** mergeado (`main` en `36c815d`), ruleset ya aplicado.

## What changed

- **`scripts/ci_gate.py`** (solo stdlib): da el veredicto del run mirando los **steps** de cada job.
- **`ci-gate`** en `ci.yml`, sin `needs`, con `actions: read` y 30 min de techo.
- **`tests/test_ci_gate.py`**: 21 tests, incluida la lista atada a `ci.yml` por conjuntos iguales.
- **Ruleset**: entra `ci-gate`, sale `test (windows-latest)`; los otros cinco intactos.
- Wiki y CHANGELOG.

## Decisions

Las que un futuro lector **no** puede deducir del código:

1. **`needs` + `always()` está descartado y no hay que reintentarlo:** `needs` espera a que el job
   termine, que es justo lo que no pasa.
2. **`timeout-minutes` se queda en `ci.yml` a propósito**, aunque no rescate del fantasma: cubre el
   otro modo de fallo, un job atascado ejecutando de verdad.
3. **Automatizar `cancel` + `rerun` se descartó por permisos:** habría pedido `actions: write`.
4. **Solo salió `test (windows-latest)` del ruleset**, pudiendo haber salido los cuatro de `ci.yml`.
   Decisión del usuario: si el gate tuviera un defecto, se desprotege un job y no todos.
5. **`install-smoke` pasa a bloquear un merge**, decidido en esta sesión. Depende de PyPI en vivo:
   un índice degradado bloqueará PRs sin que nada esté roto. Cierra de paso un pendiente del backlog.
6. **El orden importó y sigue importando:** primero el job, luego el merge, y **solo después** el
   ruleset. `verify_checks` del propio script es la red de seguridad, y se comprobó que se niega.

## Next action

Nada pendiente de este change. **Lo único que queda es una confirmación que no depende de nosotros:**
la próxima vez que GitHub cuelgue un job, comprobar que `ci-gate` lo nombra como fantasma y que el
merge no se bloquea.

## Memory

- Nota canónica: `projects/local-delegate/backlog.md` (se retira el punto del job fantasma) y la
  retrospectiva de la jornada.
- Índices: `MEMORY.md` de Claude Code.
