# Plan: Renombrado a inglés de lo publicado y salidas en español e inglés

Fase `planning` del SDD `english-names-bilingual-output`. La spec (`spec.md`, 47 requisitos) está
aprobada desde el 2026-10-12 y este plan no la reabre: lo que resultara inejecutable iría a
«Desviaciones propuestas» (sección 8), con evidencia.

Insumos: `brief.md`, `spec.md`, `research.md`, `research-rename.md` (citado «rename §n»),
`research-i18n.md` («i18n §n»), `review.md` y `evidence/`. Tamaños medidos el 2026-10-12 sobre `main`
`8ec2f1d` (0.34.0): recuentos del inventario `evidence/rename-inventory-internal.csv` (apariciones
de los nombres en español, agrupadas por el fichero donde se definen por primera vez) y de
`evidence/i18n-inventory.csv` (literales de salida sin docstrings), con un script propio en el
scratchpad (`python -I`), más búsquedas de PyCharm para comprobar acoplamientos.

Convención: los nombres nuevos que fija la spec van como están. Los que la spec no fija y propone
este plan llevan **(plan)**. El agente de la ola puede ajustar un nombre **(plan)** si choca con
algo, y lo anota en `waves/<ola>.md`. Los nombres de la spec no se tocan.

---

## 0. Reglas comunes a todas las olas

Todo encargo de ola copia esta sección, o enlaza a ella y al `brief.md`.

1. **Tipo de agente:** `general-purpose` o `python-scripting-specialist` (los dos tienen
   `local_*`). Nunca `personal-sdd-implementer`, `personal-sdd-*-reviewer` ni
   `personal-sdd-researcher`.
2. **Primer paso:** cargar `local_*` y `mcp__pycharm__*` (las dos órdenes `ToolSearch` del brief),
   con `projectPath: "D:\\Projects\\local-delegate"`. Antes de empezar, decidir qué pasos se
   delegan (la tabla de la sección 2 da el mínimo por ola).
3. **Rama y checkout.** Cada ola va en su rama, `rename/<ola>-<tema>` en el frente A e
   `i18n/<ola>-<tema>` en el B. Una ola que usa `rename_refactoring` trabaja en el checkout
   principal `D:\Projects\local-delegate`, porque PyCharm no ve los worktrees, y solo puede haber
   una a la vez (la sección 1.3 da el orden). Una ola sin `rename_refactoring` puede ir en un
   worktree (`isolation: worktree`) cuando no comparte ficheros con la ola en curso.
4. **Propiedad de ficheros.** Cada ola solo edita los ficheros de su lista «posee». Si necesita
   tocar otro, se para y lo dice: no lo edita.
5. **Comandos pesados** (pytest completo, `uv sync`/`uv tool install`, build, Playwright, node) van
   siempre con `bash ~/.claude/scripts/pesado.sh <comando>`, de uno en uno en toda la máquina. La
   suite completa se lanza **una vez por ola**, al final, y su salida se vuelca a
   `evidence/<ola>/pytest-full.log`. Durante el trabajo se corren solo los ficheros de test
   afectados (`pytest tests/test_x.py -q`), y también con el cerrojo.
6. **Saltos de línea.** Antes de editar, se guarda `git ls-files --eol` de todo el repo en
   `evidence/<ola>/eol-before.txt`; al terminar, en `eol-after.txt`. La comparación (REQ-042) se
   hace con un script sobre **todos los ficheros del diff** (`git diff -M --name-status main`), no
   solo sobre los poseídos, porque `rename_refactoring` toca imports de otros ficheros. Cada fichero
   renombrado se compara con su nombre viejo, siguiendo la correspondencia `R<n>` de ese diff; el
   resultado va a `evidence/<ola>/eol-check.txt`, y tiene que dar 0 diferencias. Nada de `write_text` en
   ediciones masivas: los scripts abren con `newline=""` y escriben lo mismo que leyeron. Los
   ficheros CRLF de `src/` y `tests/` son estos: `cli.py`, `clients.py`, `entrypoint.py`,
   `install.py`, `preguntas.py`, `server.py`, `web/metrics.py`, `__init__.py`, `__main__.py`,
   `tests/test_clients.py`, `test_ctrl_c.py`, `test_dashboard_ui.py`, `test_preguntas.py`,
   `test_smoke.py` y `test_vendor.py`. También son CRLF `pyproject.toml`, `README.md` y
   `docs/wiki/Integration-install.md`. Un fichero tiene los dos finales a la vez:
   `tests/fixtures/residencia/pre-b10909-20260915.yaml`.
7. **Después de cada `rename_refactoring`** se revisa el diff (`git diff -U0`), buscando cadenas y
   comentarios que deban conservar el nombre viejo: lecturas de formato viejo, tablas de
   equivalencias, alias y fixtures de datos viejos. Si PyCharm cambió una de ellas, se repone.
   Después se ejecutan `get_file_problems` o `lint_files` sobre los ficheros tocados.
8. **Nada de datos privados en `evidence/`**: ni rutas de usuario, ni tokens, ni contenido de
   logs, solo recuentos.
9. **Fin de ola:** se mide el número de tests recogidos (`pytest --collect-only -q`, última línea).
   Se escribe el registro `waves/<ola>.md` (sección 2.3). El borrador del commit sale de
   `local_commit_msg(path=evidence/<ola>/diff.patch)` y se revisa. El commit va **firmado** y
   **sin coautoría de Claude**, porque la memoria del proyecto anula la atribución del harness. El
   agente no hace push ni abre el PR: lo hace la sesión principal, que espera a que
   `gh pr checks <n>` dé verde en todo, CodeQL incluido, resuelve los hilos de CodeQL por GraphQL
   y mezcla.
10. **Arreglar, no descartar:** un aviso de CodeQL se corrige en el código. Si es un falso
    positivo, se reescribe el código para que deje de dispararlo; nunca se descarta por API.
11. **Correspondencias antes de renombrar, y lotes (D13).** Ninguna ola renombra nada hasta que la
    sesión principal ha revisado su fichero de correspondencias `waves/<ola>-mapping.csv` y lo ha
    marcado como aprobado. Ese fichero lo genera un script a partir del inventario. Cada agente
    trabaja un **lote de ≤ 300 nombres** como mucho, y cada lote es un commit. Una ola con más
    nombres se parte en lotes, y cada lote lleva su propio fichero
    (`waves/<ola>-<lote>-mapping.csv`).

---

## 1. Olas

### 1.1 Decisiones de diseño que fija el plan (las usan varias olas)

**D1. Registro único de nombres obsoletos (REQ-001 a REQ-004, REQ-012).** Se crea un módulo nuevo,
`src/local_delegate/deprecations.py` **(plan)**, con la tupla `DEPRECATED_NAMES`. Cada entrada
lleva `kind` (`cli_command`, `cli_option`, `env_var`, `switch_file`, `legacy_write` o `retired`), `old`, `new`
e `introduced`. Mientras la versión no se publica, `introduced` vale `"UNRELEASED"`. En el PR de
release, `scripts/bump_version.py` cambia todo `"UNRELEASED"` de ese fichero por la versión que se
publica. El registro lo leen:

- el CLI, para el aviso en `stderr`, que nombra el nombre nuevo y la versión de retirada
  (`introduced` + 3 menores);
- `config` y `hook_common`, para las variables;
- el check `config.deprecated_names`;
- los tests de horizonte.

**Entradas retiradas frente a alias (cierra el riesgo de que A0 nazca en rojo).** El registro
distingue dos clases de entrada:

- **Alias con sucesor** (`new` distinto de `None`, `kind` ≠ `retired`). Funcionan con aviso, así
  que se les aplica el horizonte: `introduced` + 3 menores es la versión de retirada, y el test de
  horizonte falla cuando la versión del paquete llega a ella.
- **Nombres retirados sin sucesor** (`kind=retired`, `new=None`), como las tres variables del rol
  `fast`, retiradas en la 0.30.0. **No** funcionan: el check solo avisa de que siguen puestas. Se
  les fija un horizonte propio y explícito: un campo `warn_until` con la última versión en que el
  check avisa de ellas, que para las variables `fast` es la 0.37.x. El test de horizonte las mide
  contra `warn_until`, no contra `introduced`+3. Su aviso dice «ya no tiene efecto desde la
  0.30.0» y no anuncia ninguna retirada futura de su función.

Regla escrita en el propio módulo: toda entrada nueva es un alias con `introduced="UNRELEASED"`;
`kind=retired` solo vale para nombres que ya no tienen efecto, y siempre lleva `warn_until`.
Tests: una entrada retirada con `introduced=0.30.0` y `warn_until=0.37.0` no hace fallar el
horizonte en la 0.34.0, ni en la 0.35.0. Si se parchea la versión a 0.38.0, falla, con el nombre en
el mensaje. Y un alias con `introduced`+3 ≤ versión también falla.

Los hooks no importan el paquete, así que `hook_common.py` lleva su propia tabla mínima (las dos
variables de hooks y el interruptor). Un test exige que esa tabla sea igual al subconjunto
correspondiente de `DEPRECATED_NAMES`, para que no haya dos fuentes que puedan divergir.

**D2. Una sola tabla de equivalencias viejo→nuevo para los datos (REQ-005, REQ-006, REQ-009).** Se
crea `src/local_delegate/legacy_names.py` **(plan)**, con un diccionario por formato para claves y
valores, y dos funciones, `read_key(row, new, old)` y `normalize(fmt, row)`, que traducen lo viejo
a lo nuevo al leer. Todo lector del paquete pasa por ahí. Los hooks llevan en `hook_common.py`
solo las equivalencias que leen ellos (el estado de enfriamiento y los temporales), atadas a
`legacy_names.py` por un test de igualdad, como en D1. El panel **no** copia la tabla: el servidor
inyecta en el HTML el subconjunto que necesita el JS (los valores de motivo, causa y rol), igual
que hoy inyecta `__WEB_FONTS__`. Así el diccionario de etiquetas del JS acepta los dos valores sin
mantener una segunda copia.

**D3. Módulos renombrados en su ola temática, no al final.** `fallos` se renombra en A3,
`enfriamiento` en A4, `atribucion`, `coste`, `cuota`, `recalcular`, `valoracion` y `precios` en A5,
y `secciones` en A6. A8 renombra los que quedan: `cadenas`, `estado_json`, `preguntas` y `sondas`.
`anotar_llamada.py` es un hook y va en A2. Así ningún fichero se renombra dos veces. Toda ola que
renombre módulos o funciones de `src/` cumple el control por script de REQ-014: `--help` y una
corrida mínima sobre fixtures o, si eso no se puede, `get_file_problems`.

| Módulo actual | Nuevo **(plan)** | Ola |
| --- | --- | --- |
| `fallos` | `failures` | A3 |
| `enfriamiento` | `cooldown` | A4 |
| `atribucion` | `attribution` | A5a |
| `transcripts` | (ya en inglés) | A5a |
| `coste` | `cost` | A5b |
| `cuota` | `quota` | A5b |
| `recalcular` | `recompute` | A5b |
| `valoracion` | `valuation` | A5b |
| `precios` | `pricing` | A5c |
| `secciones` | `sections` | A6 |
| `cadenas` | `chains` | A8a |
| `estado_json` | `json_state` | A8a |
| `preguntas` | `questions` | A8a |
| `sondas` | `probes` | A8a |
| `resources/hooks/anotar_llamada.py` | `record_call.py` (spec) | A2 |

**D4. Valores y claves persistidos (REQ-005).** La tabla completa queda en `legacy_names.py`. Estos
son los nombres que fija el plan cuando la spec no los da:

- **Log de uso:** `bloqueo_id`→`block_id`, `secciones`→`sections`,
  `fallo_conexion`→`connection_failure`.
- **Clases de fallo `Clase`:** `peticion`→`request`, `capacidad_o_carga`→`capacity_or_load`,
  `timeout_lectura`→`read_timeout`, `configuracion`→`configuration`, `modelo`→`model`,
  `sin_clasificar`→`unclassified` y `enfriamiento`→`cooldown`.
- **Causas de conexión `CausaConexion`:** `rechazada`→`refused`, `sin_ruta`→`no_route`,
  `timeout_conexion`→`connect_timeout`, `credencial`→`credential`, `sin_respuesta`→`no_response`,
  `respuesta_invalida`→`invalid_response`, `url_invalida`→`invalid_url`,
  `transporte`→`transport` y `desconocida`→`unknown`.
- **Enfriamiento.** Claves: `fallos`→`failures`, `espera_s`→`wait_s`, `hasta`→`until`,
  `reentradas`→`reentries`, `modelo`→`model`, `evento`→`event`, `clase`→`class` y
  `tras_vencer`→`after_expiry`. Valores de evento: `entra`→`enter`, `reentra`→`reenter` y
  `limpia`→`clear`.
- **Atribución.** Claves: `entradas`→`entries`, `cruce`→`match` y `banco`→`bench`. Valores:
  `exacto`→`exact`, `ventana`→`window`, `ambiguo`→`ambiguous` y `sin_cruce`→`no_match`.
- **Telemetría de hooks.** Claves: `motivo`→`reason`, `bloqueo`→`block`, `camino`→`route`,
  `rutas`→`paths` y `oferta`→`offer` (`offer` solo se lee). Valores: `encendido`→`on`,
  `acotada`→`bounded`, `codigo`→`code`, `pequeno`→`small`, `backend_ausente`→`backend_missing`,
  `modelo_enfriado`→`model_cooled`, `prosa_grande`→`large_prose`,
  `no_es_volcado`→`not_a_dump`, `sin_fichero`→`no_file`, `no_es_prosa`→`not_prose`,
  `bloqueo_apagado`→`block_off` y `mcp_ajeno`→`foreign_mcp`.
- **`cost-aggregates`:** las 21 claves de rename §1c (p. ej. `cotejo`→`check`,
  `veredicto`→`verdict`, `pasa|falla`→`pass|fail`, `fuente`→`source`, `rechazo`→`rejection`,
  `marcas`→`marks`). Las tres marcas pasan a valor de máquina: `low_bound`, `check_only` y
  `reset` (REQ-033).
- **`prices.json`/`density.json`:** `familia: nueva|anterior`→`family: new|previous`, y el resto de
  claves de rename §1c.
- **`vendor.json`:** `_acerca_de`→`_about` y `_procedencia`→`_provenance`.
- **Salida de `benchmark`:** `procedencia`→`provenance`, `descartada`→`discarded`,
  `descartada_motivo`→`discard_reason`, `truncado_repetido`→`repeated_truncation` y
  `anulada`→`voided`.

**D5. Catálogo de textos (REQ-030; resuelve i18n §5).** Se elige la **opción B**: un catálogo por
claves en JSON, **partido por superficie**: `src/local_delegate/resources/i18n/<lang>/<surface>.json`
**(plan)**, con `<lang>` igual a `es` o `en`. Cada superficie es un fichero, y cada fichero tiene
una sola ola dueña:

| Fichero | Ola dueña |
| --- | --- |
| `common.json` | B0 |
| `cli.json` | B1 |
| `argparse.json` | B1 |
| `doctor.json` | B1 |
| `mcp.json` | B2a |
| `tools.json` (resumen de cada tool para el panel) | B2b |
| `panel.json` | B4 |
| `install.json` | B5 |

Las claves llevan puntos y el primer segmento es la superficie (`cli.recompute_cost.done`); la
interpolación va con nombre (`{n}`). Un test exige que cada clave esté en el fichero de su
superficie y que dos ficheros no repitan clave. La lista de pendientes del guardián de REQ-045
también se parte por superficie (`tests/data/uncatalogued_pending/<surface>.json`), con la misma
ola dueña. Cómo llega el catálogo a cada sitio:

- **Python:** lo carga `src/local_delegate/i18n.py` **(plan)** con `importlib.resources`, a través
  de `t(key, **kw)` y `t_lang(lang, key, **kw)`.
- **Panel:** el servidor inyecta en el HTML el subconjunto `panel.*` de **los dos idiomas**.
- **Hooks**, que no importan el paquete: llevan su diccionario `HOOK_TEXTS = {"es": {...}, "en":
  {...}}` dentro de `hook_common.py`, con las mismas reglas de paridad (REQ-031).

Por qué B y no A ni C: A dejaría como clave el texto en español, que el guardián de REQ-045 vería
como literal humano fuera del catálogo, y C añade una cadena de compilación `.mo` que no existe.
Con B, Python y el panel tienen una sola fuente. Si falta una traducción en tiempo de ejecución,
se muestra la española (caso límite de la spec).

**D6. Textos que redacta el servidor para el panel (REQ-025; lo decide el plan).** Gana
**`?lang=es|en` en los `/api/*` que devuelven prosa**: `/api/stats`, `/api/events`, `/api/hooks`,
`/api/status`, `/api/system` y `/api/backend*`. El servidor sigue redactando con
`t_lang(lang, …)`: es la única fuente y se conserva la regla de la SDD anterior, según la cual el
JS no redacta los textos de una causa. El JS añade el idioma del selector a cada petición y, al
cambiar el selector, pide un refresco inmediato. Sin `lang`, el servidor usa el idioma de su
proceso: un JS viejo contra un daemon nuevo sigue funcionando. Un `lang` no válido se trata como
si faltara. Lo que no viene del servidor (KPI, diálogos, `<title>`) sale del catálogo inyectado.
Se descarta que el servidor mande claves y el JS las redacte, porque duplicaría la lógica de
redacción en JS y abriría dos fuentes.

**D7. Detección de idioma (REQ-018).** Una sola función,
`resolve_language(data_dir, env=os.environ, platform=sys.platform, ui_lang=None)`, dentro de
`hook_common.py`. Devuelve `(lang, source, pref_path, warnings)`. En Windows, el idioma de interfaz
se obtiene con `ctypes.windll.kernel32.GetUserDefaultUILanguage()` y se mapea con
`locale.windows_locale`: sin procesos ni red. El parámetro `ui_lang` permite inyectar ese idioma
en los tests. El paquete la llama con `config.LOG_DIR` y la expone como `i18n.current()`, que se
cachea por proceso en el daemon y en los servidores por stdio. Los hooks la llaman en cada
invocación con el directorio que ya resuelven. El guardián de aislamiento de entorno se amplía:
falla si alguna lectura de `LANG`, `LC_*` o `LANGUAGE`, o una llamada a
`GetUserDefaultUILanguage`, aparece fuera de esa función.

**D8. El armazón de argparse (REQ-021).** argparse llama a `_()` y `ngettext()` del propio módulo.
El CLI instala, solo en su proceso y antes de construir el parser, `argparse._ = i18n.argparse_gettext`
y `argparse.ngettext = i18n.argparse_ngettext`. Las dos buscan el msgid inglés de argparse en las
claves `argparse.*` del catálogo: en inglés devuelven el msgid y en español su traducción
(«uso: », «opciones», «muestra esta ayuda y sale», «error: », «los siguientes argumentos son
obligatorios: %s»…).

El paquete admite cualquier Python desde la 3.11 y `uv tool install` suele tomar el más nuevo, así
que **no** se fija una lista de msgid de una versión. Las cosas se hacen así:

- **Test con los msgid del argparse en ejecución.**
  `tests/test_cli_english.py::test_argparse_msgids_covered` lee por AST `argparse.__file__` del
  intérprete que corre la suite y extrae todo literal pasado a `_()` y a `ngettext()`. Falla si
  alguno no tiene clave en `argparse.json` de los dos idiomas. Control positivo: borrar
  `argparse.usage` del catálogo hace fallar el assert con el msgid que falta.
- **El catálogo cubre las versiones admitidas.** `argparse.json` lleva los msgid de todas las
  versiones de Python que admite el paquete (unión). Uno que en una versión ya no exista se queda:
  no estorba.
- **CI en todas las versiones que admite el paquete.** B1, la ola que crea el test, añade a
  `ci.yml` el trabajo `cli-python-matrix` (sección 4.2). Ese trabajo corre solo los tests del CLI,
  sin Playwright, en ubuntu, con una matriz de Python que va de la 3.11 a la última estable
  publicada. **Cada celda** de la matriz (`cli-python-matrix (3.11)`, `cli-python-matrix (3.12)`…)
  figura por su nombre en los trabajos esperados de `ci_gate.py`, así que bloquea la mezcla. B1 es
  la dueña de `ci.yml` y de `ci_gate.py` en esta tarea, fija la lista con las versiones estables que
  existan cuando se escriba y la anota en `waves/B1.md`. Cuando sale una versión estable nueva, se
  añade en los dos sitios a la vez.
  - **Test de coherencia:** `tests/test_ci_gate.py` **(plan)** lee la matriz de `ci.yml` y exige
    que los trabajos esperados de `ci_gate.py` sean exactamente los nombres que genera esa matriz,
    salvo las versiones de la lista de exclusión. Control positivo: añadir una versión a la matriz
    sin añadirla a los esperados hace fallar el test.
  - **Política para la versión más nueva sin wheels.** Nada de `continue-on-error` a nivel de
    trabajo, porque `ci_gate.py` (`:196-207`) da por mala una conclusión que no sea
    `success`/`skipped`. Mientras sus dependencias no tengan wheels, esa versión va en una lista de
    exclusión explícita dentro de `ci_gate.py` (`PYTHON_WITHOUT_WHEELS` **(plan)**, con fecha y
    motivo) y su celda **no** figura en los trabajos esperados: corre, pero no bloquea. La ola
    que la añade lo anota en su registro, y la versión sale de la lista en cuanto la instalación
    funciona. El fallo de un test nunca se tapa así: la exclusión solo vale si lo que falla es el
    paso de instalación, y eso se comprueba en el log de la celda antes de añadirla.
- **Red en ejecución.** Si en una máquina aparece un msgid sin traducir, `argparse_gettext`
  devuelve el inglés: es el caso límite «traducción ausente», y el test de la siguiente corrida del
  CI con esa versión lo caza.

**D9. Fronteras de tramo (REQ-041).** Se crea `scripts/data/measurement_boundaries.json` (spec) con
dos campos:

- `package_version_after`: la primera versión del lado «después» para `usage-*.jsonl`;
- `hook_hashes_after`: referencia a `scripts/data/hook_hashes_after.json`, un fichero aparte con el
  conjunto de hashes por script; es de B3, para que no comparta fichero con B2;

**Regla de las filas sin versión (hallazgo 4 de la ronda 2):** una fila de `usage-*.jsonl` **sin
versión es siempre del tramo «antes»**, sea cual sea su fecha. **Enmienda del 2026-10-14 (decisión
de la sesión principal en B2b-2):** la versión es la clave `v` que toda fila lleva desde F1, no una
clave nueva `package_version` (la spec la daba como «propuesto», y habría duplicado `v`); por eso una
fila sin versión es anterior a F1. La spec ya lo recoge (enmienda del
2026-10-12, `spec.md:562-563`), así que no hay fecha de reserva ni campo para ella. Test en B2b: una fila sin versión y con fecha posterior a la frontera
cae en «antes». Control positivo: clasificar por fecha hace fallar ese caso.

**`hook_hashes_after.json` lo crea B3, después de B2b.** Mientras no exista, el lector de fronteras
lo lee como un conjunto vacío: no hay frontera de hooks y todo evento de telemetría cae en «antes»,
igual que hoy. B2b no consume nada que produzca una ola posterior. Test en B2b: sin el fichero, el
lector no da error y devuelve un conjunto vacío.

