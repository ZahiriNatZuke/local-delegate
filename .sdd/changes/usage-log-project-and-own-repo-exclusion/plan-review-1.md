# Revisión adversarial 1 de la especificación y el plan

Cambio: `usage-log-project-and-own-repo-exclusion` (nivel standard). Fecha: 2026-11-10. Revisado
contra `main` en `da78ce70`. Solo lectura del código; lo único escrito es este fichero.

## Veredicto

**APROBABLE CON CAMBIOS.** Las puertas `spec` y `plan` no deben aprobarse hasta aplicar los cinco
hallazgos bloqueantes (1 a 5). Son cambios de texto en `spec.md` y `plan.md`; no hace falta
reinvestigar. El diseño de fondo se sostiene y casi todas las citas `fichero:línea` son correctas.

## Qué se comprobó contra el código y resultó cierto

| Afirmación de los artefactos | Comprobación |
| --- | --- |
| Un solo punto de escritura del log | `server.py:1312` (definición), llamadas en `:2176`, `:4394`, `:5135`, `:5951`, escritura en `:1595` |
| `resolve_call` y lo que devuelve acaba en la fila | `attribution.py:195-239`; `server.py:1417-1428` hace `rec.update(attribution.current_call())` |
| Validación de la ruta del transcript | `attribution.py:96-108` (`_safe_path`) |
| La nota de un subagente trae el transcript del principal | `attribution.py:111-128` (`_transcript_de`) |
| El respaldo del hilo es `subagent` | `cost.py:29` (`DECLARED_FALLBACK`), aplicado en `cost.py:198-199` |
| `write_backfill` no enriquece el mismo rango | `attribution.py:421-425`: `old_entry is None or _rank(new) > _rank(old)` |
| `match_lines` vuelve a pasar por todas las filas de la ventana | `transcripts.py:314-316` (`needs_backfill`) y `recompute.py:345-350`: se le pasan filas crudas, que nunca traen `n` |
| `/api/stats?session=` y su uso por el mod | `metrics.py:574-577`, `:601-604`; `mod/status.js:656` (copia en `register.js:1515`) |
| `_usage_rows` es la costura que aparta pruebas | `metrics.py:516-533`, usada en `:545` y `:578` |
| El coste ve todas las filas del rango | `metrics.py:587-591` |
| `/api/hooks` solo aparta ventanas de prueba | `metrics.py:727-774` |
| `buildQuery(range, includeTests, lang)` y las tres peticiones | `metrics.py:2324-2331`, `:2335-2347` |
| `mod_calls` con `is_mod_call` | `metrics.py:396-398`; `attribution.py:476-484` |
| `local_status` cuenta el mes sin pruebas | `server.py:9486`, `:9534-9576` |
| 16 y 7 tests de hoy en los dos scripts | `tests/test_measure_adoption.py` (16), `tests/test_measure_plugin_adoption.py` (7) |
| Test de navegador que sirve de molde | `tests/test_dashboard_ui.py:1901` |
| Tocar `hook_common.py` no cambia la huella de un hook | `hook_common.py:137-142`: la huella es el script, más `read_classifier.py` para dos hooks; `tests/test_hook_boundaries.py:60` excluye `hook_common.py` |

Otras comprobaciones:

- **Reparto en paralelo**: ningún par de tareas del mismo grupo comparte fichero. T2 y T8 tocan
  `hook_common.py`, pero van en serie. Los once ficheros de test nuevos no existen hoy.
- **Privacidad**: no encontré ningún camino que deje la ruta del proyecto en claro en un campo
  nuevo. `/api/events` ya devuelve `log_dir` en `meta` (`metrics.py:551`) y `/api/hooks` la ruta de
  la telemetría (`:769`); son de antes y no cambian. No hay ningún volcado de variables de entorno
  que pudiera sacar `LOCAL_DELEGATE_SELF_PROJECTS`.
- **D9** (el filtro mira solo el tipo): correcta y justificada.
- **D11** (lo `unknown` se queda en los totales): defendible, pero su consecuencia en esta máquina
  no está cuantificada; ver el hallazgo 5.

## Hallazgos

### 1. Bloqueante — La línea del mod no puede llevar proyecto por el camino que describe el plan (REQ-016, T8)

El plan dice que la línea del mod (`hook record-read`) saca el proyecto «del `cwd` que el mod ya
manda a `classify`», a través de `context_of`. El código no lo permite:

- El mod manda `cwd` a `classify` (`mod/read.js:447`), no a `record-read`.
- La salida de `classify` no trae `cwd`: es `kind`, `path`, `scope`, `bytes`, `range`, `via`,
  `read_switch` (`hook_entry.py:26`, `:177`).
- La entrada de `record-read` es esa salida más `decision`, `session_id` e `id`
  (`mod/read.js:643`).
- `record_decision` llama a `context_of` con un `payload` que solo lleva `session_id`
  (`suggest_delegate_read.py:463-467`, `suggest_delegate_shell.py:160-165`). `context_of` nunca ve
  `cwd` ni `transcript_path` en esa vía.

Para cumplir REQ-016 tal como está escrito habría que cambiar `record_decision` en esos dos
scripts. Los dos entran en la huella de versión, así que cambiaría la huella y se abriría un tramo
nuevo de medición con la ventana de 90 días abierta. La spec pide evitarlo (`spec.md:307-308`) y T8
dice «se para y se escala», pero el plan no lista esos ficheros ni reconoce que el camino previsto
no existe.

Hay un camino que no toca los scripts con huella ni el mod, pero el plan no lo describe:

1. `hook_entry.classify_text` añade `project` y `project_kind` a la respuesta, calculados del `cwd`
   de la entrada (no en `read_classifier.py`, que sí entra en la huella).
