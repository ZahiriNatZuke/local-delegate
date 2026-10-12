# Investigación del frente A: mapa de impacto del renombrado a inglés

Fecha: 2026-10-12. Base: `main` en `8ec2f1d` (release 0.34.0). Solo lectura del repo; los scripts de
medición viven fuera del repo (scratchpad) y sus salidas completas están en `evidence/`:

| Fichero de evidencia | Qué tiene |
|---|---|
| `evidence/rename-inventory-public.csv` | 38 filas: cada elemento publicado o persistido, con definición, quién escribe, quién lee y si hay datos reales en esta PC |
| `evidence/rename-inventory-internal.csv` | 4 640 filas: cada identificador interno en español (Python y JS del panel) con `fichero:línea` de su primera definición, tipo y apariciones; más las claves de cadena en español (`dict_key`, `subscript`, `get`) |
| `evidence/internal-scan-summary.json` | Totales del escaneo interno, por grupo, por tipo y por fichero (los 143 ficheros) |
| `evidence/persisted-data-scan.json` | Claves y valores de enumeración en español encontrados en los ficheros REALES de esta PC (solo nombres y recuentos, ningún contenido; ids de `tool_use` sustituidos) |

## 0. Método y controles

**Detector de «esto está en español»** (`esdet.py`, en el scratchpad). Parte el identificador en
palabras (`snake_case`, `camelCase`, `kebab-case`, puntos), pliega acentos y compara la frecuencia
de cada palabra en español y en inglés con `wordfreq` (300 000 palabras por idioma). Una palabra es
española si su frecuencia Zipf en español es ≥ 1,8 y supera a la inglesa en más de 1,0, o si lleva
tilde o eñe. Lista corta de términos técnicos que nunca cuentan (`id`, `url`, `ttl`, `gpu`,
`llama`, `util`…) y de palabras ambiguas que en código son inglés (`total`, `local`, `error`,
`general`…). Un nombre hecho solo de una palabra funcional corta (`o`, `en`) no cuenta.

Controles hechos, porque un no-resultado no vale si la búsqueda no podía encontrar nada:

- **Positivo:** 30 nombres españoles conocidos (`bloqueo_id`, `fallo_conexion`, `VARIABLES_DE_ENTORNO`,
  `leido_server_side`, `local-delegate-bloqueo-apagado`, `config.coste`…): detecta 29. El que se
  escapa es `tokensClaude` (palabras inglesas en orden español; la regla de palabras no lo puede ver).
- **Negativo:** 54 nombres ingleses del repo (`cooldown_failures`, `test_windows`, `residency`,
  `general`, `local`, `control`…): cero falsos positivos.
- **Precisión por muestreo:** 80 nombres marcados como españoles al azar: 78 lo son; los dos dudosos
  (`o`, `_en_h1`) motivaron la regla de palabra funcional suelta y se re-ejecutó todo.
- **Exhaustividad por muestreo:** 150 nombres NO marcados al azar: 1 español escapado
  (`PATRON_TOOL_USE_ID`: `patron` existe en inglés). Exhaustividad estimada ≈ 99 %.
- **Falsos positivos residuales conocidos:** `llama_swap_version`, `llama-server` y `gpu_util_pct`
  (corregidos con la lista técnica), `ver` como clase CSS del panel.
- **JS del panel:** el primer intento con un tokenizador propio perdió dos tercios del código (77
  declaraciones de 311); el control positivo (`tokensClaude`, `aplicarBackend`, `acct`, `fmtNum`,
  `decimales` deben aparecer como declarados) lo delató y se rehízo con `esprima` (tokenizador real):
  los cinco aparecen.

**Apariciones** = tokens `NAME` de Python (`tokenize`), así que cuentan definiciones, usos y
atributos (`x.nombre`), pero no texto dentro de cadenas ni comentarios. Las claves JSON se cuentan
aparte («claves de cadena»).

## 1. Superficie pública y persistida

### 1a. Subcomandos y opciones del CLI

Recorrido por programa del parser real (`cli.build_parser()`, incluidos los subparsers de
`benchmark.add_parser` y `llamaswap`): 15 subcomandos y 101 opciones/posicionales. **Solo dos
nombres están en español**; todo lo demás (`benchmark`, `check-llamaswap`, `init-llamaswap`,
`llamaswap residency`, `doctor`, `serve`, `test-window *`, `install`, `update`, `uninstall`) ya está
en inglés, igual que sus `choices`.

| Nombre actual | Definición | Menciones (src / tests / scripts / wiki / README+CHANGELOG) | Nota |
|---|---|---|---|
| `recalcular-coste` | `src/local_delegate/cli.py:1369` (handler `cmd_recalcular_coste`, `cli.py:309`) | 9 / 11 / 3 / 17 / 3 | además es texto en `valoracion.COMANDO` (`valoracion.py:42`), que el panel y `doctor` imprimen |
| `--reiniciar-calibracion` (`dest=reiniciar_calibracion`, valores `five_hour`/`seven_day`) | `cli.py:1376` | 1 / 2 / 1 / 4 / 1 | |

Ambos con alias temporal según la decisión ya tomada.

### 1b. Variables de entorno

