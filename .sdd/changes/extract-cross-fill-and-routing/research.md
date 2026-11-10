# Research: local_extract: aviso de valor cruzado entre claves y subida al rol long en tablas (#586)

Medido el 2026-11-10 entre las 09:12 y las 09:24 (hora de Uruguay) contra el backend real, con el
daemon 0.50.0, dentro de la ventana de prueba `w-20261110T121214Z` (`sdd-586-research`, cerrada).
Las dos llamadas de la sección del #630 fueron entre las 09:36 y las 09:40, en una segunda ventana
con la misma etiqueta, `w-20261110T123643Z` (cerrada).
Todo lo de esta carpeta usa datos inventados. Nada de `src/` se tocó.

## Resumen para decidir

- **El cruce es de las tablas y del modelo pequeño.** `gemma3-4b` cruzó 9 claves de 113 en 8 de 22
  casos; los 8 son tablas (8 de 16 casos con tabla, 0 de 6 sin tabla). `gemma4-26b-a4b` cruzó 0 de
  130 claves en 26 corridas, incluidas las mismas tablas y dos páginas de 6,6 KB y 29 KB.
- **Propuesta B (subir a `long`)**: la regla que separa es **«la entrada tiene una tabla»**, sin
  N. Dispara en 16 de 22 casos, cubre los 8 casos que cruzan (9 de 9 claves) y sube 8 de 14 casos
  limpios. Las palabras en común entre campos no separan: N ≥ 2 deja fuera 2 de 8 casos que
  cruzan y N ≥ 3 deja fuera 4.
- **Propuesta A (aviso `cross_filled_keys`)**: la variante de la propuesta («estricta») da
  **0 falsos positivos en 282 claves sin cruce** y acierta 4 de los 9 cruces reales (44 %). No ve
  el cruce desde una fila que nadie pidió (la forma de la evidencia de 33 KB), ni una clave ausente
  que comparte palabras con la fila de la que roba, ni la tabla traspuesta. Las dos variantes más
  amplias cazan más pero avisan en falso 19 y 22 veces.
- **Recomendación**: las dos. B con la regla de la tabla como arreglo, A estricta como aviso (sin
  poner null), documentada como parcial. Detalle y riesgos al final.

## Current behavior

- `local_extract` elige el rol solo por tamaño: `probe_len` son los bytes del fichero (con `path`)
  o los caracteres del texto, y `_role_for_size` devuelve `long` por encima de
  `LOCAL_DELEGATE_LONG_INPUT_CHARS` (6000) y `mechanical` si no
  (`src/local_delegate/server.py:7971-7973`, `:5213-5220`, `src/local_delegate/config.py:316`).
- La petición: `system = _guard("un objeto JSON válido con exactamente estas claves: {…}")`
  (`server.py:7977-7978`, `:6480-6485`), usuario `"Extrae los campos del siguiente
  contenido:\n\n" + contenido` (`:7995-7997`), `max_tokens=512`, `temperature=0.0`, y
  `response_format` con un schema que restringe cada clave a un primitivo
  (`:7988-7989`, `:6025-6041`).
- El post-proceso no mueve valores entre claves: normaliza nombres (`_normalize_extract_keys`,
  `:7588`), pasa a null los marcadores de «sin dato» (`_null_placeholders`, `:7683`, lista en
  `:7630-7670`), recuenta listas de un JSON (`_recount_lists`, `:7718`) y recorta copias del
  esquema (`:8158-8182`). No hay nada que compare un valor con la fila de la fuente de donde sale.
