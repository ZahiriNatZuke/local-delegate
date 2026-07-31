# Handoff: Auditoría del backlog: veredicto por punto

## Current state

- SDD status: `result-review`; gates `spec`, `plan`, `quality` y `conformance` aprobadas
- Rama: `feat/check-credencial-backend`, desde `main` en `b04a5e2`
- 568 tests + 1 skipped; los cuatro pasos del CI en verde en local

## What changed

- **Auditados los 18 puntos del backlog por ejecución.** 6 confirmados, 5 parciales, 4
  falsos/obsoletos, 3 no auditables en esta máquina. La tabla completa, con comando y salida, en
  `verification.md`.
- **`service.credential`, la comprobación nº16 de `doctor`**, y `doctor.backend_requires_key` que
  la alimenta.
- **`install --dry-run` imprime el texto literal** de lo que va a escribir (comandos de los hooks y
  entrada MCP de los dos clientes).
- CHANGELOG y `docs/wiki/Integration-install.md` al día (la tabla de checks y la nota de
  `--mcp-mode`).

## Decisions

1. **El check pregunta al backend SIN cabecera de autorización.** No es un detalle de
   implementación: es lo único que distingue «¿está sano el backend?» de «¿está abierto para quien
   no lleva la key?». El PR #100 hizo bien en preguntar al daemon para lo primero, y ese mismo
   camino es el equivocado para lo segundo — por eso conviven dos funciones y no una con un flag.
2. **Vive en el grupo `servicio`, no en `andamiaje`**, aunque lea las entradas MCP: el grupo
   `andamiaje` no sale a la red por contrato, y `install` depende de esa propiedad
   (`_SCAFFOLD_GROUPS` en `cli.py`).
3. **`--api-key-env` no es un arreglo para este caso**, y está escrito en el código: reenvía
   `${LOCAL_DELEGATE_API_KEY}`, que sale del mismo entorno que ya se vio vacío. El único arreglo
   que se ofrece es el daemon.
4. **El punto 4 (macOS) y el 16 (`elicitation` interactiva) se marcan no auditables**, no
   pendientes. Sin Mac y sin tty, un veredicto sería otra hipótesis disfrazada.
5. **El 9393 en la tailnet**: el usuario decidió **ponerle autenticación** en vez de quitarlo del
   `tailscale serve`. Es change propio.

## Next action

**Que el usuario ejecute** —el clasificador bloquea escribir en su config real—:

```
cd D:\Projects\local-delegate; uv run local-delegate install --clients claude --clients codex --no-hooks --no-skill --no-memory --mcp-mode http
```

Después, reiniciar Claude Code y Codex, y confirmar dos cosas: que `doctor` pasa a `[ OK ]` en
«credencial del backend», y que una tool `local_*` responde de verdad. Hasta entonces la
delegación sigue rota en esta máquina — el check la ve, pero no la arregla.

## Memory

- Canonical note: `projects/local-delegate/jornada-2026-07-31-el-backlog-auditado.md`
- Indexes updated: `projects/local-delegate/backlog.md` reescrito; puntero en `MEMORY.md`
