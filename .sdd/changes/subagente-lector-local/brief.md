# Brief: Subagente que solo reenvía a las tools local_* (idea 1 de backlog §4.1)

## Problem

Cuatro mediciones de adopción seguidas dan **cero delegaciones espontáneas**: Claude recibe el
aviso del hook (y, desde el 2026-09-12, el bloqueo de lectura) y aun así lee el fichero él mismo
por franjas u otro camino. La memoria `obediencia-no-viene-de-la-prosa` lo explica: una
instrucción se obedece cuando el camino alternativo **no existe**, cuando nunca se equivoca y
cuando esperar no cuesta. Hoy el camino alternativo (Read, Bash `cat`, lectura por franjas)
siempre existe.

`openai/codex-plugin-cc` resuelve el mismo problema con un subagente (`codex-rescue`) que tiene
**una sola tool** y la orden de devolver la salida tal cual: dentro de él no hay otro camino.

Evidencia: vault `projects/local-delegate/medicion-adopcion-delegacion.md`; backlog §4.1.

## Desired outcome

Un subagente de Claude Code instalado por `local-delegate install --agents` cuyas **únicas** tools
son las `local_*`, al que Claude principal le pasa «resume/extrae/clasifica X de esta ruta», y
una medición que diga si su uso **ahorra** cuota de verdad frente a que Claude lea el fichero él
mismo — con criterio de éxito y de retirada escritos antes de medir.

## In scope

- Definición del subagente (frontmatter, prompt de reenvío, modelo).
- Su instalación y actualización por el instalador existente (`agents.py` / `install --agents`).
- Cómo se ofrece a Claude principal (aviso del hook, skill `delegacion-local`).
- El protocolo de medición: qué se cuenta, de dónde se lee, cuándo se decide.

## Out of scope

- Comandos slash (idea 2), plugin (idea 3), trabajos en segundo plano (idea 4), relevo (idea 5).
- Codex, OpenCode y Claude Desktop: los subagentes `.md` son de Claude Code.
- Cambiar las tools `local_*` o los modelos.

## Constraints and risks

- **El subagente también gasta cuota** (su prompt de sistema, el catálogo de tools y la
  respuesta). Hipótesis a medir, no hecho.
- Los ficheros de `~/.claude/agents/` son del usuario: las reglas de `agents.py` (no tocar lo
  ajeno, `.bak`, marcadores) siguen valiendo.
- Firma de commits, ruleset de `main`, code scanning (ver memoria del proyecto).
- Una sesión abierta hereda el entorno viejo: la medición solo vale en sesiones nuevas.

## Open questions

- ¿Un subagente puede restringirse a tools MCP sin heredar Read/Bash? ¿Qué pasa con el hook de
  bloqueo dentro del subagente?
- ¿Haiku está disponible en la suscripción del usuario y qué modelo usa por defecto un subagente?
- ¿De dónde se lee el consumo de tokens de un subagente para comparar?
- ¿Cómo se entera Claude principal de que el subagente existe y cuándo usarlo?
