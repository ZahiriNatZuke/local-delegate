# Brief: Codex: matriz de capacidades y alternativas para barra, comandos sin modelo y tools fijadas (#671)

## Problem

El mod de Claude Code fija tools, ofrece comandos sin modelo y pinta una banda de estado. En Codex
no se sabía qué de eso existe; el plugin de Claude no lleva su interfaz (#668).

## Desired outcome

Una matriz con evidencia y las alternativas nativas viables implementadas y probadas.

## In scope

- Matriz en la wiki, enlazada desde README.
- Tools directas en Codex con `omit_tools_from` (opción de `install`, conservada en `update`,
  visible en `doctor`).

## Out of scope

- Subcomando de CLI para usar con `!` (seguimiento).
- Hooks nuevos (#669 y #670 van en paralelo sobre `codex_hooks.SPECS`).

## Constraints and risks

- Nivel `standard`: toca el instalador de Codex.
- Sin tocar `~/.codex`, el daemon ni `~/.claude*`; pruebas con `CODEX_HOME` temporal.
- PC con poca memoria: tests con `pesado.sh`, `-n 1`, solo ficheros afectados.

## Open questions

- ¿Activar las tools directas por defecto? Cuesta unos 4 000 tokens por turno; queda opcional y lo
  decide la persona usuaria.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-16 Original request, verbatim:

  > Resolver #671: matriz de capacidades Claude Code <-> Codex con evidencia, e implementar las alternativas viables (standard porque toca el instalador de Codex).
