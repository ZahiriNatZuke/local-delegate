# B2d: muestras en vivo

Ventana de prueba: **`w-20261014T215251Z`** (`local-delegate test-window start --label "B2d muestras
en vivo"`), cerrada con `stop`: 2026-10-14T21:52:51.740Z a 2026-10-14T22:01:18.409Z.

Daemon: v0.35.0 con el código de `origin/main` `359af3b` (B2a–B2c). `local_status` al empezar:
«Idioma: es (sistema…)», «Idioma de respuesta del modelo: es (sistema)»; modelos `code` =
`qwen36-35b-a3b`, `long` = `gemma4-26b-a4b`. RAM de sistema 29,1 / 31,1 GiB (aviso de < 2 GB libres).
El daemon no se reinició ni se tocó su configuración.

## 1. Idioma de respuesta (REQ-028, decisión 9): BLOQUEADA

El arnés en proceso del diseño (`waves/B2-proposal.md` §5.1) llama a las tools desde procesos hijos
contra el llama-swap local, sin pasar por el daemon. Requisito previo, comprobado antes de escribirlo:

| Comprobación | Resultado |
|---|---|
| `GET http://127.0.0.1:9292/v1/models` sin cabecera | **401** |
| `POST http://127.0.0.1:9292/v1/chat/completions` sin cabecera | **401** |
| `LOCAL_DELEGATE_API_KEY` en el entorno del agente | no está (solo `AUTOSTART`, `MAX_CONCURRENT_REQUESTS`, `WEB_TOKEN`) |

El llama-swap exige la clave que pone el lanzador del daemon. Por la decisión 5 de §11 («si la pide,
se para y se pregunta antes de planificar ningún reinicio del daemon») la muestra **no se corrió**:
no se escribió arnés (no hay sha256 que anotar) y `evidence/B2/lang-sample.json` queda con
`status: blocked`, el motivo y las combinaciones previstas, sin respuestas.

Vías posibles (decide la sesión principal): un reinicio planificado del daemon por combinación
(`LOCAL_DELEGATE_LANG` + `LOCAL_DELEGATE_OUTPUT_LANGUAGE` en su lanzador, y `/mcp` después), o que el
arnés corra como tarea del lanzador para heredar la clave sin verla.

## 2. `local_commit_msg` vía el MCP vivo: CUMPLE

Diffs volcados al scratchpad y pasados con `path`:

| Diff | Commits | Bytes | sha256 |
|---|---|---:|---|
| B0a | `git diff a5c150e 5660228` | 158 784 | `ef8f5fe338ea7b9500572f56a20739f09f60c5033c40eda87686c4aee3545d20` |
| B1a | `git diff 3492ba5 2167b9d` | 269 105 | `e2d26a47ddc61e07b7509cec935467daa699cf08407ec80d59946cf066f0fb6e` |

Salida literal, B0a (13 partes en 14 pasadas, 21 archivos, 157 406 caracteres leídos enteros):

```text
feat(i18n): añade soporte bilingüe y validación de idioma

- Implementa resolución de idioma y catálogos JSON para salida en español
- Configura CI para validar la suite completa bajo entorno LANG=es_ES.UTF-8
- Añade tests de paridad i18n y aislamiento para prevenir contaminación global
- Valida variables de entorno LOCAL_DELEGATE_LANG y OUTPUT_LANGUAGE estrictamente
- Actualiza documentación técnica y excepciones de renombrado para la ola B0a

(leído server-side: 157406 chars ≈ 70903 tokens de Claude que no entraron a tu contexto)

(resumido de 13 partes en 14 pasadas por local-delegate)

(alcance: 21 archivos, 157406 chars leídos enteros)
```

Salida literal, B1a (24 partes en 27 pasadas, 41 archivos, 266 314 caracteres leídos enteros):

```text
feat(i18n): habilitar salida bilingüe en inglés y español

- Añadir recursos de traducción para argparse y CLI en inglés y español
- Actualizar la lógica de internacionalización para soportar ambos idiomas
- Modificar las pruebas de humo para validar salidas en español por defecto
- Añadir pruebas específicas para verificar la ayuda en modo inglés
- Actualizar la configuración de CI para soportar ejecuciones bilingües
- Documentar el cambio y sus evidencias en el registro de cambios

(leído server-side: 266314 chars ≈ 119961 tokens de Claude que no entraron a tu contexto)

(resumido de 24 partes en 27 pasadas por local-delegate)

(alcance: 41 archivos, 266314 chars leídos enteros)
```

