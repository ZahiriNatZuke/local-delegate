# Evidencia de T5b: idioma del mensaje de commit

Cubre REQ-044. Decisión del usuario (2026-10-07): «Fijar el idioma y repetir». No se cargó ningún modelo,
no se llamó al backend ni al daemon, y no se tocó el `config.yaml` de llama-swap ni el lanzador de la tanda.

## Qué se añadió al prompt

La orden va al final del prompt de sistema de `local_commit_msg` (`conventional` y `plain`), detrás del formato:

- **Con `LOCAL_DELEGATE_COMMIT_IDIOMA=es`:** «Escribe el mensaje de commit entero (primera línea y cuerpo) en español.»
- **Sin la variable:** «Escribe el mensaje de commit entero (primera línea y cuerpo) en el idioma predominante de
  los textos del diff (comentarios, documentación y mensajes).»

`es`, `en`, `fr`, `pt`, `de` e `it` se traducen a su nombre; `es-CU` o `pt_BR` se reconocen por su primera parte; lo que no
está en el mapa (`catalán`, `ca`) se usa tal cual. La variable se lee con `config.commit_idioma()`, que usa `_env` y
entra en `config.VARIABLES_DE_ENTORNO`, así que el aislamiento de la suite la quita sola.

**Dónde va y dónde no.** `system` de `local_commit_msg` es el de la llamada única y el que se pasa como
`reduce_system` al map-reduce, o sea el que redacta el mensaje. El map (`map_system`) y el reagrupado de partes
producen notas intermedias que nadie lee y **no** llevan la orden. Se decidió así porque el idioma del resultado lo fija
el reduce, que es el último que escribe, y porque una orden de idioma en las notas no cambia nada que se vea y sí
arriesga mezclar la orden con la consigna de «una viñeta por archivo con su ruta literal». Lo vigilan dos tests: el
último request lleva la orden y todos los anteriores no.

## Ficheros tocados

- Código: `src/local_delegate/config.py`, `src/local_delegate/server.py`.
- Corpus y script: `scripts/construir_corpus.py` (la captura ya no quita esta variable y `afinidad` imprime el idioma
  con el que construye o comprueba), `benchmarks/afinidad-2026-10/cases.json`, `benchmarks/catalogo-2026-09/cases.json`.
- Resultados: `benchmarks/afinidad-2026-10/resultados/{gemma4-26b-a4b,qwen36-35b-a3b}.jsonl` (sin las filas de commit),
  `resultados/techo-gemma4-26b-a4b.jsonl` (movido entero) y la carpeta nueva `resultados-sin-idioma/`.
- Tests: `tests/test_commit_idioma.py` (nuevo, 15 tests contando los parametrizados) y `tests/test_corpus.py` (2 tests al final).
- Documentación: `README.md`, `docs/wiki/Configuration.md`, `docs/wiki/Tools.md`, `examples/.env.example`, `CHANGELOG.md`.
- SDD: `spec.md` (REQ-044, escenario, aclaración y trazabilidad), `plan.md` (T5b y trazabilidad), este fichero y
  `verification.md`.

No hay tabla de variables en `doctor`, `checks.py` ni `local_status` que liste las variables de configuración; los
sitios con tabla son el README y `docs/wiki/Configuration.md`, y los dos la llevan. El guardián que compara listas es
`test_aislamiento_entorno.py`, que se alimenta de `VARIABLES_DE_ENTORNO` y no necesita lista a mano.

## Tests y mutantes

Cada mutante se aplicó sobre el fichero real, se corrió `tests/test_commit_idioma.py` y
`tests/test_aislamiento_entorno.py`, y se restauró el original (comprobado con `git diff --stat`). Todos fallan con una
razón que corresponde al cambio, y cada uno muta de verdad (el assert dispara con un valor distinto del esperado, no por un
error de importación).

