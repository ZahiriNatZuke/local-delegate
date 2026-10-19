# Gate `conformance` — `english-names-bilingual-output` (evidencia del 2026-10-18; aprobado el 2026-10-19)

Revisión evaluada: `main` en `b8ede29` (release v0.36.0, PR #330). Evidencia leída en un worktree
limpio (ya borrado). Rutas de evidencia relativas a la carpeta del cambio
(`.sdd/changes/english-names-bilingual-output/`) salvo que empiecen por `src/`, `tests/` o `scripts/`.

## Recomendación

**Aprobar con salvedades.** De los 47 REQ: 41 cumplidos, 6 cumplidos con límite (REQ-011, REQ-016,
REQ-017, REQ-028, REQ-036, REQ-044), 0 no cumplidos. Dentro de esos límites hay tres huecos que hoy
no constan en ningún sitio y conviene anotar (o cerrar) antes de aprobar. Lo que queda
fuera por diseño (la ola R, que retira los alias en la 0.38.0) no se mide aquí, y el plazo lo vigila
el test de horizonte de REQ-004.

Límites que hoy **no** están anotados (ni en `verification.md` ni en el backlog §1.8–1.10):

1. **Palabras sin clasificar del detector (REQ-016/REQ-044).** La corrida del cierre
   (`evidence/close/detector.txt`) da 0 fuera de la lista, pero **111 palabras «sin clasificar»**.
   REQ-044 dice que esas palabras «bloquean el cierre de REQ-016 hasta que se clasifiquen». Hasta B1c
   los registros de ola dicen «0 sin clasificar»; las nuevas vienen de B2d-3 a B5 (como los 23
   hallazgos que el guardián nuevo sí atrapó). Repasadas una a una: son inglesas (`asserts`,
   `checking`, `visitors`…), numerales españoles de `scripts/score_lint_fidelity.py` (`catorce`,
   `diez`…: el mismo motivo que ya tienen `dos` o `veinte` en la lista) o textos del catálogo
   `resources/i18n/es/` (`eliminado`, `listo`…), que la lista ya cubre por fichero. **Ninguna es un
   nombre de máquina en español**: el fondo se cumple, pero la letra no. El guardián
   `test_repo_has_no_spanish_name_outside_the_exception_list` (tests/test_detect_spanish_names.py:213)
   solo exige `outside_exceptions == 0`, no mira las sin clasificar.
   *Salida propuesta:* un lote corto que las meta en `scripts/data/spanish_lexicon.json` y amplíe el
   guardián a `unclassified_words == {}`; o aceptarlo como límite y anotarlo.
2. **Muestra en vivo con `fr` (REQ-028, enmienda del 2026-10-14).** La traza pide «muestra en vivo
   con `fr`». La propuesta de B2 la planificó (waves/B2-proposal.md:457, 4 tools × 10 documentos),
   pero la muestra de B2d quedó bloqueada y la que se repitió en B2d-2 solo usó `es`/`en`. `fr` está
   cubierto en los tests (llega al `system` de las 4 tools y `commit_msg` no cambia:
   tests/test_response_language.py:98, tests/test_commit_language.py:127) y en el prompt real
   (`evidence/B2b-2/prompts-and-status.txt`), no con respuestas del modelo.
3. **Tamaño de la muestra de `local_explain_code` y `local_describe_image` (REQ-028).** La traza pide
   ≥ 5 documentos por tool e idioma. `summarize` y `lint_summary` los tienen (B2d-2: lint 14/15 y
   15/15, summarize 7/7 y 5/5, juez de prosa, `evidence/B2d-2/live.md:48-52`); `explain_code` y
   `describe_image` solo tienen 1 por idioma (pasada de la 0.36.0, 12 de 12,
   `evidence/live-036/answers/*/judge.jsonl`).

Límites ya documentados que tocan REQ: backlog §1.8 (lint troceado de 6+ trozos se corta e inventa
recuentos: REQ-028/REQ-017 en logs enormes), §1.9 (la celda de afinidad de `local_lint_summary`
salió: REQ-017 en la parte de enrutado), §1.10 (lint en español aún inventa alguna cifra: REQ-028;
dónde vive la lista de excepciones del guardián al archivar: REQ-016; RAM con el 35B/26B), y en
`verification.md` («Deviations»: valores de una sola palabra que el detector no ve, REQ-016; `doctor`
no tiene `--json`, REQ-011). Y los registros de ola sin `local_*` por el MCP caído (REQ-036, abajo).

## Olas → PR (orden de mezcla en `main`, `git log --first-parent 8ec2f1d..b8ede29`)

| Tramo | PR |
| --- | --- |
| Frente A, A0–A6 (+ arreglo) | A0 #247, A1 #249, A2 #250, A3 #251, A4 #252, A5a #253, A5b #259, A5c #261, A6 #262, arreglo #263 → release 0.35.0 #264 |
| Frente A, A7–A10 | A7a #265, A7b #268, A8a-1 #269, A8a-2 #270, A8b #271, A9a #272–#278, A9b #279–#284, A9c #285–#289, A10a #291–#294, A10b #295–#298, #300, #301 |
| Cierre del frente A | A-close-1…5 #302–#306, higiene de CodeQL #307, `affinity --check` sin entorno (`a5c150e`, #308) |
| Frente B | B0a #309, B0b #310, B1a–B1e #311–#315, B2a #316, B2b-1 #317, B2b-2 #318, B2c #319, B2d #320, B2d-2 #321, B2d-3 #322, B2d-4 #323, B2e #324, B2-affinity #325, B4 #326, B3 #327, B5 #328, B2f #329 |
| Release | v0.36.0 #330 (`b8ede29`) |

Ajenos al cambio en el tramo: #248, #254–#258 (dependabot), #266, #267 (CI), #290, `5263b49` (tests).

## Tabla REQ → veredicto → evidencia

Veredictos: **C** cumplido · **CL** cumplido con límite (documentado o anotado arriba) · **NC** no
cumplido · **FA** fuera de alcance por diseño.

### Frente A: renombrado

| REQ | Veredicto | Evidencia |
| --- | --- | --- |
| REQ-044 Detector versionado | **CL** | `scripts/detect_spanish_names.py`, `scripts/data/spanish_lexicon.json` (+ README), `reserved_words.json`; tests/test_detect_spanish_names.py (19 tests); ola A0 #247 (`waves/A0.md`). Límite: 111 sin clasificar en la corrida del cierre (punto 1 de arriba) |
| REQ-001 Subcomando y opción con alias | C | src/local_delegate/cli.py:357-358 (`recalcular-coste` → `recompute-cost` con aviso); tests/test_cli_renamed_names.py:59, :70, :92; A1 #249 |
| REQ-002 Variables con alias en paquete y hooks | C | src/local_delegate/deprecations.py:58-67 (registro con `used_by_hooks`); tests/test_hook_legacy_names.py:67; tests/test_environment_isolation.py:127; A1 #249, A2 #250 |
| REQ-003 Aviso de nombres obsoletos por proceso | C | src/local_delegate/checks.py:1837 (`deprecated_names_in_hook_telemetry`), :5508 (`_describe_deprecated_names` en `local_status`); tests/test_hook_legacy_names.py:76; A0–A2; en vivo `evidence/live-035/install-doctor-panel.md` |
| REQ-004 Horizonte de alias comprobado | C | src/local_delegate/deprecations.py:27 (`UNRELEASED`), `removal_version` → 0.38.0; tests/test_deprecations.py:74, :84, :88; `verification.md` fila REQ-004. La retirada en sí (ola R, 0.38.0) es **FA** de este cierre |
| REQ-005 Escritura solo en formato nuevo, con excepción | C | tests/test_cooldown.py:391 (doble escritura `enter`/`reenter`/`clear`), :407, :440; A2–A5 (#250–#261) |
| REQ-006 Lectura dual para siempre | C | src/local_delegate/legacy_names.py:587-647 (`read_key`, `normalize`, …); tests/test_recompute_legacy.py:110, :155, :167; A2–A5 |
| REQ-007 P-4 con los dos formatos | C | `scripts/measure_cooldown.py`; tests/test_measure_cooldown.py; A4 #252; corrida real en `evidence/live-035/install-doctor-panel.md` |
| REQ-046 Comandos de medición documentados siguen | C | `scripts/medir_enfriamiento.py` (envoltorio, docstring REQ-046); nota fechada en `.sdd/changes/delegacion-precisa-y-fiable/verification.md:1436` y `daemon-reparte-el-backend/verification.md:1069`; entrada de retirada en el backlog del vault (línea ~199); A10a #291–#294 |
| REQ-008 Ficheros de terceros | C | src/local_delegate/legacy_names.py:545 (`QUOTA_STATUSLINE_FILE_NAMES` con los dos nombres); src/local_delegate/recompute.py:4-5; A5 |
| REQ-009 API del panel y JS en inglés con paridad | C | tests/test_metrics.py:1124 (`test_acct_parity_between_python_and_the_dashboard_js`); A2, A3, A5, A8b #271 |
| REQ-010 Contrato de `local_extract` y marcadores | C | Subclaves `truncated`, `warning`, `read_server_side`, `fallback`, `raw` (sección «Pendiente» vacía desde B2b-1, `rename-exceptions.md:464`); tests/test_tool_contract.py:151, :169; B2b-1 #317 (`feat(tools)!`), CHANGELOG `[0.36.0]` con la tabla del contrato |
| REQ-011 Ids y grupos de checks en inglés | CL | `checks.CHECKS` con ids nuevos; tests/test_checks.py:93 (`== 25`); A6 #262. Límite documentado: `doctor` no tiene `--json`; el CHANGELOG lo anuncia por ids y grupos (`verification.md`, «Deviations») |
| REQ-012 Nombres nuevos en disco y retirada de viejos | C | src/local_delegate/install.py:111 (`_RETIRED_SCRIPTS`), :124; tests/test_install.py:160, :176, :813; `install` real en vivo en `en` y `es` (`evidence/live-036/install-doctor-panel.md` §2) |
| REQ-013 Retirada de skills instaladas | C | src/local_delegate/install.py:124 (`_RETIRED_SKILLS`), :1187; tests/test_install.py:783 (skill ajena intacta), :806; A0 #247 |
| REQ-014 Módulos en inglés sin romper scripts | C | `src/local_delegate/` sin módulos en español (listado de `b8ede29`); tests/test_scripts_english.py:77, :116; A8a #269–#270 |
| REQ-015 Identificadores, tests y scripts en inglés | C | A7–A10 (#265–#301); detector a 0 fuera de la lista; recuentos por lote en `waves/A*.md` y `evidence/conformance/wave-records.txt` |
| REQ-016 Cierre medible del frente A | **CL** | Cierre de A: 0 fuera, «pendiente» solo REQ-010, 0 sin clasificar (`waves/A-close.md:614`, `evidence/A-close/detector.json`). Cierre del cambio: 0 fuera, «pendiente» vacía (`evidence/close/detector.txt`; `rename-exceptions.md:429`, `:464`); guardián tests/test_detect_spanish_names.py:213 (nuevo en #330). Límites: 111 sin clasificar (punto 1); valores de una sola palabra no vistos (`verification.md`, «Deviations»); ubicación de la lista al archivar (backlog §1.10) |
| REQ-017 Comportamiento funcional idéntico | **CL** | Suite completa verde (ver `quality.md`); 11/11 tools en vivo en `en` y `es` (`evidence/live-036/tools.md`, ventanas `w-20261018T132615Z`, `w-20261018T134632Z`). Límites documentados: backlog §1.8 y §1.9 (cambios de calidad del resumen de lint que el frente B introdujo a propósito y cuya celda de afinidad salió) |

### Frente B: idioma

| REQ | Veredicto | Evidencia |
| --- | --- | --- |
| REQ-018 Regla única del idioma | C | src/local_delegate/resources/hooks/hook_common.py:495 (`resolve_language`, única implementación); src/local_delegate/i18n.py:34; tests/test_language.py (33 tests, los nueve casos con origen); B0a #309 |
| REQ-019 Elección con una sola variable | C | tests/test_language.py:76 (gramática); tests/test_mcp_english.py:193 (`local_status` con idioma, origen y ruta); en vivo `evidence/live-036/install-doctor-panel.md` §3 |
| REQ-047 Preferencia guardada por `install` | C | hook_common.py:384 (`language.json`); tests/test_install_language.py:100, :107, :131 (`uninstall`); en vivo `doctor` y `local_status` con origen «preferencia» (`live-036/install-doctor-panel.md` §3); B0a + B5 #328 |
| REQ-020 Selector de idioma en el panel | C | tests/test_dashboard_ui.py:1582, :1600, :1643 (dos visitantes contra un daemon), :1707; en vivo `live-036/panel-live.json` y capturas; B4 #326 |
| REQ-021 CLI completo en el idioma | C | tests/test_cli_english.py (11 tests: :145, :155, humo en `en`); B1a #311 |
| REQ-022 `doctor` y checks | C | tests/test_doctor_english.py:82, :99, :108; B1b #312 |
| REQ-023 Salidas de las tools y `local_status` | C | tests/test_mcp_english.py:132 (las 11 tools en `en`, camino feliz y errores), :193; B2a #316 |
| REQ-024 Hooks sin importar el paquete | C | tests/test_hook_texts.py:53, :67 (guardián por AST); hooks reales en sh y PowerShell en los dos idiomas (`live-036/install-doctor-panel.md` §4); B3 #327 |
| REQ-025 Panel entero en el idioma | C | Guardián de catálogo sobre el DOM en `tests/test_dashboard_ui.py` (parametrizado por idioma, :566); en vivo `live-036` §5; B4 #326 |
| REQ-026 Formatos por superficie | C | tests/test_cli_english.py:277, :282; tests/test_mcp_english.py:173; tests/test_llamaswap_english.py:135; B1, B2, B4 |
| REQ-027 Descripciones de tools solo en inglés | C | tests/test_tool_contract.py:75, :84, :92, :109; B2b-1 #317 (misma versión que REQ-010) |
| REQ-028 El modelo local responde en el idioma | **CL** | Tests: tests/test_response_language.py:98, :109, :121; tests/test_commit_language.py:127 (`commit_msg` intacto); juez `scripts/judge_response_language.py`. En vivo: B2d-2 43/44, ≥ 90 % por tool y tanda (`evidence/B2d-2/live.md:48-52`); 0.36.0 12/12 (`live-036`). Límites: backlog §1.8 y §1.10 (cifras en lint `es`); **sin muestra en vivo con `fr`** y **muestra de 1 documento por idioma en `explain_code`/`describe_image`** (puntos 2 y 3) |
| REQ-029 Skill, bloque y catálogo de subagentes en el idioma | C | tests/test_skill_parity.py:57, :63, :69; tests/test_install.py:813; `install` real en `en` y `es` (`live-036` §2); B5 #328 |
| REQ-030 Una sola fuente de textos | C | `src/local_delegate/resources/i18n/{es,en}/*.json`; tests/test_i18n_parity.py (14 tests, cubre hooks); B0a #309 |
| REQ-045 Ningún texto fuera del catálogo | C | tests/test_no_uncatalogued_text.py:515, :532, :550; `tests/data/uncatalogued_pending/` no existe en `b8ede29`; excepciones con motivo en `tests/data/uncatalogued_exceptions.json`; B0b #310 → B5 |
| REQ-031 Paridad entre idiomas | C | tests/test_i18n_parity.py:85, :97 (con control positivo en `waves/B0a.md`); B0a #309 |
| REQ-032 Guardianes del panel y la wiki en los dos idiomas | C | tests/test_dashboard_ui.py:566 (guardianes parametrizados); tests/test_wiki.py; B4 #326, B1 |
| REQ-033 Lo ya escrito se muestra tal cual | C | src/local_delegate/sections.py (`NOT_SUMMARIZED_FORMS`, `INTRODUCTION_FORMS` con las dos formas, `waves/B2a.md`); tests/test_recompute_legacy.py; `marcas` como valor de máquina (A5b); B2a, B4 |
| REQ-034 Humo en inglés por superficie | C | CLI tests/test_cli_english.py (humo en `en`); `doctor` tests/test_doctor_english.py; MCP tests/test_mcp_english.py:132; hooks tests/test_hook_texts.py; panel tests/test_dashboard_ui.py; `install` tests/test_install_english.py:60 (con su control `:81`); llama-swap tests/test_llamaswap_english.py:105 |
| REQ-043 La suite no depende del idioma de la máquina | C | tests/conftest.py:20-43 (fixture de sesión, `LOCAL_DELEGATE_LANG=es`), :183 (`browser_locale`); CI `test-lang-es` con `LANG=es_ES.UTF-8` verde y la suite por defecto verde (ver `quality.md`) |

### Transversal: proceso

| REQ | Veredicto | Evidencia |
| --- | --- | --- |
| REQ-035 Frente A antes que B | C | Primera ola de B (#309) mezclada tras la última de A que toca `src/` (A-close-5 #306); orden completo en la tabla de PR de arriba. B4 (#326) antes que B3 (#327) no lo viola: el orden exigido es A antes que B |
| REQ-036 Uso del MCP `local-delegate`, registro por ola | **CL** | Todas las olas tienen `waves/<ola>.md` con su tabla `local_*`. Mínimo («la ola que corre la suite pasa su log por `local_lint_summary`») **no cumplido en B2f, B3, B4 y B5**, con motivo escrito en cada registro: el MCP no conectaba (`ECONNREFUSED`) y un subagente no lo recupera (`waves/B2f.md:50`, `B3.md:75`, `B4.md:84`, `B5.md:72-79`). La spec admite «0 con motivo» para la tabla, no para el mínimo; queda como límite documentado |
| REQ-037 Uso del MCP de PyCharm | C | Tablas `mcp__pycharm__*` con `rename_refactoring` y `get_file_problems` en las olas que renombran (A0–A10, A-close: `waves/A*.md`). Las olas de B no renombran símbolos; B5 deja motivo (PyCharm caído, sustituido por `grep` + `ruff check`, `waves/B5.md:79`) |
| REQ-038 Pruebas en vivo en ventanas de prueba | C | Ventanas en `verification.md:31-33` (`w-20261013T123443Z`, `w-20261018T132615Z`, `w-20261018T134632Z`) y en los registros de B2d/B2d-2 (`w-20261014T215251Z`, `w-20261015T193400Z`, …); todas cerradas |
| REQ-039 Comandos pesados serializados | C | Cada log de suite empieza con la línea `[pesado] plaza … tomada` (p. ej. `evidence/live-036/suite-es.txt:1`, `B4/suite-es.txt:1`, `B2f/suite-es.txt:1`) |
| REQ-040 Cada release toca CHANGELOG, README y wiki | C | 0.35.0 (#264) y 0.36.0 (#330 + olas): `CHANGELOG.md:28` (cómo elegir español con `LOCAL_DELEGATE_LANG=es … install`), `:267-270` (retirada en 0.38.0), `:274` (volver atrás no está soportado); README +6 en #330; `docs/wiki/Language.md` (precedencia) y 10 páginas cambiadas entre 0.35.0 y 0.36.0 |
| REQ-041 Fronteras de tramo por versión | C | `scripts/data/measurement_boundaries.json`, `scripts/data/hook_hashes_after.json`; tests/test_hook_boundaries.py:66 (hash actual en el conjunto), :174 (dos máquinas: hash viejo con fecha posterior queda antes); B0, B2b-2, B3 |
| REQ-042 Formato de línea preservado | C | Comparación `8ec2f1d` → `b8ede29` de los 165 ficheros modificados o renombrados: **0** cambian de LF/CRLF/mixto (script en esta revisión; ver `quality.md`) |

## Fuera de alcance por diseño

- **Ola R: retirada de los alias** (subcomando, opción, variables, doble escritura de
  `enfriamiento.json`) en la **0.38.0**. CHANGELOG `[0.35.0]`/`[0.36.0]` lo anuncian y
  `tests/test_deprecations.py:74` falla si una versión llega a la de retirada con el alias vivo.
- No-objetivos de la spec (`spec.md`, «Non-goals»): traducir la documentación, más idiomas, migrar
  datos, la skill subida a mano a Claude Desktop, el lanzador del daemon de esta PC.

## Huecos resueltos después (2026-10-19) y decisión del gate

Los tres huecos de la recomendación se cerraron antes de aprobar:

1. **Palabras sin clasificar → 0** (PR #332). Las 111 palabras se clasificaron en
   `scripts/data/spanish_lexicon.json` (procedimiento en `spanish_lexicon.README.md`), la lista de
   excepciones se mudó a `scripts/data/name_exceptions.json` y el guardián
   `test_repo_has_no_spanish_name_outside_the_exception_list` exige ahora también
   `unclassified_words == {}`. Los PR #341 y #342 añadieron 9 palabras más por el mismo
   procedimiento (puntos 11 y 12 del README del léxico). REQ-016 y REQ-044 cumplen sin límite.
2. **Muestra en vivo con `fr`** (PR #339, con el juez arreglado en #338): 4 tools en francés
   (`summarize`, `lint_summary`, `explain_code`, `describe_image`), 5 documentos × 3 repeticiones,
   en la ventana de prueba `w-20261019T044210Z`. Resultado y juez en `evidence/req028-samples/live.md`.
3. **Muestra de 5 o más documentos** para `explain_code` y `describe_image` (PR #339): 15/15 por
   tool en `es` (`w-20261019T041119Z`) y en `en` (`w-20261019T043654Z`), con documentos en el otro
   idioma. REQ-028 cumple en es/en/fr.

Lo que sigue abierto queda fuera de este cambio y anotado: la ola R (retirada de alias en la
0.38.0, vigilada por `tests/test_deprecations.py`), el backlog §1.8 parcial (lint troceado: el paso
final ya no se corta, PR #342, pero algunos pasos intermedios sí, `evidence/lint-large-logs/live.md`)
y el §1.11 nuevo que sale de esa medición (las cifras por fichero del rol mecánico no se
adoptaron: no llegaron al criterio y retrocedían en inglés).

**Decisión: aprobado** (2026-10-19), por delegación expresa del usuario para cerrar el frente B.

