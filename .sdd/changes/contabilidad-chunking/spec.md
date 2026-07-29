# Specification — contabilidad real del chunking y map-reduce en las métricas

Change `contabilidad-chunking`. Basado en `research.md` (evidencia por ejecución sobre 111 eventos
reales y sobre el wheel `mcp` 2.0.0 instalado).

## Resumen

El panel de ahorro mide **lo que se ahorra** y no mide **lo que cuesta**. Una delegación que resolvió
en una llamada y otra que quemó la GPU 16 veces suman exactamente lo mismo en todos los KPIs. El dato
para distinguirlas **ya está escrito en el log** —`chunks` y `tokens_in`/`tokens_out` reales del
backend— y `_aggregate` no lo mira.

Al terminar, el dashboard enseña la contrapartida de coste junto al ahorro, con los tokens reales que
reportó el backend, y deja de aplicar la fórmula `chars ÷ 4` a un campo que en
`local_describe_image` son **bytes de un binario**.

## Decisiones de arquitectura tomadas antes de especificar

- **OpenTelemetry queda descartado como fuente de métricas** (decisión del usuario, 2026-07-29). El
  `usage-YYYYMM.jsonl` sigue siendo la única fuente de verdad. Razones verificadas, en `research.md`
  §4: el middleware del SDK instrumenta el borde MCP y no las llamadas al backend; `opentelemetry-sdk`
  no está instalado, así que hoy los spans son `NonRecordingSpan` y no graban nada; y recogerlos
  exigiría exportador y colector, rompiendo el «un fichero y ya» que hace que el panel funcione recién
  instalado.
- **El sesgo de `local_describe_image` entra en este change** (decisión del usuario): comparte raíz
  exacta —ignorar el token real que ya está en el log— y hoy ese caso distorsiona el KPI principal
  más que todo el resto del log junto.

## Requisitos

> **Tres superficies, no una.** `_aggregate` alimenta `/api/stats`, que **el dashboard no consume**
> (el panel pide `/api/events` y hace sus propias cuentas en JS); y durante la implementación
> apareció una tercera, `local_status`, que recorría el log por su cuenta. El mismo defecto vivía
> por triplicado, así que cada requisito de contabilidad aplica **a las tres**.

- **REQ-001:** Los agregados de `/api/stats` **y las cuentas del panel** exponen el número de
  **llamadas reales al backend**,
  además del número de eventos. Se deriva del log existente (`chunks` cuando está, `1` cuando no), de
  modo que el histórico ya grabado queda contabilizado correctamente sin reescribirlo.
- **REQ-002:** Los agregados usan `tokens_in` / `tokens_out` **reales** del log cuando el evento los
  trae, y solo recurren a la estimación `chars ÷ 4` cuando faltan. La respuesta indica cuántos
  eventos del rango fueron estimados, para que el número sea auditable.
- **REQ-002b:** `/api/stats`, el panel y `local_status` deben dar **el mismo número** para el mismo
  log. Hoy no hay nada que lo garantice y la lógica está triplicada.
- **REQ-003:** El dashboard muestra el **coste** de las delegaciones —llamadas al backend y tokens de
  entrada realmente consumidos, overhead de trocear incluido— de forma que una delegación de 16
  llamadas se distinga a simple vista de una de una sola.
- **REQ-004:** El KPI «Contexto conservado» **conserva su definición** para entradas de texto: el
  contenido leído server-side, contado **una vez**. No se le suma el overhead de trocear, porque ese
  overhead lo pagó la GPU local y no el contexto de Claude. Queda escrito en la documentación para que
  nadie lo "corrija" después.
- **REQ-005:** En `local_describe_image`, `chars_in` son **bytes de un binario**, no caracteres de
  texto. El evento lo declara y los agregados dejan de dividirlos entre 4; para esos eventos el ahorro
  se estima con los tokens reales del backend. Los eventos históricos de esa tool, que no llevan la
  marca, se tratan por el nombre de la tool.
- **REQ-006:** Ningún evento anterior a este cambio rompe el dashboard ni produce un número inventado.
  Un campo ausente degrada a un valor honesto y explicable, nunca a `0` silencioso ni a una
  extrapolación.
- **REQ-007:** El logging sigue siendo best-effort: ningún fallo de contabilidad puede propagar a la
  tool que se está ejecutando.
- **REQ-008:** `docs/wiki/Savings-and-metrics.md` y el `README.md` explican la contabilidad nueva: qué
  es ahorro, qué es coste, cuándo se usa el token real y cuándo la estimación. La ayuda «¿Cómo se
  calcula el ahorro?» del propio dashboard queda coherente con ellos.
- **REQ-009:** La decisión sobre OpenTelemetry queda registrada en el repositorio con su porqué, para
  que no se vuelva a evaluar desde cero.

## Escenarios de aceptación

### Escenario: una delegación troceada frente a una directa

- **Dado** un log con dos eventos de `local_summarize`: uno de una sola llamada y otro con
  `chunks: 4`,
