# Propuesta de la ola B1: CLI, `doctor`, `test-window`, `benchmark` y llama-swap en dos idiomas

Fase 1 (proponer, no aplicar). Rama `sdd/english-names-b1` desde `origin/main` `3492ba5`. Fuentes:
`plan.md` («#### B1», D5, D8, D10, D11, §4.2), `spec.md` (REQ-019, 021, 022, 026, 032, 034, 045),
`brief.md`, `waves/B0a.md`, `waves/B0b.md`, «Decisiones aprobadas» de `waves/B0-proposal.md`,
`rename-exceptions.md` y el código de la rama.

**Cifra de partida, medida y no estimada.** El propio guardián de B0b
(`tests/test_no_uncatalogued_text.py::_hits_by_file`) da hoy **728 textos únicos** (914 apariciones,
porque la red de contexto y la de tildes cuentan dos veces la misma línea) en los 19 ficheros
pendientes de `cli.json` y `doctor.json`:

| Fichero | Únicos | | Fichero | Únicos |
| --- | ---: | --- | --- | ---: |
| `cli.py` | 179 (57 en la parte de `install`/`update`/`uninstall`) | | `measure_cooldown.py` (script) | 31 |
| `checks.py` | 153 | | `test_windows.py` | 17 |
| `pair_sheet.py` (script) | 64 | | `probes.py` | 14 |
| `residency.py` | 58 | | `doctor.py` | 14 |
| `analyze_benchmark.py` (script) | 55 | | `recompute.py` | 11 |
| `topology.py` | 38 | | `llamaswap_config.py` | 9 |
| `llamaswap_api.py` | 32 | | `matrix.py` | 7 |
| `benchmark.py` | 32 | | `turn.py` | 5 |
| | | | `deprecations.py`, `daemon.py` | 4 y 4 |
| | | | `entrypoint.py` | 1 |

Paquete: 578 (el plan decía ~550 + ~35 «límites»: cuadra). Scripts: 150, que el plan **no**
contaba en el tamaño (se asignaron el 2026-10-14). A eso se suman ~45 msgid de argparse y los textos
que ninguna red ve (diccionarios de valores sin nombre de rótulo, p. ej. `"arriba"` en
`doctor.py:76`).

---

## 1. Diseño por fichero

### 1.1 Catálogo: `resources/i18n/{es,en}/{cli,argparse,doctor}.json` (nuevos, LF)

Mismo formato que `common.json` (D5): JSON plano, una clave por línea, ordenado, primer segmento =
nombre del fichero, interpolación con nombre. Esquema de claves:

| Fichero | Claves | Ejemplos |
| --- | --- | --- |
| `cli.json` | `cli.help.<comando>.<opción>` (ayudas), `cli.help.<comando>._description`, `cli.<comando>.<texto>` (salida), `cli.<módulo>.<texto>` para los módulos de llama-swap/benchmark/daemon, `cli.script.<script>.<texto>` para los tres scripts | `cli.help.check_llamaswap.vram_gb`, `cli.test_window.started`, `cli.residency.pinned_permanent`, `cli.deprecations.alias_warning`, `cli.script.pair_sheet.sheet_intro` |
| `argparse.json` | `argparse.<slug del msgid>` | `argparse.usage` = «uso: » / «usage: », `argparse.options`, `argparse.help_help`, `argparse.error_line` = `%(prog)s: error: %(message)s\n` |
| `doctor.json` | `doctor.check.<id del check>` (títulos, el id tal cual con sus puntos), `doctor.status.<estado>`, `doctor.group.<grupo>`, `doctor.probe.<id>.<texto>` (detalles y remedios), `doctor.header.*`, `doctor.summary.*`, `doctor.language.*` | `doctor.check.service.daemon_auth`, `doctor.status.missing` = «[FALT]» / «[MISS]» |

Los textos de `cli.py` que hablan de `install`/`update`/`uninstall` van a `cli.json`, no a
`install.json` (pregunta 1).

**Proceso de catálogo (desviación pequeña del plan):** el plan dice extraer de
`evidence/i18n-inventory.csv`, pero ese inventario es anterior al frente A (nombres de módulo y
líneas viejos). La fuente es el escáner del guardián, que ya da fichero, línea y texto actuales.
Un script del scratchpad lista las apariciones de la ola, propone clave por fichero y función, y
saca un JSONL por lotes de ~50 frases para `local_translate(path=…)`. El borrador inglés **se
revisa entero**: marcadores `{n}` y `%(x)s`, identificadores entre comillas invertidas, opciones
`--x` intactas, longitud de rótulos alineados (`[FALT]`/`[MISS]`, seis columnas).

**Frases por trozos:** las ~200 que hoy se arman con `+`, `", ".join` o f-strings encadenadas se
reescriben como una entrada entera con marcadores con nombre. Un listado (`", ".join(...)`) entra
como un solo marcador (`{matches}`); el separador es `", "` en los dos idiomas y no se cataloga.

### 1.2 `cli.py` (CRLF) — cableado de argparse (D8) y textos

- **Parche acotado al proceso y al comando.** Un gestor de contexto en `cli.py`,
  `_argparse_in_language()`, guarda `argparse._` y `argparse.ngettext`, pone
  `i18n.argparse_gettext` / `i18n.argparse_ngettext` y los restaura en `finally`. `run()` queda:
  `with _argparse_in_language(): args = build_parser().parse_args(argv); return args.func(args)`.
  Restaurar importa: la suite corre en el mismo proceso y, sin restaurar, el argparse de los
  scripts y de otros tests quedaría en español para el resto de la corrida.
- **Ayudas:** cada `help=`, `description=` y `metavar` con texto pasa a `t("cli.help.…")`. Se
  evalúan dentro de `build_parser()`, que ya corre con el idioma resuelto (`i18n.current()` se
  cachea por proceso). Un `%` literal en una ayuda va como `%%` en los dos idiomas (argparse formatea
  con `%`); `%(default)s` se conserva y la paridad de B0a ya lo exige.
- **No cambia** ningún nombre de subcomando, opción, `dest`, valor de `choices` ni la salida
  `--json` (contrato).
- **Pregunta interactiva** de `_decide_on_foreign_codex` (`cli.py:150`, «[s/N]» con «sí»): el texto
  sale del catálogo y la respuesta acepta las dos formas (`s`, `sí`, `si`, `y`, `yes`), sea cual
  sea el idioma.
- **Números (REQ-026):** ver 1.4.

### 1.3 `doctor.py` y `checks.py` (LF)

- **`Check`:** el tercer campo pasa a ser la **clave** del título (`title_key`), y `title` es una
  propiedad que devuelve `i18n.t(self.title_key)`. Como `t` devuelve la propia clave si no la
  encuentra, `tests/test_checks.py:439` (`Check("test.broken", "cliente", "roto", …)`) sigue
  valiendo sin tocarlo. Los ids y grupos no cambian (REQ-022). El título con
  `f"skill {install.SKILL_NAME}"` pasa a `doctor.check.scaffold.skill` con `{skill}` y la propiedad
  lo interpola.
- **`Result.detail` y `fix_hint`** se redactan con `t()` en el momento del probe. Llegan igual al
  reporte de `install` y a `update` (B5), que los imprimen sin tocarlos.
- **`STATUS_LABEL`:** `[ OK ]`, `[WARN]`, `[FALT]`/`[MISS]`, `[ -- ]`, desde el catálogo.
- **`doctor.py`:** cabeceras, palabra del backend («arriba»/«CAÍDO», hoy invisible para el
  guardián), líneas de `LLAMASWAP_*`, leyenda de estados y resumen final, del catálogo.
- **Idioma (REQ-019):** dos líneas nuevas en la cabecera, junto a `LLAMASWAP_EXE`/`HOME`:
  `Idioma: es (preferencia: <ruta de language.json>)` con los rótulos de
  `common.language.source.*` de B0a, y una línea `aviso:` por cada entrada de
  `i18n.current().warnings` con los textos de `common.language.warning.*`. **No** es un check nuevo
  (pregunta 4).
- **Remedio de D11:** si el origen es «preferencia» y el `language.json` guardado dice
  `"source": "variable"`, se imprime «para volver a seguir al sistema, borra `<ruta>` y ejecuta
  `install`». `LanguageResolution` no expone hoy ese `source` guardado (pregunta 5).

### 1.4 Formato de números (REQ-026)

En los ficheros de B1 no hay hoy ningún separador de miles (`:,` no aparece) y sí 14 decimales con
`:.Nf` más floats impresos tal cual («8.37 GiB»). Propuesta: una función
`i18n.format_number(value, decimals=0, *, language=None)` (es: `20.027` y `1,5`; en: `20,027` y
`1.5`) que usan **solo** los textos para personas. Nunca se localizan: la salida `--json`, lo que
se escribe en `config.yaml` (valores; los comentarios sí siguen el idioma), los argumentos de
entrada (`--vram-gb 15.5` sigue siendo punto) ni los ids de ventana. Las fechas siguen en ISO 8601
UTC (`format_instant`): son neutras y la persona las copia a `test-window add` (pregunta 6). Va en
`i18n.py` porque B2 y B4 la necesitan igual (pregunta 3).

### 1.5 Módulos de llama-swap, `benchmark`, `daemon` y los asignados por B0

`residency.py`, `topology.py`, `llamaswap_api.py`, `llamaswap_config.py`, `matrix.py`, `turn.py`,
`daemon.py`, `benchmark.py`, `test_windows.py`, `recompute.py`, `probes.py`, `deprecations.py`,
`entrypoint.py`: cada literal de salida pasa a `t("cli.<módulo>.…")` (o `doctor.probe.…` en
`probes.py`, cuyas líneas acaban en `doctor`). Casos especiales:

- `recompute.py`: `_MATCH_LABEL` y `_DISCARD_LABEL` pasan a claves (`cli.recompute_cost.match.exact`
  …). Sale la fila `sin_cruce | src/local_delegate/recompute.py` de «Texto de salida que traduce el
  frente B» en `rename-exceptions.md` (la única fila de B1 en esa sección).
- `entrypoint.py` (CRLF): el aviso de terminal interactiva importa `i18n` (solo stdlib, `config` y
  `hook_common`): no encarece el arranque del servidor.
- `daemon.py`: sus mensajes salen en el idioma del proceso daemon (preferencia de REQ-047).
- `llamaswap_config.py`: los comentarios que escribe en un `config.yaml` siguen el idioma; los
  números del YAML, nunca.
- Un literal que la red de tildes marca pero es **dato o patrón** (las expresiones regulares de
  `pair_sheet.py:300`, `:935-937`) no se cataloga: o se vuelve bilingüe (ver 1.6) o va a
  `uncatalogued_exceptions.json` con su clase y motivo.

### 1.6 Scripts `measure_cooldown.py`, `pair_sheet.py`, `analyze_benchmark.py` (LF)

Importan `local_delegate.i18n` (corren con el entorno del repo, como ya hacen sus tests) y sus
claves van en `cli.json` bajo `cli.script.<script>.*` (pregunta 2).

- `measure_cooldown.py`: solo cambia texto; la lógica de la medición P-4 (abierta hasta
  2026-12-14) no se toca.
- `analyze_benchmark.py`: rótulos de A-close-5 al catálogo.
- `pair_sheet.py`: la hoja `.md`/`.html` sale en el idioma del proceso, y el lector de la hoja
  acepta **las dos** formas (`si|sí|yes`, `parcial|partial`, `empate|tie`, `s/n`|`y/n`, «Inventa»
  e «Invents»…). La elección que `unblind --json` escribe en `human` pasa a valor de máquina en
  inglés (`tie`), y `analyze_benchmark.py` lee `empate` y `tie` para siempre (el corpus congelado
  `benchmarks/afinidad-2026-10/veredicto.json` tiene `empate`). Las filas de pair_sheet y de sus
  tests en «Entrada de interfaz escrita por una persona» pasan a «Lectura de formato viejo»
  (pregunta 7).

### 1.7 CI: `ci.yml`, `ci_gate.py`, `test_ci_gate.py` (LF)

- Trabajo `cli-python-matrix` en ubuntu, `strategy.matrix.python: ["3.11", "3.12", "3.13",
  "3.14"]` (una sola clave: el parser de `test_ci_gate.py` ya la expande), `fail-fast: false`,
  `uv sync --group dev` con `python-version: ${{ matrix.python }}`, sin Playwright, corre
  `tests/test_cli_english.py` y los tests de `--help` (`test_cli_renamed_names.py`). Cada celda,
  por su nombre, en `EXPECTED_JOBS`.
- `PYTHON_WITHOUT_WHEELS: dict[str, str]` en `ci_gate.py` (versión → fecha y motivo), vacío al
  nacer; `test_the_expected_jobs_are_exactly_those_of_ci_yml` resta esas celdas a lo declarado.
  `ci_gate.evaluate` ya ignora los trabajos no esperados (`ci_gate.py:204-215`), así que una celda
  excluida corre sin bloquear. 3.15 (pregunta 8).

### 1.8 Pendientes del guardián

`tests/data/uncatalogued_pending/cli.json` y `doctor.json` se vacían fichero a fichero en cada PR
(regla de B0b: un fichero solo sale cuando tiene al menos una aparición antes; al salir debe tener
cero). Al cerrar B1, los dos ficheros desaparecen y `SURFACE_OWNERS`/`test_the_pending_lists_are_well_formed`
se ajustan para aceptar la superficie ya vacía (o se deja el JSON con `files: []`; pregunta 9).

---

## 2. Qué se traduce y qué se queda

**Se traduce:** ayudas y armazón de argparse; resultados, errores, avisos y preguntas del CLI;
avisos de alias (`deprecations.py`); títulos, estados, detalles, remedios, cabeceras y resumen de
`doctor`; mensajes de consola de llama-swap, `benchmark`, `daemon`, `test-window`,
`recompute-cost`; comentarios que el CLI escribe en `config.yaml`; textos de los tres scripts y de
la hoja de `pair_sheet`.

**Se queda igual:** subcomandos, opciones, `dest`, `choices`, ids de check y de grupo, claves y
valores de `--json`, ids de ventana, rutas, nombres de variables, el prefijo `local-delegate:` de
los mensajes, fechas ISO 8601, valores numéricos en ficheros, prosa ya escrita en disco
(etiquetas de ventanas, REQ-033), README y `docs/wiki/`.

---

## 3. Partición en PR (mezclables por separado, en este orden)

| PR | Contenido | Textos | Sale de pendientes |
| --- | --- | ---: | --- |
| **B1a — armazón del CLI** | `argparse.json` (~45 msgid, unión 3.11–3.14), parche en `cli.py`, `i18n.format_number`, **todo** `cli.py`, `deprecations.py`, `entrypoint.py`, `test_windows.py`, `recompute.py`, `daemon.py`; `test_cli_english.py` con `test_argparse_msgids_covered`; `cli-python-matrix` + `ci_gate.py` + `test_ci_gate.py` | ~216 + 45 | esos seis ficheros |
| **B1b — `doctor`** | `doctor.json`, `checks.py`, `doctor.py`, `probes.py`, idioma y D11 en `doctor`, `test_wiki.py`, `test_doctor_english.py` | ~181 | `doctor.json` entero, `probes.py` |
| **B1c — llama-swap y `benchmark`** | `residency.py`, `topology.py`, `llamaswap_api.py`, `llamaswap_config.py`, `matrix.py`, `turn.py`, `benchmark.py` | ~181 | esos siete |
| **B1d — scripts** | `measure_cooldown.py`, `analyze_benchmark.py`, `pair_sheet.py` (con lectura dual de la hoja y de `human`), filas de `rename-exceptions.md` | ~150 | los tres; `cli.json` queda vacío |
| **B1e — control del detector** | 60 + 60 frases nuevas (sección 5) | — | — |

B1a va primero porque trae el parche, `format_number` y el trabajo de CI. B1b, B1c y B1d se
preparan en paralelo (ficheros disjuntos) pero se mezclan en serie: comparten `cli.json`/`en`, que
con una clave por línea y orden alfabético solo choca en claves vecinas. B1e va al final porque su
fuente inglesa es el catálogo **revisado y mezclado**; es pequeño a propósito: si falla, para sin
bloquear las traducciones.

---

## 4. Tests y su control positivo

| Test | Qué comprueba | Mutante → assert que debe dispararse |
| --- | --- | --- |
| `test_cli_english.py::test_argparse_msgids_covered` (B1a) | todo literal de `_()`/`ngettext()` del `argparse.__file__` en ejecución tiene clave en `argparse.json` de los dos idiomas | borrar `argparse.usage` → falla con el msgid `'usage: '` en el mensaje |
| `::test_help_in_spanish_has_no_english_frame` | `run(["--help"])` y el `--help` de cada subcomando, en `es`: sin «usage:», «options:», «show this help» | quitar el `with _argparse_in_language()` de `run()` → falla el caso español en «usage:» |
| `::test_help_in_english_has_no_spanish_catalog_text` (REQ-034) | en `en`, ningún fragmento fijo de un valor de `es/{cli,argparse}.json` que difiera del inglés aparece en la salida (fragmentos entre marcadores, con al menos una palabra de 3+ letras ausente del valor inglés, buscados por límite de palabra) | dejar una ayuda sin `t()` (texto español literal) → falla nombrando el fragmento |
| `::test_the_patch_is_restored` | tras `run(["--help"])`, `argparse._ is gettext.gettext` | quitar el `finally` → falla |
| `::test_errors_in_both_languages` | opción desconocida y argumento obligatorio ausente: «error:»/«los siguientes argumentos son obligatorios» en `es`, el inglés en `en` | borrar `argparse.error_line` de `es` → falla el caso español |
| `::test_number_format` (REQ-026) | `format_number(20027)` = `20.027` / `20,027`; `format_number(1.5, 1)` = `1,5` / `1.5`; y en una salida real de `recompute-cost` | cambiar el separador español → falla el assert de `20.027` |
| `::test_smoke_in_english` (REQ-034) | `test-window start/list`, `recompute-cost --dry-run`, `check-llamaswap` con config de ejemplo, en `en`: misma regla que la ayuda, y además ningún carácter `áéíóúñ¿¡` fuera de rutas y datos | dejar un `print` español → falla |
| `test_doctor_english.py` (B1b, REQ-022/034) | `doctor` con probes dobladas, en `en` y en `es`: mismos ids, mismo número de líneas de check, ningún texto `es` en la salida inglesa, `[MISS]` en `en` y `[FALT]` en `es` | devolver `"arriba"` literal en `doctor.py` → falla el assert del catálogo (el valor está en `es/doctor.json`), no el de tildes |
| `::test_doctor_shows_language_and_source` (REQ-019) | con `LOCAL_DELEGATE_LANG=en`: «variable»; con `language.json` falso: «preference» y la ruta; con valor no válido: el aviso | quitar la línea del idioma → falla; cambiar el origen por uno fijo → falla el caso «preferencia» |
| `::test_doctor_d11_remedy` | origen «preferencia» con `source: variable` guardado → remedio de D11; con `source: system` → no sale | invertir la condición → fallan los dos |
| `test_wiki.py` (REQ-032) | títulos de la wiki = `t_lang("es", check.title_key)` | cambiar un título en `es/doctor.json` sin su fila → falla `missing` |
| `test_ci_gate.py` (B1a) | matriz − `PYTHON_WITHOUT_WHEELS` = esperados | añadir 3.15 a la matriz sin añadirla a los esperados → falla el assert de conjuntos |
| `test_pair_sheet.py` / `test_analyze_benchmark.py` (B1d) | una hoja en `en` contestada en inglés y una en `es` contestada en español dan el mismo veredicto; `human: "empate"` y `"tie"` cuentan igual | quitar `empate` del lector → falla el caso del corpus viejo |
| Guardián de B0b | `cli.json`/`doctor.json` sin los ficheros traducidos | volver a meter `print("Hola")` en `cli.py` → falla `test_no_uncatalogued_text_outside_pending` |

Toda la suite corre en `es` por el fixture de B0a (REQ-043), así que los tests que hoy afirman
texto español siguen valiendo; los que afirmen decimales con punto en salida española cambian
(riesgo R3).

---

## 5. Control del detector (B1e, obligatorio, regla fijada aquí antes de ver resultados)

Ni quien redactó esta propuesta ni quien ejecute B1e abre `scripts/data/function_words.json` antes
de congelar el control.

**Fuentes:**

- **Español (60):** 30 valores de `es/cli.json` + `es/doctor.json` y 30 frases de `docs/wiki/*.md`
  (12 páginas), sin ninguna de las 20 del control de B0b.
- **Inglés (60):** valores de `en/cli.json` + `en/doctor.json`, de claves **distintas** de las 30
  españolas elegidas (para que ningún par sea traducción del otro).

**Regla de elegibilidad** (mecánica, en un script del scratchpad):

1. Se quitan marcadores (`{x}`, `%(x)s`, `%s`), spans entre comillas invertidas, URL y rutas.
2. Wiki: solo párrafos y elementos de lista (sin el marcador); fuera encabezados, tablas y bloques
   de código; se parte en frases por `(?<=[.!?])\s+`.
3. Elegible si queda entre 8 y 40 palabras separadas por espacios y al menos 8 tokens de
   `[a-záéíóúüñ]+` (el tokenizador del detector, no su lista).
4. Sin duplicados (texto normalizado en minúsculas).

**Selección:** se ordenan los elegibles de cada fuente por `sha256("<source>\n<text>")` y se toman
los primeros N. Ninguna decisión humana.

**Congelado:** `tests/data/detect_language_control_b1.json` (formato del de B0b, `_about` con esta
regla) entra en **un commit propio, anterior** a cualquier corrida del detector sobre él; su
`sha256` se anota en `waves/B1.md`. Después, el test: `MIN_ACCURACY_B1 = 0.98` (118 de 120; 117 no
pasa), `min_tokens=8`, y el control positivo permanente con las listas invertidas (< 98 %). El
control de B0b se conserva tal cual.

**Si no llega:** se para y decide la sesión principal. No se toca la lista de palabras.

---

## 6. Tamaño frente al plan y finales de línea

| | Plan | Medido |
| --- | --- | --- |
| Textos del paquete | ~550 + ~35 | 578 únicos (ya incluye los de una sola palabra) |
| Scripts | no contados | 150 |
| argparse | — | 39 msgid en 3.11 y 40 en 3.12 (medido); la unión con 3.13–3.14 se mide en la implementación, ~45 |
| Claves × 2 idiomas | — | ~775 × 2 |
| PR | uno | cinco (sección 3) |

**Finales de línea** (`git ls-files --eol`): **CRLF** `cli.py`, `entrypoint.py` (editar con
Python y `newline=""`, nunca `sed -i`); **LF** todos los demás: `doctor.py`, `checks.py`,
`test_windows.py`, `benchmark.py`, `residency.py`, `topology.py`, `llamaswap_api.py`,
`llamaswap_config.py`, `matrix.py`, `turn.py`, `daemon.py`, `recompute.py`, `probes.py`,
`deprecations.py`, `i18n.py`, los tres scripts, `ci.yml`, `ci_gate.py`, `test_ci_gate.py`,
`test_wiki.py`, `test_detect_language.py`, los JSON de `uncatalogued_pending/` y de `i18n/`, y
`rename-exceptions.md`. Los ficheros nuevos, LF.

---

## 7. Preguntas abiertas (con recomendación)

1. **Textos de `install`/`update`/`uninstall` que viven en `cli.py`** (57). El plan los da a B5,
   pero `cli.py` es un solo pendiente y B1 lo vacía. **Recomiendo** que B1 los catalogue en
   `cli.json` y que B5 se quede con `install.py`, `update.py` y `agents.py`. La alternativa (dejar
   `cli.py` pendiente hasta B5) deja sin guardián el CLI entero.
2. **Dónde van los textos de los tres scripts.** **Recomiendo** `cli.json` bajo `cli.script.*`
   (~15 kB más en la rueda, sin superficie nueva). Alternativa: un `scripts.json` fuera del
   paquete, que exige ampliar `i18n.catalog` y D5.
3. **`format_number` en `i18n.py`** (fichero de B0). **Recomiendo** añadirla ahí, registrado como
   desviación: B2 y B4 la necesitan igual y duplicarla abre dos fuentes.
4. **Idioma en `doctor`: línea de cabecera o check nuevo.** **Recomiendo** cabecera: un check
   cambia el total de 25 (y `test_wiki`, la wiki «las veinticinco piezas», `test_doctor`) y el
   código de salida. Contra: un valor no válido no cuenta como aviso en el resumen.
5. **El `source` guardado en `language.json` para D11.** `LanguageResolution` no lo trae.
   **Recomiendo** un campo opcional `stored_source` en `hook_common.LanguageResolution`, rellenado
   por `resolve_language` al leer el fichero (cambio pequeño en un fichero de B0/B3, como
   desviación). Alternativa: que `doctor` relea el fichero, duplicando el parser.
6. **Fechas en el CLI.** **Recomiendo** dejar ISO 8601 UTC en los dos idiomas: son la entrada de
   `test-window add` y no tienen ambigüedad. Si REQ-026 se lee como «fecha local por idioma», hay
   que decidirlo aquí.
7. **`pair_sheet`: hoja bilingüe y `human` en inglés.** **Recomiendo** lo de 1.6 (hoja en el
   idioma del proceso, lector de las dos formas, `tie` escrito, `empate` leído para siempre) en su
   PR propio. Alternativa mínima: traducir solo mensajes de consola y dejar la hoja en español
   (deja filas en «Entrada de interfaz» sin cerrar).
8. **Versiones de la matriz.** `pyproject.toml` declara 3.11–3.13 en clasificadores; el plan pide
   «hasta la última estable». **Recomiendo** 3.11–3.14 y comprobar al implementar si 3.15.0 ya
   salió (el calendario la ponía a primeros de octubre de 2026): si sale y falla solo la
   instalación, a `PYTHON_WITHOUT_WHEELS` con fecha y motivo. Los clasificadores no son de B1:
   ¿se añaden 3.14 (y 3.15) aquí o en la release?
9. **Pendientes vacíos.** **Recomiendo** borrar `cli.json` y `doctor.json` de `uncatalogued_pending/`
   y que `test_the_pending_lists_are_well_formed` exija los pendientes de las olas **aún
   abiertas** (B2–B5), no los seis de siempre.
10. **Residuo que ninguna red ve** (valores de diccionario sin nombre de rótulo, como «arriba»).
    **Recomiendo** cubrirlo con los tests de humo en inglés (catálogo + tildes) y una revisión a
    mano del volcado inglés de `--help` de cada subcomando y de `doctor`, guardada como evidencia.

---

## 8. Riesgos y contradicciones

- **R1. Plan contra fichero (pregunta 1):** «REQ-021 salvo `install`, `update` y `uninstall`» y
  «B1 vacía `cli.json`» no se cumplen a la vez mientras esos textos vivan en `cli.py`.
- **R2. Tamaño:** 728 textos + argparse, contra ~585 del plan; los 150 de los scripts no estaban.
  Por eso cinco PR.
- **R3. Coma decimal en español** (REQ-026) cambia salidas españolas de hoy («8.37 GiB» →
  «8,37 GiB») y los tests que las afirman. Hay que contarlos al implementar B1a; si son muchos, se
  pregunta antes.
- **R4. argparse de 3.13/3.14** no está instalado en esta PC (solo 3.10–3.12): la unión de msgid y
  el mecanismo del parche (que dependa de la variable global `_` del módulo) solo se verifican en
  la matriz del CI. Si una versión dejara de leer `argparse._` como global, el test del armazón
  español lo cazará en esa celda. En 3.14 la ayuda puede llevar color; los tests capturan sin TTY.
- **R5. Inventario viejo:** el proceso del plan parte de `i18n-inventory.csv`, anterior al
  renombrado; se usa el escáner del guardián (1.1).
- **R6. Medición P-4 abierta:** `measure_cooldown.py` cambia solo textos; cualquier cambio de
  lógica queda fuera de B1.
- **R7. Corpus congelado** con `empate` (`benchmarks/afinidad-2026-10/veredicto.json`): la lectura
  dual es obligatoria si `human` pasa a inglés.
- **R8. Detector de nombres a 0:** las claves nuevas están en inglés y `es/*.json` ya está cubierto
  por la fila comodín de B0a; las lecturas viejas de `pair_sheet` necesitan filas en «Lectura de
  formato viejo».
- **R9. Independencia del control:** se apoya en que la selección es mecánica y se congela en un
  commit anterior a la corrida; queda escrito en `B1.md` quién lo ejecutó y que no abrió la lista.
- **R10. Mismo proceso:** sin el `finally` del parche, los tests de los scripts verían argparse en
  español según el orden de ejecución (inestable con `xdist`).

---

## 9. Llamadas `local_*` hechas

| Tool | Para qué |
| --- | --- |
| `local_summarize` (`path` a `waves/B0a.md`) | desviaciones y pendientes para B1 |
| `local_summarize` (`path` a `waves/B0b.md`) | estado del guardián y del control del detector |
| `local_explain_code` (`path` a `cli.py`) | mapa del parser; salió truncado (20 de 63 kB) y sin líneas, así que el mapa se hizo con `grep` |

Total: 3. `spec.md`, `plan.md` y `research-i18n.md` se leyeron por franjas concretas (REQ y D
citados), porque aquí hace falta el texto literal. El conteo de textos lo dio el escáner del
propio guardián, no un modelo. `local_translate` no se usó: los borradores ingleses son trabajo
de la fase 2.

---

## 10. Decisiones aprobadas (sesión principal, 2026-10-14)

- **Partición:** cinco PR en serie, B1a → B1b → B1c → B1d → B1e. `plan.md` («#### B1») enmendado.
1. B1 traduce los 57 textos de `install`/`update`/`uninstall` que viven en `cli.py` (en B1a). Se
   enmienda el plan: B5 deja de poseerlos y conserva lo que no está en `cli.py`.
2. Los textos de los tres scripts van en `cli.json`, bajo `cli.script.*`.
3. `format_number` va en `i18n.py`, como desviación registrada. La coma decimal y el punto de miles
   en español los fija la spec (REQ-026): se aplican a la CLI, y B1a cuenta y ajusta los tests que
   afirman salidas como «8.37 GiB». Las salidas MCP (B2) siguen sin separador de miles y con punto
   decimal: `format_number` no puede romper ese modo.
4. El idioma en `doctor` va en una línea de cabecera, sin check nuevo.
5. Campo `stored_source` en `LanguageResolution` (B1b).
6. Fechas en ISO 8601 UTC en los dos idiomas.
7. `pair_sheet` como se propone: escribe `tie` y lee `empate` para siempre.
8. Matriz de 3.11 a 3.14, y 3.15 si ya es estable a 2026-10-14 (lo es: 3.15.0 salió el
   2026-10-09). Los clasificadores de `pyproject.toml` los añade B1a.
9. Se borran los pendientes vacíos y el test exige solo los de las olas abiertas.
10. Humo en inglés y revisión a mano de la salida, registrada en el `waves/B1x.md` de cada PR.