2. El mod ya reenvía la respuesta entera: `readParseClassified` la devuelve sin recortar
   (`read.js:436-443`) y `readRecord` la esparce con `...classified` (`read.js:643`).
3. `hook_entry.record_read` valida esos dos campos (16 hexadecimales; `self` u `other`) y los pasa
   por una variable de contexto de `hook_common`, como ya se hace con `_RECORD_STRICT`
   (`hook_common.py:293-304`), para que `record` o `context_of` los añadan.

Cambios pedidos:

- **`plan.md`, T8**: describir el camino real, listar los ficheros que toca de verdad y decir que
  los campos que vuelven del mod se validan (son entrada de un cliente).
- **`spec.md`, REQ-016**: decir de qué entorno sale `LOCAL_DELEGATE_SELF_PROJECTS` en la ruta
  mod → daemon. No está en `CLASSIFY_ENV` ni en `RECORD_ENV` (`hook_entry.py:80-95`); añadirla
  cambia la lista del mod, que `tests/test_mod_static.py` ata, y `classify_text` tiene por contrato
  no leer `os.environ` cuando le pasan otro entorno (`hook_entry.py:156-157`).
- **`plan.md`, tabla de mutantes**: un mutante propio para la línea del mod.

### 2. Bloqueante — REQ-006 y el mutante «se quita el `try` de la regla» no discriminan

`_log_event` ya envuelve toda la atribución en un `try ... except Exception: pass`
(`server.py:1417-1428`). Si la regla de proyecto lanza dentro de `resolve_call` sin `try` propio:

- La fila se escribe igual.
- Sale sin los dos campos nuevos.
- Pero pierde también `caller_kind`, `caller_src`, `caller_session_key`, `caller_model` y el resto,
  porque `rec.update(...)` no llega a ejecutarse. Solo queda `tool_use_id`.

El criterio de REQ-006 («la fila se escribe igual, sin los dos campos») se cumple con y sin el
`try` propio, y la aserción que nombra el plan («la fila se escribe aunque la regla lance») no
dispara con el mutante. La regresión real, perder toda la atribución de la fila, pasaría sin que
ningún test la viera.

Cambios pedidos:

- **`spec.md`, REQ-006**: añadir «y conserva `caller_kind`, `caller_src` y `caller_session_key`».
- **`plan.md`, tabla de mutantes**: la aserción de ese mutante pasa a ser «la fila conserva los
  demás `caller_*`».

### 3. Bloqueante — El paso 4 de la prueba en vivo no puede comprobar la barra del mod (REQ-026)

La prueba en vivo corre dentro de una ventana de prueba. Dentro de ella:

- `cost.merge` estampa `test_window` en la fila (`cost.py:233-236`; el panel carga por
  `metrics.py:213`).
- `/api/stats?session=` filtra por sesión y después aplica la regla de pruebas sin
  `include_tests` (`metrics.py:574-578`).
- El mod pide `/api/stats?session=<id>&lang=` sin `include_tests` (`mod/status.js:656`).

Resultado: la barra da 0 para esa delegación por la regla de pruebas, no por el filtro del propio
repo. El paso «la barra de estado del mod de la sesión del repo no da 0» o falla siempre, o pasa
gracias a delegaciones anteriores al reinicio del daemon, que no traen el campo y no prueban nada.

Además, con «Pruebas» encendido y el histórico ya rellenado, el interruptor nuevo mueve muchas
filas, no solo la de la prueba: «la aparta» y «la cuenta» no son observables sin acotar el rango.

Cambios pedidos en **`plan.md`, «Prueba en vivo»**:

- Rango desde el inicio de la ventana de prueba y cifras exactas: con `include_tests=1`,
  `excluded_self == 1` y `total.calls == 1` por defecto; `total.calls == 2` con `include_self=1`.
- Sustituir la comprobación de la barra por
  `/api/stats?session=<id de la sesión del repo>&include_tests=1`, con `total.calls >= 1` y
  `excluded_self == 0`.

### 4. Bloqueante — La tabla antes/después no puede dar un resultado distinto si el filtro está roto (REQ-027, T1, T11)

Tres problemas independientes:

- **No hay filas `self` en el rango.** El rango «acaba antes del cambio», así que ninguna fila trae
  el campo. Sin correr `recompute-cost` con el código nuevo, `excluded_self` es 0 y las tres
  columnas salen iguales. El criterio «la tercera difiere solo en lo que `excluded_self` explica»
  se cumple de forma trivial con el filtro roto. Ni T1 ni T11 mencionan `recompute-cost`.
- **`measure_adoption.py` no admite rango fijo.** Solo tiene `--since`
  (`scripts/measure_adoption.py:232-240`); no hay tope superior ni `--log-dir`. Los eventos de
  hooks que genera la propia jornada de trabajo mueven `reads`, `offered`, `blocks` y `sessions`
  entre T1 y T11. `measure_plugin_adoption.py` sí tiene `--since`, `--now`, `--log-dir` y
  `--projects` (`:256-260`).
- **El orden no es exigible.** Ninguna tarea depende de T1 (T11 depende solo de T10). Además, un
  `recompute-cost` corrido entre medias cambia el relleno y con él el coste del rango, por un
  motivo ajeno al cambio.

Cambios pedidos:

- **`plan.md`, T1**: correr `recompute-cost` con `main`; copiar `LOG_DIR` y la telemetría de hooks
  a un directorio temporal (una instantánea, que se borra al cerrar); medir el «antes» sobre esa
  copia.
- **`plan.md`, T11**: medir el «después» sobre la misma copia, tras un `recompute-cost` con el
  código nuevo sobre la copia. Criterio añadido: `excluded_self > 0`, y el reparto
  `self` / `other` / `unknown` anotado en `verification.md`.
