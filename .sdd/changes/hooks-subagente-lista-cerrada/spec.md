# Specification: Hooks y bloque gestionado ante subagentes con lista cerrada de tools (#664)

## Summary

Un subagente cuya definición cierra la lista de tools sin las `local_*` no recibe avisos,
bloqueos ni recordatorios que lo manden a ellas; el bloque de `CLAUDE.md` y la skill dicen qué hacer
cuando un subagente no tiene `ToolSearch` ni las `local_*`. Todo lo demás se comporta como hoy.

## Requirements

- **REQ-001** — Con una entrada de hook cuyo `agent_type` corresponde a una definición
  `.claude/agents/*.md` (del proyecto, de `cwd` hacia arriba o `CLAUDE_PROJECT_DIR`, o del usuario)
  con un `tools:` explícito sin comodín y sin ninguna tool que contenga `local-delegate`, los hooks
  de `Read` (prosa grande y código en subagente) y de shell no emiten aviso ni bloqueo y registran
  `reason="mcp_absent"`.
  - Request: "que el hook que resume lecturas grandes no bloquee/resuma cuando quien llama no puede delegar"
  - Verify: test tests/test_hooks_mcp_absent.py
- **REQ-002** — Un `tools:` que nombra las `local_*`, un `*`, una definición sin `tools:`, un
  `agent_type` de plugin, con forma de ruta, vacío o sin definición, y la entrada sin `agent_type`
  se comportan como hoy (aviso o bloqueo).
  - Request: derived: no romper el comportamiento de los agentes que sí pueden delegar
  - Verify: test tests/test_hooks_mcp_absent.py
- **REQ-003** — Un `tool_use` de una `local_*`, o un `deferred_tools_delta` que las añade, en el transcript propio de quien llama gana a la
  definición (cuenta como presente); el transcript del principal no cuenta para un subagente.
  - Request: derived: la definición puede no ser la que Claude Code cargó
  - Verify: test tests/test_hooks_mcp_absent.py
- **REQ-004** — `SubagentStart` no emite el recordatorio de cargar las tools para un agente que
  cumple REQ-001, y lo sigue emitiendo para uno que hereda las tools.
  - Request: "el bloque de CLAUDE.md da por hecho que todo subagente puede cargar las tools"
  - Verify: test tests/test_hooks_mcp_absent.py
- **REQ-005** — El bloque gestionado y la skill, en es y en, dicen qué hacer sin `ToolSearch` ni
  las `local_*`: quien lanza delega antes y pasa el resultado, o elige un tipo que herede las tools
  o nombre `mcp__local-delegate__local_*`; el subagente lee por rangos y lo dice en su informe.
  - Request: "que el bloque gestionado diga qué hacer cuando el subagente no tiene ToolSearch/local_*"
  - Verify: test tests/test_skill_parity.py
- **REQ-006** — Probado instalado: `install` en un HOME simulado escribe el bloque nuevo y los
  hooks instalados callan con el subagente cerrado y avisan con el abierto, sin tocar la config real.
  - Request: derived: regla del encargo «hooks se prueban INSTALADOS»
  - Verify: cmd installed_probe.py (HOME simulado, hashes antes/después)
- **REQ-007** — CHANGELOG «Unreleased» y la wiki describen el cambio.
  - Request: derived: regla de release (CHANGELOG, README, wiki)
  - Verify: review CHANGELOG.md, docs/wiki/Claude-plugin.md, docs/wiki/Integration-install.md

## Acceptance scenarios

### Scenario: revisor de lista cerrada lee un Markdown grande

- **Given** `~/.claude/agents/closed-reviewer.md` con `tools: Read, Grep, Glob` y el bloqueo encendido
- **When** ese subagente hace `Read` completo de un `.md` de 29 KB
- **Then** la lectura pasa sin `deny` y la telemetría anota `mcp_absent`

### Scenario: agente que nombra las local_*

- **Given** una definición con `tools: Read, Bash, mcp__local-delegate__local_extract`
- **When** hace la misma lectura
- **Then** el hook bloquea como hoy (`large_prose`)

## Edge cases and failure behavior

- Carpeta o fichero ilegible, frontmatter roto o con una forma YAML que el parser no lee entera,
  fichero mayor de 256 KB: se ignora y, ante la duda, como hoy. De cada carpeta se miran como mucho
  300 ficheros (primero `<agent_type>.md`) y de cada uno sus primeros 16 KB. Nunca una excepción sale
  del hook.

## Non-functional requirements

- Solo lectura de ficheros pequeños; sin red; stdlib.

## Non-goals

- Cambiar el mod; leer agentes de plugins; `local_status` con las tools de la sesión.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
