# Handoff: Borrar scripts/update_to_latest.sh, que el CLI sustituyo

## Current state

- **SDD status:** cerrado.
- **Último gate:** `memory`.
- **Revisión:** PR **#81** mergeado el 2026-07-30, `main` en `a556f04`. Los 12 checks del PR y el
  CI completo de `main` en verde. **En `Unreleased`** (solo desarrollo: `scripts/` no viaja en el
  paquete).

## What changed

Retirado `scripts/update_to_latest.sh`. Entrada nueva en el `CHANGELOG` bajo `Removed`.

## Decisions

1. **El pendiente decía «huérfano» y era falso.** El fichero documentaba su propia razón de
   existir —el hábito de teclear la ruta en la Mac— y su fallback a `python3 -m local_delegate
   update` funciona, verificado antes de borrarlo. Se retiró **por decisión del usuario** tomada
   con ese dato delante, no por estar muerto.
2. **Las menciones en pasado se conservan a propósito.** `CHANGELOG.md` (dos, de versiones
   publicadas) y `docs/wiki/Remote-backend.md:98` explican de dónde salió la regla del
   repositorio: *lo que ejecuta el usuario va al CLI; lo que ejecuta el repositorio se queda en
   `scripts/`*. Borrar el porqué junto con la cosa es lo que permitiría que alguien vuelva a poner
   un instalador ahí.
3. **Coste aceptado:** quien tenga el hábito verá `No such file or directory`.

## Gotchas

- **Al verificar «no quedan referencias», hay que excluir `.sdd/`.** Las trazas de changes
  anteriores lo mencionan y siempre lo harán; sin excluirlas, la comprobación daría un falso
  positivo permanente y el change no se podría cerrar nunca.

## Next action

Siguiente del backlog: punto 7, reubicar `docs/recipes/update_agents.py`. Por el criterio del
repositorio encaja como `local-delegate install --agents` — **pero conviene mirarlo antes de
asumirlo**, porque los dos pendientes anteriores de esta misma familia (el `.sh` de macOS y este
script) resultaron ser distintos de como los describía el backlog.

## Memory

- **Nota canónica:** pendiente de la nota de jornada en el vault (`projects/local-delegate/`).
- **Índices actualizados:** `CHANGELOG.md`, sección `Removed` nueva bajo `Unreleased`.
- Sin secretos, credenciales ni datos personales.