- **`plan.md`, dependencias**: T11 depende de T1; T5, T6, T7 y T9 no arrancan sin T1 cerrada.
- **`plan.md`, T6**: si `measure_adoption.py` necesita un tope superior o un directorio de logs
  para poder medirse sobre la copia, decirlo en la tarea.

### 5. Bloqueante — D10 y el histórico: sin cifras, y con la causa equivocada

La spec y el plan dicen que se quedan `unknown` «las anteriores a la retención»
(`plan.md:163-166`). Medido hoy sobre el log real, la mayor parte de lo que se queda `unknown`
está dentro de la retención.

**Método del recuento.** Solo recuentos, sin rutas ni contenido, sin escribir nada. Filas de tools
`local_*` de todos los ficheros `usage-*.jsonl`, cruzadas con su entrada en
`attribution-AAAAMM.json` por la clave de `attribution.file_keys`. Se apartan las pruebas con
`attribution.test_reason` sobre la fila cruda y su entrada (cliente `mcp` y transcripts de banco;
las filas de ventanas de prueba no se apartaron, porque ese sello lo pone la fusión).
`attribution.cleanup_period_days` da **90 días** en esta máquina; la investigación daba por
supuesto 30 y lo dejó como «supuesto por validar» (`research.md:102`, `:355`).

| Filas | Quién | Dentro de la retención | Entrada del relleno |
| ---: | --- | --- | --- |
| 2222 | pruebas (apartadas) | — | — |
| 986 | modelo, con `tool_use_id` | sí | ninguna |
| 71 | modelo, con `tool_use_id` | sí | `exact` |
| 169 | mod (`toolu_plugin_…`) | sí | ninguna |
| 130 | Claude Code sin `tool_use_id` | sí | `window` |
| 52 | Claude Code sin `tool_use_id` | sí | `window+path` |
| 7 | Claude Code sin `tool_use_id` | sí | `ambiguous` |
| 1 | Claude Code sin `tool_use_id` | sí | `no_match` |
| 11 | chat (`claude-ai`) | sí | ninguna |
| 34 | otros clientes sin id | sí | ninguna |
| 4 | otros clientes sin id | sí | `window` |
| 1 | otros clientes sin id | sí | `window+path` |
| 3 | otros clientes sin id | sí | `no_match` |
| 124 | otros clientes sin id | no | `no_match` |

Total que no es prueba: **1.593** filas.

Lo que sale de ahí:

- **187 filas** (130 + 52 + 4 + 1) tienen cruce `window` o `window+path`, todas dentro de la
  retención. D10 las deja sin proyecto aunque su transcript siga vivo. Es el 11,7 % de las filas
  que no son prueba.
- **169 filas del mod** no tienen entrada de relleno. El plan no prevé ningún camino para darles
  proyecto a posteriori. Inferencia mía, sin comprobar en los transcripts: el `tool_use` del mod no
  está en el transcript (el mod llama por `$.mcp.call`), así que el cruce por id daría `no_match`.
  La mayoría sí trae `caller_session_key` (161 de 166 en la muestra de la investigación).
- **986 filas con id no tienen entrada**: `recompute-cost` solo se lanza a mano
  (`cli.py:397-404`; no hay otro llamador de `recompute.run` en `src/`). Hasta que se corra tras
  actualizar, el panel no aparta nada del histórico.
- Con el relleno completo y todos los transcripts vivos, tendrían proyecto como mucho **1.057**
  filas (986 + 71). Se quedarían `unknown` al menos **536** (34 %): 187 por D10, 169 del mod, 161
  de otros clientes sin id, 11 del chat y 8 de Claude Code sin cruce.
- En esta máquina casi todo eso es uso del propio repo, y D11 lo deja dentro de los totales por
  defecto.

D10, además, no es coherente con el resto de la spec:

- REQ-007 dice que «una entrada nueva con cruce real» trae proyecto. Una `window` nueva es cruce
  real, así que llevaría proyecto, mientras que una `window` ya escrita no lo recibiría nunca.
- REQ-008 acepta `window` y `window+path` como dato real para el hilo. El mismo cruce se da por
  bueno para el hilo, el modelo y `N` (que entran en el coste), pero no para el proyecto.

Cambios pedidos:

- **`spec.md`, D10 y «Migration» de `plan.md`**: poner estas cifras y corregir la causa (no es la
  retención).
- **`spec.md`, D10**: decidir en un sentido. O se enriquecen también las `window+path` y `window`
  ya escritas, o tampoco llevan proyecto las `window` nuevas (y REQ-007 lo dice).
- **`plan.md`, T4**: recuperar el proyecto de las filas con `caller_session_key` (sesión →
  clave → directorio, con el índice de transcripts que `recompute` ya recorre), o declararlo fuera
  de alcance en la spec con su cifra.
- **`spec.md`, REQ-025**: CHANGELOG y wiki dicen que hay que correr `recompute-cost` tras
  actualizar para que el histórico se aparte.

### 6. Importante — La sal: fichero vacío que no se repara, test de carrera y caché (REQ-003, REQ-006)

- **Fichero vacío permanente.** REQ-003 fija «apertura exclusiva». Si el proceso muere entre crear
  el fichero y escribir la sal, queda un fichero vacío. Como existe, nadie lo vuelve a crear; como
  es inválido, se omite `caller_project` (`spec.md:275-276`). El hash se pierde para siempre y en
  silencio. Pido creación atómica con contenido (escribir un temporal y enlazarlo o renombrarlo sin
  sobrescribir) y el caso «fichero de sal vacío preexistente» en REQ-003 y en T2.
- **Ventana de lectura a medias.** Con apertura exclusiva, el segundo proceso puede leer el fichero
  recién creado y aún vacío. La spec lo cubre (omite el hash esa vez); con creación atómica
  desaparece.
