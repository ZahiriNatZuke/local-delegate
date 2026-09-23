# Plan v2.1: local_summarize respeta la estructura del documento (resumen por secciones)

Spec aprobada el 2026-09-23 (REQ-201 a REQ-208), con los ajustes de la revisión del plan: REQ-201
exige dos títulos **del mismo nivel**, la regla de la etapa 2 se decide solo por correctas, se
escriben las amenazas a la validez y se rellena la trazabilidad. Rama
`feat/resumen-por-secciones`. La v1 y su revisión están en `review.md`.

## Approach

1. **El servidor detecta la estructura, una sola vez, sobre el documento entero,** con la posición
   de cada título. Con menos de dos títulos del mismo nivel, el camino es el de `main` byte a byte.
2. **Al modelo se le da la lista de secciones** en orden y se le pide una línea `## <título
   literal>` por cada una, seguida de su resumen.
3. **El servidor completa la salida del modelo antes de añadir avisos y coletillas**: empareja en
   orden los títulos esperados con las líneas de título de la salida e inserta en su sitio los que
   falten, con «(sin resumir)», incluso si la salida se cortó por `length`. Cuenta también las
   secciones que el modelo dejó vacías. Así, «no omite ninguna» no depende de que el modelo
   obedezca. La medición no cuenta como aciertos las secciones completadas por el servidor.
4. **Documentos largos:** se trocea por los títulos del nivel estructural (fuera de bloques de
   código), cada trozo se resume con **sus** secciones, **su** tope de palabras y **su**
   `max_tokens`, y los parciales se **concatenan en orden** sin reduce por el modelo. Un solo
   evento de uso, como hoy.
5. **`focus`** se sanea (una línea, sin caracteres de control, 200 caracteres como mucho) y va
   delimitado en el prompt de sistema, en los dos modos y también en el reduce en prosa.
6. **Un interruptor** `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO` (encendido por defecto) apaga el modo
   estructurado. Lo lee el daemon al arrancar: para usarlo hay que ponerlo en el entorno del
   lanzador y reiniciar el daemon. La retirada (T8) cambia su valor por defecto en una release.
7. **Medir gratis antes de gastar**, con una métrica que no se engañe y controles en los dos
   sentidos, sobre copias fijas de los documentos.

## Ordered tasks

### T0 — Copias fijas de los documentos (N3, N5)

- `benchmarks/resumen-estructurado/fuentes/`: copias de `README.md`, `docs/wiki/Integration-install.md`,
  `docs/wiki/Daemon.md`, `CHANGELOG.md` y `docs/recipes/llama-swap-blackwell.md` tomadas con
  `git show 95a65ee:<ruta>` escritas como bytes (sin conversión de finales de línea), fijadas en
  `.gitattributes` con `-text` para que el checkout no las cambie, más un `MANIFEST.json` con el
  commit y el sha256 de cada una; un test comprueba los sha256. Los tests de T1, la etapa 1 y la etapa 2 usan estas copias, nunca los ficheros vivos
  (T9 edita el README).

### T1 — Detección de secciones (REQ-201, casos límite)

- `server.py`, función pura `_secciones_markdown(text) -> Estructura | None`, con
  `Estructura(nivel: int, titulos: list[Titulo])` y `Titulo(texto: str, inicio: int)` (posición del
  carácter donde empieza la línea del título).
  - ATX: `^ {0,3}#{1,6}[ \t]+texto`, quitando los `#` de cierre. Setext: línea de texto no vacía
    seguida de `^ {0,3}=+[ \t]*$` (nivel 1) o `^ {0,3}-+[ \t]*$` (nivel 2), siempre que la línea de
    texto no sea ella misma un título, un elemento de lista ni una línea de tabla.
  - Ignora el interior de bloques con valla (```` ``` ```` o `~~~`, de tres o más; cierra la
    misma marca con igual o mayor longitud) y el front matter YAML inicial (`---` en la línea 1
    hasta el siguiente `---` o `...`). Una valla sin cerrar llega hasta el final.
  - `---` tras una línea vacía es una regla horizontal.
  - Nivel estructural: el nivel más alto (número menor) con **al menos dos títulos**. Si ninguno
    llega a dos, `None`.
- Tests `tests/test_resumen_estructurado.py`, con las copias de T0 (11, 9, 5, versiones del
  CHANGELOG, y el documento corto) y casos sintéticos: 9 `##` + 1 `#` → nivel 2; un `#` y un `##`
  → `None`; `#` dentro de ```` ```bash ```` y de `~~~`; valla sin cerrar; setext de los dos
  niveles; front matter; regla horizontal; duplicados; posiciones correctas; **CRLF** (ATX con `#`
  de cierre, setext y valla con `\r\n`) y que `titulo.inicio` apunta a la línea del título en el
  mismo texto que recibe `_trozos_por_secciones`.
