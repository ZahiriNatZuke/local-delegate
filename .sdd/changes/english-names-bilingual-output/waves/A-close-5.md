# Ola A-close-5: valores de una palabra que el detector no ve (fase 1)

Fase 1: solo propuesta. Mapping en `waves/A-close-5-mapping.csv` (34 filas, sin aprobar). Punto de
partida: las 21 filas `valor-interno` de `evidence/A-close-4/singleword-scripts.tsv` (14 valores
distintos; `singleword-src.tsv` no tiene ninguna). Al leer el código de cada una aparecieron
**hermanos** que el barrido no vio (`buscando`, que no está en el léxico) o que clasificó mal
(`fallar`/`excluir` como `contenido-de-caso`, el `empate` de los veredictos como `entrada-persona`).
Un barrido AST propio sobre comparaciones y asignaciones a atributo en `scripts/` y `src/`
(scratchpad `a-close-5/cmp.py` y `gap.py`) no encontró más valores internos en `src/`.

## 1. Los 14 valores del barrido

| Valor | Fichero:línea | Clase | Decisión |
| --- | --- | --- | --- |
| `hecho` | `scripts/price_watcher.py:151`, `:187` | interno (estado del lector HTML) | `done` |
| `tabla` | `scripts/price_watcher.py:158`, `:181`, `:208` | interno (mismo estado) | `table` |
| `esperar` | `scripts/ci_gate.py:117` | interno (constante `WAIT`; `mark` de `:213` pone el rótulo) | `wait` |
| `bien` | `scripts/ci_gate.py:118` | interno (`GOOD`) | `good` |
| `mal` | `scripts/ci_gate.py:119` | interno (`BAD`) | `bad` |
| `cambiar` | `scripts/measure_cooldown.py:151` | interno (`result` que comparan los tests); sale en `--json` y en «RESULTADO:» (`:296`), nada lo relee | `change`, sin lectura dual; rótulo en español al imprimir (P1) |
| `mejor` | `scripts/analyze_benchmark.py:352`, `:677`, `:689` | interno (veredicto por pares y automático, se compara en `:687`/`:689`); sale en `decide --json` (nada lo relee) y en el informe (`:828`) | `better`; rótulo en `:828` (P1) |
| `peor` | `scripts/analyze_benchmark.py:354`, `:679`, `:687` | interno (igual) | `worse`; rótulo en `:828` (P1) |
| `produccion` | `scripts/dev/affinity_batch.py:496` | **persistido**: `via` de las filas del techo en `benchmarks/afinidad-2026-10/resultados*/techo-*.jsonl` (6 congeladas); `analyze_benchmark` las relee con `normalize_benchmark_result` (`:97`) | `production` + **lectura dual** (`benchmark_results.values.via` en `legacy_names.py:259`) + test con una fila vieja junto a `test_analyze_benchmark.py:311` + mutante |
| `valida` | `scripts/pair_sheet.py:213` | interno (`verdict` de `unblind`, lo comparan los tests); sale en la tabla (`:1234`) y en `--json`; `merge_unblinded_pairs` relee ese JSON pero solo `human` | `valid`, sin lectura dual; rótulo en `:1234` (P1) |
| `casa` | `scripts/check_install_e2e.py:81` | interno (carpeta del HOME simulado en un temporal) | `home` |
| `aviso` | `scripts/measure_adoption.py:121` | interno (motivo por defecto; solo pertenencia a un conjunto) | `suggested`, el de `PANEL_VALUE_ALIASES` (`legacy_names.py:564`) |
| `desconocido` | `scripts/macos_mcp_canary.py:182` | contenido de caso: etiqueta que se le pasa a `local_classify` junto a un texto en español | no se toca |
| `completada` | `scripts/macos_mcp_canary.py:200` | contenido de caso (con `fallida`, que el barrido no vio) | no se toca |

## 2. Hermanos que no estaban en el barrido

