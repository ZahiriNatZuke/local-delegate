# Implementation plan: local_extract: aviso de valor cruzado entre claves y subida al rol long en tablas (#586)

## Approach

La puerta (T1) ya está medida (`verification.md`, «Puerta (T1)»): **el enrutado pasa y el aviso
falla**. Se aplica la rama «Pasa / Falla» de «Puertas» de la spec, decidida antes de medir: este
plan construye y publica solo el enrutado; el aviso vuelve a diseño en un cambio SDD nuevo con su
propia puerta. T4 y el commit del aviso de T5 quedan `[-]`.

- **Un módulo puro y nuevo**, sin importar `server`, como ya hace `line_check`: `table_detect.py`
  con `has_table`, la pieza reutilizable de la decisión D3.
- **Cableado en `local_extract` (T5, único dueño de `server.py`)**:
  - El rol se decide después de `_read_input` (hoy antes, `server.py:7971-7975`). `_role_for_size`
    no cambia; una función propia de extract la envuelve: si el tamaño da `mechanical`, el
    interruptor está encendido y `has_table(content)`, el rol es `long`. Sin mínimo de campos
    (D12).
  - El motivo (`role_reason`) viaja en la entrada en vuelo o en el token de la operación, para que
    llegue tanto a la fila que escribe `_chat` o `_chat_map_reduce` como a las de `_log_stopped`
    (`server.py:2163-2219`).
  - `role_reason` entra en `_local_delegate`, también en las respuestas de error (`:8124-8128`).
- **Configuración**: `EXTRACT_TABLE_LONG = _env_flag("LOCAL_DELEGATE_EXTRACT_TABLE_LONG", True)` en
  `config.py`, junto al umbral (`:316`). Entra sola en `config.ENVIRONMENT_VARIABLES`.
- **Documentación** en una tarea aparte, que entra después del código, con un guardián que cuenta
  las superficies por programa.

El prompt no cambia: no hay frontera nueva en `scripts/build_corpus.py::PROMPT_BOUNDARIES` ni
cuerpos de petición que regenerar. Ningún test existente se edita (REQ-035). Si un test existente
falla, se para y se escala; no se retoca el test.

## Ordered tasks

Orden, todo en serie: T2, T3, T5, T6, T7 y, tras mezclar, T8. T1 está hecha y T4, retirada; ninguna
tarea depende de T4. T6 puede redactarse mientras corre T5, pero su commit entra detrás del de T5,
para que ningún commit de la rama empujada deje un test en rojo.

Reglas para todas: comandos pesados (pytest, `ruff`, build) de uno en uno en toda la máquina, con
el cerrojo de comandos pesados y `pytest -n 2`; en un worktree, `PYTHONPATH=src`; commits firmados y
sin coautoría; `personal-security-check` antes de cada commit; datos inventados en casos y
fixtures; al terminar, ningún proceso ni espera en marcha. Toda llamada en vivo va dentro de una
ventana de prueba (`local-delegate test-window start --label …`, `stop <id>`), agrupada por modelo
y de una en una.

- [x] T1 — Puerta de medición por el producto, antes de tocar `src/` (REQ-001, REQ-002, REQ-003, REQ-006, REQ-007; y la puerta del aviso, ahora en «Non-goals» de la spec)
  - Files or modules: `.sdd/changes/extract-cross-fill-and-routing/holdout/`, `gate/`, `outputs/gate-*.json` y la sección «Puerta (T1)» de `verification.md`
  - Verification: hecha el 2026-11-10. Enrutado pasa (0 de 8 cruces, 0 de 44 claves falladas, ni `error` ni `raw`, mediana 2,944 s, `extraer-toml-2k` sin tabla); mínimo de campos 1 (7 de 8 claves solas cruzan); aviso falla (1 aviso en falso en cada pasada, `c01/price`). Ver «Puerta (T1)» más abajo
  - Depends on: none
- [ ] T2 — Fixtures de los casos para la suite (REQ-008, REQ-012)
  - Files or modules: `tests/fixtures/extract_table_routing/` (nuevo: copia de los 17 ficheros de `cases/` y de `cases.json`, y un `README` de una línea con el origen)
  - Verification: un recuento por programa da 26 casos y 130 claves, 16 de los 22 pequeños con tabla según `cases.json`; ningún dato real; el sdist no arrastra nada de `.sdd`
  - Depends on: T1
- [ ] T3 — `table_detect.has_table` (REQ-007, REQ-008, REQ-009, REQ-010)
  - Files or modules: `src/local_delegate/table_detect.py` (nuevo), `tests/test_table_detect.py` (nuevo)
  - Verification: 16 de 22 casos pequeños dan tabla y 6 no; mayúsculas, `<track>`, `<tablet>`, tubería sin separadora; `False` fijado en CSV, TSV, GFM sin tuberías externas, `|-|-|` y `<div>`; cinco entradas hostiles de 1 000 000 de caracteres bajo 1 s; importar el módulo en un proceso aparte sin que cargue `local_delegate.server`; la fuente congelada de `extraer-toml-2k` no da tabla
  - Depends on: T2
