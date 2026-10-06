# Brief: coste equivalente a precio de API y % de cuota sin calibrar

## Problem

El usuario quiere ver en el panel cuánto ahorró de la cuota de 5 horas, cuánto de la semanal, y
cuánto habría costado cada ahorro a precio de la API de Anthropic. La investigación de viabilidad
(`insumos/viabilidad-cuota.md`) concluye:

- **Coste a precio de API: viable como estimación.** Cota baja: los tokens ahorrados × el precio de
  escritura de caché. Estimación: eso más N lecturas de caché posteriores (de los transcripts: la
  mediana es 49,5 y el p90, 215). Los subagentes escriben la caché a 5 min y el hilo principal a
  1 h, y 140 de 166 delegaciones van por subagentes.
- **% de cuota: no mostrable todavía.** Anthropic no publica la cuota en tokens. El statusline da
  `rate_limits.five_hour/seven_day.used_percentage` (verificado el 2026-10-06: enteros de 0 a
  100, con `resets_at` en epoch), sin desglose por modelo. Para traducir ahorro a % hace falta
  calibrar si la cuota sigue al coste a precio de lista. Los rechazos de cuota guardados en los
  transcripts dan puntos de calibración gratis: una ventana de 5 h equivale a ~$126 y una semana
  a ~$400, pero es un solo punto de cada tipo.
- **chars/4 subestima** los tokens de Claude (indicio: ~2,2 chars/token), pendiente de
  confirmar.

## Desired outcome

El panel muestra el «equivalente estimado a precio de API: entre $X y ~$Y» con los supuestos a la
vista y una tabla de precios versionada en el paquete, sin red en tiempo de ejecución. Los % de
cuota se muestran como «sin calibrar» hasta que la calibración cumpla un criterio escrito de
antemano. Nunca se afirma «ahorraste $» ni «tokens de tu cuota».

## In scope

- Tabla de precios versionada (fecha de consulta y fuente), con un control que la compare con el
  coste que calcula Claude Code y que pueda fallar (ya falló una vez: faltaba `claude-opus-5`).
- **La tabla se actualiza sola** (pedido del usuario, 2026-10-06): un workflow semanal de CI, como
  los vigilantes que ya hay en el repo (`vigilante-vendorizado`, `vigilante-captura-readme`), lee
  la página oficial de precios y abre un PR si cambia algo. También vigila la página de ayuda de
  límites de uso y abre un aviso si cambia. La red solo se usa en el CI, nunca en ejecución. Un
  modelo que no está en la tabla sale «sin precio», nunca con un precio adivinado. La deriva de
  la calibración (dispersión por encima del umbral) devuelve la cuota a «sin calibrar», y eso
  sustituye a la fecha de cambio de límites mantenida a mano.
- **La densidad (chars/token) depende del modelo y del contenido**, no del esfuerzo: ver
  `insumos/densidad-por-modelo.md` (en curso). El esfuerzo sí cambia el consumo de una tarea, y
  con él las relecturas posteriores. El registro del statusline guarda `effort` desde el
  2026-10-06.
- Fórmula de coste (cota baja y estimación) sobre la cifra **neta** de contexto conservado que
  define `panel-cuentas-y-estados-honestos`, de la que este cambio depende.
- Bloque de cuota en el panel con estado «sin calibrar», y el criterio de calibración: al menos 3
  puntos con dispersión menor al 25 %, con los puntos de rechazo de los transcripts y el registro
  del statusline.
- El experimento de chars por token (una lectura controlada), y la corrección del factor si se
  confirma.

## Out of scope

- El experimento E12 (cuánto pesa la lectura de caché en la cuota): gasta un 5–15 % de una
  ventana y se corre con el usuario delante, en otro momento.
- Consultar la red para los precios.

## Constraints and risks

- **El registro del statusline ya está activo** desde el 2026-10-06 (experimento E11, con permiso
  del usuario): `~/.claude/statusline.ps1` anexa a `~/.claude/cuota-statusline.jsonl` las
  filas `ts, session_id, model, five_hour, five_reset, seven_day, seven_reset, cost_usd` cuando
  cambian, y guarda el último JSON crudo en `~/.claude/cuota-statusline-muestra.json`. Su
  copia de seguridad es `statusline.ps1.bak-2026-10-06`. El registro es de la máquina del usuario,
  no del paquete. Si el panel lo lee, tiene que tolerar que no exista (otras máquinas, la Mac).
- Leer transcripts de `~/.claude/projects` en tiempo de ejecución tiene coste y toca privacidad:
  la spec decide si se hace en ejecución, en un comando aparte o con parámetros precalculados.
- Los mismos de `panel-cuentas-y-estados-honestos`: el espejo JS y su test de paridad, el mock de
  `tests/test_captura.py`, los helpers `_env*`, LF/CRLF, el control positivo y el cerrojo de
  comandos pesados.

## Decisiones del usuario (2026-10-06)

- «Contexto conservado» pasa a tokens reales de Claude, aunque la cifra suba.
- **No hay un modelo supuesto para todo**: cada delegación se atribuye a su modelo y esfuerzo de
  Claude, investigado y comprobado (`insumos/atribucion-modelo-esfuerzo.md`). Cuando falte el
  dato, hay un respaldo declarado y visible.
- Para dar la cuota por calibrada hace falta al menos un punto del registro del statusline.
- Un punto de calibración caduca a los 60 días. La deriva de la calibración sustituye a la fecha
  de cambio de límites mantenida a mano.

Confirmadas por el usuario sobre la spec v2 (2026-10-06):

- La cuota se calibra **solo con puntos del registro del statusline**: hacen falta 3, de ventanas
  distintas, y los rechazos de cuota quedan como comprobación.
- Las imágenes cuentan **0 tokens** de Claude en la cifra principal y se enseñan aparte.
- El relleno del histórico lo lanza el usuario con un comando; `doctor` avisa a los 20 días.
- El vigilante lanza `ci.yml` por `workflow_dispatch` sobre su PR.

## Open questions

- ¿N se calcula de los transcripts del usuario o se fija con un valor declarado?
- ¿Qué modelo de Claude se asume para el precio si el log no lo guarda?
- ¿Dónde vive el registro de calibración, y qué hace el panel cuando no lo hay?
