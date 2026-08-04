# Implementation plan: local_commit_msg deja de truncar diffs grandes

## Approach

Tres piezas, en el orden en que se pueden verificar por separado. Ninguna inventa mecanismo nuevo:
el repo ya tiene chunking por límites naturales y map-reduce con contabilidad; lo que falta es un
splitter que entienda diffs, un reduce que sepa emitir un commit, y un inventario que dé el alcance
completo por 3k caracteres.

**B (splitter) va primero** porque A sin B produce parciales que no saben de qué archivo hablan
—medido: 1 de 11 trozos empieza en frontera—. **C es la que más mueve la aguja** según el control
positivo, y es la única que no gasta una llamada al modelo.

Decisión de diseño sobre el alcance de B: el splitter es global (nivel 0 de `_SPLITTERS`) pero se
**autoinhibe** si el texto no empieza por una cabecera de diff. Así un Markdown con un diff pegado
dentro de un fence —como el `research.md` de este mismo cambio— sigue partiéndose por headers, y no
hay forma de que B degrade `local_translate` o `local_summarize` sobre documentos normales.

Decisión sobre A: se **parametriza** `_chat_map_reduce` con `reduce_system` y `build_reduce`
opcionales en vez de escribir una segunda función. Duplicarla significaría duplicar el `inflight`,
el conteo de tokens y el evento de log, que es justo la parte que ya está bien y que REQ-006 exige
no cambiar de forma.

## Ordered tasks

1. **Splitter de diff por archivo (pieza B)**
   - Archivos: `src/local_delegate/server.py` (`_split_by_diff_files` nuevo, `_SPLITTERS`),
     `tests/test_chunking.py`
   - Diseño: `re.split(r"(?m)(?=^diff --git )", text)`, mismo patrón de lookahead que
     `_split_by_headers`, así que la invariante `"".join(...) == t` se mantiene por construcción.
     Respaldo para diffs sin `--git`: cabecera `^--- ` seguida de `^+++ `, aplicado **solo cuando no
     hay ningún `diff --git` en el texto** (ver objeción 1 de `review.md`: en un diff `--git` cada
     archivo trae también su `--- a/x`, y un patrón alternativo partiría cada archivo dos veces,
     dejando piezas que empiezan en `---` y rompiendo REQ-002). Guarda de autoinhibición:
     si `text.lstrip()` no empieza por una cabecera de diff, devuelve `[text]` y `_chunk_text` cae
     al siguiente nivel, que es el comportamiento de hoy.
   - Requisitos: REQ-002
   - Verificación: sobre el diff de referencia, `_chunk_text` da >1 trozo y **todos** empiezan en
     `diff --git`; la invariante `join == t` se mantiene; un Markdown con un diff embebido se sigue
     partiendo por headers — aseverado contra el resultado esperado explícito (todo trozo empieza
     por `## `), no contra «lo de antes», que no está disponible en tiempo de test (objeción 6).
   - Rollback: quitar la entrada de `_SPLITTERS`; el resto del árbol de splitters queda intacto.

2. **Inventario de archivos sin modelo (pieza C)**
   - Archivos: `src/local_delegate/server.py` (`_diff_inventory` nuevo), `tests/test_core.py`
   - Diseño: recorre las líneas una vez y devuelve `(ruta, añadidas, quitadas)` por archivo.
     `^diff --git a/X b/Y` abre archivo; `^+`/`^-` cuentan, excluyendo `^+++`/`^---`; `rename from/to`
     y `Binary files ... differ` entran en el inventario aunque no aporten líneas. Se rinde en texto
     estilo `ruta | +N -M`.
   - Tope: si el inventario pasa del 25 % del presupuesto de trozo, colapsa a directorios de primer
     nivel con los totales agregados y una línea de «N archivos en total». Sin este tope, un diff de
     cientos de archivos desplazaría del reduce justo el material que tiene que resumir.
   - Requisitos: REQ-003
   - Verificación: conteos exactos contra `git diff --numstat` del diff de referencia; casos de
     renombrado, binario y cambio-de-modo-solo; el colapso se dispara con un inventario sintético
     grande.
   - Rollback: la función es nueva y sin llamadores hasta la tarea 3.