| Valor | Fichero:línea | Clase | Decisión |
| --- | --- | --- | --- |
| `buscando` | `scripts/price_watcher.py:140`, `:153`, `:175`, `:255` | interno (estado inicial del mismo lector) | `searching` (directa: es la misma máquina de estados) |
| `no concluyente`, `se quedan` | `scripts/measure_cooldown.py:140`, `:150` | interno, como `cambiar` | `inconclusive`, `keep` (P2) |
| `no valida`, `sin base` | `scripts/pair_sheet.py:215`, `:211` | interno, como `valida` | `invalid`, `no_baseline` (P2) |
| `empate` (veredicto) | `scripts/analyze_benchmark.py:350`, `:355`, `:681` | interno, tercer valor de `mejor`/`peor` | `tie` (P3) |
| `empate` (ganador) | `scripts/analyze_benchmark.py:1474`, `:1505` | interno (`_preferred`, espejo de `pair_sheet._winner`, que ya dice `tie`) | `tie` (P3) |
| `empate` (clave de `human`) | `scripts/analyze_benchmark.py:376`, `scripts/pair_sheet.py:198` | entrada de persona, ya decidida (`rename-exceptions.md:398-401`) | no se toca: frente B |
| `empate` (criterio) | `scripts/analyze_benchmark.py:698` | salida (criterio impreso, como `techo` en A-close-3) | no se toca: frente B |
| `fallar`, `excluir` | `scripts/build_corpus.py:2422`, `:2430`, `:2677-2678` | **persistido**: `selection.privacy` de `cases.json` (el congelado dice `excluir`), que `check_versioned_affinity` relee (`:2645`) y devuelve a `build_affinity` | `fail`, `exclude` + **lectura dual** en `affinity_corpus.values.privacy` (P4) |
| `redactado`, `real+redactado`, `real-reescrito` | `scripts/build_corpus.py:2338`, `:2344`, `:2356` | **persistido**: `source_body` de `trampas.json` (6 + 3 congelados), que compara `check_versioned_affinity` (`:2661`); hoy registrado como dato congelado (`rename-exceptions.md:334/:384/:385`) | `written`, `real+written`, `real-rewritten` + **lectura dual** en `affinity_traps.values.source_body` (P5) |
| `fecha` (clave) | `scripts/build_corpus.py:2590`, `:2591` | **persistido**: clave de `selection.real[]`/`traps[]` (46 en `cases.json`), que relee la comparación de `:2654` | `date` + lectura dual en `normalize_affinity_corpus` (P6) |
| `nuevo`, `regresion` | `scripts/build_corpus.py:2607` | salida: grupo de `by_tool` que solo se imprime (`:2697`) | sin filas (P7) |
| `peor`/`mejor` (parámetro `traps`) | `tests/test_pair_sheet.py:348`, `:368`, `:893` | interno de un helper de test | sin filas (P8) |
| `correo` | `scripts/build_corpus.py:1488`, `:1506` | salida: tipo de dato privado que sale en el hallazgo («correo: …»), junto a `ruta de perfil` e `id de sesion` | no se toca: frente B |
| `eliminado`/`eliminada`, `activa`/`inactiva`, `exclusivo`/`persistente`, `italiano` | `src/local_delegate/install.py:1535`, `server.py:4522`, `:4385`, `:3199` | salida (barrido AST de `src/`) | no se toca: frente B (B5 para `install`, B2a para `server`) |

**Rótulos para no cambiar la salida (P1).** Donde un valor nuevo se imprime (`measure_cooldown.py:296`,
`pair_sheet.py:1234`, `analyze_benchmark.py:828`) se añade un diccionario de rótulos en español,
como `_STATE_LABELS` (`analyze_benchmark.py:1679`). Así la salida queda byte a byte igual, lo que en
`measure_cooldown` es obligatorio: el envoltorio `medir_enfriamiento.py` (REQ-046) tiene que dar la
misma salida, y `test_measure_cooldown.py:378` comprueba «RESULTADO: no concluyente».