Las filas de uso llevan la versión en `v` desde F1; B2b no añade clave (enmienda del 2026-10-14).

**El conjunto de hashes «después» solo crece.** En cada PR de release,
`scripts/bump_version.py --boundaries` **añade** al conjunto de cada script el hash actual de
`resources/hooks/` (unión acumulativa) y **nunca quita** ninguno. Así, en la 0.37.0 siguen dentro
los hashes de la 0.36.0, y los eventos de una máquina que se quede en la 0.36.0 no vuelven a
«antes». Test (B3): con un conjunto que ya tiene el hash de una versión anterior, una regeneración
tras cambiar un hook conserva el viejo y añade el nuevo. Control positivo: una regeneración que
sustituye el conjunto en vez de unirlo hace fallar el assert del hash viejo.

**Scripts que comparan periodos** (enumeración que pide REQ-041), revisados con `local_extract`
sobre cada uno y comprobados con `search_text("--desde", scripts/)`:

- **`scripts/medir_adopcion.py`** compara tramos de adopción con `--desde`. **Entra.**
- **`scripts/experimento_adopcion.py`** compara variantes de hook dentro de un banco, no periodos
  del log. No entra.
- **`scripts/medir_resumen_estructurado.py`** mide una corrida etiquetada. No entra.
- **`scripts/measure_slowness.py`** lee `usage-*` en una sola ventana (`--since/--until`) y no
  compara antes y después. No entra. No lee claves en español (`search_regex` sin coincidencias),
  así que tampoco necesita lectura dual.
- **`scripts/medir_enfriamiento.py`** es la medición P-4, de una sola ventana, y no mide la
  calidad del modelo. No entra en REQ-041; su lectura dual va por REQ-007.

Conclusión: solo `medir_adopcion.py` lee las fronteras. Si aparece después otro script que
compare periodos, entra por el mismo test.

**D10. Detector de idioma y muestra de REQ-028 (fijados antes de B2).**

- **Detector:** `scripts/detect_language.py` **(plan)**, sin dependencias. Mide la proporción de
  palabras funcionales de una lista cerrada (unas 150 por idioma, escritas a mano y versionadas en
  `scripts/data/function_words.json`) y responde `es`, `en` o `unknown` (si hay menos de 20 tokens
  o un margen menor de 0,15).
- **Su control:** 60 entradas españolas y 60 inglesas del catálogo de B0/B1 (las de 8 palabras o
  más) se clasifican con un acierto de al menos el 98 %, llamando al detector con
  `min_tokens=8` (con el umbral por defecto de 20, casi todas darían `unknown`; corregido el
  2026-10-14). En B0b el control son 20 + 20 frases congeladas con como mucho 1 fallo en 40
  (≥ 97,5 %), y **no es independiente**: «ambos» y «casi» entraron en la lista española a la vista
  de sus dos fallos (38/40 antes del ajuste; 0/40 con las listas invertidas). El control de verdad
  es el de B1: 60 + 60 frases **nuevas**, congeladas antes de ver la lista, con ≥ 98 % (como mucho
  2 fallos en 120); ahí ya no se ajustan las listas a la vista de los fallos, y si no llega, se
  decide en B1. Si se invierten las dos listas de
  palabras funcionales, el control falla.
- **Control B1 a 8 tokens: FALLIDO (116/120, 2026-10-14).** El de `8be7ef7`
  (`tests/data/detect_language_control_b1.json`) se queda tal cual, como registro. Los 4 fallos son
  `unknown`, con 0 confusiones de idioma: con 8 tokens una sola palabra funcional da 0,125 < 0,15, y
  hay rótulos de catálogo sin ninguna. Límite conocido: el detector se abstiene en textos cortos.
- **Regla del control nuevo (decisión del usuario del 2026-10-14, fijada antes de aplicarla):**
  60 + 60 frases con **≥ 20 tokens** `[a-záéíóúüñ]+` (el umbral del uso real, el `min_tokens=20` de
  la muestra de REQ-028) y, como en §5, como mucho 40 palabras separadas por espacios. Misma
  limpieza, mismas fuentes (es: 30 de `es/cli.json` + `es/doctor.json` y 30 de `docs/wiki/*.md`;
  en: 60 de `en/cli.json` + `en/doctor.json` de claves distintas de las 30 españolas), sin
  duplicados y con el mismo orden por `sha256("<source>\n<text>")` de `B1-proposal.md` §5,
  **excluyendo las 120 del control fallido y las 40 de B0b**. Se congela en
  `tests/data/detect_language_control_b1_20.json`, en un commit propio y anterior a la corrida. El
  detector se mide con `min_tokens=20` y el margen de siempre (0,15): ≥ 98 % (como mucho 2 fallos
  en 120). Si una fuente no da lo que pide, se para y se decide la ampliación de fuentes antes de
  elegir nada.
- **Ampliación de fuentes (decisión del usuario del 2026-10-14, fijada antes de traducir nada):**
  los catálogos dan 26 españolas y 7 inglesas, así que:
  - **Español (60):** los 26 elegibles del catálogo y 34 de la wiki, en orden de sha256 con la
    regla de 20 tokens de arriba.
  - **Inglés (60):** de las frases elegibles de la wiki (≥ 20 tokens, ≤ 40 palabras) que no estén
    entre las 34 españolas, ni en el control fallido, ni en B0b, en orden de
    `sha256("<source>\n<text>")`, se traducen **de una en una** con
    `local_translate(text=…, target_lang="inglés")`. La traducción se guarda **tal cual, sin
    editar**: si trae restos en español, es señal del control y no se limpia. Entra si, tras la
    misma limpieza, tiene ≥ 20 tokens y ≤ 40 palabras; si no, se descarta y se pasa a la siguiente
    en orden de sha256 (regla fija, no a juicio). Una llamada que falle con
    `[local-delegate error]` se reintenta una vez; si vuelve a fallar, se descarta (anotado) y se
    pasa a la siguiente. No se mira el resultado del detector en ningún momento antes de congelar.
  - **Por frase inglesa se guarda:** frase española de origen (fichero y línea), sha256 del origen,
    traducción literal, sha256 de la traducción y modelo o rol, si `local_translate` lo indica.
  - **Límite conocido:** el inglés de este control es **traducción automática** de textos del
    dominio del proyecto, no prosa escrita por personas.
- **Muestra:** `tests/fixtures/lang_sample/` **(plan)**, con 5 documentos por tool y por idioma de
  origen, sin datos de terceros:
  - **`local_summarize`:** como textos en español, 5 extractos de `docs/wiki/` (2–6 kB cada uno);
    como textos en inglés, 5 piezas en inglés que se escriben para la muestra (descripciones de
    tool de B2 y entradas en inglés del catálogo, agrupadas por tema).
  - **`local_lint_summary`:** en español, 5 logs de pytest con mensajes de assert en español,
    sacados de la propia suite; en inglés, 5 logs de pytest y ruff con mensajes en inglés.
  - **`local_explain_code`:** en español, 5 ficheros `.py` de la 0.34.0 con identificadores y
    comentarios en español (`git show 8ec2f1d:<ruta>`); en inglés, 5 ficheros del repo ya
    renombrado con comentarios en inglés.
  - **`local_describe_image`:** 5 capturas de `site/index.html` en ES y 5 en EN. El sitio ya es
    bilingüe, y las capturas se hacen con Playwright bajo el cerrojo.
- **Corrida:** con el idioma vigente en `en` se mandan los documentos en español, y con `es` los
  ingleses: 4 tools × 5 documentos × 2 idiomas = 40 llamadas, dentro de una ventana de prueba.
- **Criterio (el de la spec, una sola regla):** para **cada tool y cada idioma vigente**, al menos
  el 90 % de las respuestas en el idioma vigente. Con 5 documentos por tool e idioma, eso es **5 de
  5**. Una respuesta que el detector clasifica como `unknown` cuenta como fallo. No hay otra
  tolerancia.

**D11. Volver a «seguir al sistema» tras una elección explícita** (menor de la verificación final).
No cambia la gramática de REQ-019. Se resuelve con texto en tres sitios: el remedio de `doctor`, en
B1, que es la dueña de `checks.py`; la wiki, en B5; y el CHANGELOG, en el PR de release.

- Cuando el origen es «preferencia» y lo guardado vino de la variable, `doctor` da como remedio:
  «para volver a seguir al sistema, borra `<ruta de language.json>` y ejecuta `install`».
- La página de la wiki sobre el idioma lo explica.
- El CHANGELOG de la 0.36.0 lo repite.

Test: `install` sin la variable, con el fichero borrado y el sistema en inglés, escribe
`{"lang":"en","source":"system"}`.

**D12. `update` regenera los bloques desfasados (bloqueante de la revisión del plan, REQ-012).**
Hoy `update` repara `scaffold.memory` solo cuando el bloque **falta** (`update.py:200`) y no toca
los subagentes (`install.py:1049-1060`). Así, la 0.35.0 dejaría el bloque de memoria y los
catálogos de los subagentes nombrando `delegacion-local`, ya borrada. Va en **A6**, la misma ola
que retira la skill:

- **Bloque de memoria: con qué se compara.** `install.py` gana en A6 la función
  `packaged_memory_blocks()` **(plan)**, que devuelve los bloques empaquetados de cada idioma
  admitido. A6 la crea solo con el español; B5, la dueña de `install.py` en el frente B, le añade el
  inglés. `checks.py` solo **llama** a esa función, así que B1 no tiene que saber cuántos idiomas
  hay ni B5 tiene que tocar `checks.py`.
- **Bloque de memoria: cuándo avisa y qué repara.** `scaffold.memory` da `OK` si el bloque presente
  en `CLAUDE.md`/`AGENTS.md`, con los **saltos de línea normalizados** (CRLF→LF) y sin espacio
  final, es igual a **alguno** de los bloques de `packaged_memory_blocks()`; si no, da `WARN`
  («desfasado»). El caso de partida es un bloque 0.34.0 que nombra la skill retirada. `update` lo
  repara en `MISSING` y en `WARN`, reescribe solo lo que hay entre `<!-- local-delegate:begin -->`
  y `<!-- local-delegate:end -->`, en el idioma vigente, y conserva el salto de línea del fichero
  (`install.py:957`). La regeneración de los subagentes usa el mismo criterio: un bloque de
  catálogo marcado solo se reescribe si, con los saltos de línea normalizados, **no coincide con el
  catálogo empaquetado de ningún idioma** admitido. La lista sale de `packaged_catalog_blocks()`
  **(plan)**, junto a `packaged_memory_blocks()` en `install.py`: A6 la crea con el español y B5
  añade el inglés.
- **Subagentes.** `update` regenera el bloque de catálogo de todo subagente de
  `~/.claude/agents/*.md` que **ya tenga** los marcadores `<!-- local-delegate:catalog:begin/end -->`,
  sin necesitar `--agents`, porque solo toca dentro de sus propios marcadores. Un subagente sin
  marcadores no se toca. Se informa como una reparación más de `update`.
- **Test de `update`** (no de `install`) sobre una 0.34.0 simulada, con `tmp_path` como `HOME`:
  skill `delegacion-local` instalada, bloque 0.34.0 en `CLAUDE.md` y `AGENTS.md`, un subagente
  con el bloque de catálogo 0.34.0 y otro sin marcadores. Al terminar, ningún fichero **vivo**
  contiene la cadena `delegacion-local`; los ficheros vivos son una lista cerrada: `CLAUDE.md`,
  `AGENTS.md`, los `.md` de `agents/` y las skills instaladas, y las copias `*.bak` que deja
  `install` (`install.py:215`) quedan fuera a propósito. Además, el subagente sin marcadores queda
  igual byte a byte y la skill `local-delegation` existe. Controles positivos:
  - sin la comparación del bloque en `scaffold.memory`, falla
    `assert "delegacion-local" not in claude_md`;
  - sin la regeneración de los subagentes, falla el mismo assert sobre el subagente marcado.
- **Tests de estabilidad (A6):**
  - un `CLAUDE.md` en CRLF con el bloque al día da `OK` y `update` no lo reescribe (mtime y bytes
    iguales);
  - una **segunda pasada** de `update` no cambia nada: ni ficheros, ni `.bak` nuevos, ni
    reparaciones informadas.

  Controles positivos: con la comparación sin normalizar, falla el caso CRLF; si la reparación
  ignora el criterio, la segunda pasada informa una reparación y falla.
- **Test de B5:** con el idioma en `en`, un bloque de memoria inglés al día da `OK`, y ni la primera
  ni la segunda pasada de `update` lo reescriben. Lo mismo vale para un subagente con el catálogo en
  inglés, y para uno con el catálogo en español mientras el idioma vigente es el inglés. Controles
  positivos: quitar el inglés de `packaged_memory_blocks()` o de `packaged_catalog_blocks()` hace
  fallar el caso correspondiente.
- **`doctor`:** el check `scaffold.memory` en `WARN` dice que el bloque está desfasado y propone
  `update`. Si el título o el estado cambian, la fila de la wiki y `test_wiki` se ajustan en A6.

**D13. Correspondencias revisadas, lotes y mínimo comprobable de PyCharm (REQ-015, REQ-037).**

- **Fichero de correspondencias.** Antes de renombrar nada, la ola ejecuta
  `tools/make_mapping.py --wave <ola>`. El script filtra el inventario, repetido con el detector de
  A0 sobre el árbol de ese momento, y escribe `waves/<ola>-mapping.csv` con estas columnas: `old`,
  `new` (propuesta), `kind`, `definition` (`fichero:línea` y ámbito), `scope` (`cross_module`,
  `module_local`, `function_local` o `unreferenced_test`), `method` (`pycharm` o `search_edit`),
  `reason` (obligatorio si el método es `search_edit`) y `verified` (la escribe el agente).
- **Una fila por definición, no por nombre.** La clave de cada fila es el nombre más su definición
  (`fichero:línea` y ámbito), resuelta por AST. Dos variables locales `estado` en dos funciones o
  ficheros distintos son **dos filas**; dos módulos con una función homónima, también.
- **Cómo se calcula `scope`: por análisis estático, dentro del script.** Un programa no puede llamar
  a las tools de PyCharm. `make_mapping.py` resuelve nombres por AST sobre `src/`, `tests/` y
  `scripts/`: los ámbitos (función, clase, módulo), los atributos y los imports, incluidos
  `from x import y` y `x.y`. A cada definición le asigna **las referencias que resuelven a ella**,
  no las coincidencias de token. Con eso clasifica:
  - `cross_module`: un import o un acceso a atributo la usa desde otro fichero;
  - `module_local`: solo la referencian sitios de su propio fichero, fuera de una única función;
  - `function_local`: todas sus referencias están dentro de la función que la define;
  - `unreferenced_test`: una función `test_*` a la que nada referencia.

  Lo que la resolución no alcanza (`getattr` con cadena, accesos dinámicos) se marca
  `scope=unresolved`, con método `pycharm` y verificación obligatoria. Test de `make_mapping.py`:
  dos funciones en dos ficheros con una variable local `estado` dan dos filas `function_local`, no
  una `cross_module`. Control positivo: agrupar por nombre hace fallar el assert del número de
  filas.
- **Verificación con PyCharm, solo donde aporta.** El agente comprueba con `analyze_calls` o
  `search_symbol` **todas** las filas `cross_module` y `unresolved`, y una muestra aleatoria (semilla registrada)
  del 10 % de las `module_local`, con 20 como mínimo. Cada una se anota en la columna `verified`
  (`ok` o `discrepancia: …`) y se cuenta en `waves/<ola>.md`. Una discrepancia corrige la fila
  antes de aplicar. Si en la muestra de `module_local` sale más de una, se verifican todas las
  `module_local` del lote.
- **Revisión de la sesión principal.** La sesión principal revisa los nombres `new`, los corrige y
  aprueba el fichero con una línea `# approved-by-main: <fecha>`. Hasta entonces la ola no aplica
  ningún renombre. El borrador de las propuestas en inglés lo puede hacer el agente; el criterio
  final no se delega.
- **Métodos:**
  - `pycharm` (`rename_refactoring`) para todo símbolo de código con `scope` `cross_module` o
    `module_local`: funciones, clases, constantes, atributos, parámetros con nombre que se usan
    como palabra clave, y módulos.
  - `search_edit` con motivo para tres cosas: (a) las variables con `scope=function_local` y los
    `test_*` con `scope=unreferenced_test`, que aplica un script de reemplazo de tokens enteros
    desde el CSV, con `newline=""`; (b) todo lo que PyCharm no cubre: claves JSON, variables de
    entorno dentro de cadenas, opciones del CLI, ids de checks, nombres de fichero, JS y docs; (c)
    un símbolo que PyCharm no pudo renombrar, con el error anotado.
- **Lotes.** Como mucho **300 filas por lote**, y cada lote lo hace un agente, con un commit. Como
  ahora hay una fila por definición, el número de filas **supera** al de nombres únicos del
  inventario (src, unos 858 nombres; tests, unos 2 306; scripts, unos 457). Las cifras de lotes que
  siguen son mínimos: A9, con 8 lotes como mínimo, y A10a y A10b, con 2 cada una. El número real
  de lotes lo fija el mapping de cada ola, y se anota.
- **Mínimo comprobable de REQ-037.** En `waves/<ola>.md`, el número de filas
  `rename_refactoring` registradas tiene que ser igual al número de filas (definiciones)
  `method=pycharm` del mapping de esa ola. Cada `rename_refactoring` se registra con la definición
  (`fichero:línea`) a la que se aplicó, para casarlo con su fila. Las filas `search_edit` se cuentan aparte, cada una con su motivo, y
  `get_file_problems` se ejecuta sobre todos los ficheros del diff. Lo comprueba
  `tools/check_wave_records.py`.

### 1.2 Frente A: renombrado

Tamaños: «apariciones» son las del inventario interno para los nombres que se definen en los
ficheros de la ola, y las de tests y docs se estiman con los importadores medidos (rename §1h).
Todas las olas A usan `rename_refactoring` salvo que se diga lo contrario, así que van **en serie**
en el checkout principal.

#### A0 — Andamiaje de compatibilidad y detector de nombres en español

- **Objetivo:** dejar las piezas que usan todas las demás olas del frente A y el detector del
  cierre.
- **REQ:** 044 (entera), 013 (entera), 004 (mecanismo y tests), 003 (el check nace, cubriendo el
  rol `fast` retirado), y 016 (lista de excepciones vacía y el detector listo).
- **Posee:**
  - nuevos: `scripts/detect_spanish_names.py`, `scripts/data/spanish_lexicon.json`,
    `scripts/data/spanish_lexicon.README.md` (procedimiento de generación),
    `scripts/data/reserved_words.json`, `src/local_delegate/deprecations.py`,
    `src/local_delegate/legacy_names.py` (esqueleto con la API de D2, sin tablas),
    `tests/test_detect_spanish_names.py`, `tests/test_deprecations.py` y
    `.sdd/changes/english-names-bilingual-output/rename-exceptions.md` (lista de REQ-016), y en la
    carpeta del cambio (no en el paquete) `tools/make_mapping.py` (genera el fichero de
    correspondencias de D13) y `tools/check_wave_records.py` (comprueba los mínimos de los
    registros de ola, sección 2.1);
  - existentes: `src/local_delegate/config.py` (helper `_env_alias`), `src/local_delegate/checks.py`
    (sustituir `config.rol_retirado` por `config.deprecated_names`),
    `src/local_delegate/install.py` (`_RETIRED_SKILLS` **(plan)** y el borrado por destino),
    `scripts/bump_version.py` (sustituye `UNRELEASED`), `tests/test_rol_fast_retirado.py`,
    `tests/test_checks.py`, `tests/test_install.py`, `tests/test_wiki.py`,
    `docs/wiki/Troubleshooting.md` y `docs/wiki/Savings-and-metrics.md` (fila del check).
- **Qué cambia:**
  1. **Detector.** Se porta `tools/research-scanners/esdet.py` y sus escáneres (`scan_py.py`,
     `js_tok.py`, `scan_data.py`) a un solo script sin `wordfreq` ni `esprima`. El tokenizador de JS
     es propio y reconoce comillas, plantillas, comentarios y literales de expresión regular (la
     trampa de `metrics.py:1935`). El léxico tiene las palabras de los tokens del repo,
     clasificadas una vez. Si para proponer esa clasificación se usa `wordfreq`, va fuera del repo
     con `uv run --with wordfreq==<versión>`, después de pasar `mcp__socket-mcp__depscore` (≥ 0,7).
     Las heurísticas no usan datos ajenos: ñ, tildes y sufijos.
  2. **Registro D1** con `DEPRECATED_NAMES` vacío, salvo las tres variables del rol `fast` que hoy
     cubre `RETIRED_FAST_ROLE_VARIABLES`. Se migran con `kind=retired`, `new=None`,
     `introduced="0.30.0"` (la sección `[0.30.0]` del CHANGELOG las nombra) y
     `warn_until="0.37.0"`, según la regla de D1. Así el check queda generalizado sin cambiar lo que
     avisa, y el test de horizonte nace en verde.
  3. **`config._env_alias(new, old)`**, que lee las dos por la puerta `_env*`, hace ganar a la
     nueva y anota la vieja en `config.DEPRECATED_SEEN`. Las dos entran en `VARIABLES_DE_ENTORNO`.
  4. **Check `config.deprecated_names`**, de estado aviso: mira la shell, el `env` de
     `~/.claude/settings.json` y la existencia de interruptores viejos (lista vacía hasta A2). El
     número de checks sigue en 25.
  5. **`install`** gana `_RETIRED_SKILLS` (vacía hasta A6) y la retirada en cada destino de skills.
  6. **`bump_version.py`** sustituye `"UNRELEASED"` en `deprecations.py`.
- **Tamaño:** unas 600 líneas nuevas (el detector, sobre 350, más los tests) y unas 120
  modificadas en 9 ficheros. `RETIRED_FAST_ROLE_VARIABLES` tiene 1 definición y unas 15 referencias
  (`config.py:244`, `checks.py:1629` y 10 menciones en `tests/test_rol_fast_retirado.py`).
- **Dependencias:** ninguna; es la primera ola.
- **PyCharm:** `search_symbol("VARIABLES_ROL_RETIRADO")`, `analyze_calls` del check viejo y un
  `rename_refactoring` (`RETIRED_FAST_ROLE_VARIABLES`→`RETIRED_FAST_ROLE_VARIABLES` **(plan)**). El id
  del check y la fila de la wiki se cambian por búsqueda y edición.
