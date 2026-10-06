# Revisiones: Panel: coste equivalente a precio de API y % de cuota sin calibrar

## Revisión de la spec

Fecha: 2026-10-06. Revisión adversaria, en solo lectura, de `spec.md` contra `brief.md` (incluida la
ampliación de alcance del mismo día), `research.md`, `insumos/viabilidad-cuota.md` y la spec del
cambio hermano `panel-cuentas-y-estados-honestos/spec.md` (ya escrita).

**Veredicto propuesto: no aprobable en su forma actual.** Tiene tres bloqueantes: la interfaz con el
cambio hermano no coincide con lo que ese cambio ya fijó, los puntos de calibración del statusline
no son independientes, y la spec no cubre dos puntos que el brief ya pide. Los tres tienen arreglo
concreto. La aritmética de los escenarios y casi todas las cifras citadas cuadran (ver «Comprobado
y correcto», al final).

### Bloqueantes

**1. La interfaz con el cambio hermano no coincide con lo que ese cambio ya definió.**
- Evidencia: `spec.md:18-23` pide «el neto en **caracteres** (o, si el otro cambio lo deja en
  tokens `chars/4`, ese valor […] `4 / c`)». El hermano ya lo decidió, y en tokens: `saved`,
  `returned` y `net` por evento con `÷ CPT` (`panel-cuentas-y-estados-honestos/spec.md:54-68`), y
  `tokens_context_net` en `/api/stats` (`:26-27`). Hay tres choques:
  - (a) En un evento `output_to_file` con `source=path`, el `net` del hermano es «entrada + salida
    escrita» (`:65`, `:395`), y esa salida son `tokens_out` **locales**. Las imágenes van en `saved`
    con su token local (`:393-394`). REQ-020 (`spec.md:85-89`) excluye las dos partes, pero a partir
    de `net` no se pueden separar sin recalcular la regla, que es justo lo que `spec.md:19-20`
    promete no hacer.
  - (b) La regla del hermano usa **un solo** `CPT` para `tokens_out` local (`:60`) y para
    `returned` (`:67`), que es lo que volvió al contexto **de Claude**. REQ-010/011 separan las dos
    densidades pero no dicen cuál le toca a `returned`.
  - (c) El control con datos reales del hermano (septiembre: bruto 873 270, devuelto 72 342, neto
    800 928, `:285`) deja de cumplirse en cuanto entre REQ-011, y la spec no dice quién actualiza
    ese escenario y su test.
- Arreglo: la interfaz se declara en **las dos** specs. Propuesta: `_accounting` expone por evento
  los componentes en caracteres (`chars_leidos_path`, solo si `ok`, `source=path` y unidad
  estimable; y `chars_devueltos`), además de los tokens. Este cambio solo los divide por `c`. Hay
  que decir qué densidad lleva `returned`, y que este cambio reescribe el escenario de septiembre
  del hermano con las cifras nuevas (o que lo mantiene en `chars/4`, si gana la alternativa de la
  decisión 1).

**2. Los puntos del statusline no son independientes, así que el criterio de calibración se puede
cumplir sin pruebas nuevas.**
- Evidencia: REQ-032 (`spec.md:120-125`) define un punto como «un par de filas de la misma sesión y
  el mismo `resets_at` […] con Δ% ≥ 10», y no exige que los pares sean disjuntos ni que haya uno por
  ventana. Una sesión que va del 10 % al 50 % en una ventana da los pares (10,20), (10,30), (20,40),
  (30,50)… Son tres o más «puntos» con casi la misma `C`, porque comparten Δ$, así que REQ-034
  (a) y (c) se cumplen con **una sola** observación. Es un control que no puede dar un resultado
  distinto: «≥ 3 puntos» debería significar tres observaciones independientes.
- Arreglo: un punto del statusline por `(tipo, resets_at)`, el del par más ancho válido (la primera
  y la última fila de la ventana sin reinicio de `cost_usd`), o tramos consecutivos disjuntos.
  REQ-034 (a) cuenta ventanas distintas. Hace falta un test con una sesión de cinco filas en una
  sola ventana que tiene que dar **un** punto.

**3. La spec no cubre dos puntos que el brief ya incluye (ampliación del 2026-10-06), y choca con
ellos.**
- Evidencia: `brief.md:33-43`.
  - **Vigilante semanal de precios y límites.** No hay ningún REQ para él. Además:
    - El non-goal «Precios por red» (`spec.md:281`) lo contradice: debería decir «en ejecución».
    - `limites_cambiaron` (REQ-001, `spec.md:45`) y el descarte de REQ-033 (`spec.md:126-128`) son
      exactamente la «fecha de cambio de límites mantenida a mano» que el brief sustituye por la
      deriva de la calibración.
    - La deriva **no se detecta** con la dispersión de REQ-034 (c). Esa medida es robusta a
      propósito: el escenario «un punto raro no lo tumba» (`spec.md:212`) lo celebra. Por eso,
      tras un cambio de límites seguiría `calibrado` hasta que cerca de la mitad de los puntos
      fueran posteriores al cambio.
    - REQ-006 avisa por la edad de `consultado` (90 días). Con un vigilante semanal hay que definir
      si `consultado` es la fecha de la última comprobación o la del último cambio; si no, `doctor`
      avisará en tablas que el CI revisa cada semana.
  - **Densidad por modelo y por contenido.** Las definiciones (`spec.md:27-30`), REQ-010 a REQ-013,
    REQ-021, el escenario de `spec.md:190` y la decisión 1 («~1,9×», `spec.md:294-296`) suponen una
    `c` global de 2,1/2,2. La definición de 2,7 para el tokenizador anterior no la usa ningún REQ:
    si la variable de modelo de REQ-022 apunta a Haiku 4.5 o a Sonnet 4.6, la fórmula sigue con 2,1
    (~30 % más tokens). El brief dice además que el esfuerzo cambia las relecturas (`brief.md:40-43`),
    y REQ-023 trata `N` como un solo número.
- Arreglo (para la reescritura):
  - **Requisitos del vigilante.** Un workflow propio con cron. El patrón del repo es
    `.github/workflows/vendor-audit.yml`; no existen workflows llamados `vigilante-vendorizado` ni
    `vigilante-captura-readme`, como nombra el brief. El vigilante abre un PR con la tabla nueva y
    **falla en voz alta** si la página cambia de forma y no se puede leer: un parseo vacío no
    puede pasar por «sin cambios». Su control positivo es una página guardada con un precio
    alterado, que tiene que producir un diff. Ojo: el ruleset de `main` exige commits **firmados**,
    y un `git commit` + `push` desde el runner queda `BLOCKED`. El PR tiene que salir con commits
    firmados (p. ej. creados por la API de contenidos) o la spec tiene que decir cómo se firman.
  - **Deriva.** Sustituir `limites_cambiaron` por una regla explícita de deriva, por ejemplo: «si
    el punto más reciente se aleja más del 25 % de la mediana de los anteriores, el tipo vuelve a
    `sin calibrar` y los puntos anteriores dejan de contar». Conservar un reinicio manual a partir
    del aviso del vigilante de límites.
  - **Densidad.** `c` pasa a ser una tabla `c(familia de tokenizador, clase de contenido)` versionada
    junto a los precios, con «sin medir» rotulado. La clase sale de la extensión del `path` del log
    (el log de uso sí guarda `path`). La familia sale del modelo **supuesto**, porque el log no
    guarda el modelo de Claude (`research.md:198`). Los REQ concretos esperan a
    `insumos/densidad-por-modelo.md`, que todavía no existe.
  - **Esfuerzo.** Decir si `N` se desglosa por esfuerzo o se queda global con ese sesgo declarado.
    De paso: 82 de las 98 filas actuales de `~/.claude/cuota-statusline.jsonl` no traen `effort`, y
    el lector tiene que tolerarlo. La lista de campos de `brief.md:62` tampoco lo incluye.

### Importantes

**4. Exigir un punto del statusline (REQ-034 b) no evita el sesgo que dice evitar.**
- Evidencia: la decisión 3 (`spec.md:299-300`) dice que la condición evita que «tres rechazos (cotas
  bajas)» inflen el %. Pero con 2 rechazos y 1 punto del statusline, la mediana sigue siendo un
  rechazo. Ejemplo: `C` = 126, 126 y 170 da una dispersión de 14,9 % < 25 %, así que sale
  `calibrado` con `mediana(C)` = 126, sesgada a la baja.
  - El Δ$ de un rechazo recoge solo el 69–77 % del coste en sesiones grandes (`research.md:88-89`,
    `:115-116`). Ese sesgo es del mismo orden que el umbral del 25 %, así que el criterio no puede
    verlo.
  - Los puntos del statusline también salen bajos cuando otras superficies gastan la misma cuota
    (`research.md:115`). El caso límite de `spec.md:243-244` solo caza la ventana **sin ningún** uso
    local.
- Arreglo: `mediana(C)` y la dispersión se calculan solo con puntos del statusline. Los de rechazo
  quedan como comprobación (`C_statusline ≥ C_rechazo`; si no, aviso). Los puntos del statusline
  se declaran «cota baja si hubo uso en otras superficies».

**5. El % calibrado no dice sobre qué periodo se calcula.**
- Evidencia: REQ-036 (`spec.md:138-142`) calcula A = cota baja ÷ mediana(C) × 100 «de una ventana de
  5 h», pero la cota baja es la del periodo que elige el panel (hoy, 30 días…). Sobre 30 días saldría
  «≈ 400 % de una ventana de 5 h», que no tiene sentido.
- Arreglo: definir el numerador por ventana. Por ejemplo, el ahorro de los eventos con `ts` dentro
  de la última ventana de 5 h (o de la semana en curso), o la media por ventana con actividad. El
  rótulo dice cuál.

**6. Dos desempates para `N` sin orden entre ellos.**
- Evidencia: REQ-022 (`spec.md:95-97`) hace `N` configurable por variable de entorno, y REQ-023
  (`spec.md:98-100`) dice «declarado salvo que exista un recálculo guardado». No se dice qué gana
  si hay variable **y** JSON: la regla no es ejecutable.
- Arreglo: orden explícito «variable > JSON del comando > declarado», el panel nombra la fuente
  usada, y un test cubre las tres.

