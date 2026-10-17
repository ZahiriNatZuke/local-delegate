# B2d-4: resultado de la medición en vivo (2026-10-17)

Método y criterio fijados antes de medir: `measure.md`. Código medido: `ea5b27a` (rama
`sdd/english-names-b2d-4`). Además, el paso 1b de `main` (`5a5a7c0`) se **re-midió** en la misma
sesión con el mismo método, desde un árbol aparte (`D:/Projects/ld-wt-b2d4-main`), para tener una
base del mismo día. 30 respuestas por versión, 0 errores, ventanas cerradas:

| Versión | Ventana A | Ventana B | Carpeta |
|---|---|---|---|
| compactado (`ea5b27a`) | `w-20261017T221618Z` | `w-20261017T221834Z` | `runs/compact/` |
| 1b re-medido (`5a5a7c0`) | `w-20261017T222234Z` | `w-20261017T222436Z` | `runs/main-remeasure/` |

La base y el 1b de B2d-3 se re-contaron con el contador de esta rama (`runs/rescore-*.json`): dan
lo mismo que con el de B2d-3 (9, 20, 6 y 2, 5, 4), porque ninguna de sus respuestas escribía el N
de un bloque.

## Tabla

| Versión | `fidelity_totals` | Media | `parenthesized_invented` | Controles (2 de 3) | Cortadas / 30 |
|---|---|---|---|---|---|
| base (B2d-3, `7a17941`) | 9, 20, 6 | 11,67 | 0, 11, 0 | A15, B31, B32 | 0 |
| 1b (B2d-3, `20faa5e`) | 2, 5, 4 | 3,67 | 0, 0, 0 | A14, A15, B31, B32 | 3 (B35) |
| 1b re-medido hoy (`5a5a7c0`) | 5, 5, 6 | 5,33 | 0, 0, 0 | A14, A15, B31 (B32 1/3) | **3 (B35)** |
| **compactado (`ea5b27a`)** | **20, 5, 5** | **10,0** | 0, 0, 0 | A14, A15, B31, B32 (todos 3/3) | **0** |

Cortadas: `runs/score-log.json` (compactado: `gemma3-4b` 21 y 0, `gemma4-26b-a4b` 9 y 0) y
`runs/main-remeasure/score-log.json` (`gemma4-26b-a4b` 9 y 3: B35 otra vez, `chars_out` 1794).
`identical_in_every_repetition`: compactado `[]`; 1b re-medido `['A15', 'B35']`.

Por llamada (r1, r2, r3):

| Caso | 1b re-medido | compactado | Qué entra en el compactado |
|---|---|---|---|
| A12 (compactado: 11 → 3 + «y 8 más») | 1, 0, 0 | 1, 2, 2 | «6 instances», «5»: el modelo cuenta las líneas que ve en vez de copiar el total |
| A13 (intacto) | 2, 2, 2 | **13**, 0, 0 | r1: «0 issues» trece veces en el informe de `doctor` |
| A15 (intacto) | 0, 0, 0 | 1, 1, 1 | la misma línea de D103 repetida |
| B31 (intacto) | 0, 0, 0 | 2, 2, 2 | «41» y «16»: **cifras reales** (41 tests de `test_chunking.py` y 16 de `test_density.py`, suman los 57 del total); el contador no las ve porque el log nombra cada test dos veces |
| B32 (intacto) | 0, 2, 2 | 0, 0, 0 | |
| B33 (intacto) | 2, 1, 2 | 3, 0, 0 | |
| B35 (compactado: 89 → 12) | 0, 0, 0 (cortado ×3) | 0, 0, 0 | |

## Veredicto contra el criterio

| Criterio | Compactado | ¿Cumple? |
|---|---|---|
| 0 cortadas en 30 | 0 | **sí** (el 1b, hoy: 3) |
| Media ≤ 11,67 | 10,0 | sí |
| Media ≤ 4,0 | 10,0 | **no** |
| `parenthesized_invented` = 0 | 0, 0, 0 | sí |
| Controles ⊇ A15, B31, B32 | A14, A15, B31, B32 | sí |

**No cumple el criterio: no se adopta tal cual.** No se maquilla: la media es 10,0 con el contador
de la medición. Lo que se ve al mirar dentro (sin cambiar el veredicto):

- El objetivo del lote sí se logra: B35 deja de cortarse (0 de 3, frente a 3 de 3 del 1b hoy) y su
  fidelidad es 0 en las 3 repeticiones.
- 13 de los 30 puntos son un solo caso intacto (A13 r1, «0 issues» ×13), el mismo modo de fallo
  que la base tuvo en su r2 (11). 6 son cifras reales que el contador no reconoce (B31).
  Descontando la revisión a mano de B31: 18, 3, 3 (media 8,0).
- Una regresión sí es del cambio: A12, el otro log que se compacta, pasa de 1, 0, 0 a 1, 2, 2. El
  modelo cuenta las líneas que ve («6 instances») en lugar de usar la cifra del marcador.
- El umbral de 4,0 tampoco lo pasa hoy el 1b (5,33, con B32 perdido): la variación entre sesiones
  es del tamaño del margen.

## Siguiente candidato (propuesto, no medido)

1. **El marcador da también el total del bloque**: «… y 8 líneas más como las anteriores (11 en
   total)», para que el modelo tenga una cifra del programa que copiar en vez de contar (A12). El
   contador ya acepta el tamaño del bloque.