- **Tests nuevos o ajustados, con su control positivo:**
  - **`test_detect_spanish_names.py`, regresión:** 29 o más de los 30 nombres de rename §0, 0 de
    los 54 ingleses, y los 5 nombres de control en el JS. **Control de heurísticas:** palabras
    reservadas fuera del repo. Mutante: se quitan las tildes de la heurística; falla el assert
    `assert detect("canción")…` del conjunto reservado.
  - **Auditoría del léxico:** una muestra con `random.Random(<semilla>)` de 100 palabras o más,
    revisada a mano palabra por palabra, en `evidence/A0/lexicon-audit.csv` con la semilla y el
    resultado. El error tiene que ser ≤ 2 %; si se pasa, se corrige y se repite con otra semilla.
  - **`test_deprecations.py`:**
    - *horizonte:* en la 0.34.0 actual está en verde, con las entradas `fast` como `retired`. Si
      se parchea la versión a `introduced`+3 de un alias de prueba, falla
      `assert not overdue, overdue` con el nombre del alias en el mensaje; si se parchea a 0.38.0,
      falla también por las `fast` (`warn_until` vencido);
    - *CHANGELOG:* cada `introduced=V` exige que la sección `## [V]` nombre `old` y `new`, y
      `UNRELEASED` exige `## [Unreleased]`. Mutante: se borra la línea del CHANGELOG en un
      fixture y falla;
    - *paridad hook/registro* (D1). Mutante: se cambia un nombre en `hook_common`.
  - **`test_install.py`:** una skill retirada se borra y una skill ajena con otro nombre sigue ahí.
    Mutante: se quita el filtro por nombre; falla `assert (dest/"ajena").exists()`.
  - **`test_checks.py` y `test_rol_fast_retirado.py`:** el check nuevo avisa de una variable `fast`
    en la shell y en `settings.json`. Mutante: no mirar `settings.json`; falla el assert del
    segundo caso.
  - **`test_wiki.py`:** sigue contando 25, ahora con la fila nueva.
  - **Reemplazo acotado de variables locales** (verificación final de la revisión del plan): el
    aplicador del mapping reemplaza los tokens de una variable local solo dentro del tramo de su
    función, no en todo el fichero. Test: dos variables homónimas en dos funciones del mismo
    fichero que pasan a nombres distintos quedan cada una con el suyo. Mutante: reemplazar en todo
    el fichero; falla el assert de la segunda función.
- **Hecho cuando:** el detector corre sobre el repo, y su salida en
  `evidence/A0/detector-baseline.json` da el número de partida; la auditoría da ≤ 2 %; la suite
  está en verde; y se ha guardado el recuento base de tests recogidos.

#### A1 — CLI y variables de entorno

- **REQ:** 001 y 002 (enteras), y 003 (variables).
- **Posee:** `cli.py`, `config.py`, `valoracion.py` (solo `COMANDO` y `valoracion.py:43`),
  `resources/hooks/hook_common.py` (solo la lectura de `LD_HOOK_READ_*` con alias), `checks.py`
  (texto de `checks.py:1652`), `deprecations.py` (las 6 entradas), `server.py` (solo el apartado de
  `local_status` que lista los nombres obsoletos leídos), `tests/test_aislamiento_entorno.py`,
  `tests/test_recalcular*.py`, `tests/test_cli*.py`, los tests de hooks que fijan `LD_HOOK_READ_*`,
  `docs/wiki/Configuration.md`, `docs/wiki/Savings-and-metrics.md`, `docs/wiki/Troubleshooting.md` y
  `README.md`.
- **Qué cambia:**
  - El subcomando `recompute-cost`, con `recalcular-coste` como alias: un subparser oculto
    (`help=argparse.SUPPRESS`) con el mismo handler y el aviso.
  - La opción `--reset-calibration`, con `--reiniciar-calibracion` oculta. Si se pasan las dos con
    valores distintos, error, como `--target`/`--clients` en `cli.py:56-71`.
  - Las cuatro variables, por `_env_alias` en `config` y por un helper equivalente en
    `hook_common`.
  - `local_status` lista los nombres obsoletos leídos por el proceso servidor, desde
    `config.DEPRECATED_SEEN`.
- **Tamaño:** 6 nombres públicos. Menciones de rename §1a/§1b: `recalcular-coste`, 9 en src, 11 en
  tests, 3 en scripts, 17 en la wiki y 3 en README/CHANGELOG; `--reiniciar-calibracion`, 1, 2, 1, 4
  y 1. Variables: 2 a 4 lecturas cada una. En total, unas 90 menciones en unos 12 ficheros.
- **PyCharm:** `rename_refactoring` de `cmd_recalcular_coste`→`cmd_recompute_cost` y
  `dest=reiniciar_calibracion`→`reset_calibration`. Las variables en cadenas, los nombres del
  subparser y la documentación van por búsqueda y edición: `search_text` de cada nombre viejo en
  todo el repo, documentación incluida.
- **Tests y su control positivo:**
  - *alias del CLI:* mismo código de salida y mismo fichero escrito con los dos nombres; el aviso
    va en `stderr` y nombra `recompute-cost` y la versión; con el nombre nuevo no hay aviso.
    Mutante: el alias llama a otro handler; falla el assert de igualdad del fichero.
  - *variables:* para cada una, vieja sola, nueva sola y las dos (gana la nueva), en el paquete y
    en un **hook instalado lanzado como subproceso**. Mutante: se quita el alias en `hook_common`;
    falla el caso «vieja sola» del hook.
  - *guardián de aislamiento:* una lectura directa de `os.environ["LD_HOOK_READ_BLOQUEAR"]` fuera
    de la puerta lo hace fallar.
  - *`local_status`* con la variable vieja en el entorno del servidor.
- **Hecho cuando:** `--help` muestra solo los nombres nuevos (captura en `evidence/A1/help.txt`) y
  la suite está en verde.

#### A2 — Hooks, telemetría, temporales e interruptor

- **REQ:** 005 y 006 (telemetría y temporales), 012 (hook `record_call.py`, interruptor y
  temporales), 003 (canal `deprecated_names` de los hooks y lectura de la cola en `doctor`), 009
  (`/api/hooks` y el diccionario JS de motivos), y 002 (resto en hooks).
- **Posee:** `resources/hooks/*.py` (`hook_common`, `suggest_delegate_*`, y `anotar_llamada.py`→
  `record_call.py`), `install.py` (`_SCRIPTS_RETIRADOS` y la lista de hooks), `checks.py` (la cola
  de la telemetría en el check e `install` viejo), `legacy_names.py` (tabla de telemetría y
  temporales), `server.py` (solo `_bloqueo_reciente`, `server.py:497-512`), `atribucion.py` (solo
  `leer_nota`, `atribucion.py:73`, y el import de `hook_common` en `:30`), `web/metrics.py` (solo el
  lector de `/api/hooks`, `:623`, y el diccionario JS de motivos), `scripts/medir_adopcion.py` y
  `scripts/_banco_claude.py` (solo la lectura dual), y los tests de hooks y telemetría
  (`tests/test_hook*.py`, `tests/test_hooks_telemetry_api.py` y `tests/test_medir_adopcion.py`).
- **Qué cambia:**
  - Las claves y valores de D4, con escritura nueva y lectura doble.
  - Los temporales y el interruptor de REQ-012. El interruptor viejo sigue valiendo y entra en el
    check.
  - `record_call.py`, con `anotar_llamada.py` en `_SCRIPTS_RETIRADOS`.
  - La clave `deprecated_names` en los eventos (solo con la telemetría encendida). `doctor` lee la
    cola de 7 días con `seek` hacia atrás.
  - El diccionario JS de motivos, con los valores viejos sacados de la tabla inyectada (D2).
- **Tamaño:** `hook_common` 296 apariciones, `suggest_delegate_*` 119 y `anotar_llamada` 4; los
  tests de hooks, unos 600 estimados. 31 691 líneas de telemetría vieja siguen leyéndose.
- **Dependencias:** A1, porque las dos tocan `hook_common.py` y `checks.py`.
- **PyCharm:** `rename_refactoring` sobre las funciones de `hook_common` que importa el paquete
  (`analyze_calls` INCOMING antes, para ver los llamadores de `atribucion.py` y `server.py`).
  Claves JSON, nombres de fichero temporal, el diccionario JS y el nombre del fichero del hook van
  por búsqueda y edición.
- **Tests y su control positivo:**
  - *telemetría mezclada:* un fichero con filas viejas y nuevas da el mismo
    `/api/hooks.by_reason` que con todas nuevas. Mutante: un lector que solo entiende `reason`;
    falla el assert de recuento.
  - *`medir_adopcion` con filas de los dos formatos.*
  - *temporales:* el daemon lee `local-delegate-bloqueos.jsonl` y `local-delegate-blocks.jsonl`.
    Mutante: se quita el nombre viejo; falla el caso de un hook viejo.
  - *`install` sobre una 0.34.0 simulada:* `anotar_llamada.py` desaparece de los destinos y de
    `settings.json`. Mutante: se saca de `_SCRIPTS_RETIRADOS`.
  - *`deprecated_names`* aparece en el evento con la variable vieja y la telemetría encendida, y
    no aparece con la telemetría apagada; `doctor` lo informa desde la cola.
  - *JS:* el diccionario de motivos da la misma etiqueta para `mcp_ajeno` y `foreign_mcp`, con un
    test de node.
- **Hecho cuando:** suite en verde, control de REQ-014 por script registrado y hook instalado
  probado como subproceso.

#### A3 — Log de uso y clases de fallo (`fallos`→`failures`)

- **REQ:** 005 y 006 (`usage-*`: claves y valores de `error_class`, `fallback_class` y causa), 009
  (campos de causa en `/api/*`, el JS y el test de paridad), y 007 (en parte: valores de clase en
  `medir_enfriamiento.py`, en el **mismo PR**, rename §3.2).
- **Posee:** `fallos.py`→`failures.py`, `server.py` (escritura de filas, `server.py:700-860`, y
  lectura de `:998`), `web/metrics.py` (lectores de causa `:774-828` y su JS),
  `src/local_delegate/pace.py`, `legacy_names.py` (tabla de uso), `scripts/medir_enfriamiento.py`
  (solo valores de clase), `scripts/medir_adopcion.py` (solo `bloqueo_id`), y los tests
  `test_causa_conexion.py`, `test_fallos*.py`, `test_respaldo.py`, `test_metrics.py` (casos de
  causa), `test_dashboard_js.py` y `test_medir_enfriamiento.py` (casos de clase).
- **Qué cambia:** los enums `Clase` y `CausaConexion` con los valores de D4, las claves de la fila,
  y los lectores normalizados con `legacy_names.normalize("usage", row)`. El marcador del contrato
  de REQ-010 **no** se toca: es de B2.
- **Tamaño:** `fallos` 836 apariciones; los nombres de uso de `server.py`, unos 150; tests, unos
  1 200 (rename §5, ola 3). Unos 14 ficheros.
- **Dependencias:** A2 (comparten `server.py`, `web/metrics.py` y `medir_adopcion.py`).
- **PyCharm:** `rename_refactoring` del módulo `fallos` (si PyCharm no renombra el fichero con sus
  imports, se hace `git mv` y se usa `search_regex("from \\.?fallos|import fallos")`), de `Clase` y
  `CausaConexion`, y de sus funciones (`etiqueta`, `detalle`). Los valores del enum y las claves
  JSON van por búsqueda y edición, con la tabla de D4.
- **Tests y su control positivo:**
  - *mezcla en un mismo fichero* (escenario de la spec): `bloqueo_id`, `fallo_conexion:
    rechazada` y `error_class: timeout_lectura` junto a filas nuevas; `/api/stats` y el coste de
    `doctor` dan la suma, con la misma etiqueta. Mutante: el lector sin `normalize`; falla el
    assert de totales.
  - *paridad node:* se renombra un campo solo en Python y el test de paridad falla, con el control
    registrado en `waves/A3.md`.
  - *`medir_enfriamiento` con `clase` vieja y nueva* da el mismo informe.
- **Hecho cuando:** suite en verde y corrida del comando P-4 documentado guardada en
  `evidence/A3/p4-command.txt` (REQ-046).

#### A4 — Enfriamiento (`enfriamiento`→`cooldown`)

- **REQ:** 005 (incluida la **excepción**: doble escritura de `enfriamiento.json`, registrada en D1
  como `legacy_write`), 006 (estado vigente: gana el nuevo; eventos: se leen los dos), 007
  (entera) y 046 (el comando sigue igual).
- **Posee:** `enfriamiento.py`→`cooldown.py`, `server.py` (solo `:1081` y las llamadas al módulo),
  `hook_common.py` (lectura de `cooldown.json`/`enfriamiento.json`, `:315`), `deprecations.py`
  (entrada `legacy_write`), `legacy_names.py` (tabla de enfriamiento),
  `scripts/medir_enfriamiento.py` (lectura dual de ficheros y claves, sin cambiar el nombre del
  script ni sus opciones), `tests/test_enfriamiento.py` y `tests/test_medir_enfriamiento.py`.
- **Qué cambia:** los nombres de fichero y las claves de D4; el daemon escribe los dos ficheros
  mientras viva la excepción; los hooks nuevos leen los dos (gana `cooldown.json`), por si el
  daemon es viejo.
- **Tamaño:** `enfriamiento` 625 apariciones; tests, unos 900. 5 ficheros de test importan el
  módulo.
- **Dependencias:** A3 (valores de clase).
- **PyCharm:** `rename_refactoring` del módulo y de sus funciones públicas; `analyze_calls` de los
  escritores. Ficheros y claves por búsqueda y edición.
- **Tests y su control positivo:**
  - *excepción:* tras `entra`, `reentra` y `limpia`, los dos ficheros dan el mismo estado. Mutante:
    no reescribir el viejo al limpiar; falla el assert del tercer evento.
  - *hook nuevo con un `enfriamiento.json` de un daemon viejo* ve el modelo enfriado.
  - *P-4:* el mismo informe con eventos viejos, nuevos y mezclados (filas sintéticas de los dos
    formatos), excluyendo `test-windows.json`. Mutante: leer solo `cooldown-events.jsonl`; falla
    el recuento.
- **Hecho cuando:** el comando de P-4, tal como está en
  `.sdd/changes/delegacion-precisa-y-fiable/verification.md`, corre sobre los datos reales de esta
  PC y da el mismo informe que antes del cambio. Las dos salidas, solo con recuentos, se guardan en
  `evidence/A4/p4-before.txt` y `p4-after.txt`.

#### A5a — Atribución (`atribucion`→`attribution`)

- **REQ:** 005 y 006 (caché `attribution-*`, con siembra **una sola vez** y regla de mejor cruce),
  y 014 (control de `test_reason` con `medir_adopcion.py`).
- **Posee:** `atribucion.py`→`attribution.py`, `transcripts.py`, `legacy_names.py` (tabla de
  atribución), `scripts/medir_adopcion.py` (import), `tests/test_atribucion.py` y
  `tests/test_transcripts.py`. Los importadores de `checks.py`, `server.py:747`, `coste.py`,
  `recalcular.py` y `valoracion.py` se tocan **solo** en su línea de import, que rehace PyCharm.
- **Tamaño:** `atribucion` es el mayor de lo publicado: 4 815 apariciones de los nombres que
  define, inflado por nombres comunes que se definen ahí primero; `transcripts` 212. Importadores
  medidos con `search_text("import atribucion")`: 6 en src, 8 en tests y 1 en scripts.
- **Dependencias:** A4.
- **Tests y su control positivo:**
  - *siembra:* una segunda corrida no cambia el recuento.
  - *exacto frente a ventana:* un cruce `exacto` viejo no se pierde frente a uno `ventana` nuevo.
  - *intactos:* el fichero viejo queda igual byte a byte.
  - Mutantes: sembrar en cada corrida, o fusionar sin la regla de mejor cruce, y falla el control
    correspondiente.
  - *REQ-014:* se renombra `test_reason` sin tocar `medir_adopcion.py` y el control por script
    falla. Se registra.

#### A5b — Coste, cuota, recálculo y valoración

- **REQ:** 005 y 006 (`cost-aggregates`, siembra con identidad `(source, type, start, end)`
  traducida **antes** de juntar), 008 (`quota-statusline.jsonl`), 009 (campos de `/api/stats` y
  su JS), 033 (`marks` como valor de máquina) y 001 (texto `COMANDO` ya cambiado en A1).
- **Posee:** `coste.py`→`cost.py`, `cuota.py`→`quota.py`, `recalcular.py`→`recompute.py`,
  `valoracion.py`→`valuation.py`, `web/metrics.py` (campos de `/api/stats` `:540-657` y el JS que
  los lee), `legacy_names.py` (tablas de coste y cuota), y los tests `test_coste*.py`,
  `test_cuota.py`, `test_recalcular*.py`, `test_valoracion.py`, `test_panel_coste.py`,
  `test_metrics.py` (casos de stats), `test_dashboard_js.py` y `test_densidad.py`.
- **Tamaño:** `cuota` 1 283, `coste` 1 059, `recalcular` 514 y `valoracion` 380 apariciones. Entre
  los 81 campos del panel, los de coste y cuota (`coste`, `cuota`, `cota_baja`, `estimacion`,
  `densidad`, `puntos`, `hay_agregados`…). Tests, unos 1 500. Es la ola más grande: si al empezar
  `search_symbol` da más de 2 500 referencias, se parte en A5b-1 (coste y cuota) y A5b-2 (recálculo
  y valoración) y se anota.
- **Dependencias:** A5a.
- **Tests y su control positivo:**
  - *punto viejo `fuente=rechazo` + gemelo nuevo* dan un solo punto.
  - *caducado:* no reaparece tras dos corridas.
  - *`descartes`:* no cambia en la segunda corrida.
  - *statusline:* se leen los dos nombres de fichero; si existen los dos, se leen los dos.
  - *`marks`:* las viejas «cota baja», «solo comprobación» y «reinicio» se arrastran como
    `low_bound`, `check_only` y `reset`.
  - *paridad:* el test node sigue en verde. Mutante: se renombra un campo de `/api/stats` solo en
    el JS y falla.

#### A5c — Precios, densidad, `resources/datos/`, vigilante y `vendor.json`

- **REQ:** 005 (ficheros del paquete; sin lectura dual, porque viajan con su lector).
- **Posee:**
  - `precios.py`→`pricing.py`;
  - `resources/datos/`→`resources/data/`, con `precios.json`→`prices.json` y
    `densidad.json`→`density.json`;
  - `resources/vendor/vendor.json`;
  - `scripts/vigilante_precios.py` (solo claves y ruta; el nombre del script es de A10) y
    `.github/workflows/vigilante-precios.yml`;
  - `scripts/check_vendor.py` y `.github/workflows/vendor-audit.yml`;
  - `pyproject.toml` (`package-data`, si lo nombra);
  - `tests/test_vigilante.py`, `tests/test_vendor.py` (CRLF), `tests/test_precios*.py` y
    `tests/test_densidad.py` (solo rutas).
- **Tamaño:** `precios` 250 apariciones; 70 claves en `precios.json` y 19 en `densidad.json`;
  `test_vigilante.py` 734.
- **Dependencias:** A5b (`densidad` la lee `coste.fundir`).
- **Tests y su control positivo:** `test_vigilante` regenera `prices.json` con las claves nuevas;
  `vendor-audit` en verde en el PR (se mira en `gh pr checks`). Mutante: dejar una clave
  `entrada`; falla el esquema del vigilante.
- **Riesgo propio:** el workflow del vigilante abre PRs automáticos. Si hay uno abierto con el
  formato viejo, se cierra antes de mezclar A5c.

#### A6 — `doctor`, skill, cookie, subagentes y `secciones`

- **REQ:** 011 (entera), 012 (skill `local-delegation`, cookie `ld_session`/`ld-session|v1` y
  nombre de la skill en los bloques, **también tras `update`**: D12), 013 (la skill vieja entra en
  `_RETIRED_SKILLS`), y 016 (sección «pendiente» con las subclaves y marcadores de REQ-010).
- **Posee:**
  - `checks.py` (ids y grupos, y `scaffold.memory` en `WARN` si el bloque está desfasado: D12),
    `doctor.py`, `cli.py` (solo `_SCAFFOLD_GROUPS`, `cli.py:46`, y las dos menciones de la skill,
    `cli.py:1423`, `help=` de `--no-skill`, y `cli.py:1460`, dentro de la ayuda de `install`, que
    empieza en `:1459`; en la ola se confirman con `search_text("delegacion-local")`);
  - `install.py` (`SKILL_NAME`, `_RETIRED_SKILLS`, la reparación del bloque de memoria y
    `packaged_memory_blocks()`, solo con el español: D12);
  - `update.py` (reparar `scaffold.memory` también en `WARN` y regenerar los bloques de catálogo
    de los subagentes ya marcados: D12);
  - `resources/skills/delegacion-local/`→`resources/skills/local-delegation/`,
    `resources/memory/local-delegate.md` y `agents.py` (el nombre de la skill y la función que
    regenera un bloque marcado, que usa `update`; la detección bilingüe del encabezado es de B5);
  - `web/auth.py` (`:45` y `:50`);
  - `secciones.py`→`sections.py`;
  - los tests `test_checks.py`, `test_doctor.py`, `test_coste_doctor.py`, `test_auth*.py`,
    `test_agents*.py`, `test_install*.py`, `test_update.py` y `test_resumen_estructurado.py` (solo
    los imports);
  - `docs/wiki/Troubleshooting.md`, `Savings-and-metrics.md` (ids) e `Integration-install.md`
    (`update` repara los bloques desfasados).
- **Qué no se toca:** `_local_delegate.{truncado,aviso,…}` y los marcadores `aviso`/`respaldo`. Los
  renombres de PyCharm en `server.py` y `secciones.py` **excluyen** esas cadenas; se comprueba con
  `search_text` después.
- **Tamaño:** `secciones` 891 apariciones; ids, 2 checks y 3 grupos con unas 30 menciones;
  `web/auth` 110; skill, 1 directorio y unas 10 menciones.
- **Dependencias:** A5c.
- **Tests y su control positivo:**
  - *`doctor --json`* con ids nuevos; `test_checks` con el conjunto exacto de grupos
    `{environment, scaffold, service, backend}`; recuento de 25.
  - *`install` sobre una 0.34.0* deja la skill nueva y no la vieja, y los bloques nombran
    `local-delegation`. Mutante: no añadirla a `_RETIRED_SKILLS`; falla
    `assert not (skills/"delegacion-local").exists()`.
  - *`update` sobre una 0.34.0* (D12): ningún fichero del `HOME` simulado contiene
    `delegacion-local`, y el subagente sin marcadores queda igual. Los dos controles positivos de
    D12 se registran en `waves/A6.md`.
  - *`scaffold.memory`* da `WARN` con un bloque 0.34.0 y `OK` con el empaquetado. Mutante:
    comparar solo si existe; falla el caso `WARN`.
  - *cookie vieja* da 401 y redirige a autenticarse, sin excepción. Mutante: aceptar la vieja;
    falla el test de seguridad.

#### A7a / A7b — Resto de `server.py` (CRLF, 4 560 líneas)

- **REQ:** 015 (interno) y 017.
- **Posee:** `src/local_delegate/server.py` y, en `web/metrics.py`, **solo** las líneas que llaman
  a funciones de `server`, porque las reescribe PyCharm. La lista cerrada sale del mapping y de
  `analyze_calls` INCOMING, y se anota en `waves/A7a.md`. A7a cubre las líneas 1 a unos 2 300
  (núcleo, troceado y respaldo) y A7b el resto (tools y `local_status`). Con ellas van sus tests:
  `test_core.py`, `test_map_reduce.py`, `test_vision.py`, `test_boilerplate_salida.py` y los demás
  que referencien solo `server`. Unos 128 nombres definidos en `server.py`: un lote por subola.
- **Tamaño:** `server.py` 979 apariciones de nombres que define, y unas 1 100 en total en el
  fichero (rename §2).
- **Regla:** la API de tools (nombres y parámetros) ya está en inglés y no se toca. Los prompts y
  los docstrings no se tocan aquí: son de B2. Solo identificadores.

#### A8a — Resto de `src/` (Python)

