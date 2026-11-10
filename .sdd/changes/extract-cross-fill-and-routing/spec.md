# Specification: local_extract: aviso de valor cruzado entre claves y subida al rol long en tablas (#586)

## Summary

`local_extract` deja de contestar en silencio con el valor de otra fila cuando la entrada es una
tabla pequeña: esa entrada va al rol `long` aunque no pase del umbral de tamaño. La respuesta y la
fila del log dicen que fue por la tabla, y una variable de entorno lo apaga.

**El aviso de valor cruzado no entra en esta versión.** Tenía su propia puerta y falló: el detector
dio 1 aviso en falso en cada pasada del conjunto nuevo escrito a ciegas (caso `c01`, número
repetido con etiqueta sinónima; `verification.md`, «Puerta (T1)»). Se aplicó la rama «el enrutado
pasa y el aviso falla» de «Puertas», decidida antes de medir: el enrutado sigue y se publica, y el
aviso vuelve a diseño en un cambio SDD nuevo con su propia puerta. Sus requisitos están en
«Non-goals».

El caso que abrió el #586 (página de 33 KB, rol `long`, valor de una fila que nadie pidió) **no
queda arreglado**: ya iba a `long`. Se dice así al cerrar el issue y se abre uno de seguimiento
(REQ-039).

