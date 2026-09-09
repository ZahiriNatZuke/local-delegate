# Handoff: opencode como tercer cliente de `install`

## Current state

- SDD status: **`closed`** (2026-09-08). Los cinco gates aprobados. El código lleva en `main` desde
  el PR #123 y salió publicado con la 0.19.0; el cambio se quedó en `verifying` un mes por los tres
  gates finales, no por trabajo pendiente.
- Suite en el cierre: **794 passed, 2 skipped** en Windows, con los 36 tests propios del change en
  verde. La evidencia de agosto (`710 passed`) era de un árbol con 84 tests menos y **no** se
  reutilizó: todo se volvió a medir. Ver la sección «Revalidación para el cierre» de
  `verification.md`.
- Verificado también contra el binario real de **opencode 1.18.29** en Windows (agosto fue 1.18.11
  en Linux): `opencode mcp add` sigue registrando la entrada, conserva comentarios y claves del
  usuario, y `opencode mcp list` dice `connected`.

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
  *(Al cerrar, 2026-09-08: la primera mitad de ese motivo **caducó**. Medido contra los dos
  binarios el mismo día, 1.18.11 rechaza la clave desconocida y **1.18.29 ya no**. La decisión se
  mantiene —ahora por prudencia— y la segunda mitad, la de los marcadores, sigue intacta.)*
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

Ninguno para este change: cerrado el 2026-09-08 con los cinco gates aprobados, el código en `main`
y el CI en verde. Lo que salió de la revalidación y **no** pertenece aquí:

1. **Tres frases de documentación desactualizadas por el cliente, no por nosotros.** `spec.md`
   (REQ-011), el docstring de `install.py` y `docs/wiki/Integration-install.md` dicen que una clave
   de primer nivel desconocida impide arrancar opencode. Era cierto en 1.18.11 y **ya no lo es en
   1.18.29** (medido con los dos binarios el mismo día). El comportamiento del paquete no cambia;
   corregir la justificación es un cambio de documentación aparte.
2. **`update` repone en el transporte de la máquina, no en el que había.** Con el daemon levantado,
   una entrada `stdio` borrada vuelve como `http`. Hace lo mismo con Claude Code, así que es
   comportamiento de `update` y no de este change; queda anotado por si alguna vez sorprende.

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
