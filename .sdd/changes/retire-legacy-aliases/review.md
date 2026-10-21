# Revisión de conformidad: Retirada de los alias de nombres viejos en la 0.38.0

Revisión desde cero contra `main` en `7603bb0` (L1–L10 mezclados, PR #370–#377 y #379), contra el
código y los tests reales, `verification.md` y `evidence/`. Fecha: 2026-10-21.

## Veredicto

**`does-not-conform`**, por **un único bloqueante de release** y de arreglo trivial (hallazgo 1):
cuando la PR de release corra `bump_version 0.38.0`, el test
`test_registry_holds_exactly_the_seven_retired_names` se pone en rojo. Los 27 requisitos, en lo que
cada uno pide, se cumplen. Con el hallazgo 1 arreglado (una línea del test), el veredicto pasa a
`conforms-with-notes`.

Recuento: **cumple 22**, **cumple con nota 5** (REQ-001, REQ-012, REQ-021, REQ-023, REQ-025),
**no cumple 0**. El bloqueante no rompe ningún REQ al pie de la letra, pero sí el objetivo del
contexto de la spec («deja la release preparada») y la pregunta de la revisión (que el bump no deje
nada roto).

## Cómo se comprobó

- Lectura de cada pieza con `fichero:línea` (abajo).
- Los dos `git grep` de código muerto de REQ-024: **0 y 0**. `git grep -w` de los 7 nombres viejos,
  de `_FAST` y de `legacy_write` en `src/` y `scripts/` (fuera de `scripts/data/`): solo quedan
  `deprecations.py` (el registro), `scripts/build_corpus.py:453` (dato congelado, previsto en
  REQ-021) y el docstring de `src/local_delegate/transcripts.py:1` (hallazgo 3). En `README.md` y
  `docs/` el patrón de REQ-023 (`0\.37\.x|hasta la 0\.37|siguen funcionando con aviso|_FAST`) da 0.
- **Bump simulado a 0.38.0** en un worktree temporal (`D:/Projects/ld-wt-review`, ya borrado):
  `scripts/bump_version.py 0.38.0` + `## [Unreleased]` vacío encima de `## [0.38.0] - <fecha>`
  (el formato real de las releases, `docs/wiki/Publishing.md:40` y `git show 465fc97:CHANGELOG.md`),
  y la suite completa con `pesado.sh … pytest -n 2`: `4199 passed, 3 failed`. Fallos:
  `test_registry_holds_exactly_the_seven_retired_names` (real, hallazgo 1),
  `test_capture.py::test_the_screenshot_shows_the_current_project_version` (artefacto de la
  simulación: los metadatos instalados siguen en 0.37.0; la release hace `uv lock`/`uv sync`) y
  `test_the_0_38_0_changelog_still_announces_every_entry` (solo con la primera simulación, sin
  `[Unreleased]` vacío; con el formato real pasa). `overdue("0.38.0") == []` en el registro sellado:
  **nada queda vencido**.
- **Mutantes de L10** en otro worktree temporal (`D:/Projects/ld-wt-mut`, ya borrado), sobre
  `tests/test_config_json_safety.py`: `_read_config_json` devolviendo `{}` → 8 fallos; leer con
  `utf-8` en vez de `utf-8-sig` → 4 fallos; `_write_json` sin BOM → 4 fallos. Los tests distinguen.
- `gh pr checks 379`: todo en verde. CodeQL en `main`: **0** alertas abiertas.
- `pyproject.toml:3` = `version = "0.37.0"`.

## Comparación con la especificación

| Requisito | Estado | Evidencia |
| --- | --- | --- |
| REQ-001 Registro | Cumple con nota | `src/local_delegate/deprecations.py:56-116`: 7 entradas en el orden de la tabla, `kind="retired"`, `introduced="UNRELEASED"`, `warn_until="0.40.0"`, multilínea; sin `_FAST` ni `legacy_write`. Test `tests/test_deprecations.py:155`. **Nota**: el test exige `UNRELEASED` y por eso se rompe con el bump (hallazgo 1). |
| REQ-002 Regla de clases | Cumple | `deprecations.py:35-49,162-192`; `legacy_write` fuera de `KINDS`; `effective_kind`. Test `tests/test_deprecations.py:77` con registro real, uno de cada clase y un inválido por regla (incluidos los tres que pide la spec). Test de imports en `:493`. |
| REQ-003 Lectores por clase efectiva | Cumple | `deprecations.py:195-207` (`env_vars`, `switch_files`, `cli_entries`); `_looks_env` desaparecido. Test `tests/test_deprecations.py:123` con registro sintético. |
| REQ-004 Texto del aviso | Cumple | `src/local_delegate/deprecation_notices.py:15-39`; claves `cli.deprecations.retired_renamed(_unreleased)` en `resources/i18n/{es,en}/cli.json:67-68` con el texto exacto. Tests `tests/test_deprecations.py:232,244,252`. |
| REQ-005 Rol `fast` fuera | Cumple | Sin `FAST` en `config.py`, `chains.py`, `checks.py`. Tests `tests/test_fast_role_retired.py:150,157,185,206` (control positivo con `reload_config`, `Context(home=tmp_path)`, telemetría vacía: `_FAST` → `OK`, gemelo → `WARN`). |
| REQ-006 Doble escritura fuera | Cumple | `src/local_delegate/cooldown.py:12-15,40,53`; sin `_write_legacy` ni `legacy_write`. Tests `tests/test_cooldown.py:381` y `:399` (el fichero viejo, bytes intactos). |
| REQ-007 Lectura dual se queda | Cumple | `cooldown.py:122,248-252`, `legacy_names.py:521`, `resources/hooks/hook_common.py:175,517-518,560`. Tests de lectura dual siguen (`tests/test_cooldown.py:420…`, `tests/test_hook_legacy_names.py:87-131`). |
| REQ-008 CLI: error antes de argparse | Cumple | `src/local_delegate/cli.py:1777-1811` (solo retirados de `cli_entries()`, comando = primer token sin `-`, opción antes de `--`, sola o `=`), `entrypoint.py:62-64`. Tests `tests/test_retired_cli_names.py:97-254`: espía sobre `recompute.run`, `--claude-dir` temporal, gemelos a 0, alias vivo no rechazado, `noexiste` con argparse, ambos ejecutables y registro real. `tests/test_cli_renamed_names.py` ya no existe. |
| REQ-009 Variables del paquete | Cumple | `src/local_delegate/config.py:214,219,248-249,262,500`; `config` importa solo `deprecations` (`:24`). Tests `tests/test_retired_env_names.py:70-103` en subproceso (viejo sin efecto, gemelo sí, viejo no pisa al nuevo). |
| REQ-010 Hooks | Cumple | `resources/hooks/hook_common.py:280-305` (solo `LD_HOOK_READ_BLOCK`, `LD_HOOK_READ_SWITCH_FILE`, constante `SWITCH_FILE_NAME`); sin `deprecated_names` en los hooks. Tests con hook **instalado** `tests/test_hook_legacy_names.py:211,221,236`; cola de 7 días `:274`. |
| REQ-011 Control positivo | Cumple | Las 9 filas tienen test con viejo y gemelo: filas 1–3 `test_hook_legacy_names.py:211-249`, 4–5 `test_retired_env_names.py:70-79`, 6–7 `test_retired_cli_names.py:97,130,235`, 8 `test_cooldown.py:381`, 9 `test_fast_role_retired.py:157`. |
| REQ-012 `doctor` | Cumple con nota | `src/local_delegate/checks.py:1845-1991`: cuatro sitios, pista `rename`/`remove`, registro de migración por nombre (`:1893-1898,1960-1963`), `settings_unreadable` (`:1946-1949`). Tests `tests/test_checks.py:2018-2180` (telemetría antes/después/otro nombre/dos migraciones, registro real). **Nota**: `checks.read_text` (`:483`) lee con `errors="replace"`, así que un `settings.json` que no es UTF-8 pero parsea como JSON no da el aviso de «ilegible» que nombra la spec (hallazgo 4). |
| REQ-013 `local_status` | Cumple | `src/local_delegate/server.py:5958-…`; cabecera en `resources/i18n/{es,en}/mcp.json:113`. Tests `tests/test_retired_env_names.py:118-147` (`reload_config`, sin el valor). |
| REQ-014 `update`: migrar → checks → notas | Cumple | `src/local_delegate/update.py:893-899` (antes de `checks.run_all` en `:907`), `:355-386` (`without_migrated_renames` respeta la shell), fallos sumados (`:898,954-956`). Tests `tests/test_update.py:967-1130`. |
| REQ-015 Qué migra | Cumple | `src/local_delegate/install.py:1752-2000` (`kind="migrate"`, relectura al aplicar, posición de la clave, copia exclusiva con fecha UTC y desempate, `copymode`, BOM y CRLF, registro por nombre con fusión, `data_dir_for` `:1659-1672`). Tests `tests/test_install.py:899-1159`, con registro real en `:1056`. |
| REQ-016 Cuándo corre | Cumple | `install.py:2172-2174` (antes de la acción `settings`), `update.py:329` (`migrate_retired_names=False` en las reparaciones). Tests `test_update.py:1067,1082,1098`, `test_install.py:1125,1174,1200`. |
| REQ-017 Límites y datos sensibles | Cumple | Solo nombres en descripción y `literal` (`install.py` `_names`). Tests `test_install.py:1135,1146,1174`, `test_update.py:1067`. |
| REQ-018 Textos | Cumple | Claves `install.migrate.*` e `install.update.migration` en `install.json` es/en; `doctor.probe.deprecated_names.settings_unreadable` en `doctor.json`. Test en inglés `test_update.py:1112`; guardianes verdes en la suite. |
| REQ-019 Horizonte 0.38.0 | Cumple | `tests/test_deprecations.py:172,469,484` (carga con `importlib` + `sys.modules`, control `overdue("0.41.0")`). Mutante `warn_until="0.37.0"` anotado en `evidence/L6/mutant-warn-until.txt`. Guardián `:167` intacto. Bump simulado: nada vencido. |
| REQ-020 `bump_version` robusto | Cumple | Tests `tests/test_deprecations.py:411,424` con los cuatro formatos. |
| REQ-021 Detector de nombres | Cumple con nota | `scripts/data/name_exceptions.json` con el motivo nuevo; README de excepciones `:19,22`; `scripts/_claude_bench.py` sin el nombre viejo; antes/después en `evidence/L6/detector-*.txt`. **Nota**: el docstring de `src/local_delegate/transcripts.py:1` sigue diciendo `local-delegate recalcular-coste` (hallazgo 3). |
| REQ-022 Autocompletado | Cumple | `src/local_delegate/completion.py:128` oculta `cli_entries()`. Tests `tests/test_completion_model.py:49,152`, `tests/test_completion_render.py:258`. |
| REQ-023 Documentación | Cumple con nota | `CHANGELOG.md` `[Unreleased]`: entradilla «Versión incompatible», tabla de 9 filas, «Qué notas…», «Cómo actualizar», lo que no mira nadie, la copia con el `env`, `local_status`. `README.md:121-125`, `docs/wiki/Configuration.md:591-616`, `docs/wiki/Integration-install.md:453`, `docs/recipes/claude-code-hooks.md:62-64`. Tests `tests/test_deprecations.py:288`, `tests/test_wiki.py:250`. **Nota**: el docstring de `deprecations.py:5-7` aún dice que los hooks llevan una copia atada por un test de igualdad, que REQ-010 borró (hallazgo 2). |
| REQ-024 Calidad | Cumple | `git grep` 0 y 0; versión 0.37.0; CodeQL 0 en `main`; checks de #379 en verde; suite verde (4187 en L9; 4199 en la simulación salvo el hallazgo 1). |
| REQ-025 Verificación en vivo | Cumple con nota | `verification.md` pasos 0–9 con hashes y `evidence/live/`. **Nota**: se hizo en `5f3a227`, antes de L10, y su «defecto 1» sigue escrito como abierto aunque #379 lo arregló; no hay pasada en vivo con el código de L10 (hallazgo 5). |
| REQ-026 BOM se lee y se conserva | Cumple | `install.py:272-337` (`_decode_config_json` con `utf-8-sig`, `_write_json` con BOM y fin de línea), `checks.py:490-505`. Tests `tests/test_config_json_safety.py:73-264`; los mutantes de lectura y escritura sin BOM los ponen en rojo. |
| REQ-027 Ilegible no se sobrescribe | Cumple | `install.py:263-320` (`UnreadableConfigError`), usada en hooks `:2194`, MCP `:2409,2731`, desinstalación `:2588`. Tests `tests/test_config_json_safety.py:137-276`; el mutante «devolver `{}`» da 8 fallos. |

## Hallazgos

1. **BLOQUEANTE (release)**: el bump a 0.38.0 pone en rojo
   `tests/test_deprecations.py::test_registry_holds_exactly_the_seven_retired_names`. La línea
   `tests/test_deprecations.py:162` exige `e.introduced == deprecations.UNRELEASED`, y
   `bump_version` la sella a `"0.38.0"` (`assert '0.38.0' == 'UNRELEASED'`, reproducido en la
   simulación). La PR de release no podrá mezclarse con el CI en verde sin tocar el test. Arreglo:
   aceptar `UNRELEASED` o la versión del paquete (p. ej.
   `e.introduced in {deprecations.UNRELEASED, "0.38.0"}`), o comparar con `_package_version()`
   cuando no sea `UNRELEASED`, y probarlo con el bump simulado. No pierde datos.
2. **Menor**: docstring desfasado en `src/local_delegate/deprecations.py:5-7`: «Los hooks … llevan su
   copia mínima en `hook_common.py`, atada a esta por un test de igualdad». REQ-010 borró esa copia
   y el test.
3. **Menor**: `src/local_delegate/transcripts.py:1` nombra el subcomando retirado
   (`local-delegate recalcular-coste`) en vez de `recompute-cost`. El detector no lo marca, así que
   no rompe nada. Es un resto del renombrado.
4. **Menor**: `checks.read_text` (`src/local_delegate/checks.py:483`) decodifica con
   `errors="replace"`. Un `settings.json` que no es UTF-8 pero es JSON válido no da el aviso de
   «no se pudo leer el env» que REQ-012 nombra para «no es UTF-8». Es un caso raro y el check sigue
   viendo las claves ASCII, así que no se esconde ningún nombre viejo.
5. **Menor (registro)**: `verification.md` es de `5f3a227` (antes de L10). Su «defecto 1» está
   escrito como abierto y para el backlog, pero #379 lo arregló. Cubren L10 los tests de
   `test_config_json_safety.py` (los mutantes discriminan) y el CI de #379, pero no hay una pasada en
   vivo con BOM e inválido sobre el código final.

## Seguimiento necesario

- **Antes de la release (obligatorio)**: arreglar el hallazgo 1 y comprobarlo corriendo
  `scripts/bump_version.py 0.38.0` en un worktree temporal con la suite de `test_deprecations.py`.
- **Antes de cerrar el SDD (recomendado)**: anotar en `verification.md` que el defecto 1 quedó
  arreglado por L10 (#379), y si se quiere, repetir en vivo los casos «BOM» e «Inválido» con
  `7603bb0` (hallazgo 5). Los hallazgos 2–4 caben en el mismo PR que el 1.

## Llamadas `local_*`

0 llamadas útiles. Las tools se cargaron al empezar, pero no se usaron: había que citar líneas
literales de la spec, del código y de los tests, y un resumen no sirve como evidencia. La salida de
la suite se miró con `tail`, porque solo hacía falta la línea de recuento y la lista `FAILED`.

## Limpieza

Los worktrees temporales `D:/Projects/ld-wt-review` y `D:/Projects/ld-wt-mut` están borrados
(`git worktree list` ya no los muestra). No quedan shells, servidores ni esperas vivas. El único
fichero que cambió en el repo es este `review.md`.