- **El mutante de la carrera no es determinista.** «La sal se crea sin apertura exclusiva → dos
  procesos acaban con la misma sal» con dos procesos reales puede pasar por azar. Pido un test
  determinista: simular que el otro proceso ganó (el fichero ya existe con contenido) y comprobar
  que la función devuelve ese contenido y no lo pisa.
- **Caché por proceso.** «Leída una vez por proceso» necesita clave por ruta: la suite cambia
  `LOCAL_DELEGATE_LOG_DIR` en cada test (`tests/conftest.py:62`) y un worker de xdist corre muchos
  tests. Pido decirlo en T2.
- **Falta un mutante.** Ni «la sal se lee en cada llamada» ni «`resolve_call` abre un fichero más»
  tienen mutante; la segunda mitad de REQ-006 se queda sin control positivo.
- **Coste en los hooks.** Cada evento de hook es un proceso: «una vez por proceso» es una lectura
  de la sal por evento. El requisito de rendimiento (`spec.md:297-298`) solo habla de
  `resolve_call`. Pido reconocerlo en la spec.

### 7. Importante — El corte de 90 días de la medición en curso mezclaría poblaciones (REQ-017)

La ventana de medición abierta desde el 2026-09-15 tiene su corte de 90 días el 2026-12-14. Con
`--exclude-self` por defecto, ese corte mezclaría:

- eventos viejos cuya sesión ya no tiene transcript: `unknown`, se quedan;
- eventos recientes del propio repo: `self`, se apartan.

Los cortes anteriores (14 y 30 días) lo incluían todo. La cifra por defecto no sería comparable
con ellos ni tendría una población definida. Ni la spec ni el plan lo mencionan.

Cambio pedido: **`spec.md`, REQ-017 y REQ-025**: ese corte se saca con `--include-self` o con las
dos cifras, y la wiki lo avisa.

### 8. Importante — REQ-022 no puede detectar una aserción relajada

- El método de verificación es `pytest`. Una aserción existente que se relaja sigue pasando: la
  segunda mitad del requisito («el diff de `tests/` solo añade») no tiene comprobación.
- T5 lista `tests/panel_server.py` y T10 `tests/data/uncatalogued_exceptions.json`. Los dos
  existen hoy, así que contradicen el criterio tal como está escrito. Añadir una excepción al
  guardián de textos sin catalogar es relajarlo.

Cambios pedidos:

- **`spec.md`, REQ-022**: verificación adicional con
  `git diff --diff-filter=MDR --name-only main -- tests/`, vacía salvo una lista explícita de
  excepciones.
- **`plan.md`, T5**: quitar `tests/panel_server.py` o justificar por qué hay que tocarlo.
- **`plan.md`, T10**: cada excepción nueva con su motivo; preferir entradas de catálogo.

### 9. Importante — REQ-028 no se cumple con la tabla de mutantes

REQ-028 pide un mutante por cada test nuevo. La tabla va por fichero y deja criterios sin control
positivo:

| Requisito | Criterio sin mutante |
| --- | --- |
| REQ-002 | una entrada de la variable con menos de 3 caracteres se ignora |
| REQ-009 | `excluded_self`, `unknown_project` y la suma `mostradas + excluded_tests + excluded_self` |
| REQ-012 | `/api/hooks` con `include_self=1` deja los eventos `self` |
| REQ-016 | línea del mod; evento sin `transcript_path` ni `cwd`; el hook no falla si la regla lanza |
| REQ-017 | el filtro sobre las filas del log de uso (solo hay mutante para los eventos de hooks) |
| REQ-018 | `delegations_by_caller` y `delegations_by_project_kind` |
| REQ-020 | `with_subagent_delegation` y `with_mod_delegation` |
| REQ-021 | «las cifras de hoy no cambian» y «la línea no sale con recuento cero» |

Mutantes que pueden no mutar según los datos del test:

- **«`write_backfill` sustituye en vez de añadir»**: solo cambia algo si la entrada vieja trae
  campos distintos de los que calcula la pasada nueva. `n` y `expiries` se recalculan
  (`transcripts.py:290-303`); el test tiene que fijar una entrada vieja con un `n` distinto.
- **«El coste recibe las filas sin filtrar»**: exige una fila `self` valorable (cliente Claude
  Code, con modelo y agregados); si el coste sale vacío, no hay nada que baje.

Cambio pedido: **`plan.md`, tabla de mutantes**: añadir los mutantes que faltan y fijar esos datos
en T4 y T5.

### 10. Importante — Las decisiones no dejan rastro de quién las tomó

- `brief.md:5-25` está entero en «TBD»: problema, resultado, alcance, restricciones y preguntas
  abiertas. Solo tiene la petición original.
- `research.md:263-280` dejó cinco preguntas que «necesitan decisión del usuario».
- `spec.md:29` dice que D1 a D8 se tomaron «antes de escribir esta spec», sin decir quién. D5
  cambia las cifras del panel: es decisión de producto.
- D9, D10 y D11 las añadió quien redactó; tampoco consta que el usuario las haya visto.

Cambio pedido: registrar en el log de `brief.md` quién decidió D1 a D8 y que D9 a D11 están
pendientes de visto bueno, y rellenar el alcance.

### 11. Menor — REQ-025 se queda corto en tres avisos

- No exige el aviso de cambio de comportamiento («las cifras bajan y cómo recuperar la
  anterior»); solo aparece en `plan.md:180-182`.
- No exige documentar `project` y `project_kind` de la telemetría de hooks.
  `docs/wiki/Savings-and-metrics.md` es la página que hoy describe esos eventos y los dos scripts.
- No avisa de que el hash es reversible por fuerza bruta para quien tenga `LOG_DIR` con
  `project-salt`, ni de que ese fichero no se comparte junto a un log. La spec reconoce el riesgo
  sin sal (D2), pero no este.

### 12. Menor — Tres definiciones flojas

