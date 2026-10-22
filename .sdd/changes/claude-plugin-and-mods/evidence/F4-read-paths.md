# Evidencia — Medir por qué vías se lee (F4-measure-reads)

Rama `feat/plugin-f4-measure-reads`, worktree `D:/Projects/ld-wt-f4-measure-reads`, sobre `main` en
`ae11459`. Cubre REQ-018 y **fija el umbral de REQ-020 antes de que se implemente F4**.

## Qué se midió y cómo

`scripts/measure_read_paths.py` recorre `~/.claude/projects/**/*.jsonl` (sesiones principales y
subagentes), empareja cada `tool_use` con su `tool_result` y clasifica la llamada por vía. No pasa
contenido por el contexto ni lo emite: solo cifras en JSON. Corrida de esta PC:

```
uv run python scripts/measure_read_paths.py --until 2026-10-22T16:00:00Z --days 30 \
    --corpus <scratchpad>/corpus-real.jsonl
```

- Periodo: 2026-09-22T16:00Z → 2026-10-22T16:00Z (30 días), 676 transcripts.
- **36 620 lecturas** de ficheros; 6 581 comandos de shell que no leen ningún fichero.
- **2 053 llamadas excluidas por estar dentro de una ventana de prueba** (`test-windows.json`).
- El 92,5 % de las lecturas las hacen subagentes (modo orquestador).

Cómo se decide cada cosa:

- **Resultado**: `done`; `blocked` si lo paró un hook (`PreToolUse… hook error` o el texto del
  bloqueo de lectura); `denied` (permisos), `error`, o `no_result` si la llamada no tiene resultado.
  El bloqueo de lectura está encendido desde el 2026-09-12, así que los `Read` grandes de prosa
  salen como `blocked` y no se confunden con lecturas hechas.
- **Tamaño del fichero**: el de un `Read` entero, de lo que devolvió; el resto, de disco **hoy**.
  `unknown` = ruta que ya no existe (muchos worktrees `ld-wt-*` borrados), directorio, o ruta no
  resoluble (comodines, variables, código Python).
- **Volumen**: caracteres del `tool_result` que entraron al contexto (las imágenes no cuentan).
- **Vías de shell**: el verbo de la primera etapa de cada comando (`&&`, `;`, saltos de línea…),
  sin heredocs ni here-strings; `_pipe` si sigue una tubería; un comando con su salida redirigida a
  un fichero (`cat a > b`) no es lectura. `type`/`gc` solo leen en PowerShell.

## Tabla por vía y volumen

Tramos de tamaño del fichero: < 8 KB, 8–32 KB, 32–128 KB, ≥ 128 KB y desconocido. «Grandes» = el
volumen que entró al contexto desde ficheros de ≥ 8 KB (umbral del hook de lectura actual).