**7. El algoritmo de `N` no está en la spec.**
- Evidencia: REQ-040 (`spec.md:150-154`) solo dice «`N` (mediana, p10, p90…)». La definición vive en
  el insumo: «peticiones posteriores a la delegación en el mismo hilo, hasta el fin del hilo o el
  primer `compact_boundary`», excluyendo los bancos `Temp-banco-*` (`viabilidad-cuota.md:103`,
  `:105`). Sin ella, dos implementaciones dan números distintos. Ya pasa: el insumo midió 166
  delegaciones y `research.md` §7 contó 168.
- Arreglo: copiar la definición con sus exclusiones en un REQ, y probarla con un transcript
  sintético cuyo `N` se conozca de antemano.

**8. REQ-011 cita una línea equivocada y le faltan sitios por cambiar.**
- Evidencia:
  - `server.py:367` **no** es «el mensaje de ahorro que devuelve la tool». Es el recibo de
    `_escribir_destino` (`server.py:351-368`), o sea, la salida a fichero, cuyo contrafactual
    REQ-020 declara que no es una lectura.
  - El mensaje de ahorro real es `_savings_feedback` (`server.py:1185-1189`, llamado en `:1317`,
    `:1617` y `:1950`). Usa primero el `tokens_in` **local** y `chars/4` solo de respaldo.
  - `leido_server_side.tokens_aprox` (`server.py:2394`) también habla a Claude. `research.md:209-211`
    clasifica `:1189` y `:2394` como tokens del modelo local, y no lo son.
  - Faltan además `CHARS_PER_TOKEN` en `web/metrics.py:55`, la constante JS `CPT = 4`
    (`web/metrics.py:1218`) y la línea de `local_status` que define el hermano (su REQ-005,
    `panel-cuentas-y-estados-honestos/spec.md:34-35`).
- Arreglo: listar en la spec, sacados con `grep`, todos los usos de `CHARS_PER_TOKEN` y `CPT`,
  clasificar cada uno como Claude o local, y decir qué hace `_savings_feedback` cuando hay
  `tokens_in` local (que no es un token de Claude).

**9. La «cota baja» solo es cota baja bajo supuestos que no se enseñan.**
- Evidencia: el neto no descuenta las relecturas del mismo fichero, que según el insumo son entre
  el ~3 % y el ~30 % (`viabilidad-cuota.md:42`; el hermano lo deja fuera, `:427`). Además, si el
  modelo real fue más barato que el supuesto (Sonnet o Haiku), la cifra queda por encima. REQ-024
  (`spec.md:101-103`) no incluye las relecturas entre los supuestos visibles, y REQ-021 la llama
  «cota baja» sin condición.
- Arreglo: añadir a REQ-024 «no descuenta relecturas del mismo fichero (medidas entre ~3 % y ~30 %)»
  y rotular «cota baja con estos supuestos».

**10. El test del cotejo puede quedar sin poder fallar.**
- Evidencia: el escenario usa «filas sintéticas construidas con la tabla oficial» (`spec.md:181-183`,
  `:258`). Si el fixture se calcula en el test a partir de la tabla cargada, un mutante de la tabla
  cambia a la vez las filas y lo esperado, y el test nunca falla.
- Arreglo: los números del fixture se congelan como literales (mejor, filas reales de `cost-state`
  reducidas a números). El test lleva una guarda que comprueba que, con la tabla sin mutar, el
  fixture sale `dentro`.

**11. La evidencia del cotejo se midió con otra regla y no se puede reproducir.**
- Evidencia: el único script guardado, `scratchpad/scripts/e10b.py`, usa una tolerancia absoluta de
  ±$0,005 (`:39`), busca el modelo por prefijo (`:12-14`) y **no suma la búsqueda web** (`:33`).
  Ejecutado hoy en solo lectura da «filas 108, dentro: 104»: los 4 de Haiku que explica
  `research.md:46-48`. El 108/108 con búsqueda web y los conteos de los mutantes (33, 69, 36, 61,
  12, 11, 5; `research.md:80-84`) no tienen script guardado. REQ-004 usa otra regla: ±máx($0,005;
  0,5 %) e id exacto. Y la tabla de controles (`spec.md:257`) dice «33 filas sin precio quitando
  Opus 5», pero `research.md:81` no dice qué modelo se quitó.
- Arreglo: guardar el script que implementa REQ-004 tal cual, volver a medir el 108/108 y los
  mutantes con esa regla, y citar ese script.

**12. El caso «transcripts borrados a los 30 días» no tiene un REQ que lo cumpla.**
- Evidencia: `spec.md:250-251` dice que los puntos ya guardados siguen vigentes hasta los 60 días.
  Pero REQ-040 escribe «**un** JSON» y no dice que conserve los puntos anteriores: si lo sobrescribe,
  el punto de rechazo del 2026-10-01 desaparece cuando se borre su transcript. Tampoco se dice
  **quién** aplica la caducidad de 60 días de REQ-033: si la aplica solo el comando, un JSON viejo
  deja el panel `calibrado` para siempre.
- Arreglo: un REQ que diga que el comando funde los puntos con los del JSON anterior por clave
  `(tipo, inicio, fin)` (REQ-043 sigue valiendo), y que el panel aplique la vigencia al leer.

### Menores

**13. Un escenario fija un conteo que va a cambiar.** `spec.md:168-171` exige «108 filas»: los
transcripts rotan a los 30 días y salen sesiones nuevas, así que ese número ya no se va a repetir.
Arreglo: «todas las juzgables dentro, 0 fuera, 0 sin precio», y anotar `n` y la fecha en la
verificación.

**14. Las cuentas citadas salen de dos mediciones distintas y no se dice.** REQ-022 dice «140 de 168»
(`research.md:190-196`); REQ-023 dice «166 delegaciones» (`viabilidad-cuota.md:105`). El brief dice
«140 de 166 delegaciones van por subagentes» (`brief.md:12`), mientras que en `research.md` §7 los
subagentes suman 142 de 168. Arreglo: indicar de qué medición sale cada cifra.

**15. Un caso del statusline queda para el plan y faltan detalles de REQ-032.** Las filas del
registro se llaman `five_reset`/`seven_reset`, no `resets_at`. No se dice cómo se reparte un
incremento de `cost_usd` que cruza el inicio del intervalo. Y el par con Δ$ = 0 (que da `C` = 0)
se deja al plan: es la «variante que el plan concreta» de `spec.md:244`. Arreglo: escribirlo en
REQ-032 (descartar con motivo `sin_uso_local`).

**16. Peticiones sin precio dentro de una ventana de rechazo.** REQ-031 (`spec.md:117-118`) no dice
qué pasa si una petición del intervalo es de un modelo sin precio. Arreglo: el punto lleva la
marca y el número de peticiones sin precio, o se descarta.

**17. A la lista de frases prohibidas le falta una que el panel ya dice.** REQ-025 no incluye
«ahorro de cuota», y el panel ya lo dice en su descripción: «Uso y ahorro de cuota de las
delegaciones» (`web/metrics.py:805`). Es la afirmación que el brief prohíbe. Arreglo: añadirla a
la lista o acordar con el hermano (que lleva la presentación) quién la cambia.

**18. REQ-003 (sin red) no tiene test en la trazabilidad.** Arreglo: un test que bloquee los sockets
y cargue la tabla y `/api/stats`.

**19. «La última `cost-state` por sesión y `startTime`» (REQ-005) no dice el orden.** `e10b.py:22`
se queda con la última en el orden de `glob`. Arreglo: la última por posición dentro del fichero, o
por marca de tiempo si la hay.

**20. La paridad del redondeo entre Python y JS queda abierta.** Con `c` decimal, `//` en Python y
`Math.floor` en JS pueden diferir por coma flotante en los bordes. Arreglo: fijar la operación (p.
ej. `floor(chars * 10 / 21)` en enteros) en REQ-013.

**21. Faltan ids exactos de modelo.** REQ-002 busca por id exacto, pero `research.md:32-42` no da el
id de Fable 5.1, Sonnet 5.5 ni Opus 4.5–4.8. Arreglo: sacarlos de la documentación oficial de
modelos (o del vigilante), no deducirlos del nombre comercial.

**22. Quedan decisiones abiertas.** La decisión 1 condiciona REQ-011, REQ-013 y el control de
septiembre del hermano (hallazgo 1c). El gate de la spec no se puede cerrar sin la respuesta del
usuario a las decisiones 1 a 4 (`spec.md:292-302`).

### Comprobado y correcto

- **Escenario de coste** (`spec.md:190`): 1 000 000 ÷ 2,2 × 5/10⁶ = $2,27, y 1 000 000 ÷ 2,1 ×
  (5 + 49,5 × 0,20)/10⁶ = $7,10.
- **Dispersión de los escenarios** (`spec.md:210-214`), recalculada con la definición de REQ-034:
  {150, 160, 170, 175} da 7,8 %; con 300 añadido, 7,2 %; {100, 160, 250} da 51,2 %.
- **Densidad**: 2,02, 1,94 y 2,15 coinciden con `research.md:162-164`, y 4 ÷ 2,1 = 1,90.
- **Modelos y `N`**: 140 de 168 coincide con `research.md:192`, y la mediana de 49,5 con
  `viabilidad-cuota.md:106`. El p90 de 215 no se cita en la spec.
- **Rechazos**: los 11 registros que se reducen a un punto coinciden con `research.md:108`. Las
  anclas de $126 y $400 no aparecen en la spec, y es correcto que no aparezcan como cifra.
- **Punto ciego del cotejo**: coincide con `research.md:83-84`.
- **Referencias al código**: `config.py:351`, `server.py:614`, `:616`, `:621` y
  `tests/test_metrics.py:648` existen y dicen lo que la spec cita. `doctor` tiene el estado `warn`
  (`checks.py:44`) y la regla «nunca `missing`» (`checks.py:12`).
- **Privacidad**: REQ-041 y REQ-042 y su test con cadena marcadora cubren lo pedido. Ni el daemon ni
  el panel leen transcripts, y el JSON lleva solo agregados.

### Llamadas a `local-delegate`

1 llamada: `local_summarize(path=panel-cuentas-y-estados-honestos/spec.md, focus=contabilidad)`.
Sirvió para comprobar que no se me escapaba ningún REQ del hermano sobre tokens. Lo que cito de esa
spec lo verifiqué después con `grep` sobre el texto literal.

No hubo más porque esta revisión exige números y líneas literales:
- `spec.md`, `research.md` y `brief.md` los leí por franjas.
- Del insumo, de `server.py` y de los scripts de medición busqué con `grep` las líneas exactas.
- El script `e10b.py` lo ejecuté en solo lectura para comprobar el 108/108 (sale 104 de 108).

