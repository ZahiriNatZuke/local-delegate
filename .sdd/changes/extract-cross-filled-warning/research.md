# Research: local_extract: aviso de valor cruzado entre claves (cross_filled_keys, #650)

## Current behavior

- `local_extract` (`src/local_delegate/server.py`, cola de la función, tras normalizar claves,
  marcadores «sin datos» y prefijos de línea) arma `_local_delegate` con avisos acumulados en
  `late_notices`; no hay ningún control de valor cruzado.
- El intento del 2026-11-10 (`.sdd/changes/extract-cross-fill-and-routing/`): `detector.py`
  (variantes `strict`, `loose`, `partial`), `holdout/` (24 casos a ciegas con respuesta correcta y
  cruzada a mano), `cases/` (19 entradas) y `outputs/evaluation.json` (respuestas reales de
  `gemma3-4b` y `gemma4-26b-a4b` con veredicto a mano). La variante estricta falló la puerta con un
  aviso en falso (`c01/price`, `verification.md` «Veredicto»).

## Medición del diseño nuevo (antes de escribir la spec)

Regla: valor no trivial; toca celdas de UNA sola fila etiquetada; cada celda tocada aparece una
sola vez en el texto de la entrada; la etiqueta (más la cabecera de columna) casa con otra clave
pedida en más palabras que con la propia.

| Conjunto | Avisos en falso | Cruces detectados | Cruces sin aviso |
| --- | --- | --- | --- |
| `holdout` respuestas correctas (24) | 0 | — | — |
| `holdout` respuestas cruzadas (49 claves cruzadas) | 0 | 31 | 18 |
| Respuestas reales grabadas (58 caso-corrida, 12 claves cruzadas) | 0 | 5 | 7 |
| Conjunto nuevo (25 tablas, 50 respuestas) | 0 | 33 | 24 |

Tras la revisión de resultado (dos jueces y seguridad) el detector se endureció: coincidencia
estricta (celda con o sin unidad, o valor hecho solo de celdas de la fila), la otra clave tiene que
casar de verdad (dos palabras, o una si una contiene a la otra), campos de ubicación fuera,
robustez ante entradas raras. Se
añadieron 7 casos (n26-n32) con los falsos positivos que propusieron los jueces. Cifras finales:

| Conjunto | Avisos en falso | Cruces detectados | Cruces sin aviso |
| --- | --- | --- | --- |
| `holdout` respuestas correctas (24) | 0 | — | — |
| `holdout` respuestas cruzadas (49 claves cruzadas) | 0 | 30 | 19 |
| Respuestas reales grabadas (58, 12 claves cruzadas) | 0 | 5 | 7 |
| Conjunto nuevo (32 tablas, 63 respuestas) | 0 | 37 | 25 |

Los cruces del #586 (`01-pricing-table-en/licensed_user_limits` y
`06-limits-table-es/limite_usuarios_con_licencia`) se detectan en las dos corridas que los tienen.
El estricto de ayer detectaba 27 de los 49 del `holdout`; el nuevo, 31, sin el falso positivo.

Los cruces sin aviso son, por diseño: valor repetido en dos filas (c19, c21, `12-capabilities`),
fila de una clave no pedida (`02-pricing`, `21-near-miss`), empate de palabras (tablas
traspuestas, `North`/`South`), etiquetas en otro idioma que la clave.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `src/local_delegate/cross_fill.py` | no existe | detector nuevo, solo biblioteca estándar | este cambio |
| `src/local_delegate/server.py` `local_extract` | arma `_local_delegate` | una llamada al detector y un aviso más en `late_notices`; una frase en la descripción | cola de `local_extract` |
| `resources/i18n/{en,es}/mcp.json` | catálogo de avisos | clave `mcp.warning.extract_cross_filled_keys` | `tests/test_i18n_parity.py` |
| `tests/data/cross_fill/` | no existe | conjunto de medición | este cambio |

## Existing conventions

- Avisos tardíos se concatenan a `warning` con `; ` sin pisar el anterior (#455/#497).
- Las claves de detalle van al lado (`placeholder_keys`, `outline_copies`, `section_only_keys`).

## Dependencies and integrations

- Ninguna dependencia nueva (`csv`, `html.parser`, `json`, `re`, `unicodedata`).

## Risks and unknowns

- Hecho: 0 falsos positivos en 132 respuestas medidas. Supuesto: entradas reales con más prosa
  podrían repetir valores (eso silencia, no da falso positivo) o tener etiquetas que casen por
  casualidad con otra clave (riesgo residual; el aviso no cambia el valor).
- Coste: un recorrido lineal de la entrada; tope de 400 000 caracteres.