Inventario por programa: `config.VARIABLES_DE_ENTORNO` tiene 60 nombres; un barrido de todo
`src/` y `scripts/` encontró 6 cadenas más con el prefijo, y ninguna es una variable que se lea
(`LD_GROUPS`, `LD_GAP_S` y `LLAMASWAP_DAEMON` son nombres de constantes que contienen el prefijo;
`LOCAL_DELEGATE_FALLBACK_`/`MODEL_` son prefijos que se completan con el rol). **Cuatro nombres en
español:**

| Variable | Dónde se lee | Quién la fija hoy en esta PC | Riesgo |
|---|---|---|---|
| `LD_HOOK_READ_BLOQUEAR` | `config.py:209` y, por su cuenta, `resources/hooks/hook_common.py:263` | bloque `env` de `~/.claude/settings.json` (valor `1`) | la leen **copias de hooks ya instaladas**: el alias tiene que existir en `hook_common` además de en `config` |
| `LD_HOOK_READ_INTERRUPTOR` (valor: ruta) | `config.py:213`, `hook_common.py:254` | no está fijada | su defecto es el fichero `~/.claude/local-delegate-bloqueo-apagado` (ver 1g) |
| `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO` | `config.py:262` | el lanzador del daemon de esta PC (fuera del repo) | el lanzador del usuario hay que tocarlo o depender del alias |
| `LOCAL_DELEGATE_COSTE_RESPALDO` | `config.py:417`; además es texto en `valoracion.py:43` | no | |

**Valores aceptados en español:** `LOCAL_DELEGATE_FALLBACK_<ROL>` acepta `residente` (y `resident`)
como sinónimo **ya obsoleto** de `loaded` (`cadenas.py:42`), con aviso de `doctor`. El resto de
valores (`auto|on|off`, `stdio|http`, `modelo:main|subagent` donde `modelo` es un id) están en
inglés.

### 1c. Formatos persistidos en disco

Datos reales medidos en esta PC (`LOG_DIR` = `%LOCALAPPDATA%\local-delegate`, telemetría en
`~/.claude/hooks/telemetry.jsonl`). Solo se contaron líneas y claves.

