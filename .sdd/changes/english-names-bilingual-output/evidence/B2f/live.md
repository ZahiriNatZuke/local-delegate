# B2f — Medición en vivo (2026-10-18)

Método, criterio y reglas de desvío: `plan.md`, sección «B2f», escritos antes de cada tanda.

## Cómo se midió

- Conjunto congelado antes de medir: `build_set.py` → `b2f-set.json` y `manifest.json` (sha256 de
  cada log; los 10 códigos y ficheros más nombrados, por `lint_patterns`). Dos logs nuevos y reales
  en `docs/`: `ruff check --select ALL` de `src/local_delegate/web/` (concise, 33,8 k) y de
  `benchmark.py` (full, 33,1 k), sobre el código de `main`.
- Ventanas (producto `es` salvo `LOCAL_DELEGATE_LANG=en`): G/GE, logs de 8–34 k en llamada única
  del rol largo; H/HE, los 4 logs del corpus de afinidad, ruff concise de 17 códigos y tsc,
  forzados al rol largo (`LOCAL_DELEGATE_LONG_INPUT_CHARS=100`); M/ME, los mismos con el rol
  mecánico; A/B, el control de B2e. `LOCAL_DELEGATE_FALLBACK_LONG=none` en G, GE, H y HE.
- `~/.claude/relevos/b2f-measure.ps1` y `b2f-batch.sh` por `pesado.sh` desde la tool Bash;
  `run_live.py --repeat 3` (las respuestas no pasan por el contexto); cada ventana en su
  `test-window` (24 ventanas, `w-20261018T072105Z` … `w-20261018T083129Z`, todas cerradas por id y
  con el número exacto de filas: ajenas 0). Puntuación: `score_b2f.py` → `score-<tag>.json`;
  criterio: `compare.py` → `compare-main-<tag>.json`; ruido: `same_prompt_check.py` →
  `same-prompt-check.json` (idénticos: M, ME, A11–A13, A15, B32–B34; 57 llamadas por tanda).
- Versiones, todas en la misma sesión: `main` (`2e25e60`, árbol aparte
  `D:/Projects/ld-wt-b2f-main`) 07:21–07:44 UTC → `runs/main/`; candidato 1 (`30d6f9a`) 07:46–08:06
  → `runs/c1/`; candidato 1 + tope doble (`b2885ba`) 08:12–08:33 → `runs/c2/`. Cada una instalada
  en el daemon con `uv tool install --force --reinstall --no-cache` y comprobada con `diff`.
- RAM: libre antes de cada ventana entre 14,0 y 22,2 GB de 31,1; mínimo visto durante las tres
  tandas 6,7 GB (vigilante cada 3 s, umbral 1,5 GB: no paró nada). Errores de la tool: 0.

## Resultado (3 repeticiones; fracción de los 10 códigos/ficheros más nombrados)

| Grupo | Versión | Códigos | Ficheros | Códigos del modelo | Invenciones por resp. | Cortadas |
|---|---|---|---|---|---|---|
| G, largo `es` | `main` | 0,33 | 0,79 | 0,33 | 0,73 | 2 de 15 |
| | c1 | 1,00 | 1,00 | 0,44 | 0,73 | 4 |
| | c2 | 1,00 | 1,00 | 0,49 | 0,73 | 0 |
| GE, largo `en` | `main` | 0,93 | 0,81 | 0,93 | 1,20 | 4 de 15 |
| | c1 | 1,00 | 1,00 | 1,00 | 0,73 | 6 |
| | c2 | 1,00 | 1,00 | 1,00 | 0,87 | 0 |
| H, pequeños forzados al largo `es` | `main` | 0,17 | 1,00 | 0,17 | 0,50 | 0 de 18 |
| | c1 | 1,00 | 1,00 | 0,93 | 0,50 | 0 |
| | c2 | 1,00 | 1,00 | 0,96 | 0,50 | 0 |
| HE, ídem `en` | `main` | 0,88 | 1,00 | 0,88 | 0,50 | 0 de 18 |
| | c1 | 1,00 | 1,00 | 0,93 | 0,50 | 0 |
| | c2 | 1,00 | 1,00 | 0,93 | 0,50 | 0 |
| M, mecánico `es` (prompt idéntico) | `main` / c1 / c2 | 0,92 / 0,89 / 0,95 | 1,00 | igual | 1,06 / 0,89 / 1,06 | 0 / 1 / 1 |
| ME, mecánico `en` (prompt idéntico) | `main` / c1 / c2 | 0,93 / 0,87 / 0,86 | 1,00 / 1,00 / 0,96 | igual | 0,39 / 0,56 / 0,33 | 0 / 0 / 0 |

Ruido (llamadas de prompt idéntico, rama frente a `main`): invenciones por respuesta 0,11 (c1) y
0,12 (c2); cortadas ±1. A14, A15, B31 y B32: 0 invenciones y 0 cortes en las tres versiones.

**Verificación en `main`:** la pérdida existe. Con el rol largo en español, 0 de 9 respuestas de
G1–G3 nombran un código (biome y `lint-9k`); en H, 0,17. El rol mecánico no la sufre (0,92 y 0,93),
así que no se toca (decisión fijada antes de medir).

## Contra el criterio

| Condición | c1 | c2 |
|---|---|---|
| 1. Códigos y ficheros ≥ 0,9 en G, GE, H, HE | sí | sí |
| 2a. Códigos del modelo no peores que `main` | sí | sí |
| 2b. Español (G+H) ≥ `main` + 0,2 (0,24) | sí (0,71) | sí (0,75) |
| 3. Invenciones ≤ `main` (0,71) + ruido | sí (0,61) | sí (0,64) |
| 4. Cortadas ≤ `main` (6) + ruido (1) | **no (10)** | sí (0) |
| 5. A14/A15/B31/B32 sin más invenciones ni cortes | sí | sí |

c1 se cortaba en G1, G4, GE1 y GE4 (los ruff con más códigos) en 3 de 3: al nombrar cada código con
su descripción no le alcanzaban los 728 tokens. Regla (2): tope doble solo en la llamada única del
rol largo. Con c2 el tope nuevo se usó hasta 944 tokens; latencia mediana de G/GE 22,9 y 21,5 s
(`main` 22,8 y 19,7 s).

**Veredicto: LLEGA con c2 (`b2885ba`).** Sin maquillar: la cobertura total de 1,00 pasa por la
línea del programa; el modelo solo, en los logs largos en español (G), nombra la mitad de los
códigos (0,49 frente a 0,33); en los pequeños (H), casi todos.