Veredicto (detector `scripts/detect_language.py`, `min_tokens=20`, margen 0,15, sobre el mensaje sin
los recibos):

| Diff | Idioma | Tokens | es_ratio | en_ratio | Viñetas | Cumple |
|---|---|---:|---:|---:|---:|---|
| B0a | es | 69 | 0,2899 | 0,0290 | 5 | sí |
| B1a | es | 73 | 0,3836 | 0,0137 | 6 | sí |

Nota de calidad (no es criterio): el asunto de B1a usa infinitivo y el de B0a presente; los dos
describen el lote de forma general pero correcta.

## 3. `local_explain_code` sobre `cli.py` vía el MCP vivo: NO CUMPLE

`src/local_delegate/cli.py`: 60 632 bytes (58 875 caracteres leídos), sha256
`b33822ff7c8be5ad8fff1620f432c3a860bdf173ab48b88b3bfd9f1154e5b327`. Pregunta: «Enumera todos los
subcomandos de la CLI que define este fichero, con una línea por subcomando que diga para qué sirve.»

Salida literal (4 partes en 5 pasadas):

```text
El código define una CLI para gestionar la configuración, instalación y monitoreo de servicios MCP y LlamaSwap. Los subcomandos principales son:

- `serve`: Arranca el daemon singleton MCP HTTP y su dashboard de monitoreo.
- `update`: Ejecuta la actualización del sistema, gestionando las dependencias y la configuración existente.
- `install`: Realiza la instalación del software, configurando clientes y componentes según las opciones especificadas.
- `uninstall`: Ejecuta la lógica de desinstalación, limpiando configuraciones y archivos asociados.
- `recompute-cost`: Calcula y reescribe los costes de API y cuotas, permitiendo resetear calibraciones.
- `test-window`: Gestiona ventanas de tiempo para pruebas, permitiendo iniciar, parar, añadir o listar ventanas de uso.
- `check-llamaswap`: Valida la configuración de LlamaSwap, verificando que los presupuestos de VRAM y RAM estimados se ajusten a los límites disponibles.
- `init-llamaswap`: Genera o actualiza el archivo de configuración inicial para LlamaSwap, validando modelos y grupos antes de escribir.
- `llamaswap-residency`: Modifica la configuración de residencia de modelos en LlamaSwap, permitiendo fijar, restaurar o ajustar el TTL, con gestión de vigilancia y recuperación ante errores.

Además, el sistema incluye utilidades internas para resolver clientes, manejar el daemon, calcular presupuestos y gestionar la internacionalización de los mensajes de ayuda.

(leído server-side: 58875 chars ≈ 29002 tokens de Claude que no entraron a tu contexto)

(resumido de 4 partes en 5 pasadas por local-delegate)
```

| Criterio | Resultado |
|---|---|
| No dice que truncó la entrada | **cumple**: sin aviso de entrada truncada; leyó los 58 875 caracteres en 4 trozos |
| Menciona `llamaswap` | **cumple** (`check-llamaswap`, `init-llamaswap`, `llamaswap-residency`) |
| Menciona `doctor` | **no** |
| Menciona `benchmark` | **no** |

Diagnóstico (sin tocar código ni prompts):

- Lo arreglado en B2c se ve: la 0.35.0 truncaba a 20 000 y no nombraba ni `llamaswap`; ahora la
  entrada llega entera y aparecen 9 subcomandos.
- Los dos que faltan están en `build_parser()` (`cli.py:1208`–`1400`): `doctor` en
  `cli.py:1343` (`sub.add_parser("doctor", …)`) y `benchmark` registrado de forma indirecta en
  `cli.py:1231` (`benchmark.add_parser(sub)`: el literal `"benchmark"` vive en otro módulo). En la
  misma función están `serve` (`cli.py:1364`) y `recompute-cost` (`cli.py:1378`), que **sí** salen; y
  `llamaswap` (el padre de `llamaswap residency`, `cli.py:1146`) sale solo como sus hijos.
