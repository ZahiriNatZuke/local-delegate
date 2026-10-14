# `affinity --check` sin depender del entorno

Lote del plan §1.4, entre la higiene de CodeQL y B0. Rama `sdd/affinity-check-env` desde
`origin/main` (00434ea). Evidencias en `evidence/affinity-check-env/`.

## 1. Verificación por ejecución (antes del arreglo)

`uv run python scripts/build_corpus.py affinity --check` (solo lectura: reconstruye en una carpeta
temporal con el backend interceptado y compara con `benchmarks/afinidad-2026-10/`).

| Entorno | Salida | Fichero |
|---|---|---|
| `LOCAL_DELEGATE_COMMIT_LANGUAGE=es` | `ok` (exit 0) | `before-es.txt` |
| sin la variable (`env -u`) | `1 diferencias`: `cases.json ya no coincide` (exit 1) | `before-unset.txt` |
| `=en` | `1 diferencias`: lo mismo (exit 1) | `before-en.txt` |

La comprobación agrupa por fichero, así que dice «1». El recuento por caso y campo
(`percase-diff.py`, `before-percase-*.txt`): con `es`, 0; sin la variable y con `en`, **40, todas
en `system` de `local_commit_msg`**. La hipótesis se confirma.

Además: el mismo agujero, al revés, en el corpus F2 (`build_corpus.py --check`,
`benchmarks/catalogo-2026-09/`): sin la variable `ok`, con `=es` **2 diferencias**
(`commit-diff-19k` y `techo-commit-156k`: `system ya no coincide`). `before-f2-*.txt`.

## 2. Causa

- `scripts/build_corpus.py:669` (en 00434ea): `PRESERVED_VARIABLES = frozenset({"LOCAL_DELEGATE_COMMIT_LANGUAGE"})`,
  y en `intercepted_production` (`:689`) esa variable era la única del paquete que **no** se quitaba
  del entorno durante la captura.
- `src/local_delegate/server.py:3226`: `_commit_language_instruction()` llama a
  `config.commit_language()` (`src/local_delegate/config.py:415`), que lee la variable al llamar;
  `server.py:3891` mete esa orden en el `system` de `local_commit_msg`.
- Resultado: la captura reconstruía el prompt con el idioma de quien la corría, y lo comparaba con
  un corpus congelado con otro.

Con qué idioma se congeló cada corpus (ninguno lo guarda; se mira en el `system` congelado):

- Afinidad: los 40 casos de commit acaban en «… (primera línea y cuerpo) en español.» → `es`.
- F2: los 2 casos de commit piden «el idioma predominante de los textos del diff» → sin variable.

## 3. Arreglo (`scripts/build_corpus.py`)

- Fuera `PRESERVED_VARIABLES`. Nuevas constantes documentadas: `COMMIT_LANGUAGE_VARIABLE` (`:670`),
  `F2_COMMIT_LANGUAGE = ""` (`:673`) y `AFFINITY_COMMIT_LANGUAGE = "es"` (`:675`).
- `intercepted_production(commit_language=F2_COMMIT_LANGUAGE)` (`:689`): quita todas las variables
  del paquete como antes y **fija** la del idioma al valor del corpus (vacío = sin variable); al
  salir la deja como estaba. No cuenta para la recarga de `config` (se lee al llamar), así que el
  aislamiento de logs de conftest no se deshace.
- `capture_case(..., commit_language=F2_COMMIT_LANGUAGE)` (`:786`); `build_affinity` captura con
  `AFFINITY_COMMIT_LANGUAGE` (`:2473`). El F2 (`build`, `check_versioned`) usa el valor por defecto.
- `main_affinity` imprime el idioma del corpus y avisa si el del entorno es otro: «no se usa» (`:2720`).
- No hace falta lectura dual: el corpus no guarda el idioma y su formato no cambia.
- **Producción intacta**: no se toca `server.py` ni `config.py`; el prompt de `local_commit_msg` es el
  mismo. Construir el corpus de afinidad sigue dando el de `es` (el de la PC), ahora en cualquier
  máquina.

Después (`after-*.txt`): `affinity --check` da `ok` sin la variable, con `es` y con `en`; el
`--check` de F2 da `ok` con y sin `es`.

## 4. Tests

`tests/test_corpus.py` (sustituyen a `test_capture_keeps_machine_commit_language` y
`test_capture_without_variable_asks_diff_language`, que fijaban el comportamiento viejo):

- `test_frozen_commit_languages_match_the_frozen_cases`: las constantes casan con lo congelado
  (40 casos de commit en afinidad con «en español.», 2 en F2 con «idioma predominante»).
- `test_affinity_capture_ignores_the_environment_language[None|es|en]`: la captura con el idioma
  de afinidad pide español sea cual sea el entorno, y deja la variable como estaba.
- `test_f2_capture_ignores_the_environment_language[None|es|en]`: control con el otro idioma.
- `test_affinity_check_is_ok_with_any_environment_language[None|en]`: `check_versioned_affinity`
  entera da `[]`. Se salta solo sin el historial de `main` (el checkout superficial del CI); aquí
  corre (los 2 skipped de la suite son los de antes).

`tests/test_environment_isolation.py`: el inventario debe contener `LOCAL_DELEGATE_COMMIT_LANGUAGE`.
La suite ya la aislaba (entra en `config.ENVIRONMENT_VARIABLES` por la lectura de arranque de
`config.py:419-427`, y conftest borra todo el inventario); el assert protege que siga ahí, porque es
una variable que se lee al llamar. Agujero en la suite: **no** había tests que pasaran por el
entorno de esta PC; el agujero estaba en los dos `--check` de línea de comandos, que no son tests.

**Mutante** (`mutant.log`): quitar el bloque que fija la variable en `intercepted_production`
(la captura vuelve a heredar el entorno). Fallan 6: afinidad `[None]` y `[en]` por
`assert system.endswith(_ASKS_SPANISH)`, F2 `[es]` y `[en]` por `assert _ASKS_DIFF_LANGUAGE in
system`, y la comprobación entera `[None]` y `[en]` por `check_versioned_affinity(...) == []`. Pasan
los 3 que deben (`[es]` de afinidad, `[None]` de F2 y el de lo congelado). Restaurado: sha256
`8a7e9e55…6e31` igual antes y después.

## 5. Calidad

- Suite: 2 627 recogidos; 2 625 passed, 2 skipped, 0 failed (`pytest-full.log`, `collect.txt`).
- Dirigidos: 80 passed (`targeted.txt`).
- `ruff check .` limpio; `ruff format --check .` 197 ficheros ya formateados (`ruff.txt`).
- Detector con la lista: 0 fuera de la lista, 0 palabras sin clasificar (`detector.txt`).
- LF conservado en los tres ficheros tocados (`git ls-files --eol`).