- **REQ:** 014 (módulos restantes de D3), 015 y 017.
- **Posee:** `cadenas.py`→`chains.py`, `estado_json.py`→`json_state.py`,
  `preguntas.py`→`questions.py` (CRLF), `sondas.py`→`probes.py`, y además `checks.py`, `install.py`,
  `cli.py`, `clients.py`, `web/auth.py`, `config.py`, `benchmark.py`, `daemon.py`, `update.py`,
  `topology.py` y `residency.py` (solo identificadores), con sus tests.
- **Tamaño:** `checks` 2 121, `cadenas` 724, `cli` 307, `install` 293, `clients` 143, `benchmark`
  142, `web/auth` 110, `preguntas` 103, `config` 72, `sondas` 47 y el resto menos de 20. Unas
  4 100 apariciones en total: si se pasa de un PR revisable (unos 1 500 cambios de línea), se parte
  en A8a-1 (`checks` y `cadenas`) y A8a-2 (el resto).
- **Cuidado:** `cadenas.py:42` acepta `residente` como sinónimo obsoleto de un **valor**. Se queda
  como está, porque es lectura de formato viejo, y va a la lista de excepciones.

#### A8b — JS del panel e ids del DOM

- **REQ:** 009 (identificadores propios del JS e ids del DOM) y 015.
- **Posee:** `web/metrics.py` (bloque `<script>` y marcado, `:1072-2946`), `tests/test_dashboard_ui.py`
  (CRLF; selectores), `tests/test_dashboard_js.py` (cabeceras literales) y
  `scripts/extract_dashboard_js.py`.
- **Tamaño:** 65 identificadores JS en español con 255 apariciones, y 20 ids del DOM con sus
  selectores en Playwright.
- **PyCharm:** sin `rename_refactoring`, porque el JS vive dentro de una cadena Python. Se hace por
  búsqueda y edición, con un script en el scratchpad que reemplaza tokens enteros con el
  tokenizador de A0 y conserva CRLF. Va **después de A7b**, sin paralelo: `web/metrics.py` llama a
  funciones de `server` que renombra A7 (`sondear_backend` en `:758` y `:846`, `_plazo_sonda` en
  `:788` y `:819`, `_backend_en_loopback` en `:817`, `_clashes_by_groups`/`_topology`), y
  `rename_refactoring` reescribe esas llamadas dentro de `metrics.py`. Por eso A7a y A7b también
  poseen `web/metrics.py`, pero solo esas líneas de llamada.
- **Tests y su control positivo:** paridad node (se renombra `acct` solo en el test y falla);
  Playwright entero bajo el cerrojo.

#### A9a / A9b / A9c — Tests

- **REQ:** 015 (1 383 nombres `test_*`, 41 módulos de test y auxiliares) y 017 (lo que afirma no
  cambia).
- **Posee:** `tests/` salvo los ficheros que posee A10. Partición por orden alfabético de módulo,
  para que sea comprobable:
  - **A9a:** `conftest.py`, los directorios de fixtures `residencia/`→`residency/` y
    `topologia/`→`topology/`, y los módulos `a*`–`d*`;
  - **A9b:** `e*`–`p*`;
  - **A9c:** `q*`–`z*`.

  Unos 2 306 nombres en tests: según D13 son **8 lotes de ≤ 300 como mínimo**. Cada subola se parte
  en los lotes que dé su mapping, sin partir un módulo de test entre dos lotes, y cada lote lo hace
  un agente. Los `test_*` sin referencias van por el script de tokens (`unreferenced_test`); el
  resto, por PyCharm.
- **Tamaño:** unas 11 550 apariciones de nombres que se definen en tests; en total, unas 15 400 en
  84 ficheros (rename §2). Hay que restar lo que ya cayó con sus olas.
- **Regla:** solo se renombra. Ningún assert cambia de sentido. Los textos en español que afirman
  los tests **no** se tocan: son salida del producto y siguen valiendo con el fixture `es`
  (REQ-043).
- **Control:** el número de tests recogidos al final de cada subola es igual al de antes, más los
  añadidos registrados. Un test perdido hace fallar la comparación de `evidence/A9x/collect.txt`.

#### A10a / A10b — Scripts

- **REQ:** 015 (14 módulos de scripts, 4 102 apariciones, con sus opciones) y 046.
- **Posee:** `scripts/` (salvo `bump_version.py`, `detect_*` y `data/`, que ya están en inglés) y
  los tests de scripts (`test_medir_*.py`, `test_analisis_benchmark.py`, `test_corpus.py`,
  `test_hoja_*.py`, `test_vigilante.py`, `test_experimento_adopcion.py` y `test_sesiones*.py`),
  que A9 **no** posee.
- **Partición:**
  - **A10a**, medición y operación: `medir_adopcion`→`measure_adoption`,
    `medir_enfriamiento`→`measure_cooldown`, `experimento_adopcion`→`adoption_experiment`,
    `medir_resumen_estructurado`→`measure_structured_summary`,
    `sesiones_de_prueba`→`test_sessions` **(plan)**, `sonda_recursos`→`resource_probe`,
    `limpiar_fixtures_vigilante`→`clean_watcher_fixtures`, `vigilante_precios`→`price_watcher`
    (con su workflow);
  - **A10b**, benchmark: `_banco_claude`→`_claude_bench`, `analizar_benchmark`→`analyze_benchmark`,
    `construir_corpus`→`build_corpus`, `hoja_pares`→`pair_sheet`, `hoja_revision`→`review_sheet`.
- **REQ-046:** `scripts/medir_enfriamiento.py` se queda como **envoltorio**, que llama a
  `measure_cooldown.main()` y conserva `--desde` y las demás opciones viejas como alias de las
  nuevas. Se añade una nota fechada en los dos `verification.md` de los SDD cerrados y una entrada
  en el backlog: «retirar el envoltorio tras la medición de P-4 de los 90 días (~2026-12-14)». La
  verificación ejecuta el comando documentado y guarda la salida.
- **Tamaño:** `construir_corpus` unas 1 076 apariciones, `analizar_benchmark` 748, `vigilante` 627 y
  `experimento_adopcion` 334.
- **Cierre del frente A (al final de A10b):** primera corrida del detector (REQ-016) en
  `evidence/A-close/detector.json`. Tiene que dar 0 fuera de `rename-exceptions.md`, con la
  sección «pendiente» solo con REQ-010 y sin palabras «sin clasificar». Los tests de control de
  REQ-044 tienen que estar en verde.

### 1.3 Orden del frente A y paralelismo

```
A0 → A1 → A2 → A3 → A4 → A5a → A5b → A5c → A6 → [release 0.35.0]
   → A7a → A7b → A8b → A8a → A9a → A9b → A9c → A10a → A10b → cierre del frente A
```

Todo va en serie, sin excepciones. Hay dos motivos: `rename_refactoring` es un recurso único en
el checkout principal, y las olas consecutivas comparten ficheros (`checks.py`, `server.py`,
`web/metrics.py` y `hook_common.py`). A8b va después de A7b porque PyCharm reescribe dentro de
`web/metrics.py` las llamadas a `server`. Dentro de una ola, un segundo agente puede escribir los tests
nuevos o la documentación en ficheros que el agente que renombra no toca, siempre que la lista
«posee» de la ola los asigne.

### 1.4 Frente B: idioma

**Orden de mezcla (explícito):**

```
A10b → cierre del frente A (A-close-1…4) → valores de una palabra (A-close-5) → higiene de CodeQL → `affinity --check` sin entorno → B0 (B0a → B0b) → B1 → B2 (lotes B2a → B2b → B2c → B2d → B2d-2 → B2d-3 → B2d-4 → B2e → B2-affinity) → { B3 ∥ B4 } → B5 → [release 0.36.0]
```

- **Valores de una palabra (A-close-5, añadida el 2026-10-14), tras A-close-4.** El barrido de
  valores de una sola palabra de A-close-4 (`evidence/A-close-4/singleword-*.tsv`, que el detector
  no ve: decisión 5) encontró 21 valores internos en español en `scripts/` (p. ej. `hecho`/`tabla`
  en `price_watcher.py`, `esperar`/`bien`/`mal` en `ci_gate.py`, `cambiar` en
  `measure_cooldown.py`, `mejor`/`peor` en `analyze_benchmark.py`, `produccion` en
  `dev/affinity_batch.py`, `valida` en `pair_sheet.py`). Un lote con mapping aprobado, como los
  anteriores: lectura dual solo si el valor se guarda y se relee (`produccion`, y `cambiar` si
  procede), con test y mutante; lo que sea texto de salida queda para el frente B.
- **`affinity --check` sin depender del entorno (añadido el 2026-10-14), tras la higiene de
  CodeQL y antes de B0.** El agente de A-close-5 vio que la comprobación del corpus de afinidad
  da ok solo con `LOCAL_DELEGATE_COMMIT_LANGUAGE=es` puesta; sin ella, 40 diferencias en los
  prompts de sistema de los casos de commit (ya en `main` 61f8b21). Va antes de B0 porque B0
  toca `config.py` y el aislamiento del entorno de la suite, y B2b exige que el prompt de
  `local_commit_msg` quede idéntico: con una comprobación que depende de la máquina, esa garantía
  no se puede medir. (Enmienda del 2026-10-14, decisión del usuario: el prompt de `commit_msg` **sí**
  cambia en B2b-2 —idioma del producto por defecto, regla del diff solo con el valor explícito
  `diff`— y en B2c —cuerpo obligatorio y topes—; lo que debe quedar idéntico es la recaptura con
  `LOCAL_DELEGATE_COMMIT_LANGUAGE=diff`, y las diferencias de los corpus las declara
  `PROMPT_BOUNDARIES`.) Primero se **verifica por ejecución** (con y sin la variable, en un entorno
  limpio) y se localiza la causa; el arreglo hace que la comprobación reconstruya el prompt con
  el idioma con que se congeló el corpus, sin leer la variable del usuario. Test con la variable
  puesta a otro valor y sin ella; mutante que vuelve a leer el entorno → falla. Origen: backlog
  del vault §1.7.
- **Sección «Texto de salida que traduce el frente B» de `rename-exceptions.md`** (nace en
  A-close-4): como «Pendiente», queda **vacía al cerrar el cambio**. Cada fila nombra la ola B que
  la traduce (B1, B2 o B4), y esa ola borra sus filas en su PR.
- **Higiene de CodeQL (añadida el 2026-10-14), entre el cierre del frente A y B0.** Un lote corto,
  con su PR, que deja en 0 las alertas abiertas de code scanning en `main` (16 al 2026-10-14).
  Va **antes** de B0 porque 6 de ellas están en `server.py`, que desde B2 tiene un solo dueño.
  Las alertas se **arreglan**, no se descartan (también las que parezcan falso positivo: se
  reescribe el código para que la regla no salte).
  - **Seguridad (1):** `py/stack-trace-exposure` en `web/metrics.py:964` (`/api/llamaswap/watch`
    devuelve `str(e)` al navegador). Pasa a un mensaje genérico con código 502 y el detalle va al
    log. Test: la respuesta no contiene el texto de la excepción; control positivo con el mutante
    que vuelve a `str(e)`.
  - **Notas (15):** 7 `py/empty-except` (`server.py:864`, `:873`, `:4515`, `residency.py:1063`,
    `hook_common.py:261`, `tests/fake_llama_server.py:134`): cada `except` lleva un motivo
    explícito (log de depuración, o `contextlib.suppress` con comentario); 4
    `py/unused-global-variable` (`topology.py:509-510`, `server.py:596`, `:1443`); 3
    `py/catch-base-exception` en tests (`test_turn.py:261`, `test_turn_daemon.py:119`,
    `test_affinity.py:210`); 1 `py/import-and-import-from` (`test_slowness.py:18`); 1
    `py/mixed-returns` (`server.py:1249`). Las líneas son las del 2026-10-14: tras A-close-3 y 4 se
    recalculan con `gh api repos/…/code-scanning/alerts?state=open`.
  - **Sin cambio de comportamiento** salvo el mensaje del 502. Suite completa y `ruff` en verde.
  - **Hecho cuando:** el PR mezclado y `gh api …/code-scanning/alerts?state=open` devuelve 0 en
    `main`, y `gh pr checks` en verde con 0 alertas nuevas.

- **Ninguna ola B se mezcla antes de A10b.** REQ-035 solo exige que estén las olas A de `src/`,
  pero todas las olas B tocan tests, y A9 y A10 renombran justo esos tests (`test_checks`,
  `test_dashboard_ui`, `test_install*`, `test_metrics`, `test_wiki`, el guardián de aislamiento y
  los tests de scripts). Así ninguna ola B se mezcla con un test sin renombrar. En las listas
  «posee» de B, los tests aparecen por su nombre de hoy; tras A9 se aplica el nombre nuevo de su
  mapping.
- **B0 puede desarrollarse antes**, en un worktree, mientras corren A9 y A10. Sus ficheros nuevos no
  existen en A, pero antes de su PR **se rebasa** sobre `main` con A10b mezclada y se ajusta a los
  nombres nuevos (`conftest.py`, el guardián de aislamiento y `config.py`).
- **Lo único en paralelo es B3 con B4.** Las dos van en worktrees, sus listas «posee» son
  disjuntas, y las dos esperan a B2: B3 necesita el fichero de fronteras y B4 las funciones
  `t_lang` de las etiquetas que deja B2. Las demás olas B van en serie.
- **Propiedad exclusiva en el frente B.** Cada fichero tiene **una sola** ola B dueña en todo el
  frente; ninguna lo comparte, ni siquiera en serie. El catálogo y la lista de pendientes van
  partidos por superficie (D5). Los puntos de cruce quedan asignados así:
  - `install.py`, `update.py` y la desinstalación son **solo de B5**: la escritura de
    `language.json`, la skill, los bloques **y** los mensajes de consola de `install`, `update` y
    `uninstall` (REQ-021 en lo que toca a esos comandos);
  - `checks.py` y `doctor.py` son solo de B1, y eso incluye el remedio de D11;
  - `server.py` es solo de B2, con sus dos lotes;
  - `i18n.py` y `tests/conftest.py` son solo de B0, y eso incluye el parche de argparse de D8 y el
    fixture común de `locale` de Playwright que usa B4;
  - `hook_common.py`: B0 añade `resolve_language` y un `HOOK_TEXTS` vacío; B3 lo llena. Lo mismo
    pasa con `ci.yml` y `scripts/ci_gate.py`: B0 añade `test-lang-es` y B1 añade
    `cli-python-matrix`, cada uno con el test que ejecuta. Son los únicos ficheros con dos dueñas
    en serie, que nunca corren a la vez;
  - el CHANGELOG, el README y la wiki de la 0.36.0 los escribe la sesión principal en el PR de
    release, a partir de los registros de ola. La excepción es la página de la wiki sobre el idioma,
    que es de B5, y `test_wiki.py`, que es de B1.
- Las olas B no usan `rename_refactoring`, así que no ocupan PyCharm, salvo para buscar.

#### B0 — Base de idioma, catálogo y guardianes (en dos PR: B0a y B0b)

Partida el 2026-10-14 tras la propuesta de la fase 1 (`waves/B0-proposal.md`, «Decisiones
aprobadas»): el tamaño real dobla la estimación inicial (~700 nuevas, < 60 modificadas en 4
ficheros) y las dos mitades son independientes. B0a se mezcla antes que B0b; las dos, antes de B1.

- **REQ:** en **B0a**, 018 (entera), 019 (gramática y aviso; la presentación va en B1 y B2), 047
  (lectura), 030, 031 y 043 (fixtures de variable, directorio de datos y `locale` de Playwright);
  en **B0b**, 045 (nace con su lista de pendientes) y el detector de D10.
- **Imports de `i18n.py`:** stdlib, `config` (por `config.LOG_DIR`, D7) y `hook_common`. No hay
  ciclo: `config` no importa `i18n`, y lo que `config` devuelve sobre el idioma son códigos, no
  textos.
- La versión de las filas de uso (`v`, desde F1; antes se proponía `package_version`) pasa a B2 (lote B2b), que es la dueña de
  `server.py`. Sale en la misma versión 0.36.0, así que la frontera no cambia.

##### B0a — Base de idioma, catálogo, paridad, fixtures y `test-lang-es`

- **Posee:**
  - nuevos: `src/local_delegate/i18n.py` (incluye `argparse_gettext`/`argparse_ngettext` de D8;
    el parche en `cli.py` es de B1), `src/local_delegate/resources/i18n/{es,en}/common.json`,
    `tests/test_language.py` y `tests/test_i18n_parity.py`; y una sección nueva, «Catálogo de
    textos (frente B)», en `rename-exceptions.md`, con una fila comodín para
    `src/local_delegate/resources/i18n/es/*.json` (el detector de nombres del frente A toma por
    términos de máquina los valores de una palabra del catálogo español) y dos para los códigos
    de idioma de los tests (`es-ES`, `es_ES.UTF-8`); va en B0a porque el catálogo nace aquí y el
    detector tiene que seguir a 0 entre las dos mezclas. Las palabras nuevas de B0a entran en
    `scripts/data/spanish_lexicon.json` (22 en inglés y `reserva` en español);
  - existentes: `resources/hooks/hook_common.py` (`resolve_language` con sus dos piezas privadas
    `_system_language` y `_windows_ui_language`, y `HOOK_TEXTS` vacío), `config.py` (registro de
    `LOCAL_DELEGATE_LANG` y, por la enmienda de REQ-028 del 2026-10-14, `output_language()`, que
    lee y valida `LOCAL_DELEGATE_OUTPUT_LANGUAGE`; las dos en `ENVIRONMENT_VARIABLES`),
    `tests/conftest.py` (`LOCAL_DELEGATE_LANG=es` y `LOCAL_DELEGATE_LOG_DIR=<tmp>` automáticos, y el
    fixture común de `locale` de Playwright con `es-ES` por defecto, que B4 usa) y
    `tests/test_environment_isolation.py` (se amplía según D7, y se arregla
    `test_the_suite_runs_without_package_variables_defined`, que con los fixtures nuevos fallaría
    porque exige que ninguna variable del inventario esté definida);
  - CI: `.github/workflows/ci.yml` (trabajo `test-lang-es`: la suite entera, Playwright incluido,
    con `LANG=es_ES.UTF-8` en ubuntu y Python 3.11, con `locale-gen` y una guarda de entorno) y
    `scripts/ci_gate.py` (`test-lang-es` en `EXPECTED_JOBS`). Ese trabajo solo ejecuta tests que ya
    existen cuando se mezcla B0a. En B0a discrimina poco (el fixture fija `es`); su poder real
    llega con los asserts en español de B1.
  - Decisiones de la regla (aprobadas el 2026-10-14): `LOCAL_DELEGATE_LANG` vacía o solo espacios
    = no puesta, sin aviso; `C.utf8` y variantes cuentan como «no declarado» (se normaliza quitando
    codificación y modificador); «empieza por `es`» es `^es(?![a-z])`, sin distinguir mayúsculas;
    en `LOCAL_DELEGATE_OUTPUT_LANGUAGE` se rechazan también los caracteres de formato (`Cf`).
- **Tamaño:** unas 650 líneas nuevas; unas 275 añadidas o modificadas en 6 ficheros existentes
  (`hook_common.py` ~120, `test_environment_isolation.py` ~65, `config.py` ~30, `conftest.py`
  ~30, `ci.yml` ~30, `ci_gate.py` 2).
- **Tests y su control positivo (un mutante por paso de la precedencia):**
  - Los nueve casos de REQ-018, con el entorno, la preferencia y `ui_lang`/`kernel32` inyectados;
    se afirma el idioma **y** el origen. Mutantes: intercambiar los pasos 1 y 2 tumba
    «`LOCAL_DELEGATE_LANG=en` con preferencia `es` → en»; intercambiar los pasos 2 y 3 tumba
    «preferencia `es` con el sistema en inglés → es»; ignorar `LANGUAGE` tumba `es:en`; honrarlo
    con el locale no declarado tumba `LANGUAGE=es` con `LANG=C`; leer `LANG` antes que `LC_ALL`
    tumba su caso; sacar `C` de los no declarados tumba el origen de `C.UTF-8`; consultar el
    formato regional en Windows tumba «interfaz `en-US`, formato `es-ES`»; leer `LANG` en Windows
    tumba «`LANG=en_US.UTF-8` e interfaz `es-ES`»; aceptar `fr` o no avisar tumba el último.
    (Corrige la versión anterior, que atribuía dos casos al intercambio de los pasos 2 y 3: el de
    la variable lo decide el paso 1.)
  - *implementación única:* el guardián de aislamiento busca por AST las constantes `LANG`,
    `LANGUAGE` y `LC_*` y los atributos `GetUserDefaultUILanguage`, `getlocale`,
    `getdefaultlocale` y `windows_locale` fuera de la lista blanca de `hook_common.py`
    (`resolve_language`, `_system_language`, `_windows_ui_language`). Mutante: una lectura de
    `LANG` en `cli.py`.
  - *REQ-043 a:* con `LOCALAPPDATA`/`HOME`/`XDG_DATA_HOME` falsos que contienen `language.json`
    con `en`, un test que espera `es` sigue en verde.
  - *REQ-043 b:* sin el fixture de `LOCAL_DELEGATE_LOG_DIR`, ese montaje hace fallar un test de
    hook lanzado como subproceso. Se registra quitando el fixture en una corrida acotada.
  - *fixture de aislamiento:* fijar en el fixture un idioma distinto del que espera el guardián
    lo hace fallar.
  - *paridad:* borrar una traducción, cambiar `{n}` o cambiar un identificador entre comillas
    invertidas la hace fallar; cubre también `HOOK_TEXTS` (con la regla de solo ASCII).
- **Hecho cuando:** suite en verde con `LANG=en_US.UTF-8` y con `LANG=es_ES.UTF-8` (en Windows no
  discrimina: ver la sección 4.2).

##### B0b — Guardián de textos fuera del catálogo y detector de idioma

- **Posee:** los nuevos `tests/test_no_uncatalogued_text.py`, `tests/data/uncatalogued_pending/`
  (un fichero por superficie: `cli`, `doctor`, `mcp`, `hooks`, `panel` e `install`; cada ola B
  solo vacía el suyo), `tests/data/uncatalogued_exceptions.json` (excepciones con motivo;
  `scripts/medir_enfriamiento.py` entra aquí como envoltorio de REQ-046, que se retira tras P-4),
  `scripts/detect_language.py`, `scripts/data/function_words.json`,
  `tests/data/detect_language_control.json` y `tests/test_detect_language.py` (D10, que adelanta
  su control).
- **Alcance del guardián:** `src/local_delegate/**` (sin `vendor/`) y los tres scripts de B1
  (`measure_cooldown.py`, `pair_sheet.py` y `analyze_benchmark.py`). Contextos: sumideros
  (`print`, `write`, `exit`, `error`, `warn`, `emit`, `deny`, `append`/`extend`), `raise`,
  argumentos con nombre de texto, `return` y constantes de rótulos (`*_LABEL(S)`, `*_TEXT(S)`…).
  Con una red complementaria por tildes en los ficheros no pendientes.
- **Ficheros sin dueña que se asignan:** `recompute.py`, `probes.py`, `deprecations.py` y
  `entrypoint.py` a B1 (`cli.json`); `questions.py` a B2 (`mcp.json`); `quota.py`, `valuation.py`
  y `attribution.py` a B4 (`panel.json`).