## Revisión del resultado (plantilla, se rellena al cerrar)

### Verdict

Choose one: `conforms`, `conforms-with-notes`, or `does-not-conform`.

### Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | | | |

### Findings

- List correctness, security, maintainability, or scope findings in severity order.

### Required follow-up

- Identify work that must be completed before closure.

## Respuesta a la revisión

Fecha: 2026-10-06. La spec se reescribió entera (versión 2). Los REQ cambiaron de número: la tabla
dice dónde quedó cada arreglo con la numeración nueva. Todas las cifras que cita la spec salen
ahora de los scripts de `insumos/scripts/` (resumen en `research.md` §0).

| # | Hallazgo | Resolución | Dónde quedó |
|---|---|---|---|
| 1 | La interfaz con el hermano no coincidía con lo que ya fijó (neto en tokens, `net` mezclado con salida e imágenes, una sola densidad para `returned`, escenario de septiembre) | Se consume el contrato del hermano tal cual (campos en caracteres, imagen en bytes, `tokens_claude` / `tokensClaude`) y solo se sustituye el cuerpo de la función. La base de coste se arma con `chars_saved_text` y `chars_returned`, sin pasar por `net`. `returned` tiene su densidad (sin numerar, clase por tool). Septiembre en tokens lo recalcula la verificación de este cambio; en caracteres no cambia | «Dependencia: el contrato…»; Definiciones (`T`); REQ-031, REQ-036, REQ-037, REQ-040 |
| 2 | Puntos del statusline no independientes | Un punto como mucho por (tipo, reset), del par más ancho de una misma sesión; ventanas solapadas se descartan; el criterio cuenta puntos, que ya son ventanas distintas. Test: cinco filas de una ventana dan un punto | REQ-052, REQ-053; escenario «varias filas de una ventana son un solo punto» |
| 3 | Faltaban el vigilante y la densidad por modelo y contenido, y chocaban con la spec | Vigilante: workflow propio con cron (patrón `vendor-audit.yml`), PR firmado por la API de contenidos, falla en voz alta, control con páginas guardadas, aviso de límites por PR. Sin `limites_cambiaron`: lo sustituyen la deriva y el reinicio a mano. `consultado` = fecha del último cambio y `doctor` ya no avisa por edad. Non-goal corregido a «red en ejecución». Densidad: tabla por familia × columna (`Read` o sin numerar) × clase, con dos respaldos ordenados. Esfuerzo: se guarda y se desglosa, no entra en la fórmula (medido: no cambia la entrada; todas las delegaciones reales fueron `high`). El lector del statusline tolera filas sin `effort` (82 de 144) | REQ-020 a REQ-024; REQ-015; REQ-056, REQ-057; REQ-030 a REQ-034; REQ-009; REQ-052; Non-goals |
| 4 | Exigir un punto del statusline no evitaba el sesgo de los rechazos | La mediana y la dispersión usan solo puntos del statusline (≥ 3); los rechazos quedan como comprobación con aviso; los del statusline llevan la marca «cota baja si hubo otras superficies». Pide confirmación (decisión 1) | REQ-051, REQ-052 (7), REQ-055, REQ-058 |
| 5 | El % no decía sobre qué periodo | Ventana móvil que termina ahora (últimas 5 h o últimos 7 días), independiente del periodo del panel, y el rótulo lo dice | REQ-060 |
| 6 | Dos desempates para `N` sin orden | Un solo orden por evento: relleno > mediana del grupo (≥ 10 casos) > declarado por hilo. Sin variable de entorno para `N`. El respaldo de modelo tiene su propio orden (variable > declarado) | REQ-042, REQ-008, REQ-006 |
| 7 | El algoritmo de `N` no estaba en la spec | Copiado en un REQ con petición, `t0`, corte, caducidades y percentiles; test con transcript sintético de `N` conocido. Implementación de referencia en `atribucion_n.py` | REQ-043 |
| 8 | REQ-011 citaba mal `server.py:367` y le faltaban sitios | Tabla sacada con `grep` de todos los usos de `CHARS_PER_TOKEN` y `CPT`, clasificados Claude/local, con qué pasa en cada uno; `_savings_feedback` deja de presentar el `tokens_in` local como tokens de Claude | REQ-034, REQ-035; `research.md` §8 corregido |
| 9 | La «cota baja» lo era solo bajo supuestos no enseñados | Supuestos visibles con «no descuenta las relecturas del mismo fichero (~3 %–~30 %)» y rótulo «cota baja con estos supuestos»; el modelo ya no es supuesto salvo en el respaldo, y la barra dice cuántos | REQ-044, REQ-007 |
| 10 | El test del cotejo podía no poder fallar | Fixture con números literales congelados; los mutantes fallan por el assert del veredicto; guarda de que sin mutar sale `dentro` | Escenario «el cotejo caza un modelo que falta…»; Controles |
| 11 | La evidencia del cotejo no se reproducía (104 de 108) | `cotejo.py` implementa la regla de la spec tal cual (búsqueda web, id exacto, tolerancia, última `cost-state` por posición): **142 de 142** hoy; mutantes remedidos y citados con su modelo | REQ-014; Controles; `research.md` §0 |
| 12 | Transcripts borrados: ningún REQ conservaba los puntos ni aplicaba la caducidad | El comando funde puntos por clave y no borra; la vigencia de 60 días la aplica el panel al leer; escenario de un punto de 61 días sin regenerar el JSON | REQ-071, REQ-054; escenario «un punto viejo caduca…» |
| 13 | Un escenario fijaba «108 filas» | «Todas las juzgables dentro», con `n` y fecha en la verificación | Escenario «la tabla cuadra…» |
| 14 | Cifras de dos mediciones sin decirlo | La spec cita solo las de `atribucion_n.py` (149 atribuidas: 135 + 14); las viejas, marcadas como de otro barrido | REQ-007, REQ-008, REQ-042; `research.md` §0 y §7 |
| 15 | Detalles de REQ-032: nombres de campos, incremento que cruza el inicio, Δ$ = 0 | Campos `five_reset` / `seven_reset`; el incremento cuenta entero si su fila posterior cae en el intervalo; Δ$ = 0 → `sin_uso_local` | REQ-052 (4) y (5) |
| 16 | Peticiones sin precio en una ventana de rechazo | El punto lleva el número de peticiones sin precio; como el rechazo ya solo es comprobación, no se descarta | REQ-051 |
| 17 | Faltaba «ahorro de cuota», que el panel ya dice | Añadida, junto con «cuota que no gastaste» (`metrics.py:1199`); este cambio reescribe `:805` y `:1199` | REQ-045 |
| 18 | REQ-003 (sin red) sin test | Test con los sockets bloqueados | REQ-012; Controles; Traceability |
| 19 | «La última `cost-state`» sin orden | La última por posición en el fichero (el total nunca baja: 153 de 153 claves) | REQ-014 |
| 20 | Paridad del redondeo Python/JS | Densidad en centésimas enteras y la misma operación, con el argumento de por qué la coma flotante no cruza un entero | REQ-033 |
| 21 | Faltaban ids exactos de modelo | Sacados de «Models overview» y «Model IDs and versioning»; los 13 ids en la spec y en `precios.json` | REQ-010 |
| 22 | Decisiones abiertas | Las cuatro de la versión 1 las tomó el usuario (quedan anotadas con su REQ); hay cinco nuevas que siguen abiertas | «Decisiones ya tomadas…» y «Decisiones que necesitan al usuario» |

**Cifras nuevas que conviene mirar antes de aprobar:** con la regla de la spec, la estimación de la
ventana medida sube de $25,84 (versión 1) a $92,69, sobre todo por Opus 5 en el hilo principal
(14 casos, `N` mediano 127, y su precio real, más caro que el de Opus 5.5 que suponía el insumo).
La cota baja pasa de $8,28 a $11,50 (`atribucion_n.py`, los mismos eventos).

**Llamadas a `local-delegate` en la reescritura: 0.** Motivo: todo lo que había que leer se iba a
citar o editar literalmente (spec, review, research, brief, los dos insumos y el contrato del
hermano), y el encargo avisaba de que cada llamada podía descargar el modelo cargado. Los
transcripts no entraron a ningún contexto: los procesaron los scripts de `insumos/scripts/`, que
devuelven solo agregados.

## Segunda pasada

Fecha: 2026-10-06. Revisión en solo lectura de `spec.md` versión 2 (56 REQ) contra la primera
revisión, `brief.md` (con las decisiones confirmadas sobre la v2), los insumos y la spec hermana
aprobada. Cada veredicto se comprobó en el texto de `spec.md`, no en la tabla de respuesta.

**Veredicto propuesto: todavía no aprobable, pero cerca.** No queda ningún bloqueante: los tres de
la primera pasada están resueltos y el contrato con el hermano coincide al pie de la letra. Quedan
seis hallazgos importantes nuevos, todos de arreglo corto en el texto, y uno de ellos (los checks del
PR del vigilante) le cambia los datos a una decisión que el usuario ya tomó. Tras esas ediciones
basta con comprobar los cambios, no hace falta otra pasada completa.

### Veredictos sobre la primera revisión

