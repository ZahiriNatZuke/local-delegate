# Verification: Atribución de cada delegación de Codex a su sesión (#669, segunda parte)

## Environment

- Revision: rama `feat/codex-session-attribution` sobre `main` (`05529e3c`), cambios sin commit al verificar
- Relevant runtime and tool versions: Windows 11, Python 3.11 (`.venv` del checkout principal con `PYTHONPATH=src`), pytest con xdist `-n 1` bajo `pesado.sh`, `jsonschema` 4.26.0; fuente de Codex `rust-v0.169.0` (`d32063f9`)

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_the_mcp_hook_is_the_last_entry_and_the_first_two_do_not_change`, `test_merge_puts_the_new_hook_behind_a_users_pre_tool_use_group` y los tests del núcleo pasados a `SPECS` | pass | tercera entrada al final con su matcher; `check_hooks_file` sin hallazgos; clave `:pre_tool_use:1:0`; un `PreToolUse/Bash` del usuario se queda en el índice 0. Mutante «matcher sin `^`» lo mata el primero |
| REQ-002 | `test_our_matcher_*`, `test_the_matcher_controls_discriminate`, `test_the_matcher_follows_the_rules_of_codex` | pass | casa `mcp__local_delegate__…` y `mcp__local-delegate__…`; no casa Bash, `apply_patch`/`Write`/`Edit`, MCP ajeno, `local_delegatex`, `xmcp…`; controles: sin `^` casa `xmcp…` y el literal en modo exacto no casa nada |
| REQ-003 | seis fixtures validados con el esquema oficial de entrada; el hook lanzado con `-I` como lo lanza Codex | pass | nota `codex-<id>.json` con exactamente siete campos, sin `session_id`, `cwd` ni `tool_input`; nada para Bash, `apply_patch` ni MCP ajeno; ids `None`, vacío, `../escape`, `a/b`, 129 caracteres y con `\n` sin nota (control: 128 pasa); stdin roto sale con 0; anota con `LD_HOOK_ENABLED=0`. Mutantes «sin comprobar la tool» y «la nota guarda `cwd`» muertos |
| REQ-004 | servidor MCP en memoria con el middleware real y `clientInfo` `codex-mcp-client` o `claude-code` | pass | Codex da `callId` y la clave de `sessionId`; Claude Code con el mismo `_meta` da solo `toolu_z`; `callId` inválido o `_meta` vacío dan `None`. Mutantes «`callId` de cualquiera» y «sesión de cualquiera» muertos |
| REQ-005 | `_log_event` dentro de una petición real con log temporal (`LOCAL_DELEGATE_LOG` y `_current_log_path` en `tmp_path`) | pass | subagente: `caller_kind`, `caller_agent_type`, `caller_model`, `caller_src: codex-hook`, `caller_session_key`, sin esfuerzo ni proyecto ni id en claro; code mode `exec-…` en el hilo principal; sin hook solo la clave; sin `callId` también la clave (mutante «solo con id» muerto); nota caducada o de Claude no cuenta (mutante «sin TTL» muerto); `/api/inflight?session=` marca la de Codex; Claude Code sin id sigue sin `caller_*` |
| REQ-006 | `match_lines` con un `tool_use` de Claude en la ventana; `merge_row` con entrada; `in_flight_row` | pass | Codex sin entrada y control `claude-code` cruzado `window`; Codex no funde la entrada (control: Claude sí, `backfill`); recibo de Codex igual con y sin nota. Tres mutantes muertos |
| REQ-007 | `cost.segment` y `valuation.cost_block` con una fila de Codex completa | pass | tramo `excluded`, `excluded_by_reason == {"not_claude": 1}` |
| REQ-008 | `caller_column`; `/api/stats` sobre un log de `tmp_path`; fuente de la tarjeta y catálogos | pass | `codex` antes que `mod`; total y cada `by_client` suman `calls` con las cinco columnas; mutante «sin `codex_calls`» muerto. Capturas claro/oscuro: pendientes, las lanza la sesión principal con la máquina tranquila (`scripts/dev/capture_dashboard.py` ya trae `codex_calls`) |
| REQ-009 | `/api/stats?session=` con dos sesiones | pass | la de Codex da sus 2 filas, todas `codex_calls`; otra sesión da 0 |
| REQ-010 | `test_measure_adoption_counts_codex_in_its_own_column`, `test_delegations_by_caller_counts_the_mod_first` (con una fila de Codex) | pass | `codex: 1` y la suma igual al total; «Codex 4» en es y en |
| REQ-011 | `tests/test_wiki.py`, `test_i18n_parity.py`, `test_detect_spanish_names.py` (léxico ampliado con nueve palabras inglesas del test nuevo) | pass | CHANGELOG, README, `Integration-install.md` (tercer hook, `3 de 3`) y `Savings-and-metrics.md` (sección «Delegaciones de Codex») |
| REQ-012 | pasos en `handoff.md` («Next action») | skip | necesita Codex real y aprobar en `/hooks`: lo hace la persona usuaria; no se simula |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -n 1` de los ficheros del área (atribución, clientes, coste, relleno, valoración, panel, en curso, medidores, Codex, textos, i18n, wiki, doctor, update) | yes | pass | 1234 passed, 3 skipped; 1 fallo del detector de nombres (palabras sin clasificar del test nuevo), arreglado y vuelto a correr: 268 passed, 1 skipped |
| `pytest -n 1` de los ficheros de instalación, plugin y `caller_column` | yes | pass | 648 passed, 2 skipped |
| mutantes (12, script en el scratchpad) contra `test_codex_attribution.py` y `test_measure_adoption_own_repo.py` | yes | pass | 12 de 12 muertos |
| `ruff check src tests scripts` / `ruff format --check src tests scripts` | yes | pass | «All checks passed!»; «420 files already formatted» |
| suite completa | no | skip | orden del coordinador: solo los ficheros afectados y su vecindad (cuatro agentes en la máquina); el CI la corre en el PR conjunto |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.