- Mutantes (mirando qué assert dispara): aceptar un solo título; contar títulos dentro de vallas;
  no ignorar el front matter; confundir la regla horizontal con un título.

### T2 — Prompt estructurado, emparejamiento y completitud, una pasada (REQ-201, REQ-202, REQ-204)

- **Prompt** con estructura:
  - Sistema: `_guard("un resumen que sigue la estructura del documento: por cada sección de la
    lista, en ese orden, una línea '## ' con el título tal cual y debajo 1 a 3 frases con lo que
    dice", max_words)` + « Los títulos no cuentan en el límite de palabras; si no alcanzan para
    todas, deja solo el título en las últimas.»
  - Usuario: «Secciones, en orden:\n- t1\n- t2…\n\nResume el siguiente contenido:\n\n<doc>».
  - `max_tokens = 2·max_words + 64 + Σ(len(título)//2 + 8)`, calculado por `_max_tokens_estructurado`.
- **Sin estructura**, o con el interruptor apagado: el código de `main`. Test: el payload
  (system, user, `max_tokens`) es igual al de `main`, copiado literal en el test.
- **Emparejamiento** (`_emparejar_secciones(salida, esperados)`), definido así:
  - Líneas de título de la salida: una línea que empieza por `#` (cualquier nivel), o una línea
    entera en negrita (`**…**`/`__…__`).
  - Normalización (`_normal_titulo`, fuente única): NFKD sin marcas diacríticas, minúsculas,
    sin backticks, `*`, `_`, corchetes ni signos de puntuación, sin numeración inicial
    (`1.`, `1)`, `I.`), espacios colapsados.
  - Una línea de título **casa** con un esperado si, normalizadas, son iguales o la línea
    **empieza** por el esperado seguido de un límite de palabra (`## Instalación: pasos` casa con
    `Instalación`). Solo líneas de título, nunca la prosa.
  - Emparejamiento por **subsecuencia común más larga** (LCS) entre la lista de esperados y la de
    líneas de título, uno a uno (un duplicado necesita dos apariciones). Un esperado sin pareja
    que **sí** aparece en alguna línea de título libre se informa como **fuera de orden** y no se
    inserta; uno que no aparece en ninguna **falta**.
  - Si la salida se cortó por `length` y su última línea es una línea de título, se quita antes de
    emparejar (es un título a medias).
  - Sección **vacía**: emparejada pero con menos de 3 palabras entre su línea y la **siguiente
    línea emparejada** (o el final). Las negritas y subtítulos propios del modelo dentro de una
    sección cuentan como contenido.
- **Completitud** (`_completar_secciones(salida, esperados, cortada) -> (texto, faltan, vacias,
  fuera_de_orden)`): inserta
  cada título que falta como `## <título>\n(sin resumir)` justo antes de la línea de título del
  siguiente esperado emparejado, o al final si no lo hay. Si `faltan + vacias > 0`, añade
  «[local-delegate aviso: N secciones sin resumir por el límite de palabras o del modelo]».
- **Dónde corre**: parámetro nuevo `postproceso: Callable[[str], str] | None` de `_chat`, aplicado
  a la salida del modelo **si `result.ok`**, justo después de `_strip_fences` y **antes** del aviso
  de truncado, del aviso de respaldo, de `chars_out` y de la coletilla de ahorro. Corre también
  cuando `finish_reason == length` (el aviso de truncado se conserva). Con error, no corre.
- Tests: payload estructurado (lista, formato, `max_tokens`); título reescrito (sin tilde, con
  número delante, como `###`, en negrita) sin duplicarlo; título mencionado solo en la prosa de
  otra sección que sí se completa; duplicado al que le falta la segunda aparición; faltan las dos
  últimas y la coletilla de ahorro sigue siendo lo último; salida cortada por `length` completada
  con el aviso de truncado conservado; salida cortada a mitad de un título (`## Instal`) sin
  duplicado; título con sufijo (`## Instalación: pasos`); A y B invertidos → ninguno insertado, uno
  fuera de orden; sección con `**Puntos clave:**` y texto debajo → tiene contenido; salida de error
  intacta; con respaldo, el aviso de respaldo no se toma por contenido. Mutantes: quitar la lista
  del prompt; quitar la completitud; emparejar por subcadena; emparejar con puntero voraz en vez de
  LCS; medir el contenido hasta cualquier línea de título; aplicar el postproceso después de los
  avisos.

