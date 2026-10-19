# Ola lint-counts — medición en vivo (2026-10-19, UTC)

Método, conjunto y criterio: `plan.md`, escritos antes de medir. Kit: `build_set.py` →
`manifest.json`/`set.json`; `measure.ps1` + `batch.sh` (por `pesado.sh`, una ventana de prueba por
ventana y versión); `run_live.py --repeat 3` (las respuestas no pasan por ningún contexto);
puntuación `score_counts.py` → `score-<tag>.json`. Lector de cifras validado antes contra la
revisión a mano de la 0.36.0: `count-scorer-check.md`.

## Versiones (misma sesión, mismo método)

| Tag | Código | Ventanas | Ventanas de prueba |
|---|---|---|---|
| `main` | 0.36.0 instalada (`b8ede29`) | 01:46–02:10 | `w-20261019T014629Z` … `w-20261019T020925Z` (8) |
| `c1` | `f5ea72c` (recuentos en el inventario) | 02:15–02:36 | `w-20261019T021500Z` … `w-20261019T023516Z` (8) |
| `c1b` | `616fac5` (c1 + «nombra cada regla por su código») | 02:40–03:01 | `w-20261019T024021Z` … `w-20261019T030023Z` (8) |

Cada versión instalada en el daemon con `uv tool install --force --reinstall --no-cache` (daemon
parado antes: con él vivo, `uv` no puede borrar `Lib`) y comprobada con `diff` del `server.py`
instalado. 108 respuestas por versión, 0 errores de la tool, ninguna troceada. RAM libre antes de
cada ventana ≥ 4 GB (las que no, se reintentaron a los 60 s).

## Resultado (3 repeticiones; `main` / c1 / c1b)

| Grupo | Códigos del modelo | Invenciones por resp. | Cortadas | Cifras mal (informativo) |
|---|---|---|---|---|
| R, ruff `sections.py` `es` | 1,00 / 1,00 / 1,00 | 0 / 0 / 0 | 0 / 0 / 0 | **6 / 0 / 0** (en 3 / 0 / 0 respuestas) |
| RE, ídem `en` | 1,00 / 1,00 / 1,00 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| G, largo `es` (15) | 0,47 / 0,67 / **1,00** | 0,73 / **10,2** / 0,20 | 0 / **2** / 0 | 36 / 44 / 17 |
| GE, largo `en` (15) | 1,00 / 1,00 / 1,00 | 0,80 / 0,27 / 0,27 | 0 / 0 / 0 | 48 / 25 / 18 |
| H, pequeños al largo `es` (18) | 0,93 / 0,98 / 1,00 | 0,50 / 0,50 / 0,33 | 0 / 0 / 0 | 0 / 3 / 3 |
| HE, ídem `en` (18) | 0,93 / 1,00 / 0,96 | 0,50 / 0,50 / 0,50 | 0 / 0 / 0 | 0 / 0 / 0 |
| M, mecánico `es` (prompt idéntico) | 0,86 / 0,98 / 0,91 | 0,50 / 1,33 / 0,94 | 0 / 2 / 0 | 20 / 20 / 20 |
| ME, mecánico `en` (prompt idéntico) | 0,87 / 0,93 / 0,91 | 0,39 / 0,39 / 0,50 | 0 / 0 / 0 | 21 / 19 / 24 |

`codes` y `files` (con la línea «Sin mencionar» del programa): 1,00 en R–HE en las tres versiones.

Ruido (M/ME, mismo prompt en las tres): hasta 0,83 invenciones por respuesta y 2 cortadas (M5, el
log de 13 códigos, `gemma3-4b`). Las «cifras mal» de G/H son informativas: en G4 (37 códigos, 231
E501) el lector no separa bien cifras por fichero y totales; las 3 de H (c1, c1b) son H6, donde la
respuesta copia el mensaje de tsc «entre 0 y 1 argumentos, pero se recibieron 2» y el lector toma
esos números como cuenta de TS2554 (falso positivo del lector, no del modelo).

## Contra el criterio

| Condición | c1 | c1b |
|---|---|---|
| 1. R y RE: 0 cifras mal en 3 de 3 y 15/15 códigos del modelo | sí | sí |
| 2a. `codes`/`files` de G–HE ≥ `main` − 0,05 | sí | sí |
| 2b. Invenciones G–HE ≤ `main` + ruido | **no** (G 10,2) | sí (todas ≤ `main`) |
| 2c. Cortadas ≤ `main` + 1 | **no** (G 2) | sí (0) |

c1 se descartó al verlo (decisión escrita en `plan.md` antes de medir c1b): G1, un ruff concise
de 8,6 k, entró en bucle en 2 de 3 en español, con las reglas traducidas y sin código («Demasiados
argumentos…: 1» repetido hasta el tope). La única corrección (iteración 2) fue pedir en la misma
frase que cada regla se nombre por su código tal cual: con c1b el modelo del rol largo nombra en
español todos los códigos que antes traducía (0,47 → 1,00 en G) y no hay bucles.

**Veredicto: LLEGA con c1b (`616fac5`).** Se adopta. Sin maquillar: la mejora de las cifras se
midió con un solo log que tuviera verdad exacta en un formato sin ficheros múltiples (R); en los
logs de varios ficheros las cifras mal bajan (G 36 → 17, GE 48 → 18), pero el lector no es fino
ahí y no es criterio.

## Por fichero

No se da (decisión de `plan.md`): solo es barato en formatos con fichero y código en la misma
línea (ruff concise, tsc), no en el formato completo de ruff ni en biome. Queda como idea.