- **`self_in_range`** (REQ-009) no está definido: ¿cuenta las filas que además son prueba?
- **Hash por `cwd`** (`spec.md:285-286`): también difiere del de la fila si el `cwd` es un
  subdirectorio del proyecto o un worktree, no solo «si Claude Code formara el nombre de otro
  modo».
- **Quién lee la variable** (T2): `config.py` lee al importar (`config.py:643` como ejemplo) y
  `hook_common` en cada llamada. El plan no dice cuál manda en el daemon.

## Llamadas `local_*` y fallos de `local-delegate` vistos

- Llamadas hechas: 1 (`local_extract` sobre `plan.md`).
- `local_extract` devolvió valores sin contenido («Título: líneas 30-79») y marcó como
  `lines_unverified` el rango 102-128, que es exactamente la tabla de mutantes.
- El bloqueo de lectura dijo «27 de sus 34 líneas» para `plan.md` (202 líneas) y «31 de 40» para
  `spec.md` (324).
- No abrí issues: el encargo era de solo lectura. Quedan para la sesión principal.

## Segunda pasada

Fecha: 2026-11-10. Releídos enteros `brief.md` (53 líneas), `spec.md` (427 líneas, 31 requisitos
y D1 a D12) y `plan.md` (293 líneas, 11 tareas y 62 mutantes), y contrastados de nuevo con el
código de `main` en `da78ce70`. Solo lectura: lo único escrito es esta sección.

### Veredicto

**Quedan bloqueantes: uno, nuevo** (el hallazgo A). Los cinco bloqueantes de la primera pasada
están resueltos en el diseño. Pero el camino nuevo de T8 rompe con seguridad un test que hoy pasa y
que el plan promete no tocar. Lo demás son hallazgos importantes y menores que no impiden aprobar
una vez resuelto A.

### Los cinco bloqueantes de la primera pasada

| N.º | Bloqueante | Estado | Evidencia |
| ---: | --- | --- | --- |
| 1 | Línea del mod sin camino real | **Resuelto en el diseño, con un problema nuevo** (hallazgo A) | `plan.md:31-42`, T8 en `plan.md:83-86`; REQ-016 en `spec.md:209-218`. El camino descrito existe en el código: `readParseClassified` reenvía la respuesta entera (`read.js:436-443`), `readRecord` la esparce (`read.js:643`) y `_RECORD_STRICT` sirve de molde (`hook_common.py:287-304`). Los scripts con huella no se tocan (`spec.md:406-408`). |
| 2 | REQ-006 y el mutante del `try` | **Resuelto** | `spec.md:149-152` exige conservar `caller_kind`, `caller_src` y `caller_session_key`; mutante 16 con esa aserción (`plan.md:145`). Ver el hallazgo C sobre el mutante 17. |
| 3 | Paso 4 de la prueba en vivo | **Resuelto** | REQ-026 en `spec.md:276-283` y pasos 4 y 5 en `plan.md:234-238`, con cifras exactas. La barra se sustituye por `session=…&include_tests=1`. La condición de que nadie más delegue, con su salida si no se cumple, está en `plan.md:225-227` y `:241-242`. |
| 4 | Tabla antes/después que no discriminaba | **Resuelto**; quedan dos huecos menores (hallazgo F) | Instantánea y `recompute-cost` en T1 (`plan.md:55-58`); criterio `excluded_self > 0` (`plan.md:205-210`); T4, T5, T6, T7, T9 y T11 dependen de T1. `measure_adoption.py` lee la copia por `config.LOG_DIR` y `LD_HOOK_TELEMETRY_LOG` (`scripts/measure_adoption.py:52-61`), así que no hace falta tope superior sobre una copia que no crece. |
| 5 | D10 y el histórico | **Resuelto** | D10 invertida con las cifras (`spec.md:69-93`), REQ-031 para el mod (`spec.md:309-316`), aviso de `recompute-cost` en REQ-025 (`spec.md:266-273`) y escenario nuevo (`spec.md:347-352`). Las cifras cuadran con mi recuento; ver el hallazgo E. |

Los hallazgos 6 a 12 de la primera pasada también están recogidos:

- sal atómica con reparación y caché por ruta (`spec.md:127-133`, T2 en `plan.md:59-62`);
- corte de 90 días (REQ-029);
- diff de `tests/` (REQ-030);
- mutantes por criterio (`plan.md:128-191`);
- quién decidió (`brief.md:37-53`);
- REQ-025 ampliado;
- `self_in_range` definido (`spec.md:173-174`).

Queda una cosa: el resto de `brief.md` (problema, resultado, alcance) sigue en «TBD»
(`brief.md:3-25`).

### Hallazgos nuevos

#### A. Bloqueante — Con D12, `classify` deja de dar lo mismo por el daemon que por el proceso, y un test de hoy falla

`tests/test_hook_classify_endpoint.py` existe para atar una promesa: misma entrada y mismo entorno
dan el mismo JSON, byte a byte, por el CLI que por el endpoint (`:7-9`). La comprueba
`test_classify_matches_the_real_cli_process` (`:177-198`):

- lanza el CLI como subproceso con `LOCAL_DELEGATE_LOG_DIR = <tmp>/data` (`_client_env`, `:61-72`;
  `_cli_process`, `:89-111`);
- llama al endpoint en el mismo proceso de pytest, cuyo `os.environ` tiene
  `LOCAL_DELEGATE_LOG_DIR = <tmp>` (`tests/conftest.py:62`);
- pasa `cwd` en todas las entradas (`:182-189`);
- compara `response.content == expected` (`:196`).