- **Cuando** se piden los agregados de ese rango,
- **Entonces** el total de llamadas al backend es **5**, el total de eventos es **2**, y los dos
  eventos son distinguibles por su coste en el dashboard.

### Escenario: el token real manda sobre la estimación

- **Dado** el evento chunked real del log (`chars_in` 84 178, `chunks` 4, `tokens_in` 26 131),
- **Cuando** se agrega el consumo de entrada,
- **Entonces** se contabilizan **26 131** tokens y no los 21 044 de la estimación por caracteres, y
  el evento **no** se cuenta como estimado.

### Escenario: evento histórico sin tokens

- **Dado** un evento sin `tokens_in` (7 de los 111 del log actual),
- **Cuando** se agrega,
- **Entonces** se usa la estimación `chars ÷ 4`, el evento suma al contador de estimados, y el
  dashboard puede advertirlo sin fallar.

### Escenario: una imagen deja de inflar el ahorro

- **Dado** un evento de `local_describe_image` con `chars_in` = 108 369 bytes y `tokens_in` = 2 232,
- **Cuando** se calcula el contexto conservado,
- **Entonces** el aporte de ese evento es del orden de los tokens reales y **no** 27 092 tokens
  (108 369 ÷ 4).

### Escenario: el ahorro de texto no se toca

- **Dado** un evento de texto con `source: "path"`, `chars_in` 40 000 y `chunks: 3`,
- **Cuando** se calcula el contexto conservado,
- **Entonces** aporta el contenido **una vez** —no tres— porque lo que no entró al contexto de Claude
  fue el documento, no el trabajo de la GPU.

## Casos límite y comportamiento ante fallo

- Evento con `ok: false` a mitad de un troceado: las llamadas ya hechas **se cuentan** como coste,
  porque la GPU las gastó.
- Evento con `chunks` presente y `tokens_in` ausente: coste de llamadas real, tokens estimados.
- Log vacío o rango sin eventos: los contadores nuevos valen `0` y el panel no revienta.
- Línea JSONL corrupta: se sigue ignorando como hoy, sin cambiar ese comportamiento.

## Requisitos no funcionales

- **Compatibilidad:** el formato del log solo puede **añadir** campos opcionales; ningún consumidor
  existente puede romperse. El dashboard debe seguir leyendo logs escritos por versiones anteriores.
- **Rendimiento:** el agregado recorre el log en una pasada, como hoy. Nada de segundas lecturas.
- **Privacidad:** no se añade al log ningún dato nuevo derivado del contenido del usuario. Los
  campos nuevos son contadores.
- **Operabilidad:** el dashboard sigue funcionando recién instalado, sin configurar servicios.

## No-goals

- **No** se monta OpenTelemetry, ni exportadores ni colectores (REQ-009 registra el porqué).
- **No** se reescribe ni migra el log histórico.
- **No** se toca la estrategia de troceado en sí: la ventana de solapamiento y el glosario acumulado
  del map-reduce son **otra deuda del backlog**, con su propio change.
- **No** se cambia `CHARS_PER_TOKEN` como constante de respaldo ni se añade un tokenizer real.
- **No** se conecta la telemetría de hooks (`LD_HOOK_TELEMETRY_LOG`) al dashboard: otro pendiente.
- **No** se añade autenticación al dashboard.

## Trazabilidad

| Req | Trabajo previsto | Evidencia de verificación |
|---|---|---|
| REQ-001 | `_accounting` + `_aggregate` | `test_stats_distingue_delegaciones_de_llamadas_al_backend`; log real: 111 eventos → 114 llamadas |
| REQ-002 | `_accounting` + `/api/stats` | `test_accounting_troceado_separa_ahorro_de_coste`, `test_stats_marca_los_eventos_que_hubo_que_estimar` |
| REQ-002b | `_accounting` única en `server.py`, compartida por las tres superficies | `test_paridad_acct_entre_python_y_el_js_del_panel`, `test_local_status_y_el_dashboard_cuentan_igual`; en vivo: `local_status` y `/api/stats` dan 118 llamadas y 256 732 tok |
| REQ-003 | KPI «Coste local» + llamadas al backend + chip de la tabla | panel en vivo: «12 delegaciones · 18 al backend (+6 por trocear)» |
| REQ-004 | `_accounting` (ahorro una vez) + wiki | delegación real: ahorro 23 754 vs coste 29 068 |
| REQ-005 | `input_unit` en `_log_event` + `_accounting` | `test_describe_image_logs_real_tokens_and_path`, `test_accounting_imagen_usa_el_token_real_y_no_los_bytes` |
| REQ-006 | degradación explícita en `_accounting` | 3 tests + agregado sobre los 111 eventos históricos |
| REQ-007 | `_log_event` intacto en su `try/except` | diff |
| REQ-008 | wiki, README y ayuda del panel | diff de documentación |
| REQ-009 | decisión de OTel en las decisiones de diseño | `docs/wiki/Architecture.md` |
