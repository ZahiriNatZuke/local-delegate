# Verification: install consume checks.CHECKS y anade --clients auto|claude,codex

## Environment

- **Revision:** rama `feat/install-checks-clients`, sobre `main` en `7c48328`.
- **Runtime:** Windows 11 Enterprise LTSC 2024, Python 3.11 (uv), CLI local-delegate 0.17.0,
  `node` para `--check`. Shells ejercitados: PowerShell 7, `cmd`, `sh` (Git Bash).

Todo lo de abajo se ejecutó de verdad; nada se da por bueno por lectura del código.

## Los cuatro pasos del CI

| Paso | Resultado |
|---|---|
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `53 files already formatted` |
| `uv run pytest -q --basetemp=<scratchpad>` | **415 passed, 1 skipped** (386 antes del change) |
| `extract_dashboard_js.py` + `node --check` | `39395 chars`, exit **0** |

29 pruebas nuevas: 27 en `tests/test_install_clients.py` y 2 en `tests/test_checks.py`.

## Verificación **al revés** — lo único que prueba que las pruebas prueban algo

La suite existente pasaba con el bug del HOME dentro, porque sus 20 pruebas fijaban
`use_cli=False`. Así que cada arreglo se revirtió y se comprobó que la prueba falla.

### El HOME simulado (REQ-006, REQ-007)

Restaurada la línea antigua `use_cli=not getattr(args, "no_client_cli", False)`:

```
FAILED tests/test_install_clients.py::test_home_simulado_no_invoca_el_binario_claude
FAILED tests/test_install_clients.py::test_uninstall_con_home_simulado_tampoco_toca_el_real
2 failed, 25 passed
```

Con el arreglo puesto: 27 passed.

### La entrada de Codex puesta a mano (REQ-008..011)

Quitado el `and not opts.skip_codex_mcp` de `plan_install`:

```
FAILED tests/test_install_clients.py::test_sin_terminal_no_pregunta_y_conserva_la_entrada
FAILED tests/test_install_clients.py::test_respondiendo_que_no_se_conserva_la_entrada
FAILED tests/test_install_clients.py::test_skip_codex_mcp_suprime_esa_accion_y_solo_esa
3 failed, 24 passed
```

Los de `--force` y «responder que sí» **no** fallan, y es correcto: en esos dos caminos el
comportamiento esperado *es* reemplazar, que es justo lo que hace el código con el bug.

## End-to-end en los tres shells, contra HOME simulado

### PowerShell — el caso por defecto

`local-delegate install --home <tmp>` sobre un HOME con solo `.claude`:

```
clientes: deteccion automatica (--clients auto): claude
...
Estado del andamiaje después de escribir:
  [ OK ] CLI local-delegate: ...\.venv\Scripts\local-delegate.EXE (versión 0.17.0)
  [ OK ] clientes: detectados: Claude Code
  [ OK ] hooks copiados: 5 script(s) en ...\home-ps\.claude\hooks\local-delegate
  [ OK ] hooks registrados: 2 registrado(s): UserPromptSubmit, PreToolUse/Bash
  [ OK ] skill delegacion-local: instalada en ...
  [ OK ] memoria global: Claude: bloque presente ... · Codex: cliente no instalado
  [ OK ] MCP en Claude Code: registrado en ...\home-ps\.claude.json (stdio uvx)
  [ -- ] MCP en Codex: Codex no está instalado (...\home-ps\.codex no existe)
```

- **No se creó `~/.codex`**: `Test-Path ...\home-ps\.codex` → `False`. Ese era el defecto.
- El reporte final aparece sin pedirlo y **no** cambió el exit code pese al `[ -- ]`.

### El `~/.claude.json` real, byte a byte

SHA-256 del `C:\Users\Yohan\.claude.json` verdadero:

| Momento | Hash |
|---|---|
| antes | `F5D6C478…4AAF4` |
| tras `install --home <tmp>` | `F5D6C478…4AAF4` |
| tras `uninstall --home <tmp>` | `F5D6C478…4AAF4` |

Idéntico en los tres. Con el bug, `uninstall` **desregistraba el MCP de verdad**.

### sh (Git Bash) — Codex a mano, sin poder responder

Con `[mcp_servers.local-delegate]` escrita a mano y stdin sin datos:

```
clientes: deteccion automatica (--clients auto): claude, codex
Aviso: entrada stdio en ...\home-sh\.codex\config.toml, pero puesta a mano (sin marcadores)
       Se conserva la entrada del usuario; el resto sí se instala.
  [WARN] MCP en Codex: entrada stdio en ..., pero puesta a mano (sin marcadores)
```

`config.toml` después: **intacto**, con `command = "lo-puse-yo"`. El resto del plan sí se aplicó.

### cmd — `--force-mcp-codex`

