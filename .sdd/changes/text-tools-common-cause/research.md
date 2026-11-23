# Investigación: causa común de los fallos de las tools de texto

- Fecha: 2026-11-23, 07:30–08:15 hora de Uruguay. Código de `main` en `a776da37` (v0.53.0, la instalada en el daemon).
- Alcance: los 11 issues abiertos (#688, #690–#699) y los 37 cerrados de la misma familia (búsqueda `gh issue list --state closed --search "<tool> in:title"` para las seis tools de texto).
- Pruebas en vivo: ventana `w-20261123T104729Z` (07:47–07:51 hora de Uruguay), 7 llamadas al daemon con entradas sintéticas de la misma forma, guardadas en el scratchpad de la sesión (`repro/`, `out/`). Ojo: `LOCAL_DELEGATE_LOG` no afecta al daemon (lo lee el proceso que escribe la fila), así que las filas fueron al log real y quedaron marcadas solo por la ventana de prueba.
- Comparación entre modelos (pregunta 3): **no se hizo**. Tras la segunda llamada al modelo `long` la RAM libre bajó a 3,5 GB (`llama-server` con 13,7 GB), por debajo del suelo de 8 GB. La evidencia indirecta está en la sección «Tres preguntas».
- `local-delegate` desde este subagente: las tools `local_*` no se podían cargar (el `ToolSearch` no las encontró en la sesión). Las lecturas se hicieron con `grep` y por rangos. 0 llamadas `local_*` por MCP de sesión, 7 al daemon para las pruebas.

## 1. Ficha por issue

| Issue | Tool | Síntoma | Entrada | Versión observada |
|---|---|---|---|---|
| #688 | lint_summary | El mismo aviso contado dos veces (ruta relativa y absoluta); la URL del pie listada como fichero; lista ficheros limpios | salida de pytest, 1,4 KB | 0.52.0 |
| #690 | lint_summary | Inventa carpetas al agrupar (`projects/knowledge/`) | salida de linter de notas, 24,5 K, 170 líneas | sin versión (2026-11-17, o sea 0.53) |
| #691 | summarize | Secciones repetidas con «(sin resumir)» en el cuerpo | Markdown de 84 K, 3 trozos | 0.53.0 |
| #692 | extract | `true` en un campo que pide una lista | Markdown de 5,8 K | 0.53.0 |
| #693 | extract | Acepta un JPEG como texto, lo trocea en 6 y da nulls | JPEG de cientos de KB | 0.53.0 |
| #694 | extract (+ explain_code en el comentario) | Devuelve las viñetas del JSDoc en vez del código; rangos correctos o no, marcados como dudosos | `.ts` de 200–890 líneas | 0.52.0 y 0.53.0 (comentario del 2026-11-20) |
| #695 | summarize | Atribuye a `/SILENT` la definición de `/VERYSILENT` (elemento vecino) | texto de 74 K, 3 trozos | 0.53.0 |
| #696 | extract | Líneas equivocadas sin aviso en requisitos; rangos correctos marcados como dudosos; nulls; en un `.md` de 400 KB, apartados de otros componentes | Markdown de 55 K y de 400 K; `.ts` de 330 líneas → `1-329` | 0.53.0 |
| #697 | extract | `null` en `ficheros_con_lineas` sobre un patch grande | patch de 140–430 KB | 0.52.0 |
| #698 | extract | JSON cortado por `max_tokens=512` o rangos sin nombre | `.ts` de 36–55 K, ~60 funciones | 0.52.0 |
| #699 | describe_image | Inventa defectos de layout (alturas, desbordes) | PNG de 1440×900, tarjetas de 320 px | 0.53.0 |

## 2. ¿Sigue en la 0.53.0?

| Issue | ¿Sigue? | Cómo se comprobó |
|---|---|---|
| #688 | **Sí** | Por programa: `lint_patterns.files_by_frequency` sobre una salida sintética devuelve 3 «ficheros»: la ruta relativa, la absoluta (sin unir) y `docs.pytest.org/.../capture-warnings.html`. En vivo (G): el modelo unió las dos rutas, pero listó la URL como fichero «sin errores». |
| #690 | **Sí, por código** (en vivo no, por la RAM) | El inventario del programa sale bien (5 de 5 rutas). El fallo es del modelo, y la red que debía cazarlo no puede: `invented_files` → `mentions` acepta un fichero si coincide su **nombre base** (`lint_patterns.py:184-198`), así que `projects/knowledge/temas/x.md` pasa porque `x.md` está en el log; y las carpetas sin extensión (`projects/knowledge/`) no son `FILE` y nunca se comprueban. |
| #691 | **Sí, por código** | `sections.complete` (`sections.py:631-689`) mete `## <título>\n(sin resumir)` por cada título que no empareja y además avisa; con el reparto `allocate_words` a una sección le tocan pocas palabras. Si el modelo escribió el título con otra forma, el emparejamiento lo da por ausente y lo inserta otra vez: de ahí la repetición. No se reprodujo (pide 3 trozos con el modelo `long`). |
| #692 | **Sí, la causa; el síntoma no se reprodujo** | El esquema JSON solo admite `string/number/boolean/null` y **prohíbe arrays** (`server.py:6509-6525`). Con decodificación por gramática, una respuesta que empieza por `[` es ilegal, y `true` es una salida legal. En vivo (C), con 3,5 K y el modelo mecánico, salió bien (`"MD013, MD033, MD041"`): el fallo depende de la entrada, la causa sigue ahí. |
| #693 | **Sí, en vivo** | (F) Un PNG falso de 3 KB: se leyó como latin-1, se llamó al modelo y devolvió `campo: null` con el aviso de codificación. Causa: desde #672 `_decode_input_file` (`server.py:1090-1114`) cae a cp1252/latin-1, que decodifican cualquier byte; no hay detección de binarios. **Es una regresión de la 0.53.0.** |
| #694 | **Sí, en vivo** | (B) `.ts` de 450 líneas, 5 K: fue al **modelo mecánico** (`gemma3-4b`, por tamaño < 6000), se cortó en 512, se rehízo en 3 trozos y devolvió `líneas 75-81` (el JSDoc), `148-297` y `300-450` (bloques enormes). **Nada marcado como dudoso**: el valor no nombra nada, así que la verificación solo mira que esté dentro del fichero. |
| #695 | **Sí, por código** (sin cambios en la tool desde que se abrió en la 0.53.0) | Fallo de fidelidad del modelo al comprimir una lista de pares; no hay comprobación por programa de pares nombre → definición. |
| #696 | **Sí, en vivo (la mitad de los falsos positivos)** | (A) Sobre un `.ts` sintético, las 60 líneas de inicio y fin que dio el modelo eran **correctas** y aun así 20 salieron en `lines_unverified`. Causa en `line_check._text_items` (`line_check.py:1239-1252`): si el tramo antes de la cita no nombra nada (`total1` no cuenta como palabra porque lleva un dígito), se usa **la línea entera** como nombre, y la ventana no contiene el resto de identificadores. Las líneas equivocadas sin aviso vienen de lo contrario: basta **una** palabra de 4+ letras que aparezca en la ventana (`any(...)`, `line_check.py:1355`), y «requisito» aparece en casi todas. |
| #697 | **Arreglado para el nombre exacto; sigue con sinónimos** | (D) `ficheros_con_lineas` sobre un patch de 104 KB y 26 ficheros: 26 rangos exactos por programa en 0,9 s (`program_only`). Pero `asks_for_diff_files("lista_de_ficheros_con_sus_lineas")` da `False` (por «sus»): ese campo va al modelo trozo a trozo y vuelve a salir null. Comprobado por programa; la variante no se llamó en vivo por la RAM. |
| #698 | **Arreglado el JSON cortado; queda lo lento y los falsos avisos** | (A) `.ts` de 44 K, 906 líneas y 60 funciones: la llamada única se cortó en 512, el reintento por mitades de #666 la rehízo en 3 trozos, y devolvió los 60 nombres con sus líneas correctas en **106 s**, con 20 marcados como dudosos por error. |
| #699 | **Sí, por código** | El rol `vision` (`gemma4-12b`) no resuelve diferencias de pocos píxeles; el aviso de #663 (PR #679) solo cubre «desalineación de píxeles» y no las preguntas de alturas o desbordes. |

## 3. Recaídas: lo que dicen los cerrados

Las 37 cerradas se agrupan en seis familias. En cada una se cerró un caso con un parche y al poco salió la variante siguiente:

| Familia | Cadena de issues | Patrón |
|---|---|---|
| Localizar líneas | #460 → #568 → #594 → #633 → #666 → #694, #696, #698 | Cada parche enseñó al programa un formato más de la respuesta del modelo (índice, título, sección, cita); la siguiente forma de fallar salió por otro lado. |
| Verificar las líneas citadas | #616 → #627 → #633 → #696 (+ A de hoy) | Cada parche aflojó el emparejamiento por palabras para quitar un falso positivo; eso abre falsos negativos (#696, #694). |
| Salida cortada por el presupuesto | #455 → #487 → #598 → #580 → #666 → #698, #691 | Topes fijos (`max_tokens=512`, `max_words` repartido); se fueron añadiendo reintentos al cortarse, nunca un presupuesto a la medida de la respuesta. |
| Diffs y patches | #582 → #665 → #665 reabierto → #687 → #697 | Funcionó al pasarlo **al programa**; lo que queda depende de que el nombre del campo caiga en una lista de palabras. |
| Valores con forma o fila equivocada | #586 → #650 → #667 → #692 | Detectores por programa después del hecho (marcadores, filas cruzadas, polaridad); el contrato de tipos no se tocó nunca. |
| Inventos del modelo | #499, #525, #538, #630, #641, #663 → #688, #690, #695, #699 | Avisos por programa caso a caso; las redes son laxas (nombre base, palabra suelta). |

Lo que se repite: **el modelo hace un trabajo que el programa sabe hacer exacto** (contar, numerar, buscar rutas, emparejar), y el programa revisa después con heurísticas por palabras. Cada parche mueve el punto de fallo. Las dos veces que se pasó la tarea entera al programa (#665/#687 con diffs y el esquema de títulos de Markdown de #594), la familia dejó de recaer en ese caso.

## 4. La cadena de punta a punta

| Eslabón | Veredicto | Evidencia |
|---|---|---|
| Cliente: hooks, mod, skill, bloque de `CLAUDE.md` | **Amplifica** | El hook de subagentes (`resources/hooks/hook_common.py:1650-1675`), la skill (`resources/skills/local-delegation/SKILL.md:104-110`) y la memoria (`resources/memory/local-delegate.md:21`) mandan a pedir `…_con_lineas` antes de leer: dirigen el uso justo a la función que más falla. Los agentes repiten la misma llamada con `temperature=0` (#698: 5 de 7 fallos eran repeticiones). |
| CLI / servidor MCP / daemon | Limpio | Sin fallos atribuibles; la cola por concurrencia (#698, hasta 131 s) es solo lentitud. |
| Lectura por `path` | **Causa** (#693) | `_decode_input_file` no rechaza binarios desde #672. |
| Elección de rol y modelo | **Causa** (#694) y amplifica | `_role_for_size` decide solo por tamaño (`server.py:5697-5704`, umbral 6000): un `.ts` de 5 K con un campo de líneas va a `gemma3-4b`. `local_extract` nunca usa el rol `code`. |
| Troceado y presupuesto | **Amplifica** | Presupuesto en caracteres (memoria `presupuesto-en-chars-limite-en-tokens`); `_numbered_code_pieces` solo sabe cortar por `def`/`class` de Python (`_TOP_LEVEL_NAME`, `server.py:5161`): un `.ts` se corta por párrafos. |
| Prompt | **Causa** (#694, #690) | `_EXTRACT_LINES_CLAUSE` (`server.py:8578-8583`) pone de ejemplo «Título: líneas 120-160»: la salida de #694 empieza literalmente por «Título: líneas 86-93». No dice que se cite código y no comentarios, ni pide la forma de la lista. El prompt de lint pide «agrupados por archivo» sin decir que se copien las rutas tal cual. |
| Llamada al backend | **Causa** (#692, #698) | `max_tokens=512` fijo en la llamada única de extract (`server.py:8893`); el esquema prohíbe arrays (`server.py:6517`): una lista de 60 entradas tiene que ir en una sola cadena (lo que se vio en A) y una lista corta puede acabar en `true`. |
| Reducción del map-reduce | Amplifica (#691, #697) | En summarize la reducción es `concat` + `sections.complete`, que rellena con «(sin resumir)» en vez de reintentar. En extract, un campo que ningún trozo contesta queda null con un aviso genérico. |
| Verificación y reparación | **Causa** (#694, #696, #690, #688) | `line_check.check_values` vale con una palabra cualquiera en la ventana y, si no hay nombre, solo comprueba la longitud del fichero; `_text_items` usa la línea entera como nombre. `invented_files` acepta por nombre base. `files_by_frequency` no une la ruta absoluta con la relativa ni descarta URLs. |
| Presentación y avisos | Amplifica | Avisos muy largos (A: 20 rangos repetidos dos veces en `warning`) que no dicen qué hacer; un `lines_unverified` falso lleva al agente a leer el fichero entero. |
| Modelo | Causa solo en #695 y #699 | Ver la pregunta 3. |

## 5. Tres preguntas

1. **¿El prompt está mal o tiene zonas grises?** Sí, pero es causa menor. El ejemplo «Título: …» sesga hacia títulos y viñetas (#694), no se distingue entre código y comentario, no se fija la forma de una lista, y el prompt de lint no exige copiar las rutas literalmente (#690). Retocar solo el prompt ya se probó (#594, #633) y recayó.
2. **¿El flujo está mal?** Sí, y es la causa principal. Se le pide al modelo que **produzca números de línea y rutas**, y después el programa intenta adivinar con heurísticas si acertó. El contrato de tipos (esquema sin arrays), el presupuesto fijo de salida, la falta de control de binarios y un ruteo por tamaño que ignora la tarea completan el cuadro.
3. **¿El modelo no da para la tarea?** No como causa general. Prueba indirecta de hoy: en A, `gemma4-26b-a4b` dio bien las 60 líneas cuando cada trozo era pequeño y estaba numerado: el fallo fue el corte y la verificación. En B, `gemma3-4b` falló en localizar en código: ahí sí es el modelo, y lo decide el ruteo. Sí es límite del modelo en #695 (comprimir listas de pares) y #699 (medidas en píxeles). No hace falta un modelo más grande: hace falta no mandar al de 4B tareas de localizar y no pedirle a ninguno lo que el programa calcula. La comparación directa entre modelos queda pendiente para cuando la RAM lo permita (protocolo: el mismo B con `local_delegate(model=gemma4-26b-a4b)` y `model=qwen36-35b-a3b`, dentro de una ventana de prueba, con al menos 8 GB libres).

## 6. Causas raíz → issues → código

| Causa | Issues abiertos | Cerrados que la tuvieron | Código |
|---|---|---|---|
| C1. El modelo genera las líneas o rutas que el programa sabe calcular | #694, #696, #697 (sinónimos), #698 | #460, #568, #582, #594, #633, #665, #666 | `server.py:8781-8807`, `8578-8583`; `line_check.py:997-1027` |
| C2. Verificación posterior por solapamiento de palabras, laxa e incoherente | #694, #696, #690, #688 | #616, #627, #633, #525, #641 | `line_check.py:1239-1361`; `lint_patterns.py:103-113`, `184-231` |
| C3. Contrato de salida sin tipos: el esquema prohíbe arrays y admite booleanos en cualquier campo | #692, #698 (lista en una cadena) | #586 | `server.py:6509-6525` |
| C4. Presupuesto de salida fijo, no a la medida de la respuesta | #698, #691 | #455, #487, #580, #598, #666 | `server.py:8893`; `sections.py:631-689`; `_structured_max_tokens` (`server.py:7763`) |
| C5. Entrada sin validar: binarios aceptados como texto | #693 | #469 (hook) | `server.py:1090-1114`, `1149-1170` |
| C6. Ruteo de rol solo por tamaño | #694 | #586, #650 | `server.py:5697-5704`, `8081-8087` |
| C7. Límite del modelo (comprimir listas de pares, medir píxeles) | #695, #699 | #630, #663 | prompts de summarize y describe_image |

## 7. Propuesta: una solución por causa raíz

### R1. Localizar por programa: el modelo da anclas literales, el programa da las líneas (C1, C2, C6). Cierra #694, #696, #697 y #698

Rediseño del eslabón de localización de `local_extract` (y de las citas de `local_explain_code` en una segunda fase):

1. **Índice estructural por programa**, por tipo de fichero: Markdown → esquema de títulos con el final de cada sección (ya existe `markdown_outline`); diff → `diff_file_hunks` (ya existe); código (`.py`, `.ts/.tsx/.js/.mjs`, más adelante otros) → declaraciones (`class`, `function`, `const|let x =`, métodos `nombre(…) {`, `computed`/`signal`) con el fin del bloque por llaves o por sangría; IDs literales (`REQ-012`, `D7`) → `grep` por palabra entera.
2. **Atajo sin modelo** (como #687): si el campo pide «todas las <categoría> con líneas» y la categoría es del índice (funciones, métodos, clases, secciones, ficheros, requisitos), contesta el programa. En un diff, **todo** campo de ubicación que nombre ficheros se resuelve por programa, sin depender de una lista cerrada de palabras.
3. **En el resto, el modelo devuelve anclas, no números**: `{"nombre": "...", "ancla": "<texto copiado de una línea>"}` por elemento. El programa busca el ancla (literal, tras normalizar espacios); si la encuentra una vez da `inicio-fin` con el bloque del índice que la contiene; si no la encuentra o la encuentra varias veces, `null` para ese elemento y aviso. Nunca devuelve un número que no haya calculado él.
4. **La verificación pasa a ser exacta** (el ancla está o no está), y la verificación por palabras de `check_values` queda solo para las respuestas en prosa de `local_explain_code`.
5. Los campos de ubicación van como mínimo al rol `long`, y al rol `code` cuando el fichero es código.

- Alcance: `server.py` (rama `numbered` de `local_extract`), módulo nuevo para el índice estructural, `line_check.py` (la verificación de extract), prompt `_EXTRACT_LINES_CLAUSE` sin el ejemplo «Título».
- Tests que discriminan: el `.ts` de 906 líneas y 60 funciones da las 60 exactas, **sin llamar al backend** y con 0 en `lines_unverified`; el `.ts` con JSDoc de viñetas devuelve 309 (`localOrder`), 311 (`orderDirty`), 317 y 322 (handlers), nunca 75-81; un Markdown con 60 `REQ-0NN` da la línea exacta de cada uno; un ancla inexistente da null y aviso, nunca un número; `lista_de_ficheros_con_sus_lineas` sobre un patch da los mismos rangos que `ficheros_con_lineas`. Control positivo: un mutante que suma 1 a las líneas del índice hace fallar cada uno de estos tests.
- Riesgo: alto, es el núcleo de #568, #594, #633 y #666. Hace falta inventario de sus tests antes de tocar nada: los que fijan la forma del valor («Título: líneas X-Y» como cadena) cambiarán de forma, y eso se decide y se escribe en el spec, no se descubre al ver el CI. Cambio de contrato visible: los valores de ubicación pasan a ser lista de `{nombre, lineas}`; hay que documentarlo en el CHANGELOG, el README y la wiki. Es implementable hoy si el índice de código se limita a Python y TS/JS.

### R2. Contrato tipado y validación con un reintento (C3, C4). Cierra #692 y la parte de #698 de rangos sin nombre

- Esquema por campo: los campos en plural o de ubicación pasan a `array` de cadenas o de objetos `{nombre, ancla}`; `boolean` solo cuando el nombre es una pregunta (`es_`, `tiene_`, `is_`, `has_`); el resto, `string|number|null`. Se valida después de parsear; si un valor no cuadra con su tipo, **un** reintento que le dice al modelo qué falló; si vuelve a fallar, null con aviso (`type_mismatch_keys`).
- `max_tokens` de la llamada única a la medida: proporcional al número de campos y de elementos esperados, con tope en el contexto del modelo, en vez de 512 fijo.
- Tests: Markdown de 6 K con «tres reglas» → lista de 3 cadenas; un valor `true` inyectado en un campo de lista (backend falso) → reintento y, si persiste, null con `type_mismatch_keys`; los tests de esquema actuales (`gemma3-4b` anidando objetos) siguen en verde.
- Riesgo: medio. Volver a permitir arrays reabre el anidado que justificó el esquema primitivo; se acota con `items` primitivos u objetos de dos claves fijas.

### R3. Entrada validada antes de cualquier llamada (C5). Cierra #693

- En `_read_input`, antes de decodificar: un fichero con bytes NUL, una firma conocida (PNG, JPEG, GIF, PDF, ZIP) o más del 10 % de bytes de control es binario y da `InputError`, que para imágenes remite a `local_describe_image`. Vale para todas las tools con `path`.
- Tests: PNG, JPEG y PDF sintéticos → error y 0 llamadas al backend; un Latin-1 con `²`/`³` y un UTF-16 con BOM siguen leyéndose (los tests de #672 intactos).
- Riesgo: bajo. Un log con algún byte de control suelto no debe caer: por eso el umbral va por proporción y no por un solo byte.

### R4. Redes del lint exactas (C2 en lint). Cierra #688 y #690

- `files_by_frequency`: unir rutas que son sufijo una de otra (la absoluta de pytest con la relativa), descartar lo que está dentro de una URL (`https?://…`) y, para pytest, quitar la lista de ficheros sin hallazgos del inventario que se le da al modelo.
- `invented_files`: comprobar la **ruta completa** y cada prefijo de carpeta que nombre el resumen (también sin extensión) contra los prefijos del log; nada de aceptar por nombre base cuando el resumen da una ruta con carpetas.
- Prompt de lint: «copia las rutas tal como aparecen en la entrada».
- Tests: la salida de pytest de #688 da 1 fichero y 1 aviso; un resumen con `projects/knowledge/` sobre un log con `knowledge/` → aviso de carpeta inventada; los tests de #525 y #641 intactos.
- Riesgo: bajo o medio; el cambio de `mentions` toca también a `not_mentioned`, así que hay que pasar la suite de lint entera.

### R5. Secciones que no caben: reintento, nunca relleno (C4 en summarize). Cierra #691

- `sections.complete` deja de insertar «(sin resumir)» en el cuerpo: las secciones que faltan se reintentan una vez agrupadas en una llamada propia; lo que siga faltando sale **una vez**, en el aviso, con sus títulos.
- Tests: un Markdown de 80 K con 40 secciones `##` y un backend falso que omite 6 → 0 «(sin resumir)» en el cuerpo, 1 reintento, aviso con 6 títulos y sin títulos duplicados; los tests de #593 y #558 intactos.
- Riesgo: medio; un reintento más alarga la llamada (y #537 ya era de lentitud). Con tope de una vuelta.

### R6. Límites del modelo, documentados y con aviso por programa (C7). Cierra #695 y #699 como «limitación del modelo, documentada»

- #699: si la pregunta a `local_describe_image` es de medida (altura, ancho, alineación, desborde, recorte, píxeles), el programa añade el aviso «no fiable para medidas: mide en el DOM» y la instrucción al modelo de decir «no se puede afirmar» en vez de suponer. Amplía el aviso de #663, que solo cubría desalineaciones.
- #695: con `focus` que pide valores literales (opciones, flags, códigos), un aviso de que las parejas valor → definición del resumen hay que comprobarlas en la fuente. Opcional, si da tiempo: un detector como el de filas cruzadas de #650, que avise cuando la frase del resumen sobre `X` comparte más palabras con la definición del elemento vecino que con la suya.
- Documentar las dos limitaciones en la wiki y en la skill.
- Riesgo: bajo.

### R7. Cortar el amplificador del cliente

- Skill, memoria y hook: recomendar `…_con_lineas` solo para Markdown, diffs y código con declaraciones (lo que cubre R1), y decir que ante `lines_unverified` se use `grep -n`, no el fichero entero.
- En el aviso de un fallo determinista (JSON cortado, tipo equivocado): «repetir la misma llamada da lo mismo».

### Orden propuesto para hoy (máximo 2 agentes con código a la vez)

1. En paralelo: **R3** (pequeño) y **R4** (pequeño). Cierran #693, #688 y #690.
2. **R2**, que prepara el contrato que usa R1. Cierra #692.
3. **R1**, el grande, con su spec (nivel `standard`). Cierra #694, #696, #697 y #698. En paralelo, **R5** (cierra #691) y **R6** (cierra #695 y #699).
4. R7 junto con la documentación de la release (CHANGELOG, README y `docs/wiki/`).

Prueba en vivo al final, una sola ventana de prueba y con al menos 8 GB libres, con las entradas sintéticas de hoy (generador `gen.py` del scratchpad; conviene copiarlo a `scripts/dev/` como fixture si se quiere reutilizar).

## 8. Entradas y salidas de las pruebas de hoy

| Id | Llamada | Resultado |
|---|---|---|
| D | extract `big.patch` (104 KB, 26 ficheros), `ficheros_con_lineas` | 26 rangos exactos, por programa, 0,9 s |
| F | extract `fake.png` (3 KB), `campo` | leído como latin-1, 1 llamada a `gemma3-4b`, `campo: null` |
| C | extract `linter_notes.md` (3,5 K), `tres_reglas_desactivadas` | correcto (`"MD013, MD033, MD041"`) |
| G | lint_summary salida de pytest (732 chars) | URL del pie listada como fichero «sin errores» |
| B | extract `steps_panel.ts` (5 K, 450 líneas), `orden_local_y_barra_con_lineas` | `gemma3-4b`, corte y 3 trozos: JSDoc 75-81 + 148-297 + 300-450, sin aviso |
| A | extract `big_component.ts` (44 K, 906 líneas), `funciones_con_lineas` | `gemma4-26b-a4b`, corte y 3 trozos, 106 s: 60/60 correctas, 20 marcadas como dudosas por error |