- **Escáner del panel:** lo escribe B4 (dueña de `metrics.py`). B0b deja una guarda que impide
  sacar `web/metrics.py` de pendientes mientras ese escáner no exista.
- **Tamaño:** unas 900 líneas nuevas (de ellas ~300 de la lista de palabras funcionales y ~130 de
  datos de control).
- **Tests y su control positivo:**
  - *`test_no_uncatalogued_text`:* `print("Hola")` en un fichero que no está en la lista de
    pendientes lo hace fallar, y una excepción con texto humano hace fallar su test. Cada fichero
    pendiente tiene que tener al menos una aparición: un pendiente que el escáner no ve no puede
    salir de la lista.
  - *`detect_language`:* control llamando con `min_tokens=8` (las frases tienen 8 palabras o más;
    el umbral por defecto de 20 rige para la muestra de REQ-028). En B0b el control son 20 + 20
    frases congeladas (español de `docs/wiki`; inglés del diccionario `en` de `site/index.html`, el
    único inglés corrido del repo) con como mucho 1 fallo en 40 (≥ 97,5 %; aprobado el
    2026-10-14). No es un control independiente: se midió 38/40 y se añadieron «ambos» y «casi» a
    la lista española a la vista de los dos fallos (queda 39/40; 0/40 con las listas invertidas).
    El control independiente es el de **B1**: 60 + 60 frases nuevas (entradas de ≥ 8 palabras de
    los catálogos), congeladas antes de ver la lista, con ≥ 98 % (como mucho 2 fallos en 120); en
    B1 ya no se ajustan las listas a la vista de los fallos, y si no llega, se decide en B1. Con
    las dos listas invertidas, el control falla.
- **Hecho cuando:** la lista de pendientes contiene todos los ficheros de salida y la suite está en
  verde.

#### B1 — CLI, `doctor`, `test-window`, `benchmark` y llama-swap

- **REQ:** 021 (salvo `install`, `update` y `uninstall`, que son de B5), 022, 026 (CLI y
  `doctor`), 032 (test de la wiki contra los títulos en español), 034 (humo en inglés del CLI y de
  `doctor`), 019 (`doctor` muestra el idioma, su origen, la ruta y el aviso) y el remedio de D11 en
  `doctor`.
- **Posee:** `cli.py`, `doctor.py`, `checks.py`, `test_windows.py`, `benchmark.py` (mensajes),
  `scripts/measure_cooldown.py`, `scripts/pair_sheet.py` y `scripts/analyze_benchmark.py` (sus
  diccionarios de rótulos en español de A-close-5; asignados el 2026-10-14),
  `residency.py`, `topology.py`, `llamaswap_api.py`, `llamaswap_config.py`, `matrix.py`, `turn.py`
  y `daemon.py` (mensajes de consola), `recompute.py`, `probes.py`, `deprecations.py` y
  `entrypoint.py` (sus mensajes; asignados por B0 el 2026-10-14),
  `resources/i18n/{es,en}/{cli,argparse,doctor}.json`,
  `tests/test_wiki.py`, los tests nuevos `tests/test_cli_english.py` (incluye
  `test_argparse_msgids_covered`, D8) y `tests/test_doctor_english.py`; en CI, `ci.yml` y
  `scripts/ci_gate.py`, después de B0 y para añadir el trabajo `cli-python-matrix` junto con el
  test que ejecuta (D8, sección 4.2), con `tests/test_ci_gate.py` (coherencia entre la matriz y
  los trabajos esperados); y
  `tests/data/uncatalogued_pending/{cli,doctor}.json` (los vacía).
- **Tamaño:** del inventario i18n, sin docstrings: `cli` 179, `checks` 160, `residency` 60,
  `topology` 37, `benchmark` 31, `llamaswap_api` 30, `test_windows` 15, `doctor` 13,
  `llamaswap_config` 12, `matrix` 7 y `daemon`/`turn` 5. Son unos 550 literales; los 97 de
  `install` y `update` pasan a B5. A esto se suman los
  aproximadamente 35 que el detector no ve (i18n «límites»). Unas 200 frases que hoy se arman por
  trozos se reescriben enteras.
- **Proceso de catálogo:** un script del scratchpad extrae de `i18n-inventory.csv` las filas de los
  ficheros de la ola y propone las claves. El borrador en inglés sale de `local_translate`, por
  lotes de unas 50 frases (`path` a un JSONL), y **se revisa entero**: marcadores `{}`,
  identificadores entre comillas invertidas, longitud. Lo revisado se fusiona en los
  `en/<superficie>.json` de la ola. Las olas B2, B4 y B5 siguen el mismo proceso.
- **Tests y su control positivo:**
  - *`--help` en español* no contiene «usage:», «options:» ni «show this help»; *en inglés*, no
    contiene ninguna cadena del catálogo `es` que difiera de la inglesa. Mutante: quitar el parche
    de argparse (D8); falla el caso español.
  - *`doctor` en los dos idiomas*, con los ids que no cambian.
  - *formato de números:* `20.027` en español y `20,027` en inglés.
  - *`test_wiki`:* compara con los títulos `es` del catálogo. Mutante: cambiar un título en
    `es/doctor.json` sin cambiar su fila; falla.
  - *`doctor`* muestra «variable», «preferencia», «sistema» o «reserva» con la ruta.

- **Partición aprobada (2026-10-14, `waves/B1-proposal.md` §3 y «Decisiones aprobadas»):** cinco
  PR mezclados en serie, B1a → B1b → B1c → B1d → B1e. Tamaño **medido** con el escáner del guardián
  de B0b: 728 textos únicos (578 del paquete y 150 de los tres scripts, que el tamaño de arriba no
  contaba) más ~45 msgid de argparse.
  - **B1a — armazón del CLI:** `resources/i18n/{es,en}/{cli,argparse}.json`, el parche de argparse
    en `cli.py` (restaurado al salir de `run()`), `i18n.format_number` (desviación registrada:
    `i18n.py` es de B0), **todo** `cli.py` (incluidos los 57 textos de `install`/`update`/`uninstall`
    que viven en él), `deprecations.py`, `entrypoint.py`, `test_windows.py`, `recompute.py` y
    `daemon.py`; `tests/test_cli_english.py` con `test_argparse_msgids_covered`; `cli-python-matrix`
    (3.11–3.15) en `ci.yml`, `ci_gate.py` (`PYTHON_WITHOUT_WHEELS`), `tests/test_ci_gate.py` y los
    clasificadores de `pyproject.toml`; la fila `sin_cruce` de `rename-exceptions.md`. ~216 textos.
    **Arreglo en el PR #311 (2026-10-14):** (1) la redacción del aviso de nombres obsoletos pasa de
    `deprecations.py` a `deprecation_notices.py` nuevo, porque el `import i18n` diferido de
    `deprecations` cerraba el ciclo `config → deprecations → i18n → config` (alerta de CodeQL
    `py/cyclic-import`; la fila de CodeQL de los riesgos ya pedía que `deprecations.py` no importe
    nada del paquete) y un test lo vigila; (2) la 3.15 es bloqueante como las demás, con su
    clasificador: su celda instaló y pasó en el CI. B1a la había dejado en `PYTHON_WITHOUT_WHEELS`
    por una prueba local con la 3.15.0a7 en Windows, que no representa la final en ubuntu; la lista
    queda vacía, con un test que ejerce el mecanismo, y solo vale el log de la celda del CI.
    **Segundo arreglo (fix(ci), mismo PR):** CodeQL marcó `PYTHON_WITHOUT_WHEELS` como global sin
    usar (`py/unused-global-variable`: solo la leían los tests), así que el mecanismo se quita entero
    de `ci_gate.py`, `ci.yml` y `test_ci_gate.py`; todas las celdas de la matriz bloquean y todas
    tienen su clasificador. Si una versión futura sale sin wheels, la exclusión se reintroduce junto
    con su uso real en `ci_gate.py` (la política de D8 sigue valiendo; su lista no existe hasta que
    haga falta).
  - **B1b — `doctor`:** `resources/i18n/{es,en}/doctor.json`, `checks.py`, `doctor.py`, `probes.py`,
    la línea de idioma en la cabecera de `doctor` (no es un check), el campo `stored_source` de
    `LanguageResolution` (desviación: `hook_common.py`) y el remedio de D11, `tests/test_wiki.py`,
    `tests/test_doctor_english.py`; borra `uncatalogued_pending/doctor.json` y el guardián pasa a
    exigir solo los pendientes de las olas abiertas. ~181 textos.
  - **B1c — llama-swap y `benchmark`:** `residency.py`, `topology.py`, `llamaswap_api.py`,
    `llamaswap_config.py`, `matrix.py`, `turn.py`, `benchmark.py`. ~181 textos.
  - **B1d — scripts:** `measure_cooldown.py`, `analyze_benchmark.py` y `pair_sheet.py` (claves
    `cli.script.*` en `cli.json`; hoja en el idioma del proceso, lector de las dos formas, `human`
    escrito como `tie` y `empate` leído para siempre); filas de `pair_sheet` en `rename-exceptions.md`;
    borra `uncatalogued_pending/cli.json`. ~150 textos.
  - **B1e — control del detector:** 60 + 60 frases nuevas con la regla de `B1-proposal.md` §5,
    congeladas en un commit anterior a la corrida; ≥ 98 %. El primero, a 8 tokens (`8be7ef7`), salió
    **FALLIDO** (116/120). El nuevo sigue la regla de D10 del 2026-10-14: ≥ 20 tokens, sin las 120
    del fallido ni las 40 de B0b, medido con `min_tokens=20`, en
    `tests/data/detect_language_control_b1_20.json`.
  - Formatos (REQ-026): coma decimal y punto de miles en español en la CLI; fechas en ISO 8601 UTC en
    los dos idiomas; las salidas MCP (B2) siguen sin separador de miles y con punto decimal.
  - Cada PR registra en su `waves/B1x.md` la revisión a mano del volcado inglés de su salida.

#### B2 — Salidas MCP, `local_status`, contrato, descripciones y prompts

Es **una sola ola**, la única dueña de `server.py` en el frente B, con dos lotes en serie (B2a y
B2b), cada uno con su commit y su PR. Los dos salen en la **misma versión**.

**Enmienda del 2026-10-14 (propuesta `waves/B2-proposal.md`, aprobada por la sesión principal y el
usuario).** La ola se parte en **cinco PR en serie**, todos en la 0.36.0:
**B2a → B2b-1 → B2b-2 → B2c → B2d**, seguidos del lote **B2-affinity** (re-evaluación de afinidad
en vivo) **antes del PR de release**.

- **B2a:** lo de «B2a» de abajo.
- **B2b-1:** contrato `_local_delegate` y marcadores (REQ-010) y descripciones en inglés (REQ-027),
  con `tools.json`, `test_tool_contract.py` y la wiki del contrato.
- **B2b-2:** idioma de respuesta (REQ-028) con `i18n.response_language()` (en `i18n.py`, no en
  `server.py`: `doctor` también la usa), la orden de idioma **detrás** de `_guard` (los prompts no se
  traducen), `LOCAL_DELEGATE_OUTPUT_LANGUAGE`, el idioma por defecto de `commit_msg` (valor explícito
  `diff` para la regla del diff), la frontera por la versión `v` de cada fila y `measurement_boundaries.json` (REQ-041), y
  `PROMPT_BOUNDARIES` versionada en `scripts/build_corpus.py`.
- **B2c:** lo de «B2c» de abajo; `truncated`/`warning` de `_local_delegate` pasan a significar «salida
  truncada en un trozo» (contrato y CHANGELOG).
- **B2d:** `tests/fixtures/lang_sample/`, el arnés en proceso (`scripts/dev/lang_sample.py`) y las
  muestras en vivo de D10, de `LOCAL_DELEGATE_OUTPUT_LANGUAGE` y de B2c en **una** ventana de prueba;
  se vacía la sección «pendiente» de `rename-exceptions.md`. Si el llama-swap local pide credencial
  fuera del daemon, se para y se pregunta antes de planificar ningún reinicio del daemon.
- **B2d-2 (enmienda del 2026-10-15):** lo de «B2d-2» de abajo; salida de `local_summarize` y
  `local_lint_summary` sin pérdidas (tope de lint, secciones vacías, corte por tope y largo crudo en
  el log; ampliado con sección repetida, contenido inventado en lint, etiquetas copiadas en
  summarize y lectura cp1252 del juez). Va entre B2d y B2e.
- **B2-affinity:** al añadir la orden de idioma, la celda aprobada `local_lint_summary` pierde su
  base (cambia su `prompt_sha256`). Se acepta durante el desarrollo; este lote re-evalúa la afinidad
  en vivo con los prompts nuevos para que la 0.36.0 salga con la base nueva.
- **Tests de corpus y afinidad** (`test_corpus.py` `check_versioned`, `check_versioned_affinity` y
  `test_affinity.py` de la huella): se actualizan en el lote que los rompe (B2b-2 y B2c), con su
  motivo, vía `PROMPT_BOUNDARIES` (aviso para `system`/`max_tokens` de las tools de la 0.36.0; error
  para todo lo demás).
- **Desviaciones de propiedad aprobadas** (cada una en el lote que la necesite y registrada):
  `doctor.py`/`doctor.json`, `topology.py`, `scripts/measure_structured_summary.py`,
  `scripts/build_corpus.py`, `matrix.py` y la wiki `Tools.md`/`Configuration.md`.
- **Referencias de línea de `server.py` actualizadas** (las de abajo son de antes de A7):
  `description` `:69-77`; `_truncation_prefix` `:475`; `_fallback_notice` `:1123`; respaldo
  `:2204`; aviso de truncado `:2457` y `:2802`; reduce por defecto `:3000-3013`; prompts
  `:3205-3357`; subclaves de `_local_delegate` `:3648-3667`; formato del commit `:3879-3887`;
  `local_explain_code` `:4033` (su `_read_input` con tope en `:4052`).
- **Juez de `LOCAL_DELEGATE_OUTPUT_LANGUAGE` en vivo (decisión 9):** no se amplía el detector a
  francés. La muestra en vivo usa el idioma **contrario** al del producto (producto `es` + variable
  `en`, y producto `en` + variable `es`), que el detector ya juzga, con el mismo criterio de ≥ 90 %
  por tool. `fr` y `português` quedan solo en los tests unitarios con backend falso (captura del
  prompt).

- **Posee la ola entera:** `server.py`, `failures.py` (etiquetas, con `t_lang` para D6),
  `chains.py` (`describe`), `sections.py` (aviso), `questions.py` (textos de las preguntas al
  cliente; asignado por B0 el 2026-10-14), `resources/i18n/{es,en}/{mcp,tools}.json`,
  y el uso de `topology.reason_text()` en `chains.py` y `server.py` (hallazgo de B1c del
  2026-10-14: hoy imprimen crudo el motivo de REQ-002, un valor de máquina en español; al
  hacerlo, B2 saca «sin LLAMASWAP_CONFIG» de `PENDING_FRAGMENTS`),
  `tests/data/uncatalogued_pending/mcp.json`, los tests nuevos `tests/test_mcp_english.py` y
  `tests/test_tool_contract.py`, `scripts/data/measurement_boundaries.json` (nace),
  `docs/wiki/Configuration.md` (solo `:221-234`, el contrato, y la entrada de `LOCAL_DELEGATE_OUTPUT_LANGUAGE`), `tests/fixtures/lang_sample/` (D10)
  y `rename-exceptions.md` (se vacía la sección «pendiente»).
- **B2a, salidas y `local_status`.**
  - **REQ:** 023, 026 (MCP: enteros sin separador y decimales con punto), 019 (`local_status`
    muestra el idioma, su origen y la ruta) y 033 (prosa vieja tal cual).
  - **Toca:** en `server.py`, los errores tras el prefijo, los recibos, el troceado y
    `local_status`; además, `failures.py`, `chains.py`, `sections.py` y `mcp.json`.
  - **Tamaño:** 159 literales en `server`, 33 en `failures` y unos 10 en `chains`/`sections`.
- **B2b, contrato, descripciones y prompts.**
  - **REQ:** 010, 027, 028 y 041 (la versión `v` de las filas de uso y fronteras de las
    descripciones y los prompts).
  - **Toca:** en `server.py`, los docstrings, las anotaciones, la `description` (`:68-73`), las
    subclaves de `_local_delegate` (`:3612-3631`), los marcadores (`:474`, `:1099`, `:2169` y
    `:2422`) y los prompts (`:3201-3316` y `:2964`) (la versión de la fila ya va en `v`);
    además, `tools.json`, `measurement_boundaries.json`, la wiki del contrato, `lang_sample/` y
    `rename-exceptions.md`.
  - **Tamaño:** 11 docstrings (8 771 caracteres), 11 títulos y 1 descripción; 5 subclaves y 3
    marcadores; unos 14 sitios de prompt.
