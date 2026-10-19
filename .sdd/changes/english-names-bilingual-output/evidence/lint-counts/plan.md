# Ola lint-counts — recuentos por programa en la llamada única del rol largo (2026-10-18)

Escrito ANTES de cualquier llamada de medición. Backlog del vault §1.10, punto 1.

## Problema

En la pasada en vivo de la 0.36.0, con el log de `ruff check --select ALL` de `sections.py`
(~14 k caracteres, llamada única del rol largo, `gemma4-26b-a4b`), el resumen en inglés dio las 15
cifras exactas y el español dos mal (D101 6 en vez de 5, D400 4 en vez de 3), con una sola
repetición (`evidence/live-036/tools.md`, fila 7).

## Cambio

El inventario que B2f pone delante del log en la llamada única del rol largo lleva ahora, junto a
cada código, las veces que aparece en todo el log, contadas por el programa
(`lint_patterns.code_counts`), y una frase pide copiar esa cifra en vez de contar. El reduce del
lint troceado y el rol mecánico no cambian (el mecánico, byte a byte).

Por fichero: no se da. Solo es barato en formatos que ponen fichero y código en la misma línea
(ruff concise, tsc); en el formato completo de ruff el fichero va en la línea siguiente, y en
biome en otra. Un recuento por fichero que solo existe en algunos formatos es un segundo camino que
medir; queda anotado.

## Conjunto (congelado por `build_set.py` antes de medir)

- **R / RE** (cambia el prompt): el log de `ruff` de `sections.py` (`docs/ruff-sections.log`,
  regenerado sobre `main` `b8ede29`; 15 códigos de diagnóstico, 30 errores), en `es` y en `en`.
- **G / GE, H / HE** (cambia el prompt): las ventanas de B2f, mismos documentos y sha256 (logs de
  8–34 k en llamada única del rol largo; los 6 pequeños forzados al rol largo).
- **M / ME** (prompt idéntico, control de ruido): los 6 pequeños con el rol mecánico.
- `LOCAL_DELEGATE_FALLBACK_LONG=none` en R, RE, G, GE, H y HE, como en B2f.

## Puntuación (`score_counts.py`, fijada antes de medir)

- `codes` / `files` / `fidelity_total` / `cut`: las de `B2f/score_b2f.py`, mismas funciones.
- **Cifras por código** (`wrong_counts`, `no_count`): para los logs cuyo formato permite contar los
  diagnósticos con una expresión independiente del programa (ruff concise, ruff completo, tsc), la
  verdad es `{total del código} ∪ {recuento del código en cada fichero}`. La lectura de cifras es
  la v3 de `B2-affinity/evaluate_reevaluation.py` (sin números de línea ni coordenadas, número en
  palabras como cifra, por frase), sobre el texto del modelo sin la línea «Sin mencionar» del
  programa. Un código con alguna cifra fuera de la verdad = cifra mal; un código nombrado sin
  cifra = sin cifra.

## Criterio (fijado antes de medir)

Versiones en la misma sesión, mismo método, `--repeat 3`: `main` (la 0.36.0 instalada, `b8ede29`)
y el candidato de esta rama.

1. **R y RE:** 0 cifras mal en las 3 repeticiones de cada idioma, y los 15 códigos de diagnóstico
   nombrados por el modelo en las 3.
2. **Sin regresión en G, GE, H, HE:** `codes` y `files` no por debajo de `main` − 0,05;
   invenciones por respuesta no por encima de `main` + el ruido; cortadas no más que `main` + 1.
3. **Ruido:** la diferencia de invenciones por respuesta en M/ME (prompt idéntico) entre las dos
   versiones. Si M/ME se mueve más que una diferencia en G–HE, esa diferencia no cuenta.
4. Informativo, no criterio: cifras mal en H/HE/G (los logs con verdad calculable).

Si no llega en 2 iteraciones: tocar una vez la redacción o el formato del inventario y, si no,
documentar el límite y el backlog.