| # | Hallazgo (sev.) | Veredicto | Comprobación en `spec.md` |
|---|---|---|---|
| 1 | Interfaz con el hermano (BLOQ) | **Resuelto** | «Dependencia: el contrato…» (`:28-48`) copia campos, unidades y firma tal cual; `T` usa `chars_saved_text` y `chars_returned`, sin pasar por `net`; `returned` tiene densidad propia (REQ-031); septiembre en tokens lo recalcula REQ-036. Queda un efecto no declarado en las imágenes (hallazgo nuevo 1) |
| 2 | Puntos del statusline no independientes (BLOQ) | **Resuelto** | REQ-052 (1)-(2): un punto como mucho por (tipo, reset), del par de una misma sesión; REQ-053 descarta solapes; escenario de cinco filas = un punto |
| 3 | Vigilante y densidad sin cubrir (BLOQ) | **Resuelto** | REQ-020 a REQ-024; non-goal corregido a «en ejecución»; sin `limites_cambiaron`; deriva en REQ-056; `consultado` = último cambio y `doctor` sin aviso por edad (REQ-015); tabla de densidad por familia × columna × clase (REQ-030 a REQ-032); esfuerzo en REQ-009; `effort` opcional (REQ-052) |
| 4 | Sesgo de los rechazos (IMP) | **Resuelto** | REQ-055 usa solo puntos del statusline; REQ-051 deja los rechazos fuera de la mediana; REQ-058 los usa como comprobación; marca de REQ-052 (7) |
| 5 | Periodo del % (IMP) | **Resuelto** | REQ-060: ventana móvil de 5 h / 7 días que termina ahora, con rótulo |
| 6 | Dos desempates para `N` (IMP) | **Resuelto** | REQ-042: relleno > mediana del grupo (≥ 10) > declarado; sin variable para `N` |
| 7 | Algoritmo de `N` (IMP) | **Resuelto** | REQ-043 lo define entero, con test sintético (`<synthetic>`, `message.id` repetido, `compact_boundary`) |
| 8 | Usos de `CHARS_PER_TOKEN` (IMP) | **Resuelto** | Tabla de REQ-034; la volví a sacar con `grep` y las 13 líneas citadas existen y dicen lo que dice la tabla. Falta el caso imagen de la coletilla (menor nuevo 9) |
| 9 | Cota baja sin supuestos (IMP) | **Resuelto** | REQ-044: relecturas ~3 %–~30 % y rótulo «cota baja con estos supuestos» |
| 10 | Test del cotejo que no podía fallar (IMP) | **Resuelto** | Escenario «el cotejo caza…»: fixture literal, mutantes por el assert del veredicto, guarda sin mutar |
| 11 | Evidencia del cotejo no reproducible (IMP) | **Resuelto** | REQ-014 cita `cotejo.py`; reproducido hoy: 142 de 142 y todos los mutantes (ver abajo) |
| 12 | Puntos perdidos al borrar transcripts (IMP) | **Resuelto** | REQ-071 funde por clave y no borra; REQ-054 aplica los 60 días al leer; escenario del punto de 61 días |
| 22 | Decisiones abiertas (MENOR) | **Parcial** | El brief registra la confirmación del usuario de las decisiones 1, 2, 3 y 5, pero la spec las sigue listando en «Decisiones que necesitan al usuario» (`:699-716`), y REQ-021 sigue diciendo que «el plan elige» los checks (ver importante nuevo 4) |

Los menores 13 a 21 también están resueltos en el texto (REQ-014, REQ-042, REQ-052 (4)-(5),
REQ-051, REQ-045, REQ-012, REQ-033, REQ-010). Sobre el 21 hay un matiz en el menor nuevo 10.

### El contrato con el cambio hermano

Comparado literalmente con «Contrato con `coste-api-y-cuota`» y REQ-007/008 de
`panel-cuentas-y-estados-honestos/spec.md` (`:65-75`, `:418-469`): **sin diferencias**.

- Nombres de campo: los 13 coinciden en Python y JS (`chars_saved_text`/`charsSavedText`,
  `bytes_saved_image`/`bytesSavedImage`, `chars_saved_output`/`charsSavedOutput`,
  `chars_returned`/`charsReturned`, `saved`, `returned`, `net`, `failed`, `tool`, `model`, `source`,
  `unit`).
- Unidades: la imagen en **bytes** en las dos; el resto en caracteres; `saved`/`returned`/`net` en
  tokens de Claude.
- Firma: `tokens_claude(cantidad: int, *, tipo: str, evento: dict) -> int` y
  `tokensClaude(cantidad, tipo, e)`, idénticas, con los mismos cuatro valores de `tipo`.
- Lo que el hermano exige que se cite (campos, firma, y un caso de paridad cuyo resultado cambie
  entre la regla de hoy y la nueva) está en el texto: REQ-037 añade varios.

Dos observaciones que no son diferencias de contrato: la spec pasa a `evento` la fila **ya
fundida** (REQ-031), y el hermano dice «la fila cruda del log». La fundida es un superconjunto
que se hace en el mismo lector de Python, así que la firma no cambia, pero conviene una frase que lo
diga. Y el hermano remite a «su REQ-020» para la base de coste, que en la v2 es REQ-040: es una
referencia vieja **en la spec hermana**, que no se edita aquí.

### Decisiones del usuario

| Decisión | Reflejada | Dónde |
|---|---|---|
| Atribución por delegación, no un modelo global; respaldo visible | Sí | REQ-001 a REQ-008 |
| Calibrar con 3 puntos del statusline de ventanas distintas; rechazos como comprobación | Sí | REQ-052, REQ-053, REQ-055, REQ-058 |
| Caducidad de 60 días | Sí | REQ-054 (aplicada al leer) |
| Imágenes a 0 tokens y aparte | Sí, con un efecto no dicho | REQ-031, REQ-040 (importante nuevo 1) |
| Relleno lanzado por el usuario, aviso de `doctor` a los 20 días | En parte | REQ-070, REQ-075; el aviso no salta si el comando nunca se lanzó (importante nuevo 5) |
| Vigilante semanal | Sí | REQ-020 a REQ-024 |
| La deriva sustituye a la fecha a mano | Sí | REQ-056, REQ-023, REQ-057; no hay `limites_cambiaron` |
| «Contexto conservado» en tokens reales | Sí | REQ-031, REQ-036 |
| El vigilante lanza `ci.yml` por `workflow_dispatch` | No está en la spec, y no basta | REQ-021 lo deja al plan (importante nuevo 4) |

### Reproducibilidad (scripts ejecutados hoy en solo lectura; solo agregados)

| Cifra de la spec | Script y argumentos | Resultado | ¿Cuadra? |
|---|---|---|---|
| Cotejo 142 de 142; 138 sin búsqueda web (4 de Haiku) | `python -I -B cotejo.py` | 142 juzgadas, 142 dentro, 0 fuera, 0 sin precio; sin búsqueda web 138 (4 de `claude-haiku-4-5`) | Sí |
| Mutantes del cotejo (39, 37, 33, 75, 10, 7, 6; puntos ciegos con 0) | `cotejo.py` | 39 sin precio quitando `claude-opus-5`; 37, 33, 75, 10, 7 y 6 fuera; 0 con escritura a 1 h ×1,25, a 5 min ×0,8 y entrada ×1,25 | Sí |
| Atribución 96,5 % (166 + 55 de 229; 7 ambiguas, 1 sin cruce; 40 de `mcp`) | `python -I -B atribucion_n.py` (ventana por defecto, hasta 14:30Z) | 166, 55, 7, 1 de `claude-code`; 40 de `mcp` sin cruce; 96,5 % | Sí |
| Cobertura 149 / 3 / 91; `N` 127 (14) y 40 (135); todo `high` | `atribucion_n.py` | Igual | Sí |
| Cota baja $11,50 y estimación $92,69 ($62,20 + $30,49); $27,07; $38,51 y $19,84; $8,28 y $25,84; 1,84 / 0,91 MTok | `atribucion_n.py` | Igual en todas | Sí |
| Densidad 109 medida / 43 respaldo (2) | `atribucion_n.py` | 109 / 43 | Sí |
| Rechazos $125,71 (1 537) y $397,68 (5 648); statusline Δ% 47, $61,26, `contaminado` (70 peticiones, $8,17); semanal `delta_pequeno`; 82 de 144 sin `effort` | `python -I -B calibracion.py --hasta 2026-10-06T15:00:30+00:00` | Igual | Sí |
| Escenarios del criterio (7,8 %, 7,2 %, 51,2 %, deriva, sentidos opuestos, mediana 235) y $2,50 / $6,50 | `python -I -B criterio.py` | Igual | Sí |
| Tabla de densidad de REQ-030 | `python -I -B densidad.py` | Coincide celda a celda | Sí |
| «43 940 tokens con `low`, `high` y sin flag» (REQ-009) | `densidad.py` | 43 940 sin flag (tarea «ok»); 43 938 con `low` y con `high` (tarea «resumen») | Conclusión correcta, frase inexacta (menor nuevo 8) |

### Fallos nuevos

#### Importantes

**1. Con la imagen a 0, cada descripción de imagen resta del «Contexto conservado».**
- Evidencia: la regla del hermano resta `returned := tokens_claude(chars_returned, tipo="returned")`
  también en las imágenes (su escenario: `chars_returned = 800`). Con REQ-031, `tipo="image"` da 0 y
  `tipo="returned"` da 800 × 100 // 223 = 358, así que el `net` de cada `local_describe_image` sale
  en **−358**. En «Ahorro por herramienta» (REQ-004 del hermano, que ya enseña barras negativas)
  la tool de imágenes aparecería como una pérdida. La decisión 2 solo dice «la cifra baja un poco».
- Arreglo: decidir y escribirlo. La función recibe `evento`, así que puede devolver 0 para
  `tipo="returned"` cuando `unit` no es `chars` (las dos partes de la imagen quedan fuera y se
  enseñan aparte), sin tocar el contrato. O bien declarar el neto negativo de las imágenes y
  confirmarlo con el usuario. Añadir el caso a REQ-037.

**2. El JS no tiene con qué elegir la familia ni la clase.**
- Evidencia: REQ-033 dice que el JS recibe la tabla de **densidad** de `/api/stats` y que «no hay una
  segunda copia de los valores». Pero `tokensClaude` necesita además la familia de cada
  `caller_model` (sale de la tabla de **precios**), el respaldo efectivo (REQ-008, que puede venir
  de una variable de entorno) y el mapa extensión → clase de REQ-032. Nada de eso llega al JS, y
  REQ-037 exige paridad «uno por familia» y «un modelo fuera de la tabla».
- Arreglo: que `/api/events` entregue en cada fila la `familia`, la clase y el origen de celda ya
  resueltos en Python (y el JS solo divide), o que `/api/stats` entregue también el mapa modelo →
  familia, el respaldo efectivo y el mapa de extensiones. Un test de que el JS no tiene copias
  propias.

**3. La clave del relleno, `(ts, tool)`, no es única.**
- Evidencia: `_log_event` escribe `ts` con resolución de segundos (`server.py:488`,
  `isoformat(timespec="seconds")`). En los logs de esta PC hay **3 claves repetidas (6 líneas) de
  406**, y el caso típico es justo el del escenario «dos subagentes a la vez con la misma tool».
  REQ-005 promete «una entrada por línea del log»: con clave repetida, dos delegaciones comparten
  atribución, `N` y caducidades.
- Arreglo: clave `(ts, tool, ordinal)`, con el ordinal de la línea entre las de la misma
  `(ts, tool)` en el orden del fichero, o añadir `chars_in`. Un test con dos líneas del mismo
  segundo y la misma tool que dan dos entradas distintas.