- Reproducido hoy por el producto, sin tocar nada: con la tabla reducida del #586 (949
  caracteres) `licensed_user_limits` vuelve con «1–5 (Standard), 1–3 per region (Enterprise)», que
  es la fila «Custom domains», sin `missing_keys` ni `warning` (`outputs/g3-extract.json`, caso 01).

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| Elección del rol de `local_extract` | `_role_for_size(probe_len)` por tamaño | B: decidir el rol con una regla propia de extract. `_role_for_size` la comparten cuatro tools (summarize, extract, lint, translate): no se cambia, se envuelve | `src/local_delegate/server.py:5213-5220`; llamadas en `:7400`, `:7973`, `:8398`, `:8682` |
| Umbral de tamaño | `LONG_INPUT_CHARS = 6000` | Ninguno: B no mueve el umbral | `src/local_delegate/config.py:316`; topes por rol en `:341-345` |
| Montaje de `_local_delegate` | `meta` con `missing_keys`, `renamed_keys`, `dropped_keys`/`dropped`, `placeholder_keys`, `recounted_keys`, `outline_copies`, `lines_unverified`, `chunked`, `read_server_side`, `fallback` | A: clave nueva `cross_filled_keys` y un aviso añadido en `late_notices` (el aviso anterior conserva su texto exacto, contrato del #455) | `src/local_delegate/server.py:8183-8255`; constante `_EXTRACT_META_KEY` en `:7580` |
| Normalización previa | claves, marcadores, recuento, prefijos de línea | A corre después de `_null_placeholders` y de quitar prefijos (`_strip_extract_prefixes`), sobre `content` entero aunque la entrada se trocee | `:8141-8156`, `:8166-8182`, `:7830` |
| Descripción de la tool (docstring) | describe el enrutado «mechanical (short inputs) or long-context» y cada clave de `_local_delegate` | A y B: añadir la clave nueva y la regla de la tabla | `src/local_delegate/server.py:7926-7961` |
| Textos de aviso es/en | `mcp.warning.extract_*` (9 claves por idioma) | A: una clave nueva en los dos idiomas (paridad exigida por test) | `src/local_delegate/resources/i18n/es/mcp.json:210-218`, `…/en/mcp.json:210-218` |
| Wiki | sección `local_extract`, tabla de tools («mecánico / largo (auto)»), enrutado por tamaño | A: `docs/wiki/Tools.md:122-151`. B: `docs/wiki/Tools.md:24`, `docs/wiki/Configuration.md:43` y `:461`, `docs/wiki/Architecture.md:37-41` | rutas citadas |
| README | fila de la tool, variable del umbral, párrafo del troceado | B: `README.md:170` y `:262`; A: solo si se quiere nombrar la clave (hoy el README no lista las claves de `_local_delegate`, salvo `chunked` en `:231-233`) | rutas citadas |
| Recetas | tabla que dice `local_extract` → «mecánico» | B: ya es inexacta hoy; corregir | `docs/recipes/claude-code-integration.md:61` |
| Skill y memoria instaladas | fila de `local_extract` sin rol ni claves | Ninguno salvo que se quiera avisar del aviso nuevo | `src/local_delegate/resources/skills/local-delegation/SKILL.md:38`, `SKILL.en.md:38`; `resources/memory/local-delegate.md:17-20` |
| Espejo del enrutado en los hooks | `LONG_THRESHOLD_CHARS = 6000` y el modelo «al que iría `local_summarize`» | Ninguno: solo modela summarize | `src/local_delegate/resources/hooks/hook_common.py:739`, `:998-1004` |
| Panel y mod (JS) | nombran la tool, no su rol ni sus claves de metadatos | Ninguno: ningún `.js`/`.ts` ni `web/metrics.py` trae el umbral ni las claves (búsqueda de `6000`, `LONG_`, y de las siete claves: 0 coincidencias fuera de tests de reloj) | `git grep` del 2026-11-10 |
| Log de uso | `role`/`model` por fila, `concurrency.model_swap`, `wait_ms`, `turn_wait_ms` | B: más filas de extract con `gemma4-26b-a4b` y más cambios de modelo; A: nada (la clave no va al log) | campos vistos en `usage-202611.jsonl` (solo nombres) |

Superficies contadas con `git grep` (no a ojo): las siete claves de metadatos aparecen en 5
ficheros que no son tests (`CHANGELOG.md` 8, `docs/wiki/Tools.md` 8, `i18n/en/mcp.json` 8,
`i18n/es/mcp.json` 8, `server.py` 38) y en 5 de tests (`test_extract_placeholder_values.py` 25,
`test_extract_normalize_keys.py` 16, `test_extract_line_numbers.py` 7,
`test_extract_field_fidelity.py` 4, `test_explain_code_verified_lines.py` 4). `local_extract` se
nombra en 86 ficheros versionados fuera de `.sdd` y `benchmarks` (26 en `src/`, 5 en `docs/wiki`,
2 en `docs/recipes`, el resto tests, README y CHANGELOG).

### Tests existentes de estas piezas

| Pieza | Test | Qué pasaría |
| --- | --- | --- |
| Enrutado por tamaño de extract | `tests/test_core.py:174-196` (texto `"corto"` y `"x" * 6001`, sin tabla) | Siguen pasando con B; faltan los de la regla nueva |
| Cuerpos congelados de la petición | `tests/test_request_body_compat.py` con `tests/fixtures/request_bodies/extract_schema.json` y `extract_schema_retry.json` | Sin tabla en la entrada (0 coincidencias de `<tr`, `<table` y `\|---`): B no cambia el modelo del cuerpo; A no toca la petición |
| Corpus congelado | `tests/test_corpus.py:179-181`, `:869`, `:914`; casos en `scripts/build_corpus.py:380-390` (`extraer-toml-2k`, rol declarado `mechanical`) y `:2048` (8 casos en línea, sin tabla) | **A comprobar en el plan**: si la fuente congelada de `extraer-toml-2k` trae una tabla Markdown, B cambiaría su rol y habría que declararlo |
| Claves y avisos de `_local_delegate` | `tests/test_extract_normalize_keys.py`, `test_extract_placeholder_values.py`, `test_extract_field_fidelity.py`, `test_extract_line_numbers.py`, `test_extract_chunked_nulls.py` | A añade una clave y un aviso al final: los asserts de igualdad exacta de `_local_delegate` en entradas con filas etiquetadas podrían cambiar; con el detector estricto no debería saltar en ninguno (sus entradas no cruzan), pero hay que correr la suite |
| Contrato y textos | `tests/test_tool_contract.py:161-171`, `tests/test_mcp_english.py:103`, `tests/test_i18n_parity.py` | A: docstring en inglés y clave i18n en los dos idiomas |
| Topes por rol y respaldo | `tests/test_role_caps.py:84`, `tests/test_fallback.py:147`, `:554` | B: con rol `long` el respaldo es otro (`long` → `qwen36-35b-a3b`; `mechanical` → `gemma4-26b-a4b`) |

## Conjunto de medición

`cases/cases.json`: 26 casos sobre 17 ficheros, 130 claves, cada una con su respuesta anotada a
mano, la fila de la que sale (`own`) y las celdas distintivas de cada fila (`rows`), que es lo que
permite llamar «cruce» a un error.

| Origen | Casos |
| --- | --- |
| `extract-prompt-sin-relleno` (las 7 entradas de la prueba en vivo del 2026-11-09) | 01 tabla HTML del #586 (el fichero inventado de entonces, tal cual), 03 JSON de un PR, 04 log de pytest, 05 booleanos por ausencia, 18 fichero de código; los ficheros del repo de aquella prueba se sustituyeron por otros inventados |
| `extract-placeholder-values` (comentario del #586 del 2026-11-04) | 03 (`comments: []`, `reviews: []`, marcadores) |
| Issue #586, evidencia de 33 KB | 02 (los tres campos de la evidencia sobre la tabla reducida), 15 (página de 6,6 KB), 19 y 20 (página de 29 KB con el ruido de marcado de un sitio real, generada por `cases/build_noisy_page.py`) |
| `extract-fidelidad-campos` | Ninguno: sus casos son de campos de línea y esquema de títulos, que no tocan el cruce ni el rol |
| Nuevos, tablas | 06 y 16 (Markdown, es, claves con palabras compartidas; 16 es la misma tabla dentro de un manual de 6,1 KB), 07 (Markdown, en, una columna), 08 (HTML, es, sinónimos), 09 (Markdown, en, sinónimos), 12 (HTML, valores repetidos entre filas), 17 (HTML traspuesta) |
| Nuevos, clave ausente casi igual a una fila | 21 a 26, sobre las tablas de 01, 06, 08, 09, 07 y 17 |
| Controles negativos (tabla sin cruce posible) | 10 (HTML, en) y 11 (Markdown, es): cada clave es la etiqueta de una fila y todas están |
| Sin tabla | 03, 04, 05, 13 (prosa en español), 14 (líneas `clave = valor`), 18 |

## Medición en vivo

Mecanismo para forzar el modelo sin tocar el producto:

- `gemma3-4b`: **`local_extract` real por `path`** (entradas de menos de 6000 bytes; el producto
  las manda solas a `mechanical`). 22 casos.
- `gemma4-26b-a4b` en entradas grandes: **`local_extract` real por `path`** (15, 16, 19, 20; pasan
  de 6000 bytes y van solas a `long`).
- `gemma4-26b-a4b` en las entradas pequeñas: **`local_delegate(model="gemma4-26b-a4b",
  chunk="off")`** con `task="Extrae los campos del siguiente contenido:"` y `output_format` igual
  al de extract, de modo que el `system` es idéntico byte a byte. Diferencias con el producto: una
  línea `Input:` antes del contenido, sin schema, `temperature` 0,2 en vez de 0, `max_tokens`
  2048 en vez de 512 y sin post-proceso (al puntuar se aplicó la misma lista de marcadores).
- Validación del sustituto: los mismos 10 casos con `gemma3-4b` por las dos vías coinciden en el
  veredicto de 49 de 51 claves y en los tres cruces de las tablas 01, 02 y 06. Difieren en
  `closes_issue` del caso 03 (`false` frente a «N/A») y en `ip_allowlist` del caso 12 («Not
  mentioned», que el producto pasaría a null, frente a «Not included»).
- Cada par (entrada, campos, vía) se llamó una vez: con temperatura 0 y semilla fija repetir no
  mide ruido.

| Modelo y vía | Casos | Claves | Acertadas | Cruzadas | Inventadas | Casos con cruce | Inferencia (mediana, mín–máx) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `gemma3-4b`, `local_extract` real | 22 | 113 | 102 (90,3 %) | 9 (8,0 %) | 2 | 8 | 0,84 s (0,41–2,01) |
| `gemma3-4b`, sustituto | 10 | 51 | 45 | 3 | 3 | 3 | 0,85 s (0,38–1,16) |
| `gemma4-26b-a4b`, sustituto (entradas pequeñas) | 22 | 113 | 112 (99,1 %) | 0 | 1 | 0 | 3,24 s (1,55–8,93) |
| `gemma4-26b-a4b`, `local_extract` real (6–29 KB) | 4 | 17 | 17 | 0 | 0 | 0 | 13,0 s (5,97–26,1) |

Por caso con `gemma3-4b` real (detalle clave a clave en `outputs/evaluation.json`):

| Caso | Tabla | Claves | Acertadas | Cruzadas | Qué cruzó |
| --- | --- | --- | --- | --- | --- |
| 01 tabla de precios, 5 campos | sí | 5 | 4 | 1 | `licensed_user_limits` ← fila «Custom domains» (clave pedida) |
| 02 tabla de precios, 3 campos | sí | 3 | 1 | 1 | `licensed_user_limits` ← «Custom domains» (fila que nadie pidió); además `plans_with_monthly_price` = «Standard, Enterprise» (inventado) |
| 06 límites, es | sí | 5 | 4 | 1 | `limite_usuarios_con_licencia` ← «Límite de usuarios activos» |
| 12 valores repetidos | sí | 5 | 4 | 1 | `ip_allowlist` ← «Not included» de las filas vecinas |
| 21 claves casi iguales, en | sí | 5 | 3 | 2 | `storage_per_user` ← «Storage per workspace»; `api_requests_per_day` ← «API requests per minute» |
| 22 claves casi iguales, es | sí | 5 | 4 | 1 | `almacenamiento_por_usuario` ← «Almacenamiento por proyecto» |
| 23 claves casi iguales, es | sí | 5 | 4 | 1 | `puestos_adicionales` ← segunda columna de «Puestos incluidos» |
| 26 traspuesta, plan inexistente | sí | 6 | 5 | 1 | `enterprise_seats` ← puestos del plan «Factory» |
| 07, 08, 09, 10, 11, 17, 24, 25 | sí | 44 | 44 | 0 | — |
| 03, 04, 13, 14, 18 | no | 27 | 27 | 0 | — |
| 05 booleanos | no | 3 | 2 | 0 | `body_language` = `false` (falla igual con `gemma4-26b-a4b`; no es un cruce) |

Con `gemma4-26b-a4b`, los mismos 22 casos pequeños salen sin ningún cruce (única clave fallada:
`body_language` = `false`), y las cuatro entradas grandes por el producto, 17 de 17.

Lo que **no** se pudo reproducir: el cruce con el rol `long` de la evidencia de 33 KB del issue.
Con datos inventados (páginas de 6,6 KB y 29 KB, esta con ruido de marcado, con los tres campos
originales y con cinco) `gemma4-26b-a4b` dio null en `licensed_user_limits` las cuatro veces.
«`gemma4-26b-a4b` lo reduce pero no lo elimina» sigue apoyado solo en aquella llamada.

Dos observaciones al margen: con el schema, `gemma3-4b` devuelve números sin unidad (`25` por
«25 GB», `5` por «5 TB»; contados como acierto y anotados); y sin schema `gemma4-26b-a4b` anida
objetos por plan, que el schema del producto no permite.

## Detector A (prototipo)

`detector.py` (suelto, fuera de `src/`), corrido por `evaluate.py` sobre las salidas reales de
`outputs/`. Saca las filas etiquetadas de la fuente (tablas HTML con `html.parser`, tablas
Markdown, líneas `etiqueta: valor` y claves de primer nivel de un JSON), mira en qué filas aparece
literal el valor de cada clave y compara cuántas palabras comparte la etiqueta con la clave y con
las demás claves pedidas. Tres variantes:

- **Estricta** (la propuesta): el valor solo aparece en filas cuya etiqueta casa mejor con otra
  clave pedida, y en ninguna donde la clave propia sea la que mejor casa.
- **Amplia**: además, el valor solo aparece en filas cuya etiqueta no comparte palabra con la
  clave, aunque nadie haya pedido esa fila.
- **Parcial**: la estricta, más las filas que casan con la clave solo en parte por los dos lados.

| Variante | Sobre qué | VP | FP | FN | Claves sin cruce |
| --- | --- | --- | --- | --- | --- |
| Estricta | `gemma3-4b` real | 4 | 0 | 5 | 104 |
| Estricta | `gemma4-26b-a4b` real | 0 | 0 | 0 | 17 |
| Estricta | las cuatro corridas | 6 | **0** | 6 | 282 |
| Amplia | las cuatro corridas | 8 | 19 | 4 | 282 |
| Parcial | las cuatro corridas | 10 | 22 | 2 | 282 |

Casos concretos de la estricta sobre las salidas del producto:

- **Verdaderos positivos (4)**: 01 `licensed_user_limits`, 06 `limite_usuarios_con_licencia`,
  12 `ip_allowlist`, 23 `puestos_adicionales`.
- **Falsos negativos (5)**: 02 `licensed_user_limits` (la fila «Custom domains» no es de ninguna
  clave pedida: es la forma de la evidencia de 33 KB); 21 `storage_per_user` y
  `api_requests_per_day`, 22 `almacenamiento_por_usuario` (la clave ausente comparte palabras con
  la fila de la que roba y ninguna otra clave la reclama); 26 `enterprise_seats` (empate en la
  tabla traspuesta).
- **Falsos positivos (0)**. La primera corrida dio uno: `closes_issue` = «#412» en el JSON del PR,
  porque el valor es un trozo del campo `body` y `body_summary` casa con `body`. Se añadió una
  guarda (una celda de más de 60 caracteres es prosa, no el valor de una fila; un trozo de ella no
  cuenta) y quedó en cero. **La guarda se ajustó mirando este mismo conjunto**: hace falta
  validarla con casos nuevos antes de darla por buena. Sin ella: VP 6, FP 1, FN 6.
- Falsos positivos de las otras dos: la amplia avisa en los sinónimos (`sso_availability` frente a
  «Single sign-on (SAML)», cuatro claves del caso 08, `licensed_user_limits` frente a «Seats»); la
  parcial, en las abreviaturas (`storage_quota` frente a «Disk quota», `sla_soporte`,
  `self_hosted_options` frente a «Self-hosted runner»).

Controles:

- **Negativo** (debe dar cero): sobre las 282 claves sin cruce, incluidos los casos 10 y 11 y las
  130 claves de `gemma4-26b-a4b`, la estricta marca 0.
- **Positivo** (prueba que puede dar otra cosa): además de los 6 VP sobre salidas reales,
  `evaluate.py` intercambia entre sí dos valores correctos de filas distintas y exige que marque
  los dos. De 308 claves intercambiadas (154 pares) la estricta marca 238 (77 %), la amplia 281 y
  la parcial 243. Lo que la estricta no marca son sinónimos (casos 08 y 09: 39), prosa sin líneas
  etiquetadas (caso 13: 12), valores repetidos (caso 12: 6) y el resto sueltos.

## Regla B

Sobre los 22 casos pequeños medidos con `gemma3-4b` por el producto (8 con cruce, 14 limpios):

| Regla | Dispara | Casos con cruce cubiertos | Claves cruzadas cubiertas | Casos limpios que sube | Deja fuera |
| --- | --- | --- | --- | --- | --- |
| **tabla (HTML o Markdown)** | 16 | **8 de 8** | 9 de 9 | 8 de 14 | — |
| tabla y ≥ 5 campos | 13 | 7 de 8 | 8 de 9 | 6 de 14 | 02 |
| tabla y ≥ 2 campos con palabras en común | 11 | 6 de 8 | 7 de 9 | 5 de 14 | 02, 12 |
| ≥ 2 campos con palabras en común | 16 | 6 de 8 | 7 de 9 | 10 de 14 | 02, 12 |
| ≥ 3 campos con palabras en común | 9 | 4 de 8 | 4 de 9 | 5 de 14 | 01, 02, 12, 21 |
| ≥ 4 campos con palabras en común | 8 | 4 de 8 | 4 de 9 | 4 de 14 | 01, 02, 12, 21 |
| tabla o ≥ 3 campos con palabras en común | 18 | 8 de 8 | 9 de 9 | 10 de 14 | — |

«Tabla» = la fuente trae `<table`/`<tr`, o una línea con dos o más `|` seguida de una línea
separadora (`|---|`). «Campos con palabras en común» = campos que comparten al menos una palabra
de contenido con otro campo pedido (sin artículos ni preposiciones, plural quitado).

- La tabla sola separa mejor que cualquier N. Los campos con palabras en común no predicen el
  cruce: el caso 02 cruza con tres campos sin ninguna palabra en común y el 14 (siete campos, los
  siete con palabras en común, sin tabla) no cruza.
- Con la regla de la tabla, los 16 casos pasarían a `gemma4-26b-a4b`, que los contestó sin ningún
  cruce (por el sustituto): 9 de 9 cruces menos en este conjunto.
- No medido aquí: un solo campo pedido. La investigación del 2026-11-09 anotó en el issue que
  «con un solo campo pedido, contesta bien»; si se confirma, exigir dos o más campos ahorra subidas.

### Cuántas llamadas históricas habrían cambiado de rol

Solo con metadatos del log de uso (tool, tamaño, origen, extensión del `path`); no se abrió
ningún fichero del usuario ni se imprimió ninguna ruta. Fuera de las 258 ventanas de prueba, del
2026-07-18 al 2026-11-10:

- 76 llamadas a `local_extract`: 48 ya iban a `long` por tamaño y 28 a `mechanical`.
- De esas 28: 7 por `path` con extensión `.md` (pueden traer tabla), 10 con texto en línea (no se
  sabe), 11 con `.txt`, `.toml` o `.json` (no traen tabla HTML ni, en la práctica, Markdown) y
  ninguna `.html`.
- La regla de la tabla habría cambiado de rol **entre 0 y 17 llamadas en casi cuatro meses** (como
  mucho el 22 % de las llamadas a extract). El número exacto exige leer el contenido, y no se
  hizo. El log no guarda cuántos campos se pidieron, así que una regla por campos no se puede
  estimar.
- Aviso: 61 de las 137 filas de extract del log caen en ventanas de prueba; el uso real es poco
  y el de esta PC está sesgado por el propio repo.

### Coste de cambiar de modelo en una PC compartida de 32 GB

Los modelos de texto están en un grupo `swap`: cargar uno descarga el otro.

| Dato | Valor | De dónde |
| --- | --- | --- |
| Carga de `gemma4-26b-a4b` (espera sin el turno) | 10,4 s, 10,8 s, 10,9 s; 16,5 s y 21,8 s con dos llamadas a la vez | filas de la ventana con `model_swap` |
| Vuelta a `gemma3-4b` | 4,6 s, 4,6 s, 4,8 s, 5,1 s; 10,2 s y 10,9 s la primera vez, tras `qwen36-35b-a3b` | ídem |
| Histórico, espera con cambio de modelo | `gemma4-26b-a4b` mediana 12,7 s, p90 31,9 s (115 llamadas); `gemma3-4b` mediana 4,8 s, p90 5,4 s (31) | log de julio a noviembre, solo `wait_ms` − `turn_wait_ms` |
| Inferencia de la misma entrada pequeña | 0,84 s con `gemma3-4b`, 3,24 s con `gemma4-26b-a4b` (×3,9) | tabla de la medición |
| Latencia total de una llamada pequeña que obliga a cambiar | de ~1 s a ~14 s (carga + inferencia), más ~5 s que paga la siguiente llamada mecánica al volver | suma de las filas anteriores |

Cambios de modelo que provocó **esta** medición: **6 alternancias mías** (`gemma3-4b` →
`gemma4-26b-a4b` a las 09:15:04; vuelta a las 09:20:05; ida a las 09:20:21; vuelta a las
09:20:40; ida a las 09:21:23; vuelta a las 09:22:08), cuando con las llamadas agrupadas por modelo
habría bastado una (más la vuelta). 13 de mis 58 filas llevan `model_swap`; tres de ellas
(09:12:33, 09:19:07, 09:23:13) son recargas forzadas por llamadas de otra sesión a
`qwen36-35b-a3b` intercaladas con las mías. Mientras el backend cambiaba de modelo, la Mac del
usuario, que comparte este backend, lo vio como caído (aviso del coordinador a media medición;
issue #628 abierto por lo mismo en la barra del mod). Desde ese aviso: llamadas de una en una,
5 s entre ellas y un único cambio. Mientras `gemma4-26b-a4b` estuvo cargado, dos
`local_lint_summary` de otra sesión que pedían `gemma3-4b` los contestó `gemma4-26b-a4b`.

En la segunda ventana (las dos llamadas del #630, las dos a `gemma4-26b-a4b`): la primera no
cambió de modelo, porque otra sesión ya lo tenía cargado desde las 09:36:47 (esperó 29,6 s en
cola); la segunda esperó 84,7 s el turno detrás de un `local_explain_code` de otra sesión con
`qwen36-35b-a3b` y después hubo que recargar `gemma4-26b-a4b` (una recarga, por intercalado ajeno,
no por alternancia mía).

Es el coste real de B: cada extract pequeño con tabla, en una sesión que por lo demás usa el
modelo mecánico, son dos cambios de modelo (~15 s de espera repartidos entre esa llamada y la
siguiente) y dos tramos en los que los demás clientes ven el backend «arrancando».

## Recomendación

| Opción | Qué da en este conjunto | Qué cuesta |
| --- | --- | --- |
| A sola (estricta, guarda de 60) | Avisa de 4 de los 9 cruces de `gemma3-4b`, 0 avisos en falso en 282 claves; los otros 5 siguen saliendo en silencio | Nada en latencia; código nuevo que parsea la entrada |
| B sola (tabla → `long`) | Quita los 9 cruces (0 de 113 con `gemma4-26b-a4b`) | Inferencia ×3,9 en 16 de 22 casos, 8 de ellos limpios; ~10,5 s de carga cuando el residente es `gemma3-4b`; entre 0 y 17 llamadas reales en cuatro meses |
| **Ambas** | Lo de B, y un aviso para lo que B no cubre (el rol `long`, donde el issue vio un cruce y aquí ninguno; tablas que la regla no reconoce) | Lo de las dos |

Recomiendo **ambas**, en este orden:

1. **B con la regla «la entrada tiene una tabla», solo en `local_extract`** y con dos o más campos
   pedidos (lo de un solo campo, pendiente de medir). Sin N de palabras en común: no separa. Es lo
   único medido que quita el fallo, y el volumen real es bajo (como mucho unas 17 llamadas en
   cuatro meses), así que el coste de los cambios de modelo es pequeño en absoluto aunque cada uno
   moleste.
2. **A en su variante estricta, solo aviso** (`_local_delegate.cross_filled_keys` =
   `{clave: {"row": etiqueta, "other_key": clave}}` y un texto añadido al final de `warning`), con
   la guarda de celda larga en 60 caracteres y el empate contado como fila propia. Documentada
   como red parcial: que no avise no certifica nada (acierta 4 de 9). No recomiendo la amplia ni la
   parcial: 19 y 22 avisos en falso contra 8 y 10 aciertos repiten el `ungrounded_keys` que se
   retiró en el #609.

Riesgos y qué podría romper:

- **La medición de `gemma4-26b-a4b` en entradas pequeñas es por el sustituto**, sin schema y con
  temperatura 0,2. Por el producto solo hay 4 casos grandes (17 de 17). Antes de publicar B hay
  que repetir las tablas pequeñas por el producto con el rol ya cambiado.
- **La regla de la tabla no ve una rejilla hecha con `<div>`**, que es como muchas páginas de
  precios pintan la comparación. No se sabe si la evidencia de 33 KB tenía `<table>`; daba igual
  porque ya iba a `long`.
- **El detector estricto no habría avisado en la evidencia de 33 KB** (fila vecina no pedida):
  cerrar el #586 solo con A no lo cierra.
- **B cambia el respaldo y el tope de esas llamadas** (`long`: respaldo `qwen36-35b-a3b`, tope
  48 000) y sube los cambios de modelo que ven los demás clientes del backend (Mac, otras
  sesiones). Si el residente pasa a ser otro modelo, las cifras de carga cambian.
- **Tests y datos a revisar**: `tests/test_core.py:174-196` (añadir los de la regla),
  `scripts/build_corpus.py:380-390` (`extraer-toml-2k` declara `mechanical`: comprobar si su
  fuente trae tabla), los asserts de igualdad de `_local_delegate` en los cinco ficheros
  `tests/test_extract_*.py`, `tests/test_i18n_parity.py` y `tests/test_mcp_english.py` (clave y
  docstring nuevos), y las excepciones de nombres del léxico si aparece algún identificador en
  español.
- **Entrada no confiable**: el detector parsea HTML y Markdown que vienen de fuera. El prototipo
  usa `html.parser` y búsquedas de subcadena, sin expresiones regulares con cuantificadores
  anidados; el coste es filas × campos × celdas, así que en `src/` conviene un tope de filas.
- **La guarda de 60 caracteres está ajustada sobre este conjunto**; necesita casos nuevos.

## local_summarize y tablas (#630)

El #630 (abierto durante esta investigación) entra en este cambio como candidato de la regla B:
dos resúmenes de `local_summarize` con el modelo mecánico traían una causa cambiada, cifras de una
tabla mezcladas, la expansión inventada de una sigla y una palabra en portugués.

**Dónde elige rol.** `local_summarize` hace lo mismo que `local_extract`, con la misma función:
`probe_len` y `role, model = _role_for_size(probe_len)` en `src/local_delegate/server.py:7398-7400`
(la función, en `:5213-5220`). Comparten la función, no una decisión común: cada tool la llama por
su cuenta, y las dos lo hacen **antes** de leer el contenido (`_read_input` va en `:7401` y en
`:7975`). En summarize el rol decide además el resumen estructurado (`role == "long"`, `:7416`) y el
tope de troceado (`:7456`). Y tiene un espejo que extract no tiene: los hooks calculan «el modelo
al que iría `local_summarize`» solo con el tamaño
(`src/local_delegate/resources/hooks/hook_common.py:739`, `:998-1004`).

**Los dos resúmenes con `gemma4-26b-a4b`.** Repetidos a las 09:37 y 09:40 (hora de Uruguay) en la
ventana `w-20261110T123643Z`, por `local_delegate(model="gemma4-26b-a4b")` con el mismo guard de
summarize; la cláusula del enfoque y la orden de idioma, que summarize lleva en el `system`, fueron
en el mensaje, y no hubo nota de secciones. Textos en `outputs/summarize-630-g4.json`.

| Defecto del #630 | Fichero | Con `gemma4-26b-a4b` |
| --- | --- | --- |
| Causa cambiada (atribuía la reversión al test intermitente) | registro de verificación, con tablas | **Desaparece**: da como causa las dos regresiones de la prueba en vivo y que el caso del #586 no se arregló; no nombra el test intermitente |
| Cifras mezcladas (lo que hace fallar un mutante contado como resultado) | el mismo | **Desaparece**: dice que la ausencia de la cláusula provoca el fallo de 3 tests y de 6 de cuerpos, y la falta de decodificación, el de 4 casos |
| Sigla inventada («SDD» expandida) | nota de relevo, **sin tablas** | **Desaparece**: deja «SDD» sin expandir |
| Palabra en otro idioma («deviações») | registro de verificación | **Desaparece**: todo en español; los títulos `#` copiados tal cual, que la orden permite |

Aparece una imprecisión nueva, menor: dice que las fixtures que no se regeneraron son «en
`test_corpus.py`», cuando el fichero habla de las fixtures de los cuerpos de petición. Y el segundo
resumen salió con etiquetas en negrita por sección, no en prosa.

**Con dos casos no hay cifra.** Son dos ficheros y una llamada por fichero. Además la comparación
no es limpia: los resúmenes con defectos salieron por el producto y los de `gemma4-26b-a4b` por el
sustituto, y no corrí el control del sustituto con `gemma3-4b` para no provocar otro cambio de
modelo. Que los cuatro defectos no salgan esta vez no prueba que el cambio de rol los quite; solo
que no es incompatible con ello.

**¿Una misma función para las dos tools?** Sí en lo mecánico: «la entrada tiene una tabla → rol
`long`» necesita el contenido, así que en las dos habría que decidir el rol después de
`_read_input`, y puede ser una sola función (`has_table` de `evaluate.py` es el prototipo). Lo que
cambia de una a otra:

- **Volumen**: fuera de las ventanas de prueba hay 589 llamadas a `local_summarize` frente a 76 de
  extract; 66 son pequeñas y de ellas 48 son `.md` por `path` y 8 texto en línea. Subirlas a `long`
  multiplica los cambios de modelo que hoy apenas existen en extract.
- **Espejos**: el hook que predice el modelo de summarize (`hook_common.py:998-1004`) dejaría de
  acertar si no se le da la misma regla, y con `LOCAL_DELEGATE_STRUCTURED_SUMMARY` encendido el
  rol `long` cambia también la forma del resumen.

**Lo que el cambio de rol NO arreglaría del #630:**

- La **sigla inventada**: salió en la nota de relevo, que no tiene ninguna tabla (0 líneas de
  tabla; el registro de verificación tiene 10). La regla no dispararía y la llamada seguiría en el
  modelo mecánico.
- La **causa cambiada** y la **palabra en otro idioma** no nacen de una tabla: la primera sale de
  dos viñetas seguidas de la lista final y la segunda de un encabezado en inglés. En ese fichero la
  regla dispararía porque trae tablas, pero un fichero con las mismas viñetas y sin tabla se
  quedaría como está.
- Solo las **cifras mezcladas** vienen de una tabla. Es decir, de los cuatro defectos, la regla
  apunta a la causa de uno.
- En summarize no hay claves contra las que comprobar el resultado: no existe un equivalente del
  aviso A.

## Existing conventions

- Lo que no es dato va en `_local_delegate`; un aviso nuevo se añade al final de `warning` y el
  anterior conserva su texto exacto (contrato del #455, `server.py:8213-8236`).
- Toda clave nueva de `_local_delegate` se describe en el docstring, en `docs/wiki/Tools.md` y en
  el CHANGELOG, y su aviso existe en `es` y en `en`.
- Código e identificadores en inglés; textos de salida en español e inglés por i18n.
- Sin expresiones regulares nuevas que puedan retroceder de forma catastrófica sobre la entrada.
- Un cambio de prompt exige declarar frontera en `scripts/build_corpus.py::PROMPT_BOUNDARIES`;
  ni A ni B tocan el prompt.

## Dependencies and integrations

- Sin dependencias nuevas: `html.parser`, `json`, `re` y `unicodedata` de la biblioteca estándar.
- Backend: llama-swap con el grupo `swap` (un modelo de texto cargado a la vez); turno común con
  la Mac por el mismo backend.
- Respaldo entre modelos encendido (hasta 2 saltos): cambia según el rol.

## Risks and unknowns

Hechos confirmados aquí: el cruce se reproduce por el producto con `gemma3-4b` en tablas; no
apareció sin tabla; `gemma4-26b-a4b` no cruzó en 26 corridas; el detector estricto no dio falsos
positivos; la tabla separa mejor que las palabras en común.

Sin validar: `gemma4-26b-a4b` por el producto en entradas pequeñas con tabla; el cruce en `long`
que cita el issue; un solo campo pedido; rejillas sin `<table>`; la guarda de celda larga fuera de
este conjunto; el recuento exacto de llamadas históricas con tabla.

## Artefactos

- `cases/` — 17 ficheros de entrada, `cases.json` (campos y respuestas anotadas) y
  `build_noisy_page.py` (genera el caso 19).
- `outputs/g3-extract.json`, `g3-proxy.json`, `g4-proxy.json`, `g4-extract.json` — salidas tal
  como volvieron (las del sustituto, ya parseadas).
- `outputs/summarize-630-g4.json` — los dos resúmenes del #630 repetidos con `gemma4-26b-a4b`.
- `outputs/log-window-rows.json` — metadatos de las 62 filas del log en la ventana (58 mías, 4 de
  otras sesiones), sin rutas ajenas.
- `detector.py` y `evaluate.py` — prototipo y evaluación; `python evaluate.py` regenera
  `outputs/evaluation.json`.
