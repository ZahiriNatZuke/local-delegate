# Specification: local_extract: las líneas las calcula el programa y el esquema tiene tipos por campo (#692, #694, #696, #697, #698)

## Summary

En `local_extract` con `path`, todo número de línea que devuelve un campo de ubicación lo calcula
el programa. Cuando un índice del fichero contesta (Python, TS/JS, Markdown, diff, ids como
`REQ-012`), no se llama al modelo. En el resto, el modelo elige nombres del índice o copia un trozo
literal de una línea (un «ancla»). El programa busca esa ancla exacta y calcula la línea; si no la
encuentra, o la encuentra en más de un sitio, da null con aviso. Nunca devuelve un número escrito
por el modelo. Los campos de ubicación que necesitan modelo van al rol `code` (código) o `long`,
nunca al mecánico. Además, cada campo tiene su tipo en el esquema JSON: listas donde el nombre pide
varias cosas y booleanos solo en preguntas. Si un tipo no cuadra, hay un reintento. El tope de
salida se calcula según los campos pedidos.

Cierra #692 (booleano en un campo de lista), #694 (JSDoc en vez de código), #696 (líneas
equivocadas o falsos dudosos en requisitos), #697 (null en un patch con un sinónimo del nombre) y
#698 (JSON cortado o rangos sin nombre en un `.ts` grande).

### Forma nueva del valor de un campo de ubicación

```json
"funciones_con_lineas": [
  {"name": "StepsPanel.localOrder", "start": 309, "end": 309},
  {"name": "StepsPanel.onSaveOrder", "start": 317, "end": 321},
  {"name": "orderHelper", "start": null, "end": null}
],
"ficheros_y_hunks_con_lineas": [
  {"name": "src/a.ts", "start": 1, "end": 40, "hunks": [[5, 22], [23, 40]]}
]
```

- Siempre una **lista** de objetos, también si el nombre es singular (`heading_line`,
  `REQ_012_linea`): una lista de un elemento. Si no hay ningún elemento, el valor es `null`, no `[]`.
- `name`: qué es (nombre del índice, ruta del diff, id, título o el nombre que dio el modelo).
- `start`/`end`: líneas del fichero, empezando en 1 y con los dos extremos incluidos, contadas
  partiendo solo por `\n`, como `Read`. Para leer:
  `offset=start`, `limit=end-start+1`. Los dos son `null` en un elemento que no se pudo ubicar; el
  motivo va en `_local_delegate.unlocated`.
- `hunks`: solo en elementos de un diff cuando el campo pide hunks; lista de `[start, end]`.
- Orden: el del fichero (por `start`; los no ubicados al final, en el orden en que llegaron).

## Decisions

Las tomó quien redactó este spec, siguiendo la decisión del usuario del 2026-11-23 (rediseño
completo de R1 junto con R2). Las revisiones de spec y plan pueden discutirlas.

- **D1 — Siempre lista.** Un valor por campo siempre en la misma forma, sin decidir «singular o
  plural» por el nombre. Motivo: el detector de singular de #594 (`_ONE_PLACE_WORDS`,
  `_SEVERAL_PLACES_WORDS`) es justo la clase de lista de palabras frágil que se quiere quitar, y un
  consumidor que siempre itera no falla.
