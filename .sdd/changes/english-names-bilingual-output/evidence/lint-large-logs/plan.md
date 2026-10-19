# Ola lint-large-logs — logs muy grandes y cifras por fichero del rol mecánico (2026-10-19)

Escrito ANTES de cualquier llamada de medición. Backlog del vault §1.8 (logs grandes) y la señal
de `evidence/affinity-by-language/live.md` (cifras por fichero del 4B en español).

## Problemas

1. **Logs de más de ~150 000 caracteres (lint troceado, rol `long`, `gemma4-26b-a4b`).** El paso
   final pide una entrada por fichero; con 50–130 ficheros escribe 6–8 k caracteres y acaba en
   `length`, y 2–5 `map` por llamada se cortan con su tope (696). En L3 (`pytest --collect-only`)
   inventa recuentos de tests por fichero (`B2e/live.md`).
2. **Rol mecánico en español (`gemma3-4b`) con varios ficheros.** El inventario da el total de cada
   código en todo el log, y el 4B lo copia bajo un solo fichero («F401: 3» en `app/util.py`, que
   tiene 2) o pone «W291: 0» en un fichero sin W291. Respuestas con alguna cifra mal: 6 → 12 de 18
   (`affinity-by-language/live.md`, lector laxo de `lint-counts`).

## Conjunto (congelado por `build_set.py` antes de medir)

- **X** (cambia el prompt; problema 1; `es`, troceado del rol largo, `LOCAL_DELEGATE_FALLBACK_LONG=none`):
  - X1 `B2e/docs/L1-ruff-select-all-src.txt` — ruff concise `--select ALL`, real, 180 k, 54 ficheros, 95 códigos.
  - X2 `B2e/docs/L3-pytest-collect-only.txt` — pytest `--collect-only`, real, 207 k, 109 ficheros.
  - X3 `docs/N1-eslint-stylish.txt` — eslint stylish, sintético realista (`gen_synthetic.py`), 137 k, 128 ficheros.
  - X4 `docs/N2-tsc.txt` — tsc, sintético realista, 115 k, 91 ficheros, 11 códigos.
- **M / ME** (cambia el prompt; problema 2): los 6 logs pequeños de `lint-counts` con el rol mecánico,
  `es` y `en` (todos tienen formato contable: ruff concise, ruff completo, tsc).
- **G** (prompt idéntico en todas las versiones: control de ruido): los 5 logs de 8–34 k de
  `lint-counts` en llamada única del rol largo, `es`. Ningún cambio de esta ola toca esa llamada.

Sin `en` en X: el troceado no depende del idioma salvo en la orden de idioma, y cada versión cuesta
~40 min de GPU. Queda dicho como límite.

## Puntuación (`score_large.py`, fijada antes de medir)

- `codes` / `files` / `model_codes` / `model_files` / `fidelity_total` / `finish_reason` /
  `chunks` / `model`: las de `B2f/score_b2f.py` (sus funciones; contador de fidelidad `new`).
- **Cifras por fichero (`per_file_wrong`)**, lector propio e independiente del producto: la verdad
  por fichero sale de expresiones del set (ruff concise y completo, tsc, eslint stylish, nodos de
  pytest), no de `lint_patterns`. En la respuesta del modelo (sin la línea del programa ni avisos),
  una línea que nombra un solo fichero de la verdad abre su sección, y una línea de título sin
  fichero la cierra. Dentro de la sección de F, una cifra pegada a un código (`E501: 3`,
  `E501 (3)`, `3 E501`, `E501 — 3 veces`) tiene que ser la del código en F (si F no tiene ese
  código, cualquier cifra está mal, también 0), y una cifra con palabra de recuento («3 errores»,
  «57 tests») tiene que ser el total de F o la de uno de sus códigos. Los números de línea y las
  coordenadas no cuentan. Fuera de secciones, una cifra pegada a un código vale si es su total o
  la de algún fichero. Se informa: respuestas con alguna cifra mal y cifras mal en total.
- `fidelity_total` se cuenta sin la línea «Y otros N ficheros» que añade el programa (su cifra es del
  programa, no del modelo); en la base no existe y no cambia nada.
- Latencia: `latency_ms` de la fila del log de uso.
- Validación del lector ANTES de medir: sobre las respuestas M de `lint-counts/runs/c2` y `c1b`,
  contra una lectura a mano de 4 respuestas (control positivo: M1-r3 y M3-r3 de c2 tienen 3 y ≥ 5
  cifras mal a mano).

## Criterio (fijado antes de medir)

Base: la rama de partida (`feat/lint-counts-by-program`, `b604969`) instalada en el daemon, medida
en esta sesión con el mismo método, `--repeat 3`.

**Problema 1 (X, 12 respuestas):**
1a. Cortadas (alguna llamada en `length`): 0 de 12.
1b. Invenciones por respuesta ≤ 0,25 y no por encima de la base.
1c. Respuestas con alguna cifra por fichero mal: ≤ 1 de 12.
1d. `codes` y `files` (con la línea del programa) ≥ 0,9; `model_files` ≥ 0,7; `model_codes` no por
    debajo de la base − 0,05.
1e. Latencia mediana no por encima de 1,25 × la de la base.

**Problema 2 (M, 18 respuestas `es`):**
2a. Respuestas con alguna cifra por fichero mal: ≤ 3 de 18 y por debajo de la base.
2b. ME (`en`) no peor que su base en esa misma cifra.
2c. Sin regresión en M y ME: `codes`/`files` ≥ base − 0,05; invenciones por respuesta ≤ base + ruido;
    cortadas ≤ base + 1.

**Ruido:** la diferencia de invenciones por respuesta y de cortadas en G entre versiones. Una
diferencia en X o M menor que la de G no cuenta.

Las respuestas de M servidas por otro modelo que `gemma3-4b` (afinidad hacia el 26B si estaba
cargado) se cuentan aparte.

Si no llega en 2 iteraciones: tocar una vez límites (tope de ficheros, topes de tokens) y, si no,
documentar el límite y el texto del backlog.

## Diseño de la iteración 1 (decidido antes de medir; las alternativas, en el informe)

- Problema 1: salida acotada por programa en vez de topes más altos. El paso final (y cada `map`)
  da una entrada solo para los N ficheros más nombrados del inventario (N = 10, el mismo de la línea
  «Sin mencionar»), y el programa añade «y otros M ficheros» contado por él. Cuando el formato es
  contable, el inventario del paso final lleva el total de cada fichero; cuando no lo es, se
  prohíben las cifras por fichero.
- Problema 2: en la llamada mecánica, cuando el log es de un formato contable y nombra más de un
  fichero, el inventario da los recuentos POR FICHERO (contados por el programa) en lugar del total
  de cada código en todo el log.
