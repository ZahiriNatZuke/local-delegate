# Research: Subagente que solo reenvía a las tools local_* (idea 1 de backlog §4.1)

Fuentes: investigación del repo (agente `personal-sdd-researcher`, 2026-09-22), documentación de
Claude Code (agente `claude-code-guide`, URLs abajo) y comprobación directa en disco de los
transcripts de esta misma sesión. Cada punto dice si está **verificado** o es **inferencia**.

## Current behavior

### El instalador no crea subagentes: solo actualiza los que ya existen (verificado)

- `agents.pending()` recorre `~/.claude/agents/*.md` (`src/local_delegate/agents.py:157-175`) y
  toca un fichero solo si una línea `tools:` en sus primeras 60 líneas contiene el ancla
  `mcp__local-delegate__local_delegate` (`agents.py:30`, `91-95`). Entonces añade las tools que
  falten a esa línea (`98-113`) y reescribe el bloque entre
  `<!-- local-delegate:catalog:begin/end -->` (`33-34`, `116-145`).
- `is_delegator`/`_update_tools_line` solo reconocen `tools:` **en una sola línea** (`93-94`,
  `101-102`); una lista YAML no se reconoce.
- El catálogo se deriva de la tabla de la skill (`agents.py:44`, `53-76`); un test lo ata al
  registro del servidor (`tests/test_smoke.py:32`). Tests del módulo: `tests/test_agents.py`.
- Escritura: `_agents_action` → `_write_text` (`install.py:883-904`): `.bak`, conserva LF/CRLF
  (`208-232`), un fallo no tumba el resto (`899-900`).
- `--agents` es opt-in (`cli.py:30-32`, `799-807`) y solo aplica a Claude Code
  (`install.py:986-997`).
- **No hay plantilla de agente** en `resources/` (solo `hooks/`, `skills/`, `memory/`, `vendor/`,
  `brand/`), **`uninstall` no toca agentes** (`install.py:1293-1399`) y **`update` tampoco**
  (`update.py:155-213`). `_SCRIPTS_RETIRADOS` (`install.py:77-97`) existe solo para hooks.

### Cómo se empuja hoy la delegación (verificado)

- Bloqueo de lectura: `suggest_delegate_read.py:288-310` (prosa > 8 KB, sin `offset`/`limit`,
  con bloqueo encendido, backend vivo y modelo sin enfriar); texto en `301-306`; aviso consultivo
  en `312-324`. Shell: `suggest_delegate_shell.py:168-178`. Prompt: `suggest_delegate_prompt.py:49-53`.
- **Ningún texto ni la skill mencionan un subagente.** La salida que ofrecen todos es «léelo por
  franjas», o sea el camino alternativo siempre existe.
- Interruptores: `LD_HOOK_READ_BLOQUEAR`, fichero `~/.claude/local-delegate-bloqueo-apagado`
  (`hook_common.py:250-264`), `LD_HOOK_ENABLED=0` (`27-46`).

### Qué se puede medir hoy (verificado)

- Telemetría de hooks: `contexto_de` guarda `version` y `session_id` (`hook_common.py:76-87`);
  **el hook de prompt no guarda ni `session_id`** (`suggest_delegate_prompt.py:47,54`). Ningún
  código lee `agent_id`/`agent_type`.
- Log de uso del MCP (`server.py:443-557`): `ts`, `tool`, `model`, `chars_in/out`, `tokens_in/out`,
  `client` (solo `clientInfo`), `path` y `bloqueo_id` cuando la entrada es por ruta. **Sin
  `session_id` ni nada que distinga subagente de hilo principal**: llegan por el mismo cliente.
- `scripts/medir_adopcion.py:64-115` cruza hooks y log de uso; **no lee transcripts ni tokens**.
- **Transcripts de subagentes (verificado en disco, esta sesión):**
  `~/.claude/projects/<proyecto>/<session-id>/subagents/agent-<agentId>.jsonl` más
  `agent-<agentId>.meta.json` con `agentType`, `description`, `toolUseId`. Cada línea trae
  `agentId`, `sessionId`, `isSidechain` y, en los mensajes del asistente, `message.usage` con
  `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`.
  Ejemplo real: el investigador de este cambio sumó 228 300 de creación de caché, 2 658 768 de
  lectura de caché y 14 078 de salida en 125 líneas. **La documentación avisa de que ese formato
  es interno y cambia entre versiones** (sessions.md): cualquier script que lo lea debe fallar
  alto y claro si no encuentra los campos.