De la petición original, «los extract con muchos campos parecidos» **no** se implementa: medido, no
separa (decisión D1). `local_summarize` (#630) queda fuera (decisión D3).

Nombres fijados por esta spec (todos en inglés):

| Sitio | Nombre |
| --- | --- |
| Variable de entorno del enrutado | `LOCAL_DELEGATE_EXTRACT_TABLE_LONG` (encendida por defecto; `0` la apaga) |
| Constante de configuración | `config.EXTRACT_TABLE_LONG` |
| Detección de tabla, reutilizable | `local_delegate.table_detect.has_table` |
| Clave de la respuesta: por qué ese rol | `_local_delegate.role_reason` = `{"role": "long", "reason": "table", "notice": "…"}` |
| Campo de la fila del log de uso | `role_reason` (`"table"`) |
| Texto (es y en) | `mcp.warning.extract_role_reason_table` |

El campo `routing` que ya existe en el log (`"affinity"`) es otra cosa y no se toca. Los nombres
del aviso (`cross_filled_keys`, `cross_fill`, `LOCAL_DELEGATE_EXTRACT_CROSS_FILL`, `cross_fill.py`,
`no_data.py`) no se escriben en esta versión.

## Decisions

Tomadas antes de escribir esta spec, con `research.md` delante. No se reabren aquí.

- **D1 — La regla es «la entrada tiene una tabla», sin umbral de campos parecidos, y va encendida
  por defecto.** En los 22 casos pequeños medidos por el producto con `gemma3-4b` (8 con cruce, 14
  limpios) la tabla dispara en 16, cubre los 8 casos con cruce (9 de 9 claves) y sube 8 de los 14
  limpios. Contar campos con palabras en común no separa: con 2 o más deja fuera 2 de los 8 casos
  con cruce (02 y 12), con 3 o más deja fuera 4, y el caso 14 (siete campos, los siete con
  palabras en común, sin tabla) no cruza. El cruce es de las tablas y del modelo pequeño: 8 de 16
  casos con tabla, 0 de 6 sin tabla. Encendida por defecto: confirmado por la sesión coordinadora
  tras la revisión del 2026-11-10; el usuario no se opuso cuando se le planteó.
- **D2 — Aviso con el detector en su variante estricta, y solo aviso.** En las cuatro corridas de
  la investigación la estricta no dio ningún aviso en falso: 282 claves sin cruce, que son 130
  pares (caso, clave) distintos y 123 valores no nulos distintos. Vio 6 de 12 cruces. Las variantes
  amplia y parcial avisan en falso 19 y 22 veces (7 y 10 pares distintos). **Superada por D11**: la
  puerta del aviso falló y el aviso sale de esta versión.
- **D3 — `local_summarize` (#630) queda fuera.** Dos resúmenes no son una cifra; solo uno de los
  cuatro defectos del #630 nace de una tabla; summarize tiene un espejo en los hooks
  (`hook_common.py:998-1004`) y más volumen (589 llamadas frente a 76 de extract, 66 pequeñas). Se
  mide aparte. Lo único que este cambio le deja preparado es la función de detección de tabla,
  escrita como pieza reutilizable.
- **D4 — La regla se puede apagar y el cambio de rol se ve.** Una variable de entorno, con el
  estilo de las que ya hay (`LOCAL_DELEGATE_FALLBACK`, `LOCAL_DELEGATE_STRUCTURED_SUMMARY`), apaga
  el enrutado; el motivo del rol queda en la fila del log y en la respuesta. Motivo: la regla sube
  la latencia y provoca cambios de modelo en un backend compartido; quien lo sufra tiene que poder
  ver por qué y quitarlo sin tocar código.
- **D5 — Puerta de validación antes de implementar.** La cifra «`gemma4-26b-a4b` no cruza en
  tablas pequeñas» salió por un sustituto; el cambio anterior sobre esta tool (#621) pasó tests y
  revisión y falló en vivo. Por eso la primera tarea midió por el producto.

Decisiones de la sesión coordinadora tras la revisión adversarial del 2026-11-10
(`plan-review-1.md`):

- **D6 — La puerta va por un segundo proceso, no reiniciando el daemon**, unido al turno real
  (REQ-006).
- **D7 — El conjunto nuevo lo escribe un agente que no ha visto el detector**, con cupos
  obligatorios de las formas que dieron avisos en falso en la revisión (REQ-004).
- **D8 — El detector tendría interruptor y rastro en el log.** No aplica: el aviso no entra (D11).
- **D9 — Cierre del #586 solo si pasan la puerta del enrutado y la prueba en vivo**, diciendo en
  la primera línea que el caso reportado y el aviso de cruce quedan fuera, y con un issue público de
  seguimiento (REQ-039).
- **D10 — Cada pieza tiene su puerta, y la bifurcación se fija antes de medir.** Ver «Puertas».

Resultado de la puerta (T1), aplicado por la sesión coordinadora el 2026-11-10:

- **D11 — El enrutado pasa y el aviso falla; se aplica la rama correspondiente de «Puertas».**
  Enrutado: 0 de 8 casos cruzan con el modelo grande por el producto, 0 de 44 claves falladas en
  los limpios, ninguna respuesta con `error`/`raw`, mediana de 2,944 s y `extraer-toml-2k` sin
  tabla. Aviso: 1 aviso en falso en cada pasada (`c01/price`, valor correcto). Detalle en
  `verification.md`, «Puerta (T1)».
- **D12 — El mínimo de campos es 1.** Con una sola clave pedida, 7 de las 8 claves que cruzaron
  vuelven a cruzar con el modelo pequeño (REQ-002): la regla dispara también con un campo y no
  hace falta constante de mínimo.
- **D13 — El detector se congeló sin la corrección de plurales.** La spec solo la permitía antes
  de congelar el conjunto a ciegas, y ese conjunto ya estaba congelado cuando empezó T1; el plan la
  situaba después, que era una contradicción, ya corregida en el plan. No cambia el resultado: el
  aviso en falso es de número repetido, no de plurales.

Decisiones de diseño de esta spec:

- **S1 — El rol se decide después de leer la entrada.** Hoy se decide antes (`server.py:7973`,
  lectura en `:7975`). Saber si hay tabla exige el contenido. `_role_for_size` no cambia: la
  comparten cuatro tools; `local_extract` la envuelve.
- **S2 — El motivo del rol va en su propia clave, no en `warning`.** Como `chunked.notice` y
  `turn_wait.notice`: no es un fallo, y meterlo en `warning` acostumbra a ignorar los avisos y
  cambia el texto de un contrato (#455).

## Puertas

| Puerta | Requisitos | Pasa si | Resultado |
| --- | --- | --- | --- |
| **Enrutado** | REQ-001, REQ-003, REQ-007 (REQ-002 fija un valor, no para) | Se cumplen los tres criterios de REQ-001, la mediana de REQ-003 y REQ-007 | **Pasa** |
| **Aviso** | Antes REQ-004 (y REQ-005, que solo se anotaba); hoy en «Non-goals» | Se cumplen los dos criterios de la puerta del aviso: 0 avisos sobre las respuestas anotadas a mano y 0 avisos sobre las de `gemma3-4b` | **Falla** |

Qué pasa en cada combinación, decidido antes de medir:

| Enrutado | Aviso | Qué se hace |
| --- | --- | --- |
| Pasa | Pasa | El cambio sigue entero |
| **Pasa** | **Falla** | **Rama aplicada.** El enrutado sigue y se publica. El aviso no entra en esta versión: sus requisitos propios (REQ-020 a REQ-030) y la parte del aviso de REQ-031 a REQ-033 y de REQ-035 a REQ-038 salen de la spec y quedan en «Non-goals»; T4 y el commit del aviso de T5 se marcan `[-]` con el motivo; el aviso vuelve a diseño en un cambio SDD nuevo con su propia puerta. REQ-004 y REQ-005, la puerta del aviso, también pasan a «Non-goals»; sus filas de `verification.md` quedan como registro de la medición, marcadas «puerta del aviso, fuera de esta versión». La transición en `state.json` la anota la sesión coordinadora |
| Falla | Pasa | Se para y se escala: la sesión coordinadora decide si el aviso sale solo |
| Falla | Falla | Se para y se escala |

## Límites (parte del contrato)

### Lo que la regla de la tabla no ve

`has_table` da `False` en tablas reales que no son HTML ni Markdown con tuberías: **CSV, TSV, la
tabla GFM sin tuberías externas** (`Seats | Domains`, un solo `|` por línea), **el separador
`|-|-|`** (la regla exige `--`) y **las rejillas hechas con `<div>`**. Esas entradas se quedan en el
modelo mecánico y pueden cruzar: en la puerta, el CSV `c20` cruzó (el modelo rellenó una celda
vacía con la vecina de su fila, que nadie pidió) y el `c19` quedó ambiguo; los dos van al issue de
seguimiento (REQ-039). Da `True`, del lado de subir de más, en un diff de una tabla, en una cadena
de un JSON o un f-string con `<tr`, y en una etiqueta dentro de un bloque de código.

### Lo que esta versión no cubre

- El caso reportado en el #586: 33 KB, rol `long`, valor de una fila que nadie pidió. Ya iba a
  `long` y la regla no actúa; no se reprodujo con páginas inventadas de 6,6 y 29 KB.
- Ningún aviso de valor cruzado: un cruce que quede (en el rol `long`, o en una tabla que la regla
  no ve) sigue saliendo en silencio.

## Requirements

### Puerta del enrutado (antes de implementar; medida el 2026-11-10)

- **REQ-001** — Los 16 casos pequeños con tabla del conjunto (01, 02, 06, 07, 08, 09, 10, 11, 12,
  17 y 21 a 26) se miden con `gemma4-26b-a4b` por el propio `local_extract` (schema, temperatura 0,
  `max_tokens` 512 y post-proceso del producto; no por `local_delegate`). La puerta pasa si se
  cumplen las tres: en los 8 que cruzaron con `gemma3-4b` (01, 02, 06, 12, 21, 22, 23, 26) el
  modelo grande cruza en 1 caso como mucho; en los 8 limpios (07, 08, 09, 10, 11, 17, 24, 25)
  falla 1 clave como mucho de 44 (con `gemma3-4b` fueron 0); y ninguna de las 16 respuestas trae
  `error`/`raw`. Si no, falla la puerta del enrutado (ver «Puertas»).
  - Request: "medir antes de decidir"
  - Verify: manual tabla de la puerta en `verification.md` (por caso: claves, acertadas, cruzadas, falladas, inferencia) y filas del log temporal del segundo proceso con `tool: local_extract` y `model: gemma4-26b-a4b`
- **REQ-002** — Las 8 claves que cruzaron (la de 01 y 02 es la misma llamada; 06, 12, las dos de
  21, 22, 23 y 26) se piden **solas**, cada una en su llamada, por el producto con `gemma3-4b`. Si
  las 8 salen bien (el valor anotado, o `null` cuando la clave no está), el enrutado exige dos o
  más campos distintos; si alguna sale mal, dispara también con un campo. El valor queda escrito en
  `verification.md` junto a las 8 respuestas. (Resultado: 1 de 8 bien; mínimo 1, D12.)
  - Request: "medir antes de decidir"
  - Verify: manual tabla de un solo campo en `verification.md` y el mínimo de campos anotado al lado
- **REQ-003** — La puerta deja anotada la mediana de inferencia de los 16 casos de REQ-001 por el
  producto. Si pasa de 6,5 s (el doble de los 3,24 s medidos por el sustituto), falla la puerta
  del enrutado (ver «Puertas»).
  - Request: derived: el coste de la regla es la mitad de la decisión D1 y solo está medido por el sustituto
  - Verify: manual mediana, mínimo y máximo en la tabla de la puerta de `verification.md`
- **REQ-006** — La tanda con el modelo grande (REQ-001, REQ-003) va por un segundo proceso con el
  código publicado, log y `LOG_DIR` temporales, y unido al turno real del daemon. Antes de la tanda,
  una llamada pequeña sin tabla comprueba que el turno se pide al daemon: su fila del log temporal
  lleva `remote_turn` de turno concedido y el daemon muestra la operación como entrada
  `remote:<host>/<op>`. La copia del lanzador borra `LLAMASWAP_CONFIG` de forma explícita antes de
  arrancar el proceso, porque es una variable de usuario en esta máquina y la tarea programada la
  hereda. Si la comprobación falla, o el usuario no da el visto bueno para lanzar el proceso con la
  credencial del backend, la tanda va por el daemon con `LOCAL_DELEGATE_LONG_INPUT_CHARS=0`,
  avisando antes de cada reinicio.
  - Request: derived: decisión D6
  - Verify: manual registro de la comprobación en `verification.md` (fila del log temporal, entrada del daemon, visto bueno del usuario o vía usada)
- **REQ-007** — La fuente congelada del caso de corpus `extraer-toml-2k`
  (`scripts/build_corpus.py:380-390`, rol declarado `mechanical`) no trae tabla según `has_table`,
  y `tests/test_corpus.py` pasa sin tocar. Si la trajera, se para y se declara antes de seguir.
  - Request: derived: la regla cambiaría el rol declarado de un caso congelado del corpus
  - Verify: test tests/test_table_detect.py

### Detección de tabla

- **REQ-008** — `table_detect.has_table(text)` devuelve `True` si y solo si el texto trae una
  etiqueta `<table` o `<tr` (sin distinguir mayúsculas, seguida de blanco, `>` o `/`) o una línea
  con dos o más `|` seguida de una línea separadora (solo `|`, `:`, `-` y blancos, con `--`). Sobre
  los 22 casos pequeños da `True` en los 16 con tabla y `False` en los 6 sin ella (03, 04, 05, 13,
  14, 18). El texto se mira tal cual: un JSON no se trata aparte. Da `False` en las formas de
  «Lo que la regla de la tabla no ve» (CSV, TSV, GFM sin tuberías externas, `|-|-|`, `<div>`), y
  un test lo fija para que un cambio de la regla sea visible.
  - Request: "mandar al rol long las tablas"
  - Verify: test tests/test_table_detect.py
- **REQ-009** — `has_table` no usa ninguna expresión regular y su coste es lineal: cada entrada
  hostil de 1 000 000 de caracteres (`<` repetido, `<tr` repetido sin cerrar, `|` en una sola
  línea, una línea `|` por renglón, una línea separadora sin fin) se resuelve en menos de 1 s.
  - Request: derived: la entrada no es de confianza; convención del repo contra el retroceso catastrófico
  - Verify: test tests/test_table_detect.py
- **REQ-010** — `has_table` vive en un módulo propio que se importa sin cargar `server`, y
  `server.py` no repite la regla: la llama.
  - Request: derived: decisión D3; la misma función servirá a `local_summarize` cuando se mida
  - Verify: test tests/test_table_detect.py

### Enrutado

- **REQ-011** — Con el interruptor encendido, una llamada a `local_extract` cuya entrada no pasa
  del umbral de tamaño y trae tabla va al rol `long`: el modelo es el del rol `long` y la llamada
  lleva `role="long"` (tope, respaldo y parámetros de ese rol), por `text` y por `path`.
  - Request: "mandar al rol long las tablas"
  - Verify: test tests/test_extract_table_routing.py
- **REQ-012** — Una entrada sin tabla sigue el enrutado por tamaño de hoy: los 6 casos sin tabla
  van a `mechanical`, y `tests/test_core.py` y `tests/test_request_body_compat.py` pasan sin tocar.
  - Request: derived: control negativo; un arreglo no rompe otra cosa
  - Verify: test tests/test_extract_table_routing.py
- **REQ-013** — No hay mínimo de campos: con un solo campo pedido, una entrada pequeña con tabla
  también va al rol `long` (D12).
  - Request: derived: resultado de la puerta (REQ-002)
  - Verify: test tests/test_extract_table_routing.py
- **REQ-014** — Con `LOCAL_DELEGATE_EXTRACT_TABLE_LONG=0` el rol sale solo del tamaño, la
  respuesta no lleva `role_reason` y la fila del log tampoco.
  - Request: derived: decisión D4
  - Verify: test tests/test_extract_table_routing.py
- **REQ-015** — La regla solo aplica a `local_extract`: `local_summarize`, `local_lint_summary` y
  `local_translate` con una entrada pequeña con tabla siguen yendo a `mechanical`.
  - Request: derived: decisión D3
  - Verify: test tests/test_extract_table_routing.py
- **REQ-016** — La respuesta lleva `_local_delegate.role_reason` igual a
  `{"role": "long", "reason": "table", "notice": <texto>}` si y solo si la regla subió el rol,
  **también en una respuesta de error** (`error`/`raw`): quien recibe un error tras esperar al
  modelo grande sabe por qué fue a ese modelo. No aparece si la entrada ya iba a `long` por tamaño,
  si no hay tabla ni con el interruptor apagado, y no añade nada a `warning`.
  - Request: derived: decisión D4
  - Verify: test tests/test_extract_table_routing.py
- **REQ-017** — Toda fila que la operación escribe en el log de uso lleva `role_reason: "table"` si
  y solo si la regla subió el rol: la del camino bueno y las que escribe `_log_stopped`
  (`server.py:2163-2219`: cancelación, plazo propio agotado, `queue_saturated`, excepción). El
  motivo viaja en la entrada en vuelo o en el token de la operación, no solo en un argumento de
  `_chat`. `model` es el modelo que respondió, como hoy.
  - Request: derived: decisión D4; las filas de fallo son las más probables con un modelo que tarda en cargar
  - Verify: test tests/test_extract_table_routing.py
- **REQ-018** — La regla no cambia el prompt: `system` y mensaje de usuario son idénticos byte a
  byte a los de una llamada sin la regla, y no hace falta frontera nueva en `PROMPT_BOUNDARIES`.
  Lo que sí cambia es el rol de la llamada: si `backend-params.json` define parámetros para `long`
  (hoy `roles: {}`), se aplican a esa llamada y un test lo fija.
  - Request: derived: un cambio de prompt en esta tool ya se revirtió (#621)
  - Verify: test tests/test_extract_table_routing.py
- **REQ-019** — Con la regla encendida, si el modelo de `long` falla, el respaldo es el de la cadena
  de `long` (`chains.py:47-51`: `loaded` y después `code`). Como `local_extract` no tiene celdas
  de afinidad, `loaded` sale vacío y responde el modelo de `code`; un test lo fija con
  `fallback.answered_by` igual a `config.MODEL_CODE`.
  - Request: derived: la revisión encontró que el respaldo de una tabla pequeña pasa a ser el modelo de carga más cara
  - Verify: test tests/test_extract_table_routing.py

### Documentación y superficies

- **REQ-031** — La descripción de la tool (docstring, en inglés) nombra `role_reason`, la regla de
  la tabla y su interruptor; `tests/test_tool_contract.py`, `tests/test_mcp_english.py` y
  `tests/test_i18n_parity.py` pasan sin tocar.
  - Request: derived: convención del repo; toda clave nueva de `_local_delegate` va en la descripción de la tool
  - Verify: test tests/test_extract_table_routing.py
- **REQ-032** — Los nombres nuevos están en cada superficie que describe el enrutado,
  `_local_delegate` o los campos del log: `LOCAL_DELEGATE_EXTRACT_TABLE_LONG` y `role_reason` en
  `README.md`, `docs/wiki/Tools.md`, `docs/wiki/Configuration.md` y `CHANGELOG.md`; la regla en
  `docs/wiki/Architecture.md` y `docs/recipes/claude-code-integration.md`; el campo del log
  `role_reason` en `docs/wiki/Savings-and-metrics.md` (junto a `routing`, `:156-164`); y la clave
  de texto `mcp.warning.extract_role_reason_table`, en `i18n/es/mcp.json` y `i18n/en/mcp.json`.
  - Request: derived: una release toca tres sitios (CHANGELOG, README y `docs/wiki/`)
  - Verify: test tests/test_extract_table_routing_docs.py
- **REQ-033** — `docs/wiki/Tools.md` y la entrada del `CHANGELOG.md` dicen, con cifras: qué quita
  el enrutado (0 de 8 cruces por el producto en la puerta) y qué cuesta (mediana de inferencia
  de 2,944 s medida en la puerta, frente a 0,84 s; de 10 a 13 s más si el modelo no estaba
  cargado; p90 histórico de la espera con cambio de modelo, 31,9 s; que el respaldo de una tabla
  pequeña pasa a ser el modelo de `code`; efecto en los demás clientes del mismo backend); cómo se
  apaga; lo que la regla de la tabla no ve; y que el caso de 33 KB del #586 y el aviso de cruce
  quedan fuera de esta versión.
  - Request: derived: el límite se documenta, no se esconde
  - Verify: review lectura de las dos piezas contra «Límites» y «Coste» de esta spec
- **REQ-034** — Las superficies que nombran la tool pero no su rol ni sus claves no cambian: la
  skill (`SKILL.md`, `SKILL.en.md`), la memoria instalada, `tools.json`, `panel.json`,
  `install.json`, el mod (`register.js`, `mod/`), el espejo de los hooks (`hook_common.py`) y
  `web/metrics.py`.
  - Request: derived: contar las superficies con el programa, no a ojo
  - Verify: cmd git diff --name-only main...HEAD -- src/local_delegate/resources/skills src/local_delegate/resources/memory src/local_delegate/resources/claude-plugin src/local_delegate/resources/hooks src/local_delegate/web

### Verificación de conjunto

- **REQ-035** — Ningún test existente se edita ni se debilita: bajo `tests/` el cambio solo añade
  ficheros `.py` y fixtures, y en `tests/data/` solo las entradas que pida un guardián. La suite
  entera pasa.
  - Request: derived: un arreglo no rompe otra cosa
  - Verify: cmd git diff --name-status main...HEAD -- tests
- **REQ-036** — Cada mutante de la tabla del plan, aplicado solo y tras comprobar que muta (la
  sonda da un resultado distinto, o tarda más del tope cuando la sonda es de tiempo), hace fallar
  el test nombrado por la aserción nombrada; queda anotado uno a uno.
  - Request: derived: el control positivo no es opcional
  - Verify: manual tabla de mutantes rellena en `verification.md` (mutó, test, aserción que disparó)
- **REQ-037** — `verification.md` trae la tabla antes/después de los 22 casos pequeños y los 4
  grandes (rol, modelo, claves cruzadas, `role_reason`, inferencia), y en ella los 6 casos sin
  tabla no cambian de rol ni de valores y los 4 grandes no ganan `role_reason`.
  - Request: "medir antes de decidir"
  - Verify: manual tabla antes/después en `verification.md`
- **REQ-038** — Antes de mezclar, el enrutado se prueba en vivo por el daemon, con el paquete
  instalado desde la rama y dentro de una ventana de prueba. La ventana se cierra y no queda ningún
  proceso vivo.
  - Request: derived: el cambio anterior sobre esta tool (#621) pasó tests y revisión y falló en vivo
  - Verify: manual registro de la prueba en vivo en `verification.md` (id de la ventana, filas del log, respuestas)
- **REQ-039** — El #586 se cierra solo si pasan la puerta del enrutado y la prueba en vivo. La
  primera línea del comentario de cierre dice que quedan fuera el caso reportado (33 KB, rol
  `long`, valor de una fila que nadie pidió) y el aviso de valor cruzado; después, qué sí, con sus
  cifras, y los límites. Se abre un issue público de seguimiento con: ese caso y su criterio de
  reapertura (una entrada inventada que lo reproduzca); el aviso, con el aviso en falso de `c01`
  que hizo fallar su puerta; y los CSV `c20` (celda vacía rellenada con la vecina) y `c19`
  (ambiguo). Una tarjeta del tablero lo enlaza; el #630 tiene su propia tarjeta.
  - Request: "resolver los issues abiertos (#586)"
  - Verify: review comentario de cierre, issue de seguimiento y tarjetas del tablero

## Contract

### `_local_delegate.role_reason`

```jsonc
// entrada pequeña con tabla, interruptor encendido
{ "seats": "5", "_local_delegate": { "role_reason": { "role": "long", "reason": "table", "notice": "…" } } }

// la misma, con el backend fallando: el motivo sigue
{ "_local_delegate": { "error": "…", "raw": "…", "role_reason": { "role": "long", "reason": "table", "notice": "…" } } }
```

`notice` sale en el idioma del servidor y dice que la entrada trae una tabla, que por eso fue al
modelo de contexto largo, que tarda más y puede tener que cargarse, y que
`LOCAL_DELEGATE_EXTRACT_TABLE_LONG=0` lo apaga.

### Campo del log

| Campo | Valores | Cuándo |
| --- | --- | --- |
| `role_reason` | `"table"` | La regla subió el rol; en toda fila de la operación, también las de `_log_stopped` |

### Convivencia

| Clave que ya existe | Con `role_reason` |
| --- | --- |
| `missing_keys`, `renamed_keys`, `dropped_keys`, `dropped`, `placeholder_keys`, `recounted_keys`, `outline_copies`, `lines_unverified` | Sin relación |
| `chunked` | Pueden ir juntas si el tope del rol obliga a trocear |
| `fallback` | Pueden ir juntas: `role_reason.role` es el rol decidido y `fallback.answered_by`, quien respondió (con la regla, el modelo de `code`) |
| `truncated`, `warning` | No toca `warning` |
| `read_server_side`, `turn_wait` | Sin cambio |
| `error`, `raw` | Aparece si la regla subió el rol |

### Entradas

| Entrada | Enrutado |
| --- | --- |
| `text` | Tamaño en caracteres; si no pasa del umbral, se mira la tabla |
| `path` | Tamaño en bytes; si no pasa del umbral, se mira la tabla en lo leído |
| Por encima del umbral | Ya va a `long`: no se mira la tabla y no hay `role_reason` |
| Troceada | `role_reason` solo si la regla subió el rol |
| JSON | No hay «tabla» salvo que el texto traiga `<table`/`<tr` |

## Coste

Medido en una PC compartida de 32 GB con los modelos de texto en un grupo donde cargar uno descarga
el otro:

- Inferencia de una entrada pequeña con tabla: 0,84 s de mediana con `gemma3-4b`; con
  `gemma4-26b-a4b` por el producto, en la puerta, 2,944 s (entre 1,918 y 6,085 s).
- Si el modelo grande no estaba cargado: de 10,4 a 10,9 s más (16,5 y 21,8 s con dos llamadas a la
  vez). Histórico de la espera con cambio de modelo: mediana 12,7 s, p90 31,9 s (115 llamadas).
- La siguiente llamada mecánica paga la vuelta: unos 5 s.
- Una llamada pequeña que obliga a cambiar pasa de 1 s a unos 14 s.
- **Respaldo**: si falla el modelo de `long`, responde el de `code` (`qwen36-35b-a3b`, 17,7 GB, el
  de carga más cara), no el que hoy respalda a `gemma3-4b`. No está medido.
- Volumen: entre 0 y 17 llamadas reales en casi cuatro meses (como mucho el 22 % de las 76 a
  `local_extract`). Con un solo campo también sube (D12), que no cambia ese techo: estaba contado
  por llamadas.
- Mientras el backend cambia de modelo, los demás clientes que lo comparten (otra máquina, otras
  sesiones) lo ven arrancando, y con el modelo grande cargado una llamada mecánica ajena la puede
  contestar él.

La regla la decide el proceso MCP de cada cliente: una máquina remota con esta versión también
sube sus tablas y provoca el cambio de modelo en el backend compartido; el interruptor se pone en
el entorno de cada cliente y se lee al arrancar.

Se le dice a quien llama en dos sitios: en la respuesta (`role_reason.notice`) y en la
documentación (REQ-033).

## Acceptance scenarios

### Scenario: tabla pequeña con el enrutado encendido

- **Given** la tabla HTML del caso 01 (949 caracteres), cinco campos y la configuración por defecto
- **When** se llama a `local_extract` por `path`
- **Then** la llamada va al modelo del rol `long`, la respuesta lleva `role_reason` con
  `reason: "table"` y la fila del log lleva `role_reason: "table"`

### Scenario: tabla pequeña con un solo campo

- **Given** la misma tabla y solo el campo `licensed_user_limits`
- **When** se llama a `local_extract`
- **Then** la llamada también va al modelo del rol `long`

### Scenario: entrada pequeña sin tabla

- **Given** el fichero de líneas `clave = valor` del caso 14 y siete campos
- **When** se llama a `local_extract`
- **Then** la llamada va al modelo mecánico y ni la respuesta ni el log llevan `role_reason`

### Scenario: plazo agotado con el modelo grande

- **Given** una tabla pequeña, el enrutado encendido y un plazo propio que vence mientras carga el
  modelo grande
- **When** la operación se corta
- **Then** la fila que escribe `_log_stopped` lleva `role_reason: "table"`

### Scenario: interruptor apagado

- **Given** `LOCAL_DELEGATE_EXTRACT_TABLE_LONG=0` en el entorno del servidor
- **When** llega una entrada pequeña con tabla
- **Then** va al modelo mecánico, como antes de este cambio

### Scenario: pasa la puerta del enrutado y falla la del aviso (ocurrido)

- **Given** la puerta del enrutado pasa y el conjunto nuevo da un aviso en falso
- **When** se cierra la primera tarea
- **Then** el enrutado sigue y se publica, y el aviso sale de esta versión y vuelve a diseño con su
  propia puerta, como fija «Puertas»

## Edge cases and failure behavior

- Fichero que no existe, ruta protegida o `fields` vacío: los mismos errores de hoy, antes de mirar
  ninguna tabla.
- `<table` o `<tr` dentro de un bloque de código, de una cadena de un JSON, de un f-string, de un
  diff o de un comentario: dispara la regla. El error cae del lado de subir de más.
- CSV, TSV, GFM sin tuberías externas, `|-|-|` y rejillas `<div>`: la regla no las ve y la llamada
  se queda en el modelo mecánico. Límite documentado.
- `<track>`, `<tablet>` o una tubería de shell (`a | b | c`) sin línea separadora: no son tabla.
- El backend falla o el modelo no devuelve JSON: respuesta de error de hoy, con `role_reason` si la
  regla había subido el rol; la fila del log también lo lleva.
- Con el rol `long` el respaldo es el de ese rol (modelo de `code`); si responde, `fallback` lo dice
  como hoy.
- Un cliente con una versión anterior contra el mismo backend: no aplica la regla; nada que migrar.

## Non-functional requirements

- **Seguridad**: sin dependencias nuevas. `has_table`, sin expresiones regulares y lineal. Ningún
  agente lee ni imprime la credencial del backend.
- **Privacidad**: al log de uso va únicamente `role_reason`, un valor fijo. Fixtures y casos con
  datos inventados.
- **Rendimiento**: `has_table` solo corre cuando la entrada no pasa del umbral. El coste de latencia
  de la regla va en «Coste».
- **Compatibilidad**: la clave y el campo nuevos son aditivos; ninguna clave ni texto existente
  cambia. El interruptor devuelve el enrutado de hoy.
- **Operación**: el interruptor se lee al arrancar el servidor; cambiarlo exige reiniciarlo.
- **Idioma**: identificadores, claves y docstring en inglés; textos de salida en español e inglés.

## Non-goals

- **El aviso de valor cruzado** (rama «Pasa / Falla» de «Puertas»; vuelve a diseño en un cambio SDD
  nuevo, con su propia puerta). Salen de esta spec:
  - Antes REQ-020: el detector estricto marca las mismas claves que el prototipo congelado.
  - Antes REQ-021: forma de `_local_delegate.cross_filled_keys`, con el valor del modelo intacto.
  - Antes REQ-022: texto del aviso en es/en, añadido al final de `warning`.
  - Antes REQ-023: claves que el detector no examina (nulas, recontadas, de ubicación, descartadas).
  - Antes REQ-024: entrada troceada, `text` y `path`.
  - Antes REQ-025: topes y presupuesto del detector (`MAX_COMPARISONS = 200_000` y demás constantes),
    con un test que cuenta comparaciones.
  - Antes REQ-026: el detector no rompe la tool; fallo a `daemon-errors.log` bajo el daemon y a stderr
    fuera de él.
  - Antes REQ-027: interruptor `LOCAL_DELEGATE_EXTRACT_CROSS_FILL`.
  - Antes REQ-028: campo `cross_fill` solo en el log.
  - Antes REQ-029: lista de marcadores en `no_data.py`, comprobada por identidad.
  - Antes REQ-030: control positivo por intercambio de valores.
  - Y la parte del aviso de REQ-031 a REQ-033 (docstring, superficies, documentación del límite),
    de REQ-035 (mover la excepción de «sin información»), de REQ-036 (sus mutantes), de REQ-037
    (claves avisadas) y de REQ-038 (fase 1 de la prueba en vivo).
  - La corrección de plurales del detector no se aplicó (D13) y queda para ese diseño.
  - Antes REQ-004, la puerta del aviso: conjunto nuevo escrito a ciegas, con cupos de formas, y
    0 avisos en falso como criterio, sin modelo y con `gemma3-4b`. Medida en T1: 1 aviso en falso
    en cada pasada (`c01/price`). Su fila de `verification.md` queda como registro de esa medición,
    marcada «puerta del aviso, fuera de esta versión».
  - Antes REQ-005, el caso CSV del conjunto nuevo: `c20` cruza con una celda vecina no pedida y
    `c19` queda ambiguo; los dos van al issue de seguimiento (REQ-039). Su fila de
    `verification.md` queda como registro, con la misma marca.
- `local_summarize`, `local_lint_summary` y `local_translate` no cambian de enrutado (#630 se mide
  aparte), ni el espejo de los hooks.
- No se enruta por número de campos parecidos ni se mueve `LOCAL_DELEGATE_LONG_INPUT_CHARS`.
- La regla no se amplía a CSV, TSV ni rejillas `<div>` en este cambio; `c20` y `c19` van al issue
  de seguimiento.
- No se toca el prompt de `local_extract` ni su schema.
- El panel y el mod no muestran el motivo del rol.
- No se cambia el catálogo de modelos, la cadena de respaldo ni el grupo de carga del backend.
- No se arregla el caso de 33 KB del #586; queda en el issue de seguimiento.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.

Pendientes: no queda ningún marcador de pendiente en esta spec. Los identificadores REQ-020 a
REQ-030, y REQ-004 y REQ-005, no se reutilizan: están en «Non-goals». REQ-001 a REQ-003, REQ-006 y REQ-007 ya están medidos
(`verification.md`, «Puerta (T1)»).