| Fichero | Lo escribe | Lo leen | Datos reales aquí | Claves en español | Valores en español |
|---|---|---|---|---|---|
| `usage-YYYYMM.jsonl` | daemon, `server.py:382`, filas en `server.py:700-860` | `web/metrics.py` (panel), `pace.py:241`, `atribucion`, `valoracion`, `scripts/medir_adopcion.py`, `medir_enfriamiento.py`, `experimento_adopcion.py`, `medir_resumen_estructurado.py` | 4 ficheros, 446 filas | `bloqueo_id` (`server.py:786`, 33 filas), `secciones` (`server.py:813`, 116 filas), `fallo_conexion` (`server.py:808`, 0 filas aquí) | `error_class`/`fallback_class`: enum `fallos.Clase` (`fallos.py:45`): `peticion`, `capacidad_o_carga`, `timeout_lectura`, `configuracion`, `modelo`, `sin_clasificar` (6 de 7) + `enfriamiento` (`server.py:1081`); `fallo_conexion`: enum `CausaConexion` (`fallos.py:204`), 8 de 11 en español (`rechazada`, `sin_ruta`, `timeout_conexion`, `credencial`, `sin_respuesta`, `respuesta_invalida`, `url_invalida`, `transporte`, `desconocida`); `fallback_reason` es prosa (`"en enfriamiento"`) |
| `enfriamiento.json` | daemon, `enfriamiento.py:261` (`estado_json.escribir_json_atomico`) | daemon; **los hooks instalados** (`hook_common.py:315`) | 1 (vacío) | `fallos`, `espera_s`, `hasta`, `reentradas` (`enfriamiento.py:79`) | — |
| `enfriamiento-eventos.jsonl` | daemon, `enfriamiento.py:47-62` | `scripts/medir_enfriamiento.py` (**medición P-4 abierta**, 90 días desde 2026-09-15 → hasta ~2026-12-14) | 2 líneas | `modelo`, `evento`, `espera_s`, `reentradas`, `clase`, `tras_vencer` | `evento`: `entra`, `reentra`, `limpia`; `clase`: valores de `fallos.Clase` |
| `atribucion-YYYYMM.json` | `atribucion.escribir_relleno` (`atribucion.py:278-319`), vía `recalcular-coste` | `atribucion`, `coste`, `recalcular`, `transcripts`, `valoracion`, check `config.coste` | 4 ficheros | `entradas`, `cruce`, `banco` | `cruce`: `exacto`, `ventana`, `ambiguo`, `sin_cruce`. Lleva `version: 1` (`atribucion.py:55`) pero **nadie la comprueba al leer** |
| `coste-agregados.json` | `recalcular.py:28-61` | `cuota.estado`, panel (`/api/stats`), check `config.coste` | 1 | 21 (`cotejo.{fecha,fuera,juzgadas,sin_precio,veredicto,version_tabla}`, `puntos[].{inicio,fin,fuente,tipo,marcas,peticiones_sin_precio}`, `fuentes`, `generado`, `n_por_mes`, `plazo_dias`, `descartes.*.{contaminado,fuera_de_rango,linea_corrupta…}`) | `veredicto`: `pasa`/`falla`; `fuente`: `rechazo`…; `marcas` son **prosa usada como valor**: `"cota baja"`, `"solo comprobación"`, `"reinicio"` (`cuota.py:30-33`). `version: 1` (`recalcular.py:29`) |
| `test-windows.json` | `test_windows.py:263` | daemon, panel, `scripts/medir_*.py` | 1 | ninguna | — (ojo: `VERSION=1` y una versión desconocida se trata como error, `test_windows.py:206`) |
| `daemon.json`, `inflight.json`, `clients.jsonl` | daemon | daemon, CLI, panel, `doctor` | sí | ninguna | — |
| `~/.claude/hooks/telemetry.jsonl` (`LD_HOOK_TELEMETRY_LOG`) | hooks, `hook_common.record` (`hook_common.py:91-107`) | panel `/api/hooks` (`web/metrics.py:623`), `scripts/medir_adopcion.py`, `scripts/_banco_claude.py` | **31 691 líneas** | `motivo` (16 912 líneas), `bloqueo` (13 791), `camino` (13 054), `oferta` (62, ya no la escribe nadie), `rutas` (25) | `bloqueo: encendido`; `motivo`: `acotada`, `codigo`, `pequeno`, `backend_ausente`, `modelo_enfriado`, `prosa_grande`, `no_es_volcado`, `sin_fichero`, `no_es_prosa`, `bloqueo_apagado`, `mcp_ajeno` |
| `TEMP/local-delegate-bloqueos.jsonl` | hooks (`hook_common.py:349-371`) | daemon (`server._bloqueo_reciente`, `server.py:497-512`) | 2 líneas | ninguna (`id`, `sha`, `ts`) | nombre del fichero en español |
| `TEMP/local-delegate-llamadas/<tool_use_id>.json` | hook `anotar_llamada.py` (`hook_common.py:395-447`) | daemon (`atribucion.leer_nota`, `atribucion.py:73`) | 1 directorio | ninguna | nombre del directorio en español; caduca a 600 s |
| `TEMP/local-delegate-salud-<huella>.json` | hooks (`hook_common.py:180-234`) | hooks | 1 | ninguna (`ts`, `ok`) | nombre en español; caché |
| `~/.claude/cuota-statusline.jsonl` | **el statusline propio del usuario** (contrato documentado en `docs/wiki/Savings-and-metrics.md:349`) | `recalcular.py:195` | 1 248 líneas | ninguna (`ts`, `session_id`, `model`, `five_hour`…) | solo el **nombre del fichero** es español y lo escribe código que no es del paquete |
| `resources/datos/precios.json` (paquete) | `scripts/vigilante_precios.py` desde el workflow `.github/workflows/vigilante-precios.yml` | `precios.py:48`, `coste`, `valoracion`, `recalcular`, `checks` | — | 70 (`modelos.*.{entrada,lectura,salida,familia,admite_esfuerzo}`, `consultado`, `fuente`, `busqueda_web_por_1000`, `_nota`) | `familia`: `nueva`/`anterior` |
| `resources/datos/densidad.json` (paquete) | a mano | `precios.py:55`, `coste.resolver_densidad` | — | 19 (`familias`, `medido_con`, `sin_numerar`, `formato_read`, `prosa`, `codigo`, `estructurado`, `medido`, `_nota`) | claves `nueva`/`anterior` |
| salida de `local-delegate benchmark --output` | `benchmark.py:1230-1324` | `scripts/analizar_benchmark.py`, `hoja_pares.py`, `hoja_revision.py`, `construir_corpus.py` | fuera de `LOG_DIR` | `procedencia`, `descartada`, `descartada_motivo` | `truncado_repetido`, `anulada` |

Barrido complementario de valores tipo enumeración en `src/` (comparaciones, valores de dict,
constantes y argumentos con nombre): **57 valores distintos** en español; la lista está en las
filas `string_key` del inventario interno y en `persisted-data-scan.json`.

### 1d. Endpoints HTTP y panel

- **Rutas:** todas en inglés: `/api/events`, `/api/stats`, `/api/hooks`, `/api/inflight`,
  `/api/backend`, `/api/backend/stats`, `/api/status`, `/api/system`, `/api/llamaswap/status`,
  `/api/llamaswap/watch[/<id>]` (`web/metrics.py:493-959`) y `/api/daemon` (`daemon.py:30`).
  Parámetros de consulta en inglés (`from`, `to`, `include_tests`).
- **Campos de respuesta en español:** el JS del panel (un único bloque `<script>` de 1 293 líneas,
  `metrics.py:1651-2944`) lee **81 nombres de propiedad en español** que no declara él mismo, es
  decir, que llegan del JSON: `estado` (11 lecturas), `disponible`, `bueno`, `cifra`, `ultimo`,
  `motivo`, `detalle`, `etiqueta`, `clase`, `titulo`, `coste`, `cuota`, `cota_baja`, `estimacion`,
  `densidad`, `imagenes`, `puntos`, `by_motivo`, `motivo_pct`, `hay_agregados`… (lista completa:
  filas `panel_js_property` del inventario interno). Los producen `web/metrics.py:540-657`,
  `valoracion.py:226-297`, `cuota.py:85-394` y `coste.py`. Incluye **diccionarios de etiquetas
  indexados por valores persistidos** (los 11 `motivo` de la telemetría y los valores de
  `CausaConexion`): si se renombran los valores, ese diccionario JS tiene que aceptar los dos.
