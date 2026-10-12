# Investigación del frente B: salidas en español e inglés

Mapa de impacto para que todo texto de salida para personas exista en español e inglés. Solo
evidencia y opciones; la spec decide. Medido el 2026-10-12 sobre `main` (`8ec2f1d`, 0.34.0).

Listado completo, fila a fila, en `evidence/i18n-inventory.csv` (3 066 filas: capa, superficie,
contexto, `fichero`, `línea`, si interpola, si el detector lo marcó como español, texto).

## Cómo se midió (y sus límites)

- **Python**: recorrido con `ast` de los 41 módulos del paquete (`src/local_delegate/**.py`, sin
  `__pycache__`). Cada literal `str` o f-string se clasifica por contexto sintáctico (docstring,
  docstring de tool MCP, `help=` de argparse, `print`, excepción, `return`, prompt al modelo,
  otro) y por un detector de «texto humano en español» (tildes, `¿¡«»`, o ≥2 palabras con alguna
  de un vocabulario español).
- **Panel**: el literal `HTML` de `web/metrics.py:1072-2946` se parte en marcado y `<script>`. El
  marcado con expresiones regulares; el JS con un tokenizador real (`esprima` 4.0.1, solo en el
  scratchpad con `uv run --with`, sin tocar el proyecto), porque un escáner por regex se
  rompía con los literales de expresión regular del JS (``/`([^`]+)`/g``, línea 1935).
- **Tests**: `ast` de `tests/test*.py`; cuenta las expresiones de `assert` (no su mensaje) y los
  `pytest.raises(match=…)` que contienen texto en español.
- **Controles positivos** (los cuatro dieron con su objetivo): «Respaldo entre modelos»
  (`cadenas.py:167`), «sin residente» (`cadenas.py:184,187`), «[local-delegate error] no se pudo
  conectar» (`server.py:1306`), «etiqueta libre» (`cli.py:419`); en el JS, el `tip` de
  «Invocaciones a tools locales» (`metrics.py:2679`), que el escáner por regex **no** encontraba.
- **Precisión y exhaustividad del detector**: en una muestra de 35 positivos, 35 eran texto
  humano. De los 150 literales con espacios que el detector descartó, una muestra de 30 dio 7
  textos humanos («residente: {}», «{} muestras», «fecha ilegible: {}»…): faltan **~35** en
  Python. En el JS fallaba con etiquetas de una o dos palabras («Latencia», «llamadas»,
  «Cargando»): se revisaron a mano las 330 cadenas únicas no detectadas y se sumaron 91 únicas
  (124 apariciones).

## 1. Inventario por superficie

Cifras de literales con texto humano en español **sin contar docstrings internos** (751
docstrings en español, que no son salida).

| Superficie | Literales | De ellos con interpolación | Dónde, representativo |
|---|---:|---:|---|
| (a) CLI: `print`, errores, `--help` | 179 (`cli.py`) + 31 (`benchmark.py`) | 47 + 10 | `cli.py:245` «{n} acción(es) fallaron.»; 102 `help=` y 3 `description=` de argparse, p. ej. `cli.py:1191`, `cli.py:419-431` |
| (b) `doctor` y `checks.py` | 173 | 99 | títulos de los 25 checks `checks.py:1784-1843`; etiquetas de estado `[ OK ] [WARN] [FALT] [ -- ]` `checks.py:48-53`; remedios `checks.py:55-61`; cabeceras de grupo `doctor.py:24-34`; «arréglalo con:» `doctor.py:45`; «Resultado: … aviso(s)» `doctor.py:111` |
| (c) salidas de tools MCP y `local_status` (`server.py`, `fallos.py`, `cadenas.py`) | 196 | 102 | ver detalle abajo |
| (d) descripciones de tools y parámetros | 11 docstrings de tool (8 771 caracteres) + 11 títulos de anotación + 1 descripción del servidor | — | `server.py:3428-4404` (`_anotaciones("Resumir texto o archivo")`…), `server.py:68-73` |
| (e) hooks | 7 mensajes | 4 | ver detalle abajo |
| (f) panel | ~440 | ≥15 | ver detalle abajo |
| (g) `install`, `update`, `test-window`, `recalcular-coste`, llama-swap | 49 + 48 + 15 + 7 + 102 | 22 + 24 + 11 + 6 + 65 | `install.py:1009` «{} hook(s) registrados»; `update.py:796`; `test_windows.py:56` «fecha ilegible»; `residency.py`/`llamaswap_*` (47 son mensajes de excepción que acaban en consola) |
| Otros módulos que acaban en salida | 37 `topology.py`, 15 `sondas.py`, 10 `cuota.py`, ~25 sueltos | — | `topology.py:471` «el router `matrix` no se reparte por grupos» |
| **Total Python (sin docstrings)** | **902 detectados + ~35 no detectados ≈ 940** | 431 f-string / 471 literales | |

Total aproximado de cadenas de salida: **~940 en Python + ~440 en el panel ≈ 1 380**, más las 11
descripciones de tool. La estimación del brief (~1 100) se queda corta.

**Plurales**: 27 apariciones del patrón «palabra(s)/(es)» (`cli.py:245`, `checks.py:1700`,
`checks.py:1772`, `install.py:1009`); 8 condicionales `== 1 else` en Python
(`server.py:4344` «1 vez seguida» / «{n} veces seguidas»); un helper `_plural` en
`llamaswap_api.py:396`; 6 ternarios `===1?` en el JS (`metrics.py:2678` «llamada»/«llamadas»).
Español e inglés tienen las dos mismas formas (uno / otros): no hace falta motor de plurales.

### (c) Lo que ve el modelo cliente en las respuestas de las tools

El texto de la respuesta lo lee **el modelo** (Claude, Codex, opencode) y a veces el usuario en
el transcript. Capas:

- **Errores** con el prefijo fijo `[local-delegate error]`: 17 sitios (`server.py:1058`, `1113`,
  `1122`, `1306`, `1317`, `1329`, `1337`, `1344`, `2023`…). El **prefijo es contrato** (lo
  comprueban `server.py:3929` y 10+ tests, y lo nombran el `CLAUDE.md` del usuario y la skill):
  se queda tal cual; solo se traduce lo que va detrás.
- **Avisos y recibos añadidos al resultado**: «(leído server-side: N chars ≈ M tokens de Claude
  que no entraron a tu contexto)» `server.py:2344-2347`; «[local-delegate aviso: salida truncada
  por max_tokens…]» `server.py:3103`; «(procesado en N trozos…)» `server.py:2793`; «(resumido de
  N partes…)» `server.py:3134`; «[local-delegate aviso: N secciones sin resumir…]»
  `secciones.py:271`; el recibo de `local_boilerplate` `server.py:439-442`; aviso de truncado de
  entrada «[local-delegate: entrada truncada — procesados …]»; y en `local_extract` la clave
  reservada `_local_delegate` con `"error": "respuesta no parseable como JSON"`
  (`server.py:3612-3614`: la clave es frente A; el valor, frente B).
- **`local_status`**: ~32 cadenas en `server.py:4090-4560` más `cadenas.describir()`
  (`cadenas.py:161-188`) y las etiquetas de causa de `fallos.py:322-336`. Lo lee sobre todo el
  modelo para diagnosticar, y la persona cuando lo pide.
- **Formato de números**: Python usa `:,` → «20,027» (agrupación inglesa) dentro de frases en
  español (`server.py:439`, `2344`, `3931`), mientras el panel usa punto de miles
  (`metrics.py:1655-1663`). Hoy ya son incoherentes entre sí.

### (d) Descripciones de tools y parámetros: ¿entran?

Las ven los modelos en `tools/list`, nunca una persona en una pantalla propia del producto…
salvo una excepción medida: **el panel muestra la primera línea de cada docstring** como tooltip
de su chip (`metrics.py:856` `summary`, pintado en `metrics.py:2380`). Además el servidor declara
`description` en `server.py:68-73` y 11 títulos de anotación (los muestran algunos clientes en
su UI, p. ej. el diálogo de permisos).

| | A favor de traducirlas | En contra |
|---|---|---|
| Comprensión | Un modelo entiende ambas; el usuario anglófono que inspecciona `/mcp` ve inglés | Ninguna ganancia para el modelo |
| Adopción medida | — | La obediencia del modelo a estos textos se ha medido y afinado **en español** (REQ-102, «PREFIERE esta tool…»); cambiar el texto invalida esas mediciones |
| Mecánica | Un idioma por proceso es fácil (se fijan al importar `server`) | El **daemon HTTP es uno para varios clientes** (Mac y PC): un solo idioma por daemon; y el cliente cachea el esquema de la sesión |
| Coste | 11 docstrings, ~8,8 k caracteres | Tests de `test_wiki.py:286` y del catálogo de la skill leen esos textos |

Opción intermedia: docstrings en **inglés únicamente** (son «texto de máquina» para un modelo,
como los nombres) y solo el `summary` del panel pasa por el catálogo. Es una decisión de
producto (ver preguntas abiertas).

### (e) Hooks

Canales (`hook_common.py`, confirmado por lectura y por `local_explain_code`):
`additionalContext` (`hook_common.py:118-120`, lo ve **el modelo**) y `permissionDecision` +
`permissionDecisionReason` (`hook_common.py:147-150`, lo ven **el modelo y el usuario** en la UI
de permisos). Mensajes: `suggest_delegate_prompt.py:73`, `suggest_delegate_read.py:301`,
`312-320`, `suggest_delegate_shell.py:179`. Están **en ASCII sin tildes a propósito**
(«Pasalo», «Recomendacion»). Detalle importante: los hooks son scripts sueltos copiados a
`~/.claude/hooks/` que **no importan el paquete**: un catálogo dentro del paquete no les llega;
o se copia con ellos o el texto vive en `hook_common.py`.

Las expresiones de `suggest_delegate_prompt.py:13-24` ya detectan intención en los dos idiomas
(`resum|summarize`, `traduc|translate`): no son salida, no cambian.

### (f) Panel

| Pieza | Cuenta | Dónde |
|---|---:|---|
| Texto entre etiquetas del HTML | 89 nodos (62 frases + etiquetas cortas «Hoy», «Pruebas», «Sistema») | `metrics.py:1072-1650` |
| Atributos visibles (`title`, `aria-label`, `content`) | 30 | «Desde», «Hasta», «Refrescar», «Tema claro / oscuro», «Cerrar» |
| Cadenas del JS | 215 detectadas + 124 cortas ≈ **339** (10 plantillas con `${}`) | `tip:`/`hint:`/`lbl:` de los KPI `metrics.py:2672-2690`, `innerHTML`, `push(` de filas, mapas de motivo de hook (`mcp_ajeno`, `no_es_prosa`, `bloqueo_apagado`…) |
| `<html lang="es">`, `<title>`, `<meta description>` | 3 | `metrics.py:1073-1078` |
| Formatos | `fmtNum` propio (punto de miles, coma decimal) `metrics.py:1655-1670`; `Chart.defaults.locale='de-DE'` `metrics.py:1716`; `Intl.DateTimeFormat('es',…)` `metrics.py:1756` | |
| **Textos que llegan ya redactados del servidor** | etiquetas de causa (`fallos.etiqueta`, `metrics.py:774-780`), `detalle` de `fallos.detalle()` (`metrics.py:822-828`), etiquetas de rol «mecánico/largo/código/visión» (`metrics.py:848-851`), `reason` de hooks (`metrics.py:684`), `summary` de tools (`metrics.py:856`) | el JS «no redacta los textos de una causa» (REQ-011): el idioma tiene que viajar **al servidor** o el servidor tiene que mandar claves |
| **Texto persistido** | `motivo` del respaldo en `usage-*.jsonl` (`server.py:1085`: es el texto del error); la `label` libre de `test-windows.json` | lo ya escrito queda en español; no se puede retraducir, solo mostrar tal cual |

### (h) Capa aparte: prompts al modelo local

Los prompts de sistema están en español (`_guard`, `server.py:3201-3205`, y sus 12 llamadores
`server.py:3479-4068`; `_lint_system`; reduce del map-reduce `server.py:2964`; secciones
`server.py:3305-3316`). **No piden idioma de respuesta**, salvo `local_commit_msg`
(`LOCAL_DELEGATE_COMMIT_LANGUAGE`, `server.py:3169-3196`, medido: sin orden el 26B escribía
17/30 en inglés) y `local_translate` (`target_lang`). El idioma de lo que genera el modelo local
lo decide la entrada, no la interfaz. Esto **no es frente B** (no es texto de la interfaz), pero
si la spec quiere «salidas en inglés» de verdad para un usuario anglófono, `local_summarize` y
compañía seguirán resumiendo en el idioma del documento. Cambiar los prompts afecta a calidad
medida (afinidad, F2): fuera de alcance salvo decisión expresa.

### Otras superficies que escriben texto en ficheros del usuario

- Bloque gestionado de memoria `resources/memory/local-delegate.md` (lo escribe `install` en el
  `CLAUDE.md`/`AGENTS.md` del usuario) y la skill `resources/skills/delegacion-local/SKILL.md`
  (90 líneas): prosa en español para el modelo.
- **Trampa**: `agents.py:41` detecta la cabecera del bloque con
  `^#{1,3}\s*Delegaci[oó]n a modelos locales`; y `agents.py:44` lee el catálogo de la tabla de la
  skill. Traducir el bloque o la skill rompe esa detección y deja dos bloques en el fichero.

## 2. Cómo están hoy las cadenas

- **No hay ningún mecanismo de i18n** en el paquete: cero `gettext`, cero catálogos, cero
  `Accept-Language` (búsqueda de `gettext|i18n|locale|Accept-Language|navigator.language|LANG`
  sobre `src/`; el detector sí encontraba `Intl.` y `lang="es"`, así que podía dar positivos).
- **`cadenas.py` no es un módulo de cadenas de texto**: son las *cadenas de respaldo* entre
  modelos (`code -> loaded -> long`). El nombre confunde; es frente A si se quiere.
- Los textos están **dispersos en f-strings** junto a la lógica: 431 con interpolación, 471
  literales. Muchos se arman por trozos (`checks.py:1773` «{} ventanas, {}»; `server.py:4474-4478`
  concatenaciones condicionales), lo que obliga a reescribir la frase entera, no solo a envolverla.
- **argparse ya usa gettext** (dominio `argparse`): «usage:», «options:», «show this help message
  and exit» salen hoy **en inglés** mezclados con la ayuda en español. Es el único texto del CLI que
  ya está en inglés.
- **Precedente en el repo**: `site/index.html` ya es bilingüe en cliente: diccionarios `T.es` /
  `T.en`, ranuras `data-t` (51), botones ES/EN (`site/index.html:407-409`), `localStorage`
  `ld-lang`, idioma inicial = guardado o `navigator.language` que empiece por `en`
  (`site/index.html:704-709`), y un guardián de paridad de claves (`tests/test_site.py:109`).
- Consola de Windows: `checks._cp1252` (`checks.py:530`) sanea texto ajeno; los hooks evitan
  tildes. El inglés no empeora esto.

## 3. Tests que afirman texto en español

- **567** expresiones de aserción con texto en español (540 `assert` + 27 `pytest.raises(match=)`)
  en **66 de 92** ficheros. Otros 385 asserts solo tienen en español su *mensaje*, que no cuenta.
- Más cargados: `test_resumen_estructurado.py` 44, `test_checks.py` 42, `test_corpus.py` 28,
  `test_panel_coste.py` 27, `test_analisis_benchmark.py` 26, `test_hoja_pares.py` 24,
  `test_panel_estados.py` 24, `test_residency.py` 23, `test_residency_cli.py` 23,
  `test_dashboard_ui.py` 21 (Playwright), `test_core.py` 20, `test_cadenas.py` 13.
- Una parte no es salida del producto (corpus y hojas de benchmark: `test_corpus`, `test_hoja_pares`,
  `test_analisis_benchmark`, `test_medir_enfriamiento` ≈ 90) y otra son prompts al modelo local
  (`test_resumen_estructurado`, que afirma el texto del prompt): **~450 afectan al frente B**.
- **Guardianes del panel que dependen de la longitud del texto**: `test_dashboard_ui.py:581-582`
  («sin prosa»: ninguna etiqueta de ≥6 palabras) y `test_dashboard_ui.py:641-660` (`masLargo`,
  sin párrafos). Tipografía: `test_dashboard_ui.py:469`, `1012`, `test_metrics.py:641`. Habría que
  correrlos **en los dos idiomas**: el inglés suele ser más corto, pero una traducción puede pasar
  de 5 a 6 palabras.
- **Wiki**: `test_wiki.py:219-236` compara los títulos de `checks.CHECKS` con la tabla de la wiki
  (en español), y `test_wiki.py:239` busca «las {n} piezas». Si el título pasa a ser una clave
  del catálogo, el test tiene que comparar contra el título **en español** del catálogo.
- Qué implica: si el idioma por defecto sigue siendo español y el catálogo devuelve el mismo
  texto, los ~450 asserts siguen valiendo sin tocarse (afirman el texto en español, que no
  cambia). Pasarlos a «afirmar la clave» los haría inmunes a la redacción pero ciegos a una
  traducción vacía o rota; lo barato es dejarlos y **añadir** un guardián de paridad de claves y
  un puñado de tests en inglés por superficie.

## 4. Cómo se elegiría el idioma, superficie a superficie

| Superficie | Proceso que imprime | Qué existe hoy | Vía posible | Trampa |
|---|---|---|---|---|
| CLI (`doctor`, `install`, `update`…) | el del usuario | nada | variable (p. ej. `LOCAL_DELEGATE_LANG=es\|en`) → si no, locale del sistema (`LANG`/`LC_ALL`/`LC_MESSAGES` en POSIX; `locale.getlocale()` en Windows da `('Spanish_Spain', '1252')`, hay que mapearlo) → si no, defecto | Una opción global `--lang` no traduce comandos, es compatible con la regla |
| MCP por stdio | el que lanza el cliente | entradas MCP con bloque `env` que escribe `install` (`install.py:481`) | la misma variable en `env` de la entrada | cuatro clientes con cuatro formatos de config; Claude Desktop no lo toca el instalador |
| MCP por HTTP (daemon) | el daemon, lanzado por tarea programada | entorno del lanzador | variable en el lanzador | **un idioma por daemon para todos los clientes** (Mac y PC comparten backend); MCP `initialize` trae `clientInfo` pero **no locale** |
| Hooks | Claude Code | heredan el entorno del lanzador de Claude Code (memoria «telemetría de hooks va en el lanzador») | la misma variable | sesión abierta conserva el entorno viejo; los scripts no importan el paquete |
| Panel | navegador | `<html lang="es">` fijo | selector ES/EN en la cabecera + `localStorage` (como el sitio), inicial = `navigator.language`, con el defecto del daemon inyectado en el HTML como hoy `__WEB_FONTS__` | textos que vienen del servidor (causas, roles, `reason`, `summary`): o `?lang=` en `/api/*`, o el servidor manda claves y el JS traduce. `localStorage` es por origen: el panel (127.0.0.1:9393) no comparte la elección con el sitio |

`Accept-Language` sirve solo para el primer pintado del panel y lo da igual de bien
`navigator.language`; no aporta nada al MCP ni al CLI.

**Idioma por defecto**: hoy todo sale en español. Para usuarios de PyPI desde cualquier
Windows/Linux, el defecto razonable sería el locale del sistema y, si no se reconoce, inglés;
para no romper a quien ya lo usa, español. Es decisión de producto.

## 5. Opciones de diseño del catálogo

| | A. Diccionario Python con el texto español como clave + JSON para el JS | B. Catálogo por claves en JSON compartido (`resources/i18n/es.json`, `en.json`) | C. gettext (`.po`/`.mo`) |
|---|---|---|---|
| Forma | `_("{n} acción(es) fallaron.", n=…)`; en español devuelve la fuente; en inglés busca en `en.py`/`en.json` | `t("cli.failures", n=…)`; Python con `importlib.resources`, el panel recibe el JSON servido o embebido | `_()` de stdlib, `ngettext` para plurales |
| Dependencias nuevas | ninguna | ninguna | en ejecución ninguna (stdlib); para compilar `.mo` hace falta `msgfmt` (no viene en todas las instalaciones de Python) o Babel como dependencia de desarrollo (auditar con Socket); el JS necesita aparte un conversor `.po`→JSON |
| Tests actuales | **siguen valiendo sin tocarlos** (el español no cambia) | siguen valiendo si el defecto es español | siguen valiendo (msgid = español) |
| Riesgo | cambiar una frase en español huérfana su traducción: lo detecta un guardián de «toda clave tiene `en`» | dos ficheros a mantener en paridad (guardián como `test_site.py:109`); el texto se aleja del código | herramienta extra en el release; empaquetar `.mo` en el wheel; `test_wiki`/`checks` siguen con su título |
| Ventaja propia | migración mínima: envolver, no reescribir; `grep` del texto sigue llevando al código | una sola fuente para Python y panel (como el sitio) | traduce también el chrome de argparse («usage:», «options:») con el mismo dominio; plurales nativos |
| Coste aproximado | ~940 envolturas + ~440 en el panel + escribir el inglés; ~200 frases armadas por trozos hay que reescribirlas enteras en cualquier opción | igual, más inventar ~1 380 claves | igual que A, más la cadena de compilación |

Común a las tres: el panel necesita su propio diccionario JS servido por el daemon; los hooks
necesitan su copia (no importan el paquete); argparse se traduce aparte (en A y B, con
`gettext.translation` del dominio `argparse` o reescribiendo `usage`/`options` con
`formatter_class`); y los formatos de número/fecha por idioma (`fmtNum` y `Intl` en el JS; en
Python, una función de formato en vez de `:,`).

`local_translate` puede dar el **borrador** inglés de las ~1 380 cadenas (el brief lo permite,
siempre revisado): cuidado con que respete los `{}` y los identificadores entre comillas
invertidas (225 cadenas llevan uno embebido: 165 en Python, 60 en el panel).

## 6. Documentación

Medido por proporción de palabras funcionales españolas frente a inglesas:

| Fichero | Líneas | Español |
|---|---:|---:|
| `README.md` | 333 | 99 % |
| `CHANGELOG.md` | 2 556 | 100 % |
| `CONTRIBUTING.md`, `SECURITY.md` | 53, 99 | 100 % |
| `docs/wiki/*.md` (12 páginas) | 3 585 | 97–100 % |
| `site/index.html` | 730 | bilingüe en cliente (ES/EN) |

La única pieza pública en inglés es la metadata de registro: `server.json` (descripciones en
inglés) y la descripción del paquete. `README`, wiki y CHANGELOG están solo en español.

## 7. Interacción con el frente A

- Solo **7** cadenas de salida nombran literalmente un identificador que el frente A renombra:
  `recalcular-coste` (`checks.py:1652`, `valoracion.py:42`, `cli.py:319`), la skill
  `delegacion-local` (`cli.py:1423`, `cli.py:1459`), «secciones» en el aviso
  `secciones.py:271` (palabra de prosa, no el campo) y el prompt `server.py:3316`. Lo demás llega
  **por interpolación** de constantes (`{install.SKILL_NAME}`, `{TOKEN_VAR}`, nombres de variable
  en `config`), así que el frente A los arrastra solo si el texto usa la constante.
- **225** cadenas llevan algún identificador embebido (variable de entorno, `--opción`, algo entre
  comillas invertidas o `local_*`): si el frente A cambia un nombre escrito a mano dentro de una
  frase, hay que tocarla antes de catalogarla, que es justo por qué el brief ordena A antes que B.
- **Valores de máquina que el panel traduce a etiqueta**: el JS mapea `motivo` de la telemetría de
  hooks (`mcp_ajeno`, `no_es_prosa`, `no_es_volcado`, `sin_fichero`, `bloqueo_apagado`,
  `modelo_enfriado`, `pequeno`, `codigo`) y claves de rol a texto. Son valores persistidos (frente
  A, con lectura del formato viejo); las etiquetas son frente B. El mapa del JS debe aceptar el
  valor viejo y el nuevo.
- **Grupos del doctor** `entorno`/`andamiaje`/`servicio` (`checks.py:1784+`, `doctor.py:24-28`)
  son ids (frente A) que hoy hacen de clave de las cabeceras en español (frente B).
- **Contratos que no se traducen**: el prefijo `[local-delegate error]`, el marcador
  `[local-delegate aviso: …]` si alguien lo analiza, y los marcadores de bloque de `install`
  (`<!-- local-delegate:begin -->`). La cabecera del bloque de memoria la usa `agents.py:41` como
  detector: o se vuelve un marcador estable o el detector acepta los dos idiomas.
- `cadenas.py` y sus nombres (`Cadena`, `resolver`, `describir`) son frente A.

## Preguntas abiertas que cambian la spec

1. **Descripciones de tools (11 docstrings, 8,8 k caracteres)**: ¿se traducen, se pasan a inglés
   único, o se quedan en español? Afecta a las mediciones de adopción hechas en español y a que el
   daemon HTTP sirve un solo idioma a todos sus clientes.
2. **Idioma por defecto** para quien no elige nada: español (no rompe a nadie hoy) o locale del
   sistema con inglés de reserva (lo natural en PyPI).
3. **Una variable para todo** (CLI, MCP, hooks, defecto del panel) o selección por superficie.
   Con el daemon compartido, ¿basta un idioma por daemon?
4. **Textos que el servidor redacta para el panel** (causas, roles, `reason`, `summary`): ¿el
   servidor manda claves y el JS traduce, o el JS manda `?lang=` a `/api/*`?
5. **Prompts al modelo local y lo que genera**: ¿fuera de alcance (lo que el modelo local escribe
   sigue el idioma de la entrada) o se añade orden de idioma como en `local_commit_msg`?
6. **Skill, bloque de memoria y catálogo de agentes**: ¿se ofrecen en inglés? Si sí, `agents.py:41`
   necesita un detector que no dependa del texto.
7. **Documentación** (README, wiki, CHANGELOG): ¿entra en el frente B o queda para otro cambio?
8. **Mecanismo del catálogo** (A, B o C). A es el que menos toca los ~450 tests y los ~940
   sitios; B es el que mejor comparte con el panel; C es el único que traduce el chrome de
   argparse sin trabajo extra.
9. **Formato de números en las salidas del MCP**: ¿se unifica con el del panel (punto de miles en
   español) o el MCP se queda con `:,` porque lo lee un modelo?

## Llamadas local_* hechas

| Tool | Para qué | Resultado |
|---|---|---|
| `local_explain_code` (`path=resources/hooks/hook_common.py`) | Canales por los que los hooks emiten texto y quién lo ve | Útil: `additionalContext` lo ve el modelo, `permissionDecisionReason` el modelo y el usuario. Las líneas que dio eran aproximadas; se corrigieron con el `ast` (118-120 y 147-150) |
| `local_extract` (`path=site/index.html`, 6 campos) | Mecanismo de idioma del sitio sin meter sus 38 k caracteres al contexto | Correcto y verificado contra `site/index.html:640-709` |

No se delegó el inventario: es conteo exacto con `ast` y un tokenizador JS, que un modelo local
no hace mejor que un script. No se usó `local_translate`: el frente B aún no tiene catálogo que
traducir. `local_summarize` no hizo falta: los ficheros grandes (`server.py`, `metrics.py`) se
recorrieron con scripts, no leyéndolos.