Con REQ-016 más D12, `classify_text` añade `project` calculado con la sal del `LOG_DIR` de
`os.environ`. El subproceso crea su sal en `<tmp>/data` y el daemon de test la suya en `<tmp>`. Son
dos sales aleatorias, el hash difiere y los bytes también: el test falla. No lo he ejecutado; sale
de leer el código. T8 dice que ese fichero «pasa sin tocar» y deja como condición de parada «si
algún test de hoy compara la respuesta entera de `classify` con una entrada que trae `cwd`»
(`plan.md:85`). Esa condición se cumple con certeza hoy. `test_classify_matches_the_cli_on_the_whole_corpus`
(`:140-174`) solo pasa por casualidad: `_cli_in_process` deja `os.environ` apuntando a `<tmp>/data`
durante todo el test.

El fallo del test refleja un fallo de diseño. En uso real, la línea del mod sale por el daemon o
por el proceso de respaldo (`read.js:446-460`). D12 hace que cada camino use su propio entorno, así
que una misma decisión puede llevar un `project` o un `project_kind` distinto según el camino que
respondió (ver también el hallazgo B).

No vale la salida obvia de tomar la sal del `LOCAL_DELEGATE_LOG_DIR` que manda la petición, que
está en `CLASSIFY_ENV` (`hook_entry.py:85`). Convertiría `POST /api/hook/classify` en una forma de
crear un fichero `project-salt` en cualquier directorio que nombre la petición. Es la misma clase
de fallo que se cerró en la 0.41.1 para `record-read` (`web/metrics.py:1207-1212`). En eso D12
acierta.

Cambio pedido en **`plan.md`, T8 y Approach, y `spec.md`, REQ-016 y REQ-005**: no tocar
`classify_text`. Que `hook_entry.record_read` resuelva el proyecto con el `session_id` que ya trae
la entrada (`read.js:643`):

1. validar el id con un patrón estricto, porque acaba en una ruta;
2. buscar `<raíz de proyectos>/*/<session_id>.jsonl`;
3. aplicar `project_identity` sobre esa ruta, en el proceso que escribe.

Ventajas:

- el hash sale del mismo directorio que el de la fila, no del `cwd`, así que desaparece el caso
  límite de `spec.md:377-380` para el mod;
- la respuesta de `classify` no cambia y `test_hook_classify_endpoint.py` sigue valiendo;
- no hay excepción al contrato de `classify_text`, así que sobra `plan.md:280-281`;
- el mod no cambia.

Coste: un `glob` sobre unos 40 directorios por cada `record-read`, que es lo que ya hace
`measure_adoption.py` con los eventos viejos (D4). Si se mantiene el diseño actual, el plan tiene
que declarar como excepción de REQ-030 el cambio en `test_hook_classify_endpoint.py:177-198`, con
su motivo, y la spec tiene que decir que el daemon y el respaldo pueden discrepar.

#### B. Importante — D12 con la variable en el cliente y no en el daemon: datos incoherentes y sin aviso

Caso: una máquina donde `LOCAL_DELEGATE_SELF_PROJECTS` está en el entorno del lanzador (por
ejemplo, en el bloque `env` de los ajustes de Claude Code, que es donde viven las demás variables
`LD_HOOK_*`) pero no en el del daemon, que arranca por una tarea programada o por launchd y no lo
hereda. Para un clon cuyo nombre no contiene `local-delegate`:

- **Filas del log**: las sella el daemon (`resolve_call`) y salen `other`.
- **Eventos de los hooks**: los sella el lanzador y salen `self`.
- **Panel**: `/api/hooks` aparta esas lecturas y `/api/stats` cuenta sus delegaciones.
- **`measure_adoption.py`**: cruza avisos (sin `self`) con delegaciones (con `self`), así que la
  tasa de aceptación sube sin motivo.
- **Línea del mod**: sale `other` por el daemon y `self` por el proceso de respaldo. Desaparece si
  se aplica el cambio de A.
- **`recompute-cost`**, corrido desde una terminal con la variable, escribe `self` en el relleno.
  Pero `merge_row` solo rellena lo vacío (`cost.py:187-189`) y la fila ya dice `other`: el relleno
  no lo corrige nunca.

La spec solo dice que la variable «tiene que verla tanto el daemon como el lanzador»
(`spec.md:402-405`). El chequeo de `doctor` está fuera de alcance (`spec.md:420`) y nada lo
detecta. La regla por nombre cubre el repo y sus worktrees, así que solo afecta a clones con otro
nombre. Por eso no es bloqueante.

Cambio pedido, una de dos:

- **(a)** Sacar la lista de un fichero en `LOG_DIR` (por ejemplo `self-projects.json`), como ya se
  hace con el interruptor `read-hook.json`. Así la leen igual el daemon, los hooks, el respaldo y
  los scripts.
- **(b)** Mantener la variable y escribir este caso en «Edge cases» de la spec y en REQ-025: dónde
  definirla, en el entorno del usuario del sistema y no solo en el `env` de los ajustes, y que una
  fila ya sellada `other` no se corrige.

Recomiendo (a).

#### C. Importante — El mutante 17 no muta lo que dice

Mutante 17: «la regla mira el directorio del proyecto en disco»; aserción: «`resolve_call` abre los
mismos ficheros que hoy» (`plan.md:146`). T3 lo verifica con un «espía de aperturas de fichero en
`resolve_call`» (`plan.md:65`). El único punto de inyección que tiene hoy `resolve_call` es
`opener`, y solo lo usa `_find_model` (`attribution.py:165`, `:201`, `:233`). Mirar el disco se
hace con `Path.exists`, `is_dir` u `os.stat`, que no pasan por `open`: con un espía sobre `opener`,
o sobre `builtins.open`, ese mutante no dispara.

Cambio pedido en **`plan.md`, T3 y mutante 17**: espiar también `os.stat`, `os.scandir` y
`os.listdir` (`Path.exists` e `is_dir` acaban en `os.stat`), dejando fuera solo la sal. O cambiar
el mutante por uno que sí abra un fichero.

