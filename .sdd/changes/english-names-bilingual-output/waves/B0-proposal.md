# Propuesta de la ola B0: base de idioma, catálogo y guardianes

Fase 1 (proponer, no aplicar). Rama `sdd/english-names-b0`, sacada de `origin/main` (`a5c150e`).
No se ha editado nada del repo salvo este fichero. Fuentes: `plan.md` §B0 (líneas 1020–1064),
D5, D7, D8 y D10 (líneas 189–357), §4.2 (1444–1467); `spec.md` REQ-018, 019, 028 (con la enmienda
del 2026-10-14), 030, 031, 043, 045 y 047; `research-i18n.md` §1; el código actual.

Convenciones de esta propuesta: nombres, claves JSON, valores y códigos en inglés; los textos de
salida en español en `es/` y su par en `en/`. Todos los ficheros nuevos van en **LF**.

---

## 1. Diseño por fichero

### 1.1 `src/local_delegate/resources/hooks/hook_common.py` (existente, LF): `resolve_language` y `HOOK_TEXTS`

Es la única implementación de la regla (REQ-018, D7). Stdlib pura; `ctypes` y `locale` se
importan **dentro** de la función de Windows, para no cargar nada más en cada invocación de hook.

```python
LANGUAGES = ("es", "en")
LANGUAGE_PREFERENCE_FILE = "language.json"
# Gramática de REQ-019, sin distinguir mayúsculas.
LANGUAGE_GRAMMAR = re.compile(r"^(es|en)([-_]([A-Za-z]{2}|[0-9]{3}))?$", re.IGNORECASE)
UNDECLARED_LOCALES = frozenset({"", "c", "posix"})  # tras quitar «.codificación» y «@modificador»

# Textos de los hooks (REQ-030/031): los llena B3, en ASCII. El guardián de paridad ya los cubre.
HOOK_TEXTS: dict[str, dict[str, str]] = {"es": {}, "en": {}}


class LanguageResolution(NamedTuple):
    lang: str                      # "es" | "en"
    source: str                    # "variable" | "preference" | "system" | "fallback"
    pref_path: Path                # la ruta de language.json consultada, exista o no (REQ-047)
    warnings: tuple[tuple[str, str], ...]  # (código, detalle); sin prosa: la redacta quien la muestra


def parse_language(value: str | None) -> str | None:
    """Valor de REQ-019 → "es"/"en", o None si no es válido. Recorta espacios."""


def resolve_language(
    data_dir: Path,
    env: Mapping[str, str] = os.environ,
    platform: str = sys.platform,
    ui_lang: str | None = None,
) -> LanguageResolution: ...


def _system_language(env, platform, ui_lang) -> str | None:
    """Paso 3: lo que declara el sistema, o None si no declara nada / falla la consulta."""


def _windows_ui_language(kernel32=None) -> str | None:
    """`GetUserDefaultUILanguage()` → `locale.windows_locale` (o máscara de idioma primario)."""
```

Precedencia (el primer paso que da resultado decide):

1. **Variable:** `env.get("LOCAL_DELEGATE_LANG")`. Vacía o solo espacios = no puesta (sin aviso,
   ver pregunta 3). Válida según la gramática → `(lang, "variable")`. No válida → aviso
   `("invalid_variable", valor_crudo)` y se sigue.
2. **Preferencia:** `data_dir / "language.json"`. No existe → se sigue sin aviso. Error de lectura
   o JSON roto → aviso `("unreadable_preference", ruta)`. Objeto sin `lang` válido → aviso
   `("invalid_preference", ruta)`. Válido → `(lang, "preference")`. El campo `source` del fichero
   lo escribe y lo usa B5 (REQ-047, D11); B0 solo lee `lang`.
3. **Sistema:**
   - `platform == "win32"`: `ui_lang` si se inyecta; si no, `_windows_ui_language()`. **No** se
     consultan `LANG`, `LC_*` ni `LANGUAGE`.
   - Resto (Linux, macOS, y también `cygwin`/`msys`, que tienen semántica POSIX): locale
     efectivo = primer valor no vacío de `LC_ALL`, `LC_MESSAGES`, `LANG`. Se normaliza quitando
     `.codificación` y `@modificador` y se compara sin mayúsculas con `UNDECLARED_LOCALES`
     (así `C.UTF-8`, `C.utf8` y `POSIX` cuentan como «no declarado», ver pregunta 4). Si el efectivo
     está declarado y `LANGUAGE` tiene valor, manda su primer elemento no vacío (`es:en` → `es`);
     si no, manda el efectivo.
4. **Decisión:** lo obtenido empieza por `es` (sin mayúsculas, seguido de fin, `_`, `-`, `.` o
   `@`; ver pregunta 5) → `es`; cualquier otro valor → `en` con origen `"system"`. No se obtuvo
   nada (no declarado, error al consultar) → `("en", "fallback")`.

`_windows_ui_language(kernel32=None)`: `kernel32 or ctypes.windll.kernel32`; llama a
`GetUserDefaultUILanguage()` (LANGID), busca en `locale.windows_locale`; si no está, mira el
idioma primario (`langid & 0x3FF`: `0x0A` → `"es"`, `0x09` → `"en"`); cualquier excepción → `None`.
Nunca llama a `GetUserDefaultLCID`/`GetUserDefaultLocaleName` (formato regional). El parámetro
`kernel32` existe solo para inyectar un falso en los tests; es lo que permite distinguir «interfaz»
de «formato regional» en Linux.

Las tres funciones privadas son la «función» de D7 partida en piezas: el guardián de aislamiento
las declara como lista blanca explícita (pregunta 6).

Tamaño: ~120 líneas añadidas. Ninguna línea existente cambia salvo los imports (`NamedTuple`,
`Mapping`).

### 1.2 `src/local_delegate/i18n.py` (nuevo, ~120 líneas)

Importa solo stdlib, `config` y `hook_common` (no hay ciclo: `config` no importa `i18n`; ver riesgo
R7).

