# B2d-2 — Plan de la medición en vivo (fijado antes de medir)

Fijado el 2026-10-15, antes de cualquier llamada de medición. Lo corre la sesión principal tras
instalar el código de la rama en el daemon. Todo lo que puntúa ya está aquí: el conjunto, el
criterio de «hecho» y los scripts. Lo que salga va a `evidence/B2d-2/live.md`.

## Ficheros

| Fichero | Qué es |
|---|---|
| `manifest.json` | Las 44 llamadas, con su tanda (A, B, C), su documento y sha256, el idioma de entrada, el pedido y dónde guardar la respuesta literal (`live-answers/<id>.txt`). |
| `fidelity-set.json` | Los 10 logs del conjunto 3 con su sha256 y lo que contienen (cifras, ficheros, recuentos que respaldan), la base (9) y el umbral (0). |
| `fidelity-baseline-set3/` y `fidelity-baseline-set3.json` | Las respuestas literales del conjunto 3 (código `32d8612`, tope 496) y su puntuación: 7 cifras inventadas, 0 ficheros, 2 frases repetidas. |
| `lint-truncation-baseline-2026-10-15.json` | Base del tope: filas de lint del 2026-10-15 en el log de uso (orden endurecida, tope 496): `gemma4-26b-a4b` 4 de 15 cortadas por `length`, `gemma3-4b` 0 de 30. |
| `lint-truncation-baseline-before-hardening.json` | Filas de lint del 2026-10-01 al 14: `gemma4` 3 de 22 (el 3/22 del plan). |
| `control-set3-labels.json` | Control de la regla de etiquetas sobre el conjunto 3: encuentra 10, las 9 revisadas a mano más «llamaswap residency»; y la introducción doble de pycparser (2). |
| `score_live.py` | Puntúa: `log` (tope y troceado desde el log de uso), `answers` (etiquetas, introducción y fidelidad desde el manifiesto), `labels`, `intro`, `control-set3`. |
| `../../../../scripts/score_lint_fidelity.py` | El contador de invenciones (con sus tests en `tests/test_lossless_summary_output.py`). |

## Preparación (una vez)

1. Instalar la rama en el daemon: `uv tool install --force --reinstall --no-cache ".[llamaswap]"` y
   reiniciar el daemon con el procedimiento de siempre. Tras reiniciar, `/mcp` y comprobar con
   `local_status` que responde la versión instalada.
2. Comprobar que el log de uso nuevo escribe `chars_out_raw` (cualquier llamada de prueba dentro de
   una ventana sirve).

## Tandas

Cada tanda en su propia ventana de prueba: `local-delegate test-window start --label "<label>"`,
anotar el id, hacer las llamadas en serie y `local-delegate test-window stop <id>` al acabar.
Variables de entorno temporales del daemon (en el lanzador o como se hizo en B2d):

| Tanda | Variables | Label | Llamadas |
|---|---|---|---|
| A | `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en` (producto `es`) | `B2d-2 tanda A es + output en` | 15 lint (conjuntos 1, 2 y 3, tanda 1) + 5 summarize del conjunto 3 + httpcore2 y httpx2 |
| B | `LOCAL_DELEGATE_LANG=en`, `LOCAL_DELEGATE_OUTPUT_LANGUAGE=es` | `B2d-2 tanda B en + output es` | 15 lint (tanda 2) + 5 summarize del conjunto 3 |
| C | `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en`, `LOCAL_DELEGATE_MAX_CHARS_LONG=8000` | `B2d-2 tanda C troceado forzado` | lint de `en-log-biome-lint.txt` y `lint-9k.txt` |

Cada llamada con `path=<ruta absoluta del documento>` y los argumentos por defecto (sin `max_words`
ni `focus`). Guardar la respuesta **literal** en el `answer` de su fila del manifiesto (UTF-8). Al
acabar, quitar las variables temporales y volver a reiniciar el daemon.

## Puntuación (después de las tres tandas)

```bash
E=.sdd/changes/english-names-bilingual-output/evidence/B2d-2
LOG="C:/Users/Yohan/AppData/Local/local-delegate/usage-202610.jsonl"   # el del daemon
# 1. Tope de lint y troceado (desde el inicio de A hasta el final de C, en UTC):
uv run python $E/score_live.py log --usage-log "$LOG" --since <ts inicio A> --until <ts fin C>
# 2. Etiquetas, introducción y fidelidad:
uv run python $E/score_live.py answers --manifest $E/manifest.json
# 3. Idioma, con el juez de prosa (no con el detector sobre el texto entero), por respuesta:
uv run python scripts/judge_response_language.py --document <doc> --requested <en|es> <answer>
```

Comprobar antes de juzgar: los sha256 de los documentos siguen iguales (`score_live.py answers`
falla con `log_changed` en los de fidelidad); en la tanda C, `chunks > 1` en las dos filas del log.

## Criterios de «hecho» (por punto del plan)

1. **Tope de lint.** 0 respuestas de `gemma4-26b-a4b` con `finish_reason="length"` en lint en las
   tandas A, B y C (base: 4 de 15 el 2026-10-15). Si no es 0, nunca por encima de 3/22 (13,6 %).
   En la tanda C, ningún paso del troceado cortado (la fila del log no lleva `truncated_out`). Si
   falla: subir `LINT_TOKENS_PER_WORD`/`LINT_TOKENS_BASE` (`server.py`), reinstalar y repetir solo
   el lint; los valores de hoy (3·w+128 y 3·w+96 por trozo) son provisionales.
2. **Sección vacía.** httpx2 (tanda A): sin `[local-delegate warning: ` de secciones sin resumir por
   `## Release Information`, y su línea del prompt sin palabras (visible solo en tests).
3. **Corte por tope.** Sin medición propia: lo cubren los tests; si httpcore2 sale cortado, que el
   cuerpo de la última sección no desaparezca entero.
4. **Largo crudo.** httpcore2 (tanda A): la fila tiene `chars_out_raw`; explicar en `live.md` la
   diferencia con `chars_out` y con `tokens_out` (corte, espacios degenerados o razonamiento
   oculto). Recuento de filas con `chars_out_raw > chars_out` en `score_live.py log`.
5. **Sección repetida.** pycparser (tanda A): `introductions` = 1 (base: 2). `duplicate_introductions`
   = 0 en `score_live.py answers`.
6. **Contenido inventado.** Primero se mide con el tope nuevo: `fidelity_total` de los 10 logs del
   conjunto 3 (base 9; umbral 0, nunca por encima de 9). Con ese número se decide el cambio (prompt
   «solo lo que está en el log», recuentos calculados por el programa o ambos), se implementa en un
   lote propio y se vuelve a medir con el mismo conjunto. Las atribuciones falsas (un fichero real
   presentado como fichero con errores) se anotan a mano en `live.md`.
7. **Etiquetas copiadas.** `copied_labels` = 0 en los 10 summarize del conjunto 3 (base: 10 con la
   regla de hoy, 9 revisadas a mano).
8. **Juez en cp1252.** Sin medición: `scripts/judge_response_language.py` con
   `es-log-B2c_corpus-f2-check.txt` como documento ya no lanza `UnicodeDecodeError`.

Idioma (no es un punto de B2d-2 pero se reporta): con el juez de prosa, ≥ 90 % `requested` entre
las juzgables por tool y tanda, 0 en el idioma contrario.
