# Implementation plan — contabilidad real del chunking y map-reduce

Change `contabilidad-chunking`. Spec aprobada el 2026-07-29.

## Enfoque

Tres ideas sostienen el diseño:

1. **El dato ya existe; falta leerlo.** `chunks` es el número real de llamadas al backend
   (`_chat_chunked` y `_chat_map_reduce` escriben `chunks=calls`, no el número de trozos), y solo se
   omite cuando vale 1. Por tanto `chunks or 1` da la contabilidad correcta **también para los 111
   eventos ya grabados**, sin migrar ni reescribir nada. No hace falta un campo nuevo para contar
   llamadas.
2. **Una sola implementación de las cuentas.** Hoy la lógica está duplicada: `_aggregate` sirve
   `/api/stats` (que el panel no usa) y el JS recalcula todo desde `/api/events`. Los KPIs pasan a
   servirse de `/api/stats`, que es la única implementación. El JS solo conserva lo que **necesita la
   zona horaria del navegador** —las series por día— con un helper mínimo, y ese helper se ata a
   Python con un test de paridad ejecutado con `node`.
3. **Ahorro y coste son dos magnitudes, no una.** El ahorro es el contenido contado una vez (correcto
   hoy, no se toca para texto). El coste es la suma real de tokens de las N llamadas. Se presentan
   enfrentados, nunca mezclados.

Lo único que toca `server.py` es la marca de unidad de `local_describe_image`: el código ya sabe que
ahí `chars_in` no son caracteres (`feedback_char_estimate=False`), pero esa marca no llega al log.

## Tareas ordenadas

### Tarea 1 — La unidad de `chars_in` viaja al log

- **Ficheros:** `src/local_delegate/server.py`.
- **Qué:** `_log_event` acepta `input_unit` y lo escribe **solo cuando no es `"chars"`** (convención
  del proyecto: campos opcionales únicamente cuando aportan). `_chat` lo recibe y lo propaga;
  `local_describe_image` pasa `input_unit="bytes"`. Ningún otro llamador cambia.
- **Requisitos:** REQ-005, REQ-007.
- **Verificación:** test que llame a `local_describe_image` con el backend mockeado y afirme que la
  línea escrita trae `input_unit: "bytes"`; y que una tool de texto **no** trae el campo.
- **Rollback:** campo aditivo y opcional; quitarlo deja el log como hoy.

### Tarea 2 — Contabilidad por evento, en un solo sitio

- **Ficheros:** `src/local_delegate/web/metrics.py`.
- **Qué:** función pura `_accounting(row) -> dict` que normaliza un evento a:
  `backend_calls` (`chunks or 1`), `tokens_in` / `tokens_out` (real si está, estimado si no),
  `estimated` (bool), y `saved_tokens` (el ahorro de contexto, con la regla de REQ-004/REQ-005:
  para texto `chars_in ÷ 4` **una vez**; para `input_unit == "bytes"` o
  `tool == "local_describe_image"` en el histórico, el `tokens_in` real, y si falta, `0` declarado
  como no estimable en vez de un número inventado).
- **Requisitos:** REQ-002, REQ-004, REQ-005, REQ-006.
- **Verificación:** tests de tabla sobre `_accounting` con un evento de cada forma: normal, chunked,
  sin tokens, imagen con marca, imagen histórica sin marca, evento fallido a mitad.
- **Rollback:** función nueva y aislada; `_aggregate` puede volver a la suma anterior.

### Tarea 3 — `_aggregate` expone coste y llamadas

- **Ficheros:** `src/local_delegate/web/metrics.py`.
- **Qué:** `_aggregate` consume `_accounting`. Añade a `total`, `by_tool`, `by_model` y `by_backend`:
  `backend_calls`, `tokens_in`, `tokens_out`, y en la raíz `estimated_events` (cuántos del rango se
  estimaron). `tokens_context_saved` pasa a sumar `saved_tokens`. Los campos existentes se conservan
  para no romper a nadie que ya lea `/api/stats`.
- **Requisitos:** REQ-001, REQ-002, REQ-004, REQ-005, REQ-006.
- **Verificación:** el escenario de aceptación de la spec —dos eventos, uno con `chunks: 4`— da
  `calls: 2` y `backend_calls: 5`; y el evento real del log da 26 131 tokens y no 21 044.
- **Rollback:** aditivo sobre la respuesta.

### Tarea 4 — Los KPIs del panel se sirven de `/api/stats`

- **Ficheros:** `src/local_delegate/web/metrics.py` (JS inline).
- **Qué:** el panel pide `/api/stats` con el mismo rango y pinta los KPIs desde ahí, en vez de sumar
  eventos en el cliente. Tarjetas resultantes: **Contexto conservado** (ahorro, sin cambio de
  definición), **Delegaciones** (con las llamadas al backend en el hint cuando difieren),
  **Coste local** (tokens de entrada reales, nueva), **Generado en local** (pasa a tokens reales),
  **Latencia media** y **Tasa de error**. Cuando `estimated_events > 0`, el hint lo dice.