2. **Sin la frase nueva en la regla de la cantidad**: el marcador ya es «la cifra que el contenido
   escribe», que la regla del 1b cubre. Menos prompt, menos efecto en los logs que no se compactan
   (A13, A15).
3. **Medir contra el 1b re-medido en la misma sesión** y revisar el criterio de 4,0 con el usuario:
   hoy el propio 1b lo incumple. Y en el contador, los recuentos por fichero de pytest (líneas
   distintas por fichero), para que B31 no cuente cifras reales como inventadas.

---

# Segunda ronda (2026-10-17): marcador con el total y la regla del 1b

Decisión del usuario y criterio nuevo, escritos antes de medir: `../../plan.md` (B2d-4, «Segunda
ronda») y `measure.md` («Segunda ronda»). Código medido: `6408477` (marcador «… y N líneas más
como las anteriores (M en total)», `_lint_count_clause()` igual a la del 1b). `main` (`5a5a7c0`)
medido en la misma sesión justo antes, desde `D:/Projects/ld-wt-b2d4-main` (ya borrado). 30
respuestas por versión, 0 errores, ventanas cerradas:

| Versión | Ventana A | Ventana B | Carpeta |
|---|---|---|---|
| `main` (`5a5a7c0`) | `w-20261017T225007Z` | `w-20261017T225239Z` | `runs/round2-main/` |
| nueva (`6408477`) | `w-20261017T225548Z` | `w-20261017T225817Z` | `runs/round2-new/` |

Contador nuevo: el que reconoce los tests por fichero de pytest, validado a mano antes de usarlo
(`counter-validation.md`: 14 de 18 frente a 10 de 18; control negativo 8 de 9 en los dos).

## Tabla

| Versión | `fidelity_totals` (nuevo) | Media (nuevo) | Media (viejo) | `parenthesized_invented` | Controles | Cortadas / 30 |
|---|---|---|---|---|---|---|
| `main`, esta sesión | 6, 6, 5 | **5,67** | 6,33 (8, 6, 5) | 0, 0, 0 | A14, A15, B31 3/3; B32 2/3 | **2 (B35)** |
| **nueva** | **11, 6, 7** | **8,0** | 10,0 (13, 8, 9) | 0, 0, 0 | A14, A15, B31, B32 3/3 | **0** |

Ficheros: `runs/round2-*/score-answers.json` (contador nuevo), `runs/round2-per-call.txt` (por
llamada, nuevo y viejo), `runs/controls-round2.json`, `runs/round2-*/score-log.json` (cortadas:
`main`, `gemma4-26b-a4b` 9 llamadas y 2 `length`, las dos en B35 con `chars_out` 1709; nueva, 0).
`identical_in_every_repetition`: `[]` en las dos.

## Veredicto contra el criterio de la segunda ronda

| Criterio | Nueva | ¿Cumple? |
|---|---|---|
| 0 cortadas en 30 | 0 (`main`: 2) | sí |
| Media no peor que la de `main` de esta sesión | 8,0 frente a 5,67 (viejo: 10,0 frente a 6,33) | **no** |
| Media ≤ 11,67 | 8,0 | sí |
| `parenthesized_invented` = 0 | 0, 0, 0 | sí |
| Controles ⊇ A15, B31, B32 | A14, A15, B31, B32 (3/3) | sí |

**No cumple el criterio: no se adopta.** La evidencia queda en la rama. Lo que se ve al mirar
dentro (no cambia el veredicto):

- **8 de las 10 llamadas mandan el mismo prompt en las dos versiones**, byte a byte (`system` y
  contenido: `runs/round2-same-prompt.json`, de `same_prompt_check.py`). El cambio solo toca A12 y
  B35, los dos logs que se compactan. En esas 8, cualquier diferencia es ruido del modelo.
- En esas 8, la nueva suma 22 puntos y `main` 13; casi todo es A13 («0» por cada chequeo sano del
  informe de `doctor`): 9, 3, 4 frente a 3, 2, 1, con el mismo prompt. Ese ruido (9 puntos) es
  mayor que toda la diferencia entre versiones (24 frente a 17).
- En las 2 llamadas que el cambio toca: la nueva suma 2 (A12 0, 1, 1; B35 0, 0, 0) y `main` 4
  (A12 2, 2, 0; B35 0, 0, 0 pero **cortada 2 de 3**). Los 2 de la nueva son el mismo falso positivo
  del contador: `scripts/build\_corpus.py` (el `_` escapado en Markdown no casa con el log). Las
  respuestas copian las cifras del marcador (A12 «11 lines», B35 «45» y «40»), que es lo que
  buscaba la ronda.
- Con n = 3 y este ruido, el criterio «no peor que `main`» compara sobre todo el azar de A13. No
  se maquilla: el criterio fijado no se cumple.

## Propuesta (no medida; decide el usuario)

1. **Comparar donde el cambio actúa:** criterio de fidelidad sobre las llamadas cuyo prompt
   cambia (aquí A12 y B35), y las demás como control de ruido (deben quedar dentro de su
   variación). Hay que fijarlo antes de otra medición.
2. **O más repeticiones** (p. ej. `--repeat 10`) para que el ruido de A13 no decida.
3. **Contador:** quedan tres falsos positivos vistos en la validación (posiciones de `tsc` como
   `(52,24)`, versiones como `v255`) y uno nuevo aquí (`build\_corpus.py` con el `_` escapado).
   Arreglarlos pide su propia validación a mano, no ajustarlos a la vista de esta medición.