```python
LANGUAGES = hook_common.LANGUAGES
CATALOG_FALLBACK = "es"   # D5: si falta una traducción en ejecución, se muestra la española

def current() -> hook_common.LanguageResolution:
    """REQ-018 para este proceso, con `config.LOG_DIR`. Se cachea por proceso (daemon, stdio)."""
def reset() -> None:
    """Vacía la caché de `current()` y del catálogo. La llama el fixture de la suite."""
def lang() -> str: ...                                # current().lang
def t(key: str, /, **values: object) -> str: ...      # t_lang(lang(), key, **values)
def t_lang(lang: str, key: str, /, **values: object) -> str:
    """Texto de `key` en `lang`; si falta, el de CATALOG_FALLBACK; si falta en los dos, la clave
    (visible, no rompe; los guardianes lo impiden antes). Interpola con nombre (`{n}`) solo si se
    pasan valores."""
def catalog(lang: str) -> dict[str, str]:
    """Une `resources/i18n/<lang>/*.json` (planos, claves con puntos) vía importlib.resources."""
def argparse_gettext(msgid: str) -> str: ...
def argparse_ngettext(singular: str, plural: str, n: int) -> str: ...
```

`argparse_gettext` (D8): en `en` devuelve el msgid; en `es` busca el msgid entre los **valores**
de las claves `argparse.*` del catálogo inglés (índice inverso cacheado) y devuelve el valor
español de esa clave; si no hay clave, el msgid (caso «traducción ausente»). `argparse_ngettext`
elige singular o plural por `n == 1` y hace la misma búsqueda. En B0 no existe todavía
`argparse.json` (es de B1), así que en producción devuelven siempre el msgid; los tests las prueban
con un catálogo inyectado. B0 **no** instala el parche en `cli.py` (es de B1).

### 1.3 Catálogo `src/local_delegate/resources/i18n/{es,en}/common.json` (nuevos)

Formato: objeto JSON **plano**, una clave por línea, claves con puntos y primer segmento igual al
nombre del fichero (D5). Contenido inicial (lo que B0 necesita y comparten `doctor` y
`local_status`):

| Clave | es | en |
| --- | --- | --- |
| `common.language.source.variable` | variable | variable |
| `common.language.source.preference` | preferencia | preference |
| `common.language.source.system` | sistema | system |
| `common.language.source.fallback` | reserva | fallback |
| `common.language.warning.invalid_variable` | `LOCAL_DELEGATE_LANG` vale «{value}», que no es válido: se usa `es` o `en`, con o sin región. | `LOCAL_DELEGATE_LANG` is set to "{value}", which is not valid: use `es` or `en`, with or without a region. |
| `common.language.warning.invalid_preference` | El fichero de preferencia {path} no tiene un idioma válido y se ignora. | The preference file {path} has no valid language and is ignored. |
| `common.language.warning.unreadable_preference` | No se pudo leer el fichero de preferencia {path} y se ignora. | The preference file {path} could not be read and is ignored. |
| `common.output_language.source.output_variable` | variable de salida | output variable |
| `common.output_language.warning.too_long` | `LOCAL_DELEGATE_OUTPUT_LANGUAGE` pasa de {max} caracteres y se ignora. | `LOCAL_DELEGATE_OUTPUT_LANGUAGE` is longer than {max} characters and is ignored. |
| `common.output_language.warning.control_chars` | `LOCAL_DELEGATE_OUTPUT_LANGUAGE` tiene saltos de línea o caracteres de control y se ignora. | `LOCAL_DELEGATE_OUTPUT_LANGUAGE` contains line breaks or control characters and is ignored. |

Unas 12 claves × 2 idiomas. No hay código de B0 que las imprima: las usan B1 (`doctor`) y B2b
(`local_status`). Ojo: los valores sueltos en español («preferencia», «reserva»…) los marcaría el
detector de nombres del frente A (pregunta 9).

### 1.4 `src/local_delegate/config.py` (existente, LF)

- **`LOCAL_DELEGATE_LANG`:** solo registro en el inventario, porque quien la lee y valida es
  `resolve_language`. Una línea en el bucle de lecturas de arranque (`config.py:419-427`), con la
  función `language_variable()` que devuelve `_env("LOCAL_DELEGATE_LANG", "")`, sin uso en el
  paquete (mismo patrón que `HOOK_ENABLED`, `:228-233`). Así entra en `ENVIRONMENT_VARIABLES`
  (nombre actual de la tabla; antes `VARIABLES_DE_ENTORNO`) y la suite la aísla.
- **`LOCAL_DELEGATE_OUTPUT_LANGUAGE` (enmienda de REQ-028):** se lee **al llamar**, como
  `commit_language()` (`:415-416`), para que un test la fije con `monkeypatch.setenv` sin recargar,
  y entra en el mismo bucle de registro.

```python
OUTPUT_LANGUAGE_MAX_CHARS = 40

class OutputLanguage(NamedTuple):
    value: str          # "" = sin poner o no válida → se sigue al idioma vigente (lo decide B2b)
    problem: str | None # None | "too_long" | "control_chars" (código; el texto está en common.json)
    raw: str            # el valor crudo, para el aviso

def output_language() -> OutputLanguage:
    raw = _env("LOCAL_DELEGATE_OUTPUT_LANGUAGE", "")
    value = raw.strip()
    if not value:                       # vacía o solo espacios = el valor por defecto, sin aviso
        return OutputLanguage("", None, raw)
    if any(ch in "\r\n\x85  " or unicodedata.category(ch) in _CONTROL_CATEGORIES
           for ch in value):
        return OutputLanguage("", "control_chars", raw)
    if len(value) > OUTPUT_LANGUAGE_MAX_CHARS:
        return OutputLanguage("", "too_long", raw)
    return OutputLanguage(value, None, raw)
```

`_CONTROL_CATEGORIES = {"Cc", "Cf", "Zl", "Zp"}` (pregunta 7 sobre `Cf`). Valores válidos según
REQ-028: 1 a 40 caracteres tras recortar, sin saltos ni control (`fr`, `pt`, `de`, `it`,
`français`, `português do Brasil`…). Longitud en puntos de código. B0 no la usa: la usa B2b, que
también decide el texto y el origen («variable de salida») en `doctor`/`local_status`.

Tamaño: ~30 líneas.

### 1.5 `tests/conftest.py` (existente, LF)

- **`env_without_package_variables`** (sesión): tras el bucle de `delenv`, `mp.setenv(
  "LOCAL_DELEGATE_LANG", SUITE_LANGUAGE)` con `SUITE_LANGUAGE = "es"` como constante del módulo
  (REQ-043). Los tests de inglés y de detección la sobrescriben con su `monkeypatch`.
- **`isolate_runtime_logs`** (por test): además de `config.LOG_DIR`, `monkeypatch.setenv(
  "LOCAL_DELEGATE_LOG_DIR", str(tmp_path))` (REQ-043 b: los hooks lanzados como subproceso usan el
  mismo directorio) y `i18n.reset()` antes y después (la caché de `current()` no cruza tests).
  Comprobado: ningún test actual finge `LOCALAPPDATA`/`XDG_DATA_HOME`; los que tocan
  `LOCAL_DELEGATE_LOG_DIR` usan `setenv`/`delenv(raising=False)` y siguen valiendo
  (`test_f1_conformance.py:233-235`, `test_measure_adoption.py:221-227`).
- **Playwright (REQ-043; lo usa B4):**

```python
@pytest.fixture
def browser_locale() -> str:
    return "es-ES"          # los tests de inglés lo sobrescriben con parametrize o override

@pytest.fixture
def new_page(browser_locale):
    def make(browser, **kwargs):
        kwargs.setdefault("locale", browser_locale)
        return browser.new_page(**kwargs)
    return make
```

  B0 no toca `test_dashboard_ui.py` (17 llamadas a `browser.new_page`; las pasa B4).

Tamaño: ~30 líneas.

### 1.6 Guardián de aislamiento `tests/test_environment_isolation.py` (existente, LF; nombre que le dio A9a)

- `test_the_variable_inventory_is_not_empty`: añade `LOCAL_DELEGATE_LANG` y
  `LOCAL_DELEGATE_OUTPUT_LANGUAGE` a las obligatorias.
- `test_the_suite_runs_without_package_variables_defined`: excluye las variables que la suite fija
  a propósito y comprueba su valor: `LOCAL_DELEGATE_LANG == conftest.SUITE_LANGUAGE` y
  `LOCAL_DELEGATE_LOG_DIR == str(tmp_path)`. **Sin este cambio el fixture nuevo rompe este test**
  (ver riesgo R1).
- `_variables_read_by_hooks`: cuenta también `<cualquier>.get("LOCAL_DELEGATE_…"/"LD_HOOK_…")`
  y `<cualquier>["…"]` con nuestro prefijo, no solo `os.environ`. Sin esto, la lectura de
  `env.get("LOCAL_DELEGATE_LANG")` de `resolve_language` (entorno inyectado) es invisible al test de
  hooks.
- Nuevo `test_only_resolve_language_reads_the_system_language` (D7 y «implementación única» de
  REQ-018): AST sobre `src/local_delegate/**/*.py` (sin `vendor`) y los hooks; falla si aparece una
  constante `LANG`, `LANGUAGE` o `LC_*` (regex exacta `^(LANG|LANGUAGE|LC_[A-Z]+)$`, así que
  `LOCAL_DELEGATE_LANG` no cuenta), o un atributo `GetUserDefaultUILanguage`, `getlocale`,
  `getdefaultlocale` o `windows_locale`, fuera de la lista blanca
  `{"hook_common.py": {"resolve_language", "_system_language", "_windows_ui_language"}}`. Control
  dentro del propio test: el escáner tiene que encontrar al menos una aparición **dentro** de la
  lista blanca (si no, pasaría en vacío).

Tamaño: ~60 líneas añadidas, ~6 modificadas.

### 1.7 Guardián de textos fuera del catálogo `tests/test_no_uncatalogued_text.py` (nuevo, REQ-045)

**Alcance:** `src/local_delegate/**/*.py` (sin `vendor/`, incluidos los hooks) y los tres scripts que
B1 ya tiene asignados por sus rótulos (`scripts/measure_cooldown.py`, `scripts/pair_sheet.py`,
`scripts/analyze_benchmark.py`). El resto de `scripts/` es herramienta del repo, no se publica, y
queda fuera con su motivo escrito en el propio test (pregunta 11).

**Contextos de salida** (clasificación declarada en el guardián; un literal o la parte fija de una
f-string cuenta si está en uno de ellos):

1. argumentos de llamadas a sumideros: `print`, `*.write` (`sys.stdout/stderr`), `sys.exit`,
   `*.error` (argparse), `warnings.warn`, `emit`/`deny` (hooks), `*.append`/`*.extend` sobre
   listas de líneas que acaban impresas;
2. mensaje de `raise X(...)`;
3. argumentos con nombre de texto: `help`, `description`, `epilog`, `title`, `usage`, `remedy`,
   `detail`, `message`, `reason`, `hint`, `label`, `summary`;
4. valor de `return` (los textos de `checks.py`, `install.py`, `server.py`, `failures.py`… salen por
   ahí: medido con un prototipo, sin esta regla `checks.py` daba 0 apariciones y con ella 183);
5. constantes de módulo cuyo nombre termina en `_LABEL(S)`, `_TEXT(S)`, `_MESSAGE(S)`, `_REASON(S)`,
   `_HINT(S)` (diccionarios de rótulos como `_MATCH_LABEL` de `recompute.py` o `_STATE_LABELS`).

Un literal **no** cuenta si: es el primer argumento de `t`/`t_lang` (es una clave); es un docstring;
o es «de máquina» (todas sus palabras son identificadores: llevan `_ . / - : = { } %`, son
`MAYÚSCULAS`, `camelCase` o rutas/URL). Una sola palabra alfabética **sí** cuenta («Latencia»,
«Cargando», «ok»): no se depende de detectar español.

**Lista de pendientes** `tests/data/uncatalogued_pending/<surface>.json`, una por superficie y
con la ola dueña de D5. Formato: `{"surface": "cli", "owner": "B1", "files": ["src/…", …]}`.
Contenido inicial (de i18n §1, de las listas «posee» del plan y de un escaneo real de esta rama):

| Fichero | Dueña | Ficheros |
| --- | --- | --- |
| `cli.json` | B1 | `cli.py`, `benchmark.py`, `test_windows.py`, `residency.py`, `topology.py`, `llamaswap_api.py`, `llamaswap_config.py`, `matrix.py`, `turn.py`, `daemon.py`, `scripts/measure_cooldown.py`, `scripts/pair_sheet.py`, `scripts/analyze_benchmark.py`; **huérfanos propuestos:** `recompute.py`, `probes.py`, `deprecations.py`, `entrypoint.py` |
| `doctor.json` | B1 | `doctor.py`, `checks.py` |
| `mcp.json` | B2 | `server.py`, `failures.py`, `chains.py`, `sections.py`; **huérfano propuesto:** `questions.py` |
| `hooks.json` | B3 | `resources/hooks/hook_common.py`, `suggest_delegate_prompt.py`, `suggest_delegate_read.py`, `suggest_delegate_shell.py` |
| `panel.json` | B4 | `web/metrics.py`; **huérfanos propuestos:** `quota.py`, `valuation.py`, `attribution.py` (sus textos llegan al panel por `/api/stats`) |
| `install.json` | B5 | `install.py`, `update.py`, `agents.py` |

Los «huérfanos» tienen texto de salida real y **ninguna ola B los posee** en el plan (riesgo R3):
`probes.py:110-318` («no se encontró la ruta de llama-server…»), `questions.py:117-158`
(«Arrancar», «Modelo»), `recompute.py:353-404` («Transcripts leídos: …»), `quota.py:40-43`,
`valuation.py:40-42`, `deprecations.py:98-161` (avisos de alias), `entrypoint.py:45`,
`attribution.py:41` («no es Claude»). La propuesta los reparte por superficie (pregunta 2).

**Excepciones** `tests/data/uncatalogued_exceptions.json`: lista de `{"file", "text", "kind",
"reason"}` con `kind` en un conjunto cerrado (`contract_prefix`, `json_dump`, `path`, `id`,
`machine_name`, `format_only`). Coincide por fichero + literal exacto. Al nacer tendrá pocas
entradas (las de los ficheros no pendientes que el escaneo marque; el prototipo dio ~6 en
`config.py`, todas de máquina como `"Bearer "`, que la regla de «palabras de máquina» ya debería
absorber).

**Tests del guardián:**

- `test_no_uncatalogued_text_outside_pending`: cero apariciones fuera de pendientes y excepciones.
- `test_pending_lists_are_well_formed`: los seis ficheros de superficie, exactamente; cada ruta
  existe; ninguna ruta en dos superficies; `owner` coincide con D5.
- `test_every_pending_file_is_seen_by_the_scanner` (guarda de «llegó a comprobar algo»): cada
  fichero pendiente tiene al menos una aparición. Un pendiente sin texto sobra y se quita; un
  pendiente con texto que el escáner no ve indica que falta un contexto (pregunta 8 sobre el panel).
- `test_exceptions_are_live_and_have_a_reason`: cada excepción coincide con algún literal (una
  excepción caducada falla) y tiene motivo no vacío.
- `test_no_exception_is_human_text`: falla si el `text` de una excepción tiene dos o más palabras
  «de persona» seguidas, salvo `kind == "contract_prefix"`, cuyo texto tiene que estar en una tupla
  cerrada del propio test (`("[local-delegate error]",)`).
- Unitarios del clasificador sobre código sintético: `print("Hola")` → aparición;
  `raise ValueError("Latencia")` → aparición; `print(t("common.x"))` → nada; `help="--flag"` →
  nada.

### 1.8 Guardián de paridad `tests/test_i18n_parity.py` (nuevo, REQ-031 y REQ-030)

- Mismos ficheros en `es/` y `en/`; mismas claves; ningún valor vacío.
- Marcadores iguales como multiconjunto: `{nombre}`, `{0}`, `%s`, `%(nombre)s` (los de argparse).
- Identificadores entre comillas invertidas idénticos como multiconjunto.
- Cada clave empieza por el nombre de su fichero (`common.` en `common.json`); ninguna clave en
  dos ficheros.
- Las mismas reglas sobre `hook_common.HOOK_TEXTS` (`es` contra `en`), más **solo ASCII** en los dos
  (los hooks lo exigen; ver i18n §1 (e)). Hoy pasa en vacío; las funciones de comprobación se
  prueban aparte con diccionarios sintéticos (siguiente punto).
- Las comprobaciones son funciones (`check_pair(es, en) -> list[str]`) con tests unitarios sobre
  catálogos sintéticos: borrar una traducción, cambiar `{n}` por `{m}`, cambiar `` `local_extract` ``
  por `` `local_extrac` `` y añadir una tilde a un texto de hook, cada uno da su error.
- Toda clave literal pasada a `t(...)`/`t_lang(..., ...)` en el paquete existe en el catálogo
  (AST). Barato y evita la clave que se muestra tal cual en ejecución.
- Guarda de no vacío: el catálogo real tiene al menos 10 claves (las de `common.json`).

### 1.9 Detector de idioma (D10)

- **`scripts/detect_language.py`** (nuevo, stdlib, LF, ~90 líneas, con shebang y
  `git update-index --chmod=+x`): `detect(text, *, min_tokens=20, min_margin=0.15) ->
  Detection(lang, tokens, es_ratio, en_ratio)`; tokens = `re.findall(r"[a-záéíóúüñ]+", text.lower())`;
  proporción de tokens en cada lista; `unknown` si hay menos de `min_tokens` o el margen es menor
  que `min_margin`. CLI: `detect_language.py FICHERO…` imprime una línea JSON por fichero
  (`{"path", "lang", "tokens", "es_ratio", "en_ratio"}`), claves en inglés.
- **`scripts/data/function_words.json`** (nuevo, LF): `{"version": 1, "es": [...], "en": [...]}`,
  ~150 palabras por idioma, escritas a mano, **disjuntas** (fuera las ambiguas: `a`, `no`, `me`,
  `he`, `son`, `come`, `sin`…).
- **Control:** ver pregunta 10; hay una contradicción entre `min_tokens=20` y «frases de 8 o más
  palabras» (riesgo R5).

### 1.10 CI: `.github/workflows/ci.yml` (existente, LF) y `scripts/ci_gate.py` (existente, LF)

Trabajo nuevo, sin matriz y sin filtro `paths` (§4.2):

```yaml
  # REQ-043: la suite entera con el sistema en español. La otra corrida («CI en inglés») ya la dan
  # los `test` de la matriz (ubuntu corre con LANG=C.UTF-8). Una sola vez, en ubuntu y 3.11.
  test-lang-es:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      LANG: es_ES.UTF-8
    steps:
      - uses: actions/checkout@v7
      - name: Install uv
        uses: astral-sh/setup-uv@v7
        with:
          python-version: "3.11"
      - name: Generate the Spanish locale
        run: sudo locale-gen es_ES.UTF-8
      - name: Sync deps (with the ui group)
        run: uv sync --group dev --group ui
      - name: Install browser for the dashboard UI tests
        run: uv run playwright install --with-deps chromium
      # Guarda de «esto llegó a comprobar algo»: si el runner pisara LANG o pusiera LC_ALL, el
      # trabajo correría en verde sin estar en español.
      - name: Check the job really runs in Spanish
        run: python3 -c "import os; assert os.environ['LANG']=='es_ES.UTF-8'; assert not os.environ.get('LC_ALL'); assert not os.environ.get('LC_MESSAGES')"
      - name: Tests (pytest, LANG=es_ES.UTF-8)
        timeout-minutes: 10
        run: uv run pytest -q -n auto --dist loadgroup