**4. Los checks del PR del vigilante: la decisión confirmada no está en la spec y, tal cual, no
basta.**
- Evidencia: el usuario eligió «el vigilante lanza `ci.yml` por `workflow_dispatch`» (`brief.md:88`),
  pero REQ-021 sigue diciendo que «el plan elige» y la decisión 5 sigue abierta (`spec.md:713-716`).
  Además, el ruleset `protect-main` (leído hoy con `gh api …/rulesets/19859628`) exige
  `ci-gate`, `lint`, `test (ubuntu-latest)`, `test (macos-latest)`, `secrets` **y
  `Analyze (python)`**, más la regla `code_scanning` de CodeQL. `Analyze (python)` sale de
  `codeql.yml`, que solo se dispara con `push`, `pull_request` y `schedule`. Lanzar solo `ci.yml`
  deja el PR `BLOCKED`. Y para lanzar un workflow, el job del vigilante necesita `actions: write`,
  que REQ-020 no le da (solo `contents: write` y `pull-requests: write`).
- Arreglo: un REQ que diga que el vigilante lanza **`ci.yml` y `codeql.yml`** por
  `workflow_dispatch` sobre su rama, que a los dos se les añade ese disparador, y que el job tiene
  `actions: write`. Falta comprobar [I] que el análisis de CodeQL lanzado así cumple la regla
  `code_scanning` del PR: si no, hay que volver a llevarle la decisión al usuario. Actualizar
  «Decisiones ya tomadas» con las cuatro confirmadas.

**5. El aviso de `doctor` a los 20 días no salta si el comando nunca se lanzó.**
- Evidencia: REQ-015 da `unknown` si no hay cotejo («comando nunca lanzado»), y REQ-075 da `warn`
  si hay `pendientes` y «el último relleno tiene más de 20 días». Si no hubo relleno nunca, las dos
  reglas chocan y no se dice cuál gana; el escenario «otra máquina sin datos» elige `unknown`. Así,
  quien no lanza nunca el comando pierde el histórico a los 30 días sin aviso, que es justo lo que
  la decisión del usuario quería evitar.
- Arreglo: que el aviso mire la delegación `pendiente` más antigua, no la fecha del último
  relleno: `warn` si hay alguna con más de 20 días y existe `~/.claude/projects`, se haya lanzado el
  comando o no. Escribir la precedencia frente al `unknown` de REQ-015 y ajustar el escenario.

**6. El test del vigilante se rompe con el primer PR del propio vigilante.**
- Evidencia: REQ-024 exige que «la de precios intacta da exactamente la tabla del paquete». Cuando
  el vigilante abre su PR con la tabla nueva, la copia guardada de la página sigue siendo la vieja,
  y ese test falla en el propio PR. Lo mismo con el texto de límites si el test usa la copia que el
  PR actualiza.
- Arreglo: o el PR del vigilante actualiza también la copia guardada, o el test compara la página
  guardada con una tabla esperada congelada en el propio test, no con la del paquete. Decirlo en
  REQ-024.

#### Menores

**7. Escenario atado a los datos de hoy.** «Hoy, la cuota está sin calibrar» fija «1 descartado:
contaminado», y el registro del statusline crece en vivo: cuando se implemente, ya no se repetirá.
Es el mismo defecto del menor 13 de la primera pasada. Arreglo: dejar la regla (sin % y con lo que
falta) y anotar los conteos en `verification.md`.

**8. REQ-009 cita mal la medida del esfuerzo.** `densidad.py` da 43 940 sin flag (tarea «ok») y
43 938 con `low` y con `high` (tarea «resumen»). La conclusión es correcta (dentro de cada tarea, el
esfuerzo no cambia la entrada), pero la frase dice que las tres dieron 43 940.

**9. La coletilla de imágenes queda sin definir.** `_savings_feedback` también lo usa
`local_describe_image` (`feedback_label="bytes imagen"`, `server.py:2856`), y hoy presenta el
`tokens_in` local como tokens que no entraron. REQ-034 y REQ-035 le mandan `tipo="text"`, que sobre
bytes no tiene sentido. Arreglo: para imágenes, la coletilla dice solo los bytes, sin tokens de Claude.

**10. El vigilante deduce ids del nombre comercial.** REQ-021 traduce «Claude ‹Familia› ‹X.Y›» a un
id, y el arreglo del menor 21 pedía no hacerlo. El fallo es seguro (un id mal deducido da
«sin precio» y el cotejo lo caza), pero conviene decirlo o leer la página de ids.

**11. REQ verificables a medias.** REQ-048 no tiene tolerancia: propuesta, el cálculo del panel
sobre la misma ventana tiene que dar **exactamente** lo de `atribucion_n.py` corrido el mismo día.
REQ-003 (50 ms) y la parte «solo lectura en `~/.claude`» de REQ-074 no tienen test en la
trazabilidad.

**12. Detalles sueltos.**
- REQ-008: si la variable trae solo `modelo`, no se dice qué hilo se supone.
- REQ-042 (2) y REQ-070: no se dice que los agregados de `N` excluyan bancos y clientes excluidos
  (el script sí lo hace).
- REQ-007: los 91 `excluido (pruebas)` incluyen transcripts de banco, que REQ-007 no rotula como
  «pruebas».
- REQ-060: la estimación B cuenta relecturas futuras que pueden caer fuera de la ventana; el rótulo
  debería decirlo.
- La familia `anterior` se midió solo con Haiku 4.5 y se aplica también a Opus 4.5/4.6 y Sonnet
  4.5/4.6; y `admite_esfuerzo: true` de los modelos heredados es un supuesto que ninguna tarea
  comprueba todavía.
- La definición de `T` escribe `tokens_claude(…, tipo=…)` sin `evento`: es una abreviatura, pero
  mejor con la firma completa.

### Comprobado y correcto

- Todos los números que la spec atribuye a un script salen igual al ejecutarlo hoy (tabla de
  reproducibilidad), salvo la frase de REQ-009.
- La aritmética de REQ-033 es correcta: el resto de `cantidad × 100 / c100` es un múltiplo de
  1/`c100` ≥ 1/1000, y el error de coma flotante para cantidades de hasta 10⁹ es del orden de 10⁻⁸.
- Las líneas citadas en REQ-034 y REQ-045 (`config.py:351`, `server.py:367`, `:614`, `:616`, `:621`,
  `:1185-1195`, `:1317`, `:1617`, `:1950`, `:2394`, `metrics.py:55`, `:414`, `:805`, `:1199`, `:1215`,
  `:1222`, `:1342`) existen y dicen lo que dice la spec.
- `precios.json`: el escenario de $2,50 / $6,50 usa bien la escritura a 5 min ($5) y la lectura
  ($0,20) de Opus 5.5.
- No encontré controles que no puedan fallar, salvo el del importante 6 (que falla siempre en el
  sitio equivocado), ni artefactos sin tarea que los produzca, salvo lo dicho en el menor 12.

### Llamadas a `local-delegate`

0. Motivo: la revisión exige texto literal (spec, review, contrato del hermano) para citar líneas y
comparar nombres de campo, y lo leí por franjas. Las cifras las sacaron los scripts en solo lectura,
volcados a ficheros del scratchpad: salidas cortas de agregados que no compensaba resumir con un
modelo local, porque cada llamada lo carga.

## Respuesta a la segunda pasada

Fecha: 2026-10-06. `spec.md` pasa a la versión 2.1 (58 REQ: entran REQ-025 y REQ-038). Las
decisiones de la sesión principal están en la sección nueva «Decisiones confirmadas» de la spec.