### T3 — `focus` (REQ-205, N10)

- Firma: `local_summarize(text=None, path=None, max_words=150, focus: str | None = None)`.
- Saneado (`_sanear_focus`): quita los caracteres de control, colapsa espacios y saltos de línea,
  recorta a 200; vacío → `None`.
- Se añade al sistema, delimitado: « Prioriza este aspecto: «{focus}». Conserva literales los datos
  concretos que tengan que ver con él (cifras, nombres, decisiones).»
- En map-reduce en prosa, el enfoque llega al reduce por un parámetro nuevo
  `reduce_extra: str = ""` de `_chat_map_reduce`, que se concatena al `_guard` **por defecto** sin
  convertirlo en `reduce_propio` (la rama «un solo parcial» y el reagrupado no cambian).
- Tests: payload con `focus` en prosa, en estructurado y en el reduce en prosa; `focus` de varias
  líneas y con caracteres de control; vacío = ausente; recorte; el texto no llega al log.

### T4 — Documentos largos por secciones (REQ-203, B1, B2, B6)

- `_chat_map_reduce` gana un modo `por_trozo`, con parámetros nuevos y opcionales, sin cambiar a
  los llamadores actuales:
  - `pieces: list[Trozo] | None`, con `Trozo(texto, titulos, continua_de)`: los títulos del nivel
    estructural que contiene (con sus posiciones del documento entero) y, si empieza a mitad de
    sección, el título de esa sección. Sin `pieces`, `_chunk_text` sobre `str` como hoy.
  - `system_for(trozo)`, `user_for(trozo)`, `words_for(trozo)` y `tokens_for(trozo, words)`: se
    usan en el map **y** en los subtrozos del reintento por desborde.
  - `split_for(trozo) -> list[Trozo]`: cómo se parte un trozo que no cabe. En modo `por_trozo`
    usa `_trozos_por_secciones` con las posiciones del documento entero (nunca `_chunk_text`
    genérico, que corta en `#` de código) y marca como continuación los subtrozos que no empiezan
    en un título.
  - `reduce="concat"`: sin reduce por el modelo; los parciales se unen con `"\n\n"` en orden.
  - `postproceso`: igual que en `_chat`, sobre el texto unido y antes de los avisos.
- **Troceado por secciones** (`_trozos_por_secciones(text, estructura, budget)`): corta **solo**
  en las posiciones de los títulos del nivel estructural detectados en T1 (así nunca dentro de una
  valla ni en un subtítulo) y empaqueta secciones enteras hasta el presupuesto (0,8 × tope). Una
  sección mayor que el presupuesto se parte con `_chunk_text`; las partes siguientes llevan en su
  prompt de usuario «Continúa la sección '<título>': resume solo este fragmento, sin línea de
  título» y su salida se pega bajo la de la sección.
- `words_for`: `max_words` repartido en proporción al tamaño de cada trozo, con un mínimo de 40
  **solo si** `40 × trozos ≤ max_words`; si no, el reparto exacto. La suma no pasa de `max_words`.
- **Corte por `length` por trozo (B6, vale para todos los llamadores):** `_one` guarda si alguna
  llamada acabó en `length`; el evento lleva `finish_reason: "length"` y `truncated_out: true`, y
  el texto el aviso de truncado. Cambio visible para `local_lint_summary` y `local_commit_msg`:
  hoy un parcial cortado se acepta en silencio; va al CHANGELOG como `Fixed`.
- Tests: documento largo con títulos → un evento, `chunks` = llamadas, cada payload lleva los
  títulos de su trozo, su «Máximo N palabras» y su `max_tokens`; un `# comentario` dentro de una
  valla junto a la frontera de corte no corta; sección gigante partida con «Continúa la
  sección»; reintento por desborde con los prompts por trozo; desborde en un trozo cuyo punto
  medio cae dentro de una valla con un `# comentario` → los subtrozos llevan los títulos correctos
  y el de continuación dice «Continúa la sección»; mock con `length` en el trozo 2 →
  el evento lo registra y el texto avisa; la suma de palabras pedidas ≤ `max_words`; la nota
  «(resumido de N partes…)» se mantiene. `test_map_reduce.py` y `test_chunking.py` existentes, en
  verde sin tocarlos salvo el caso de `length`, que se añade. Mutante: usar el reduce por modelo en
  vez de concatenar.