- [-] T4 — Marcadores en `no_data.py` y `cross_fill` con topes y presupuesto (los requisitos del aviso, ahora en «Non-goals» de la spec; su rediseño queda en el issue de seguimiento de REQ-039) dropped: la puerta del aviso falló (1 aviso en falso en cada pasada del conjunto a ciegas, `c01/price`; `verification.md`, «Puerta (T1)»); el aviso vuelve a diseño en un cambio SDD nuevo con su propia puerta (spec, «Puertas» y D11)
- [ ] T5 — Cableado del enrutado en `local_extract` (REQ-011, REQ-012, REQ-013, REQ-014, REQ-015, REQ-016, REQ-017, REQ-018, REQ-019, REQ-031)
  - Files or modules: `src/local_delegate/server.py` (`local_extract` y su docstring; el paso del motivo por la entrada en vuelo o el token hasta `_log_event` y `_log_stopped`), `src/local_delegate/config.py` (el interruptor), `src/local_delegate/resources/i18n/es/mcp.json`, `src/local_delegate/resources/i18n/en/mcp.json`, `tests/test_extract_table_routing.py` (nuevo; incluye el docstring)
  - Verification: tests de rol por `text` y `path`, un solo campo, interruptor, las otras tres tools, `role_reason` en respuesta (también de error) y en filas de un log temporal (camino bueno, plazo agotado, `queue_saturated`, excepción), prompt idéntico byte a byte, parámetros del rol `long` aplicados, respaldo al modelo de `code`. Si la entrada en vuelo lleva el motivo, el panel y `local_status` siguen leyendo el fichero en vuelo. Un solo commit
  - Depends on: T3
  - [-] Commit del aviso (los requisitos del aviso, ahora en «Non-goals» de la spec) dropped: misma razón que T4 (`verification.md`, «Puerta (T1)»)
- [ ] T6 — Documentación, los tres sitios de una release y guardián de superficies (REQ-032, REQ-033)
  - Files or modules: `CHANGELOG.md`, `README.md` (`:170`, `:262` y fila nueva de la variable), `docs/wiki/Tools.md` (`:24` y la sección `local_extract`, `:106-167`), `docs/wiki/Configuration.md` (`:43`, `:461` y la sección `local_extract`, `:584-617`), `docs/wiki/Architecture.md` (`:37-41`), `docs/wiki/Savings-and-metrics.md` (campo del log, junto a `routing`, `:156-164`), `docs/recipes/claude-code-integration.md` (`:61`, que hoy dice «mecánico»), `scripts/data/spanish_lexicon.json` y `tests/data/uncatalogued_exceptions.json` (solo entradas añadidas, y solo si un guardián las pide), `tests/test_extract_table_routing_docs.py` (nuevo)
  - Verification: el guardián busca los nombres en cada fichero de la lista y la clave de texto en los dos idiomas; entra en verde porque T5 ya está; lectura de las cifras contra «Coste» y «Límites» de la spec, con las de la puerta
  - Depends on: T5
- [ ] T7 — Integración y verificación de conjunto (REQ-034, REQ-035, REQ-036, REQ-037, REQ-038)
  - Files or modules: `.sdd/changes/extract-cross-fill-and-routing/verification.md`, `.sdd/changes/extract-cross-fill-and-routing/outputs/live-*.json` (nuevos)
  - Verification: suite completa; `git diff --name-status main...HEAD -- tests` con solo altas; superficies sin cambio; mutantes; prueba en vivo por el daemon; tabla antes/después; `personal-harness sdd check extract-cross-fill-and-routing` en verde antes de las puertas `quality` y `conformance`
  - Depends on: T6
- [ ] T8 — Cierre del #586, issue de seguimiento y tarjetas (REQ-039)
  - Files or modules: comentario de cierre en el issue público, issue público de seguimiento nuevo (los dos sin rutas ni contenido privado; se busca antes un duplicado), tarjetas del tablero del proyecto (buscar antes de crear), `.sdd/changes/extract-cross-fill-and-routing/handoff.md`
  - Verification: la primera línea del comentario dice que el caso de 33 KB y el aviso de cruce quedan fuera; el issue de seguimiento trae ese caso con su criterio de reapertura, el aviso con el fallo de `c01`, y `c20` y `c19`; tarjetas del seguimiento y del #630; puerta `memory` y estado `closed`. Si la prueba en vivo no pasó, el #586 sigue abierto y solo se comenta el resultado
  - Depends on: T7

## Test strategy