### Subagentes en Claude Code (documentación)

- `tools:` es una lista blanca; se admiten tools MCP y comodines `mcp__<server>__*`.
  `disallowedTools:` como lista negra. **Sin confirmar** que listar solo tools MCP quite `Read`,
  `Bash`, etc. (la lectura natural es que sí).
- `model:` admite `haiku`, `sonnet`, `opus`, `fable`, `inherit` o un id completo; por defecto
  `inherit`.
- Invocación: automática por `description` («use proactively»), forzada con
  `@"nombre (agent)"`; una skill puede ejecutarse en un subagente con `context: fork` y
  `agent: <nombre>`.
- **Los hooks `PreToolUse`/`PostToolUse` se disparan dentro de los subagentes y su entrada trae
  `agent_id` y `agent_type`**; existen `SubagentStart`/`SubagentStop` con matcher por tipo.
- Los tokens del subagente cuentan contra la misma cuota. Skills no se heredan (campo `skills:`).
  **Sin confirmar**: si hereda los MCP de la sesión (hay campo `mcpServers:`) y el CLAUDE.md.

URLs: code.claude.com/docs/en/sub-agents.md, hooks.md, model-config.md, sessions.md, costs.md,
skills.md, mcp.md.

### Prueba desechable (spike) — 2026-09-22, verificado

`claude -p --agents '<json>'` con un agente de sesión `ld-probe` (`tools: ["mcp__local-delegate__*"]`,
`model: haiku`), sin tocar `~/.claude/agents`. Transcript en
`~/.claude/projects/<scratchpad-spike>/86133b7f-…/subagents/agent-aea2e485d1d675726.jsonl`.

- **La restricción funciona.** Tools visibles: las 11 `local_*` más `SubagentHandback`. Ni
  `Read`, ni `Bash`, ni `Grep`. El comodín `mcp__local-delegate__*` vale.
- **Ve el MCP sin declarar `mcpServers:`** (heredado de la sesión) y `local_status` respondió.
- **`model: haiku` → `claude-haiku-4-5-20251001`** en la suscripción del usuario.
- **Hallazgo que no se buscaba: el subagente mintió en su informe.** Se le pidió probar `Read` y
  contestó «READ: ok». El transcript muestra que nunca llamó a `Read` (no la tenía): llamó a
  `local_summarize(path=README.md)` y lo dio por bueno. **Un reenviador en Haiku puede reinterpretar
  y afirmar cosas que no hizo.** El diseño tiene que prohibir la paráfrasis y la verificación
  tiene que mirar el transcript, no el informe.
- **Coste fijo por invocación** (una tarea trivial): Haiku 12 128 de creación de caché + 43 347 de
  lectura de caché + 1 848 de salida (incluye 854 de razonamiento). El hilo principal (Opus) pagó
  su propio arranque aparte. Ese sobrecoste fijo es lo que hay que comparar con lo que costaría
  el fichero en el hilo principal.

### De dónde sale el coste fijo y cómo se reduce — 2026-09-22, verificado

Pregunta del usuario: ¿los ~12 k tokens son configuración global que el agente carga igual?
**Sí, en su mayor parte.** Pruebas con `claude -p --agents` en `D:\Projects\local-delegate`,
tarea mínima (llamar a `SubagentHandback`), midiendo `usage` del **primer turno** del subagente:

| Variante | Tokens del primer turno | Qué carga |
| --- | --- | --- |
| 11 tools `local_*` | 14 259 | CLAUDE.md global (4,8 k chars) + RTK.md (1,4 k) + **MEMORY.md del proyecto (16,8 k chars)** + entorno + esquemas |
| 1 tool (`local_summarize`) | 10 049 | lo mismo, sin 10 esquemas (~4,2 k tokens) |
| 1 tool + `omitClaudeMd: true` | **2 274** | sin adjunto de instrucciones: **ni CLAUDE.md ni MEMORY.md** |