| # | Hallazgo (sev.) | Resolución | Dónde quedó |
|---|---|---|---|
| 1 | Con la imagen a 0, cada descripción de imagen restaba del neto (IMP) | Decisión: `local_describe_image` sale **entera** del neto (`saved = returned = net = 0`); los campos del contrato no cambian. Bloque aparte «Imágenes» con número, bytes y caracteres devueltos. Caso nuevo en la paridad y escenario «una imagen no resta del neto» | REQ-038 (nuevo), REQ-031, REQ-033, REQ-037, REQ-040; escenario |
| 2 | El JS no tenía con qué elegir familia ni clase (IMP) | Un solo lugar de verdad: `resolver_densidad` en Python, aplicada en la fusión; cada fila de `/api/events` lleva `densidad` por `tipo` (`[c100, origen]`, `null` en imágenes). `tokens_claude` y `tokensClaude` solo dividen. Control: se cambia a mano el `c100` de una fila y las dos copias lo siguen; si el JS resolviera solo, el test falla | REQ-033, REQ-006, REQ-037; escenario «el JS sigue a Python» |
| 3 | La clave `(ts, tool)` del relleno no era única (IMP) | Clave = `tool_use_id` si existe; si no, `(ts, tool, ordinal)` en el orden del fichero. Medido con el script nuevo `insumos/scripts/clave_relleno.py` sobre 409 líneas: `(ts, tool)` repite 3 claves (6 líneas), con `chars_in`/`chars_out` repite 1, con ordinal **0**. Test: mismo segundo y tool → dos entradas, estables al añadir una tercera | REQ-005; escenario «dos líneas del mismo segundo…»; Controles |
| 4 | Los checks del PR del vigilante: la decisión no estaba y `ci.yml` solo no bastaba (IMP) | Leí el ruleset con `gh api repos/ZahiriNatZuke/local-delegate/rulesets` (y `/19859628`): `protect-main` exige `ci-gate`, `lint`, `test (ubuntu-latest)`, `test (macos-latest)`, `secrets` (todos de `ci.yml`; `secrets` es gitleaks, no una app), `Analyze (python)` (`codeql.yml`), la regla `code_scanning` de CodeQL y rama al día. El vigilante lanza `ci.yml` **y** `codeql.yml` por `workflow_dispatch` (se les añade el disparador; ninguno depende del evento), con `actions: write`, y actualiza la rama si `main` avanzó. Socket y GitGuardian no son requeridos. Queda [I] si el CodeQL lanzado así cumple `code_scanning`: si no, comentario en el PR, cerrar y reabrir a mano, y vuelve al usuario | REQ-020, REQ-021, REQ-025 (nuevo); «Decisiones que necesitan al usuario» |
| 5 | El aviso de `doctor` no saltaba si el comando no se lanzó nunca (IMP) | El aviso mira la delegación `pendiente` más antigua (> 20 días) si existe `~/.claude/projects`, se haya lanzado el comando o no, y gana a las demás reglas del check (orden escrito). Escenario nuevo con el comando nunca lanzado; el de «otra máquina sin datos» sigue en `unknown` porque no hay `~/.claude/projects` | REQ-015, REQ-075; dos escenarios |
| 6 | El test del vigilante se rompía en su propio PR (IMP) | El test compara las páginas guardadas en `tests/` con tablas y textos esperados **congelados en el test**, nunca con la tabla del paquete ni con el texto de límites del repo, que son lo que cambia el PR | REQ-024; escenario del vigilante; Controles |
| 7 | Escenario atado a los datos de hoy (MENOR) | Escrito como regla («con menos de 3 puntos, sin calibrar, sin %, y dice qué falta»); los conteos del día van a `verification.md` | Escenario «con menos de tres puntos…» |
| 8 | REQ-009 citaba mal la medida (MENOR) | Ahora dice: tarea «ok», 43 940 sin flag, con `low` y con `high`; tarea «resumen», 43 938 en las seis llamadas. La frase vieja era cierta para la tarea «ok», pero se callaba la otra. `densidad.py` imprime ahora el desglose por tarea y esfuerzo | REQ-009; `insumos/scripts/densidad.py` |
| 9 | La coletilla de imágenes sin definir (MENOR) | Para `local_describe_image`, solo los bytes, sin tokens | REQ-034 (fila de `_savings_feedback`, con `:2856`), REQ-035 |
| 10 | El vigilante deduce ids del nombre (MENOR) | Se dice que es inevitable (la página de precios no trae ids), que sigue la forma de «Model IDs and versioning», que un id mal deducido falla de forma segura (sale «sin precio» y lo caza el cotejo) y que el PR lista los ids nuevos para revisarlos | REQ-021 |
| 11 | REQ verificables a medias (MENOR) | REQ-048: el panel tiene que dar **exactamente** lo de `atribucion_n.py` el mismo día. REQ-003: test del presupuesto con espía de lectura (≤ 256 KB) y reloj inyectado (50 ms). REQ-074: lista de ficheros con hash idéntica antes y después | REQ-048, REQ-074; Traceability |
| 12 | Detalles sueltos (MENOR) | Respaldo con solo `modelo` → hilo `subagent`; agregados de `N` sin `excluidos`; «pruebas (scripts y bancos)»; el rótulo del % avisa de relecturas fuera de la ventana; la tabla de densidad guarda con qué modelos se midió cada familia y marca `densidad de la familia` a los demás; tarea del plan para comprobar `admite_esfuerzo` de los heredados; `T` con la firma completa; frase sobre `evento` fundido en el contrato | REQ-008, REQ-042, REQ-070, REQ-007, REQ-060, REQ-030, REQ-044, Definiciones, «Dependencia…», Traceability |
| 22 | Decisiones abiertas (resto de la primera pasada) | Sección «Decisiones confirmadas» con fecha y su REQ; «Decisiones que necesitan al usuario» queda sin ninguna abierta, salvo la condicional de REQ-025 | «Decisiones confirmadas» |

Scripts tocados en esta ronda: `clave_relleno.py` (nuevo) y `densidad.py` (desglose del esfuerzo).
Los demás no cambian, así que sus cifras siguen siendo las de la tabla de reproducibilidad de la
segunda pasada.

**Llamadas a `local-delegate` en esta ronda: 0.** Las ediciones exigían el texto literal de la
spec y de la revisión, y el ruleset se leyó con `gh api` (salida corta). Los logs de uso solo los
leyó `clave_relleno.py`, que devuelve conteos.

## Revisión del plan

Fecha: 2026-10-06. Revisión adversaria, en solo lectura, de `plan.md` (commit `c8287fa`) contra
`spec.md` v2.1, `brief.md`, `research.md`, el código de la rama `feat/panel-honesto` (con
`d20d4f3`, `2b03251` y `b73734d`) y, para lo que el panel aún no ha hecho, su `spec.md` y su
`plan.md`. Se ejecutaron solo lecturas: `git`, `grep`, `git ls-files --eol`, conteos sobre los logs
de uso (sin abrir contenido) y la fecha de modificación de los transcripts.

**Veredicto: el gate del plan NO se aprueba todavía.** Un bloqueante y diez importantes. Ninguno
obliga a rehacer el diseño: son decisiones que faltan, controles que fallarían por una razón
distinta de la que dicen y una pareja en paralelo que no es independiente del todo. Con los arreglos
de abajo, el plan es aprobable en una pasada corta.

### Bloqueantes

**1. El horizonte de 30 días ya no es el de esta PC, y está cosido en la spec, en el plan y en los
tests.** El usuario subió `cleanupPeriodDays` a 90 el 2026-10-06 (`~/.claude/settings.json:153`),
con efecto desde las sesiones nuevas. Evidencia: el transcript más antiguo de `~/.claude/projects`
es del 2026-09-03 (33 días) y sigue ahí; septiembre desde el día 3 queda rellenable hasta primeros
de diciembre. Lo que cambia:
- **Riesgo 4 del plan** («cada día que el panel tarde… pierde relleno»): ya no es cierto en esta
  PC. Lo perdido es lo anterior al 2026-09-03 (julio, agosto y el 1–2 de septiembre), y eso ya no
  depende de la espera. El riesgo pasa a ser: «mezclar antes de diciembre» y «otra máquina (la Mac)
  sigue con 30 días».
- **T0.5** («cada día de espera borra un día»): tiene que medir otra cosa: que el ajuste está en
  vigor (un transcript de más de 30 días sigue existiendo) y anotar la fecha del más antiguo.
- **Lo que de verdad pierde datos ahora es la propia spec**: REQ-004 rellena solo «las líneas de
  los últimos 30 días»; REQ-007 llama `pendiente` a lo que tiene menos de 30 días; REQ-075 avisa a
  los 20 días «antes de que Claude Code borre sus transcripts». Con 90 días: (a) el comando dejará
  sin rellenar líneas de 30 a 90 días cuyo transcript existe, así que **T8.4 (septiembre en tokens,
  «con relleno donde aún haya transcripts») saldrá con la primera mitad de septiembre en
  `supuesto` por la ventana de REQ-004, no por borrado**; (b) `doctor` dará un `warn` de urgencia
  falsa a los 20 días; (c) `test_tramos` (29/31 días) y el mensaje de T7 fijan el 30.
- **Arreglo**: decisión del usuario antes de T4, T5 y T7 (el brief recoge «doctor avisa a los 20
  días» como decisión suya). Propuesta: un **horizonte** que lee el comando (que ya lee
  `~/.claude`) de `cleanupPeriodDays` (30 si falta), guardado en `coste-agregados.json`; REQ-004
  usa ese horizonte, `pendiente` es «menos que el horizonte», y el aviso salta a horizonte − 10
  días. El panel y `doctor` lo leen del JSON (nunca de `~/.claude`, REQ-073) y, sin JSON, usan 30.
  Es una enmienda pequeña de la spec (v2.2) y cambia los tests de `test_tramos`, del cruce y del
  `doctor`. La alternativa mínima, quedarse con 30 a sabiendas, también vale si el usuario la
  elige, pero entonces el plan tiene que decir que T8.4 dará `supuesto` por diseño y no por borrado.

### Importantes

**2. El plan no sabe que existe `daemon-reparte-el-backend`, que toca los mismos ficheros.** Su
spec (aprobada) también va «después del panel» y añade **dos checks** a `doctor` (su REQ-036),
campos nuevos en `_log_event`, variables en `config.py`, un subcomando en `cli.py`,
`test_aislamiento_entorno.py`, el JS de `metrics.py` y la wiki (`daemon-reparte-el-backend/
spec.md`, «Ficheros compartidos con `panel-cuentas-y-estados-honestos`»). Ni su spec nombra este
cambio ni este plan nombra aquel. Este plan escribe a fuego «veintiuno → veintidós»
(`_NUMERO[22]`, `_NUMERO_DE_CHECKS[22]`, «las veintidós piezas»): si aquel se mezcla antes, son 23
→ 24. **Arreglo**: fijar el orden entre los dos cambios (decisión de la sesión principal) y que T0
lea `len(checks.CHECKS)` y `len(install._HOOK_EVENTS)` reales y reescriba las cifras de T7 y T2;
anotar en la tabla de propiedad qué zonas de `server.py`, `config.py`, `cli.py` y del JS reclama
cada cambio.

**3. La nota del hook se escribe leyendo y reescribiendo el fichero entero, y el caso que importa
es justo el concurrente.** El plan copia `anotar_bloqueo` («las 200 últimas, como
`anotar_bloqueo`»), que hace `read_text` + `write_text` sin cerrojo
(`resources/hooks/hook_common.py:352-369`). Para un bloqueo (raro) da igual; para **cada** llamada
`local_*`, con dos subagentes a la vez (el escenario de REQ-005), dos hooks pierden la nota del
otro, y el daemon puede leer el fichero truncado a medias (`write_text` trunca y luego escribe).
**Arreglo**: el hook añade una línea con `open("a")` en una sola escritura, y el recorte a 200 se
hace aparte con fichero temporal + `os.replace`; el lector tolera una última línea rota. Test nuevo
en T2: N procesos del hook lanzados a la vez dejan N notas legibles; mutante: el
`read_text`+`write_text` de hoy → falla `assert len(notas) == N`.

**4. T4 y T5 no son independientes del todo: uno prueba lo que el otro está editando.** (a) El
inventario de T4 (paso 3) corre la suite entera salvo los tres tests nuevos de T5, y eso incluye
`test_smoke.py`, `test_clients.py`, `test_daemon.py`, `test_install_*` y `test_llamaswap_config.py`,
que importan `cli.py`, el fichero que T5 está editando en ese momento; también
`test_aislamiento_entorno.py::test_config_solo_lee_el_entorno_por_la_puerta_registrada`, que
escanea los módulos nuevos a medio escribir de T5. Un rojo de T5 entraría en el inventario de T4
como si fuera suyo. (b) La verificación de T5 corre `test_aislamiento_entorno.py`, que lee
`config.py`, el fichero que T4 está editando. **Arreglo**: el inventario de T4 se hace con
`--deselect`/`--ignore` de los tests que importan `cli` y sin `test_aislamiento_entorno.py` (lo
corre al final de su tarea, o lo corre I3), y T5 quita `test_aislamiento_entorno.py` de su
verificación (lo cubre I3).

