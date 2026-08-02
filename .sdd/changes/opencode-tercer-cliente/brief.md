# Brief: opencode como tercer cliente de `install`

## Problem

`local-delegate install` sabe configurar **dos** clientes: Claude Code y Codex. La lista está
escrita como una tupla de dos en `cli.py:33` (`_ALL_TARGETS`), como un par de pares en
`install.py:99` (`present_targets`) y como dos ramas en cada componente del plan de instalación.

**opencode** es hoy el tercer cliente de terminal con adopción real y habla MCP. Un usuario que lo
tenga instalado no tiene ningún camino soportado: ni `install` le escribe la entrada, ni `doctor`
mira si está, ni `update` la repone si desaparece. La única salida es editar
`~/.config/opencode/opencode.json` a mano — que es justamente lo que este paquete dejó de pedir en
la 0.15.0 para los otros dos.

Y no hay herencia que salve el caso: **está medido** que opencode **no** lee la configuración MCP
de Claude Code (`~/.claude.json`) ni la de Codex (`~/.codex/config.toml`) — ver `research.md` R1.

## Desired outcome

`local-delegate install` trata a opencode como a los otros dos: lo detecta solo, le escribe la
entrada MCP (stdio o HTTP contra el daemon), le deja la regla de delegación en su memoria global y
la skill donde su cargador la busca; `doctor` lo comprueba y `update` lo repone. Todo idempotente,
reversible y sin escribir secretos, con las mismas garantías que ya tienen Claude Code y Codex.

## In scope

- `--clients opencode` (y `--target opencode`), y detección automática por `~/.config/opencode`.
- Componente **mcp**: entrada `type: "local"` (stdio con `uvx`) o `type: "remote"` (HTTP contra el
  daemon), con `{env:VAR}` para la API key y el token del puerto.
- Componente **memory**: bloque gestionado en `~/.config/opencode/AGENTS.md`.
- Componente **skill**: `~/.config/opencode/skill/delegacion-local/SKILL.md`.
- `uninstall` retira exactamente eso, y nada más.
- Comprobaciones: `client.presence` y `scaffold.memory` cuentan a opencode; un
  `scaffold.mcp_opencode` nuevo.
- `update.REPAIRS`: reponer la entrada MCP y el bloque de memoria de opencode cuando falten.
- Documentación (`docs/wiki/Integration-install.md`, `README.md`, `docs/wiki/Daemon.md`) y
  `CHANGELOG`.

## Out of scope

- **Hooks.** opencode no tiene el mecanismo de hooks de Claude Code: su punto de extensión son
  *plugins* en TypeScript/JavaScript bajo `~/.config/opencode/plugin/` con otra superficie de
  eventos (`tool.execute.before`, `chat.message`, …). Nuestros tres hooks son scripts de Python
  que hablan el protocolo de stdin de Claude Code y **no portan**. Traducirlos es un change
  distinto, con su propio piloto A/B, no un apéndice de este.
- **Elicitation.** Medido: opencode declara solo `roots`, no `elicitation` (R8). `preguntas.py` ya
  degrada a lo de antes cuando falta la capability, así que aquí no hay nada que hacer — solo no
  prometerlo en la documentación.
- **Config de proyecto** (`./opencode.json`, `.opencode/`). `install` configura el HOME del
  usuario; escribir en el repo de al lado sería otra cosa.
- Cambiar el formato o la rotación de `clients.jsonl`. opencode aparecerá ahí solo, por el
  observador que ya existe.

## Constraints and risks

- **Una clave desconocida en el config de opencode impide arrancar el cliente entero**
  (`ConfigInvalidError`, medido en R6). Es un modo de fallo más duro que el de Claude Code o
  Codex: una escritura mal formada no deja una entrada rota, deja al usuario sin cliente. Todo lo
  que se escriba tiene que ser exactamente una clave dentro de `mcp`.
- **El fichero puede llevar comentarios.** opencode parsea JSONC aunque el fichero se llame
  `.json` (R6-A), y un `json.dumps` de ida y vuelta **borraría los comentarios del usuario**. Esa
  es la razón de que el camino por defecto sea la CLI del propio cliente.
- **No existe `opencode mcp remove`** (R4): el `uninstall` no puede delegar en el cliente y tiene
  que editar el fichero nosotros.
- `~/.config/opencode` sale de `HOME` y opencode lo respeta (R2), así que `--home` sigue siendo un
  sandbox de verdad — al contrario de lo que pasa con `claude mcp add-json --scope user`.
- El `probe` **nunca escribe**: hay un test que compara el árbol del HOME byte a byte.
- **Sin caracteres fuera de cp1252** en la salida: una flecha `→` mata el doctor en la consola de
  Windows.
- Las frases de tamaño de `checks.py` («dieciséis») se dicen en cinco sitios y hay un test que las
  ata a `len(CHECKS)`.

## Open questions

Tres, todas de alcance y ninguna bloqueante para la investigación. Están razonadas con su
recomendación en `plan.md` § *Decisiones que pide el usuario*:

1. ¿La skill se instala en `~/.config/opencode/skill/` o se confía en que opencode la lea de
   `~/.claude/skills/`? (Recomendación: instalarla; el atajo depende de una compatibilidad que el
   usuario puede apagar y que no existe en una máquina sin Claude Code.)
2. ¿El bloque de memoria va también en `~/.config/opencode/AGENTS.md` habiendo medido que opencode
   ya lee `~/.claude/CLAUDE.md`? (Recomendación: sí, por lo mismo.)
3. ¿Se acepta que sin la CLI `opencode` y con un config con comentarios la entrada MCP **no se
   escriba** y se avise? (Recomendación: sí; es la misma regla que ya gobierna el Codex ajeno.)