| Vía | Lecturas | Hechas | Bloq. | Error | Subag. | Volumen (M car.) | % vol. | De grandes (M) | <8K | 8–32K | 32–128K | ≥128K | ? |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `shell_grep_pipe` | 10 594 | 10 502 | 0 | 92 | 9 887 | 18,72 | 21,2 % | 7,59 | 669 | 1 506 | 1 410 | 944 | 6 065 |
| `shell_sed` | 6 900 | 6 862 | 0 | 38 | 6 520 | 21,15 | 24,0 % | 12,03 | 419 | 1 436 | 1 633 | 774 | 2 638 |
| `shell_grep` | 4 636 | 4 549 | 0 | 87 | 4 310 | 5,94 | 6,7 % | 2,26 | 404 | 676 | 631 | 325 | 2 600 |
| `shell_python` | 3 790 | 3 585 | 0 | 205 | 3 398 | 3,27 | 3,7 % | 0,00 | 0 | 0 | 0 | 0 | 3 790 |
| `read_range` | 2 798 | 2 797 | 0 | 1 | 2 657 | 21,11 | 24,0 % | 16,91 | 97 | 693 | 802 | 442 | 764 |
| `shell_head_tail` | 1 974 | 1 913 | 0 | 61 | 1 810 | 2,17 | 2,5 % | 0,53 | 241 | 114 | 138 | 48 | 1 433 |
| `shell_cat` | 1 584 | 1 537 | 4 | 43 | 1 440 | 3,66 | 4,2 % | 0,23 | 503 | 77 | 22 | 3 | 979 |
| `read_whole` | 968 | 691 | 277 | 0 | 891 | 5,60 | 6,3 % | 3,74 | 463 | 433 | 48 | 1 | 23 |
| `shell_sed_pipe` | 960 | 955 | 0 | 5 | 879 | 2,11 | 2,4 % | 0,93 | 114 | 163 | 154 | 123 | 406 |
| `shell_cat_pipe` | 847 | 830 | 0 | 17 | 765 | 1,90 | 2,2 % | 0,19 | 332 | 47 | 5 | 2 | 461 |
| `grep_tool` | 453 | 448 | 0 | 5 | 420 | 0,95 | 1,1 % | 0,36 | 21 | 56 | 78 | 52 | 246 |
| `shell_head_tail_pipe` | 275 | 265 | 0 | 10 | 227 | 0,36 | 0,4 % | 0,13 | 29 | 28 | 40 | 24 | 154 |
| `read_image` | 183 | 183 | 0 | 0 | 148 | 0,00 | 0,0 % | 0,00 | 0 | 7 | 23 | 17 | 136 |
| `shell_awk_pipe` | 135 | 132 | 0 | 3 | 118 | 0,27 | 0,3 % | 0,10 | 6 | 6 | 27 | 21 | 75 |
| `shell_awk` | 113 | 113 | 0 | 0 | 109 | 0,26 | 0,3 % | 0,12 | 11 | 18 | 18 | 16 | 50 |
| `shell_git_show_pipe` | 106 | 104 | 0 | 2 | 92 | 0,14 | 0,2 % | 0,00 | 0 | 0 | 0 | 0 | 106 |
| `mcp_pycharm` | 100 | 100 | 0 | 0 | 100 | 0,01 | 0,0 % | 0,00 | 0 | 0 | 0 | 0 | 100 |
| `mcp_obsidian` | 92 | 92 | 0 | 0 | 26 | 0,36 | 0,4 % | 0,00 | 0 | 0 | 0 | 0 | 92 |
| `shell_python_pipe` | 59 | 59 | 0 | 0 | 45 | 0,12 | 0,1 % | 0,00 | 0 | 0 | 0 | 0 | 59 |
| `shell_other` | 21 | 20 | 0 | 1 | 20 | 0,01 | 0,0 % | 0,00 | 2 | 0 | 0 | 0 | 19 |
| `shell_cat_partial` | 20 | 18 | 0 | 2 | 10 | 0,02 | 0,0 % | 0,00 | 5 | 0 | 0 | 0 | 15 |
| `shell_other_pipe` | 9 | 9 | 0 | 0 | 8 | 0,01 | 0,0 % | 0,00 | 1 | 0 | 1 | 0 | 7 |
| `shell_git_show` | 3 | 2 | 0 | 1 | 3 | 0,00 | 0,0 % | 0,00 | 0 | 0 | 0 | 0 | 3 |

Total: 88,1 M caracteres al contexto, 45,1 M desde ficheros de ≥ 8 KB.

Lo que dice la tabla:

- **`Read` ya no es la vía principal.** `Read` (entero + franjas) es el 30 % del volumen total;
  `sed -n` solo, el 24 %. De los 968 `Read` enteros, 277 (29 %) los paró el hook; ninguna lectura
  de shell la paró (solo 4 `cat`).
- **`grep` es la vía más usada** (15 683 llamadas, 43 %), casi siempre con `| head` y en
  subagentes, pero es búsqueda: devuelve líneas sueltas, no un fichero ni una franja.
- `python -c "open(…)"` es frecuente (3 849) pero no se puede saber qué fichero lee: tamaño
  siempre desconocido.
- Las tools de lectura de otros MCP casi no pesan aquí (0,4 %): `obsidian` y `pycharm`.