**5. T5 necesita la lista de exclusión que escribe T4.** REQ-070 y REQ-042 piden los agregados de
`N` «sin delegaciones `excluidas`» (clientes `codex-mcp-client` y `mcp`, y `banco`). Los agregados
los escribe `recalcular.py` (T5), pero la regla de exclusión vive en `coste.tramo` (T4), que T5 no
puede importar porque está en marcha. O T5 la duplica (dos fuentes para el mismo dato, el defecto
recurrente del repo) o importa un módulo a medio hacer. **Arreglo**: la lista de clientes excluidos
y la función `excluida(fila, relleno)` van a `atribucion.py` (T2, ya cerrado); `coste.tramo` y
`recalcular` la importan. Un test en T2 la fija.

**6. Cuatro controles fallarían por una excepción, no por el assert que nombran.**
- `test_recalcular.py::test_el_cli_lo_lanza` llama a `cli.main([...])`, que **no existe**: el
  punto de entrada es `cli.run(argv)` (`cli.py:918`; `entrypoint.py:68`). Hoy daría
  `AttributeError`, no `SystemExit(2)`. Arreglo: `cli.run([...])`.
- `test_panel_coste.py::test_home_vacio` con el JSON corrupto: el mutante «se lee sin `try`» no da
  un 500, porque `TestClient` propaga la excepción del servidor por defecto
  (`raise_server_exceptions=True`; así se usa en `tests/test_clients.py:258`). El test fallaría por
  `JSONDecodeError`, que es un `ValueError`. Arreglo: `TestClient(metrics.app,
  raise_server_exceptions=False)`.
- `test_atribucion.py::test_una_resolucion_rota_no_se_lleva_la_linea`: el `try` general de
  `_log_event` solo captura `OSError` (`server.py`, final de `_log_event`). Si el doble lanza otra
  cosa, en el mutante la excepción **sale de `_log_event`** y rompería la tool (lo que prohíbe
  REQ-001), y el test falla por esa excepción. Arreglo: el doble lanza `RuntimeError`, el test
  envuelve la llamada y comprueba primero `assert not escapo` y después `assert len(lineas) == 1`;
  el plan anota que el `try` propio debe capturar `Exception`.
- `test_cargar_las_tablas_no_abre_sockets` y `test_api_stats_no_abre_sockets` sustituyen solo
  `socket.socket.connect`. El mutante `urlopen(tabla["fuente"])` resuelve el nombre **antes** de
  conectar; sin red (o con DNS caído) `getaddrinfo` lanza y `connect` nunca se llama, así que
  `intentos == []` se cumple y **el mutante sobrevive**. Arreglo: registrar también
  `socket.getaddrinfo` y `socket.create_connection`.

**7. La integración por ola es ejecutable, pero la regla de quién arregla un rojo no.** (a) «Un
rojo lo arregla el agente de integración aunque esté fuera de las listas»: un rojo semántico (una
cifra de ÷ 4, un control) lo arreglaría quien no tiene el contexto, y sin volver a comprobar el
control de la tarea dueña; contradice «cada rojo tiene dueño». (b) La regla común «`git diff
--stat` sin ficheros ajenos» no se puede cumplir en una ola en paralelo: el árbol tiene los
ficheros de la pareja. (c) No dice quién hace los commits (firmados) ni quién actualiza
`state.json`. **Arreglo**: el integrador arregla solo lo mecánico (`ruff`, imports, EOL); un rojo
de comportamiento vuelve al agente dueño (retomado con su contexto) y su `evidencias/T<n>.md` se
completa con el control re-ejecutado; `git diff --stat -- <ficheros propios>`; un commit por tarea
con rutas explícitas, que hace el integrador al cerrar la ola; `state.json`, la sesión principal.

**8. El criterio de parada del `_meta` llega después de casi todo el trabajo, y el del directorio
temporal ya tiene respuesta.** El `_meta` del daemon real solo se comprueba en T10.3, con T4–T9
construidos sobre él. Por otro lado, el riesgo del temporal compartido está casi retirado: el log
real tiene **31 líneas con `bloqueo_id`** (27 en `usage-202609.jsonl`, 4 en `usage-202610.jsonl`,
la última del 2026-10-06 con `client: claude-code`), y `bloqueo_id` solo aparece si el daemon leyó
la nota que dejó un hook en `tempfile.gettempdir()` (`server._bloqueo_reciente`). **Arreglo**:
(a) T0 cuenta esas líneas y lo anota como evidencia del riesgo 3; (b) en I2, una prueba de humo
con el servidor del repo en HTTP en otro puerto y una sola llamada real desde Claude Code con
`--mcp-config`, que confirme que llega `claudecode/toolUseId`; si es con `claude -p`, se anota que
contamina esa ventana de 5 h (REQ-052, paso 6). T10.3 se queda como verificación instalada.

**9. `tokens_claude` en Python resuelve la densidad por su cuenta y el JS no.** El plan (Diseño y
T4.4) hace que la Python, «sin clave `densidad`», llame a `resolver_densidad`, mientras la JS da 0.
REQ-033 dice que las dos «hacen lo mismo y nada más» y que son **los mensajes en vuelo** quienes
llaman a `resolver_densidad` antes de convertir. Además, la asimetría tapa una fusión olvidada en
cualquier camino de Python (daría una cifra con el respaldo en vez de un 0 visible). **Arreglo**:
`tokens_claude` da 0 sin `densidad`, como el JS; los tres mensajes de REQ-035 llaman a
`resolver_densidad` (vía la fila en curso fundida) antes de convertir.

**10. Dos requisitos aprobados quedan sin test.** REQ-054 tiene dos mitades y el plan solo prueba
la vigencia: el **saneado** (filas con % fuera de [0, 100] o no numérico, descartadas y contadas)
no tiene test, y la tabla de trazabilidad no lo nombra. REQ-061 («una línea corrupta se salta y
cuenta como descarte») solo se prueba en el panel con el JSON corrupto, no en el comando con el
registro del statusline ni con un transcript roto. **Arreglo**: en T5,
`test_cuota.py::test_sanear_y_lineas_corruptas` (fila con 120 %, fila con `"abc"`, línea JSON
rota en el registro y en un transcript) con un mutante por rama; mutante «sin saneado» → falla
`assert descartes["five_hour"].get("fuera_de_rango") == 1`.

**11. La búsqueda de privacidad de T8.2 no ve la ruta más probable.** Busca `\Users\`, `/Users/` y
`C:`, pero el repo y los proyectos están en `D:\Projects`, y las carpetas de `~/.claude/projects`
llevan la ruta codificada (`D--Projects-…`). **Arreglo**: patrones `[A-Za-z]:[\\/]`, `--Projects`
(o, mejor, el nombre de cada carpeta de `~/.claude/projects` leído en el momento), el nombre de
usuario del sistema y los UUID; el resultado se anota solo como conteo.

### Menores

12. **La paridad en el corte (c) no falla donde dice el plan.** Con Python ya cambiado y el JS con
÷ 4, el primer fallo es el **caso 0 de los que ya existen** (`_ev(tokens_in=1100, tokens_out=90)`,
por `path` sin extensión → clase `otro`), en el campo `returned`, el primero de `_CAMPOS_PARIDAD`
(Python 179, JS 100), no «el primer caso nuevo, 4000 caracteres, 2000 contra 1000». El assert es
la misma línea, pero la evidencia que pide el plan no coincidiría. Y hay que decir explícitamente
que **los 22 casos que ya existen** también pasan por `coste.fundir`: si no, en el estado final
Python resuelve y el JS da 0, y la paridad se rompe.
13. **El inventario de T4 corre antes de cambiar el JS** (paso 3 contra paso 4), así que no ve los
rojos de `test_dashboard_js.py` que el propio plan espera. Repetirlo tras el paso 4.
14. **El inventario de los ÷ 4 está completo** según el `grep` de esta revisión (incluidos los
tests que añadieron T1 y T3 del panel: `test_delegacion_conexion.py`, `test_sondeo_backend.py` y
`test_post_chat_caminos.py` no fijan tokens de Claude). Para que el agente no dependa solo de la
ejecución: `test_metrics.py` (29 coincidencias, entre ellas `test_accounting_una_llamada_sin_trocear`
y las de `local_status` en `:1018` y `:1040`), `test_dashboard_js.py` (8),
`test_boilerplate_salida.py:295` (`8000 // config.CHARS_PER_TOKEN + 950`), `test_vision.py:146`,
`test_core.py:493-494` (`"500 tokens"` es el `tokens_in` local de la coletilla, que REQ-035 quita)
y `test_resumen_estructurado.py:332` (la cola, que se conserva).
15. **Números de línea movidos** en el inventario de T2: `conftest.py:116` (no `:96`) y
`test_checks.py:574` (no `:572`), por `b73734d`. T2 vuelve a correr el `rg`, así que no bloquea.
16. **El test del shebang** (`test_wiki.py::test_un_script_con_shebang_esta_marcado_ejecutable_en_git`)
mira `scripts/*.py` y `resources/hooks/*.py`, y solo ve ficheros ya añadidos a git: T2 y T3 lo
corren después de `git add` (si el script lleva `#!`, `git update-index --chmod=+x`).
17. **Los tests del hook escribirían en el temporal real**, el que lee el daemon en vivo: el
subproceso del hook lleva `TEMP`/`TMP`/`TMPDIR` apuntando a `tmp_path`.
18. **La memoria de `llamada_actual()`** tiene que vivir por petición (un `ContextVar` que pone el
middleware), no en un diccionario del módulo, que en el daemon crecería sin límite.
19. **Seguridad del `transcript_path`**: lo lee el daemon de un fichero del temporal que cualquier
proceso local puede escribir. Validar que está bajo `~/.claude/projects` y acaba en `.jsonl`
antes de abrirlo (para `personal-security-check` en T10). Y la nota guarda una ruta con el id de
sesión, contra la regla de `hook_common` («nunca escribe rutas»): lo pide REQ-002, pero el plan
debería decirlo y mantener el tope de 200 líneas.
20. **Cobertura parcial de REQ menores**: el Δ$ de un punto de rechazo (REQ-051) no se comprueba
(T8.6 compara solo descartes; añadir el Δ$ contra `calibracion.py`); el cuerpo del PR de límites
con el comando de reinicio (REQ-023), «actualiza el PR si ya está abierto» y «lista los ids
nuevos» (REQ-021) no tienen assert; `caller_agent_type` solo en subagentes (REQ-003) tampoco.
21. **Documentación**: `docs/recipes/claude-code-hooks.md` lista los hooks y no está en T9.
22. **T10.3** necesita una sesión interactiva nueva: o la abre el usuario (decirlo) o se usa
`claude -p` desde el principio. **T10.7**: tras volver a la 0.32.0, correr `doctor` y anotar qué
dice del hook que queda instalado.
23. `--group ui` es una opción de `uv run`, no de `pytest`: escribir el comando entero.

