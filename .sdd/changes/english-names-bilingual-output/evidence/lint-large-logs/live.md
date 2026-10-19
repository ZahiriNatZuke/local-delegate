# Ola lint-large-logs — medición en vivo (2026-10-19, UTC)

Método, conjunto y criterio: `plan.md`, escritos antes de medir. Kit: `gen_synthetic.py` (eslint y
tsc sintéticos), `build_set.py` → `manifest.json`/`set.json`; `measure.ps1` + `batch.sh` (por
`pesado.sh`, una ventana de prueba por ventana y versión); `run_live.py --repeat 3` (las respuestas
no pasan por ningún contexto); `score_large.py` → `score-<tag>.json`. Lector de cifras por fichero
validado antes contra la lectura a mano (`lint-counts/runs/c2` M1-r3 y M3-r3, 3 y 8 cifras mal; y
`c1b` H1, H3, H6 sin cifras mal y H2 con 5 bien detectadas). Una corrección tras la iteración 2
(línea copiada tal cual del log), aplicada igual a todas las versiones (`plan.md`).

## Versiones (misma sesión, mismo método)

SHA de antes del rebase sobre `main` (tras mezclarse #331); en la rama publicada: `13daae6` → `87a86cd`,
`22c4b12` → `257bcd6`, `34dde55` → `65ba241`.

| Tag | Código | Ventanas (M, ME, G, X) |
|---|---|---|
| `base` | `b604969` (rama de #331) | `w-20261019T112408Z`, `…112511Z`, `…112624Z`, `…113711Z` |
| `it1` | `13daae6` | `w-20261019T121802Z`, `…121917Z`, `…122018Z`, `…122710Z` |
| `it2` | `22c4b12` | `w-20261019T130817Z`, `…130921Z`, `…131019Z`, `…131634Z` |
| `it3` | `34dde55` (paso de límites) | `w-20261019T135029Z`, `…135132Z`, `…135234Z`, `…135849Z` |

Cada versión, instalada en el daemon con `uv tool install --force --reinstall --no-cache` (daemon
parado antes) y comprobada con `diff` del `server.py` instalado. 0 errores de la tool. Todas las
respuestas de X y G del 26B; todas las de M/ME del 4B.

## Problema 1: logs grandes (X, 4 logs × 3, `es`)

| | base | it1 | it2 | it3 |
|---|---|---|---|---|
| Cortadas (alguna llamada en `length`) | 12 | 12 | 12 | **10** |
| `map` cortados / 66 | 38 | 42 | 25 | 15 |
| Pasos finales cortados / 12 | 7 | 4 | 2 | **0** |
| Invenciones por respuesta | 2,17 | 0,25 | 0,25 | 0,33 |
| Respuestas con cifras por fichero mal | 8 | 1 | 1 | 1 |
| Cifras por fichero mal (total) | 130 | 9 | 3 | 7 |
| `model_codes` / `model_files` | 0,47 / 0,73 | 1,00 / 1,00 | 1,00 / 1,00 | 1,00 / 1,00 |
| Latencia mediana (s) | 189 | 180 | 126 | 152 |
| Caracteres de la respuesta (mediana) | 6 907 | 4 487 | 3 696 | 4 148 |

Control G (prompt idéntico en las cuatro): invenciones 0,13 / 0,07 / 0,27 / 0,33; cortadas 0 en todas;
cifras por fichero mal 6 de 15 en todas. La diferencia de invenciones entre it2 e it3 en X (0,08) es
menor que el movimiento de G: no cuenta.

**Contra el criterio:** 1b (≤ 0,25 y ≤ base) roza en it3 (0,33, dentro del ruido de G); 1c, 1d y 1e
cumplen desde it1; **1a no llega en ninguna versión.** Lo que queda cortado son los `map`: con su tope
de base escriben una entrada por fichero aunque se les dé la lista de los diez que van; con formato
escueto bajan; con el doble de tope escriben más (un `map` de pytest llega a 10 449 caracteres y se
corta igual). La obediencia al «solo estos ficheros» del `map` no viene de la prosa.

## Problema 2: rol mecánico con varios ficheros (M `es`, ME `en`, 6 logs × 3)

| | base | it1 | it2 | it3 (= base) |
|---|---|---|---|---|
| M: respuestas con cifras por fichero mal | 9 | 8 | 6 | 10 |
| M: cifras mal | 36 | 18 | 15 | 38 |
| ME: respuestas con cifras mal | 4 | 4 | 1 | 4 |
| M / ME `model_codes` | 1,00 / 0,99 | 1,00 / 0,98 | 0,94 / **0,83** | 1,00 / 0,99 |
| M / ME invenciones por respuesta | 0,94 / 0,39 | 0,78 / 0,83 | 0,78 / **1,17** | 0,78 / 0,50 |

it1 (recuentos por fichero en el inventario): el 4B los copia mal (D103 3 donde la lista dice 2). it2
(códigos sin cifras y el recuento por fichero añadido por el programa): el 4B sigue escribiendo cifras
en M2 (mal, y contradicen el bloque del programa) y en inglés deja de nombrar los códigos de M1. Ninguna
llega a ≤ 3 de 18; it2 retrocede en `en`. it3 vuelve a la llamada de la base y repite su nivel (10 y 4
de 18): control de que el resto de la rama no toca el rol mecánico.

## Veredicto

- **Problema 1: no llega (1a).** Se adopta igualmente it3 (`34dde55`), por ser mucho más útil que la
  base en todo lo demás: el resumen que lee el usuario ya no se corta nunca (pasos finales 7 → 0 de
  12), las cifras por fichero mal bajan de 130 a 7, las invenciones de 2,17 a 0,33, nombra todos los
  códigos y ficheros principales y tarda menos (189 → 152 s). Lo que se pierde en los `map` cortados
  lo cubre el inventario del programa. Límite y propuesta, en el texto del backlog del informe.
- **Problema 2: no llega; no se adopta.** La llamada mecánica queda como en la base.
