# Afinidad de `local_lint_summary` por idioma — medición en vivo (2026-10-19, UTC)

Plan y criterio, escritos antes de medir: `plan.md`. Candidato: `ce96766` (el rol mecánico recibe el
inventario con recuentos de la ola lint-counts), instalado en el daemon con
`uv tool install --force --reinstall --no-cache` y comprobado con `diff`.

## Cómo se midió

- Afinidad: `measure.ps1` + `batch.sh` (copias de las de B2-affinity para este árbol, por
  `pesado.sh`), `B2-affinity/run_affinity_live.py --repeat 3` con resultados en
  `benchmarks/afinidad-2026-10/reevaluation-lint-counts/results/`. Seis ventanas de prueba, una por
  (modelo, idioma), 03:05–03:12: `w-20261019T030522Z`, `w-20261019T030559Z`,
  `w-20261019T030634Z` (es: 4B, 2B, 26B) y `w-20261019T030857Z`, `w-20261019T030937Z`,
  `w-20261019T031006Z` (en). Cada ventana: 1 llamada de calentamiento + 12; 0 líneas ajenas, 0
  problemas (`logs/`). RAM mínima durante las ventanas: 3,2 GB (26B), umbral 1,5 GB.
- Veredicto: `B2-affinity/evaluate_reevaluation.py --scorer v2` (la v3) →
  `reevaluation-lint-counts/verdict.json` y `verdict.md` (aquí). El campo `method` del veredicto
  conserva el texto de B2-affinity porque el script es el mismo, sin tocar.
- No-regresión del 4B en producción: ventanas M/ME de `lint-counts` con este candidato
  (`w-20261019T031325Z`, `w-20261019T031423Z`), `lint-counts/score-c2.json`.
- Al final, launcher restaurado (sha256 `c96f022a…`, `match=True`).

## Resultado

| Celda | Rep. 1 | Rep. 2 | Rep. 3 | Veredicto |
|---|---|---|---|---|
| lint → 26B, `es` | approved | approved | approved | **aprobada** |
| lint → 26B, `en` | approved | approved | approved | **aprobada** |

Calidad por caso (rol / 2B / 26B), detalle en `verdict.md`: en `es` el 26B iguala o supera al 4B en
los 4 casos de las 3 repeticiones (docstrings y un-solo-archivo 1,00 frente a 0,75 y 0,67); en `en`,
1,00 en los 4 casos de las 3. Latencia mediana del 26B 3,9–4,1 s (`es`) y 3,0–3,2 s (`en`), dentro
del criterio de latencia en todas. En B2-affinity, con el prompt mecánico sin inventario, el 26B en
`es` sacaba 0 en 3 de 4 casos por no nombrar ni un código.

**Revisión a mano** (repetición 3, `es`, tres-reglas y cinco-reglas): el 26B da todas las cifras
por fichero bien, con su código («**E501**: Dos líneas…», «SIM102: 3 veces…»); el 4B copia el total
del log bajo un fichero (F401 3 en `app/util.py`, que tiene 2; UP006 4 en `lib/io.py`, que tiene 2)
y pone «W291: 0». El sentido rol/26B que da la v3 coincide con la lectura a mano.

## No-regresión del 4B (M/ME, rol mecánico, 6 logs × 3)

| Grupo | Versión | Códigos | Ficheros | Invenciones por resp. | Cortadas | Respuestas con cifras mal (informativo) |
|---|---|---|---|---|---|---|
| M `es` | lint-counts (c1b, prompt mecánico de `main`) | 0,91 | 1,00 | 0,94 | 0 | 6 de 18 |
| | este candidato | **1,00** | 1,00 | 0,83 | 0 | **12 de 18** |
| ME `en` | c1b | 0,91 | 0,98 | 0,50 | 0 | 10 de 18 |
| | este candidato | **1,00** | 0,99 | 0,44 | 0 | 10 de 18 |

Criterio 2 (`codes`/`files` ≥ c1b − 0,05, invenciones ≤ c1b + 0,15, cortadas ≤ c1b + 1): **cumple**
en los dos idiomas. Ruido del día en M con el mismo prompt (`main`/c1/c1b): 0,50–1,33 invenciones y
0–2 cortadas.

**Señal que no es criterio y que hay que vigilar:** en español el 4B tiene más respuestas con alguna
cifra mal (6 → 12 de 18) y en el corpus de afinidad su nota baja (media 0,79 en B2-affinity →
0,67 aquí; en inglés sube de 0,74 a 0,88). Leído a mano, es el mismo patrón de arriba: copia el
total del log (que el inventario da para todo el log) en la entrada de un fichero. El inventario
dice «en todo el log», pero el 4B en español no lo respeta siempre. Va al backlog con la palanca
obvia: recuento por fichero cuando el formato lo permite (ruff concise, tsc: los logs cortos del rol
mecánico suelen serlo), o sin cifras en la llamada mecánica cuando el log nombra más de un fichero.

## Veredicto

**Llega en los dos idiomas a la primera iteración.** Se adopta: el rol mecánico recibe el
inventario, y `matrix.CELLS` vuelve a tener la celda de lint, una por idioma (campo `language`),
con la huella del prompt de cada idioma (`0b070d5d…` en `es`, `2c9a0a31…` en `en`). La celda del
otro idioma ni enruta ni hace avisar a `doctor`. Con la config real de llama-swap,
`_approved_alternatives('local_lint_summary', 'mechanical', 'gemma3-4b', …)` da el 26B en `es` y en
`en`, y `doctor` (sonda de residencia) sale OK sin aviso de afinidad en los dos.

## El puntuador

La v3 se queda en la evidencia y no pasa a `analyze_benchmark.py` (razón en `plan.md`): tiene otro
fallo de lectura conocido (cifra delante del código en frases con varios códigos), arreglado solo en
`lint-counts/score_counts.py`, y llevarla al producto exige re-puntuar T6 con revisión a mano.
