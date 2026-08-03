# Handoff: opencode como tercer cliente de `install`

## Current state

- SDD status: `verifying`. Gates `spec` y `plan` aprobados; `quality`, `conformance` y `memory`
  pendientes de la revisión del usuario, con la evidencia ya recogida en `verification.md`.
- Rama `claude/opencode-mcb-integration-m8q9qq`, base `67e585f`.
- Suite: **700 passed, 4 skipped, 1 failed**. El fallo es anterior y ambiental (la suite corre
  como root y `chmod 000` no le quita permiso de lectura); baseline antes de tocar nada:
  `667 passed, 1 failed`, el mismo.

## What changed

`install`, `doctor` y `update` pasan de conocer dos clientes a conocer **tres**. opencode recibe la
entrada MCP (`type: "local"` o `type: "remote"`), el bloque de memoria en
`~/.config/opencode/AGENTS.md` y la skill en `~/.config/opencode/skill/delegacion-local/`.
`doctor` gana la comprobación **nº17** (`scaffold.mcp_opencode`) y `update` repone la entrada.

Once ficheros: `install.py` (el grueso), `cli.py`, `checks.py`, `update.py`,
`tests/test_install_opencode.py` (nuevo, 33 tests), `tests/conftest.py`, `tests/test_checks.py`,
`tests/test_install_clients.py`, `scripts/check_install_e2e.py`, tres de documentación y el
`CHANGELOG`.

## Decisions

Las cuatro que no se deducen del código, cada una con lo que las decidió:

- **`opencode_dir` es una función, no una ruta.** `XDG_CONFIG_HOME` gana sobre `HOME` (medido con
  `opencode debug paths`). Escrita a mano en los tres módulos que la necesitan, en una máquina con
  esa variable `install` habría escrito un fichero que el cliente nunca lee y `doctor` habría dicho
  que falta la entrada recién puesta. Con HOME simulado se ignora, para no romper el sandbox de
  `--home`.
- **Se escribe con `opencode mcp add`; el camino propio es el de socorro, y a veces no escribe.**
  Su config es JSONC y admite comentarios aunque el fichero se llame `.json`. La CLI los conserva;
  un `json.dumps` de ida y vuelta los borraría **sin que el fichero pareciera roto**. Sin CLI y con
  comentarios —o con un fichero que no parsea— la entrada no se escribe, se avisa y el resto sí se
  instala. Misma regla que ya protege el Codex escrito a mano.
- **La identidad de lo nuestro es la clave `mcp["local-delegate"]`, sin marcadores.** No es
  estilo: una clave de primer nivel desconocida hace que opencode **no arranque**. De ahí también
  que no exista un `--force-mcp-opencode`: sin marcadores no hay forma de distinguir nuestra
  entrada de una escrita a mano, exactamente como en Claude Code.
- **La skill y la memoria se instalan en el sitio propio de opencode**, aunque esté medido que lee
  `~/.claude/skills/` y `~/.claude/CLAUDE.md`. Las dos compatibilidades son apagables
  (`OPENCODE_DISABLE_EXTERNAL_SKILLS`, `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT`) y **no existen** en
  una máquina sin Claude Code, donde el instalador ni siquiera emitiría esas acciones.

Dos cosas que se decidieron **midiendo, no diseñando**:

- **No se escribe `"enabled": true`.** La CLI del cliente tampoco lo escribe, así que ponerlo hacía
  que los dos caminos dejaran formas distintas y que el `--dry-run` prometiera una clave que luego
  no aparecía.
- **El `returncode` de la CLI no basta.** El binario devuelve `0` también para subcomandos que no
  existen (se vio con `opencode mcp remove`, que no existe). Se confirma leyendo el fichero después;
  si no, un `add` renombrado en el futuro daría por hecho un registro que no ocurrió.

## Deliberately out of scope

- **Hooks.** opencode no tiene el mecanismo de Claude Code: extiende con plugins en TypeScript y
  otra superficie de eventos (`tool.execute.before`, `chat.message`, …). Nuestros tres hooks son
  Python hablando el protocolo de stdin de Claude Code. Portarlos es un change con su propio
  piloto A/B, no un apéndice de este.
- **`elicitation`.** opencode declara solo `roots`. `preguntas.puede_preguntar()` ya degrada solo,
  así que no hubo nada que tocar — solo dejar de prometerlo en la documentación.
- **Config de proyecto** (`./opencode.json`, `.opencode/`).

## Next steps

1. Aprobar los gates `quality` y `conformance` con `verification.md` delante.
2. Dejar que el CI corra el e2e en Windows y macOS: es lo único de este change que aquí solo se
   ejercitó en Linux.
3. Al publicar, la línea del `CHANGELOG` ya está redactada en `Unreleased`.

## Cómo repetir las mediciones

Ninguna salió de la documentación —`opencode.ai` está bloqueado por la política de red de este
entorno—, así que conviene dejar escrito el camino:

```bash
npm install opencode-ai@1.18.11
OC=node_modules/opencode-linux-x64/bin/opencode
HOME=<árbol> $OC debug paths     # dónde cree que está su config
HOME=<árbol> $OC debug config    # la config YA RESUELTA (aquí se ve si {env:VAR} expandió)
HOME=<árbol> $OC debug skill     # qué skills carga, y desde dónde
HOME=<árbol> $OC mcp list        # conecta de verdad contra los servidores
```

Para saber qué declara opencode por MCP, un servidor stdio de pega que anote el `initialize` y
`opencode mcp list`: devolvió `clientInfo {"name":"opencode","version":"1.18.11"}`, protocolo
`2025-11-25` y `capabilities {"roots":{}}`.