- Unit: `has_table` como función pura, con cadenas en línea y con los fixtures.
- Integration: `local_extract` con `_chat` sustituido o con el backend simulado de la suite, log en
  un directorio temporal y los helpers de aislamiento de entorno; ninguna prueba escribe en el log
  real ni llama al backend.
- End-to-end or manual: la prueba en vivo (T7), por el daemon y dentro de una ventana de prueba.
  La hace la sesión principal o un único agente con el backend para él.
- Security and secret scanning: `personal-security-check` antes de cada commit; pruebas de coste
  con entradas hostiles (REQ-009); fixtures sin datos reales; los issues públicos describen la
  forma de la entrada, no su contenido; ningún agente lee ni imprime la credencial del backend.

### Puerta (T1), hecha

Registro en `verification.md`, «Puerta (T1)». Lo que se hizo, por orden:

1. **Conjunto nuevo, a ciegas (puerta del aviso)**, escrito por un agente sin acceso al detector,
   con los cupos de la puerta del aviso y casos CSV y TSV; congelado con `sha256` antes de pasarle nada.
2. **Versión del detector que se congela**: copia byte a byte del prototipo, **sin la corrección
   de plurales**. La spec solo permitía esa corrección antes de congelar el conjunto a ciegas, que
   ya estaba congelado cuando empezó T1; la versión anterior de este paso la colocaba después, y
   esa contradicción se resuelve a favor de la spec (D13). Primera pasada del aviso, sin modelo,
   sobre las respuestas anotadas a mano: 1 aviso en falso. Comprobación sin backend de
   `extraer-toml-2k` (REQ-007): sin tabla.
3. **Tanda con `gemma3-4b`, conjunto nuevo**, por el MCP del daemon: segunda pasada del aviso, 1
   aviso en falso (`c01/price`). CSV: `c20` cruza con una celda vecina no pedida; `c19`, ambiguo.
4. **Tanda con `gemma3-4b`, un solo campo (REQ-002)**: 1 de 8 bien; mínimo de campos 1.
5. **Tanda con `gemma4-26b-a4b` (REQ-001, REQ-003, REQ-006)**, por un segundo proceso con el
   código publicado, log y `LOG_DIR` temporales, sin `LLAMASWAP_CONFIG` y unido al turno del daemon
   con `LOCAL_DELEGATE_TURN_URL`, validado antes con una llamada pequeña. Lo que esa vía no prueba
   (la capa MCP por HTTP, el middleware de cancelación, plazas y enfriamiento compartidos, el
   proceso instalado) lo cubre la prueba en vivo de T7 por el daemon.

Resultado: rama «Pasa / Falla» de «Puertas».

### Mutantes (REQ-036)

Cada mutante se aplica solo. Antes de correr el test se comprueba que **muta**: una llamada directa
a la función con la entrada de la columna «Sonda» da un resultado distinto del código sin mutar o,
si la sonda es de tiempo, el mutante pasa del tope (con un tope duro de 10 s) y el original no. Se
anota qué aserción dispara; si falla por otra, se corrige el test, no el mutante.

El mutante del mínimo de campos («por debajo del mínimo, rol por tamaño») y su test se retiran: el
mínimo quedó en 1 (D12). Lo sustituye el de REQ-013, en sentido contrario: que nadie vuelva a
exigir dos campos sin medir. Los mutantes del aviso salen con él.