- Por tanto no es pérdida de entrada sino de **contenido en el map-reduce**: el paso map del trozo con
  `build_parser` o el reduce los omiten. El inventario de nombres del paso final (B2c §4.2) lista
  `def`/`class` de primer nivel (`build_parser`, `_add_install_parsers`…), no los subcomandos que
  registran, así que no puede rescatarlos. `benchmark` es además difícil por construcción: el fichero
  no contiene el nombre del subcomando, solo la llamada al módulo.
- `check-llamaswap` (`cli.py:1233`) también está en `build_parser()` y sí sale: el trozo de esa
  función llegó al modelo y la omisión es selectiva, no de un trozo entero.
- No se repitió la llamada: la RAM estaba al límite (< 2 GB libres) y una repetición suelta no
  decide si la omisión es estable; queda para la sesión principal.
- Para separar map de reduce haría falta ver las salidas parciales de cada trozo, que hoy no se
  registran.

## Tanda 1: idioma de respuesta con producto `es` y `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en`

Ventana de prueba: **`w-20261014T221424Z`** (`--label "B2d idioma tanda 1 (es + output en)"`),
2026-10-14T22:14:24.349Z a 22:19:21.727Z, cerrada con `stop`; 20 filas, una por llamada.
`local_status` al empezar: «Idioma: es (sistema…)» e «Idioma de respuesta del modelo: en (variable
de salida)»; RAM 14,2 / 31,1 GiB. El daemon no se reinició ni se tocó su configuración.

Método: cada tool llamada **a través del MCP vivo** (el daemon tiene la clave del backend) con
`path=<documento>`. Los 20 documentos (y los 20 de la tanda 2) se congelaron antes de la primera
llamada en `lang-sample-docs.json`, con regla escrita y sha256; los de esta tanda están en español.
`local_explain_code` con la pregunta fija «¿Qué hace este fichero y cuáles son sus partes
principales?» (en el idioma de los documentos, para que no ayude). Juez: `scripts/detect_language.py`
`detect(min_tokens=20, min_margin=0.15)` sobre la respuesta sin las líneas de envoltorio del producto
(«(leído server-side: …)», «[local-delegate warning: …]», «(sin resumir)»), que van en el idioma del
producto por diseño. Respuestas literales y veredictos: `evidence/B2/lang-sample.json`.

| Tool | Juzgables | En inglés | % | ≥ 90 % |
|---|---:|---:|---:|---|
| `local_summarize` | 5 | 4 | 80 | no |
| `local_lint_summary` | 5 | 3 | 60 | no |
| `local_explain_code` | 5 | 5 | 100 | sí |
| `local_describe_image` | 5 | 5 | 100 | sí |
| **Total** | **20** | **17** | **85** | **no** |

No juzgables (< 20 tokens): ninguna. Respuestas en español: **ninguna**. Los tres fallos son
`unknown` del detector por margen (< 0,15), todos con `en_ratio` > `es_ratio`:

| Tool | Documento | Tokens | es | en | Margen |
|---|---|---:|---:|---:|---:|
| `local_summarize` | `docs/wiki/Backend-versions.md` | 201 | 0,0448 | 0,1841 | 0,1393 |
| `local_lint_summary` | `evidence/A5c/mutants.txt` | 60 | 0,0167 | 0,05 | 0,0333 |
| `local_lint_summary` | `evidence/A7b/mutants.txt` | 91 | 0 | 0,1429 | 0,1429 |

Texto de cada fallo (juzgado, sin el recibo):

- `Backend-versions.md`: el cuerpo está en inglés, pero arrastra títulos y una negrita copiados del
  documento en español: «## Introduction / `local-delegate` is a generic client for
  OpenAI-compatible endpoints that does not fix versions. / ## Introducción / ## Versiones probadas /
  **Qué se usa de llama-swap v255 y de llama-server**: **llama-swap v255** provides turn and
  affinity logic via `config.yaml`, … / ## Workspace de referencia / Everything is contained under a
  single root directory, … / ## Chequear tu instalación: `local-delegate doctor` / Detects installed
  versions and suggests updates. … / ## Medir un canary: `local-delegate benchmark` / Runs real tasks
  against a candidate backend … / ## Métricas persistentes del backend (#898) / **llama-swap** can
  persist activity metrics in SQLite …».
