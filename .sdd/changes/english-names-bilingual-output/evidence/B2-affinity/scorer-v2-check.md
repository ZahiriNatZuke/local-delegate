# B2-affinity — revisión a mano del puntuador de lint (v2 → v3)

Revisión del agente (no humana), 2026-10-18. Semántica de T6 que se conserva: una regla cuadra si
la respuesta la nombra por su código y todas las cifras que le atribuye están entre las válidas (el
total, los archivos que la tienen o lo que suma en alguno). Se juzga con esa semántica, no con una
más estricta: una cifra por fichero equivocada pero que coincide con el total no se castiga, ni en
T6 ni aquí.

Salidas: `scorer-v2-check-v2.txt` (v2) y `scorer-v3-check.txt` (v3, la última, con el arreglo de la
lista de líneas).

## Control 1 — referencias

`reference_ok` = 1,0 con formato y `reference_bad` < 1 en los 4 casos, con v1 y con v3. **Pasa.**

## Control 2 — respuestas congeladas de T6 (16 filas de lint)

La v2 cambiaba 8 notas; la v3, 7. Las 7, leídas a mano, dan la razón a la v3:

| Modelo | Caso | v1 | v3 | A mano | Por qué falla la v1 |
| --- | --- | --- | --- | --- | --- |
| gemma3-4b | tres-reglas | 0,33 | 1,00 | 1,00 | cuenta «líneas 12 y 40», «línea 55» |
| gemma3-4b | cinco-reglas | 0,00 | 0,25 | 0,25 | «2 problemas (I001)»: la cifra va delante |
| qwen35-2b | tres-reglas | 0,33 | 1,00 | 1,00 | números de línea |
| qwen35-2b | un-solo-archivo | 0,67 | 1,00 | 1,00 | «Las líneas 4-7» |
| qwen36-35b-a3b | tres-reglas | 0,00 | 1,00 | 1,00 | números de línea en cada fila |
| qwen36-35b-a3b | un-solo-archivo | 0,00 | 1,00 | 1,00 | «(líneas 4, 5, 6, 7)» |
| qwen36-35b-a3b | cinco-reglas | 0,00 | 1,00 | 1,00 | «en líneas 12, 44, 80» |

La octava diferencia de la v2 (qwen35-2b, cinco-reglas: 0,75 → 0,50) era error de la v2: «en lugar
de **un** solo bloque» contado como 1 para SIM102. La v3 quita `un`/`una`. **Pasa** (7 de 7).

Consecuencia fuera de este lote: las dos respuestas de `qwen36-35b-a3b` que tumbaron su celda de lint
en T6 por calidad (tres-reglas y un-solo-archivo) eran correctas; el puntuador leía los números de
línea. Esa celda también fallaba por latencia (6 272 ms frente a 4 865). Nota de backlog.

## Control 3 — repetición 1 de la primera tanda (16 respuestas)

| Idioma | Modelo | Caso | v3 (reglas mal) | A mano | ¿Coincide? |
| --- | --- | --- | --- | --- | --- |
| es | 4B | tres-reglas | — | — | sí |
| es | 4B | docstrings | D103 | D103 | sí |
| es | 4B | un-solo-archivo | E711 | — («un error de tipo E711» es 1) | **no** |
| es | 4B | cinco-reglas | — | — | sí |
| es | 26B | tres-reglas | todas | todas (no nombra ningún código) | sí |
| es | 26B | docstrings | todas | todas (no nombra ningún código) | sí |
| es | 26B | un-solo-archivo | — | — | sí |
| es | 26B | cinco-reglas | todas | todas (no nombra ningún código) | sí |
| en | 4B | tres-reglas | — | — | sí |
| en | 4B | docstrings | D103 | D100, D103 («three … (D100)» y «four … (D100)»: la v3 le atribuye el «one» de D103) | **no** |
| en | 4B | un-solo-archivo | E501 | E501 («two lines») | sí (tras arreglar la lista de líneas) |
| en | 4B | cinco-reglas | — | — | sí |
| en | 26B | los 4 | — | — | sí (4 de 4) |

**14 de 16: no llega al 15 de 16 fijado.** Los dos desacuerdos son del rol, en prosa con la cifra
fuera de su sitio, y van en sentidos contrarios (uno de menos, uno de más). Ninguno cambia el sentido
de la comparación rol/26B de su caso: en `es` el 26B queda por debajo en tres-reglas, docstrings y
cinco-reglas con las dos lecturas; en `en`, el 26B saca 1,00 en los cuatro con las dos.

Arreglo hecho durante la revisión (implementación, no regla nueva): la regla 2 («fuera `línea(s)`
seguidos de una lista de enteros») no se comía el final «, and 7» de «lines 4, 5, 6, and 7»; ahora
sí. Sin él había un tercer desacuerdo (en, 4B, un-solo-archivo).

Decisión escrita en el plan antes de la segunda tanda: la v3 puntúa, y en cada (idioma, caso,
repetición) se revisa a mano el **sentido** de la comparación rol/26B; donde no coincida, manda la
revisión a mano y se anota.
