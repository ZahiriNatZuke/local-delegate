# B2d-2 — Medición en vivo (2026-10-15)

Conjunto y criterios fijados antes de medir en `live-plan.md` y `manifest.json` (commit `8a67dd0`).
Código de la rama instalado con `uv tool install --force --reinstall --no-cache ".[llamaswap]"`; el
daemon arrancó con las variables temporales de cada tanda en el lanzador, y al acabar se restauró
el lanzador con su huella original (`c96f022a…f69f69a`). Las 44 llamadas se hicieron con
`run_live.py` contra el `/mcp` del daemon, sin pasar por el contexto de Claude; las respuestas
literales están en `live-answers/`.

| Tanda | Ventana de prueba | Variables | Llamadas | Errores |
|---|---|---|---|---|
| A | `w-20261015T193400Z` | `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en` | 22 | 0 |
| B | `w-20261015T193836Z` | `LOCAL_DELEGATE_LANG=en`, `LOCAL_DELEGATE_OUTPUT_LANGUAGE=es` | 20 | 0 |
| C | `w-20261015T194137Z` | `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en`, `LOCAL_DELEGATE_MAX_CHARS_LONG=8000` | 2 | 0 |

Puntuación: `live-score-log.json` (`score_live.py log`, de 19:34 a 19:43 UTC),
`live-score-answers.json` (`score_live.py answers`) y `live-language-verdicts.txt` (juez de prosa).
Sha256 de los documentos: sin cambios (`run_live.py` lo comprueba antes de cada tanda).

## Resultado por punto

1. **Tope de lint: CUMPLE.** `gemma4-26b-a4b` en lint: 0 de 9 con `finish_reason="length"` (base:
   4 de 15 el 2026-10-15). `gemma3-4b`: 0 de 23. En la tanda C las dos llamadas se trocearon
   (`chunks` 4 y 3), terminaron en `stop` y ninguna lleva `truncated_out`. Los valores 3·w+128 y
   3·w+96 dejan de ser provisionales.
2. **Sección vacía: CUMPLE.** httpx2 (A42) sale sin `[local-delegate warning: ` de secciones sin
   resumir.
3. **Corte por tope: CUMPLE.** httpcore2 (A41) sale cortado por `max_tokens` (esperado: 26 534
   chars de changelog). La última sección conserva su cuerpo hasta el corte; no desaparece entera.
4. **Largo crudo: CUMPLE.** La fila de httpcore2 lleva `chars_out_raw` = 5 426, `chars_out` = 5 484 y
   `tokens_out` = 2 112, con `finish_reason="length"`. `chars_out` supera al crudo porque el producto
   añade los títulos del documento y el aviso; ~2,6 chars por token, sin espacios degenerados ni
   razonamiento oculto. En las dos filas troceadas de la tanda C, `chars_out_raw` (3 588 y 3 819)
   es la suma de los parciales y `chars_out` (1 103 y 1 162) el reduce: 2 filas con
   `chars_out_raw > chars_out`, las dos por troceado.
5. **Introducción repetida: CUMPLE.** pycparser (A19): una sola introducción;
   `duplicate_introductions` = 0 (base: 2).
6. **Contenido inventado: NO CUMPLE; va al lote B2d-3.** `fidelity_total` = 12 en los 10 logs del
   conjunto 3 (base: 9; umbral 0, nunca por encima de 9). Reparto: A13 5, B35 4, A12 1, A15 1,
   B33 1 (frase repetida); el resto 0. Revisión a mano de A13 (`doctor` con el home vacío): las
   cifras son **reales**, recuentos por elemento («Claude Code Client (3)», «… (0)») que el log no
   trae. El prompt pide «la cantidad por tipo» y el modelo la inventa cuando el log no tiene cifras;
   con el tope más alto, tiene más sitio para hacerlo. Decisión y cambio: lote B2d-3 del plan.
7. **Etiquetas copiadas: CUMPLE.** `copied_labels` = 0 en los 10 summarize del conjunto 3 (base: 10).
8. **Juez en cp1252: CUMPLE.** El juez procesó A12 (documento `es-log-B2c_corpus-f2-check.txt`,
   cp1252) con veredicto y sin `UnicodeDecodeError`.

## Idioma (se reporta; no es punto de B2d-2)

Juez de prosa: 43 de 44 `requested`, 1 `unknown` (A07, `doctor` con salida casi vacía), 0 en el
idioma contrario. Por tool y tanda: lint A 14/15, summarize A 7/7, lint B 15/15, summarize B 5/5,
lint C 2/2. Cumple (≥ 90 % y 0 contrarios).
