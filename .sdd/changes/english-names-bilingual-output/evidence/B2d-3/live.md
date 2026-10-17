# B2d-3 — Medición en vivo de la regla de la cantidad de lint

## Método nuevo: base, paso 1 y paso 1b, 3 repeticiones (2026-10-17)

La hizo la sesión principal con el procedimiento de `measure.md`: cada versión instalada en el
daemon, las 10 llamadas de lint del conjunto 3 (tandas A y B de `manifest.json`) repetidas 3 veces,
sin pasar por el contexto de Claude, y recuento desde la rama con el contador y el control nuevos.
Respuestas literales en `runs/<versión>/<id>-r<k>.txt`, horas en `runs/<versión>/live-runs.json`,
recuento en `runs/<versión>/score-answers.json`, control en `runs/controls.json` y log de uso en
`runs/score-log.json`. Al acabar, el lanzador del daemon quedó restaurado (sha256 `c96f022a…f69f69a`,
el de antes).

| Versión | Commit | Ventana tanda A | Ventana tanda B | Llamadas | Errores |
|---|---|---|---|---|---|
| base | `7a17941` (`main`) | `w-20261017T153225Z` | `w-20261017T153449Z` | 30 | 0 |
| paso 1 | `8999bce` | `w-20261017T153801Z` | `w-20261017T154019Z` | 30 | 0 |
| paso 1b | `20faa5e` | `w-20261017T154328Z` | `w-20261017T154547Z` | 30 | 0 |

Las seis ventanas están cerradas.

### Resultado por versión

| Versión | `fidelity_totals` (r1, r2, r3) | Media | Media sin B35 | `parenthesized_invented` | Controles conservados (2 de 3) | Cortadas |
|---|---|---|---|---|---|---|
| base | 9, 20, 6 | 11,67 | 8,67 | 0, 11, 0 | A15, B31, B32 | 0 |
| paso 1 | 6, 7, 6 | 6,33 | 6,33 | 0, 0, 0 | B31, B32 (A15 0 de 3; B32 2 de 3) | 0 |
| paso 1b | 2, 5, 4 | **3,67** | 3,67 | **0, 0, 0** | **A14, A15, B31, B32** | **3** (B35 ×3) |

`identical_in_every_repetition`: base y paso 1, ninguna; paso 1b, `['A15']` (las 3 respuestas de A15
son idénticas byte a byte; las otras 9 llamadas sí varían, así que las repeticiones miden ruido).

### Por llamada (`per_call`, r1/r2/r3)

| Log | base | Qué cuenta en la base | paso 1 | Qué cuenta en el paso 1 | paso 1b | Qué cuenta en el paso 1b |
|---|---|---|---|---|---|---|
| A11 | 0/0/0 | — | 0/0/0 | — | 0/0/0 | — |
| A12 | 3/1/1 | 6, 6, 4; 6; 6 | 0/0/0 | — | 0/0/0 | — |
| A13 | 1/11/2 | 3; once cifras entre paréntesis (0 ×9, 8, 3); 3, 255 | 1/1/1 | 3; 255; 255 | 0/1/1 | 3; 3 |
| A14 | 0/0/0 | — | 0/0/0 | — | 0/0/0 | — |
| A15 | 1/1/1 | 3 en cada una | 1/1/1 | «three» en cada una | 0/0/0 | — |
| B31 | 2/0/0 | 44, 13 | 2/2/2 | 41, 16 en cada una | 0/0/0 | — |
| B32 | 0/2/0 | 3, «tres» | 0/0/0 | — | 0/2/0 | 4, 4 |
| B33 | 0/0/0 | — | 2/2/2 | 52, 127 en cada una | 2/2/2 | 2 frases repetidas; 2 frases repetidas; 52, 127 |
| B34 | 0/0/0 | — | 0/1/0 | 5 | 0/0/1 | 5 |
| B35 | 2/5/2 | 4, 72; 4, 64 y 3 frases repetidas; 4, 72 | 0/0/0 | — | *cortada ×3* | no se juzga (0 en el recuento) |
| **Total** | **9/20/6** | | **6/7/6** | | **2/5/4** | |