### Comprobado y correcto

- **Trazabilidad**: los 58 REQ de la spec están en la tabla del plan, y ninguna tarea hace algo
  que no pida un REQ (las decisiones propias, `--claude-dir` y el techo de 30 s, son de diseño).
- **T2 ∥ T3 y T6 ∥ T7 no comparten ficheros ni se importan**: ningún test de `test_metrics.py`,
  `test_dashboard_*` o `test_captura.py` importa `checks`, y ni `test_doctor.py`, `test_checks.py`
  ni `test_wiki.py` tocan `metrics` o `valoracion`; `checks.py` no importa `metrics`. Ningún test
  de T2 lee `.github/`.
- **Finales de línea**: los 28 ficheros existentes de la tabla de propiedad tienen el EOL que dice
  el plan (`git ls-files --eol`).
- **Guardianes de tamaño**: `_NUMERO` (`test_checks.py:1093`) y `_NUMERO_DE_CHECKS`
  (`test_wiki.py:35`) llegan hoy a 21; sin la entrada nueva fallarían por `KeyError`, y el plan la
  añade primero. Las afirmaciones son cinco (cuatro «veintiún» y «ver los otros veinte»), que
  cuadran con «cuatro frases» más «ver los otros veintiún».
- **Controles que sí mutan**: `test_busqueda_exacta_en_los_pares` (en `precios.json`,
  `claude-opus-5-5` va antes que `claude-opus-5` y `claude-fable-5-1` antes que `claude-fable-5`);
  `test_un_millon_de_caracteres` (5 contra 8 USD/MTok: $2,50 contra $4,00); `test_el_mismo_py…`
  (el valor coincide en 3,12 y el control es el origen, como dice el plan);
  `test_una_imagen_no_resta_del_neto` (hoy `saved` = 1200, el `tokens_in` reportado); los dos
  guardianes de tamaño con la entrada 22 añadida.
- **Hilos y `ContextVar`**: las 33 líneas troceadas de septiembre y octubre llevan `client`, así
  que el `ContextVar` del middleware llega al `_log_event` también en las operaciones troceadas;
  el `tool_use_id` irá por el mismo camino.
- **GitHub**: `ci.yml` y `codeql.yml` no tienen condiciones que dependan del evento; la
  concurrencia de `ci.yml` (`ci-${{ github.ref }}`) separa el run del `workflow_dispatch` del de
  `pull_request`. T11 va antes de la release y su fallo no la bloquea, como dice la spec.
- **Release**: T9 toca CHANGELOG, README y wiki, y quita la nota «No publicar versión hasta mezclar
  `coste-api-y-cuota`» que deja el T6 del panel (`panel-cuentas-y-estados-honestos/plan.md:443`).
- **Privacidad de los tests**: todos con transcripts, registros y logs sintéticos en `tmp_path`;
  los únicos datos reales que entran al repo son los números del cotejo literal, como pide la spec.

### Llamadas a `local-delegate`

**0.** La revisión necesitaba el texto literal del plan y de la spec para citar líneas y comprobar
cada control, así que se leyeron por franjas; el código se miró con `grep` y `sed` acotados, y los
logs de uso solo con conteos (`grep -c`, un script que cuenta). Un resumen del modelo local no
habría servido para comprobar que un mutante muta.

## Respuesta a la revisión del plan

Fecha: 2026-10-06. `plan.md` pasa a la versión 2, con las decisiones de la sesión principal. Los
controles corregidos se **ejecutaron** contra `feat/panel-honesto` con
`scratchpad/controles/comprobar.py` (desechable, sin tocar el producto); el plan los marca
«comprobado».

### Bloqueante

1. **Plazo de los transcripts.** Decisión de la sesión principal: el comando lee
   `cleanupPeriodDays` de `~/.claude/settings.json` (30 si falta) y lo guarda en
   `coste-agregados.json` (`plazo_dias`). Enmienda mínima de la spec, anotada al final de `spec.md`
   como «Enmiendas posteriores a la aprobación», con su motivo: definición nueva de `H`; REQ-004,
   REQ-007 y REQ-075 usan `H` (aviso a `H` − 10 días, que con 30 sigue siendo a los 20); escenario
   de `doctor` con `H` = 30 y una nota con `H` = 90. El panel toma `H` del JSON (30 sin JSON);
   `doctor` lo lee de `settings.json`. La función vive en `atribucion.plazo_de_borrado` (T2), con su
   test. Tests nuevos: `test_el_relleno_usa_el_plazo_leido` (T5), `test_guarda_el_plazo` (T5),
   `test_tramos` con `plazo_dias` 30 y 90 (T4), `test_el_aviso_sigue_al_plazo` (T7). T0.6 comprueba
   que el plazo está en vigor; el riesgo se reescribe («mezclar antes de diciembre; la Mac, con 30»)
   y T8.4 dice qué se espera de septiembre.

### Importantes

2. **`daemon-reparte-el-backend`.** Orden fijado: panel → este → aquel. Nueva sección «Orden entre
   cambios» en la «Approach», con la tabla de ficheros compartidos; este plan cuenta 21 → 22 checks
   y 1 → 2 hooks, y T0.3 se para si no son esos.
3. **Notas concurrentes.** Una nota por llamada: un fichero por `tool_use_id` en
   `local-delegate-llamadas/`, escrito con temporal + `os.replace`; el id se valida antes de
   construir la ruta; el hook borra las de más de 10 min. Tests: `test_dos_llamadas_no_se_pisan`
   (mutante «nombre fijo», comprobado), `test_ocho_hooks_a_la_vez` (guarda) y
   `test_una_nota_a_medias_es_sin_nota`.
4. **T4 ∥ T5.** Pasan a ir en serie (olas 3 y 4). El inventario de T4 corre la suite entera sin
   `--ignore`.
5. **Exclusión.** `CLIENTES_EXCLUIDOS` y `excluida(fila, entrada)` van a `atribucion.py` (T2), con
   `test_excluida`; `coste.tramo` (T4) y `recalcular` (T5) la importan, y T5 gana
   `test_los_agregados_de_n_no_cuentan_excluidas`.
6. **Controles que fallaban por excepción.** `cli.run` (comprobado: hoy `SystemExit(2)`; `cli.main`
   no existe). `TestClient(..., raise_server_exceptions=False)` (comprobado: el `JSONDecodeError`
   llega como 500). La resolución rota lanza `RuntimeError`, el test la recoge en `escapo` y
   comprueba `assert not escapo` antes de contar líneas; el `try` propio atrapa `Exception`
   (comprobado: una `RuntimeError` sale hoy de `_log_event`). Los tests de sockets registran
   `getaddrinfo`, `create_connection` y `connect` (comprobado: `urlopen` deja un intento sin red
   con un nombre y con una IP literal).
7. **Quién arregla un rojo.** El integrador solo arregla lo mecánico; un rojo de comportamiento
   vuelve a su dueño, que repite el control. `git diff --stat -- <ficheros de la tarea>`. Un commit
   firmado por tarea con rutas explícitas; `state.json`, la sesión principal.
8. **`_meta` antes de construir encima.** Prueba de humo en I2 con el servidor del repo y una
   llamada real de `claude -p` (anota que contamina esa ventana de 5 h). T0.7 cuenta las líneas con
   `bloqueo_id` como evidencia del temporal compartido; T10.3 queda como verificación instalada.
9. **`tokens_claude` simétrica.** Sin `densidad`, las dos dan 0; los mensajes en vuelo llaman a
   `resolver_densidad`. Test nuevo `test_sin_densidad_las_dos_dan_cero`; el mutante de
   `test_local_status_funde_como_el_panel` muta ahora porque sin fusión da 0.
10. **REQ-054 y REQ-061 sin test.** `test_cuota.py::test_sanear_y_lineas_corruptas` en T5, con un
    mutante por rama; trazabilidad actualizada.
11. **Privacidad de T8.2.** Patrón de unidad `[A-Za-z]:[\/]` (cubre `D:`), `/Users/`, `/home/`, el
    nombre de cada carpeta de `~/.claude/projects`, el usuario del sistema, UUID y `toolu_`; solo
    conteos.

### Menores

12. Paridad (c): el plan cita ya el caso 0 existente y el campo `returned` (179 contra 100), y dice
    que los 22 casos existentes también pasan por `coste.fundir`. Hecho.
13. Segundo inventario de T4 tras cambiar el JS (paso 5). Hecho.
14. Lista de partida del inventario copiada en T4.3. Hecho.
15. Líneas `conftest.py:116` y `test_checks.py:574`, con «el `rg` manda». Hecho.
16. Test del shebang tras `git add` y `chmod +x` si hay `#!`, en las reglas comunes, T2 y T3. Hecho.
17. `TEMP`/`TMP`/`TMPDIR` del subproceso del hook en `tmp_path`. Hecho.
18. Memoria por petición en un `ContextVar` que pone el middleware; test
    `test_la_memoria_no_cruza_peticiones`. Hecho.
19. Validación del `transcript_path` (bajo `~/.claude/projects`, `.jsonl`) con
    `test_una_ruta_fuera_de_projects_no_se_abre`; el plan dice por qué la nota guarda una ruta y
    que caduca a los 10 min. Hecho.
20. Δ$ del rechazo contra `calibracion.py` (T8.6); asserts del cuerpo del PR de límites, del «ya hay
    PR», de los ids nuevos y de `caller_agent_type` solo en subagentes. Hecho.
21. `docs/recipes/claude-code-hooks.md` en T9. Hecho.
22. T10.3 usa `claude -p` desde el principio (anota la ventana contaminada); T10.7 corre `doctor`
    tras volver a la 0.32.0. Hecho.
23. Comando entero `uv run --group ui pytest -q`. Hecho.

### Llamadas a `local-delegate`

0 en esta pasada: había que citar líneas literales de la revisión y de la spec y comprobar
controles ejecutándolos; un resumen no servía para eso.
