# Brief: install consume checks.CHECKS y anade --clients auto|claude,codex

Change **C**, el último del andamiaje A → B → C. A (`checks-andamiaje`, PRs #54 y #55) creó el
registro y lo puso bajo `doctor`; B (`update-reinicia-daemon`, PR #66, publicado en la 0.17.0) lo
puso bajo `update`. Falta el tercer verbo.

## Problem

`install` es el único de los tres verbos que **no mira el sistema**: planifica a ciegas y escribe.
Evidencia en el código de `main` (`7c48328`):

1. **`install.py` no importa `checks`.** El único punto de contacto en todo el camino de
   instalación es `cli._avisa_si_el_cli_no_esta_en_el_path()` (`cli.py:108-123`), que usa la
   *constante* `checks.CLI_HINT` — no ejecuta ni un `probe`. La dependencia real va al revés:
   `checks.py:33` importa `install` para reutilizar `_is_ours`, `_HOOK_EVENTS`, `SKILL_NAME` y
   los marcadores.
2. **El default `--target all` escribe en clientes que no existen.** `cli.py:43` resuelve
   `selected = args.target or ["all"]` → `targets = {"claude", "codex"}`, y `plan_install` crea
   `~/.codex/AGENTS.md` y `~/.codex/config.toml` en una máquina sin Codex (`install.py:401-441`).
   `checks` ya sabe distinguirlo —`_probe_clients` (`checks.py:199-207`) mira qué directorios de
   cliente existen— y `update` ya actúa sobre esa base con `_present_targets`
   (`update.py:167-174`) y el marcador `PRESENT`. `install` no.
3. **`install` puede pisar configuración puesta a mano.** `upsert_codex_mcp`
   (`install.py:311-316`) borra con `_CODEX_SECTION_RE` cualquier `[mcp_servers.local-delegate]`
   previo, tenga marcadores o no. Ese caso exacto es el que `checks._probe_mcp_codex` reporta
   `warn` («entrada puesta a mano, sin marcadores», `checks.py:392`) y por el que `update` se
   niega a reparar en `warn` — la única excepción de su tabla `REPAIRS` (`update.py:160-163`).
4. **`install --home` escribe fuera del HOME simulado.** `_register_claude_mcp`
   (`install.py:451-476`) prefiere `claude mcp add-json --scope user`, que escribe **siempre** en
   el `~/.claude.json` del usuario real e ignora `opts.home`. `update` ya lo corrigió pasando
   `use_cli=not opts.simulated_home` (`update.py:236`) tras descubrirlo por ejecución; `install`
   arrastra el bug. Está apuntado como pendiente propio en el backlog del vault.
5. **`install` termina sin verificar nada.** Imprime «Listo. Reinicia el cliente…»
   (`cli.py:83`) contando acciones aplicadas, no estado alcanzado. Si una acción escribió algo
   que no quedó como debía, nadie lo dice: hay que ejecutar `doctor` aparte.

## Desired outcome

`local-delegate install` decide sobre lo que `checks` ve, no sobre supuestos:

- Sin flags, configura **solo los clientes presentes en la máquina** y lo dice.
- No pisa una entrada MCP de Codex escrita a mano: avisa y la deja, salvo petición explícita.
- Con `--home` simulado escribe **solo** dentro de ese árbol, verificable byte a byte fuera de él.
- Al terminar, informa del estado real de los checks del andamiaje, no del número de acciones.

## In scope

- **`--clients auto|claude|codex`** (repetible, default `auto`) en `install` y `uninstall`, con
  `auto` resuelto por presencia de cliente. `--target` se mantiene aceptado como alias para no
  romper la wiki (`docs/wiki/Integration-install.md:45`), el recipe
  (`docs/recipes/claude-code-integration.md:10`) ni el README (`README.md:231`).
- **`install` consume `checks.run_all`**: antes de planificar, para resolver `auto` y detectar el
  caso «puesto a mano»; después de aplicar, para reportar el estado alcanzado.
- **Respeto de la configuración ajena**: `scaffold.mcp_codex` en `warn` no se sobrescribe sin un
  flag explícito.
- **El bug de `--home`**: `use_cli` desactivado cuando el HOME es simulado, igual que en `update`.
- Actualizar `README.md`, `docs/wiki/Integration-install.md`,
  `docs/recipes/claude-code-integration.md` y `CHANGELOG.md` (`Unreleased`).

## Out of scope

- Publicar a PyPI. El change entra en `Unreleased`.
- Tocar `doctor` o `update`: su consumo de `checks` ya está hecho y verificado.
- Añadir, quitar o cambiar la semántica de un `probe`. El registro son doce checks y sigue siendo
  una tupla estática, no un framework.
- El resto del backlog: `doctor` vs PyPI, el JSON cacheado de `update`, `uv tool upgrade`, hooks
  duplicados del `.sh` retirado, el `rev` de ruff en pre-commit, la captura del README y el
  amarillo de la landing. Cada uno es su propio change.
- Fase 3 del SDK `mcp` 2.x (`middleware`, elicitation, `auth`).

## Constraints and risks

- **El contrato que dejó A no se toca:** `probe` nunca escribe (hay un test que compara el árbol
  del HOME simulado byte a byte) y lo que no se pudo comprobar es `unknown`, jamás `missing`.
  `install` es un verbo que escribe, así que es precisamente el consumidor donde un `missing`
  falso causaría el daño: sobrescribir configuración ajena.
- **Riesgo de invertir la relación de módulos.** Hoy `checks` importa `install`; si `install`
  importara `checks` a nivel superior habría un ciclo. El módulo ya resuelve esto con imports
  diferidos (`checks.py:80-104`) y hay precedente en `cli.py:116`.
- **Cambio de comportamiento observable:** el default deja de escribir en clientes ausentes. Es el
  objetivo del change, pero va al `CHANGELOG` como cambio de comportamiento, no como fix mudo.
- **`install` es declarativo, `update` es reparador.** El riesgo de diseño es convertir `install`
  en un segundo `update` que solo escribe lo que falta: dejaría de servir para «reinstalar y que
  todo quede como lo pone la versión actual», que es lo que hoy arregla una instalación vieja.
  `checks` decide **a quién** se escribe y **qué no se pisa**; no decide **si** se escribe.
- **No publicar sin probar `install` end-to-end en Windows.** El incidente del 2026-07-30 (PRs #55
  y #57) bloqueó Claude Code por un string de hook mal formado; el comando generado hay que verlo
  correr en `sh`, `cmd` y PowerShell antes de tocar el HOME real.
- Un comentario del repo no es evidencia: verificar por ejecución, y verificar los tests al revés
  (un test que no falla con el bug puesto no prueba nada).

## Open questions

- Ninguna bloqueante. Dos decisiones tomadas con su porqué, a confirmar en la spec:
  1. `--target` se conserva como alias en vez de eliminarse — está en tres documentos publicados y
     romperlo no compra nada.
  2. El flag de escape para el caso «puesto a mano» se resuelve en la especificación: o un
     `--force` acotado a ese caso, o ninguno (avisar y no tocar). Se decide con la evidencia de
     la investigación, no aquí.