**Lectura dual** solo en `produccion` (directa), `fallar`/`excluir` (P4), `source_body` (P5) y la
clave `fecha` (P6). `cambiar` no la necesita: el plan la dejaba en «si procede» y nada relee
`result` de disco (solo sale en `--json`, que no guarda el repo).

## 3. Preguntas para la sesión principal

1. **Rótulos al imprimir.** ¿Los valores nuevos que se imprimen pasan por un diccionario de rótulos en
   español (como `_STATE_LABELS`), o se imprimen tal cual en inglés? *Recomendación:* rótulos; el
   frente A no cambia la salida, y en `measure_cooldown` lo exige REQ-046. ¿Qué ola B traduce
   después esos rótulos? Ninguna ola del plan posee `measure_cooldown.py`, `pair_sheet.py` ni
   `analyze_benchmark.py`. *Recomendación:* que B0 los asigne (B1 por cercanía con `benchmark`) y que
   vayan a «Texto de salida que traduce el frente B» de `rename-exceptions.md`.
2. **Hermanos de dos palabras** (`no concluyente`, `se quedan`, `no valida`, `sin base`). Son el mismo
   conjunto de valores que `cambiar` y `valida`: dejarlos en español daría un conjunto mixto.
   *Recomendación:* entran en el lote (`inconclusive`, `keep`, `invalid`, `no_baseline`). El
   `no concluyente` de `adoption_experiment.py:214` queda fuera (otro script, otro conjunto).
3. **`empate` de los veredictos** (`analyze_benchmark.py:350/:355/:681`, y `:1474/:1505` en
   `_preferred`). *Recomendación:* `tie` en las dos cosas, el mismo valor que ya usa
   `pair_sheet._winner`. Se quedan en español la clave `empate` de `human` (ya decidida para el
   frente B) y el criterio `empate` de `:698` (salida, como `techo`).
4. **`--privacy fallar|excluir`**, un valor de opción que además se guarda en el corpus congelado y
   se relee en `--check`. *Recomendación:* regla 1, como la pregunta 6 de A-close-3 (el constructor
   lo sigue escribiendo y un corpus nuevo saldría en español): `fail`/`exclude`, tabla en
   `affinity_corpus` y `test_corpus.py:984` como test con el valor viejo real. La opción cambia sin
   alias (no sale en `docs/`, README ni CHANGELOG); sacar la fila `excluir` de
   `rename-exceptions.md:159`.
5. **`source_body` de las trampas**, registrado como dato congelado en A10b-6. *Recomendación:* el
   mismo argumento que en P4 (`build_corpus.py` lo sigue escribiendo): `written`, `real+written` y
   `real-rewritten` con tabla en `affinity_traps`, y sacar las tres filas de `rename-exceptions.md`.
   Si se prefiere no reabrir lo de A10b-6, queda como está y no se aplica la fila.
6. **La clave `fecha`** de `selection.real[]`/`traps[]`. Es una clave, no un valor, pero tampoco la ve
   el detector. *Recomendación:* que entre en este lote (`date`) con lectura dual en
   `normalize_affinity_corpus`, que hoy no entra en esas listas. Si no, se anota como pendiente del
   detector.
7. **`nuevo`/`regresion`** de `by_tool` (`build_corpus.py:2607`): solo se imprimen, dentro de un JSON
   con claves en inglés y junto a `sheet_role` (`trap`). *Recomendación:* `new`/`regression` sin
   lectura dual, en este lote; si no, frente B.
8. **El parámetro `traps="peor"|"mejor"`** del helper `_responses` de `test_pair_sheet.py`.
   *Recomendación:* `worse`/`better` en este lote; es un valor interno de test y el cambio es de tres
   líneas.

## 4. Llamadas `local_*`

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente A-close-5 (fase 1) | `local_summarize`, `local_extract`, `local_explain_code` (0) | motivo: cada decisión necesitaba el literal de unas pocas líneas (`sed -n` de 10 a 40 líneas por sitio) y el criterio de si se relee de disco; el barrido de huecos se hizo por AST, y no había ningún fichero grande que leer entero |