```
Aviso: entrada stdio en ...\home-cmd\.codex\config.toml, pero puesta a mano (sin marcadores)
       --force-mcp-codex: se reemplaza (queda una copia .bak al lado).
  [ OK ] MCP en Codex: bloque gestionado en ... (stdio)
```

`config.toml` después:

```toml
[mcp_servers.otro]
command = "ajeno"

# local-delegate:begin
[mcp_servers.local-delegate]
command = "uvx"
args = ["--from", "local-delegate-mcp", "local-delegate-mcp"]
# local-delegate:end
```

La entrada **ajena** (`[mcp_servers.otro]`) sobrevivió al reemplazo.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `--clients` en los dos verbos | ✅ | `test_uninstall_auto_limpia_solo_los_clientes_presentes` |
| REQ-002 | presencia por directorio, definición única | ✅ | `test_present_targets_mira_los_directorios` (3 casos), `test_update_y_install_comparten_la_misma_definicion` |
| REQ-003 | la resolución se imprime | ✅ | línea `clientes: deteccion automatica…` en las tres ejecuciones reales |
| REQ-004 | `--target` vivo; combinarlo, error | ✅ | `test_target_all_conserva_el_comportamiento_historico`, `test_clients_y_target_juntos_es_error_de_uso` (exit 2, nada escrito) |
| REQ-005 | sin clientes: nada escrito, exit 0 | ✅ | `test_auto_sin_ningun_cliente_no_escribe_nada_y_sale_bien` (`snapshot(home) == {}`) |
| REQ-006 | cero invocaciones del binario | ✅ | espía; **verificado al revés** |
| REQ-007 | HOME real intacto | ✅ | hashes SHA-256 arriba + `snapshot()` en dos pruebas |
| REQ-008 | pregunta antes de reemplazar | ✅ | `test_respondiendo_que_no_…`, `test_respondiendo_que_si_…` (ver *Deviations*) |
| REQ-009 | sin tty no pregunta y conserva | ✅ | `test_sin_terminal_no_pregunta_…` + ejecución real en sh |
| REQ-010 | `--force-mcp-codex` | ✅ | `test_force_reemplaza_sin_preguntar_ni_terminal` + ejecución real en cmd |
| REQ-011 | `--dry-run` no pregunta | ✅ | `test_dry_run_no_pregunta_y_lo_anuncia` |
| REQ-012 | reporte siempre | ✅ | `test_install_termina_diciendo_el_estado_real` + las tres ejecuciones |
| REQ-013 | sin red ni binarios | ✅ | `test_filtrar_por_grupo_no_toca_la_red_ni_el_backend` (colaboradores que revientan si se llaman) |
| REQ-014 | no altera el exit code | ✅ | `test_el_reporte_no_altera_el_exit_code` |
| REQ-015 | rótulo en `--dry-run` | ✅ | `test_dry_run_rotula_el_reporte_como_estado_actual` |
| REQ-016 | garantías vigentes | ✅ | las 20 pruebas previas de `test_install.py`, verdes sin tocar sus aserciones |
| REQ-017 | documentación | ✅ | README, wiki, recipe y CHANGELOG (`Unreleased`; CRLF conservado: 876 CRLF / 0 LF sueltos) |
| REQ-018 | dos textos falsos corregidos | ✅ | docstring de `test_install.py` reescrito; la wiki dice «doce piezas» |

## Quality checks

- [x] Project-native tests pass — 415 passed, 1 skipped.
- [x] Lint, formatting, y el `node --check` del JS del dashboard pasan.
- [x] Secret scanning — `git diff` sobre `pyproject.toml` y `uv.lock` **vacío** (ninguna
      dependencia nueva); búsqueda de `api_key|token|secret|password|Bearer|sk-` en el diff da un
      solo acierto: la palabra «tokens» dentro de un comentario en español.
- [x] No unrelated changes — `git status` limpio salvo los ficheros del change y su traza SDD.
- [x] Salida compatible con la consola de Windows: `test_la_salida_nueva_cabe_en_la_consola_de_windows`
      codifica stdout+stderr a **cp1252** y falla si algo no cabe (la lección de la flecha `→`).

## Deviations and residual risk

**La respuesta afirmativa por teclado no se probó con una terminal de verdad**, porque el agente
no dispone de tty. Se cubre con `builtins.input` doblado en dos pruebas, y los tres caminos que
**sí** se ejecutaron de verdad —EOF en sh, `--force` en cmd, `--dry-run`— son los que escriben o
conservan sin intervención. El camino no ejecutado es el menos peligroso de todos: pide
confirmación explícita y su valor por defecto es no tocar nada.

Riesgo residual del change, y es el declarado desde el principio: el **cambio de default** puede
sorprender a quien esperara que `install` configurara los dos clientes. Mitigado por la línea que
imprime siempre la resolución, por `--target all` como vía de escape intacta, y por la entrada de
`CHANGELOG` bajo *Changed*.