Las frases repetidas de B33 en el paso 1b son el mismo texto para elementos distintos («El tipo de
dato proporcionado es string | undefined…», «Se recomienda agregar undefined a los tipos…») bajo un
mismo encabezado.

### Controles (`runs/controls.json`)

| Caso | Cifras reales | base | paso 1 | paso 1b |
|---|---|---|---|---|
| A14 | 125, 551, 653 | 0 de 3 | 0 de 3 | **3 de 3** |
| A15 | 10 | 3 de 3 | **0 de 3** | 3 de 3 |
| B31 | 57 | 3 de 3 | 3 de 3 | 3 de 3 |
| B32 | 7 | 3 de 3 | 2 de 3 | 2 de 3 |
| `cases_kept` | | A15, B31, B32 | B31, B32 | A14, A15, B31, B32 |

A14 no distingue con la base (no lo conserva), pero el paso 1b lo conserva en las 3: la regla de la
línea de total hace lo que se buscaba.

### Respuestas cortadas (`runs/score-log.json`)

| Tool y modelo | Llamadas | Cortadas (`finish_reason=length`) |
|---|---|---|
| `local_lint_summary` · `gemma3-4b` | 63 | 0 |
| `local_lint_summary` · `gemma4-26b-a4b` | 27 | 3 |

Las 3 cortadas son **B35 del paso 1b**, una por repetición (log de uso 15:46:48, 15:47:37 y 15:48:28
UTC, dentro de B-r1, B-r2 y B-r3 de `runs/step1b/live-runs.json`; `chars_out` de ~1700 a ~1790). B35
es `B2d-fix/docs-3/es-log-B2d-fix_corpus-affinity-check.txt` (89 líneas, sin línea de total) y va a
`gemma4-26b-a4b`. En la base y en el paso 1 B35 no se cortó ninguna vez. El modelo enumera elemento a
elemento: un bloque por cada «commit-trampa-…» y por cada «techo-commit-…», con el mismo texto en
cada uno («**System**: El sistema cambió con los prompts de la versión 0.36.0.», «**Max_tokens**: El
valor de tokens máximos cambió con los prompts de la versión 0.36.0.»), hasta agotar el tope. Su
`fidelity` sale 0, pero no se juzga.

### Diagnóstico

- **El paso 1b cumple los tres criterios del plan:** media 3,67 ≤ 11,67 (base) y ≤ 4,0;
  `parenthesized_invented` 0 en las 3 repeticiones; conserva todos los controles de la base (A15, B31,
  B32) y además A14.
- **Pero tiene una regresión que el criterio no veía:** B35 sale cortado en las 3 repeticiones. El
  tope de lint no se toca (regla del lote), así que la salida tiene que ser más corta: enumera el
  mismo problema una vez por elemento.
- **El paso 1 arregla los paréntesis y pierde totales:** 0 recuentos entre paréntesis, pero A15
  pierde «10» en las 3 repeticiones; quedan inventadas fijas A13 255, B31 41/16 y B33 52/127.
- **Decisión del usuario (2026-10-17): probar un paso 1c**, que mantiene la regla del total y pide
  agrupar en una sola línea los elementos con el mismo problema. Criterio en `measure.md` y en
  `plan.md`, fijado antes de medir.

## Referencia: paso 1, n=1 (2026-10-17)

Código del paso 1 (`8999bce`) instalado en el daemon; las 10 llamadas de lint del conjunto 3 con
`run_live.py --manifest manifest.json`, sin pasar por el contexto de Claude. Respuestas literales en
`live-answers/`. **Es una corrida por log: queda de referencia y no cuenta para el criterio**, que se
mide con el método nuevo de `measure.md` (3 repeticiones y tres versiones).

| Tanda | Ventana de prueba | Variables | Llamadas | Errores |
|---|---|---|---|---|
| A | `w-20261017T145849Z` | `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en` | 5 | 0 |
| B | `w-20261017T145949Z` | `LOCAL_DELEGATE_LANG=en`, `LOCAL_DELEGATE_OUTPUT_LANGUAGE=es` | 5 | 0 |