| Mutante | Qué muta | Assert que dispara |
|---|---|---|
| M1 No leer la variable | `commit_idioma()` devuelve siempre `""` | `test_con_la_variable_en_es_el_prompt_pide_espanol[conventional/plain]`: `'…en español.' in system` (línea 87), más `test_el_codigo_se_traduce_a_un_nombre_legible` y el de inventario (línea 75) |
| M2 Quitar la rama del idioma del diff | `if not codigo:` pasa a `if False:`, así que sin variable se arma `en .` | `test_sin_la_variable_el_prompt_pide_el_idioma_del_diff[conventional/plain]`: la orden del diff no está (línea 99), más el del map-reduce sin variable |
| M3 El reduce sin la orden | `reduce_system=_guard(fmt)` en lugar de `system` | `test_el_map_reduce_redacta_en_el_idioma_pedido…` (línea 151: la orden de español no está en el último request) y `test_el_map_reduce_sin_variable…` (línea 164) |
| M4 Sin traducir el código | `nombre = codigo` | `test_el_codigo_se_traduce_a_un_nombre_legible[es, EN, es-CU, pt_BR]` (línea 133) y los dos de «es» |
| M5 El map también lleva la orden | `map_system = _orden… + _guard(…)` | `test_el_map_reduce_redacta_en_el_idioma_pedido…` (línea 153: `all(orden not in system de los anteriores)`) y su gemelo sin variable (línea 165) |
| M6 Leer con `os.environ` directo | `commit_idioma()` sin pasar por `_env` | `test_la_variable_entra_en_el_inventario_del_entorno` (línea 75) y `test_config_solo_lee_el_entorno_por_la_puerta_registrada` (`['commit_idioma']`) |
| M7 La captura del corpus quita la variable | `VARIABLES_QUE_SE_CONSERVAN = frozenset()` | `test_la_captura_conserva_el_idioma_del_commit_de_la_maquina` (`tests/test_corpus.py:922`: la orden de español no está en el `system` capturado); su control sin variable pasa |

El script de los mutantes está en el scratchpad de la sesión (no se versiona).

## Corpus

Rehecho con `LOCAL_DELEGATE_COMMIT_IDIOMA=es`: `bash ~/.claude/scripts/pesado.sh uv run python scripts/construir_corpus.py afinidad --privacidad excluir`
(imprime `idioma del mensaje de commit: es`; 73 casos).

Hizo falta tocar el constructor: `produccion_interceptada()` borraba del entorno **todas** las variables de
`config.VARIABLES_DE_ENTORNO` para capturar el prompt de un entorno limpio, y la nueva es una de ellas, así que el corpus
habría salido siempre con la orden del «idioma del diff». Ahora `VARIABLES_QUE_SE_CONSERVAN` la deja en el entorno.

Comparado con el commit anterior, mediante un script sobre los dos JSON:

- Cambian **40 casos**, y en todos solo el campo `system`: 30 reales, 9 trampas y el techo (`techo-commit-156k`). Los
  mismos 73 ids y en el mismo orden; `schema_version`, `production_config`, `controls` y `seleccion` iguales.
- `trampas.json`, `reglas.json` y `fuentes/` no cambian.
- `afinidad --comprobar` con la variable: `ok`. Sin la variable: `cases.json ya no coincide con el constructor` (control
  de que el comprobador ve la diferencia).
- El corpus de F2 (`benchmarks/catalogo-2026-09/cases.json`) recaptura los mismos dos casos de commit (`commit-diff-19k` y
  `techo-commit-156k`) y su test (`test_corpus_versionado_sigue_reflejando_a_produccion`) fallaba al cambiar el prompt de
  producción. Se regeneró con `uv run python scripts/construir_corpus.py --log-dir <ruta inexistente>` y **el entorno
  limpio**: cambia solo el `system` de esos dos casos (2 líneas) y no se tocan `conteos-log.json` ni las fuentes.

sha256:

| Fichero | Antes | Ahora |
|---|---|---|
| `afinidad-2026-10/cases.json` | `1bde663ba516b1588f2f8d9fde71ec1b653db2a348c2308c56898e12190cdfbb` | `6dc7d7a1723fdfff02e110b1197f085618f63e3a0af0b4f08d92ebbebaa6739c` |
| `afinidad-2026-10/trampas.json` | `a9295180be8c597028b50ddae927501dca50f302d35a6bc11ae20ef1a76d9121` | igual |
| `afinidad-2026-10/reglas.json` | `3aac45aa83c16be7b006bc73b941252f4fee6727cce64727fd8eb5a304e968bf` | igual |
| `afinidad-2026-10/huellas.json` | `b96df2a649cff9eaf61ab7221ae8e2bd81f1f7896e8b145f25ca6c102fc22409` | sin tocar (ver abajo) |
| `catalogo-2026-09/cases.json` | `4b39454ad0a66f91d05cb1a03dc24dca366e1dc15c60cc33fe9b87a7eb22edb2` | `caadda48fdbc99e3a9466a9bc2e101331978ee11531171bce3c6ae0754307921` |

**Huellas.** `huellas.json` no se reescribió. Calculadas con la config de llama-swap de ahora (solo lectura) y el corpus
nuevo, cambian 2 de 26: `local_commit_msg` de `gemma4-26b-a4b` y de `qwen36-35b-a3b`, y solo su `prompt_sha256`. La
tanda, al reanudar, se negará a seguir hasta que se pase `--rehacer-huellas` (lo dice su mensaje de error). El techo no
quita la variable: `correr_techo` parte de `dict(os.environ)` y solo suma sus cuatro variables, así que hereda
`LOCAL_DELEGATE_COMMIT_IDIOMA` del lanzador.

## Resultados viejos

Movidos sin borrar, con los mismos nombres, a `benchmarks/afinidad-2026-10/resultados-sin-idioma/` (los bytes de cada
línea, con su fin de línea): 39 filas de commit de `gemma4-26b-a4b` (30 reales y 9 trampas), 39 de `qwen36-35b-a3b` y las
3 del techo (fichero entero). En `resultados/` quedan las mecánicas intactas: 33 + 33 + 33 + 33 filas.

**Cuidado con git.** El `.gitignore` tiene `*.jsonl`; los de `resultados/` están versionados porque se añadieron a la
fuerza, y la carpeta nueva queda **ignorada**. Para que no se pierdan al hacer commit: `git add -f
benchmarks/afinidad-2026-10/resultados-sin-idioma/`. Sin eso, el commit borraría las filas viejas del historial visible.

`bash ~/.claude/scripts/pesado.sh uv run python scripts/dev/tanda_afinidad.py --seco`:

```
gemma3-4b: 33 peticiones (0 pendientes, 33 hechas) + 0 de calentamiento
qwen35-2b: 33 peticiones (0 pendientes, 33 hechas) + 0 de calentamiento
gemma4-26b-a4b: 72 peticiones (39 pendientes, 33 hechas) + 1 de calentamiento
qwen36-35b-a3b: 72 peticiones (39 pendientes, 33 hechas) + 1 de calentamiento
techo (gemma4-26b-a4b, camino de produccion): 3 peticiones (3 pendientes, 0 hechas) + 1 de calentamiento
total: 213 peticiones (81 pendientes) + 3 de calentamiento
```

Pendientes: 39 + 39 + 3, y 0 en las mecánicas.

## Comprobaciones

- `uv run ruff check .`: `All checks passed!`; `uv run ruff format --check .`: `163 files already formatted`.
- Suite completa con `pesado.sh`, volcada a fichero: `1908 passed, 2 skipped, 1 warning in 129.72s` (antes
  `1891 passed, 2 skipped`: 15 tests nuevos de `test_commit_idioma.py` contando los parametrizados, y 2 de `test_corpus.py`).
- Sin dependencias nuevas, sin `noqa`, sin imports nuevos entre módulos del paquete.

## Llamadas `local_*`

**0.** Las lecturas fueron franjas acotadas de `server.py`, `config.py`, `construir_corpus.py`, `tanda_afinidad.py` y del
SDD, con `Read` por rangos y `grep`; ningún fichero era lo bastante grande para compensar la espera de un resumen, y los
JSON de corpus y resultados se analizaron con scripts, no con un modelo. Además, el backend local estaba libre pero no
hacía falta cargarlo.
