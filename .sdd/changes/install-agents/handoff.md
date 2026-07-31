# Handoff: local-delegate install --agents mantiene los subagentes al dia con el catalogo real

## Current state

- **SDD status:** cerrado.
- **Último gate:** `memory`.
- **Revisión:** PR **#82** mergeado el 2026-07-31, `main` en `efb28b5`. Los 12 checks del PR y el
  CI completo de `main` en verde. **En `Unreleased`, sin publicar.**

## What changed

Módulo nuevo `agents.py` y flag `install --agents` (opt-in). Retirada
`docs/recipes/update_agents.py`. 478 tests (+15).

## Decisions

1. **El catálogo se deriva de la tabla de `SKILL.md`**, no se escribe. Es un recurso empaquetado y
   lo que el usuario ya lee, y evita importar `server.py` (SDK MCP + uvicorn) para responder algo
   que es texto.
2. **Y esa fuente no puede mentir:** `test_smoke.py` compara sus nombres con
   `server.mcp.list_tools()` en **conjuntos iguales, no inclusión**. Una fila sobrante sería una
   tool retirada que se sigue anunciando y que `--agents` propagaría a 27 agentes.
3. **`--agents` es el único componente que se pide en vez de excluirse.** Los subagentes los
   escribió el usuario; tocarlos sin pedirlo sería el error del viejo `--target all`.
4. **Solo se tocan los que ya declaran el ancla.** Un subagente ajeno ni se abre — y el test lo
   fija comprobando que no queda ni un `.bak`.
5. **`uninstall --agents` queda fuera**: qué hacer con las tools ya añadidas al `tools:`, que el
   usuario pudo editar, no tiene respuesta obvia.
6. **`agents.py` no importa nada del paquete** (solo `re` y `pathlib`): recibe la ruta de la
   skill. Ver abajo.

## Gotchas que costaron tiempo aquí

- **CodeQL bloqueó el merge por un ciclo de imports real.** `agents` importaba `install` y
  `install` importa `agents`; funcionaba solo porque el segundo era diferido. Se arregló
  invirtiendo la dependencia (la ruta se pasa), no silenciándolo.
- **Un merge `BLOCKED` con los 12 checks en verde NO es un fallo de infraestructura.** El ruleset
  tiene `required_review_thread_resolution: true`, así que dos comentarios sin resolver de
  `github-advanced-security` lo bloqueaban. Se diagnostica con `gh pr view --json reviews` y los
  `reviewThreads` de la API GraphQL — no con `gh pr checks`, que los daba todos en verde.
- **Un defecto lo encontró la ejecución real, no los tests:** `.lower()` sobre la descripción
  convertía «lint/tests/**CI**» en «lint/tests/ci». Solo se ve mirando la salida.

## Next action

**Los 27 subagentes reales siguen sin actualizar**: solo se ejecutó `--dry-run`. Se aplican con
`local-delegate install --agents`, pendiente de autorización porque escribe en ficheros del
usuario.

Siguiente del backlog: punto 8 (nada obliga a regenerar la captura del README) y punto 9 (el
amarillo del botón de idioma de la landing).

## Memory

- **Nota canónica:** pendiente de la nota de jornada en el vault (`projects/local-delegate/`).
- **Índices actualizados:** `CHANGELOG.md` (`Added` y `Removed`) y
  `docs/wiki/Integration-install.md` (sección nueva y el flag en la tabla).
- Sin secretos, credenciales ni datos personales.
