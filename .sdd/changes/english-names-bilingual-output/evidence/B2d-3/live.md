# B2d-3 — Medición en vivo del paso 1 (2026-10-17, n=1, referencia)

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

## Por respuesta

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

## Diagnóstico

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