- **JS propio:** 311 identificadores declarados, **65 en español** (255 apariciones):
  `aplicarBackend`, `decimales`, `tokensClaude`…
- **DOM:** 75 ids, 20 en español (`costeCard`, `cuotaBody`, `dlgImagenes`, `dlgPruebas`,
  `dlgSistema`…); la suite de Playwright (`tests/test_dashboard_ui.py`) los selecciona.
- **`localStorage`** del navegador: `ld-theme`, `ld-tests` (inglés).
- **Cookie de sesión** `ld_sesion` y prefijo firmado `ld-sesion|v1` (`web/auth.py:45, 50`):
  persistido en el navegador; cambiarlo obliga a volver a autenticarse una vez (no rompe).
- **Espejo JS de `_accounting`:** `server._accounting` (`server.py:896`) y `tokens_claude`
  (`server.py:870`) frente a `acct`/`tokensClaude` del JS (`metrics.py:2601`). La paridad la atan
  `tests/test_dashboard_js.py` (corre node y **extrae funciones del HTML por su cabecera literal**,
  p. ej. `"function tokensClaude("`, `"function acct(e){"`) y `tests/test_metrics.py`. Ambos leen
  `densidad[tipo]` de la fila fundida (`coste.fundir`).

### 1e. Contrato de salida de las tools MCP

- **Nombres de tools y parámetros:** los 11 (`local_summarize` … `local_status`, `server.py:3429-4405`)
  y todos sus parámetros están en inglés (comprobado por AST: 0 parámetros en español).
- **`local_extract` → clave reservada `_local_delegate`** (raíz en inglés) con subclaves en español:
  `truncado`, `aviso`, `leido_server_side.{chars, tokens_aprox}`, `respaldo.{respondio,
  en_lugar_de, motivo, clase}`, `crudo` (`server.py:3612-3631`, `server.py:1083`). Documentado
  como contrato en `docs/wiki/Configuration.md:221-234`.
- **Marcadores de texto que un agente puede detectar:** `[local-delegate error] …` (inglés; el propio
  servidor lo detecta en `server.py:3929` y la skill lo cita), pero `[local-delegate aviso: …]`
  (`server.py:1099, 2422`), `[local-delegate respaldo: …]` (`server.py:2169`) y
  `[local-delegate: entrada truncada …]` (`server.py:474`) están en español. Son prefijos de máquina
  con prosa detrás: el prefijo es del frente A, la prosa del B.
- La línea `(leído server-side: …)` que se anexa al resultado es prosa (frente B).

### 1f. Ids de checks de `doctor`

25 checks en `checks.CHECKS` (`checks.py:1785-1810`). **Dos ids en español:** `config.rol_retirado`
(`checks.py:1790`) y `config.coste` (`checks.py:1792`). **Tres de los cuatro grupos** también:
`entorno`, `andamiaje`, `servicio` (`backend` ya en inglés), usados como claves en `doctor.py:24`,
`cli.py:46` (`_SCAFFOLD_GROUPS`) y en los tests (`tests/test_checks.py:77, 120`).

Dónde se usan los ids: `tests/test_rol_fast_retirado.py` (10 menciones), `tests/test_checks.py`,
`tests/test_coste_doctor.py`, `docs/wiki/Troubleshooting.md:247`,
`docs/wiki/Savings-and-metrics.md:338`, `CHANGELOG.md:148, 403`. **El test de la wiki
(`tests/test_wiki.py:219-235`) compara los TÍTULOS** (prosa en español, `Check.title`) y la columna
de grupo, no los ids: renombrar ids no lo rompe; traducir títulos en el frente B sí.

### 1g. Ficheros, rutas y nombres instalados en el disco del usuario

| Nombre | Definición | Mecanismo de retirada hoy |
|---|---|---|
| `~/.claude/local-delegate-bloqueo-apagado` (interruptor en caliente; no existe ahora) | `hook_common.py:255` | ninguno; lo crea el usuario a mano |
| hook `anotar_llamada.py` en `~/.claude/hooks/local-delegate/` (instalado aquí) | `install.py:64`, `install.py:314` | `_SCRIPTS_RETIRADOS` (`install.py:102`) borra el viejo y quita su entrada de `settings.json` **si se añade a la tupla** |
| `hook_common.py` (lo importan los otros cuatro hooks **y el paquete**: `atribucion.py:30`, `server.py:507`) | `resources/hooks/` | — |
| skill `delegacion-local` en `~/.claude/skills/` y `~/.config/opencode/skill/` (instalada aquí) | `install.py:45` | **ninguno**: no hay equivalente a `_SCRIPTS_RETIRADOS` para skills; renombrarla deja la vieja instalada y duplicada |
| bloque gestionado de memoria (`resources/memory/local-delegate.md`, marcadores `<!-- local-delegate:begin -->`) | `install.py:38` | marcadores en inglés; el texto del bloque cita la skill `delegacion-local` |
| ficheros temporales `local-delegate-bloqueos.jsonl`, `local-delegate-llamadas/`, `local-delegate-salud-*.json` | ver 1c | efímeros |
| `~/.claude/cuota-statusline.jsonl` | `recalcular.py:195` | lo escribe el statusline del usuario |
| directorio del paquete `resources/datos/` | `precios.py:48, 55` | interno al wheel |