- **Tests y su control positivo:**
  - *contrato:* `_local_delegate` con `truncated`/`warning`, y ninguna clave vieja.
  - *descripciones:* no cambian con `LOCAL_DELEGATE_LANG`. Mutante: pasarlas por `t()`.
  - *prompts:* las 4 tools piden el idioma vigente. **Enmienda del 2026-10-14 (decisión del
    usuario, tras la revisión `evidence/local-tools-review/report.md`):** `local_commit_msg` ya no
    usa «el idioma predominante del diff» por defecto, porque en repos bilingües el modelo elige
    uno u otro (reproducido: el diff de B0a salió en inglés, el de B1a en español). Precedencia:
    `LOCAL_DELEGATE_COMMIT_LANGUAGE` → idioma vigente del producto (`resolve_language`); la regla
    del diff queda solo como valor explícito de la variable. `LOCAL_DELEGATE_OUTPUT_LANGUAGE` no se
    aplica a `commit_msg`. Tests: sin la variable, con idioma vigente `es` el prompt pide español
    y con `en` inglés; con la variable puesta, manda ella; con el valor explícito de la regla del
    diff, el prompt de hoy. Mutante: volver al «predominante» por defecto (falla el de «sin la
    variable»).
  - *idioma de respuesta en texto libre (enmienda de REQ-028 del 2026-10-14, issue #260):*
    `LOCAL_DELEGATE_OUTPUT_LANGUAGE` en `config.py` (lectura con validación: 1–40 caracteres, sin
    saltos ni control) y una sola función en `server.py` que resuelve el idioma de respuesta
    (variable de salida → idioma vigente) y que usan las 4 tools, también en cada paso del
    troceado. `local_status` (y `doctor`, vía la misma función) muestran el valor efectivo y su
    origen. `config.py` es de B0: B0 deja la lectura de la variable y B2b la usa. Tests: puesta
    (`fr`, `português`) → aparece en el prompt de las 4 tools y en cada paso del map-reduce;
    vacía o no válida (`"a\nb"`, 41 caracteres) → prompt del idioma vigente y aviso;
    `local_commit_msg` idéntico con y sin ella. Mutantes: ignorar la variable (fallan los de
    «puesta»); aplicarla también a `commit_msg` (falla el de `commit_msg`); ponerla solo en el
    paso de reducción (falla el del map-reduce). Muestra en vivo en la misma ventana de D10 con la
    variable puesta al idioma **contrario** al del producto (enmienda del 2026-10-14, decisión 9:
    producto `es` + `en` y al revés; ≥5 documentos por tool, ≥90 % en el idioma de la variable,
    juzgado con el detector de D10), en `evidence/B2/lang-sample.json`; `fr`/`português` solo en
    tests unitarios. La wiki (`Configuration.md`) documenta la variable.
  - *recibos en inglés:* sin cadenas `es` del catálogo.
  - *números:* `20027`, no `20,027`.
  - *muestra en vivo de D10:* se guarda en `evidence/B2/lang-sample.json` con el id de la ventana.
  - *fronteras:* el test de dos máquinas sobre `usage-*` (fila con `v` vieja y fecha
    posterior → tramo «antes»).
- **Cierre de B2:** la sección «pendiente» de `rename-exceptions.md` queda vacía.

#### B2c — Cuerpo de `local_commit_msg` y troceado de `local_explain_code`/`local_extract`

Lote nacido el 2026-10-14 de la revisión `evidence/local-tools-review/report.md` (ventana de prueba
`w-20261014T182701Z`). Va **en serie después de B2b** (mismo `server.py`) y sale en la 0.36.0.

- **Cuerpo del commit:** hoy el formato dice «cuerpo opcional» (`server.py:3879-3887`) y los topes
  son 256 tokens (una llamada) y 244 en el paso final del troceado (`max_words=90`); el modelo para
  solo con 53–66 caracteres. Cambio: cuerpo obligatorio de 2–6 viñetas, también en el paso final,
  y topes de ~700 tokens y `max_words≈250`. Tests con backend falso que capture prompt y tope.
  Mutante: el formato y los topes de hoy (falla por el assert del cuerpo o del tope, no por otro).
- **Troceado:** `local_explain_code` y `local_extract` truncan a 20 000 caracteres en una sola
  llamada (`server.py:4033`); este mes, 10 de 24 llamadas de `explain_code` truncadas, y la
  explicación de `cli.py` (32 % leído) dio por completa una lista a la que faltaban subcomandos.
  Cambio: las dos pasan por `_chat_map_reduce`, partiendo por `def`/`class` de primer nivel en
  `explain_code` y llevando la pregunta (o los campos) al paso final. Test: un fichero de ~60 000
  caracteres con `def ZZZ_marker` al final llega al backend. Mutante: el camino de hoy (falla en
  ese assert).
- **Muestra en vivo:** en una ventana de prueba, `local_commit_msg` sobre los diffs de B0a y B1a
  (español con cuerpo) y `local_explain_code` sobre `cli.py` (menciona `doctor`, `benchmark` y
  `llamaswap`), en `evidence/B2c/live.md`. (Enmienda del 2026-10-14: se corre en B2d, en la misma
  ventana que la muestra de D10.)

#### B2d-2 — Salida de `local_summarize` y `local_lint_summary` sin pérdidas

Lote nacido el 2026-10-15 de la investigación `evidence/B2d-fix/chunking-model-investigation.md`
(§2 «Presupuesto de salida» y §4), con sus tests fallando hoy en
`evidence/B2d-fix/investigation-tests/test_chunking_language_investigation.py` (B1 y B2). Va **en
serie después de B2d y antes de B2e** (mismo `server.py` y `sections.py`, dueña B2) y sale en la
0.36.0. Los cuatro primeros puntos no son de idioma: la salida se corta o se pierde, y eso ensucia
cualquier medición de idioma posterior. Los cuatro siguientes (ampliación del 2026-10-15) salieron
de la medición en vivo del conjunto 3 (`evidence/B2d-fix/lang-sample-set3-batch1.json` y
`lang-sample-set3-batch2.json`): secciones repetidas, contenido inventado, etiquetas copiadas y el
juez que no lee ficheros cp1252.

**Fuera de este lote:** la decisión de cómo juzgar el idioma se tomó en B2d: se juzga solo la prosa
(`scripts/judge_response_language.py`, reglas en `evidence/B2d-fix/judge-rules.md`).

- **Tope de salida de `local_lint_summary`.** La llamada directa pide `2·max_words+96 = 496` tokens
  (`server.py:4168`) y cada parcial del troceado y el reduce `2·w+64 = 464` (`_tokens`,
  `server.py:3152-3153`). Con la orden de idioma endurecida (`71846c1`), `gemma4-26b-a4b` en lint
  pasó de 3 de 22 truncadas a 3 de 4, todas paradas justo en 496.
  - *Cambio:* dimensionar los dos topes (directo y por trozo) con medición, no a ojo.
  - *Medición antes/después:* % de llamadas con `finish_reason="length"` en lint, por modelo, con
    los mismos documentos de `lang-sample-docs-2.json` y del conjunto 1, en una ventana de prueba;
    el troceado forzado con `LOCAL_DELEGATE_MAX_CHARS_LONG=8000` sobre `en-log-biome-lint.txt` y
    `lint-9k.txt`, comprobando `chunks > 1` en el log antes de juzgar. En `evidence/B2d-2/live.md`.
  - *Hecho cuando:* 0 truncadas de `gemma4` en lint con los documentos de la muestra (o el % que se
    fije con la medición de antes, nunca por encima del 3/22 previo al endurecimiento).
  - *Test:* backend falso que captura `max_tokens` del camino directo y de cada paso del troceado.
    Mutante: los topes de hoy (falla el assert del tope, no otro).
- **Sección vacía en el documento avisada como «no resumida».** `complete` cuenta como `empty` una
  sección cuyo cuerpo tiene menos de `min_content` palabras (`sections.py:276-282`, `:345-353`) sin
  mirar si el original ya estaba vacío (caso `## Release Information` de httpx2, seguido directamente
  de `## 2.13.1`), y añade «1 section not summarized». Además, `allocate_by_size` mide el tramo con
  el título incluido y le pide ~23 palabras a una sección sin contenido, lo que invita a inventar.
  - *Cambio:* una sección vacía en el original ni se avisa ni recibe presupuesto de palabras.
  - *Test:* `test_B1_a_section_empty_in_the_document_is_not_reported_as_not_summarized` pasa a verde
    y entra en `tests/`, más uno de `allocate_by_size` (0 palabras para el tramo sin cuerpo).
    Mutante: volver a medir el tramo con el título / a contar como `empty` sin mirar el original
    (falla el assert del aviso o del presupuesto).
- **El corte por tope puede borrar una sección entera.** Con `truncated=True`, `complete` quita la
  última línea si «parece título» (`sections.py:318-319`), sin mirar su largo: una línea larga que
  empieza por `#` con el cuerpo pegado se pierde entera. Caso probable de httpcore2 en la tanda 1
  (`max_tokens=2112` agotados, 752 chars entregados y `## Changelog` vacío).
  - *Cambio:* solo se quita la última línea si es de verdad un título cortado (largo de título, sin
    cuerpo detrás), no cualquier línea que empiece por `#`.
  - *Test:* `test_B2_truncation_drops_a_whole_long_last_line_that_starts_with_hash` pasa a verde y
    entra en `tests/`, con un caso de control de un título corto cortado que sí se quita. Mutante:
    la condición de hoy (falla el assert de la línea larga, no el del título corto).
- **Largo de la salida cruda del modelo en el log.** Hoy no se registra, y por eso httpcore2 no se
  puede diagnosticar (§4.2 de la investigación: ~2 000 tokens perdidos sin saber si por el corte,
  por espacios degenerados o por razonamiento oculto).
  - *Cambio:* `_log_event` (`server.py:724`) guarda el largo en caracteres de la salida del modelo
    **antes** del post-proceso (`_strip_think` y `complete`), junto al `chars_out` de hoy. Campo
    nuevo en inglés (regla del frente A), sin el texto crudo (privacidad del log de uso).
  - *Test:* backend falso cuya respuesta pierde texto en `complete`; la fila del log tiene el largo
    crudo mayor que `chars_out`. Mutante: registrar el largo después del post-proceso (falla).
  - *En vivo:* repetir httpcore2 en la ventana de la medición del primer punto y explicar el caso
    con el campo nuevo, en `evidence/B2d-2/live.md`.
- **Sección repetida en `local_summarize`.** La sección «Introduction»/«Introducción» que añade el
  producto se duplica cuando el documento ya trae una sección con ese nombre (pycparser, tanda 1 del
  conjunto 3).
  - *Cambio:* si el documento ya tiene una sección con el nombre de la que añade el producto (en
    cualquiera de los dos idiomas, sin distinguir mayúsculas), no se añade otra; el resumen sale con
    una sola.
  - *Test:* documento con `## Introduction` propia; la respuesta (backend falso) tiene exactamente
    una sección de introducción, en `es` y en `en`. Caso de control: documento sin esa sección
    sigue recibiendo la del producto. Mutante: añadir siempre la sección (falla el assert del
    recuento, no el del control).
  - *En vivo:* repetir pycparser en la ventana de la medición del tope, en `evidence/B2d-2/live.md`.
- **Contenido inventado en `local_lint_summary`.** En el conjunto 3 aparecen cifras y afirmaciones
  que no están en el log: «Missing MCP Credentials (2)», «4 errores» o «72 errores» sin respaldo,
  `scripts/build_corpus.py` presentado como fichero con errores, frases repetidas y ~30 hashes
  listados en `corpus-affinity-check`, que además se cortó en 496 tokens.
  - *Cambio:* a decidir con la medición, no a ojo (prompt con «solo lo que está en el log», recuentos
    calculados por el programa cuando el formato lo permite, o ambos). Va **ligado al punto del
    tope**: parte de lo inventado (repeticiones, listas de hashes) aparece al llegar al tope, así que
    se mide después de dimensionarlo, y se mide de nuevo si el tope cambia.
  - *Medición de fidelidad:* un conjunto de logs **fijado antes de medir** (en
    `evidence/B2d-2/fidelity-set.json`, con el sha256 de cada log y, por log, las cifras y ficheros
    que sí contiene), que incluya `corpus-affinity-check.txt` y los logs del conjunto 3 con
    invenciones. Se cuenta, por respuesta, cada cifra o fichero que no está en el log y las frases
    repetidas; antes y después, en una ventana de prueba, en `evidence/B2d-2/live.md`.
  - *Hecho cuando:* 0 cifras ni ficheros inventados y 0 frases repetidas en el conjunto fijado (o el
    umbral que se escriba en el JSON antes de medir, nunca peor que la medición de antes).
  - *Test:* el contador de invenciones con un control positivo (una respuesta con una cifra y un
    fichero inventados que detecta) y uno negativo (una fiel que deja en 0). Mutante: el contador
    que no mira el log (falla el control positivo).
- **Etiquetas copiadas en `local_summarize`.** Copia subtítulos del documento como etiquetas
  `**…**` en el otro idioma (5 en la tanda 1 y 4 en la tanda 2 del conjunto 3). No tumba el juez de
  prosa, pero va contra la orden de idioma.
  - *Cambio:* la orden de idioma de `local_summarize` cubre también las etiquetas, como se hizo en
    B2d con `local_lint_summary` (§3 de «Juez de prosa y etiquetas» en `waves/B2d.md`).
  - *Test:* el prompt de `local_summarize` en `es` y en `en` lleva la regla de etiquetas (backend
    falso que captura el `system`). Mutante: quitar la regla (falla el assert de la regla, no otro).
  - *Medición:* contar las etiquetas copiadas en el otro idioma (la regla de `live-probe-X.json`)
    con los documentos del conjunto 3; *hecho cuando* 0, en `evidence/B2d-2/live.md`.
- **El juez lee el documento en UTF-8 estricto.** `scripts/judge_response_language.py`
  (`:181` y `:184`) usa `read_text(encoding="utf-8")` y falla con ficheros cp1252 (por ejemplo
  `evidence/B2d-fix/docs-3/es-log-B2c_corpus-f2-check.txt`), mientras el servidor lee con
  `errors="replace"` (`server.py:491`).
  - *Cambio:* el juez lee el documento y las respuestas como el servidor, con `errors="replace"`.
  - *Test:* documento con bytes cp1252 (por ejemplo `0xE9`) que el juez procesa sin excepción y
    con veredicto. Mutante: volver a UTF-8 estricto (falla con `UnicodeDecodeError` en ese test).
- **Cierre del lote:** suite completa en `es` y en `en`, `ruff`, corpus y afinidad como en B2c (los
  topes de lint cambian el `max_tokens` del corpus: frontera en `PROMPT_BOUNDARIES` con su motivo),
  CHANGELOG, y registro en `waves/B2d-2.md` con las llamadas `local_*`.

#### B2d-3 — `local_lint_summary` sin cifras inventadas

Lote nacido el 2026-10-15 de la medición en vivo de B2d-2 (`evidence/B2d-2/live.md`, punto 6): con
el tope nuevo, `fidelity_total` subió de 9 a 12 en los 10 logs del conjunto 3. Revisado a mano
(A13, `doctor` con el home vacío): las cifras son reales, recuentos por elemento («Claude Code
Client (3)») que el log no trae. El prompt de lint pide «la cantidad por tipo de error/regla» y el
modelo la inventa cuando el log no tiene cifras. Va **en serie después de B2d-2 y antes de B2e**
(mismo `server.py`) y sale en la 0.36.0.

- **Cambio, en dos pasos medidos con el mismo conjunto** (`evidence/B2d-2/fidelity-set.json`, sin
  tocarlo):
  1. *Prompt:* la cantidad solo cuando el log la da o cuando se cuentan líneas que el log repite; si
     no, sin número. Se mide.
  2. *Si el paso 1 no llega a 0:* el programa revisa la salida contra el log con la lógica de
     `scripts/score_lint_fidelity.py` (sin duplicarla: se mueve a `src/` y el script la importa) y
     quita los recuentos entre paréntesis que el log no respalda. Se mide otra vez.
- *Test:* por paso, con un log sin cifras y un modelo simulado que devuelve «(3)»; mutante que quita
  la regla o la revisión, y comprobar qué assert salta. Control: un log con cifras reales conserva
  las suyas.
- *Medición:* `score_live.py answers` sobre los 10 logs del conjunto 3, en `es` y en `en` (tandas A y
  B de `manifest.json`, solo lint), en ventanas de prueba. *Hecho cuando* `fidelity_total` = 0, y
  nunca por encima de 9; las cifras reales del control siguen ahí. El tope de lint no se vuelve a
  tocar (0 cortadas en B2d-2): si una respuesta sale cortada, se anota y no se juzga la fidelidad
  con ella.
- **Cierre del lote:** suite en `es` y en `en`, `ruff`, corpus y afinidad (el prompt de lint cambia:
  frontera en `PROMPT_BOUNDARIES`), CHANGELOG, y registro en `waves/B2d-3.md` con las llamadas
  `local_*`.
- **Resultado del paso 1 (2026-10-17, `8999bce`, n=1, ventanas `w-20261017T145849Z` y
  `w-20261017T145949Z`; `evidence/B2d-3/live.md`):** `fidelity_total` = 9 (B2d-2: 12; base de
  entonces: 9). Los recuentos entre paréntesis por elemento, lo que se buscaba, desaparecieron (A13
  tenía «3, 3, 3, 3» en B2d-2; ahora 0 inventados entre paréntesis en las 10). Quedan A11 2.5/3.5,
  A13 255, A15 «102» (el log acaba en la línea 100) y B33 52/127; A14 da 3 frases repetidas que son
  la misma regla en ficheros distintos (falso positivo del contador). **No se puede concluir con
  n=1:** comparado con B2d-2 en los mismos logs, A11 pasa de 0 a 2, A14 de 0 a 3, B35 de 4 a 0 y A13
  de 5 a 1. Y la medición tenía tres fallos:
  1. El contador no veía cifras escritas en palabras: A15 dice «eight instances of … (T201)» y el
     log trae 6 T201, y «three … (D103)» sobre 2 D103 tampoco salía.
  2. `check_controls.py` rechazaba «57.» al final de frase (`(?![\d.])`): B31 «Pruebas superadas:
     57.» salía como no conservada. Corregido, B2d-2 conserva A15 «10», B31 «57» y B32 «7»; el paso 1
     solo B31. **A15 y B32 perdieron la línea de total** («Found 10 errors.», «Found 7 errors.»);
     B32 da recuentos por tipo que suman 7, pero no el total. A14 no conservaba sus totales ni en
     B2d-2: ese caso no distingue.
  3. Una sola corrida por log, con la temperatura de lint (0.2), es ruido.
- **Cambio de método (decidido por el usuario el 2026-10-17), ANTES de seguir:** control corregido,
  contador que cuenta también las cifras de cero a veinte en palabras (inglés y español, sin
  «one/un/una/uno» ni «once»; con respaldo si su cifra lo tiene, también si el log la escribe en
  palabras) y que no cuenta como repetida una frase bajo dos encabezados de fichero distintos, y **3
  repeticiones por log**. Se miden con ese método tres versiones: base (`main` = `7a17941`), paso 1
  (`8999bce`) y paso 1b. Procedimiento: `evidence/B2d-3/measure.md`. Las respuestas n=1 del paso 1
  (`evidence/B2d-3/live-answers/`) quedan de referencia y no cuentan para el criterio.
- **Paso 2 (revisión por programa de los recuentos entre paréntesis): EN ESPERA.** El paso 1 no dejó
  ninguno que quitar. Se reabre solo si la medición nueva vuelve a dar recuentos entre paréntesis
  inventados.
- **Paso 1b, nuevo (2026-10-17):** si el contenido trae una línea de total («Found 10 errors.», «57
  passed»), el resumen la copia tal cual, en `_lint_count_clause()` (llamada única y reduce del
  troceado). No cambia la regla contra los recuentos inventados. Test con mutante en
  `tests/test_lint_count_rule.py`. Motivo: el control del paso 1 perdió los totales de A15 y B32.
- **Criterio de hecho revisado, fijado ANTES de medir (2026-10-17).** Con el método nuevo, 3
  repeticiones de las tandas A y B (10 logs × 3 = 30 respuestas por versión), contador nuevo; el
  «paso final» es la versión que se publica (1b, o 1 si 1b empeora):
  - *Fidelidad:* media de `fidelity_total` sobre las 3 repeticiones del paso final **≤ la media de la
    base** y **≤ 4,0** (tendente a 0: la mitad de 8, el menor total n=1 visto con el contador nuevo,
    el del paso 1).
  - *Paréntesis:* `parenthesized_invented` = **0** en las 3 repeticiones del paso final.
  - *Control:* los casos conservados del paso final (un caso se conserva si 2 de sus 3 repeticiones
    conservan una cifra real) incluyen **todos** los que conserva la base. Si la base no conserva
    A14, A14 no distingue: se anota y no se juzga.
  - Las respuestas cortadas (`finish_reason=length`) se anotan y no se juzgan. Si
    `identical_in_every_repetition` recoge las 10 llamadas de una versión, sus repeticiones no miden
    ruido: se anota y se mira por qué antes de concluir.
  - Si ningún paso cumple, se reabre el paso 2.
- **Resultado del método nuevo (2026-10-17, medido por la sesión principal; `evidence/B2d-3/live.md`
  y `runs/`):** base `7a17941`, paso 1 `8999bce` y paso 1b `20faa5e`, 30 respuestas cada una, 0
  errores, ventanas cerradas.

  | Versión | `fidelity_totals` | Media | Sin B35 | `parenthesized_invented` | Controles (2 de 3) | Cortadas |
  |---|---|---|---|---|---|---|
  | base | 9, 20, 6 | 11,67 | 8,67 | 0, 11, 0 | A15, B31, B32 | 0 |
  | paso 1 | 6, 7, 6 | 6,33 | 6,33 | 0, 0, 0 | B31, B32 | 0 |
  | paso 1b | 2, 5, 4 | 3,67 | 3,67 | 0, 0, 0 | A14, A15, B31, B32 | 3 |

  El paso 1b **cumple los tres criterios** (y conserva además A14, que la base no). **Regresión que
  el criterio no veía:** B35 (`B2d-fix/docs-3/es-log-B2d-fix_corpus-affinity-check.txt`, 89 líneas,
  sin línea de total, `gemma4-26b-a4b`) sale cortado por `max_tokens` en las 3 repeticiones del 1b
  (`finish_reason=length`, `chars_out` ~1700–1790); en la base y en el paso 1, ninguna vez. El
  modelo repite el mismo texto en un bloque por cada «commit-trampa-…» y «techo-commit-…» hasta
  agotar el tope. `identical_in_every_repetition` del 1b = `['A15']`. Log de uso: `gemma3-4b` 63
  llamadas y 0 cortadas, `gemma4-26b-a4b` 27 y 3.
- **Paso 1c (decidido por el usuario el 2026-10-17), criterio fijado ANTES de medir:** mantiene la
  regla del total del 1b y añade, en `_lint_count_clause()`, que los elementos con el mismo problema
  vayan en una sola línea que los nombre juntos (sin número si el log no da la cifra), en vez de
  repetir el mismo texto por cada uno. Test con mutante en `tests/test_lint_count_rule.py`. Se
  **adopta** si cumple los tres criterios del 1b (media ≤ 11,67 y ≤ 4,0; `parenthesized_invented` = 0
  en las 3 repeticiones; controles ⊇ A15, B31 y B32) **y** tiene **0 cortadas** en las 30 llamadas.
  Si no, **se queda el 1b** (se revierte el commit del 1c) y el corte de B35 se anota como deuda.
  Comandos en `evidence/B2d-3/measure.md` (`--answers-dir $E/B2d-3/runs/step1c --repeat 3`, tandas
  A y B).
- **Resultado del paso 1c (2026-10-17, `d12f5af`, medido por la sesión principal; ventanas
  `w-20261017T160612Z` y `w-20261017T160828Z`; `evidence/B2d-3/live.md` y `runs/step1c/`):**
  `fidelity_totals` 1, 7, 1 (media **3,0**; 1b: 3,67), `parenthesized_invented` 0, 0, 0,
  `identical_in_every_repetition` = `[]`, controles A14 3/3, A15 2/3, B31 3/3 y B32 2/3. Pero
  **3 cortadas de 30**, otra vez B35 (`gemma4-26b-a4b`, `chars_out` ~1420): ahora agrupa, pero en
  una sola línea nombra los más de 80 elementos `commit-…` del log hasta agotar el tope.
  **Veredicto: el 1c no se adopta** (falla «0 cortadas»). **Se queda el 1b**: el commit del 1c se
  revierte (`src/` y `tests/` como en `20faa5e`) y su evidencia se conserva. El corte de B35 pasa al
  lote **B2d-4**, el siguiente en el orden.

#### B2d-4 — `local_lint_summary` no se corta con logs de muchos elementos iguales

Lote nacido el 2026-10-17 de la medición del paso 1c de B2d-3 (`evidence/B2d-3/live.md`). Con la
regla del 1b, B35 (`B2d-fix/docs-3/es-log-B2d-fix_corpus-affinity-check.txt`, 89 líneas, sin línea
de total, `gemma4-26b-a4b`) sale cortado por `max_tokens` en las 3 repeticiones: enumera uno a uno
decenas de elementos con el mismo problema; con el 1c los agrupa, pero los nombra todos en una
línea y también se corta. En la base y en el paso 1, ninguna vez. Es una **regresión que trae
B2d-3** y saldría en la 0.36.0, así que no va al backlog.

- **Sitio en el orden: en serie después de B2d-3 y antes de B2e** (mismo `server.py` y la misma
  `_lint_count_clause()`). No se mete dentro de B2e: B2e trata la pérdida al combinar los trozos, y
  B35 no se trocea (0 troceadas en `runs/score-log-1c.json`); el corte está en la llamada única.
  Pero el cambio tiene que valer también en el `reduce_extra` del troceado, como las reglas del 1 y
  el 1b.
- **Cambio candidato (se decide antes de medir):** limitar cuántos elementos iguales se nombran
  («… y N más», con N contado del log, no por el modelo), o resumir por tipo de problema sin listar
  los elementos. El tope de lint no se toca (regla de B2d-2/B2d-3).
- **Decisión (2026-10-17, ANTES de medir): compactado por programa, no regla de prompt.**
  `local_lint_summary` pasa el log por `server.compact_repeated_lines()` antes de decidir si trocea:
  un bloque denso (miembros a ≤ 3 líneas uno de otro) de **10 o más** líneas iguales salvo **un**
  token se queda con sus 3 primeras líneas en su sitio y una línea «… y N líneas más como las
  anteriores», con N contado por el programa. Nunca agrupan una línea con ruta o posición de
  fichero (un log de lint por fichero llega entero), una línea de menos de 3 tokens ni un token que
  sea solo una cifra. La regla de la cantidad (`_lint_count_clause()`, también en `reduce_extra`)
  añade una frase: nombrar solo los que aparecen y escribir «y N más» con ese número. Por qué: el
  1c demostró que una orden de agrupar no basta (el modelo la obedece a medias); si el modelo no ve
  los 80 elementos, no los puede enumerar, y N no depende de que cuente bien. En el conjunto 3 solo
  compacta B35 (45 y 40 → 3 + marcador cada bloque; 89 → 12 líneas) y A12 (11 → 3 + marcador);
  A11, A13–A15 y B31–B34 llegan intactos. `scripts/score_lint_fidelity.py` acepta como cifra del
  log el tamaño de cada bloque compactado y su N (los cuenta el programa del mismo log; el test
  los comprueba contra una cuenta propia), y la base y el 1b se **re-cuentan** con ese mismo
  contador antes de comparar. Medición: `evidence/B2d-4/measure.md`.
- **Resultado (2026-10-17, `ea5b27a`; ventanas `w-20261017T221618Z` y `w-20261017T221834Z`;
  `evidence/B2d-4/live.md`):** **0 cortadas de 30** (B35 ya no se corta), `parenthesized_invented`
  0, 0, 0, controles A14, A15, B31 y B32 (3/3 cada uno), pero `fidelity_totals` 20, 5, 5 (media
  **10,0**: > 4,0). **No cumple el criterio; no se adopta tal cual** (el commit queda en la rama a la
  espera de la decisión del usuario). De los 30 puntos, 13 son un caso intacto (A13 r1, «0 issues»
  ×13) y 6 son cifras reales que el contador no ve (B31: 41 y 16 tests por fichero); la regresión
  propia del cambio es A12 (1, 2, 2: el modelo cuenta las líneas que ve). El 1b de `main`
  re-medido en la misma sesión (ventanas `w-20261017T222234Z` y `w-20261017T222436Z`) da 5, 5, 6
  (media 5,33, también > 4,0), B32 1/3 y otra vez **3 cortadas** (B35). Siguiente candidato
  propuesto en `live.md`: el marcador con el total del bloque, sin la frase nueva en la regla, y
  medir contra el 1b re-medido el mismo día revisando el umbral de 4,0.
- **Segunda ronda (decisión del usuario, 2026-10-17, ANTES de medir):**
  1. *Cambio:* el marcador lleva también el total del bloque, «… y 8 líneas más como las
     anteriores (11 en total)», las dos cifras contadas por el programa; y **se quita la frase
     nueva** de `_lint_count_clause()`, que vuelve a ser la regla del 1b palabra por palabra (el
     marcador ya es «una cifra que el contenido escribe»).
  2. *Criterio, cambiado:* el «≤ 4,0» fijo se sustituye por **«media no peor que la de `main`
     medida en la misma sesión con el mismo método»**. Motivo: el 3,67 del 1b salió de una sola
     sesión, y el propio `main` (1b) re-medido hoy da 5,33 (> 4,0); la variación entre sesiones es
     del tamaño del margen, así que un umbral fijo mide la sesión y no el cambio. Lo demás se
     mantiene: **0 cortadas en 30**, media ≤ 11,67, `parenthesized_invented` = 0 en las 3
     repeticiones y controles ⊇ A15, B31 y B32.
  3. *Contador:* `scripts/score_lint_fidelity.py` reconoce como cifras del log los tests
     distintos por fichero de un log de pytest (B31 nombra cada test dos veces: los «41» y «16»
     reales contaban como inventados). Validado contra revisión a mano antes de aplicarlo:
     `evidence/B2d-4/counter-validation.md`. Se reportan las cifras con los dos contadores.
  4. *Medición:* en la misma sesión, `main` (árbol aparte) y la versión nueva, tandas A y B,
     `--repeat 3`, tags nuevos (`round2-main`, `round2-new`). Método: `evidence/B2d-4/measure.md`,
     sección «Segunda ronda».
- **Resultado de la segunda ronda (2026-10-17, `6408477`; `evidence/B2d-4/live.md`, «Segunda
  ronda»):** nueva: **0 cortadas de 30**, `fidelity_totals` 11, 6, 7 (media **8,0**; contador
  viejo 10,0), `parenthesized_invented` 0, 0, 0, controles A14, A15, B31 y B32 3/3. `main` en la
  misma sesión: 6, 6, 5 (media **5,67**; viejo 6,33), **2 cortadas** (B35), B32 2/3. **No cumple
  «no peor que `main`»: no se adopta** (los commits quedan en la rama a la espera del usuario).
  Dentro: 8 de las 10 llamadas mandan el mismo prompt en las dos versiones, y en ellas la nueva
  suma 22 y `main` 13 (A13 sola: 16 frente a 6), ruido mayor que toda la diferencia; en las 2 que
  el cambio toca (A12, B35), nueva 2 (un falso positivo del contador) y `main` 4 más 2 cortes.
  Propuesta en `live.md`: criterio sobre las llamadas cuyo prompt cambia, con las demás como
  control de ruido, o más repeticiones.
- **Decisión del usuario (2026-10-17): se adopta la segunda ronda (`6408477`).** Se le presentaron
  tres salidas (fijar antes de medir un criterio sobre las llamadas cuyo prompt cambia y medir otra
  vez, adoptar ya, o subir a `--repeat 10`) y eligió adoptar ya, con la evidencia actual: 0 cortes
  frente a 2 de `main`, y mejor en las 2 llamadas que el cambio toca. Riesgo asumido y anotado: el
  reparto «llamadas tocadas / no tocadas» se miró después de ver los números. Queda para B2e el
  falso positivo del contador con el guion bajo escapado en Markdown (`build\_corpus.py`).
- *Test:* con un log sintético de decenas de elementos con el mismo problema; mutante que quita la
  regla y comprobar qué assert salta. Si N lo calcula el programa, test de N contra el log.
- *Medición:* el método de B2d-3 (`evidence/B2d-3/measure.md`: tandas A y B, 3 repeticiones,
  ventanas de prueba). *Hecho cuando* tiene **0 cortadas en 30** y además cumple los tres criterios
  del 1b contra la base (media ≤ 11,67 y, desde la segunda ronda del 2026-10-17, **no peor que la
  de `main` medida en la misma sesión** en lugar de ≤ 4,0; `parenthesized_invented` = 0, controles
  ⊇ A15, B31 y B32).
- **Cierre del lote:** suite en `es` y en `en`, `ruff`, corpus y afinidad, CHANGELOG, y registro en
  `waves/B2d-4.md` con las llamadas `local_*`.

#### B3 — Hooks

- **REQ:** 024, 041 (conjunto de hashes y lectura en `measure_adoption.py`) y 034 (humo de hooks).
- **Posee:** `resources/hooks/*.py` (textos de `HOOK_TEXTS` en ASCII; `hook_common.py`, después de
  B0), `scripts/measure_adoption.py` (lectura de fronteras), `scripts/bump_version.py`
  (`--boundaries`), un fichero aparte `scripts/data/hook_hashes_after.json` (el conjunto de hashes,
  que `measurement_boundaries.json` referencia; así B3 no comparte el fichero de B2), los tests de
  hooks, `tests/test_measure_adoption.py` y `tests/data/uncatalogued_pending/hooks.json`.
- **Tamaño:** 7 mensajes, 4 de ellos con interpolación (i18n §1e).
- **Dependencias:** B2b (el fichero de fronteras) y A10a (nombre del script).
- **Tests y su control positivo:**
  - *hook instalado lanzado como subproceso* con un `language.json` `en`: el motivo sale en inglés
    y en ASCII.
  - *guardián:* ningún hook importa `local_delegate`. Se crea si no existe. Mutante: añadir el
    import.
  - *ASCII:* todo el texto de `HOOK_TEXTS` es ASCII. Mutante: poner una tilde.
  - *hash actual en el conjunto.* Mutante: tocar un hook sin regenerar el conjunto.
  - *el conjunto solo crece* (D9): tras regenerar con un hook cambiado, el hash de la versión
    anterior sigue dentro. Mutante: sustituir en vez de unir.
  - *dos máquinas:* un evento con hash viejo y fecha posterior queda en «antes».

#### B4 — Panel

- **REQ:** 020, 025, 026 (panel), 027 (resumen de cada tool desde el catálogo), 032 (guardianes en
  los dos idiomas), 033 (prosa tal cual), 034 (humo del panel) y 043 (fixture de `locale` de
  Playwright).
- **Posee:** `web/metrics.py` (HTML, JS, inyección de los dos catálogos `panel.*` y `?lang=` de
  D6), `quota.py`, `valuation.py` y `attribution.py` (textos que llegan al panel por
  `/api/stats`; asignados por B0 el 2026-10-14), el escáner del panel del guardián de REQ-045
  (`tests/test_no_uncatalogued_text.py`, solo esa función), `resources/i18n/{es,en}/panel.json`,
  `tests/data/uncatalogued_pending/panel.json`,
  `tests/test_dashboard_ui.py` (usa el fixture de `locale` de B0 y parametriza por idioma),
  `tests/test_dashboard_js.py` y `tests/test_metrics.py` (`?lang=`). No toca `conftest.py`, que es
  de B0.
- **Tamaño:** unas 440 cadenas del panel (846 literales en `metrics.py`, de los que 310 los marcó el
  detector; el resto son etiquetas cortas y atributos). `fmtNum`, `Chart.defaults.locale` e
  `Intl.DateTimeFormat` pasan a depender del idioma.
- **Tests y su control positivo:**
  - *Playwright, selector:* se guarda en `localStorage` `ld-lang` **(plan)** y se recuerda al
    recargar.
  - *valor inicial:* `es-ES` → es y `en-US` → en; sin idioma declarado, en.
  - *dos visitantes en idiomas distintos* contra el mismo daemon.
  - *DOM en inglés:* ninguna cadena `es` que difiera de su versión inglesa. Mutante: dejar
    «Latencia» sin traducir; falla.
  - *`<html lang>`, `<title>` y descripción* siguen al selector.
  - *guardianes de «sin prosa»* (`test_dashboard_ui.py:581` y `:641`) parametrizados en es y en.
  - *sin el fixture de `locale` y con el navegador en `en-US`,* fallan los asserts en español. Se
    registra.
  - *`localStorage` bloqueado:* el selector funciona durante la visita y no hay errores en
    consola.

#### B5 — `install`, skill, bloques y preferencia

- **REQ:** 029, 047 (escritura por `install`/`update` y borrado por `uninstall`), 021 (mensajes de
  `install`, `update` y `uninstall` que no viven en `cli.py`: los de `cli.py` los traduce B1a,
  decisión del 2026-10-14), 034 (humo de `install`), 040 (precedencia en la wiki y D11)
  y 012 (resto: catálogo de subagentes).
- **Posee:** `install.py` (entero en el frente B: mensajes, escritura de `language.json`, elección
  del idioma de la skill y del bloque, y `uninstall`), `update.py` (entero en el frente B: mensajes
  y escritura de `language.json`), `agents.py` (encabezado bilingüe, `:41`, y reemplazo del bloque
  `<!-- local-delegate:catalog:begin -->` en cualquier idioma),
  `resources/skills/local-delegation/SKILL.md`, `SKILL.en.md` **(plan)**,
  `resources/memory/local-delegate.md` y `local-delegate.en.md` **(plan)**,
  `resources/i18n/{es,en}/install.json`, `tests/data/uncatalogued_pending/install.json`, la página
  de la wiki sobre el idioma, y los tests `test_install*.py`, `test_update.py`, `test_agents*.py`
  y el nuevo `tests/test_skill_parity.py`.
- **Tamaño:** 49 literales en `install` y 48 en `update`, más la skill (90 líneas) y el bloque de
  memoria.
- **Tests y su control positivo:**
  - *escritura de la preferencia:* los cinco casos de REQ-047 (dos idiomas de sesión; variable
    guardada más `update` sin la variable; sistema guardado más reserva; `update` con la variable;
    `uninstall`). Mutante: escribir la reserva; falla «sistema guardado + reserva».
  - *bloque 0.34.0 en español → reinstalar en inglés* deja un solo bloque.
  - *subagentes* con encabezado español, con inglés y con bloque 0.34.0.
  - *paridad de la skill:* las mismas tools `local_*` en es y en. Mutante: quitar una fila en
    `SKILL.en.md`.
  - *D11:* tras borrar `language.json`, se vuelve a seguir al sistema.
  - *D12 con el bloque inglés:* `packaged_memory_blocks()` gana el inglés. Con el idioma en `en`,
    un bloque inglés al día da `OK` y dos pasadas de `update` no lo reescriben. Mutante: quitar el
    inglés de la lista; falla.
- **Cierre del frente B:** todos los ficheros de `tests/data/uncatalogued_pending/` vacíos y segunda corrida del detector de
  REQ-016 («pendiente» vacía).

### 1.5 Ola de retirada (fuera del cierre de este SDD)

- **R, retirada de alias.** Cuando `pyproject.toml` llegue a 0.38.0, el test de horizonte falla y
  obliga a la retirada:
  - se quitan los alias de CLI, variables e interruptor y la doble escritura de
    `enfriamiento.json`;
  - se quitan sus entradas de `DEPRECATED_NAMES` y de `rename-exceptions.md`;
  - se actualizan el CHANGELOG, el README y la wiki.

  La lectura dual de datos **no** se retira nunca. Se apunta en el backlog del proyecto al cerrar
  este SDD.

---

## 2. Pasos `local_*` y PyCharm previstos por ola, y plantilla del registro

### 2.1 Mínimos por ola (REQ-036/037)

Las olas que corren la suite son todas. Los mínimos que mira el gate `conformance` son estos:

- `local_lint_summary(path=evidence/<ola>/pytest-full.log)` en **todas** las olas.
- **Olas y lotes que renombran Python** (A0–A7b, A8a, A9a–c y A10a–b): el número de filas
  `rename_refactoring` de `waves/<ola>.md` es **igual** al número de filas `method=pycharm` de
  `waves/<ola>-mapping.csv` (D13). Las filas `search_edit` se cuentan aparte y cada una lleva su
  motivo. Hay un `get_file_problems` o un `lint_files` por cada fichero del diff. Si PyCharm no
  responde, la fila pasa a `search_edit` con el motivo «PyCharm no responde», y el recuento sigue
  cuadrando. Además, la verificación de `scope` (D13) está completa: todas las filas
  `cross_module` y la muestra de `module_local` tienen la columna `verified` rellena, y las
  discrepancias se cuentan en el registro.
- **A8b y las B**, que no renombran Python: su tabla de PyCharm lleva al menos un `search_text` o
  un `search_regex` y un `get_file_problems` por fichero Python del diff, o su motivo.
- **Controles positivos:** cada fila tiene el assert que disparó.
- **Mapping aprobado:** la cabecera `# approved-by-main` está presente en cada mapping.
- **Comprobación automática:** `tools/check_wave_records.py` (A0) recorre `waves/*.md` y los
  mappings, comprueba todo lo anterior y escribe `evidence/conformance/wave-records.txt`, que es
  la evidencia del gate `conformance`. El script se prueba con un registro de prueba al que le
  falta la fila de `local_lint_summary`, y tiene que fallar.

| Ola | `local_*` previstas | PyCharm previstas |
| --- | --- | --- |
| A0 | `local_explain_code(path=tools/research-scanners/esdet.py)` y `(…/js_tok.py)` para portarlos; `local_lint_summary`; `local_commit_msg` | `search_symbol` del rol retirado, `analyze_calls` del check, 1 `rename_refactoring`, `get_file_problems` |
| A1 | `local_summarize(path=docs/wiki/Configuration.md, focus="variables y comandos")` para localizar menciones; `local_lint_summary`; `local_commit_msg` | `search_text` de los 6 nombres viejos, `rename_refactoring` ×2, `get_file_problems` |
| A2 | `local_explain_code(path=resources/hooks/hook_common.py, question="escritores de temporales y telemetría")`; `local_extract(path=scripts/medir_adopcion.py, fields=[claves leídas])`; `local_lint_summary`; `local_commit_msg` | `analyze_calls` INCOMING de las funciones de `hook_common`, `rename_refactoring`, `search_text` de claves y temporales, `get_file_problems` |
| A3 | `local_summarize(path=src/local_delegate/fallos.py, focus="enums y etiquetas")`; `local_lint_summary`; `local_commit_msg` | `rename_refactoring` del módulo, de `Clase`, `CausaConexion` y funciones; `search_regex` de los valores; `get_file_problems` |
| A4 | `local_summarize(path=scripts/medir_enfriamiento.py, focus="campos y valores leídos")`; `local_lint_summary` del log de P-4 si es largo; `local_lint_summary`; `local_commit_msg` | `rename_refactoring` del módulo, `analyze_calls` de los escritores, `get_file_problems` |
| A5a/b/c | `local_explain_code(path=…/atribucion.py, question="regla de fusión")`, `(…/recalcular.py, question="identidad del punto")`; `local_extract(path=resources/datos/precios.json, fields=[claves])`; `local_lint_summary`; `local_commit_msg` | `rename_refactoring` de los módulos y funciones, `search_text` de los 81 campos del panel que tocan, `get_file_problems` |
| A6 | `local_summarize(path=resources/skills/delegacion-local/SKILL.md)`; `local_lint_summary`; `local_commit_msg` | `rename_refactoring` de `secciones` y de las constantes de grupos; `search_text` de ids, skill y cookie; `get_file_problems` |
| A7a/b | `local_summarize(path=src/local_delegate/server.py, focus="secciones del fichero por línea")` para partir; `local_lint_summary`; `local_commit_msg` | `rename_refactoring` (lotes), `get_file_problems` |
| A8a | `local_lint_summary`; `local_commit_msg` | `rename_refactoring` de los módulos y lotes, `get_file_problems` |
| A8b | `local_explain_code(path=scripts/extract_dashboard_js.py)`; `local_lint_summary` (incluye el log de Playwright); `local_commit_msg` | `search_regex` de los identificadores JS e ids, `get_file_problems` |
| A9a/b/c | `local_lint_summary` (con la comparación de `--collect-only`); `local_commit_msg` | `rename_refactoring` por lotes, `get_file_problems`/`lint_files` |
| A10a/b | `local_extract(path=scripts/<x>.py, fields=["opciones","ficheros leídos"])` por script; `local_lint_summary`; `local_commit_msg` | `rename_refactoring` de los módulos y funciones, `get_file_problems` por script |
| B0 | `local_boilerplate(spec=…, target=tests/test_language.py)` para el armazón de los 9 casos (revisado); `local_translate` del `en/common.json` inicial; `local_lint_summary` ×2 (corrida `en` y corrida `es`); `local_commit_msg` | `search_regex("LANG\|LC_ALL\|LANGUAGE")` en `src/`, `get_file_problems` |
| B1 | `local_translate(path=evidence/B1/es-batch-N.jsonl, target_lang="en")` por lotes, **revisado**; `local_lint_summary` ×2; `local_commit_msg` | `search_text` de los literales por fichero, `get_file_problems` |
| B2a/b | `local_translate` por lotes (`mcp.*`); `local_summarize(path=…/server.py, focus="prompts al modelo local")`; los mismos 40 documentos de D10 por las 4 tools en la ventana de prueba; `local_lint_summary` ×2; `local_commit_msg` | `search_text` de `_local_delegate`, `aviso`, `respaldo` y `_guard`; `get_file_problems` |
| B3 | `local_translate` de los 7 mensajes (revisado, en ASCII); `local_lint_summary` ×2; `local_commit_msg` | `search_text("import local_delegate", resources/hooks/)`, `get_file_problems` |
| B4 | `local_translate` por lotes (`panel.*`); `local_describe_image` de las capturas ES/EN del panel, para comprobar que no hay texto sin traducir (además del test); `local_lint_summary` ×2 (Playwright incluido); `local_commit_msg` | `search_regex` en `web/metrics.py`, `get_file_problems` |
| B5 | `local_translate(path=…/SKILL.md, target_lang="en")` y del bloque de memoria (revisados contra el guardián de paridad); `local_lint_summary` ×2; `local_commit_msg` | `search_text("Delegaci")`, `get_file_problems` |

Lo que **no** se delega, en ninguna ola: decidir nombres, revisar diffs de `rename_refactoring`,
revisar traducciones y escribir los asserts de los controles positivos. Eso requiere criterio.

### 2.2 Cómo se vuelca la salida para delegarla

```
bash ~/.claude/scripts/pesado.sh uv run pytest -q -p no:cacheprovider > "evidence/<ola>/pytest-full.log" 2>&1
```

Después, `local_lint_summary(path=<ruta absoluta de ese log>)`. Con `pytest` no se usa xdist con
más de 2 workers. Los tests de node y Playwright van dentro de la misma corrida, que ya está bajo
el cerrojo.

### 2.3 Plantilla de `waves/<ola>.md`

```markdown
# Ola <id> — <título>

- Rama: `<rama>` · PR: #<n> · Commit(s): `<sha>` (firmado)
- REQ cubiertos: REQ-xxx, …
- Ficheros poseídos (según plan.md §1): …; tocados fuera de la lista: ninguno | <cuál y por qué>
- EOL: `evidence/<ola>/eol-check.txt` sobre todo el diff, con los renombres seguidos: 0 diferencias (sí/no)
- Mapping: `waves/<ola>-mapping.csv` aprobado (`# approved-by-main`); filas `pycharm` <n> = filas `rename_refactoring` <n>; filas `search_edit` <m>, cada una con su motivo
- Tests recogidos: antes <n> → después <m> (+<añadidos>, −0)
- Suite: `evidence/<ola>/pytest-full.log` (con `pesado.sh`), resultado <verde/rojo>

## Controles positivos
| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |

## Llamadas `local_*` (sesión principal y cada agente)
| Quién | Tool | Para qué | Resultado (útil / corregido / descartado) |
| --- | --- | --- | --- |
<!-- 0 filas exige motivo. Mínimo: local_lint_summary del log de la suite. -->

## Llamadas `mcp__pycharm__*`
| Quién | Tool | Símbolo o patrón | Resultado |
| --- | --- | --- | --- |
<!-- Olas que renombran Python: ≥1 rename_refactoring y ≥1 get_file_problems, o motivo. -->

## Revisión del diff tras rename_refactoring
- Cadenas o comentarios que PyCharm cambió y se repusieron: …

## Scripts (REQ-014, solo olas que renombran en src/)
| Script | `--help` | Corrida mínima o `get_file_problems` |
| --- | --- | --- |

## Desviaciones y nombres «(plan)» ajustados
- …
```

---

## 3. Releases

### 3.1 Qué sale en cada versión

| Versión | Olas | Qué anuncia (CHANGELOG, README y `docs/wiki/`, en español: REQ-040) |
| --- | --- | --- |
| **0.35.0** | A0–A6 (todo lo publicado del frente A) | Lo que hace: tabla viejo → nuevo de los comandos, opciones, variables, interruptor, hook, skill, ids y grupos de `doctor`, cookie y ficheros de datos. Plazos: alias vigentes hasta la 0.37.x, retirada en la 0.38.0, y la doble escritura de `enfriamiento.json`, que también se retira en la 0.38.0. Lo que rompe: «volver a una versión anterior no está soportado»; `doctor --json` cambia sus ids; una reautenticación en el panel; la ventana de «hooks nuevos con daemon viejo» hasta reiniciar. Wiki: Configuration (variables), Troubleshooting y Savings-and-metrics (checks, `quota-statusline.jsonl`), Integration-install (skill y hook) y Daemon (ficheros). |
| **0.36.0** | A7–A10 (internos, sin cambio funcional) + B0–B5 | Lo que hace: salida en español e inglés y precedencia del idioma. Lo que rompe: el **cambio de idioma por defecto** (con el sistema en inglés se pasa a ver inglés), con cómo elegir español (`install` con `LOCAL_DELEGATE_LANG=es`) y cómo volver a seguir al sistema (D11). La **tabla viejo → nueva del contrato de `local_extract` y de los marcadores** como cambio incompatible, y las descripciones de las tools en inglés como frontera de tramo de las mediciones. Wiki: página del idioma (precedencia y cómo verlo en `doctor` y `local_status`), Configuration (`LOCAL_DELEGATE_LANG`, contrato `:221-234`) y Tools. |
| 0.37.0 | — (nada obligatorio de este cambio) | Si hay release, sigue anunciando los alias vigentes y su retirada. |
| 0.38.0 | Ola R | Retirada de los alias y de la doble escritura. Fuera del cierre de este SDD. |

Entre A0 y A6 **no** se publica: todo lo renombrado de cara afuera sale junto, con un único
horizonte de alias. Entre B0 y B5 tampoco: una versión a medio traducir mezclaría idiomas. Si hace
falta un arreglo urgente en medio, va en una rama desde la etiqueta `v0.34.0` o `v0.35.0`, sin
meter nada de las olas a medio hacer.

### 3.2 Cómo se fija la versión de retirada de cada alias (REQ-004)

1. Cada ola registra sus alias en `deprecations.py` con `introduced="UNRELEASED"`, y añade su
   anuncio a `## [Unreleased]` del CHANGELOG. El test de CHANGELOG lo exige.
2. El PR de release ejecuta `python scripts/bump_version.py 0.35.0`. El script sube la versión en
   sus cuatro sitios, cambia todo `UNRELEASED` de `deprecations.py` por `0.35.0` y, con
   `--boundaries`, añade los hashes actuales al conjunto de hooks «después» sin quitar ninguno
   (unión acumulativa, D9; desde la 0.36.0).
3. En el mismo PR, `## [Unreleased]` pasa a `## [0.35.0] - <fecha>`. El test de CHANGELOG comprueba
   que la sección `[0.35.0]` nombra cada `old` y `new` con `introduced=0.35.0`.
4. La versión de retirada es la que deriva el código (`introduced` + 3 menores = 0.38.0). El aviso
   del CLI y el check la imprimen, y el CHANGELOG la escribe en la misma frase.

### 3.3 Mecánica del PR de release (la lleva la sesión principal)

- La rama de release sale de `main` con todas las olas de la versión mezcladas.
- Se ejecutan `bump_version.py`, `bump_version.py --check` y `scripts/release.py` con sus
  comprobaciones.
- La sesión principal revisa el diff de CHANGELOG, README y `docs/wiki/`.
- Commit firmado. `gh pr checks <n>` en verde en **todo**: CI de los tres sistemas, CodeQL, Socket,
  GitGuardian, `vendor-audit` y wiki. Los hilos de CodeQL se resuelven por GraphQL.
- Después de publicar, se pasa Socket `depscore` sobre `local-delegate` y se compara con la
  0.34.0. Se instala la versión publicada en esta PC (`uv tool install --force --reinstall
  --no-cache ".[llamaswap]"` o desde PyPI), se reinicia el daemon y se avisa de que la Mac se
  actualiza a mano.

---

## 4. Estrategia de verificación (alimenta `verification.md`)

### 4.1 Por requisito

| REQ | Comando o test | Evidencia |
| --- | --- | --- |
| 001 | `tests/test_cli*.py::…alias…`; `local-delegate --help` y `recalcular-coste --help` | `evidence/A1/help.txt`; log de la suite |
| 002 | tests de variable vieja, nueva y las dos, en el paquete y en un hook como subproceso; guardián de aislamiento | log; control positivo en `waves/A1.md` |
| 003 | tests del check (shell y `settings.json`), de `local_status` y de la cola de telemetría; `test_wiki` | log; `doctor` en vivo con `LD_HOOK_READ_BLOQUEAR` en `settings.json` (ventana de prueba) |
| 004 | `tests/test_deprecations.py` (horizonte y CHANGELOG) | control positivo con la versión en `introduced`+3, en `waves/A0.md` |
| 005 | tests de escritura por formato; test de la excepción con los 3 eventos; `vendor-audit` y vigilante | log; `gh pr checks` de A5c |
| 006 | un test por formato con filas viejas y nuevas; los 4 controles de siembra | log; mutantes en `waves/A2–A5*.md` |
| 007 | `tests/test_medir_enfriamiento.py` (formatos viejo, nuevo y mezclado); comando de P-4 real | `evidence/A4/p4-before.txt` y `p4-after.txt` (recuentos) |
| 008 | test con los dos nombres de fichero | log |
| 009 | test de paridad node, con su control positivo; diccionarios JS con valores viejos | log; `waves/A3.md` y `A5b.md` |
| 010 | test de claves y marcadores; diff del CHANGELOG 0.36.0 | log; PR de release 0.36.0 |
| 011 | `doctor --json`, `test_checks` (grupos) y recuento de 25 | log |
| 012 | `install` sobre una 0.34.0 simulada (`tmp_path` como `HOME`); `install` real en vivo | log; `evidence/A6/install-live.txt` (lista de ficheros, sin rutas privadas) |
| 013 | test de retirada de skills con una skill ajena intacta | log |
| 014 | registro por script en cada ola de `src/`; control con `test_reason` | `waves/*.md` §Scripts; `waves/A5a.md` |
| 015 | `pytest --collect-only -q` antes de A0 y al final | `evidence/A0/collect.txt` y `evidence/A-close/collect.txt` |
| 016 | `python scripts/detect_spanish_names.py --json` al cerrar A y al cerrar el cambio | `evidence/A-close/detector.json` y `evidence/close/detector.json` |
| 017 | suite completa; pasada en vivo de las 11 tools en una ventana de prueba con la 0.35.0 candidata y con la 0.36.0 candidata | `evidence/live-035/tools.md` y `evidence/live-036/tools.md`, con los ids de ventana |
| 018 | `tests/test_language.py` (9 casos + implementación única) | log; mutante en `waves/B0a.md` |
| 019 | tests de la gramática y del aviso; `doctor` y `local_status` | log; salida en vivo |
| 020 | Playwright: selector, persistencia, valor inicial y dos visitantes | log de Playwright |
| 021 | `test_cli_english.py` (`--help` es/en sin mezcla) | log; `evidence/B1/help-es.txt` y `help-en.txt` |
| 022 | `test_doctor_english.py` | log |
| 023 | tests de errores, avisos, recibos y `local_status` en inglés | log |
| 024 | hook instalado en inglés y ASCII; guardián de no importar el paquete | log |
| 025 | Playwright: control del catálogo sobre el DOM en inglés, con su control positivo | log; capturas en `evidence/B4/` (claro y oscuro, es y en) |
| 026 | tests de formato por superficie e idioma | log |
| 027 | test de descripciones constantes; resumen del panel desde el catálogo | log |
| 028 | tests de prompt; `commit_msg` sin cambios; muestra en vivo de D10 | `evidence/B2/lang-sample.json` con el id de ventana y el porcentaje por tool e idioma |
| 029 | tests de bloque, subagentes y paridad de la skill | log |
| 030 | revisión del plan (D5) + paridad que cubre `HOOK_TEXTS` | log |
| 031 | `test_i18n_parity.py` con su control positivo | log |
| 032 | guardianes del panel parametrizados; `test_wiki` | log |
| 033 | test de prosa vieja tal cual; `marks` como valor de máquina | log |
| 034 | un test de humo en inglés por superficie (B1–B5) | log |
| 035 | orden de mezcla de los PR (`git log --first-parent main`) | lista en `verification.md` |
| 036 | `waves/<ola>.md` con los mínimos de la sección 2.1 | revisión del gate `conformance` |
| 037 | tablas PyCharm de `waves/<ola>.md` | revisión del gate `conformance` |
| 038 | ids de las ventanas de prueba | `verification.md` |
| 039 | todas las corridas pesadas con `pesado.sh` | línea de comando en cada `waves/<ola>.md` |
| 040 | diff de CHANGELOG, README y wiki en los PR de release 0.35.0 y 0.36.0 | enlaces a los PR |
| 041 | fichero de fronteras; test de hash actual; test de dos máquinas (`usage` y telemetría) | log |
| 042 | comparación de EOL sobre todo el diff, con los renombres seguidos (regla 6) | `evidence/<ola>/eol-check.txt` |
| 043 | doble corrida es/en; controles sin el fixture de variable, sin el de `locale` y con un `language.json` falso | `evidence/B0a/pytest-en.log` y `pytest-es.log`; CI (ubuntu, `LANG=C.UTF-8`) |
| 044 | tests del detector; auditoría del léxico | `evidence/A0/lexicon-audit.csv` (semilla y error) |
| 045 | guardián con la lista de pendientes vacía al cerrar B; test de excepciones | log; `tests/data/uncatalogued_pending/*.json` vacíos |
| 046 | comando de P-4 documentado, ejecutado tras A4 y tras A10a | `evidence/A4/` y `evidence/A10a/p4-command.txt`; notas fechadas y entrada del backlog |
| 047 | tests de escritura con origen y de `uninstall`; en vivo, `doctor` y `local_status` con el mismo idioma, origen «preferencia» y ruta | log; `evidence/B5/lang-live.txt` |

### 4.2 Doble corrida de la suite con `LANG` en inglés y en español (REQ-043)

- **En esta PC (Windows):** `LANG=en_US.UTF-8 bash ~/.claude/scripts/pesado.sh uv run pytest -q`, y
  después lo mismo con `es_ES.UTF-8`. **Limitación:** en Windows, REQ-018 no consulta `LANG`, así
  que esta corrida **no discrimina**. Prueba lo que tiene que probar (que la suite no depende de
  `LANG`) solo a medias.
- **Corrida que sí discrimina:** en Linux. La da el CI de ubuntu (`LANG=C.UTF-8`, el escenario «CI
  en inglés»). No hay workflow aparte: los dos trabajos nuevos van en **`ci.yml`**, que corre en
  todos los PR, **sin filtro `paths`**, y entran en los trabajos esperados de `scripts/ci_gate.py`.
  El ruleset ya exige `ci-gate`, así que bloquean la mezcla sin tocar el ruleset.
  - **`test-lang-es`** (lo añade B0): la suite **entera**, una sola vez, en ubuntu, con Python 3.11
    y `LANG=es_ES.UTF-8`. Es el coste grande y no se multiplica.
  - **`cli-python-matrix`** (lo añade B1, con su test): **solo los tests del CLI**
    (`test_cli_english.py` y los de `--help`), sin Playwright, con una matriz de todas las versiones
    de Python que admite el paquete. Son pocos tests por celda, así que es barato aunque la matriz
    crezca. Cada celda figura en los trabajos esperados, con un test de coherencia. La versión más
    nueva sin wheels sigue la política de D8: lista de exclusión en `ci_gate.py`, sin
    `continue-on-error` a nivel de trabajo.

  Cada trabajo nace en la misma ola que el test que ejecuta, y ninguno consume tests de una ola
  posterior. Además, localmente se corre en WSL, con `bash` de WSL desde PowerShell, bajo el
  cerrojo.
- **Controles positivos de REQ-043** (sin el fixture de la variable, sin el de `locale`, y con un
  `language.json` falso): en WSL o en una rama de CI marcada como de control, nunca en `main`.

### 4.3 Pruebas en vivo

- **Antes de cada prueba en vivo:**
  `uv tool install --force --reinstall --no-cache ".[llamaswap]"` desde la rama candidata, bajo el
  cerrojo; reinicio del daemon (`schtasks /Run` de la tarea, según la memoria del proyecto); `/mcp`
  para comprobar que el MCP volvió antes de lanzar agentes, porque un subagente lanzado con el MCP
  caído no lo recupera.
- **Siempre** entre `local-delegate test-window start --label "<SDD english-names, ola X, …>"` y
  `local-delegate test-window stop <id>`, con el id anotado en `verification.md`.
- **Pasadas:**
  - 0.35.0 candidata: las 11 tools, `doctor`, `install` real, panel y comando de P-4;
  - 0.36.0 candidata: las 11 tools en `en` y en `es` (cambiando `language.json` con `install`),
    muestra D10, `doctor` y `local_status` (REQ-047) y panel con dos navegadores.
- La credencial del backend la pone el daemon. **No se le pide al usuario.**
- Al terminar, se deja instalada la última versión en esta PC (regla del entorno local).

### 4.4 Comandos pesados

Todo con `bash ~/.claude/scripts/pesado.sh`: pytest (completo o de un fichero), Playwright, node de
paridad, `uv tool install`, `uv sync`, build y capturas. Nunca dos a la vez en toda la máquina.
`jest` no aplica en este repo. Si se usa xdist con pytest, `-n 2` como máximo.

---

## 5. Riesgos y mitigación

| Riesgo | Mitigación |
| --- | --- |
| **PyCharm cambia cadenas o comentarios** que deben conservar el nombre viejo (tablas de `legacy_names.py`, alias, fixtures de formato viejo, prompts) | Las tablas de equivalencias guardan los nombres viejos como **cadenas**, que PyCharm no toca, nunca como identificadores. En cada ola, revisión de `git diff -U0` y `search_text` de los nombres viejos después del rename: tienen que quedar justo los de la lista de excepciones. Los tests de lectura dual con filas viejas fallan si se tocó una tabla. |
| **PyCharm no renombra módulos o no responde** | `git mv` + `search_regex` de los imports + edición. Se anota en `waves/<ola>.md`. Por cada script, `get_file_problems` (REQ-014). |
| **LF/CRLF** (`server.py`, `cli.py`, `install.py`, `web/metrics.py`, `test_dashboard_ui.py`…) | comparación de EOL sobre todo el diff, siguiendo los renombres (regla 6); scripts con `newline=""`; nunca `write_text`; detección con `git ls-files --eol`, nunca con `grep -c $'\r$'`. |
| **La Mac con el formato viejo** escribe `usage`, telemetría y `enfriamiento-eventos` en español durante meses | Lectura dual para siempre (REQ-006); escenario de la Mac como test con los ficheros mezclados; la frontera por versión y hash (REQ-041) evita que sus filas caigan en el tramo equivocado. La Mac la actualiza el usuario: tras la 0.35.0 se le recuerda que `update` repone los hooks. |
| **P-4 abierta** hasta ~2026-12-14 | `medir_enfriamiento.py` lee los dos formatos desde A3 (valores) y A4 (ficheros), en el mismo PR que los cambia. El comando documentado se ejecuta y se guarda en A3, A4 y A10a; el envoltorio de REQ-046 vive hasta cerrar P-4 y su retirada queda en el backlog. Recordatorio para el informe: lo esperable de P-4 es «no concluyente». |
| **Hooks nuevos con daemon viejo** (y al revés) | Los hooks nuevos leen los dos ficheros de enfriamiento; el daemon nuevo escribe los dos (excepción) y lee los temporales con los dos nombres; `update` reinicia el daemon. |
| **CodeQL** (ciclos de import aunque sean diferidos, `ctypes`, parche de argparse, cookie) | `i18n.py` solo importa stdlib, `config` (para `config.LOG_DIR`) y `hook_common`, y `config` no importa `i18n`; `legacy_names.py` y `deprecations.py` no importan nada del paquete. Los avisos se arreglan, no se descartan. Se mira `gh pr checks`, no `gh run list`. |
| **Ola A5 demasiado grande para revisar** | Partición prevista (A5a/b/c, y A5b-1/A5b-2 si pasa de 2 500 referencias). |
| **Traducciones de `local_translate` que rompen `{}` o identificadores** (225 cadenas con identificadores embebidos) | Revisión humana de cada lote, más el guardián de paridad de REQ-031 (marcadores e identificadores entre comillas invertidas iguales). |
| **El guardián de REQ-045 se esquiva clasificando de menos** | La lista de contextos se declara en el guardián, cada excepción lleva su motivo y un test de que ninguna excepción contiene prosa. |
| **Una traducción alarga una etiqueta del panel** hasta 6 palabras o más | Guardianes de «sin prosa» parametrizados por idioma; capturas en claro y oscuro (regla del panel-dashboard). |
| **El argparse de otra versión de Python** cambia los msgid (el paquete admite cualquier versión desde la 3.11) | `test_argparse_msgids_covered` saca los msgid del argparse en ejecución; el trabajo `cli-python-matrix` de `ci.yml`, vigilado por `ci-gate`, lo corre en todas las versiones admitidas; un msgid que falte cae al inglés (D8). |
| **Un Python recién publicado sin wheels** pone en rojo la matriz | Esa versión va a la lista de exclusión `PYTHON_WITHOUT_WHEELS` de `ci_gate.py` (su celda corre pero no bloquea), con fecha y motivo, solo si falla la instalación y no un test, y sale de la lista en cuanto la instalación funciona (D8). |
| **Un bloque bilingüe o en CRLF da aviso perpetuo** o `update` lo reescribe en cada pasada | Comparación normalizada contra los bloques de cualquier idioma, sacados de `packaged_memory_blocks()`; tests de CRLF y de segunda pasada en A6, y del bloque inglés en B5 (D12). |
| **`update` deja bloques que nombran una skill retirada** | D12 en A6: `scaffold.memory` en `WARN` si el bloque está desfasado, `update` lo repara y regenera los catálogos de los subagentes ya marcados, y hay un test de `update` sobre una 0.34.0 simulada. |
| **Nombres en inglés malos o inconsistentes** aplicados en masa | Mapping revisado y aprobado por la sesión principal antes de renombrar; lotes de ≤ 300 (D13). |
| **Socket**: dependencias de desarrollo nuevas (`wordfreq`) | Fuera del repo con `uv run --with ==<versión>`, después de `depscore` ≥ 0,7; ningún dato suyo se versiona. Tras cada release, `depscore` del paquete propio. |
| **Medición de adopción**: las descripciones en inglés y los prompts cambian lo medido | Frontera por versión en `measurement_boundaries.json` (REQ-041) e informe por tramos en `measure_adoption.py`. |
| **El PR automático del vigilante de precios** abierto con el formato viejo | Se cierra antes de mezclar A5c, y el siguiente lo genera el workflow renombrado. |
| **Un subagente lanzado con el MCP `local-delegate` caído** no lo recupera | Tras cada reinstalación, `/mcp` antes de lanzar agentes; si falla, el agente sigue sin `local_*` y lo dice. |
| **Datos privados en `evidence/`** | Solo recuentos, sin rutas absolutas. La sesión principal junta la rama y la revisa antes del push. |

---

## 6. Matriz REQ → ola → evidencia

| REQ | Ola(s) | Evidencia principal |
| --- | --- | --- |
| 001 | A1 | test del alias; `help.txt` |
| 002 | A1 (+A2 hooks) | tests de paquete y hook; guardián de aislamiento |
| 003 | A0, A1, A2 | tests del check, `local_status` y cola; `test_wiki` |
| 004 | A0 (+ cada release) | `test_deprecations.py`; diff de `bump_version` |
| 005 | A2, A3, A4, A5a, A5b, A5c | tests de escritura; excepción de enfriamiento |
| 006 | A2, A3, A4, A5a, A5b | tests mezclados y de siembra con mutantes |
| 007 | A3 (valores), A4 | test de P-4; corrida real antes y después |
| 008 | A5b | test de los dos nombres |
| 009 | A2, A3, A5b, A8b | paridad node con control positivo |
| 010 | B2b | test del contrato; CHANGELOG 0.36.0 |
| 011 | A6 | `doctor --json`; grupos; 25 checks |
| 012 | A2, A6 (incluye D12, `update`) (+B5 subagentes) | `install` y `update` sobre una 0.34.0 simulada; `install` en vivo |
| 013 | A0 (+A6 la usa) | test de retirada de skills |
| 014 | A3, A4, A5a–c, A6, A8a (toda ola de `src/`) | registro por script; control con `test_reason` |
| 015 | A7a–A10b | recuento de tests recogidos |
| 016 | A0 (detector), cierre de A (A10b), cierre del cambio (B5) | dos corridas del detector |
| 017 | todas las de A | suite; pasadas en vivo de las 11 tools |
| 018 | B0 | `test_language.py` |
| 019 | B0, B1 (`doctor`), B2a (`local_status`) | tests de gramática; salidas en vivo |
| 020 | B4 | Playwright del selector |
| 021 | B1 (CLI y `--help`), B5 (`install`, `update`, `uninstall`) | `--help` es/en; msgid de argparse en todas las versiones de Python; humo de `install` en inglés |
| 022 | B1 | `doctor` es/en |
| 023 | B2a | salidas MCP en inglés |
| 024 | B3 | hook instalado en inglés |
| 025 | B4 | control de catálogo sobre el DOM |
| 026 | B1, B2a, B4 | formatos por superficie |
| 027 | B2b (+B4 resumen del panel) | descripciones constantes |
| 028 | B2b | tests de prompt; muestra D10 |
| 029 | B5 | bloque, subagentes y paridad de la skill |
| 030 | B0 | D5; paridad con `HOOK_TEXTS` |
| 031 | B0 | `test_i18n_parity.py` |
| 032 | B1 (wiki), B4 (panel) | guardianes parametrizados |
| 033 | A5b (`marks`), B2a, B4 | prosa vieja tal cual |
| 034 | B1, B2a, B3, B4, B5 | humo en inglés por superficie |
| 035 | todas (orden de la sección 1.3/1.4) | `git log --first-parent` |
| 036 | todas | `waves/<ola>.md` (sección 2) |
| 037 | todas las de implementación | tablas PyCharm |
| 038 | verificación en vivo (0.35.0 y 0.36.0) | ids de ventana |
| 039 | todas | `pesado.sh` en los registros |
| 040 | releases 0.35.0 y 0.36.0 (+B5 wiki del idioma) | diff de docs en los PR de release |
| 041 | B2b (fronteras por `v`, descripciones y prompts), B3 (hashes y script), cada release | fichero de fronteras; tests |
| 042 | todas | `eol-check.txt` sobre todo el diff, con los renombres seguidos |
| 043 | B0 (fixtures, incluido el de `locale`; B4 lo usa) | doble corrida; trabajo `test-lang-es` de `ci.yml`, vigilado por `ci-gate`; controles |
| 044 | A0 | detector, léxico y auditoría |
| 045 | B0b (nace) → B1–B5 (se vacía) | lista de pendientes vacía |
| 046 | A4, A10a | comando de P-4; nota fechada; backlog |
| 047 | B0 (lectura), B5 (escritura) | tests con origen; en vivo |

Son 47 de 47.

---

## 7. Lo que la spec dejó «para el plan», resuelto uno a uno

1. **Cómo llegan al panel los textos que redacta el servidor (REQ-025).** Con `?lang=` en
   `/api/*` y redacción en el servidor (D6).
2. **Mecanismo del catálogo (REQ-030, i18n §5).** Opción B: catálogo JSON por claves, con
   `HOOK_TEXTS` dentro de `hook_common` cubierto por la misma paridad (D5).
3. **Detector y conjunto de documentos de la muestra de REQ-028, antes de B2.** Están fijados en
   D10; el detector nace en B0 para tener su control antes.
4. **Scripts de medición de calidad que comparan periodos (REQ-041).** Solo `medir_adopcion.py`
   (`measure_adoption.py` tras A10a); los demás quedan descartados con su motivo (D9).
5. **Olas del frente B (traceability: «las fija el plan»).** B0–B5, con B2 partida en B2a y B2b
   (sección 1.4).
6. **Versión de retirada de los alias (REQ-004: «la fija el PR de release»).** Centinela
   `UNRELEASED` y `bump_version.py` (sección 3.2): 0.35.0 → retirada en 0.38.0.
7. **Cómo volver a «seguir al sistema»** (menor de la verificación final de `review.md`). Se borra
   `language.json` desde la ruta que muestra `doctor` y se ejecuta `install`: remedio en `doctor`,
   wiki y CHANGELOG, más un test (D11).
8. **Nombres no fijados por la spec** (módulos, valores de enumeración, claves de caché): tablas
   D3 y D4, marcadas **(plan)**.
9. **Dónde viven los textos de los hooks.** En `HOOK_TEXTS` dentro de `hook_common.py` (D5); no hay
   fichero nuevo que copiar, en coherencia con REQ-018.
10. **Armazón de argparse (REQ-021).** Parche de `argparse._`/`ngettext` en el proceso del CLI,
    con los msgid sacados del argparse en ejecución y CI en todas las versiones de Python (D8).
11. **Cuándo se mezcla B respecto de A (REQ-035).** Tras A10b, todas. B0 se desarrolla antes y se
    rebasa. Orden: B0a → B0b → B1 → B2 → (B3 ∥ B4) → B5 (sección 1.4).

---

## 8. Desviaciones propuestas

Ninguna que reabra la spec. Hay dos precisiones de ejecución, dichas aquí para que el gate las vea:

- **REQ-043, doble corrida con `LANG`.** En Windows no discrimina, porque REQ-018 ignora `LANG` en
  Windows. Por eso la evidencia que discrimina sale de Linux (CI de ubuntu, más un paso nuevo con
  `es_ES.UTF-8`, y WSL en local). No cambia el requisito: lo hace ejecutable donde puede fallar.
- **REQ-006, lista de lectores.** Se revisó `scripts/measure_slowness.py`, que no estaba en la
  lista: lee `usage-*`, pero ninguna clave ni valor en español (`search_regex` sin coincidencias).
  No necesita lectura dual. Queda escrito para que no parezca un olvido.
- **REQ-041, filas sin versión (`v`).** Ya no es una desviación: la spec lo incorporó en la
  enmienda del 2026-10-12 (`spec.md:562-563`). Una fila sin versión cuenta siempre como «antes».
  El plan lo aplica en D9, con test y control positivo, y no hay fecha de reserva.
- **REQ-041 y REQ-043, reparto entre olas.** La traceability de la spec ponía `package_version` en
  B0 y el fixture de `locale` de Playwright en B4. Con la propiedad exclusiva del frente B, pasan a
  B2 (la dueña de `server.py`) y a B0 (la dueña de `conftest.py`). Las dos salen en la 0.36.0, así
  que no cambia lo que se publica ni la frontera.