- `A5c/mutants.txt`: inglés telegráfico en viñetas, casi sin palabras funcionales: «**Linting &
  Testing Summary** / **1. prices.json & Vigilante (5 Errors)** / Key inconsistencies:
  `"claude-opus-5-5"` vs. `"entrada"` (2 errors) / KeyError: `'input'` in `vigilante_precios.py`
  (2 errors) – impacting table comparisons. / Restoration successful. / **2. Family Labels (1
  Error)** / Key inconsistency: `FAMILIA` vs. `nueva` (1 error) / AssertionError related to family
  name mismatch. / Restoration successful. / **3. Accounting Parity (1 Error)** / JS vs. Python
  discrepancy: `e.density` (1 error) / AssertionError related to numerical comparison. /
  Restoration successful.»
- `A7b/mutants.txt`: inglés, se queda a 0,0071 del margen: «**Linting & Testing Summary** /
  **tools/make_mapping.py (1 failed):** A conditional statement error (`elif False:`) introduced a
  `ValueError` during testing, … / **tests/test_turn_daemon.py (1 failed):** Threading issues due to
  outdated arguments (`role="long"`) caused a `TypeError` and `RuntimeError`. … /
  **src/local_delegate/server.py (1 failed):** A dataclass field naming discrepancy
  (`BackendState.cause` vs. `causa`) … / **Overall:** Following restoration, 43 tests passed. …»

Lectura: con el juez y el criterio congelados, la tanda 1 **no cumple** (85 % total; `summarize` 80 %
y `lint_summary` 60 %). Ninguna respuesta salió en español; los fallos son abstenciones del juez ante
inglés telegráfico (lint) y ante títulos copiados del documento (summarize). No se ajustó ni el juez
ni el umbral a la vista de los resultados.

Hallazgo aparte, en `local_summarize` (resumen estructurado por secciones): en las 5 respuestas cada
sección sale **dos veces**, una con el título traducido al inglés y resumida y otra con el título
original en español y el marcador «(sin resumir)»; el aviso las cuenta como «N secciones sin resumir
por el límite de palabras o del modelo» (5, 1, 6, 3 y 1). Parece que el ensamblado empareja las
secciones por el título y, al traducirlo el modelo, no las reconoce. En `Backend-versions.md` y
`Remote-backend.md` el modelo además dejó títulos en español con el cuerpo en inglés. No se tocó
código ni prompts.

## Tanda 2: idioma de respuesta con producto `en` y `LOCAL_DELEGATE_OUTPUT_LANGUAGE=es`

Ventana de prueba: **`w-20261014T222250Z`** (`--label "B2d idioma tanda 2 (en + output es)"`),
2026-10-14T22:22:50.726Z a 22:31:11.095Z, cerrada con `stop`; 21 filas (20 de la muestra y 1 de
`local_commit_msg`). `local_status` al empezar: «Language: en (variable…)» y «Model response
language: es (output variable)», salida entera en inglés; RAM 14,5 / 31,1 GiB. El daemon lo reinició
la sesión principal; este agente no lo tocó.

Mismo método que la tanda 1, con los documentos ya congelados en `lang-sample-docs.json` (en inglés,
sin cambiar ninguno). Pregunta fija de `local_explain_code`: «What does this file do and what are its
main parts?». Las líneas de envoltorio que se quitan antes de juzgar son las mismas en inglés
(«(read server-side: …)», «[local-delegate warning: …]», «(not summarized)»).

| Tool | Juzgables | En español | % | ≥ 90 % |
|---|---:|---:|---:|---|
| `local_summarize` | 5 | 4 | 80 | no |
| `local_lint_summary` | 5 | 3 | 60 | no |
| `local_explain_code` | 5 | 5 | 100 | sí |
| `local_describe_image` | 5 | 5 | 100 | sí |
| **Total** | **20** | **17** | **85** | **no** |

No juzgables (< 20 tokens): ninguna. Respuestas en inglés: **ninguna**. Los tres fallos vuelven a ser
`unknown` por margen, todos con `es_ratio` > `en_ratio`:

| Tool | Documento | Tokens | es | en | Margen |
|---|---|---:|---:|---:|---:|
| `local_summarize` | `cfgv-3.5.0.dist-info/METADATA` | 273 | 0,1062 | 0,044 | 0,0622 |
| `local_lint_summary` | `resume-ruff-cinco-reglas.txt` | 52 | 0,1731 | 0,0962 | 0,0769 |
| `local_lint_summary` | `lint-9k.txt` | 120 | 0,125 | 0 | 0,125 |