Nombres del servicio (`LocalDelegateDaemon`, `com.local-delegate.daemon`,
`local-delegate.service`, `update.py:46-48`): inglés.

### 1h. Módulos en español

`pyproject.toml` solo publica `local_delegate:main` (dos alias de script); `__init__.py` exporta
solo `main`; ninguna página de `docs/` importa un módulo del paquete. **Ningún módulo es API
pública.** Pero dos cosas los atan por nombre: los scripts de `scripts/` los importan, y
`hook_common` se importa desde el paquete como `.resources.hooks.hook_common`.

| Grupo | Ficheros .py | En español | Lista |
|---|---|---|---|
| `src/local_delegate` | 48 | **14** | `anotar_llamada`, `atribucion`, `cadenas`, `coste`, `cuota`, `enfriamiento`, `estado_json`, `fallos`, `precios`, `preguntas`, `recalcular`, `secciones`, `sondas`, `valoracion` |
| `tests` | 96 | 41 | p. ej. `test_aislamiento_entorno`, `test_enfriamiento`, `test_causa_conexion`… (más los directorios de fixtures `residencia/` y `topologia/`) |
| `scripts` | 31 | 14 | `_banco_claude`, `analizar_benchmark`, `construir_corpus`, `medir_adopcion`, `medir_enfriamiento`, `vigilante_precios`… |

Importadores aproximados (regex) de cada módulo de `src` en español: `atribucion` 5 en src / 8
tests / 1 script; `precios` 5/2/0; `fallos` 4/5/0; `coste` 3/6/1; `recalcular` 2/8/0;
`enfriamiento` 0/5/1; `secciones` 0/1/1; el resto ≤ 2.

## 2. Superficie interna (no persistida)

| Medida | src | tests | scripts | Total |
|---|---|---|---|---|
| Nombres únicos definidos | 3 100 | 4 114 | 1 023 | 8 237 |
| … en español (por fichero de primera definición) | 858 | 2 306 | 457 | **3 621** |
| Apariciones de esos nombres | 5 801 | 15 438 | 4 669 | **25 908** |
| Ficheros con alguna aparición | 36 | 84 | 23 | 143 |
| JS del panel: declarados en español / apariciones | 65 / 255 | — | — | |
| Claves de cadena en español (`"x":`, `d["x"]`, `.get("x")`) únicas / apariciones | 128 únicas | | | 557 / 3 057 |

Desglose por tipo (nombres en español, primera definición): **tests**: 1 383 funciones `test_*`,
396 variables, 267 funciones auxiliares, 115 constantes, 70 parámetros, 26 clases; **src**: 338
variables, 246 funciones, 141 constantes, 81 parámetros, 25 clases, 13 atributos; **scripts**: 155
variables, 149 funciones, 98 constantes, 25 parámetros, 13 clases. (El tipo «módulo» de este
desglose subcuenta porque un nombre se asigna a su primera definición; el recuento real de módulos
está en 1h.)

Nombres más frecuentes: `texto` 603, `salida` 388, `ruta` 350, `datos` 286, `ahora` 283, `linea`
264, `fila` 259, `resultado` 254, `lineas` 232, `estado` 230, `destino` 224, `nombre` 220, `evento`
211, `recargar_config` 207, `entrada` 203.

Top 30 ficheros por apariciones de identificadores en español:

| # | Fichero | Apariciones |
|---|---|---|
| 1 | `src/local_delegate/server.py` | 1 096 |
| 2 | `scripts/construir_corpus.py` | 1 076 |
| 3 | `tests/test_analisis_benchmark.py` | 834 |
| 4 | `tests/test_dashboard_ui.py` | 805 |
| 5 | `scripts/analizar_benchmark.py` | 748 |
| 6 | `tests/test_vigilante.py` | 734 |
| 7 | `tests/test_resumen_estructurado.py` | 680 |
| 8 | `scripts/vigilante_precios.py` | 627 |
| 9 | `tests/test_atribucion.py` | 544 |
| 10 | `tests/test_respaldo.py` | 536 |
| 11 | `tests/test_enfriamiento.py` | 515 |
| 12 | `src/local_delegate/secciones.py` | 511 |
| 13 | `src/local_delegate/checks.py` | 433 |
| 14 | `tests/test_corpus.py` | 397 |
| 15 | `src/local_delegate/recalcular.py` | 379 |
| 16 | `tests/test_medir_enfriamiento.py` | 375 |
| 17 | `src/local_delegate/transcripts.py` | 340 |
| 18 | `scripts/experimento_adopcion.py` | 334 |
| 19 | `tests/test_checks.py` | 324 |
| 20 | `tests/test_metrics.py` | 316 |
| 21 | `tests/test_panel_coste.py` | 309 |
| 22 | `tests/test_hoja_pares.py` | 300 |
| 23 | `tests/test_causa_conexion.py` | 298 |
| 24 | `src/local_delegate/enfriamiento.py` | 296 |
| 25 | `src/local_delegate/fallos.py` | 287 |
| 26 | `src/local_delegate/cuota.py` | 281 |
| 27 | `tests/test_experimento_adopcion.py` | 281 |
| 28 | `tests/test_valoracion.py` | 277 |
| 29 | `src/local_delegate/valoracion.py` | 275 |
| 30 | `tests/test_cuota.py` | 275 |