3. **`_chat_map_reduce` parametrizable y `local_commit_msg` a map-reduce (pieza A)**
   - Archivos: `src/local_delegate/server.py` (`_chat_map_reduce`, `local_commit_msg`),
     `tests/test_map_reduce.py`
   - Diseño:
     - `_chat_map_reduce(..., reduce_system=None, build_reduce=None)`. Con `None` se usan los de hoy
       —`local_summarize` y `local_lint_summary` no cambian de comportamiento ni de firma efectiva—.
     - `local_commit_msg` lee con `_NO_TRUNCATE` y bifurca como `local_summarize` (`server.py:1147`):
       por encima de `max_chars_for(MODEL_CODE)` baja a map-reduce, por debajo sigue el `_chat` de
       hoy intacto (REQ-005).
     - El `system` del **map** pide un parte por archivo («qué cambió en cada archivo, en viñetas»),
       distinto del `reduce_system`, que es el `_guard` de Conventional Commits que ya arma la tool
       hoy (REQ-004).
     - `build_reduce` antepone el inventario de la tarea 2 a los parciales, y dice explícitamente
       que el inventario es la lista completa y los parciales pueden ser incompletos.
     - El bucle jerárquico de reducción por niveles no se toca: cuando los parciales tampoco caben
       se re-resumen con el `system` del map, o sea nunca emite un commit intermedio.
     - **El presupuesto del reduce se mide sobre el prompt armado, no sobre los parciales pelados**
       (objeción 2 de `review.md`): hoy el bucle compara `len(joined) <= budget`, y con el inventario
       antepuesto el prompt real puede pasarse del presupuesto y desbordar el contexto justo en la
       llamada que importa. La comparación pasa a hacerse sobre el texto que de verdad se envía.
     - **Tope de tokens de los parciales, separado del mensaje final** (objeción 3): hoy
       `partial_words = max(80, max_words)` y de ahí sale `max_tokens`. Un mensaje de commit son ~90
       palabras, pero un parte de 5 archivos necesita bastante más, y quedarse corto significa
       parciales cortados por `finish_reason=length` — o sea perder material en el map, que es
       exactamente lo que este cambio combate. Se añade un tope explícito para los parciales.
   - Requisitos: REQ-001, REQ-004, REQ-005, REQ-006
   - Verificación: el diff de referencia da N llamadas y **un** evento con `chunks: N`,
     `truncated_in: false`; el payload del reduce contiene el inventario; un diff de un archivo hace
     exactamente 1 llamada; `local_summarize`/`local_lint_summary` mantienen sus tests verdes.
   - Rollback: `local_commit_msg` vuelve a `_read_input(..., max_chars_for(MODEL_CODE))`; los
     parámetros nuevos de `_chat_map_reduce` quedan sin usar y son opcionales.

4. **Alcance visible y diff vacío (REQ-007 y borde)**
   - Archivos: `src/local_delegate/server.py` (`local_commit_msg`), `tests/test_core.py`
   - Diseño: cuando hubo troceado, la salida lleva de cuántos archivos y cuántos chars se redactó.
     Va **siempre**, no bajo `FEEDBACK_ENABLED`: es lo que impide que el fallo silencioso de hoy se
     repita con otra forma. Entrada vacía o en blanco → error explícito `[local-delegate error]`;
     entrada que no es un diff **no** falla (cae al camino de hoy con inventario vacío).
   - Requisitos: REQ-007
   - Verificación: la nota aparece con el diff grande y no con el pequeño; `diff=""` da error;
     texto libre no da error.
   - Rollback: quitar las dos líneas.

5. **Medida final contra el backend real**
   - Archivos: `.sdd/changes/commit-msg-diffs-grandes/verification.md`
   - Diseño: repetir la corrida de `research.md` con el código nuevo y anotar el mensaje resultante
     junto al de hoy. Es la única tarea que necesita el backend arriba.
   - Requisitos: REQ-001 (evidencia de extremo a extremo)
   - Rollback: n/a.

## Test strategy

- **Unit:** `_split_by_diff_files` (fronteras, invariante, autoinhibición), `_diff_inventory`
  (conteos, renombrado, binario, colapso por tope).
- **Integration:** `local_commit_msg` con el backend mockeado (`backend_mock`, como
  `tests/test_map_reduce.py`): número de llamadas, forma del evento de log, contenido del payload
  del reduce, y no-regresión del camino corto.
- **Control positivo obligatorio:** cada test nuevo se corre contra el código **sin** el cambio y
  debe fallar. Y no basta con que falle: hay que mirar **qué assert** dispara —si es uno que ya
  existía, el test está midiendo otra cosa—.