Texto de cada fallo (juzgado, sin el recibo):

- `cfgv` METADATA: español, pero casi todo son firmas de la API citadas del documento: «## Introduction
  / Valida configuraciones y produce mensajes de error legibles para humanos. / … / ## API /
  **`cfgv.validate(value, schema)`** Valida un esquema. **`cfgv.apply_defaults(value, schema)`** Aplica
  valores por defecto. … / ## Validator objects / **writing your own validator** Permite crear
  validadores personalizados. **`Required(key, check_fn)`** Asegura presencia de clave. … /
  **`Conditional(key, check_fn, condition_key, condition_value, ensure_absent=False)`** Validación
  condicional. … / ## Check functions / **`check_any(_)`** No hace nada. …».
- `resume-ruff-cinco-reglas.txt`: español telegráfico: «**Resumen de Problemas:** / **lib/io.py:** 2
  problemas. / I001: Importación desordenada (2) / UP006: Uso incorrecto de anotaciones de tipo (3) /
  **lib/net.py:** 3 problemas. / SIM102: Múltiples `if` statements (3) / RET504: Asignación
  innecesaria antes de `return` (1) / **lib/db.py:** 3 problemas. / …».
- `lint-9k.txt`: español en viñetas de recuento: «**Resumen de errores por archivo:** /
  **src/local_delegate/benchmark.py** (Más relevante) / **Docstrings (D):** 31 (Faltan en clases,
  métodos, funciones y `__init__`). / **Formato/Estilo (COM, E, T, RUF):** 16 (Comas faltantes, líneas
  largas, uso de `print`, orden de `None`). / … / **Totales destacados:** / **D (Docstrings):** 33 /
  **COM (Comas):** 13 / …».

### Las dos tandas juntas

| Tool | Juzgables | En el idioma pedido | % | ≥ 90 % |
|---|---:|---:|---:|---|
| `local_summarize` | 10 | 8 | 80 | no |
| `local_lint_summary` | 10 | 6 | 60 | no |
| `local_explain_code` | 10 | 10 | 100 | sí |
| `local_describe_image` | 10 | 10 | 100 | sí |
| **Total** | **40** | **34** | **85** | **no** |

Con el juez y el criterio congelados, REQ-028 **no cumple** en `local_summarize` ni en
`local_lint_summary`. En las 40 respuestas no hay **ninguna** en el idioma contrario al pedido: los 6
fallos son abstenciones del detector (margen < 0,15) con la proporción mayor del idioma pedido, en
textos telegráficos (lint) o cargados de identificadores y títulos citados del documento
(summarize). No se ajustó el juez ni el umbral.

### Secciones duplicadas de `local_summarize`

**No se repite** en la tanda 2: en las 5 respuestas el modelo dejó los títulos en inglés, como en el
original, y no aparece ninguna sección doble ni ningún «(not summarized)». Refuerza la hipótesis de la
tanda 1: la duplicación sale cuando el modelo **traduce** el título y el ensamblado ya no lo empareja.
Aquí no tradujo los títulos (inglés → español), así que la prueba no la provoca. Detalle aparte: la
respuesta de `annotated_doc` trae el aviso «1 section not summarized…» sin que se vea ninguna sección
con el marcador.

### `local_commit_msg` con producto `en` y variable `es`

Una llamada sobre el mismo diff de B1a de la §2 (`git diff 3492ba5 2167b9d`, sha256
`e2d26a47…6fb6e`). Salida literal:

```text
feat(i18n): add English CLI output and bilingual test suite

- Introduce English translations for argparse and CLI messages
- Add smoke tests to verify English output and base functionality
- Update existing tests to expect default Spanish strings
- Ensure i18n integration does not break original English behavior
- Add configuration for bilingual output in CI and local environments

(read server-side: 266314 chars ≈ 119961 Claude tokens that did not enter your context)

(summarized from 24 parts in 27 passes by local-delegate)

(scope: 41 files, 266314 chars read in full)
```

Detector sobre el mensaje sin recibos: `en`, 57 tokens, es 0, en 0,2281. Cuerpo de 5 viñetas.
**Cumple**: sale en el idioma del producto (inglés) y `LOCAL_DELEGATE_OUTPUT_LANGUAGE=es` no le afecta.