Resto de `src` (apariciones): `coste` 271, `atribucion` 265, `web/metrics.py` 236 (solo Python; el
JS va aparte), `install` 193, `hook_common` 142, `web/auth` 131, `suggest_delegate_shell` 86, `cli`
83, `cadenas` 78, `clients` 76, `suggest_delegate_read` 74, `precios` 67, `config` 40, el resto < 35.

Contraste con la estimación del brief (≈3 500 nombres, ≈32 000 apariciones, 156 ficheros): los
nombres cuadran (3 621); las apariciones salen menos (25 908 + 255 de JS) porque aquí no se cuentan
cadenas ni comentarios; con las 3 057 apariciones de claves de cadena el total ronda 29 200.

## 3. Acoplamientos que imponen un orden

1. **Datos ya escritos que no se pueden regenerar.** `atribucion-*.json` y los `puntos` de
   `coste-agregados.json` guardan cruces con transcripts que Claude Code borra con el tiempo
   (`recalcular.py:210`: «un punto cuyo transcript ya se borró sigue ahí hasta que caduca»). Un
   lector nuevo que ignore las claves viejas **pierde historia de forma irreversible**: hace falta
   leer las dos formas o migrar en el sitio antes de dejar de leer la vieja.
2. **Medición P-4 abierta hasta ~2026-12-14.** `scripts/medir_enfriamiento.py` lee
   `enfriamiento-eventos.jsonl` (`modelo`, `evento` = `entra|reentra|limpia`, `espera_s`, `clase`,
   `tras_vencer`) y del log de uso `fallback_class == "modelo"` y `clase == "timeout_lectura"`
   (líneas 112-211). Renombrar campos o valores de `fallos.Clase` antes de esa fecha obliga a que el
   script lea los dos formatos **en el mismo PR**, o a congelar ese formato hasta cerrar P-4.
3. **Hooks instalados frente a daemon nuevo, en los dos sentidos.** Los hooks copiados en
   `~/.claude/hooks/local-delegate/` solo se reponen con `install`/`update` (y la Mac corrió hooks
   viejos hasta la 0.31.2). Comparten con el daemon: `enfriamiento.json` (los hooks leen el estado,
   `hook_common.py:315`), `local-delegate-bloqueos.jsonl` (hooks escriben, daemon lee),
   `local-delegate-llamadas/` (ídem), la telemetría (hooks escriben, panel lee) y
   `LD_HOOK_READ_BLOQUEAR`. Durante una ventana conviven versiones distintas de cada lado: el lector
   tiene que aceptar nombre viejo y nuevo de ficheros, claves y valores.
4. **`hook_common` es a la vez script instalado y módulo del paquete** (`atribucion.py:30`,
   `server.py:507`): renombrar sus funciones toca los dos lados en el mismo cambio, y renombrar el
   fichero obliga a `_SCRIPTS_RETIRADOS` y a cambiar los `from hook_common import` de los cuatro
   hooks.
5. **Paridad Python/JS.** Los nombres de campo de la fila fundida (`densidad`, …) los leen
   `server._accounting` y `acct` del JS a la vez; los tests de paridad extraen las funciones JS por
   su cabecera literal (`tests/test_dashboard_js.py:94-249`), así que renombrar una función JS
   rompe esos tests (en rojo, no en silencio). Campos de `/api/stats` y diccionarios de etiquetas
   del JS cambian con su productor en el mismo PR.
6. **Aislamiento del entorno en tests.** `tests/test_aislamiento_entorno.py` escanea por AST las
   lecturas `os.environ.get/getenv/[...]` de los hooks y exige que `config.py` solo lea por `_env*`
   o `_leer` (`:84-114`). Un alias de variable tiene que leerse **por esa puerta en los dos nombres**
   (si no, el nombre viejo queda fuera de `VARIABLES_DE_ENTORNO` y la suite hereda el entorno real).
7. **Wiki y `doctor`.** `tests/test_wiki.py:219-244` compara títulos y número de checks; añadir un
   check de «nombres obsoletos» cambia el número (la wiki dice «las N piezas») y exige su fila.
   Ids y grupos aparecen además en CHANGELOG y en `test_checks.py:77` (conjunto exacto de grupos).
8. **La Mac** escribe el formato viejo en su propio `LOG_DIR` y su propia telemetría hasta que se
   actualice; sus logs se copian a mano a la PC para medir, así que los scripts `medir_*.py` también
   tienen que leer ambos formatos.
9. **`precios.json` lo regenera un workflow.** `scripts/vigilante_precios.py` (lo corre
   `.github/workflows/vigilante-precios.yml` y abre PRs) escribe las claves y la ruta
   `resources/datos/precios.json`: script, workflow, `precios.py` y los tests del vigilante
   (`tests/test_vigilante.py`, 734 apariciones) cambian juntos.