### T5 — Registro de uso e interruptor (REQ-206, N11)

- `_log_event` acepta `secciones: int | None` (número de títulos del nivel estructural) y
  `focus: bool = False`, aditivos y omitidos cuando no aplican; `_chat` y `_chat_map_reduce` los
  pasan.
- Guardianes revisados por nombre: `src/local_delegate/web/metrics.py`, `_accounting` y su espejo JS
  (`tests/test_dashboard_js.py`), `tests/test_metrics.py`. Si alguno enumera campos, se actualiza;
  si ninguno, test de que un evento con los campos nuevos se agrega igual.
- Si `metrics.py`, el panel o `_accounting` calculan tasas de truncado o de `finish_reason`, el
  `length` de map-reduce (T4) es un corte de serie para `local_lint_summary` y `local_commit_msg`:
  se anota en el CHANGELOG. En `local_commit_msg` el aviso queda dentro del mensaje, antes de
  «(alcance…)»; el `Fixed` lo dice.
- `config.RESUMEN_ESTRUCTURADO` con el helper `_env_flag`, encendido por defecto (los tres
  guardianes de `tests/test_aislamiento_entorno.py` lo exigen); apagado, el camino es el de `main`.
- Tests: evento con `secciones` y `focus: true` sin el texto; evento sin estructura idéntico al de
  hoy; interruptor apagado = payload de `main`; `tests/test_conformidad_f1.py` en verde (el rol se
  sigue eligiendo por el documento entero).

### T6 — Métrica de la etapa 1 (B7, N1, N8)

- `scripts/medir_resumen_estructurado.py`, con la lógica de medición en funciones puras que usan
  `_normal_titulo` y `_emparejar_secciones` **importadas de `local_delegate.server`** (fuente única):
  - cobertura = títulos emparejados por **línea de título y en orden** / esperados, **sin contar**
    los insertados por el servidor (se reconocen por «(sin resumir)»);
  - orden correcto (el emparejamiento ya es en orden; se informa además si hay títulos esperados
    fuera de su sitio);
  - secciones con contenido = emparejadas con al menos 5 palabras debajo;
  - palabras sin contar títulos, contra `max_words`;
  - `finish_reason`, `truncated_out` y latencia, leídos del evento de uso de la llamada.
- Controles escritos a mano, **con el resultado esperado escrito a mano** (no calculado con la
  función que se prueba), con test: un buen resumen da 1,0 y pasa; solo títulos, falla el
  contenido; prosa que menciona los títulos, cobertura baja; títulos desordenados, falla el orden;
  títulos completados por el servidor, no cuentan; un CHANGELOG con la mitad de las versiones
  completadas por el servidor **falla**; sección con `**Puntos clave:**` y texto debajo tiene
  contenido; título con sufijo casa; duplicado con una sola aparición cuenta una.
- Contenido de una sección: desde su línea emparejada hasta la siguiente línea emparejada (o el
  final), como en T2.
- El banco de T5 (`experimento_adopcion.cobertura_de_titulos`) **no cambia**: su línea base se
  midió con la normalización vieja y así se compara en T8. Se escribe en el docstring.

### T7 — Etapa 1, sin cuota (REQ-208)

- El script llama `local_summarize` por el `/mcp` del daemon con `path` a las copias de T0:
  README, `Integration-install.md`, `Daemon.md` y CHANGELOG con `max_words` 500;
  `llama-swap-blackwell.md` (va al 4B); y `Daemon.md` con `focus="puertos, variables y rutas"`.
  Salidas **fuera del repo** (`%TEMP%`) para la revisión humana; en el repo solo las métricas. El
  token del daemon se lee de la variable de usuario y nunca se imprime.
- **Primero con el daemon actual (código de `main`)**: línea base y control positivo; la
  cobertura tiene que salir baja, como en el piloto. La llamada con `focus` falla ahí y se anota
  como esperada.
