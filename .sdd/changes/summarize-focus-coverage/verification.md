# Verification: local_summarize: el enfoque llega a la sección que lo trata, o avisa

## Environment

- Revision: rama `fix/summarize-focus-coverage` desde `main` (`89551158`).
- Windows 11, Python del `.venv` del checkout principal con `PYTHONPATH=src` (importa el worktree).
- Backend falso (`backend_mock`). La reproducción en vivo del síntoma se hizo con la 0.48.0
  instalada (ventana de prueba `w-20261104T104920Z`).

## Causa medida

- La entrada del issue (16 KB) supera `LONG_INPUT_CHARS` (6000) y cabe en el tope del rol `long`
  (48000): una sola llamada. El daemon tiene encendido el resumen estructurado (la respuesta en
  vivo trae `## Introducción`, `## Revisado sin hallazgos`…): los `###` son subtítulos de la
  introducción.
- El foco llega al prompt de sistema en todos los caminos (`_focus_clause` en `extra`: llamada
  única, cada trozo del map estructurado, `reduce_extra` del map/reduce en prosa; lo cubren
  `test_focus_arrives_sanitized_and_not_in_the_log` y `test_focus_in_structured_mode`). No hay
  preselección de secciones. El modelo lo ignora frente a la lista de secciones con su reparto de
  palabras. Reproducido en vivo con la 0.48.0: el resumen no menciona `cp1252`, `utf8` ni `stdin`.
- Con la rama, sobre el fichero real (función pura, sin red): `focus_terms` = `cp1252, utf8,
  stdin`; las secciones nombradas al modelo son 2 (la de `cp1252` y la lista final, que menciona
  stdin); el resumen de la 0.48.0 no tiene ninguno de los términos, así que llevaría el aviso.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | Markdown sintético de ~14 KB con la forma del issue: el mensaje de usuario nombra la sección de `cp1252` en prosa, en estructurado (tras la lista de secciones) y en el map (solo el trozo que la tiene) | pass | `tests/test_summarize_focus_coverage.py::test_prose_path_…`, `test_structured_path_…`, `test_each_chunk_names_only_the_sections_it_holds`, tests de `focus_terms`/`focus_terms_in`/`focus_sections`; mutante «`_focus_note` devuelve ''» los hace fallar en `user.startswith("Secciones que tratan…")` |
| REQ-002 | resumen sin los términos: aviso `cp1252, stdin` antes del recibo; resumen con `CP1252`: sin aviso; foco ausente de la entrada: sin aviso; error del backend: sin aviso; título repuesto «(sin resumir)» no cuenta | pass | `test_…_warns_when_it_is_missed` (3), `test_a_summary_that_covers_the_focus_is_not_warned`, `test_a_focus_absent_from_the_input_is_not_warned`, `test_a_backend_error_carries_no_focus_warning`, `test_a_heading_put_back_unsummarized_…`; mutante «sin aviso» falla en `assert _warning("cp1252, stdin") in output`; mutante «juzgar tras `complete`» falla en ese mismo assert del último test |
| REQ-003 | sin foco: mensaje de usuario `Resume el siguiente contenido:\n\n{DOC}` y ni rastro de «aspecto prioritario» ni del aviso, en prosa y estructurado | pass | `test_without_focus_nothing_changes`; los tests existentes de `local_summarize` siguen verdes sin tocarlos |
| REQ-004 | entrada en CHANGELOG `[Unreleased]` → Corregido con (#558) | pass | `CHANGELOG.md` |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest` (suite completa, `-n 2`, con el cerrojo `pesado.sh`) | sí | ver entrega | salida en el scratchpad de la sesión |
| `ruff check src tests/test_summarize_focus_coverage.py` | sí | pass | All checks passed! |
| `ruff format` (ficheros tocados) | sí | pass | formateado |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [ ] Secret scanning passes. (lo hace el CI: GitGuardian)
- [x] No unrelated changes are present.

## Deviations and residual risk

- La primera corrida de la suite completa dio 4 rojos que se arreglaron sin tocar tests existentes:
  `test_a_code_file_does_not_take_the_structured_path` (#539) recibía la nota con «Verify», un
  título de una cadena del `.mjs` → la nota no se calcula en ficheros de código; los guardianes de
  texto sin catalogar (literales de prompt reescritos → se dejaron byte a byte y la nota se
  concatena; nota nueva y lista de palabras vacías → excepciones `verbatim` en
  `tests/data/uncatalogued_exceptions.json`) y de nombres en español (`informe.md`, `stopwords`,
  `folds`… → renombrados).

- La nota del prompt mejora la probabilidad de que el modelo cubra la sección, pero no la
  garantiza; el aviso es la red. No se midió en vivo la rama contra el modelo real (la prueba en
  vivo la hace la sesión principal tras instalar).
- Coincidencia por prefijo: un término corto puede casar con otra palabra (`stdin` → `stdi…`); en
  el peor caso suprime un aviso o nombra una sección de más, nunca cambia la salida sin foco.