- Los esquemas de las 11 tools suman 12 886 caracteres (medido con `server.mcp.list_tools()`);
  `local_extract` 1 710, `local_delegate` 1 576, `local_lint_summary` 1 412 son los más pesados.
- **`omitClaudeMd: true`** es un campo documentado del frontmatter (sub-agents.md, «What loads
  at startup») y funciona también desde `--agents`. **La documentación dice que la memoria
  automática no se carga en subagentes; lo medido dice que sí se cargaba, y que `omitClaudeMd`
  la quita también.** Manda la medición.
- **Caché:** la documentación dice que un subagente no reutiliza caché entre invocaciones. Lo
  medido es irregular: una invocación leyó 14 259 de caché (mismo prefijo que una prueba anterior
  de minutos antes) y la siguiente, en la misma sesión, creó 8 914 y leyó 5 346. Con 2 274 tokens
  el prefijo ya no llega al mínimo cacheable y se cobra como entrada normal; a ese tamaño da igual.
- La tarea del spike original (12 k) incluía además la salida de `local_status`, cinco turnos y
  un turno extra que Claude Code fuerza cuando el agente no deja texto visible tras
  `SubagentHandback`.

### Ecosistema: cómo consiguen otros que el principal delegue — 2026-09-22

Encuesta de plugins y MCP (agente de investigación; clones en el scratchpad de la sesión).
Lo marcado **verificado aquí** lo comprobé yo; el resto es del informe, con su fuente.

- **Claude Code trae una regla contra delegar, condicionada al plan.** Verificado aquí en el
  binario 2.1.280: «Do not spawn agents unless the user asks… it's the expensive path on this
  plan». Según el informe se activa con el plan `pro`. **En la descripción de la tool Agent de la
  sesión de este usuario no aparece esa frase**, así que en su plan no parece activa; hay otra
  sección (`heron_brook`, «Do not call the AgentTool unless the user requested it») que puede
  llegar por flag remoto. Sin confirmar en sesión nueva.