- Después se reinstala el daemon con la rama y se repite.
- Criterio (spec): cobertura ≥ 0,9 en los tres documentos sin las completadas, todas las
  emparejadas con contenido, y el usuario lee los tres resúmenes y acepta al menos 2 como fieles.
  CHANGELOG: cobertura ≥ 0,9 sin las completadas, cada versión emparejada con contenido, sin
  `length`. Documento corto (4B): cobertura ≥ 0,9 sin las completadas; si no, el modo
  estructurado se limita al rol `long` (cambio en T2 con su test) y se repite la medición del
  corto. Se informan también el `focus` y las palabras frente a `max_words`. Si no pasa: no hay etapa 2; se vuelve al plan (alternativa:
  llamadas por sección).

### T8 — Etapa 2, con cuota (REQ-208, N2, N4)

- `experimento_adopcion.py` gana `--variantes` (por defecto las tres, como hoy) y
  `--fuentes <dir>` (lee las tareas de las copias de T0 en vez del repo). `--piloto` no cambia.
  Informe nuevo `informe_resumen(filas)`: correctas y corridas con contenido en el contexto
  (`contenido_en_contexto`, la misma definición de T5), con test puro.
- `uv run python scripts/experimento_adopcion.py --banco %TEMP%\banco-resumen-estructurado --piloto
  --variantes v0 --repeticiones 3 --fuentes benchmarks/resumen-estructurado/fuentes`, previa
  confirmación del gasto (unos 3,6 USD). Se anota la versión de hooks instalada.
- Decisión (spec): ≥ 6/9 correctas se queda; ≤ 3/9 se retira; entre medias, se decide con el
  usuario.
- **Retirada, escrita antes de medir (N9):** el valor por defecto del interruptor pasa a apagado
  en una release y se anota; el código queda para medir de nuevo. `focus`, los campos del log y el
  aviso de `length` se quedan. Igual que en la spec.
- `verification.md` lleva el desglose por tarea (la base comparable real es V0: 0 de 3), para no
  leer un 6 de 9 como uniforme.

### T9 — Documentación y cierre (REQ-207)

- Después de T8 (N9): docstring de `local_summarize` (estructura y `focus` con ejemplo);
  `docs/wiki/Tools.md`, `docs/wiki/Configuration.md` (el interruptor), `README.md` si nombra el
  comportamiento, skill `resources/skills/delegacion-local/SKILL.md`, CHANGELOG `[Unreleased]`
  (`Added`: `focus`; `Changed`: resumen estructurado; `Fixed`: `length` en map-reduce).
- Copias del prompt en `benchmarks/catalogo-2026-09/cases.json`, `scripts/construir_corpus.py` y
  `tests/test_corpus.py`: el camino sin títulos no cambia; si algún caso lleva títulos, se anota en
  `verification.md` como fotografía del prompt viejo.
- Suite completa, ruff, reinstalación con los cuatro flags, `doctor`, commit firmado sin
  coautoría, vault, memoria y gates.

## Test strategy

- Unitarios puros: detección (T1), emparejamiento y completitud (T2), saneado (T3), troceado por
  secciones y reparto (T4), métrica (T6).
- Payloads capturados con el mock de `test_map_reduce.py`/`test_chunking.py`; el camino sin títulos
  y el interruptor apagado se fijan contra el payload de `main` copiado literal.
- Mutantes por test nuevo, mirando qué assert dispara.
- Controles de la métrica en los dos sentidos (T6) y control positivo con el daemon de `main` (T7).

## Migration and compatibility

- `focus` opcional; clientes con el schema en caché siguen funcionando.
- Sin títulos o con el interruptor apagado, nada cambia; benchmarks y corpus comparables.
- Campos nuevos del log aditivos. El aviso de `length` en map-reduce es un cambio visible para
  `local_lint_summary` y `local_commit_msg` (CHANGELOG `Fixed`).

## Risks

- El 26B puede no seguir la lista: la completitud salva el formato, pero la etapa 1 no cuenta las
  completadas, así que no pasa con una salida llena de «(sin resumir)».
- El 4B sigue peor el formato: se ve en la etapa 1 con el documento corto.
- Títulos inventados por el modelo: no se quitan; si aparecen, se ven en la revisión humana.
- Latencia: una pasada como hoy; en documentos largos, las mismas llamadas del map y ninguna de
  reduce.

## Plan review

v1: `revise`, 8 bloqueantes y 13 no bloqueantes. v2: `revise`, 3 bloqueantes pequeños (V2-B1 a
V2-B3) y 9 no bloqueantes, todos aplicados en esta versión (v2.1). Detalle y resolución en
`review.md`.