## Qué vías cubre F4

Criterio del script (`f4_candidates`): las vías que, de mayor a menor, suman el 90 % de lo que
entró al contexto desde ficheros grandes: `read_range` (37,5 %), `shell_sed` (64,1 %),
`shell_grep_pipe` (81,0 %), `read_whole` (89,2 %), `shell_grep` (94,3 %).

Agrupadas según REQ-019/021:

| Grupo | Vías | Lecturas | % vol. total | % vol. de grandes |
|---|---|--:|--:|--:|
| **Cubre F4** (clasificable con seguridad: fichero y alcance conocidos) | `read_whole`, `read_range`, `shell_sed` (+`_pipe`), `shell_head_tail` (+`_pipe`), `shell_cat` (+`_pipe`, `_partial`) | 16 326 | 65,9 % | **76,9 %** |
| **Solo aviso y registro** (búsqueda, no lectura de un fichero) | `shell_grep`, `shell_grep_pipe`, `grep_tool` | 15 683 | 29,1 % | 22,6 % |
| **Solo aviso y registro** (no clasificable) | `awk`, `python`, `git show`, `other`, MCP | 4 428 | 5,1 % | 0,5 % |

Decisión: **F4 cubre el primer grupo**, que es el 77 % del volumen de ficheros grandes. `grep`
queda fuera del bloqueo/elección: no es «leer el fichero X», y resumir con el modelo local no
sustituye a una búsqueda; se registra por vía (REQ-021) para revisar tras medir F4. `awk`,
`python`, `git show` y MCP no son clasificables con seguridad: solo aviso y registro.

## Umbral de REQ-020

`range_coverage` mide, por transcript y fichero, qué parte de las líneas cubren las franjas hechas
(`Read` con `offset`/`limit`, `sed -n a,bp`, `head -n N`, `cat | head`, `Get-Content -TotalCount`),
como unión de intervalos sobre las líneas del fichero (las del `Read` si las hay; si no, las de
disco hoy). 4 212 ficheros con franjas:

| Grupo | n | p25 | p50 | p75 | p90 |
|---|--:|--:|--:|--:|--:|
| Una sola franja | 2 524 | 0,05 | 0,19 | 0,70 | 0,92 |
| Varias franjas | 1 688 | 0,08 | 0,19 | 0,45 | 0,93 |
| **Tras un `Read` bloqueado** | 131 | 0,87 | **0,96** | 1,00 | 1,00 |

Qué parte de cada grupo llega a cada umbral candidato (`at_least`):

| Umbral | Varias franjas | Tras un bloqueo |
|--:|--:|--:|
| 0,5 | 22,6 % | 90,8 % |
| 0,6 | 18,0 % | 89,3 % |
| 0,7 | 15,6 % | 87,8 % |
| **0,8** | **13,2 %** | **85,5 %** |
| 0,9 | 10,9 % | 64,9 % |

Histograma de cobertura con varias franjas (decenas %): 0–10: 545, 10–20: 330, 20–30: 189,
30–40: 136, 40–50: 107, 50–60: 77, 60–70: 41, 70–80: 40, 80–90: 39, ≥ 90: 184.

**Umbral fijado: 0,8 (80 % de las líneas del fichero).**

Razonamiento:

- El patrón que REQ-020 quiere cazar está medido: tras un `Read` bloqueado, el agente rehace el
  fichero por franjas y llega a una mediana del **96 %**. Con 0,8 se caza el 85,5 % de esos casos.
- La navegación normal por franjas no llega ahí: mediana 19 %, p75 45 %. Con 0,8 solo el 13,2 %
  cuenta como lectura entera, y buena parte de ese 13 % son ficheros pequeños leídos casi enteros,
  a los que F4 no se aplica (van por debajo del umbral de tamaño).
- Bajar a 0,7 gana 2,3 puntos de reconstrucciones a cambio de 2,4 puntos más de navegación normal;
  subir a 0,9 pierde 20,6 puntos de reconstrucciones para ahorrarse 2,3 de navegación. 0,8 es el
  codo.

## Corpus para REQ-019