10. **Scripts de `scripts/` importan módulos del paquete** (`medir_adopcion.py` usa
    `atribucion.test_reason`; `medir_enfriamiento.py`, `enfriamiento`): renombrar un módulo rompe
    scripts que la suite solo cubre si tienen test.
11. **`cuota-statusline.jsonl` lo escribe el statusline del usuario**, no el paquete: renombrarlo
    rompe silenciosamente la calibración de quien siga la wiki, salvo que se lean los dos nombres.
12. **`test-windows.json` rechaza versiones desconocidas** (`test_windows.py:206`). No tiene claves
    en español, pero si alguna ola sube su `version`, un daemon viejo (Mac) lo tratará como error.
13. **LF/CRLF:** 16 ficheros de `src`/`tests`/`docs/wiki` son CRLF, entre ellos `server.py`,
    `cli.py`, `install.py`, `web/metrics.py`, `clients.py`, `preguntas.py` y
    `docs/wiki/Integration-install.md`; un fixture es mixto
    (`tests/fixtures/residencia/pre-b10909-20260915.yaml`). Un renombrado masivo con
    `write_text` los convertiría.

## 4. Mecanismos de compatibilidad que ya existen

| Mecanismo | Dónde | Reutilizable para |
|---|---|---|
| Opción histórica equivalente (`--target` = `--clients`, incompatibles entre sí) | `cli.py:56-71`, `cli.py:1407` | alias de `--reiniciar-calibracion` y del subcomando |
| Sinónimos obsoletos de un **valor** que siguen valiendo + aviso de `doctor` (`residente`/`resident` → `loaded`) | `cadenas.py:42, 142-158`; `checks.py:1612-1619` | valores de variables y, por analogía, valores persistidos |
| Variables retiradas leídas aparte y nombradas por `doctor` (`RETIRED_FAST_ROLE_VARIABLES` + check `config.rol_retirado`) | `config.py:244-251`; `checks.py:1629` | generalizarlo a «variables renombradas»: leer la vieja como alias y avisar |
| Scripts de hooks retirados que `install` borra y desregistra | `install.py:102, 333, 899` | renombre de `anotar_llamada.py` y de cualquier hook |
| Detección de registros de hooks de una instalación anterior | `checks.py:767-790` | aviso tras renombrar hooks |
| Alias Python retrocompatibles de nombres públicos de módulo | `llamaswap_config.py:279, 456` | aliases temporales de funciones si algún script externo las usa |
| Lectura de un fichero heredado junto a los rotados (`usage.jsonl`) | `web/metrics.py:94-96` | leer `enfriamiento-eventos.jsonl` viejo junto al nuevo, etc. |
| Lectura tolerante del estado con esquema fijo y defectos | `enfriamiento.py:76-89` (`_entrada`), `test_windows.load` | lector que acepta dos nombres de clave |
| Campo de `version` en las cachés (`atribucion` v1, `coste-agregados` v1, `test-windows` v1) | `atribucion.py:55`, `recalcular.py:29`, `test_windows.py:33` | migración explícita por versión (hoy `atribucion` y `coste-agregados` no la comprueban al leer) |
| Lectura de dos campos con prioridad | `server.py:998` (`error_class` o `fallback_class`) | patrón para claves renombradas en filas del log |
| Marcadores de bloque gestionado en inglés | `install.py:38-40`, `agents.py:33` | no hace falta tocarlos |

No existe: un retiro de skills instaladas (equivalente a `_SCRIPTS_RETIRADOS`), ni un helper
común de «clave nueva o vieja» para JSON, ni un aviso genérico de «nombre obsoleto» en `doctor`.

## 5. Troceado posible en olas (dato para el plan, no propuesta cerrada)

Tamaños en apariciones de identificadores en español (src + sus tests), más los nombres públicos.

| Ola | Contenido | Tamaño aproximado |
|---|---|---|
| 0. Andamiaje de compatibilidad | helper de variable con alias (por `_env*`), helper de clave JSON vieja/nueva, retiro de skills en `install`, check de `doctor` de nombres obsoletos (+ fila de wiki) | pequeño: ~150-250 líneas nuevas, 1 check nuevo |
| 1. CLI y variables | `recalcular-coste`, `--reiniciar-calibracion`, las 4 variables (alias en `config` **y** en `hook_common`), docs | 6 nombres; ~90 menciones en src/tests/docs |
| 2. Hooks y telemetría | `hook_common` + 4 hooks (≈320 apariciones), claves y 11 valores de `motivo`, ficheros temporales, interruptor, `anotar_llamada.py` → `_SCRIPTS_RETIRADOS`, lector de `/api/hooks` y JS, `medir_adopcion.py` | ≈320 src + tests de hooks; 31 691 líneas viejas a seguir leyendo |
| 3. Log de uso y clases de fallo | `bloqueo_id`, `secciones`, `fallo_conexion`, enums `Clase` y `CausaConexion`, `fallos.py` (287), lectores del panel y JS | ≈600 src + `test_causa_conexion`, `test_fallos*`, `test_respaldo` (≈1 200) |
| 4. Enfriamiento | `enfriamiento.py` (296), sus dos ficheros, `medir_enfriamiento.py` | ≈300 src + ≈900 tests; **condicionada a P-4** |
| 5. Coste, cuota y atribución | `coste`, `cuota`, `atribucion`, `recalcular`, `valoracion`, `precios`, `transcripts` (≈1 880), cachés, `precios.json`/`densidad.json`, `resources/datos/`, vigilante y workflow, campos de `/api/stats` y JS | la mayor de lo publicado: ≈1 900 src + ≈2 500 tests |
| 6. Contrato MCP, skill, `doctor` y cookie | subclaves de `_local_delegate`, marcadores `aviso`/`respaldo`, skill `delegacion-local`, ids y grupos de checks, `ld_sesion`, `secciones.py` (511) | ≈700 src + docs |
| 7. `server.py` resto | ≈1 100 apariciones en un fichero CRLF de 4 560 líneas | partirlo en 2 PRs |
| 8. Resto de `src` | `checks`, `install`, `cli`, `clients`, `web/auth`, `cadenas`, `preguntas`, `sondas`, `config`… y módulos (14 renombres de fichero) | ≈1 200 |
| 9. Tests | 1 383 nombres `test_*`, 41 módulos de test, auxiliares (lo que no haya caído con su ola) | ≈15 400 apariciones en 84 ficheros; 2-3 PRs |
| 10. Scripts | 14 módulos, 4 669 apariciones (no se publican) | 2 PRs |