#### D. Menor — Recuperar el mod por clave de sesión: sin regla para el caso ambiguo, y una preferencia sin motivo

La clave es `sha256(prefijo + id)[:32]` (`hook_common.py:1281-1291`): 128 bits, sin colisiones en
la práctica. El índice sale del nombre del transcript principal. Medido hoy en esta máquina, solo
recuentos: 353 ids de sesión en 40 directorios de proyecto, ninguno repetido en dos directorios.
Riesgo bajo, pero:

- REQ-031 no dice qué pasa si un id aparece en dos directorios. Inferencia mía sin comprobar: una
  sesión reanudada desde otro `cwd` podría dar ese caso. El índice se quedaría con uno según el
  orden de recorrido (`transcripts.py:204`) y asignaría un proyecto sin certeza. Pido: id en más de
  un directorio → sin proyecto.
- «Si no coinciden, manda el de la clave de sesión» (`spec.md:313-314`) no trae motivo. El cruce
  `exact` dice dónde está de verdad el `tool_use`. Pido justificar la preferencia o tratar el
  desacuerdo como ambiguo, sin proyecto. El mutante 25 cambiaría con ello.

#### E. Menor — Las cifras cuadran, pero 1.593 es una cota alta

1.413 + 180 = 1.593. El desglose también cuadra con mi recuento:

- 986 + 71 + 187 + 169 = 1.413;
- 8 + 11 + 161 = 180;
- 161 = 34 + 3 + 124;
- 187 = 130 + 52 + 4 + 1, que incluye 5 filas de otros clientes con cruce de ventana.

Pero mi recuento apartó las pruebas con `test_reason` sobre la fila cruda, sin el sello
`test_window` que pone la fusión (`cost.py:233-236`). Las filas de ventanas de prueba están dentro
de las 1.593. Pido añadir en `spec.md:79-93` que es una cota alta por ese motivo.

#### F. Menor — Dos huecos de la tabla antes/después

- El rango del panel no está fijado. Sin `from` ni `to`, `/api/stats` toma «los últimos 30 días
  hasta ahora» (`web/metrics.py:183-194`), así que T1 y T11 medirían rangos distintos aunque la
  copia no cambie. Pido `from` y `to` fijos, anotados en T1. Lo mismo para `local_status`, que
  cuenta el «mes en curso»: T1 y T11 tienen que caer en el mismo mes, o la cifra se sustituye.
- `recompute-cost` no admite `--now` (`cli.py:1603-1620`): su ventana `now − 90 días`
  (`recompute.py:339`) corre entre T1 y T11. La segunda copia para el coste (`plan.md:208-210`)
  cubre la deriva de los transcripts, pero no esta. Pido anotarlo como fuente de diferencia
  admitida, o pasar `now` llamando a `recompute.run` directamente.

#### G. Menor — Dos mutantes que dependen de datos que el plan no fija

- **Mutante 29**: `excluded_self` cuenta también las pruebas. Solo dispara si el test lleva una
  fila que sea a la vez prueba y `self`. Pido fijarla en T5.
- **Mutante 46**: cubre la variable, pero no el `LOG_DIR` de la sal. Si se mantiene el diseño
  actual de A, pido un mutante «la sal sale del `LOG_DIR` de la petición», con su aserción. Con el
  cambio de A, sobra.

### Llamadas `local_*` y fallos vistos en esta pasada

- Llamadas `local_*`: 0. Leí enteros los artefactos, como pedía el encargo, y el código por rangos
  con Grep.
- Fallos nuevos de `local-delegate`: ninguno.
- Sin procesos en marcha.

## Tercera pasada

Fecha: 2026-11-10. Acotada a lo que pidió la sesión coordinadora: `project_of_session` (REQ-016,
REQ-032, D13), el fichero `LOG_DIR/self-projects.json` (D12, REQ-002, REQ-025) y D14. Leí los
tramos nuevos de `spec.md` (497 líneas) y `plan.md` (325 líneas) y los contrasté con el código de
`main` en `da78ce70`. Solo lectura: lo único escrito es esta sección.

### Veredicto

**APROBABLE.** Ningún bloqueante abierto. Quedan un hallazgo importante (H1) y tres menores, que
se pueden corregir sin volver a revisar.

### 1. `project_of_session`

- **No puede salirse de la raíz por el id.** Solo acepta ids con forma de UUID (`spec.md:253-255`).
  Sin separadores ni `..` no hay forma de escapar de `<raíz>/*/<id>.jsonl`, y el mutante 46 lo ata.
  Además, del fichero encontrado solo se usa el nombre de su directorio padre, que se hashea: no se
  abre ni se lee ningún transcript. Medido hoy en esta máquina, solo recuentos: 353 de 353 nombres
  de transcript principal tienen forma de UUID, así que la validación no deja fuera ninguna sesión
  real.
- **Coste.** Es una lectura de la raíz y una comprobación de existencia por carpeta de proyecto
  (unas 40 aquí, de las que 16 son temporales de bancos). Se notará poco. D14 obliga a mirar todas
  las carpetas y no parar en la primera. El coste crece con las carpetas que Claude Code acumula
  por cada `cwd`, y la línea del mod por el daemon tiene plazo: si no llega a tiempo, la petición
  cuenta como «tarde» y pasa a reintento. Ver H3.
- **Sin rutas en claro.** No encontré ningún camino que deje una ruta en un campo, un log o un
  error:
  - el fallo de `record-read` solo registra el tipo de la excepción, la decisión y la vía
    (`hook_entry.py:240-265`; en el daemon, `web/metrics.py:1253-1255`);
  - la variable de contexto lleva el hash y el tipo, no la ruta (`plan.md:44-47`);
  - REQ-005 cubre el evento de hooks, y con él la línea del mod.