- **End-to-end / manual:** tarea 5 contra el backend local.
- **Security:** el cambio no toca autenticación, red ni rutas; `_check_allowed_dir` sigue siendo la
  única puerta de `path` y no se modifica. El inventario se calcula sobre contenido que ya estaba en
  memoria: no abre archivos nuevos. Sin secretos ni datos personales en los fixtures — el diff de
  referencia se genera con `git diff` del propio repo, no se versiona.

## Migration and compatibility

- Firma pública de la tool sin cambios (`diff`, `path`, `style`).
- Un diff grande pasa de 1 a N+1 llamadas al backend: más lento y más cómputo local, a cambio de un
  resultado que sirve. Es el mismo trato que ya aceptaron `local_summarize` y `local_lint_summary`.
- Sin variables de configuración nuevas. Si se añadiera alguna, tendría que pasar por los helpers
  `_env*` de `config` o los tres guardianes de `tests/test_aislamiento_entorno.py` lo detectarían.
- El daemon de esta máquina sale del paquete de `uv tool`, no del venv del repo: para probar la tool
  vía MCP con el código nuevo hay que apuntarlo al repo y **devolverlo al terminar**.

## Tarea 6, añadida tras medir contra el backend real

La medida de la tarea 5 falló, y el fallo invalida un supuesto que el plan daba por bueno: que el
presupuesto de trozo de `_chat_map_reduce` —16 000 chars, 0,8 × `max_chars_for(MODEL_CODE)`— sirve
para un diff. **El presupuesto está en caracteres y el límite del modelo está en tokens**, y la
relación entre los dos depende del contenido:

| Contenido | Densidad medida |
| --- | --- |
| Prosa de `.sdd/*.md` (la que veía el truncado de hoy) | 3,12 chars/token |
| `uv.lock` — hashes y URLs de PyPI | **1,57 chars/token** |

Once trozos pasaron; el doceavo, que es donde cae `uv.lock`, mandó 15 750 chars = 10 193 tokens
contra 8 192 de contexto y el backend respondió 400 `exceed_context_size_error`. El defecto estaba
latente en `local_summarize` y `local_lint_summary` desde su propia migración —un log de CI con
base64 tiene esa misma densidad—; el diff solo lo hizo visible.

Bajar el factor a ojo no acota nada: un diff de un fichero base64 puro baja de 0,75 chars/token.
Lo que sí acota es **hacer que mande el límite real en vez de la estimación**.

6. **Reintento adaptativo cuando el backend dice que no cabe**
   - Archivos: `src/local_delegate/server.py` (`_chat_map_reduce`), `tests/test_map_reduce.py`
   - Diseño: si una llamada del map falla con `exceed_context_size`, ese trozo se parte por la
     mitad y se reintenta con las mitades, hasta dos niveles. El error deja de ser terminal y el
     presupuesto en chars pasa a ser una estimación inicial, no una promesa.
   - Alcance: el reintento va en el **map**, que es donde está el volumen y donde ocurrió. El
     reduce trabaja sobre prosa generada por el propio modelo, de densidad predecible (~3
     chars/token), y ya tiene el bucle de reagrupación por niveles para cuando no cabe. Queda
     anotado como límite conocido, no como cubierto.
   - Requisitos: REQ-001 (sin esto, un diff con un lockfile dentro no produce mensaje ninguno)
   - Verificación: un backend simulado que responde 400 `exceed_context_size` al primer trozo y
     200 después; se comprueba que el resultado llega completo y que el trozo grande se reenvía
     partido. Y el control positivo correspondiente.
   - Rollback: quitar la rama de reintento; vuelve a ser un error terminal.

## Tarea 7, añadida tras diagnosticar la calidad del mensaje

Con el diff coherente (4 archivos, un solo cambio) salió `feat(server.py): add return statement
for resultado` y luego `feat(tests): agregar pruebas...`. La hipótesis de partida —«el reduce
copia la estructura del map en vez de sintetizar»— **era falsa**. Un espía sobre `_run_chat`
mostró las cuatro llamadas reales:

| Llamada | Qué devolvió |
| --- | --- |
| MAP 1 (`server.py`, el cambio principal) | `- ruta: qué cambió y para qué` — **la plantilla del prompt, copiada literal** |
| MAP 2 (continuación de `server.py`) | `- ruta: archivo.py …` — **nombre inventado**: la pieza no lleva cabecera `diff --git` |
| MAP 3 (los tres de tests) | correcto y detallado |
| REDUCE | `feat(tests): …` — fiel a lo que recibió: 3 de 5 notas eran de tests |

El reduce no falla: le entra basura. Dos defectos en el map, más una mejora de encuadre:

7. **Que el map produzca notas utilizables**
   - Archivos: `src/local_delegate/server.py` (`local_commit_msg`), `tests/test_map_reduce.py`
   - Diseño:
     - **(a) El formato deja de ser copiable.** `Output EXACTO: … una línea '- ruta: qué cambió y
       para qué'` se lee como una plantilla rellenable y el modelo la devuelve tal cual. El
       formato se ancla con los nombres reales de los archivos del trozo, que ya se saben:
       `_diff_inventory(trozo)`.
     - **(b) Los trozos de continuación dicen a qué archivo pertenecen.** Cuando un archivo
       excede el presupuesto y se subdivide, las piezas 2..N no llevan cabecera. `build_user`
       arrastra el último archivo visto —las piezas se procesan en orden— y lo declara en el
       prompt. Sin esto el modelo inventa la ruta.
     - **(c) El reduce sabe qué pondera.** Un cambio con sus tests tiene más líneas de test que
       de código; el titular debe describir el comportamiento que cambia, no el volumen de
       tests que lo acompaña.
   - Requisitos: REQ-004 (el mensaje resultante tiene que servir)
   - Verificación: con mock, que el prompt del map nombre los archivos reales del trozo y que un
     trozo de continuación declare el archivo que continúa. Y la medida contra el backend real,
     que es la única que juzga calidad.
   - Rollback: los prompts vuelven a su forma anterior; la maquinaria no cambia.

## Revisión adversarial

Siete objeciones planteadas contra el plan; cuatro lo cambiaron.

1. **El respaldo `^--- ` parte cada archivo dos veces.** *(cambia el plan)* En un diff `--git` todo
   archivo trae `diff --git`, `--- a/x` y `+++ b/x`. Un patrón alternativo que acepte las dos
   cabeceras habría cortado en ambas, dejando piezas que empiezan en `--- a/x` sin la cabecera
   `diff --git` que dice de qué archivo son. Habría **incumplido REQ-002 pasando los tests** si el
   test solo mirase la invariante. → El respaldo se aplica solo cuando no hay ningún `diff --git`.

2. **El inventario puede desbordar el presupuesto del reduce.** *(cambia el plan)* El bucle compara
   `len(joined) <= budget` para decidir si ya puede reducir, pero lo que se envía es
   `inventario + joined`. Con el inventario en su tope (25 % del presupuesto) el prompt real se pasa
   y desborda el contexto del modelo **en la única llamada que produce el resultado**. → La
   comparación se hace sobre el prompt armado.

3. **Los parciales heredarían el tope de tokens del mensaje final.** *(cambia el plan)*
   `partial_words = max(80, max_words)`; un commit son ~90 palabras, así que los parciales saldrían
   con ~244 tokens de tope. Un parte de cinco archivos no cabe ahí y se corta por
   `finish_reason=length`: material perdido en el map, que es el defecto que este cambio combate,
   reaparecido un nivel más adentro. → Tope explícito para los parciales, separado del final.

4. **No se puede comprobar «igual que antes» sin el antes.** *(cambia el plan)* La verificación de
   que B no degrada Markdown decía «el mismo troceado que antes del cambio», y en tiempo de test no
   existe el código viejo con el que comparar. Un test así se escribe pasando siempre. → Se asevera
   el resultado esperado explícito: todo trozo empieza por `## `.

5. **La nota de alcance se salta `FEEDBACK_ENABLED`.** *(se mantiene, con razón anotada)* Quien
   apagó el feedback quiere menos ruido. Pero lo que se añade no es contabilidad de ahorro: es el
   dato que impide que el fallo silencioso vuelva con otra forma. Se queda, y queda escrito por qué.

6. **`chars_in` cambia de significado en el log.** *(sin cambio)* Hoy registra los chars truncados;
   con map-reduce será el total del diff. Es el comportamiento correcto y el mismo que ya tienen
   `local_summarize` y `local_lint_summary` desde su migración, así que el dashboard no ve una forma
   nueva.

7. **Que el reduce con N parciales dé un buen mensaje no está comprobado.** *(riesgo aceptado, con
   salida)* Es la única pieza que no se puede verificar sin el backend real, y por eso existe la
   tarea 5. Criterio de fallo: si el mensaje resultante no es mejor que el del control positivo
   —solo el diffstat—, el trabajo no está hecho, y la salida es reducir sobre inventario más
   parciales acortados en vez de sobre los parciales completos. No se cierra el cambio sin esa
   medida.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