Total: 11-13 olas, coherente con las 12-16 del brief. Las olas 0-6 son las que tocan lo
publicado; 7-10 son mecánicas y no cambian contratos.

## 6. Preguntas abiertas que cambian la spec

1. **Datos ya escritos: ¿leer los dos formatos para siempre, durante N versiones, o migrar en el
   sitio?** Las cachés `atribucion-*.json` y los puntos de `coste-agregados.json` no se pueden
   regenerar; el log de uso y la telemetría (31 691 líneas) son historia de las mediciones.
2. **P-4: ¿se congela `enfriamiento-eventos.jsonl` y los valores de `fallos.Clase` hasta
   ~2026-12-14, o se renombra ya con `medir_enfriamiento.py` leyendo los dos formatos?**
3. **¿Entran los VALORES de enumeración persistidos** (`error_class`, `fallo_conexion`, `motivo`,
   `cruce`, `familia: nueva|anterior`, `evento: entra|limpia`, `veredicto: pasa|falla`)? Son 57
   valores; si entran, cada lector y el diccionario de etiquetas del JS necesitan tabla de
   equivalencias.
4. **Prosa guardada como valor de máquina** (`marcas: "cota baja"`, `"solo comprobación"`,
   `fallback_reason: "en enfriamiento"`): ¿se convierte en código inglés con texto aparte (frente A)
   o se trata como texto traducible (frente B)?
5. **Contrato de `local_extract` y marcadores `[local-delegate aviso|respaldo: …]`:** una salida no
   admite alias. ¿Se emite solo el nombre nuevo (cambio incompatible anunciado en CHANGELOG) o los
   dos durante una versión?
6. **Skill `delegacion-local`:** su nombre es visible para el usuario y para Claude (lo cita el
   bloque de memoria instalado y el `CLAUDE.md` global de esta PC). ¿Se renombra? Exige un
   mecanismo nuevo de retiro de skills en `install`.
7. **`~/.claude/cuota-statusline.jsonl`** lo escribe el statusline del usuario: ¿se mantiene el
   nombre (contrato externo) o se aceptan los dos?
8. **Alcance de `tests/` y `scripts/`:** son el 78 % de las apariciones (20 107 de 25 908) y no se
   publican. ¿Mismo SDD y mismas olas, o un cambio aparte de menor prioridad?
9. **Horizonte de los alias** (subcomando, opción, 4 variables, nombre de ficheros): ¿cuántas
   versiones viven y qué dice `doctor`? Si se generaliza `config.rol_retirado` a un check de
   «nombres obsoletos», cambia el número de checks y la wiki.
10. **Cookie `ld_sesion`:** ¿se acepta que renombrarla obligue a autenticarse una vez?

## Llamadas local_* hechas

| Tool | Para qué | Resultado |
|---|---|---|
| `local_explain_code(path=tests/test_aislamiento_entorno.py)` | entender cómo descubren los guardianes las variables y qué rompería un alias | útil: confirma escaneo AST de hooks y la puerta `_env*`/`_leer` (contrastado con `grep` de las líneas 84-114) |
| `local_summarize(path=scripts/medir_enfriamiento.py, focus=campos)` | qué campos y valores lee la medición P-4 sin leer el script | útil: añadió el valor `reentra` y `error == "cooldown"`, que se verificaron después con `grep` |
| `local_extract(path=scripts/medir_adopcion.py, fields=[5 campos])` | qué ficheros, campos y valores lee la medición de adopción | útil: destapó que el script importa `atribucion.test_reason` (acoplamiento por nombre de módulo, punto 10) |

No se delegó el inventario en sí: contar por programa con AST, `tokenize` y `esprima` es exacto y
la regla del brief pide números medidos, no resumidos. Las lecturas largas (`config.py`,
`hook_common.py`) se hicieron por tramos con `sed` en vez de enteras.