```

Con Playwright incluido porque REQ-043 pide la suite entera «incluidos los tests de Playwright», y
con `CI=true` el módulo del panel no puede saltarse (`test_dashboard_ui.py:1317-1328`). Coste
estimado: ~3–5 minutos de runner por PR (pregunta 12).

`scripts/ci_gate.py:90-97`: añade `"test-lang-es"` a `EXPECTED_JOBS` (nombre actual; antes
`JOBS_ESPERADOS`) con una línea de comentario. `tests/test_ci_gate.py` **no** se toca:
`test_the_expected_jobs_are_exactly_those_of_ci_yml` ya ata los dos ficheros por conjuntos iguales,
y su parser admite un trabajo sin matriz. No hace falta tocar el ruleset (exige solo `ci-gate`).

---

## 2. Tests y control positivo de cada uno

Los mutantes se aplican en la fase 2 en una copia de trabajo, se registra **qué assert dispara** y
se deshacen. Los marcados «permanente» quedan como test (el mutante es parte de la suite).

| Test | Mutante | Qué falla (assert concreto) |
| --- | --- | --- |
| Gramática de REQ-019 (tabla: `es`, `EN`, `es-MX`, `en_US`, `es-419` válidos; `fr`, `english`, `es-`, `es_ESP`, `es-4190` no) | quitar `|[0-9]{3}` de la regex | el caso `es-419` → `parse_language("es-419") == "es"` |
| Caso 1: `LANGUAGE=es:en`, `LANG=en_US.UTF-8` → `es`/`system` | ignorar `LANGUAGE` | `res.lang == "es"` del caso 1 |
| Caso 2: `LANGUAGE=es`, `LANG=C` → `en`/`fallback` | honrar `LANGUAGE` aunque el locale no esté declarado | `res.lang == "en"` del caso 2 |
| Caso 3: `LC_ALL=en_US.UTF-8`, `LANG=es_ES.UTF-8` → `en`/`system` | leer `LANG` antes que `LC_ALL` | `res.lang == "en"` del caso 3 |
| Caso 4: `LANG=C.UTF-8` → `en`/`fallback` | quitar `c` de `UNDECLARED_LOCALES` | `res.source == "fallback"` del caso 4 (el idioma sale `en` igual: por eso se afirma también el origen) |
| Caso 5: Windows, interfaz `en-US` (LANGID `0x0409`) y formato regional `es-ES` (LCID `0x0C0A` en el `kernel32` falso) → `en` | `_windows_ui_language` llama a `GetUserDefaultLCID` | `res.lang == "en"` del caso 5 (nivel `_windows_ui_language` con el falso) |
| Caso 6: Windows, `LANG=en_US.UTF-8`, interfaz `es-ES` → `es` | consultar `LANG` también en `win32` | `res.lang == "es"` del caso 6 |
| Caso 7: preferencia `es`, sistema `en` → `es`/`preference` | intercambiar los pasos 2 y 3 | `res.lang == "es"` del caso 7 |
| Caso 8: `LOCAL_DELEGATE_LANG=en`, preferencia `es` → `en`/`variable` | intercambiar los pasos 1 y 2 | `res.lang == "en"` del caso 8 |
| Caso 9: `LOCAL_DELEGATE_LANG=fr`, `LANG=es_ES.UTF-8`, sin preferencia → `es`/`system` + aviso | tratar el valor no válido como `en` / no avisar | `res.lang == "es"` / `("invalid_variable", "fr") in res.warnings` |
| Extras: `LC_MESSAGES` gana a `LANG`; preferencia rota → aviso `unreadable_preference`; preferencia con `lang: "fr"` → `invalid_preference`; `kernel32` que lanza → `en`/`fallback`; LANGID fuera de `windows_locale` con primario `0x0A` → `es`; `pref_path` devuelto aunque no exista | borrar la rama correspondiente | el assert de cada extra |
| `i18n.current()` usa `config.LOG_DIR` (preferencia `en` en `tmp_path`, sin `LOCAL_DELEGATE_LANG`) | pasar `hook_common.log_dir()` en vez de `config.LOG_DIR` | `i18n.lang() == "en"` |
| Caché: `current()` cachea y `reset()` re-resuelve | quitar el `cache_clear` de `reset()` | el segundo `lang()` tras cambiar la preferencia |
| `t`/`t_lang` (catálogo inyectado): interpolación, traducción ausente → español, clave ausente → la clave | devolver `None` si falta la traducción | `t_lang("en", "x.only_es") == "solo es"` |
| `argparse_gettext`/`argparse_ngettext` (catálogo inyectado con `argparse.usage`) | `ngettext` devuelve siempre el singular | el caso `n=2` |
| REQ-043 a: `LOCALAPPDATA`, `XDG_DATA_HOME` y `HOME` falsos con `language.json` = `en`; `i18n.lang() == "es"` y `hook_common.log_dir() == tmp_path` | (control registrado, no mutante de código) el test **sigue en verde**, que es lo que pide la spec | — |
| REQ-043 b: hook-side en subproceso (`python -c` con el directorio de hooks en `sys.path`), sin `LOCAL_DELEGATE_LANG`, `language.json` = `es` en `tmp_path` y `en` en los directorios falsos → imprime `es` | quitar el `setenv("LOCAL_DELEGATE_LOG_DIR")` del fixture (corrida acotada, registrada) | `out == "es"` (sale `en`) |
| Fixture de `locale` (navegador falso que guarda los kwargs): por defecto `es-ES`; con `browser_locale` sobrescrito, `en-US` | quitar el `setdefault("locale", …)` | `kwargs["locale"] == "es-ES"` |
| Inventario: `LOCAL_DELEGATE_LANG` y `LOCAL_DELEGATE_OUTPUT_LANGUAGE` en `ENVIRONMENT_VARIABLES` | quitar la función del bucle de registro | `"LOCAL_DELEGATE_LANG" in config.ENVIRONMENT_VARIABLES` |
| Suite fija `es` y el directorio | el fixture fija `"en"` | `os.environ["LOCAL_DELEGATE_LANG"] == conftest.SUITE_LANGUAGE`… (y los asserts en español de B1+ después) |
| Implementación única | `os.environ.get("LANG")` en `cli.py` | `culprits == []` con `cli.py:<línea>` en el mensaje |
| `output_language()`: sin poner, vacía y `"   "` → `("", None)`; `" fr "` → `"fr"`; 40 caracteres → válido; 41 → `too_long`; `"fr\nen"` → `control_chars`; `"fr​"` → según pregunta 7 | cambiar `> 40` por `> 41` | el caso de 41 caracteres |
| Paridad (permanente, sintético): borrar traducción / cambiar `{n}` / cambiar identificador / tilde en hook | — | cada uno su error en `check_pair` |
| Paridad (real, registrado): borrar `common.language.source.system` de `en/common.json` | — | `test_same_keys` con la clave en el mensaje |
| Textos fuera del catálogo (registrado): `print("Hola")` en `config.py` (no pendiente) | — | `test_no_uncatalogued_text_outside_pending` con `config.py:<línea> 'Hola'` |
| Excepción con texto humano (permanente, sintético): `{"text": "Hola mundo", "kind": "id"}` | — | `test_no_exception_is_human_text` |
| Detector (permanente): con las listas `es`/`en` intercambiadas, el acierto del control baja de 98 % | — | `accuracy(swapped) < 0.98` |
| Detector: menos de `min_tokens` → `unknown`; margen < 0,15 → `unknown`; listas disjuntas y ≥ 120 palabras cada una | poner `min_margin=0` | el caso de margen |
| CI: trabajo en `ci.yml` sin entrada en `EXPECTED_JOBS` | añadir `test-lang-es` solo a `ci.yml` | `test_the_expected_jobs_are_exactly_those_of_ci_yml` (ya existe) |

Corridas de la fase 2 (bajo `pesado.sh`): suite entera con `LANG=en_US.UTF-8` y con
`LANG=es_ES.UTF-8` en esta PC (no discrimina en Windows, §4.2) y, para la que discrimina, en WSL
o en el CI del PR. Los controles de REQ-043 (sin el fixture de la variable, con `language.json`
falso) en WSL o en una rama de control, nunca en `main`.

---

## 3. Tamaño y finales de línea

| Pieza | Líneas nuevas (aprox.) |
| --- | ---: |
| `i18n.py` | 120 |
| `common.json` ×2 | 30 |
| `test_language.py` | 300 |
| `test_i18n_parity.py` | 160 |
| `test_no_uncatalogued_text.py` | 260 |
| `uncatalogued_pending/*.json` (6) + `uncatalogued_exceptions.json` | 80 |
| `detect_language.py` | 90 |
| `function_words.json` (una palabra por línea) | 310 |
| `test_detect_language.py` + datos de control | 200 |
| **Nuevas, total** | **~1 550** |

| Fichero existente | EOL (`git ls-files --eol`) | Líneas añadidas/modificadas |
| --- | --- | ---: |
| `src/local_delegate/resources/hooks/hook_common.py` | `i/lf w/lf` | ~120 |
| `src/local_delegate/config.py` | `i/lf w/lf` | ~30 |
| `tests/conftest.py` | `i/lf w/lf` | ~30 |
| `tests/test_environment_isolation.py` | `i/lf w/lf` | ~65 |
| `.github/workflows/ci.yml` | `i/lf w/lf` | ~30 |
| `scripts/ci_gate.py` | `i/lf w/lf` | 2 |
| **Existentes, total** | | **~275 en 6 ficheros** |

Frente al plan (~700 nuevas, < 60 modificadas en 4 ficheros): **más del doble** en nuevas y unas
cinco veces en modificadas, y 6 ficheros en vez de 4 (riesgo R6). Lo que lo explica: D7 pone
`resolve_language` (~120 líneas) dentro de `hook_common.py`, que el plan cuenta como «modificación»;
`ci.yml` y `ci_gate.py` no estaban en la cuenta de 4; la lista de palabras funcionales (~300 líneas
de datos) y los datos de control no se contaron; y el guardián de REQ-045 necesita los contextos
`return` y de constantes de rótulos para ver `checks.py`, `install.py` o `server.py`. Ningún
fichero de la lista toca CRLF; todos los nuevos van en LF (como sus vecinos `scripts/data/*.json`,
`resources/data/*.json` y `scripts/detect_spanish_names.py`). En ficheros LF se puede editar con
las herramientas normales; nada de `write_text` sin `newline=""` si alguno resultara CRLF.

---

## 4. Preguntas abiertas (con recomendación)

1. **¿Se parte B0 en dos PR?** Recomiendo **sí**: **B0a** (base: `i18n.py`, `common.json`,
   `resolve_language`, `config.py`, `conftest.py`, guardián de aislamiento, `test_language.py`,
   `test_i18n_parity.py`, trabajo `test-lang-es`) y **B0b** (guardián de REQ-045 con pendientes y
   excepciones, y el detector de D10). Son independientes, cada uno ronda las 800 líneas y así la
   revisión de la regla de idioma no se mezcla con el clasificador de contextos.
2. **Ficheros con texto de salida que ninguna ola B posee** (`recompute.py`, `probes.py`,
   `deprecations.py`, `entrypoint.py`, `questions.py`, `quota.py`, `valuation.py`,
   `attribution.py`). Recomiendo **asignarlos ya** como en la tabla de 1.7: los cuatro primeros a
   B1 (`cli.json`: `recompute-cost`, sondas de `benchmark`, avisos de alias y el mensaje del
   arranque), `questions.py` a B2 (`mcp.json`: lo ve el cliente MCP) y `quota.py`, `valuation.py` y
   `attribution.py` a B4 (`panel.json`: llegan por `/api/stats`), y anotar la ampliación en las
   listas «posee» del plan. Si la sesión principal prefiere otro reparto, solo cambia qué JSON los
   lleva.
3. **`LOCAL_DELEGATE_LANG` vacía o solo espacios.** Recomiendo tratarla como **no puesta, sin
   aviso** (igual que la enmienda de REQ-028 hace con `OUTPUT_LANGUAGE`), y recortar espacios antes
   de aplicar la gramática. La spec no lo dice.
4. **`C.utf8` y variantes.** La spec cita `C`, `POSIX`, `C.UTF-8` y el vacío. Debian y Ubuntu usan
   también `C.utf8`. Recomiendo **normalizar** (quitar codificación y modificador y comparar sin
   mayúsculas), que es la intención de la spec, y anotarlo en `verification.md` como lectura de la
   spec, no como cambio.
5. **«Empieza por `es`».** Literal, `est_EE` (estonio, código de 3 letras en `LANGUAGE`) daría
   español. Recomiendo `^es(?![a-z])` sin mayúsculas: mismo resultado en todos los casos reales y
   sin ese falso positivo.
6. **¿Una función o varias?** D7 dice «una sola función». Recomiendo **tres piezas** dentro de
   `hook_common.py` (`resolve_language`, `_system_language`, `_windows_ui_language`) con lista
   blanca explícita en el guardián: la de Windows necesita el `kernel32` inyectable para el caso 5,
   y una función única de 80 líneas sería peor de probar. La «implementación única» se mantiene: un
   solo fichero, una sola entrada pública.
7. **`OUTPUT_LANGUAGE` y caracteres de formato invisibles (`Cf`, p. ej. U+200B).** La spec solo dice
   «saltos de línea ni caracteres de control». Recomiendo **rechazar también `Cf`**: van al prompt
   del modelo y no tienen uso legítimo en un nombre de idioma.
8. **El escáner del panel (literales del JS y texto/atributos del HTML de `metrics.py`).** REQ-045 lo
   pide y el plan de B0 solo prueba el lado Python. Recomiendo que **B0 deje el escáner de Python
   completo** y una guarda que impida sacar `panel.json` de pendientes mientras el escáner del panel
   no exista (test: «si `web/metrics.py` no está pendiente, `scan_panel` tiene que estar
   implementado y ver ≥ 1 aparición con `metrics.py` mutado»), y que **B4**, dueña de `metrics.py`
   y que ya tiene `scripts/extract_dashboard_js.py`, escriba el escáner del panel. Alternativa: B0
   lo escribe entero (+~120 líneas).
9. **El detector de nombres del frente A marcará los valores sueltos de `es/common.json`**
   («preferencia», «reserva», «sistema»): `scan_resources_json` recorre todo `src/**/resources/*.json`
   (`detect_spanish_names.py:632-641`) y trata como término de máquina cualquier valor de una
   palabra. El frente A cerró con el detector a 0. Recomiendo **añadir en B0 una fila con comodín**
   a `rename-exceptions.md` (`* | src/local_delegate/resources/i18n/es/*.json | texto de salida del
   catálogo`), en una sección nueva «Catálogo de textos (frente B)», que el formato de excepciones ya
   admite (`fnmatch` sobre fichero y nombre). No se toca la sección «Texto de salida que traduce el
   frente B», que vacían las olas B. La alternativa (excluir `resources/i18n/es` en el detector)
   toca un fichero del frente A.
10. **Datos del control del detector.** D10 pide 60 + 60 frases «de `docs/wiki` y del propio
    `en/common.json` inicial», pero `common.json` tendrá ~12 entradas y casi ninguna llega a 8
    palabras; en el repo, el único inglés corrido es el diccionario `en` de `site/index.html` (20
    frases de ≥ 8 palabras, `site/index.html:588-640`). Recomiendo: fichero congelado
    `tests/data/detect_language_control.json` con 60 frases españolas de `docs/wiki` y, en inglés,
    las 20 de `site/index.html` más las entradas inglesas de ≥ 8 palabras de los catálogos según
    vayan existiendo; el test exige 20 + 20 en B0 y **60 + 60 en cuanto existan `cli.json` y
    `doctor.json`** (B1), con un assert que lo haga obligatorio entonces. Así no se escriben a mano
    frases que el propio autor de la lista de palabras sabe que pasarán (sería un control que no
    discrimina).
11. **Alcance del guardián de REQ-045 en `scripts/`.** Recomiendo solo los tres scripts que B1 ya
    tiene asignados; el resto de `scripts/` imprime para quien desarrolla el repo y no se publica.
    Confirmar que no se quiere `scripts/medir_enfriamiento.py` (P-4) dentro.
12. **¿`test-lang-es` instala Playwright?** Recomiendo **sí** (REQ-043 lo pide expresamente y con
    `CI=true` el módulo del panel no puede saltarse), a cambio de ~1–2 minutos más por PR.
13. **Red adicional por tildes.** Opcional y barata: en ficheros **no pendientes**, cualquier literal
    que no sea docstring con `áéíóúñ¿¡` fuera del catálogo falla. Cubre textos que salgan por un
    contexto que el clasificador no conoce. Recomiendo **añadirla** como test aparte, marcada como red
    complementaria (REQ-045 no depende de ella). Los hooks quedan fuera mientras sean pendientes (son
    ASCII a propósito).

---

## 5. Riesgos y contradicciones encontrados

- **R1 — El fixture nuevo rompe un test existente.** `test_the_suite_runs_without_package_variables_defined`
  (`tests/test_environment_isolation.py:34-39`) exige que **ninguna** variable del inventario esté
  definida; REQ-043 obliga a definir `LOCAL_DELEGATE_LANG` y `LOCAL_DELEGATE_LOG_DIR`, que entran en
  el inventario. Hay que cambiar el test a la vez (1.6); el plan no lo menciona.
- **R2 — El mutante del plan no mata uno de los dos casos que dice.** El plan (B0, «Tests y su
  control positivo») dice que intercambiar los pasos 2 y 3 hace fallar «preferencia `es` con el
  sistema en inglés» **y** «`LOCAL_DELEGATE_LANG=en` con preferencia `es`». El segundo lo decide el
  paso 1, que no se mueve: sigue en verde. Propuesta: un mutante por paso (tabla de §2); el caso 8
  lo mata el intercambio de 1 y 2.
- **R3 — Ficheros con texto de salida sin ola dueña** (pregunta 2). Sin asignarlos, la condición
  de cierre del frente B (pendientes vacíos) es inalcanzable o se cumple sacándolos sin traducir.
- **R4 — Vaciado en falso de la lista de pendientes.** Si una ola saca un fichero cuyo texto sale
  por un contexto que el clasificador no conoce, el guardián pasa sin haber visto nada. Mitigación
  propuesta: la guarda «cada pendiente tiene ≥ 1 aparición» (obliga a que el clasificador vea cada
  fichero **antes** de sacarlo), la regla de que una ola que añade un contexto lo hace con su
  control positivo, la red de tildes (pregunta 13) y los humos en inglés de REQ-034.
- **R5 — Contradicción en D10.** El detector responde `unknown` con menos de 20 tokens, y el control
  usa frases «de 8 palabras o más»: muchas darían `unknown`, que cuenta como fallo, y el 98 % sería
  inalcanzable. Propuesta: el control llama a `detect(…, min_tokens=8)`, y un test aparte comprueba
  que el umbral por defecto de 20 rige para la muestra de REQ-028 (respuestas largas).
- **R6 — Tamaño** muy por encima de la estimación del plan (§3); de ahí la pregunta 1.
- **R7 — Imports de `i18n.py`.** La tabla de riesgos del plan (`plan.md:1503`) dice que `i18n.py`
  «solo importa stdlib y `hook_common`», pero D7 exige que el paquete la llame con `config.LOG_DIR`.
  Importar `config` no crea ciclo (`config` no importa `i18n` y la propuesta lo mantiene así: los
  avisos de `config.output_language()` son códigos, no textos). Conviene corregir la frase del plan.
- **R8 — `test-lang-es` discrimina poco en B0.** Con el fixture fijando `es` y los tests de
  detección inyectando el entorno, en B0 este trabajo solo demuestra que nada lee `LANG` por su
  cuenta. Su poder real llega con B1 (asserts en español con `LANG` del sistema distinto). No es un
  defecto, pero conviene no presentarlo como control de REQ-043 hasta B1.
- **R9 — Runner de ubuntu y `es_ES.UTF-8`.** Si el locale no está generado, Python puede avisar al
  arrancar o caer en `C`. Por eso el paso `locale-gen` y la guarda de entorno del trabajo.
- **R10 — Subprocesos que heredan el directorio de la suite.** Con `LOCAL_DELEGATE_LOG_DIR` en el
  entorno, todo subproceso (hooks, CLI, daemon de prueba) escribe en `tmp_path`. Es lo que pide
  REQ-043 b y no se encontró ningún test que dependa de lo contrario, pero solo la corrida completa
  de la fase 2 lo confirma.
- **R11 — Python de Windows con `sys.platform` distinto de `win32`** (MSYS2/Cygwin): se tratan como
  POSIX y leen `LANG`, que en Git Bash suele valer `en_US.UTF-8`. Es coherente con su semántica, pero
  conviene anotarlo en la página de idioma de la wiki (B5).
- **Dependencias:** ninguna nueva (todo stdlib); no hace falta Socket.

---

## 6. Llamadas `local_*` hechas

| Tool | Para qué | Resultado |
| --- | --- | --- |
| `local_summarize(path=research-i18n.md, focus=…)` | resumir §4–§5 y las preguntas abiertas sin meter el fichero en contexto | útil; confirmó que hooks y panel no importan el catálogo y que no hay mecanismo de i18n previo |
| `local_explain_code(path=hook_common.py, question=…)` | cómo resuelve `log_dir()` el directorio, qué variables lee y qué emiten `emit`/`deny` | útil (avisó de truncado: leyó 20 027 de 25 416 caracteres; lo que hacía falta, `:356-370`, estaba dentro) |

Total: **2**. No se usaron más porque el resto de lecturas necesitaban texto literal (los nueve
casos de REQ-018, la gramática de REQ-019, la enmienda de REQ-028 y los nombres exactos de `config.py`,
`conftest.py`, `ci.yml` y `ci_gate.py`) y se leyeron por franjas con `offset`/`limit` o `grep`.
Los recuentos de literales por fichero los dio un prototipo de escáner en el scratchpad, fuera del
repo (contar con el programa, no a ojo). No se usaron tools de PyCharm.

---

## 7. Decisiones aprobadas (sesión principal, 2026-10-14)

1. **B0 se parte en dos PR.** **B0a**: `i18n.py`, `resolve_language` y sus piezas en
   `hook_common.py`, `HOOK_TEXTS` vacío, `{es,en}/common.json`, paridad, `config.py`
   (`LOCAL_DELEGATE_LANG` y `LOCAL_DELEGATE_OUTPUT_LANGUAGE` validada), fixtures de `conftest.py`,
   guardián de aislamiento ampliado y trabajo de CI `test-lang-es` con `ci_gate.py`. **B0b**:
   `test_no_uncatalogued_text` con `uncatalogued_pending/` y `uncatalogued_exceptions.json`, y el
   detector de idioma (`detect_language.py`, `function_words.json` y su test).
2. **Los ocho módulos sin dueña se asignan como se propuso:** B1 (`recompute.py`, `probes.py`,
   `deprecations.py`, `entrypoint.py`), B2 (`questions.py`) y B4 (`quota.py`, `valuation.py`,
   `attribution.py`).
3. `LOCAL_DELEGATE_LANG` vacía o solo espacios = no puesta, sin aviso.
4. `C.utf8` y variantes = «no declarado» (se normaliza).
5. «Empieza por `es`» = `^es(?![a-z])`, sin distinguir mayúsculas.
6. Tres funciones con lista blanca en el guardián.
7. `OUTPUT_LANGUAGE` rechaza también `Cf`.
8. El escáner del panel lo escribe B4; la guarda que impide sacar `metrics.py` de pendientes va en
   B0b.
9. Fila comodín en una sección nueva de `rename-exceptions.md`, con motivo. Al implementar se
   adelantó a **B0a** (el catálogo nace ahí y el detector debe seguir a 0 entre las dos mezclas).
10. Control del detector: 20 + 20 frases congeladas en B0b, 60 + 60 obligatorias desde B1, y el
    control llama con `min_tokens=8` (D10 corregida en el plan).
11. `scripts/medir_enfriamiento.py` **no entra** en el alcance: es el envoltorio de REQ-046 que se
    retira tras P-4; en B0b va a `uncatalogued_exceptions.json` con ese motivo. Los tres scripts de
    B1 sí entran.
12. `test-lang-es` instala Playwright.
13. Red por tildes como complemento, en B0b.

Riesgos: aceptados todos. `test_the_suite_runs_without_package_variables_defined` se arregla en
B0a; un mutante por paso de la precedencia; cada pendiente debe tener al menos una aparición antes
de salir (B0b); la frase de los imports de `i18n.py` se corrige en el plan.

El plan (`plan.md`, «#### B0») se enmendó con todo lo anterior: partición en B0a/B0b con sus listas
y tamaños, mutantes por paso, `min_tokens=8` en D10, imports de `i18n.py`, el arreglo del test del
fixture, los ocho módulos en las listas de B1, B2 y B4, y el orden de mezcla B0a → B0b → B1.
