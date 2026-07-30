# Research — Registro único de comprobaciones y `doctor` que ve el sistema entero

## Current behavior

Tres subcomandos saben cada uno un pedazo del sistema, y ninguno tiene la foto completa.

**`doctor` (`doctor.py:264-330`) solo mira el backend.** Imprime `LLAMASWAP_EXE`,
`LLAMASWAP_CONFIG`, si `BASE_URL/models` responde, y compara las versiones instaladas de
`llama-swap` y `llama-server` contra `RECOMMENDED_VERSIONS` (`doctor.py:29-33`: `b9925` y `v238`);
con `--online` añade issues de GitHub. **No comprueba nada del andamiaje del MCP**: ni skill, ni
hooks, ni memoria, ni entrada MCP, ni el daemon.

**`install` (`install.py:343-428`) configura pero no verifica.** Planifica acciones y las aplica;
no responde a la pregunta «¿está bien ahora mismo?». Al terminar no comprueba que lo que escribió
funcione.

**Nadie mira el daemon.** `daemon.query_daemon()` (`daemon.py:97-110`) ya sabe responder «¿hay un
daemon nuestro en este puerto?» y devuelve `{version, pid, host, port}`, pero solo lo usa el propio
daemon para no duplicarse.

## El andamiaje completo, enumerado

De `install.plan_install` y de `doctor.run_doctor`, más lo que no cubre nadie:

| # | Elemento | Dónde vive | Quién lo sabe hoy |
|---|---|---|---|
| 1 | Hooks copiados | `~/.claude/hooks/local-delegate/` (`HOOKS_SUBDIR`) | `install` (escribe) |
| 2 | Hooks registrados | `~/.claude/settings.json`: `UserPromptSubmit` y `PreToolUse/Bash` (`_HOOK_EVENTS`); el de `Read` apagado por diseño (`_READ_HOOK`) | `install` |
| 3 | Skill | `~/.claude/skills/delegacion-local/` (`SKILL_NAME`) | `install` |
| 4 | Memoria | bloque entre `<!-- local-delegate:begin -->` y `:end` en `~/.claude/CLAUDE.md` y `~/.codex/AGENTS.md` | `install` |
| 5 | MCP en Claude | CLI `claude mcp` o `~/.claude.json` | `install` |
| 6 | MCP en Codex | bloque `# local-delegate:begin` en `~/.codex/config.toml` | `install` |
| 7 | Daemon | `http://127.0.0.1:9393/api/daemon` | **nadie** |
| 8 | Backend responde | `BASE_URL/models` | `doctor` |
| 9 | `llama-swap` | versión instalada vs `v238` | `doctor` |
| 10 | `llama-server` | versión desde el `config.yaml` vs `b9925` | `doctor` |
| 11 | Clientes presentes | ¿hay `~/.claude`? ¿hay `~/.codex`? | **nadie** (hoy se pasa a mano con `--targets`) |

Soportados hoy: **Claude Code y Codex**. Los elementos 1-3 son solo de Claude; 4-6 aplican a los dos.

## Impact map

| Área | Responsabilidad actual | Impacto esperado | Evidencia |
|---|---|---|---|
| **nuevo** `src/local_delegate/checks.py` | — | registro único: cada check con `probe()` sin efectos y `fix()` opcional | — |
| `src/local_delegate/doctor.py` (≈330) | diagnóstico solo del backend | pasa a **consumir** el registro y ver los 11 elementos | `doctor.py:264` |
| `src/local_delegate/install.py` (591) | `plan_install` escribe el andamiaje | **no cambia en este change**; sus acciones serán los `fix` de los checks en el change C | `install.py:343` |
| `src/local_delegate/daemon.py` | `query_daemon` | se reusa como `probe` del check 7 | `daemon.py:97` |
| `tests/test_doctor.py` | cubre el doctor actual | se amplía; lo existente no debe romperse | — |
| `docs/wiki/` | — | documentar qué comprueba cada check y qué significa cada estado | — |

## Existing conventions

- **`plan_* / apply(dry_run)`** (`install.py:343,575`): planificar sin tocar disco. El registro de
  checks debe seguir la misma disciplina: `probe()` **no escribe nunca**.
- **Estilo de salida del doctor**: prefijos `[ ok ]`, `[warn]`, `[ -- ]` y exit code 0/1
  (`doctor.py:210-251,297`). Hay que conservarlo: es lo que ya lee el usuario.
- **`--home` para HOME simulado**, que hace testeable todo sin tocar el HOME real.
- **Nada de red obligatoria**: hoy `--online` es opt-in y el doctor funciona sin internet. Un check
  que exija red rompería esa propiedad.
- Tests de módulos con `tmp_path` y dobles; **ningún test lanza procesos reales**.

## Dependencies and integrations

- Sin dependencias nuevas: `httpx2` (ya, para `/models` y `/api/daemon`), `platformdirs` (vía
  `config`), `subprocess` para versiones de ejecutables.
- `RECOMMENDED_VERSIONS` es una constante del repo que envejece; el check debe distinguir
  «distinta de la probada» (aviso) de «no detectada» (informativo), como ya hace `_compare_line`.

## Risks and unknowns

**Confirmado por ejecución:**

- `/api/daemon` responde con `version`, `pid`, `host`, `port` (0.13.1, pid 27032).
- `doctor.run_doctor` no toca ningún fichero del andamiaje: solo lee entorno y ejecutables.

**Sin validar:**

- **El riesgo principal es de diseño, no técnico: que el registro se vuelva un framework.** Once
  checks no justifican una arquitectura de plugins. La forma debe ser una lista de objetos simples
  con dos funciones; si hace falta un registro dinámico, es señal de que se fue de las manos.
- **Falsos negativos por permisos**: comprobar `~/.claude/settings.json` en una máquina donde el
  fichero no es legible debe reportarse como «no se pudo comprobar», no como «falta» — un `fix`
  posterior sobre esa base sobrescribiría configuración ajena.
- **El check de hooks tiene que distinguir «los nuestros» de «los del usuario»**: `install.py:171`
  ya tiene `_is_ours(hook, hooks_dir)` para eso, y el check debe reusarlo en vez de inventar otro
  criterio.
- **Coste de arranque**: `doctor` ya tarda por consultar versiones con `subprocess`; añadir 7 checks
  no debe convertirlo en algo lento. Los que hablan por red van con timeout corto (el de
  `query_daemon` es 1 s, el de `/models` 2 s).