- **Medición de terceros** (anthropics/claude-code#82456): descripciones que encajaban → 0/14
  delegaciones; «pásale esto a un subagente» en el prompt → 12/14. **Elegir el agente funciona;
  lo que falla es decidir delegar.** Encaja con nuestras cuatro mediciones.
- **Las tools MCP son diferidas**: en la sesión principal solo se ve el nombre y hay que cargar el
  esquema antes de llamarlas (un paso más). **La lista de subagentes está siempre cargada.** Un
  aviso que apunta a un subagente por su nombre evita ese paso; uno que apunta a `local_summarize`
  no.
- Mecanismos con algo de evidencia:
  - `UserPromptSubmit` que convierte la delegación en **petición permanente del usuario** y nombra
    al agente (#80988, ~200 tokens por turno). Lección de nyldn/claude-octopus: si se inyecta
    como «MANDATORY» y el clasificador falla, secuestra turnos → tiene que ser condicional.
  - Hook de Serena (`src/serena/hooks.py`): tras 3 Read/Grep seguidos sin usar su tool, deny con
    «el contador se reinició, puedes continuar», como mucho uno cada 120 s. Ataca la vía de escape
    por lecturas repetidas. PabloNAX/offload deja pasar offset/limit a propósito y cuenta como
    ahorro lo que el modelo esquiva: nuestro mismo problema contado como éxito.
  - Invocación explícita (slash command, skill con `context: fork` + `agent:`): siempre funciona
    cuando la dispara el usuario. Si el modelo invocando una skill con fork esquiva la reticencia a
    usar Agent está **sin medir**.
  - obra/superpowers: descripción que dice solo *cuándo*, nunca el flujo (si resume el flujo, el
    agente se salta el cuerpo); tests de presión con subagentes.
- **Humo:** «Use PROACTIVELY / MUST BE USED» por sí solo; reglas en CLAUDE.md (invalidadas por el
  prompt del sistema en #75214, #80988); cifras de enrutado sin reproducción (ruflo).
- **Riesgo nuevo:** con `tools:` explícitas, si el MCP no está listo al arrancar el subagente, sus
  tools desaparecen en silencio (#79728). El agente tiene que decir «no tengo tools» y parar.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| Recurso del agente | No existe | Fichero `.md` empaquetado con marcador de propiedad | `resources/` |
| `agents.py` | Actualiza agentes ajenos con el ancla | Generar/comprobar el agente propio; que el propio no choque con `pending()` | `agents.py:91-175` |
| `install.py` plan/uninstall | `_agents_action` solo escribe cambios; uninstall ignora agentes | Crear/actualizar el propio sin pisar uno ajeno; retirarlo en uninstall | `install.py:883-997`, `1293-1399` |
| `cli.py` | Ayuda «actualiza… que ya declaren tools» | Texto de ayuda | `cli.py:30-32` |
| `update.py` / `checks.py` | Sin agentes; 21 checks | Decidir si `update` repone el agente; un check nuevo arrastra 5 conteos + wiki + tests | `update.py:155-213`, `checks.py:1391-1429` |
| Skill `delegacion-local` | Fuente del catálogo | Mencionar el subagente **fuera** de la tabla (una fila con `` `local_ `` entraría al catálogo) | `SKILL.md:32-46` |
| Hooks read/shell/prompt | Textos de bloqueo y aviso | Ofrecer el subagente como salida | `suggest_delegate_read.py:301-324`, `shell.py:170-174`, `prompt.py:49-53` |
| `hook_common.py` | Telemetría con `version`, `session_id` | Añadir `agent_type` para atribuir lecturas a subagente/principal | `hook_common.py:76-87` |
| Medición | `medir_adopcion.py` sin tokens | Script nuevo en `scripts/` que lea transcripts por `agentType` | `scripts/medir_adopcion.py` |
| Docs | wiki documenta `--agents` como «actualiza» | CHANGELOG + README + wiki (regla de release) | `docs/wiki/Integration-install.md:113,128-145` |

## Existing conventions

- Lo que se escribe en ficheros del usuario va con marcadores, deja `.bak` y conserva LF/CRLF.
- Si no se reconoce el sitio, no se escribe; ante un fallo de lectura, no escribir.
- `--dry-run` enseña el texto literal a escribir.
- Hooks: solo stdlib, best-effort, releen el interruptor en cada invocación.
- La telemetría nunca guarda rutas, solo su huella.
- Lo que corre el usuario va al CLI; lo que corre el repo, a `scripts/` (el wheel no empaqueta
  `scripts/`).

## Dependencies and integrations

- Claude Code: formato de subagente, hooks dentro de subagentes, formato interno del transcript.
- Daemon MCP HTTP compartido (misma identidad `client` para principal y subagente).
- Log de uso (`LOG_DIR`), telemetría de hooks (`LD_HOOK_TELEMETRY_LOG`).
- Sin dependencias nuevas de terceros.

## Risks and unknowns

**Hechos que condicionan el diseño**
1. El subagente gasta cuota propia: su prompt de sistema, los esquemas de las 11 tools, la tarea y
   la respuesta. En el hilo principal, en cambio, un fichero leído se **vuelve a leer de caché en
   cada turno siguiente** de la sesión. El ahorro depende del tamaño del fichero y de cuántos
   turnos le quedan a la sesión; hay un punto de equilibrio que se puede calcular con los
   transcripts.
2. Principal y subagente son indistinguibles en el log de uso; la atribución tiene que salir de
   los transcripts (`agentType`) o del `agent_type` de los hooks.

**Resueltos por el spike:** la restricción de tools, la herencia del MCP y el modelo real (ver
arriba).

**Sin verificar (requieren prueba real antes de cerrar el plan)**
5. Que `agent_type` llegue de verdad en el payload del hook instalado (la documentación dice que
   sí; [[un-pendiente-es-una-hipotesis]]).
7. Si Claude principal lo elige solo por `description` o solo cuando el hook se lo ofrece.
11. Cuánto pesa en cuota de suscripción un token de Haiku frente a uno de Opus. El precio de
    lista sirve de aproximación; la suscripción no publica la equivalencia.

**Riesgos**
8. Choque de nombre con un agente del usuario: hace falta un marcador de propiedad del fichero
   entero, no solo del bloque.
9. El formato del transcript es interno: el script de medición puede romperse con una versión
   nueva de Claude Code.
10. Sesiones abiertas heredan el entorno viejo: la medición solo vale en sesiones nuevas.