- **H1. Importante — la raíz de proyectos no queda fijada en la spec.** En el daemon,
  `record_read` corre dentro de `run_with_environ` con el entorno que manda el mod
  (`hook_entry.py:222`; `hook_common.py:40-54`). Ese entorno trae `HOME` y `USERPROFILE`, porque
  están en `CLASSIFY_ENV` (`hook_entry.py:88-89`) y por tanto en `RECORD_ENV`. Si quien implemente
  resuelve `~` como lo hace el clasificador, con `current_environ()`, la petición decidiría qué
  carpeta se recorre. Sería un oráculo de existencia de ficheros en una carpeta elegida por quien
  llama, la misma familia que el fallo cerrado en la 0.41.1. Además el hash podría salir de otra
  raíz que la de la fila. Hoy solo lo dice una línea de riesgos (`plan.md:312`), sin requisito ni
  mutante. Pido:
  - en REQ-016 y D12: «la raíz de proyectos sale del `os.environ` del proceso
    (`Path.home()`, como `attribution._projects_root`, `attribution.py:92-93`), nunca del entorno
    de la petición»;
  - un mutante «la raíz sale de `current_environ()`», que dispare con una petición que trae otro
    `HOME` o `USERPROFILE`.
- **H2. Menor — dos instancias del módulo.** El daemon carga `hook_common` dos veces: como módulo
  suelto en `record_read` (`hook_entry.py:141-149`, `:219`) y como módulo del paquete en
  `attribution`. Cada instancia tiene su propia variable de contexto y su propia caché. Pido que T8
  diga que la variable de contexto se pone en la instancia suelta, la que leen `record_decision` y
  `context_of`. La prueba por `POST /api/hook/record-read` que ya prevé el plan (`plan.md:119`) lo
  comprueba siempre que mire el campo escrito, así que basta con exigirlo.
- **H3. Menor — sin presupuesto de tiempo ni caché en el daemon.** Pido un tope de tiempo para la
  búsqueda, igual que el de 50 ms de `attribution` (`attribution.py:38`), y en el daemon una caché
  `session_id → resultado`, porque una sesión registra muchas decisiones. También, anotar el tiempo
  medido en `verification.md`.

### 2. `self-projects.json`

- **No hay superficie de escritura nueva.** El código nunca lo crea ni lo escribe: se edita a mano
  (`spec.md:485`). Hoy no existe ningún código que empaquete o exporte `LOG_DIR` (no hay
  `zipfile`, `make_archive` ni `copytree` sobre él en `src/`). La copia de T1 lo incluye y se borra
  en T11.
- **La lectura está cubierta.** Vive en `LOG_DIR` del proceso (D12), con la misma confianza que
  `read-hook.json` (`read_switch.py:70`). Un fichero ausente, roto o con otra forma equivale a una
  lista vacía, sin error (REQ-002, mutante 7). Su contenido no se registra
  (`spec.md:426-428`, `:454-455`).
- **Lleva rutas en claro, y la spec lo reconoce** (`spec.md:454-455`). Tres matices:
  - **H4. Menor — la privacidad del contenido se revisa a ojo.** Solo la cubre una revisión
    (`plan.md:127`), no un test. Pido añadir a REQ-005 y a `tests/test_project_privacy.py` una
    entrada marcadora en la lista, que no puede aparecer en la fila, el evento, `local_status` ni
    las respuestas `/api/*`.
  - **Menor — coincidencia por subcadena.** Una entrada de 3 letras como `app` marca como `self`
    todo proyecto cuyo nombre la contenga, y apartaría uso real sin aviso (REQ-002). Pido exigir
    que la entrada coincida con el nombre entero del directorio o con un tramo entre guiones, o al
    menos decirlo en la documentación.
  - **Menor — normalización de letras con tilde o ñ.** «Cada carácter no alfanumérico por `-`»
    con `str.isalnum` de Python conserva la ñ y las vocales con tilde; inferencia mía: Claude Code
    probablemente las cambia por `-`. En esta máquina ningún directorio de proyecto tiene
    caracteres fuera de `[A-Za-z0-9-]`, así que no se puede medir. Pido fijar la regla en ASCII
    (`[^A-Za-z0-9]` → `-`) y probarla con un nombre con ñ.
  - **Menor — tamaño.** No hay tope de tamaño; un fichero enorme solo lo pondría el propio usuario.
    Basta con un tope modesto.

### 3. Bloqueantes de las pasadas anteriores

Todos resueltos:

- **Primera pasada, 1 a 5:** resueltos, como recoge la segunda pasada.
- **Hallazgo A de la segunda:** `classify_text` no se toca y REQ-032 exige el mismo JSON byte a
  byte por los dos caminos (`spec.md:361-365`); el mutante 50 apunta a
  `test_classify_matches_the_real_cli_process`; T8 lo excluye.
- **B:** la variable se sustituye por un fichero en `LOG_DIR` (D12); el caso de un `LOG_DIR`
  distinto entre procesos queda documentado (`spec.md:432-434`, REQ-025).
- **C:** el espía mira `open`, `os.stat`, `os.scandir` y `os.listdir` (`plan.md:77`; mutante 18).
- **D:** D14 deja sin proyecto la sesión ambigua y el desacuerdo entre fuentes
  (`spec.md:138-143`; mutante 47).
- **E:** cota alta dicha (`spec.md:84`, `:94`).
- **F:** rango y `now` fijos, con `recompute.run(now=)` (REQ-027; `plan.md:69`).
- **G:** fila prueba y `self` fijada en T5 (`plan.md:85`) y mutante 49 para el `LOG_DIR` de la
  petición.

### Llamadas `local_*` y fallos vistos en esta pasada

- Llamadas `local_*`: 0. Leí los tramos de los artefactos que pedía el encargo y el código por
  rangos con Grep.
- Fallos de `local-delegate`: ninguno.
- Sin procesos en marcha.