`tests/fixtures/read_corpus.jsonl`: 759 filas de esta corrida, hasta 40 por vía, más 40 comandos que
no leen (`via: "none"`) como negativos. Cada fila lleva `tool`, `via`, `scope` y, según la tool,
`command` (shell), `input` (`Read`, con `offset`/`limit`) o `input_keys` (`Grep`, MCP).

Anonimización: se conservan solo los verbos conocidos, las opciones (`-n`, `-TotalCount`…), los
números y franjas (`1,80p`) y los operadores. Todo lo demás va como `<path:hash>`, `<arg:hash>` o
`<code:hash>` (hash HMAC con sal aleatoria de cada corrida, no guardada: no se puede revertir con
un diccionario de rutas), el código Python que abre ficheros como `<code:reads-file>`, y los
cuerpos de heredoc como `<heredoc>`/`<heredoc:reads-file>`. Revisión manual de los tokens
conservados: verbos, opciones, números y operadores; ningún nombre, ruta, correo ni texto.
`test_corpus_is_anonymised` lo comprueba con expresiones regulares propias, no con el anonimizador.

## Límites

- Tamaños de disco de **hoy**: un fichero que creció o se borró da otro tramo o `unknown` (27 %
  de las lecturas de `read_range`, más de la mitad de las de `grep`, por los worktrees borrados).
- `sed`/`head`/`cat|head` sin `Read` del mismo fichero toman las líneas de disco de hoy.
- El clasificador es heurístico (verbo de la primera etapa); REQ-019 lo sustituye por el módulo
  único con este corpus como banco de pruebas.
- Solo esta PC (la Mac no está medida).

## Tests

`tests/test_measure_read_paths.py` (4 tests), escritos antes del script. Contra un script vacío
que imprimía un informe sin datos fallaban por el assert que dicen: `KeyError: 'read_whole'` (no
cuenta las vías), `el escenario debe medir algo…` (guarda de la prueba de privacidad),
`FileNotFoundError: corpus.jsonl` (no escribe corpus) y `KeyError: 'shell_cat'` (ventanas). Con el
script y sin el corpus versionado, `test_corpus_is_anonymised` seguía fallando por
`assert 0 >= 20` (el fixture vacío).

Controles positivos (mutantes sobre el script, `scratchpad/f4/mutants.sh`), cada uno contra su
test y con el assert que dispara:

| Mutante | Test | Falla por |
|---|---|---|
| No excluye las ventanas de prueba | `test_test_windows_excluded` | `'shell_sed' not in …` |
| El corpus guarda la ruta real del `Read` | `test_never_emits_file_contents` | `'secret-private-dir' not in …` |
| El anonimizador deja las rutas de shell | `test_corpus_is_anonymised` | la regex `[A-Za-z]:[\/]` del test |
| `sed` no se clasifica | `test_counts_each_path_kind` | `KeyError: 'shell_sed'` |
| Las franjas se suman sin unir solapes | `test_counts_each_path_kind` | `0.4275 == 0.35` |

Suite completa (`pesado.sh`, `pytest -n 2`): 4 391 pasan, 28 omitidos. `ruff check` y `ruff format --check` limpios. El detector de nombres en
español (`test_detect_spanish_names`) pidió clasificar 35 palabras nuevas: se renombraron las
abreviaturas o dudosas (`vias` → `by_via`, `anon`, `idx`, `ops`, `nverb`, `delim`, `inp`, y la
carpeta de prueba) y las 28 restantes, todas inglés técnico (`heredoc`, `grep`, `sed`, `awk`,
`operands`, `percentiles`…), se añadieron a `en` en `scripts/data/spanish_lexicon.json`.

## Llamadas `local_*`

- `local_lint_summary(path=suite.txt)`: resumen de la primera suite completa (1 fallo: el
  detector de nombres en español).
- `local_commit_msg(path=diff)`: borrador del mensaje de commit.

El resto (análisis de la tabla, umbral, decisión de vías) necesitaba criterio y lo hice yo; la
salida del script es JSON corto y se leyó entera.
