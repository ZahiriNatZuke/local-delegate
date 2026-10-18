# Lote B2-affinity: la celda de afinidad de `local_lint_summary` con los prompts de la 0.36.0

Rama `sdd/english-names-b2-affinity` desde `main` (`db384c3`, B2e). Ejecuta el lote «B2-affinity»
de `plan.md` (sección escrita en este lote, antes de medir). Medición en vivo del agente con
`evidence/B2-affinity/run_affinity_live.py` y el script de la sesión
`~/.claude/relevos/b2affinity-measure.ps1` (patrón de `b2e-measure.ps1`). Sin push ni PR.

## Commits

| Commit | Qué |
|---|---|
| `55fa4d8` test(affinity) | sección del plan con método y criterio antes de medir; scripts de medición, evaluación y control de la flecha; las dos tandas, el veredicto nuevo y la evidencia |
| (siguiente) fix(affinity) | la celda de lint sale de `CELLS`; tests de afinidad; docstring de `_lint_system`; CHANGELOG, wiki `Tools.md` y este registro |

## Celdas afectadas

Comprobado por ejecución en `db384c3` con la config real de llama-swap
(`checks._stale_affinity_cells`): solo `local_lint_summary → gemma4-26b-a4b` (frente a
`gemma3-4b`), por `prompt_sha256`. El prompt de lint depende ahora del idioma (`es` `0b070d5d…`,
`en` `2c9a0a31…`; T6 midió `5202980b…`). `local_translate` y `local_delegate` siguen con su huella.

## Método y resultado

Detalle en `evidence/B2-affinity/live.md`. Los 4 casos de lint del corpus congelado por la tool
real del daemon, 3 repeticiones, una ventana por (modelo, idioma); los seis criterios de T6 con
`analyze_benchmark.evaluate_mechanical_cell` sin tocarlo; «hecho» = `approved` en las 3
repeticiones.

1. **Primera tanda: la flecha no discriminaba.** El puntuador de T6 solo lee «`CÓDIGO: N`» y cuenta
   los números de línea; con el prompt nuevo puso 0 también al rol. Regla (2) antes que la (1):
   puntuador v3 (solo en la evidencia), con sus controles escritos antes de usarlo
   (`scorer-v2-check.md`): referencias, pasa; las 7 notas de T6 que cambia, la revisión a mano le
   da la razón; 16 respuestas de la primera tanda, 14 de 16 (no llega al 15 fijado: dos del rol en
   prosa ambigua, sin cambiar el sentido de ninguna comparación). Se dejó escrito que, en la segunda
   tanda, la revisión a mano del sentido manda donde no coincida.
2. **Segunda tanda (decide):** 26B rechazada en `es` (3 de 3) y en `en` (2 de 3); regla (1),
   `qwen36-35b-a3b`, rechazada en los dos (3 de 3). Falla la calidad; la latencia cumple siempre.
   La revisión a mano coincide en todo: en `es` el 26B no nombra ningún código de regla en 9 de 9
   respuestas de tres casos; en `en` a veces no da cifras; Qwen escribe prosa sin códigos.
3. **Regla (3):** la celda sale de `CELLS`. Sin afinidad de lint en la 0.36.0 (en ejecución no
   cambia nada: la celda sin base ya no se usaba), `doctor` sin «afinidad sin base» en `es` y en
   `en`, y el veredicto nuevo (`benchmarks/afinidad-2026-10/reevaluation-0.36.0/verdict.json`, con
   `supersedes`) dice por qué. Nota de backlog: `evidence/B2-affinity/backlog-note.md`.

## Tests y control positivo

`tests/test_affinity.py`: fuera `CELLS_WITHOUT_BASE`; `test_matrix_cells_are_the_approved_cells_of_the_verdict`
compara `CELLS` con T6 menos lo reemplazado más lo aprobado en la re-evaluación;
`test_prompt_footprint_of_the_code_is_the_measured_one` sin excepciones; nuevo
`test_reevaluation_verdict_rejects_the_lint_cell_in_both_languages` (las 4 celdas medidas,
rechazadas, 3 repeticiones, y la huella guardada = el prompt de hoy en el idioma de la corrida, y
distinta de la del otro idioma).

Mutante: volver a poner la celda de lint (huella de T6) en `CELLS` → fallan
`test_matrix_cells_…` («Extra items in the left set: ('local_lint_summary', 'gemma4-26b-a4b',
'gemma3-4b')») y `test_prompt_footprint_…` (`'0b070d5d…' == '5202980b…'`), por la razón que dicen.

## Verificación

- Suite completa, `-n 2`: `evidence/B2-affinity/suite-es.txt` y `suite-en.txt`, 3067 passed y
  2 skipped en las dos.
- `ruff check .` y `ruff format --check .` limpios (247 ficheros).
- Corpus: `corpus-affinity-check.txt` y `corpus-f2-check.txt`, `ok`. Las 89 notas «frontera
  declarada» de `affinity --check` se quedan a propósito: el corpus congelado no se regenera (B2b-2)
  y mide el prompt de T6.
- `doctor` (`checks._stale_affinity_cells` con la config real): `([], 0)` en `es` y en `en`.
- Lanzador restaurado desde `launcher-backup.ps1`, huella
  `c96f022aeb1b2570fc273419203f2f870d7a13022c373e35f7ae6af7ae69f69a` comprobada; 14 ventanas de
  prueba abiertas y cerradas por id; daemon con el código de la rama instalado al final.

## Llamadas `local_*`

**0.** El MCP `local-delegate` estaba caído para esta sesión desde el principio (`ECONNREFUSED` al
cargar las tools, con el daemon en marcha en el 9393), y un subagente no recupera el MCP tras
reiniciar el daemon. Las respuestas de la medición no pasaron por el contexto salvo las que se
revisaron a mano (32 de lint, cortas).