Ficheros: `live-runs.json` (horas), `live-score-answers.json` (`score_live.py answers` con el
contador de entonces, `fidelity_total` = 9), `recount-n1.json` (B2d-2 y paso 1 con el contador y el
control nuevos) y `controls.json` (control corregido sobre el paso 1). El primer `controls.json`,
hecho con la regex rota, daba 0 de 4; se sustituyó.

### Por respuesta

«Viejo» es `scripts/score_lint_fidelity.py` en `acd2980`; «nuevo», el de esta ola (cifras en
palabras y repeticiones por encabezado). Control: cifras reales conservadas, con la regex corregida
(entre corchetes, lo que daba la rota). B2d-2 son las respuestas de `../B2d-2/live-answers/` (código
de `main`, `7a17941`), también n=1.

| Log | B2d-2 viejo | B2d-2 nuevo | Paso 1 viejo | Paso 1 nuevo | Qué cuenta el nuevo en el paso 1 | Control B2d-2 | Control paso 1 |
|---|---|---|---|---|---|---|---|
| A11 | 0 | 0 | 2 | 2 | 2.5, 3.5 | — | — |
| A12 | 1 | 1 | 0 | 0 | — | — | — |
| A13 | 5 | 5 | 1 | 1 | 255 | — | — |
| A14 | 0 | 0 | 3 | **0** | (las 3 «repetidas» eran la misma regla en ficheros distintos) | ninguna [ninguna] | ninguna [ninguna] |
| A15 | 1 | **3** | 1 | **3** | 102, three (2 D103 en el log), eight (6 T201) | 10 [10] | ninguna [ninguna] |
| B31 | 0 | 0 | 0 | 0 | — | 57 [57] | **57** [ninguna] |
| B32 | 0 | 0 | 0 | 0 | — | **7** [ninguna] | ninguna [ninguna] |
| B33 | 1 | **0** | 2 | 2 | 52, 127 | — | — |
| B34 | 0 | 0 | 0 | 0 | — | — | — |
| B35 | 4 | 4 | 0 | 0 | («Tres reglas», «Cinco reglas»: nombres del log, `resume-ruff-tres-reglas`) | — | — |
| **Total** | **12** | **13** | **9** | **8** | | 3 casos | 1 caso |

Cifras inventadas entre paréntesis (`parenthesized_invented`): B2d-2 5 (A13 «(0)», «(3)» ×4), paso
1 **0**.

### Diagnóstico

- **Lo que se buscaba, conseguido:** los recuentos entre paréntesis por elemento desaparecieron (A13
  «Claude Code Client (3)» en B2d-2; 0 en el paso 1).
- **Lo que queda:** A11 2.5/3.5, A13 255, A15 102 (el log acaba en la línea 100), B33 52/127, y en
  palabras A15 «three» y «eight» (antes no se veían).
- **Ruido de n=1:** en los mismos logs, A11 0→2, A14 0→3 (contador viejo), B35 4→0, A13 5→1. Una
  corrida por log a temperatura 0.2 no basta para decir si el paso 1 mejora.
- **Contador:** A14 era un falso positivo (la misma línea de regla bajo dos ficheros) y B33 de B2d-2
  también («El conteo de este tipo de error es 1.» en dos ficheros con un error cada uno); el
  contador nuevo no los cuenta. Ve en cambio las cifras en palabras de A15 (B2d-2 «three»/«seven»,
  paso 1 «three»/«eight»). «Tres reglas»/«Cinco reglas» de B35 no cuentan: el log las escribe en un
  nombre (`resume-ruff-tres-reglas`), y se tratan como cualquier cifra que el log escribe.
- **Control:** la regex rota (`(?![\d.])`) rechazaba «57.» al final de frase. Corregida, B2d-2
  conserva A15, B31 y B32; el paso 1 solo B31. **A15 y B32 perdieron la línea de total** («Found 10
  errors.», «Found 7 errors.»); B32 da recuentos por tipo que suman 7, pero no el total. A14 no
  conserva sus totales en ninguna de las dos: ese caso no distingue.
- **Siguiente:** método nuevo (`measure.md`) con tres versiones, y paso 1b: copiar la línea de total
  del log.