- **Requisitos:** REQ-001, REQ-002b, REQ-003.
- **Verificación:** `extract_dashboard_js.py` + `node --check`; y test que afirme que el HTML pide
  `/api/stats`. Verificación visual en el dashboard real.
- **Rollback:** el JS anterior queda en git; el endpoint sigue existiendo.

### Tarea 5 — Helper `acct()` en JS y paridad con Python

- **Ficheros:** `src/local_delegate/web/metrics.py` (JS), `tests/test_metrics.py`.
- **Qué:** función `acct(e)` en el JS con **las mismas reglas** que `_accounting`, usada por las
  series por día y por la tabla. Test que extrae el JS con `extract_dashboard_js.py`, lo corre con
  `node` sobre un fixture de eventos que cubre todas las formas, y compara el resultado con el de
  `_accounting`. El test se **salta** (`skip`) si `node` no está en el PATH, para no romper a quien
  no lo tenga.
- **Requisitos:** REQ-002b.
- **Verificación:** el propio test; se comprueba **al revés** (rompiendo una regla en el JS a
  propósito) que detecta la divergencia.
- **Rollback:** test independiente.

### Tarea 6 — La tabla y el chip dicen la verdad

- **Ficheros:** `src/local_delegate/web/metrics.py` (JS).
- **Qué:** el chip `N×` de la tabla pasa a decir *llamadas al backend* y no *trozos* (hoy el título
  dice «Procesado en N trozos» sobre un valor que es `calls`). Los eventos estimados se distinguen
  del dato real.
- **Requisitos:** REQ-003, REQ-006.
- **Verificación:** `node --check` y revisión visual.

### Tarea 7 — Documentación y la decisión sobre OTel

- **Ficheros:** `docs/wiki/Savings-and-metrics.md`, `README.md`, la ayuda inline del panel,
  `CHANGELOG.md`, y la decisión de OTel en `docs/wiki/` (junto al criterio de dependencias).
- **Qué:** explicar ahorro contra coste, cuándo manda el token real y cuándo la estimación, y por qué
  el caso de imagen es distinto. Registrar que **OpenTelemetry queda descartado como fuente de
  métricas**, con las tres razones verificadas, para no re-evaluarlo desde cero.
- **Requisitos:** REQ-008, REQ-009.
- **Verificación:** revisión de links internos y coherencia con la ayuda del panel.

## Estrategia de test

- **Unitario:** `_accounting` por tabla de casos (Tarea 2); `input_unit` en el log (Tarea 1).
- **Integración:** `/api/stats` sobre un log fixture con eventos chunked, sin tokens, de imagen con
  marca y de imagen histórica; se afirman `backend_calls`, `tokens_in` y `estimated_events`.
- **Paridad Python↔JS:** Tarea 5, ejecutando `node`.
- **Estático del panel:** `extract_dashboard_js.py` + `node --check`, como manda el CI.
- **Manual, por ejecución:** disparar una delegación real que trocee (un fichero grande con
  `local_summarize`) contra el backend, con el daemon **reiniciado sobre el código nuevo**, y
  comprobar en el dashboard que las llamadas al backend y el coste aparecen. Sin esto no se da por
  cerrado: los dos bugs del 2026-07-29 aparecieron corriendo el código, no leyéndolo.
- **Secretos:** el change no toca credenciales; los fixtures son contadores sintéticos. Se pasa la
  comprobación de seguridad antes del commit.

## Migración y compatibilidad

- **Log:** solo se **añade** un campo opcional (`input_unit`). Los 111 eventos existentes siguen
  siendo válidos y quedan bien contabilizados por `chunks or 1` y por el nombre de la tool en el caso
  de imagen.
- **`/api/stats`:** solo campos nuevos; los existentes conservan nombre y significado.
- **Números visibles:** «Contexto conservado» **bajará** al corregirse el caso de imagen. Es la
  corrección de un defecto, y queda anotado en el `CHANGELOG.md` para que el salto no parezca una
  regresión.
- **Segunda causa del salto, que hay que declarar:** hoy el JS calcula los KPIs sobre la lista de
  eventos **truncada a `MAX_EVENTS = 5000`**, mientras muestra al lado `meta.count`, el total real.
  En rangos con más de 5000 eventos el panel ya se contradice consigo mismo y **subestima**.
  `_aggregate` no trunca, así que la Tarea 4 cierra de paso esa incoherencia latente. Va al
  `CHANGELOG.md` junto a lo anterior (ver `plan-review.md`, Hallazgo 2).
- **Sin dependencias nuevas.** `node` ya es requisito del CI y su test degrada a `skip`.

## Revisión del plan

- [x] Cada requisito se mapea a al menos una tarea y una verificación.
- [x] Nada destructivo: todo es aditivo y reversible por git.
- [x] Sin dependencias ni configuración nuevas.
- [x] Sin trabajo ajeno al change (el solapamiento del map-reduce y la telemetría de hooks quedan
      fuera, como dice la spec).