| Mutante | Sonda | Test que debe fallar | Aserción que debe disparar |
| --- | --- | --- | --- |
| `has_table` solo mira HTML | tabla Markdown del caso 06 | `tests/test_table_detect.py` | una tabla Markdown es tabla |
| `has_table` no exige línea separadora | `a \| b \| c` en una línea | `tests/test_table_detect.py` | una tubería sin separadora no es tabla |
| `has_table` distingue mayúsculas | `<TABLE><TR>` | `tests/test_table_detect.py` | `<TABLE>` es tabla |
| `has_table` no mira el carácter que sigue a la etiqueta | `<track>` | `tests/test_table_detect.py` | `<track>` y `<tablet>` no son tabla |
| `has_table` por `re.search(r"(?:\|[^\n]*)+\n[ \t\|:]*--", text)` | tiempo: una línea de 1 000 000 de `\|` sin salto | `tests/test_table_detect.py` | termina en menos de 1 s |
| El rol se sigue decidiendo solo por tamaño | caso 01 | `tests/test_extract_table_routing.py` | la tabla pequeña va al modelo de `long` |
| Se exige un mínimo de 2 campos | caso 01 con un solo campo | `tests/test_extract_table_routing.py` | con un campo, la tabla pequeña va al modelo de `long` |
| Se cambia el modelo pero no el rol de la llamada | caso 01 | `tests/test_extract_table_routing.py` | la llamada lleva `role="long"` |
| La regla pasa `explicit=True` (sin respaldo) | caso 01 con el modelo de `long` fallando | `tests/test_extract_table_routing.py` | `fallback.answered_by` es el modelo de `code` |
| El interruptor del enrutado no se lee | caso 01 con el interruptor apagado | `tests/test_extract_table_routing.py` | apagado, va al modelo mecánico |
| La regla se mete en `_role_for_size` | `local_summarize` con el caso 06 | `tests/test_extract_table_routing.py` | las otras tres tools siguen en `mechanical` |
| La regla añade una frase al `system` | caso 01 | `tests/test_extract_table_routing.py` | `system` y mensaje idénticos byte a byte |
| `role_reason` sale siempre que el rol es `long` | caso 15 (6,6 KB) | `tests/test_extract_table_routing.py` | por tamaño no hay `role_reason` |
| `role_reason` se quita de las respuestas de error | caso 01 con el backend devolviendo texto que no es JSON | `tests/test_extract_table_routing.py` | la respuesta de error lleva `role_reason` |
| El motivo solo va en un argumento de `_chat` | caso 01 con el plazo propio agotado | `tests/test_extract_table_routing.py` | la fila de `_log_stopped` lleva `role_reason: "table"` |
| El texto de `role_reason` se añade a `warning` | caso 10 | `tests/test_extract_table_routing.py` | `warning` no existe |
| El docstring no nombra la clave nueva | `local_extract.__doc__` | `tests/test_extract_table_routing.py` | el docstring nombra `role_reason` y `LOCAL_DELEGATE_EXTRACT_TABLE_LONG` |

### Prueba en vivo (REQ-038)

Antes de mezclar, por el daemon con el paquete instalado desde la rama (un reinicio, avisado antes
porque corta el MCP de las sesiones abiertas). Las llamadas, agrupadas por modelo:

1. `local-delegate test-window start --label sdd-586-live` y anotar el id.
2. Primero los 6 casos pequeños sin tabla, después los 16 con tabla y los 4 grandes, por `path`.
   Criterios: los 6 sin tabla, con `gemma3-4b` y sin `role_reason`; los 16 con tabla, con el
   modelo de `long`, `role_reason` en la respuesta y en la fila del log; los 4 grandes, en `long` y
   sin `role_reason`; cruces en 1 caso como mucho de los 8 que cruzaban; ninguna respuesta con
   `error`/`raw`.
3. `local-delegate test-window stop <id>`; ningún proceso ni espera en marcha.

### Tabla antes/después (REQ-037)

Una fila por caso (22 pequeños y 4 grandes). «Antes» sale de las salidas grabadas de la
investigación; «después», de la prueba en vivo.

| Columna | Antes | Después |
| --- | --- | --- |
| Rol y modelo | `outputs/g3-extract.json`, `outputs/g4-extract.json` | fila del log |
| Claves acertadas y cruzadas | `outputs/evaluation.json` | misma puntuación de `evaluate.py` sobre la respuesta nueva |
| `role_reason` | no existía | respuesta y fila del log |
| Inferencia | filas de la ventana de la investigación | filas de la ventana nueva |

Controles negativos, leídos de la misma tabla: los 6 casos sin tabla no cambian de rol, de modelo
ni de valores; los 4 grandes no ganan `role_reason`.

## Migration and compatibility

- La clave `role_reason` de `_local_delegate` y su campo del log son aditivos: un lector viejo los
  ignora y una fila vieja se lee igual. Nada que migrar ni reescribir.
- La variable nueva se lee al arrancar el servidor. Apagarla devuelve el enrutado de hoy.
- Una máquina remota con una versión anterior contra el mismo backend no aplica la regla. Con esta
  versión, la aplica su propio proceso MCP y provoca el cambio de modelo en el backend compartido:
  va dicho en `docs/wiki/Configuration.md` y en el CHANGELOG.
- Vuelta atrás: el interruptor, sin publicar nada; o revertir el commit de T5.
- Release: CHANGELOG, README y `docs/wiki/` van en T6; la versión la publica la sesión principal
  con el CI de `main` en verde y los issues de la jornada cerrados.
- Cierre del #586 (D9 y REQ-039): se cierra con esta versión solo si pasa la prueba en vivo. La
  primera línea del comentario dice que quedan fuera el caso reportado (33 KB, rol `long`, fila
  que nadie pidió) y el aviso de valor cruzado; después, qué sí y con qué cifras, y los límites.
  Se abre un issue público de seguimiento con ese caso y su criterio de reapertura, el aviso (con
  el fallo de `c01`) y los CSV `c20` y `c19`, enlazado desde una tarjeta del tablero.

## Plan review

- [ ] Every requirement maps to at least one task and verification step.
- [ ] Risky or destructive operations have safeguards and rollback.
- [ ] Dependencies and configuration changes are explicit.
- [ ] The plan does not include unrelated work.