- **D2 — La entrada ya no va numerada en extract.** Ni el contenido ni el catálogo del índice llevan
  números de línea. Motivo: el modelo no tiene que escribir números, y verlos lo invita a
  escribirlos (#694 copió «Título: líneas 86-93» del ejemplo). Además los números gastan casi un
  token por dígito. `local_explain_code` sigue numerado (fuera de este cambio).
- **D3 — Sin interruptor de compatibilidad.** La forma vieja (cadena «X: líneas a-b») no se mantiene
  detrás de una variable. Motivo: dos contratos doblan la matriz de pruebas (memoria
  `cubrir-la-combinacion-no-la-funcion`) y los consumidores son agentes que leen la descripción de
  la tool. Va en una versión menor (0.54.0), en «Cambiado (incompatible)».
- **D4 — El nombre del campo solo decide si hace falta el modelo, nunca de dónde salen las
  líneas.** Un nombre que no se entiende nunca acaba en null ni en números del modelo: como mucho
  pasa a la elección por el modelo, y el programa sigue poniendo las líneas (corrige la causa de
  #697).
- **D5 — Comprobación exacta.** Un ancla casa si, tras normalizar los espacios, es subcadena de
  exactamente una línea. No hay parecido por palabras ni tolerancia de ±1 línea.
- **D6 — Se retiran de extract** `lines_unverified`, `outline_copies` y `diff_files`. Siguen en
  `local_explain_code` las que ya tenía (`lines_unverified`). `section_only_keys` se conserva.

## Requirements

<!-- One block per requirement. Request quotes the literal fragment of the request, or says
"derived: <reason>". Verify starts with one method: test, cmd, manual or review. -->

- **REQ-001** — Ningún número de línea escrito por el modelo llega al valor de un campo de
  ubicación ni a `_local_delegate`. Un doble del backend que responde con números (cadena
  «X: líneas 5-9», `{"start": 5}`, `[5, 9]` o el objeto nuevo con `start`) produce elementos cuyos
  `start`/`end` salen solo del índice o de un ancla. Si no hay índice ni ancla, salen `null`.
  - Request: "las líneas SIEMPRE las calcula el programa … nunca un número del modelo"
  - Verify: test `tests/test_extract_locate_server.py::test_model_numbers_never_reach_the_value`, con control positivo (un mutante que copia el `start` del modelo lo hace fallar)

- **REQ-002** — El valor de todo campo de ubicación tiene la forma de «Forma nueva del valor»:
  lista de objetos `{"name": str, "start": int|null, "end": int|null}` (+ `hunks` en diffs que los
  piden), ordenada por `start`, con `1 <= start <= end <= total_lines`, o `null` si no hay
  elementos. Nunca una cadena ni un número suelto.
  - Request: derived: la decisión de rediseño fija «la nueva forma del valor de los campos de líneas»
  - Verify: test `tests/test_extract_locate_server.py::test_every_location_value_has_the_new_shape` (parametrizado sobre todos los caminos: índice, selección, ancla, diff, troceado)

- **REQ-003** — Índice de Python por `ast` (stdlib): funciones, `async def`, clases y métodos a
  cualquier profundidad (`Clase.metodo`), y asignaciones de módulo a un nombre. Cada entrada va
  desde su primer decorador hasta `end_lineno`. Si hay un `SyntaxError`, no hay índice y se avisa
  (REQ-022).
  - Request: "índice por tipo de fichero (Python, …)"
  - Verify: test `tests/test_locate_index_python.py` (fichero sintético con decoradores, clase anidada, `async def`, constante; líneas exactas contra el texto)

- **REQ-004** — Índice de TS/JS (`.ts .tsx .mts .cts .js .jsx .mjs .cjs`) con un analizador que
  sigue llaves y salta cadenas, plantillas con `${}` anidado, comentarios y regex literales.
  Entradas: `function` y `async function`; `class`, `interface`, `enum` y `type X =`;
  `const|let|var x =` de módulo (con `export` y `export default`); y miembros de clase:
  métodos, `get`/`set`, `async`, `static`, modificadores de acceso y `readonly`, y propiedades
  con inicializador. Una propiedad cuyo inicializador es una función flecha, `function`, `computed(…)`,
  `signal(…)` o `effect(…)` es `kind = "function_property"`; cualquier otra (`x = 5`) es
  `kind = "property"`, y `funciones_con_lineas` no la incluye. Nombre `Clase.miembro`.
  El rango empieza en la línea de la declaración o de su primer decorador (`@Input()`) y **nunca
  incluye el JSDoc ni otros comentarios previos**. Termina en la llave o en el punto y coma que
  cierra la declaración.
  - Request: "índice por tipo de fichero (… TS/JS …)"; #694, #698
  - Verify: test `tests/test_locate_index_ts.py`: (a) un `.ts` de 906 líneas con 60 funciones y métodos da las 60 entradas con sus líneas exactas; (b) un componente con JSDoc de viñetas da `localOrder`, `orderDirty`, `onSaveOrder` y `onDiscardOrder` en sus líneas, y ninguna entrada empieza dentro del JSDoc; (c) llaves dentro de cadenas, plantillas, regex y comentarios no mueven ningún fin

- **REQ-005** — Índice de Markdown (`.md .markdown .mdx`): cada título ATX fuera de bloques de
  código (`markdown_outline`), con su sección. La sección termina en la línea anterior al siguiente
  título de nivel igual o superior, o al final del fichero, sin las líneas en blanco del final. Las
  tablas (filas seguidas que empiezan por `|`), los elementos de lista y los bloques de código
  cercados son bloques que un ancla puede señalar (REQ-011).
  - Request: "índice por tipo de fichero (… Markdown …)"
  - Verify: test `tests/test_locate_markdown_ids.py::test_sections_end_before_the_next_heading_of_same_or_higher_level` y `::test_blocks_at_a_line`

- **REQ-006** — Índice de diff (un `.patch`/`.diff`, o un fichero que empieza como diff unificado),
  hecho con `line_check.diff_file_hunks`. Una entrada por fichero, con su ruta y su rango en el
  patch, y los hunks de cada uno. Las rutas y los rangos son los mismos que da hoy #665/#687 para
  los mismos patches.
  - Request: "índice por tipo de fichero (… diff …)"; #697
  - Verify: test `tests/test_extract_diff_files_names.py` y `tests/test_extract_diff_files_and_cut.py` reescritos: los patches de 92 KB, 6000 líneas, con preámbulo y sin hunks dan los mismos rangos que hoy, en la forma nueva

- **REQ-007** — Ids literales. Se reconocen de dos maneras:
  - (a) En el nombre del campo, un id «letras + dígitos», en una palabra (`D7_linea`) o en dos
    (`REQ_012_linea`), da ese id. Los ids del nombre se sacan **antes** de quitar las palabras
    cortas (como las categorías, REQ-008). Casa en el contenido como palabra entera, **sin distinguir mayúsculas ni separador**
    (`REQ_012`, `REQ-012`, `req-012`, `REQ012` son el mismo id). Si no aparece, el elemento sale
    `not_found`.
  - (b) Con una palabra de ids o requisitos en el sujeto (`requisitos_con_lineas`, `ids_con_lineas`),
    da los ids del fichero con forma estricta `[A-Z]{2,}[-_]\d{2,}` (dos o más mayúsculas, guion o
    subrayado, dos o más dígitos) y el prefijo más frecuente. Así `MD013`, `UTF8`, `H1` o `ES2020`
    (sin separador) no cuentan. La línea de un id es la de su **definición**: una
  aparición que abre un elemento de lista, un título o la primera celda de una fila de tabla. Si no
  hay definición y el id aparece una sola vez, vale esa aparición. Si hay varias candidatas, el
  elemento sale con líneas `null`, motivo `ambiguous` y hasta 5 `candidates`. El rango termina
  donde termina el bloque de la definición: una fila de tabla es esa fila; un título, su sección;
  un elemento de lista llega hasta la línea anterior a la siguiente línea no vacía con sangría
  igual o menor que la suya, o a un título (las viñetas anidadas y las líneas de continuación
  quedan dentro), sin las líneas en blanco del final.
  - Request: "índice por tipo de fichero (… ids tipo `REQ-NNN`)"; #696
  - Verify: test `tests/test_locate_markdown_ids.py::test_sixty_requirements_get_their_exact_lines` (Markdown de ~55 KB con 60 `- **REQ-0NN** — …` con viñetas anidadas, citas cruzadas entre requisitos, `MD013` y `UTF8` en el texto y una tabla de 40 filas; cada uno de los 15 campos `REQ_0NN_linea` da `start` y `end` exactos de su definición; ninguno null; `requisitos_con_lineas` da los 60 y ningún `MD013`), `::test_a_cited_id_without_definition_is_ambiguous` y `::test_id_case_and_separator_do_not_matter`; y en servidor `tests/test_extract_locate_server.py::test_the_696_fields` (el mismo fichero con `base_analisis_con_lineas` y `tabla_parametros_con_lineas`: el doble ancla una línea a mitad de la tabla y el título de la sección; vuelven la tabla entera y la sección con sus líneas exactas)

- **REQ-008** — Clasificación de un campo de ubicación por **presencia**, no por exclusión. Primero
  se buscan en el nombre las **categorías** (vocabulario cerrado por categoría, es y en, con su forma
  singular y plural): `files`, `hunks`, `sections`, `ids`, y `declarations` con subtipos
  (`functions`: funciones, métodos, `computed`, `signals`, handlers → `function`, `method` y
  propiedades con función o `computed`/`signal`; `classes` → `class`; `types` → `interface`,
  `type`, `enum`; `variables`/constantes → `variable`; `declaraciones`/símbolos → todas). Después,
  del resto se quitan las palabras de ubicación (`_LOCATION_NAME_WORDS`), los cuantificadores y toda
  palabra de 3 letras o menos; lo que queda es el **resto**. Cada categoría encontrada lleva si
  apareció en **singular** o en plural. Una palabra desconocida nunca anula una categoría: solo pasa
  al resto. `is_location_field` no cambia.
  - Request: "Reconocer los campos de líneas sin depender de una lista de palabras frágil (#697: `lista_de_ficheros_con_sus_lineas`)"
  - Verify: test `tests/test_locate_fields.py` (parametrizado): `lista_de_ficheros_con_sus_lineas`, `ficheros_con_lineas`, `files_with_lines`, `ficheros_que_cambian_con_sus_lineas` → `files` plural; `fichero_con_lineas` → `files` singular; `files_and_hunks_with_lines` → `files`+`hunks`; `funciones_con_lineas`, `metodos_y_computed_con_lineas` → `declarations/functions`; `clases_con_lineas` → `declarations/classes`; `secciones_con_lineas` → `sections`; `heading_line`, `section_line` → `sections` singular; `ids_con_lineas`, `requisitos_con_lineas` → `ids`; `REQ_012_linea` → id `REQ-012`; `orden_local_y_barra_con_lineas` → sin categoría, resto `orden local barra`

- **REQ-009** — Respuesta solo del programa. Un campo con categoría **en plural**, sin resto y con
  índice disponible lo contesta el programa con todas las entradas de la categoría (o del subtipo:
  `funciones_con_lineas` da funciones, métodos y propiedades función, no clases, tipos ni
  constantes). Una categoría en **singular** (`heading_line`, `fichero_con_lineas`,
  `funcion_con_lineas`) nunca recibe el índice entero: va a elección por el modelo con un
  elemento como máximo (REQ-010), salvo un id explícito en el nombre (`REQ_012_linea`), que lo
  contesta el programa. Si **todos** los
  campos pedidos se contestan así, no hay ninguna llamada al backend y se escribe una fila de uso
  `program_only` con `PROGRAM_MODEL`, 0 tokens y la lectura en servidor (generaliza #687). Sobre un
  patch, `lista_de_ficheros_con_sus_lineas` da los mismos elementos que `ficheros_con_lineas`.
  - Request: "Donde un índice por tipo de fichero … contesta, sin modelo"; #697, #698
  - Verify: test `tests/test_extract_locate_server.py::test_index_only_fields_never_reach_the_backend` (parametrizado: patch de 140 KB y 26 ficheros con `ficheros_con_lineas` —la forma literal de #697, sin `chunked`— y con `lista_de_ficheros_con_sus_lineas`; `.ts` de 906 líneas con `funciones_con_lineas` → exactamente las 60 funciones y métodos, aunque el fichero tenga además una clase, dos interfaces y constantes; `.py`; Markdown con `secciones_con_lineas`; Markdown con `requisitos_con_lineas`), `::test_program_only_row_is_written` y `::test_a_singular_heading_field_gets_one_heading` (#594: el doble elige un título; vuelve un elemento con su línea, nunca el esquema)

- **REQ-010** — Elección por el modelo. Un campo con categoría y resto (`funciones_que_validan_entrada_con_lineas`)
  le pide al modelo los **nombres** de las entradas que cumplen, sacados del catálogo del índice.
  Con 300 nombres o menos, el esquema lleva `enum`; con más, el nombre va como cadena libre. El
  programa empareja cada nombre exacto con el índice: con el nombre completo, o con el último
  segmento si es único (`orderDirty` → `StepsPanel.orderDirty`; si el segmento casa con varios,
  `ambiguous` con candidatas). Pone las líneas de la entrada. Un nombre que no está en el índice
  queda con líneas `null` y motivo `not_in_index`. En una categoría singular el esquema lleva
  `maxItems: 1`; si llegan más (modo libre), se quedan todos, ubicados, y `located[campo].extra`
  dice cuántos sobran.
  - Request: derived: con índice disponible, el modelo filtra y el programa ubica
  - Verify: test `tests/test_extract_locate_server.py::test_selected_names_get_the_index_lines` y `::test_a_name_outside_the_index_is_unlocated`

- **REQ-011** — Anclas. Un campo sin categoría (o sin índice) le pide al modelo, por elemento,
  `{"name", "anchor", "anchor_end"}`. `anchor` es un trozo copiado literal de una línea del
  contenido; `anchor_end` es opcional y marca la última línea. El programa normaliza los espacios
  (recorta los extremos y deja un solo espacio donde había varios) y busca el ancla como subcadena
  de **una sola línea** del fichero. Casos:
  - Una línea → `start` es esa línea. Si hay `anchor_end`, `end` es la **primera** línea después
    de `start` que lo contiene; si no aparece después, se ignora (`located[campo].anchor_end_ignored`
    lo cuenta) y se aplica la regla sin `anchor_end`. Sin `anchor_end`: si la línea está **dentro**
    de una tabla, un elemento de lista (con sus viñetas anidadas) o un bloque cercado, el bloque que
    la contiene; si **empieza** una declaración o una sección, ese bloque; si no, solo esa línea.
  - Ninguna línea: `not_found`. Más de una línea: `ambiguous`, con hasta 5 `candidates` (líneas
    calculadas por el programa). Menos de 6 caracteres que no sean espacios: `too_short`.
  - En un fichero de código con índice, un ancla cuya línea es entera de comentario da `in_comment`.
  - En los cuatro casos: líneas `null` y el motivo en `unlocated`.
  - Normalización: espacio, tabulador y cualquier otro blanco cuentan como espacio; un ancla con
    saltos de línea dentro se corta en el primero. Mayúsculas y acentos **sí** cuentan.
  - Antes que el ancla se prueba el `name`, emparejado con el índice como en REQ-010. Si el nombre
    casa y el ancla apunta a otra línea fuera de su bloque, gana el nombre y
    `located[campo].conflicts` lo cuenta.
  - Request: "en el resto, el modelo devuelve un trozo de texto copiado literal y el programa calcula las líneas exactas, o null con aviso … Comprobación exacta (no por palabras)"
  - Verify: test `tests/test_locate_anchor.py` (único, `anchor_end` normal, repetido y solo antes, bloque que empieza en la línea, ancla a mitad de una tabla de 40 filas → la tabla entera, `not_found`, `ambiguous` con candidatas, `too_short`, `in_comment`, tabuladores y espacios distintos que casan, mayúsculas distintas que **no** casan, conflicto nombre/ancla) y `tests/test_extract_locate_server.py::test_a_jsdoc_anchor_is_never_returned_as_code` (#694)

- **REQ-012** — Prompt sin números. Con campos de ubicación que necesitan modelo, ni el contenido
  ni el catálogo llevan números de línea. El catálogo (tipo y nombre de cada entrada del índice
  del **fichero entero**, sin líneas; el mismo en todos los trozos) puede ocupar hasta el 15 % del
  presupuesto del trozo; si no cabe, se omite.
  `_EXTRACT_LINES_CLAUSE` se sustituye por una cláusula que pide: elegir nombres del catálogo
  (REQ-010) o copiar una línea literal del contenido (REQ-011), copiar líneas de código y no de
  comentarios, y no escribir números de línea. No lleva el ejemplo «Título: líneas 120-160».
  - Request: derived: #694 (el ejemplo del prompt sesga hacia títulos y viñetas) y D2
  - Verify: test `tests/test_extract_line_numbers.py::test_no_line_number_reaches_the_model` (ningún `N| `, ningún «líneas \d», ningún «Título» en el sistema ni en el usuario de ninguna llamada) y `::test_the_catalogue_is_left_out_when_too_long`

- **REQ-013** — Troceado. Con campos de ubicación y el contenido por encima de `max_chars` del rol,
  los trozos cortan en los límites de los bloques de primer nivel del índice, si lo hay, y por
  párrafos si no. El programa conoce el rango absoluto de líneas de cada trozo. Un ancla se busca
  primero dentro de ese rango: si aparece una vez, vale; si aparece más de una vez dentro del
  trozo, `ambiguous` con esas candidatas; si no aparece, se busca en el fichero entero, con las
  reglas de REQ-011. Los nombres se emparejan contra el índice del fichero entero.
  Después se unen por `(name, start, end)` sin repetir, en orden de fichero. La reducción del modelo deja a
  null los campos de ubicación («Deja a null las claves de ubicación» se conserva) y nunca los
  reescribe.
  - Request: derived: #568 (unión por programa) y causa C6/troceado de §4 de la causa común
  - Verify: test `tests/test_extract_line_numbers.py::test_chunked_anchors_are_resolved_against_the_whole_file` (un ancla que aparece una vez en el fichero y cae en el trozo 3 da su línea absoluta; un ancla única en su trozo y repetida en otro da la línea de su trozo, no `ambiguous`; dos trozos que anclan el mismo elemento dan un solo elemento) y `tests/test_locate_index_ts.py::test_pieces_cut_at_top_level_blocks`

- **REQ-014** — Rol. Si al menos un campo de ubicación necesita modelo (REQ-010 o REQ-011), la
  llamada va al rol `code` cuando el fichero tiene índice de código (Python, TS/JS) y al rol
  `long` en otro caso, también con entradas pequeñas. Nunca va al rol `mechanical`. El
  `_local_delegate.role_reason` lo dice
  (`{"role", "reason": "location", "notice"}`), y la fila de uso también. Si hay a la vez tabla y
  ubicación, manda la razón de ubicación. Una llamada que contesta solo el programa no tiene rol.
  Si el rol `code` no está configurado o su modelo falla, se pasa a `long` (con el respaldo entre
  modelos que ya existe), nunca a `mechanical`.
  - Request: "Campos de líneas al rol `long` o `code`, nunca al de 4B"
  - Verify: test `tests/test_extract_locate_server.py::test_location_fields_never_go_to_the_mechanical_role` (parametrizado: `.ts` de 5 K → `code`; `.md` de 3 K → `long`; con tabla → `location`; solo índice → sin llamada)

- **REQ-015** — Esquema con tipo por campo (`extract_schema.field_kind`). Orden de decisión:
  `location` > `boolean` > `count` > `list` > `scalar` (el primero que aplica gana).
  - `location` (`is_location_field` y entrada por `path`): array de objetos `{name: string (enum y `maxItems: 1` según REQ-010), anchor: string|null, anchor_end: string|null}`, con `additionalProperties: false`, o `null`. Con `text=` un campo de ubicación **no** es `location`: sigue las reglas de abajo y vale lo de hoy (REQ-019).
  - `boolean`: `["boolean", "null"]`, si la primera palabra del nombre es de pregunta (`es`, `esta`, `son`, `tiene`, `tienen`, `hay`, `existe`, `puede`, `debe`, `usa`, `contiene`, `is`, `are`, `has`, `have`, `can`, `should`, `does`, `do`, `uses`, `contains`) o si el nombre acaba en `?`. Esta lista solo **promueve** a booleano; no saber que un campo es pregunta no lo castiga (ver `scalar`).
  - `count`: `["number", "string", "null"]`, si el nombre empieza por `number_of`, `num_`, `numero_de`, `cantidad_de`, `total_`, `count_` o acaba en `_count`, `_total` (recuentos; `_recount_lists` de #586 sigue igual).
  - `list`: `["array", "string", "number", "null"]`, con `items` `string|number`, si el nombre lleva un numeral (`dos`…`diez`, `two`…`ten`, dígitos sueltos), un cuantificador (`lista`, `list`, `todos`, `all`, `cada`, `each`) o una palabra de 4 letras o más acabada en `s` que no acaba en `ss`, `us` ni `is`. **Sin `boolean`**: es lo que corrige #692.
  - `scalar` en el resto: `["string", "number", "boolean", "null"]`. Admite booleano a propósito: un campo de sí/no cuyo nombre no empieza por un verbo de la lista (`soporta_windows`) no debe caer en reintento ni en null.
  - Ningún tipo permite objetos libres anidados: se mantiene la protección contra el anidado de gemma3-4b.
  - Request: "Esquema JSON con tipos por campo (listas permitidas, booleanos solo para preguntas)"; #692. Desviación anotada: el booleano se quita de `list` y `location` (donde causaba #692) y se mantiene en `scalar` para no romper campos de sí/no con nombre libre.
  - Verify: test `tests/test_extract_schema.py::test_field_kinds` (parametrizado: `tres_reglas_desactivadas` → `list`; `tiene_tests` y `hay_errores` → `boolean`; `tiene_dos_tests` → `boolean` (orden); `number_of_comments` → `count`; `licensed_user_limits` → `list` y acepta `14`; `status` → `scalar`; `funciones_con_lineas` con path → `location`, con `text=` → `list`) y `tests/test_core.py::test_json_schema_payload_types_each_field` (ningún `list` ni `location` admite `boolean`; ningún `items` admite objetos libres)

- **REQ-016** — Validación y un reintento. Tras parsear, cada valor se comprueba contra su tipo
  (también en modo libre, `LOCAL_DELEGATE_JSON_SCHEMA=off` o tras un rechazo del esquema). Solo
  incumplen: un booleano o un objeto en `list` o `count`; un objeto en `scalar`; un campo `location`
  que no es una lista de objetos con `name`. Un número en `list` **no** incumple (un recuento con
  nombre plural sigue valiendo). Un incumplimiento provoca **un** reintento de la llamada única.
  El reintento le dice al modelo qué campo falló y qué tipo se esperaba, y se pliega en la misma
  fila de uso. Si vuelve a fallar, ese campo queda `null` y aparece en
  `_local_delegate.type_mismatch_keys = {campo: {"expected", "got"}}`, con aviso añadido al final de
  `warning`. En el camino troceado no hay reintento: el valor de un trozo que no cuadra se descarta
  antes de unir y se informa igual. Tope de llamadas al backend de una llamada única: 1 + 1
  reintento de tipo; si la respuesta se corta, el reintento en mitades de #666 sustituye al de tipo
  (nunca los dos).
  - Request: "reintento si el tipo no cuadra"; #692
  - Verify: test `tests/test_extract_schema.py::test_a_boolean_in_a_list_field_is_retried_once` (backend falso: `true` y luego la lista → lista, 2 llamadas, 1 fila), `::test_a_mismatch_that_persists_is_null_and_said` (2 llamadas, null, `type_mismatch_keys`), `::test_free_mode_is_validated_too`, `::test_a_number_in_a_list_field_is_accepted` y `::test_a_boolean_in_a_scalar_field_is_accepted`; además todo `tests/test_extract_*.py` sin tocar los marcados «conserva» (incluidos `test_extract_placeholder_values.py` y `test_extract_cross_fill.py`, que responden números en campos plurales)

- **REQ-017** — Tope de salida a la medida. `extract_schema.output_budget(kinds, index_sizes)`:
  64 de base, más por campo 16 (`boolean`), 32 (`count`), 192 (`scalar`), 384 (`list`) y 40 tokens por elemento
  esperado (`location`). Los elementos esperados son los del catálogo cuando hay elección (REQ-010)
  y 40 cuando hay anclas. El total va con suelo 512 y techo `_EXTRACT_MAX_OUTPUT_TOKENS = 4096`.
  Se aplica a la llamada única, al reintento y a cada trozo del map. Si aun así se corta, se
  conservan el reintento en mitades de #666, la fila única y el error que dice `max_tokens`.
  - Request: "tope de salida a la medida del campo"; #698
  - Verify: test `tests/test_extract_schema.py::test_output_budget` (un escalar → 512; 60 declaraciones elegibles → 64+40·60 = 2464; techo 4096) `tests/test_extract_locate_server.py::test_the_real_max_tokens` (el `max_tokens` que llega al backend en la llamada única y en un trozo del map con 60 declaraciones elegibles es 2464) y `tests/test_summarize_word_budget.py` intacto (map con un campo escalar → `{512}`)

- **REQ-018** — Metadatos. `_local_delegate` gana:
  - `located = {campo: {"by": "program"|"selection"|"anchor", "index": "python"|"typescript"|"markdown"|"diff"|"ids"|null, "items": n, "unlocated": n}}`;
  - `unlocated = {campo: [{"name", "reason", "candidates"?}]}`, con aviso añadido al final de `warning`;
  - `type_mismatch_keys` (REQ-016).

  `section_only_keys` (#633) se sigue informando sobre los elementos ya ubicados, con la regla de
  hoy (`line_check.section_only`: sujeto con una palabra en plural y sin palabra de bloque) aplicada
  al resto del campo; un campo con categoría `sections` nunca entra. Un campo de ubicación que
  vale `null` entra en `missing_keys`, como hoy. Extract deja de emitir `lines_unverified`, `outline_copies` y `diff_files` (D6).
  - Request: derived: «null con aviso» y compatibilidad documentada
  - Verify: test `tests/test_extract_locate_server.py::test_meta_keys` y `tests/test_extract_section_lines.py::test_the_shape_of_the_issue_is_reported` (reescrito)

- **REQ-019** — Lo demás no cambia:
  - Sin campos de ubicación, o con `text=`, el prompt y la respuesta son los de hoy (salvo el tipo de
    REQ-015, donde con `text=` un campo de ubicación es `list` o `scalar`, nunca `location`).
    Test `tests/test_extract_locate_server.py::test_inline_text_keeps_todays_location_value`.
  - Se mantienen marcadores sin dato (#586), filas cruzadas (#650) y polaridad (#667), que saltan
    los campos de ubicación; también el aviso de nulls al trocear (#473), la normalización de
    claves y la regla de tabla.
  - Los textos y el orden de `warning` (#455/REQ-010) no cambian.
  - `local_explain_code` no cambia.
  - Los tests de las tablas «conserva» de `research.md` pasan sin tocarlos.
  - Request: derived: memoria `fix-sin-regresiones`
  - Verify: cmd `pytest -n 1 tests/test_extract_*.py tests/test_explain_code_*.py tests/test_core.py tests/test_summarize_word_budget.py tests/test_i18n_parity.py tests/test_no_uncatalogued_text.py` en verde, con `git diff --stat origin/main -- <tests marcados conserva>` vacío

- **REQ-020** — Documentación y versión. La descripción de `local_extract` (docstring) explica la
  forma nueva, `located`, `unlocated`, `type_mismatch_keys` y que las líneas son del programa.
  También se actualizan:
  - `CHANGELOG.md`: `[Unreleased]`, «Cambiado (incompatible)», con el ejemplo antes y después;
  - `README.md`;
  - `docs/wiki/Tools.md` (el bloque 210-242 se reescribe);
  - `resources/skills/local-delegation/SKILL.md:104-110` y `resources/memory/local-delegate.md:21`
    (la forma y que ya no hay `lines_unverified` en extract);
  - los textos nuevos en `es` y `en`.
  - Request: derived: memoria `regla-release-toca-tres-sitios` y D3
  - Verify: test `tests/test_extract_locate_docs.py` (cada superficie nombra `located`, `unlocated` y `type_mismatch_keys`, y ninguna nombra `outline_copies` como clave de extract) y `tests/test_i18n_parity.py`

- **REQ-021** — Control positivo de los tests que discriminan. Cada mutante hace fallar al menos el
  test indicado:
  - sumar 1 a las líneas del índice: REQ-003, REQ-004, REQ-005, REQ-007 y REQ-009;
  - dejar pasar el `start` del modelo: REQ-001;
  - aceptar un ancla por parecido sin mayúsculas: REQ-011;
  - `classify_field` que exige que todas las palabras del sujeto estén en el vocabulario (la regla de
    `asks_for_diff_files`): REQ-008 con el nombre de #697;
  - buscar las categorías después de quitar las palabras cortas: REQ-008 con `ids_con_lineas`;
  - dar el índice entero a una categoría singular: REQ-009 (`test_a_singular_heading_field_gets_one_heading`);
  - volver a `max_tokens=512` en `server.py`: REQ-017 (`test_the_real_max_tokens`);
  - volver a permitir `boolean` en `list`: REQ-015;
  - resolver el ancla de un trozo solo contra el fichero entero: REQ-013.
  - Request: derived: memoria `control-positivo-no-es-opcional`
  - Verify: manual tabla de mutantes en `verification.md` con el assert que dispara cada uno

- **REQ-022** — Fallo seguro y coste. Un fichero cuyo índice no se puede construir (`SyntaxError`
  de Python, llaves que no cuadran en TS/JS) no hace fallar la llamada: el índice queda vacío, las
  anclas siguen dando la línea (sin bloque) y `located[campo].index` es `null`, con aviso. El coste
  de construir el índice y resolver las anclas crece de forma lineal con la entrada: en tiempo de
  CPU, 1 MB cuesta menos de 25 veces lo que cuesta 100 KB (lo lineal da ~12–14; lo cuadrático,
  ~100). Como referencia, 1 MB tarda ~0,5 s de CPU en la PC de desarrollo. Sus expresiones
  regulares son lineales (sin retroceso catastrófico).
  - Cambio del 2026-11-23 (antes: «menos de 1 s sobre 1 MB»): el tope absoluto medía el runner y no
    el código; el mismo código daba 0,5 s en la PC y 1,25–1,7 s en el runner de ubuntu del CI. La
    proporción entre dos tamaños no depende de la máquina y es lo que protege del riesgo real, un
    coste cuadrático.
  - Request: derived: entrada no confiable; memoria de gotchas de regex
  - Verify: test `tests/test_locate_index_ts.py::test_unbalanced_braces_drop_the_index`, `tests/test_locate_index_python.py::test_syntax_error_gives_no_index`, `tests/test_locate_anchor.py::test_index_and_anchors_cost_grows_linearly` y `tests/test_locate_index_ts.py::test_typescript_index_cost_grows_linearly` (ayudante `tests/linear_cost.py`)

## Acceptance scenarios

### Scenario: lista de funciones de un `.ts` grande sin modelo (#698)

- **Given** un `.ts` de 906 líneas y 44 K con 60 funciones y métodos
- **When** se llama `local_extract(path=…, fields=["funciones_con_lineas"])`
- **Then** vuelven 60 elementos `{name, start, end}` exactos, 0 llamadas al backend, fila `program_only`, `located.funciones_con_lineas.by == "program"`

### Scenario: código pedido por descripción en un componente con JSDoc (#694)

- **Given** un componente Angular de 450 líneas con JSDoc de viñetas y, en el cuerpo, `localOrder`, `orderDirty`, `onSaveOrder` y `onDiscardOrder`
- **When** se pide `orden_local_y_barra_con_lineas` y el modelo (doble) elige esos cuatro nombres, o ancla en una viñeta del JSDoc
- **Then** los cuatro nombres salen con las líneas del índice; el ancla en el JSDoc sale `in_comment` con líneas null; la llamada fue al rol `code`

### Scenario: requisitos de un Markdown de 55 K (#696)

- **Given** un Markdown con 60 `- **REQ-0NN** — …` que se citan entre sí
- **When** se piden 15 campos `REQ_0NN_linea`
- **Then** cada uno da la línea de su definición, sin llamada al backend

### Scenario: patch con un sinónimo del nombre (#697)

- **Given** un patch de 140 KB con 26 ficheros (por encima de `max_chars` de `long`, la forma literal de #697)
- **When** se pide `ficheros_con_lineas`, y aparte `lista_de_ficheros_con_sus_lineas`
- **Then** las dos dan los mismos 26 elementos, sin llamada al backend y sin `chunked`

### Scenario: una lista que vuelve como booleano (#692)

- **Given** un Markdown de 6 K y el campo `tres_reglas_desactivadas`
- **When** el backend (doble) responde `true` y luego `["MD013", "MD033", "MD041"]`
- **Then** vuelve la lista; con `true` dos veces vuelve `null` y `type_mismatch_keys`

## Edge cases and failure behavior

- Ancla que aparece en varias líneas: null y `ambiguous` con candidatas, nunca la primera.
- El modelo devuelve la forma vieja (cadena con números): no cuadra con el tipo (REQ-016), un
  reintento y después null con `type_mismatch_keys`. Sus números nunca pasan (REQ-001).
- Un campo con categoría sobre un fichero sin ese índice (`funciones_con_lineas` en un `.md`) pasa a
  anclas (REQ-011).
- Un fichero sin extensión conocida que empieza como diff usa el índice de diff (como hoy).
- Un nombre del modelo que empareja con varios del índice por el último segmento (`init` en dos
  clases): `ambiguous` con candidatas.
- JSON cortado en la llamada única: reintento en mitades (#666). Si sigue cortado: error con
  `max_tokens`. No hay verificación `raw` de líneas.
- Respuesta que no es JSON con campos que contestó el programa: los valores del programa se quedan
  y el error va en `model_error` (#665).
- Saltos de línea: el lector (`_decode_input_file`) ya convierte `\r\n` y el `\r` suelto en `\n`
  antes de que exista el contenido; índice, anclas y líneas se calculan sobre ese texto, partiendo
  solo por `\n`. Test (`tests/test_locate_anchor.py::test_a_lone_cr_keeps_read_lines`) con un `\r`
  suelto en mitad del fichero: las líneas del programa coinciden con las del contenido leído.
  Límite aceptado: en un fichero con `\r` suelto (sin `\n`), `Read` sobre el fichero crudo puede
  contar otras líneas; con `\n` o `\r\n`, coinciden.

## Non-functional requirements

- Sin dependencias nuevas; solo stdlib (`ast`, `re`, `dataclasses`).
- Rendimiento: REQ-022. Ahorro de tokens: el contenido ya no lleva el prefijo `N| `.
- Seguridad: el fichero es entrada no confiable; el analizador no ejecuta nada (`ast.parse`, nunca
  `compile`/`eval`) y sus regex son lineales.
- Compatibilidad: incompatible a propósito (D3), documentada en REQ-020; versión 0.54.0.
- Operabilidad: `located` y `unlocated` dicen siempre de dónde salió cada línea o por qué falta.

## Non-goals

- `local_explain_code` (citas en prosa, `line_check.check`): fase 2 de R1, otro cambio.
- Índices de otros lenguajes (Go, Rust, Java…): sus ficheros usan anclas sin bloque.
- Detección de binarios y redes de `local_lint_summary` (R3, R4): SDD `text-tools-binary-and-lint-paths`.
- R5 (`summarize`, secciones sin resumir), R6 (límites del modelo) y el resto de R7 (consejos del
  hook y del aviso de fallo determinista).
- Un interruptor para volver a la forma vieja (D3).
- Ubicar líneas con `text=`.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
