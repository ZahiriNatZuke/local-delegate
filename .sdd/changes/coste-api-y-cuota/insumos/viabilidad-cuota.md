# Viabilidad: mostrar en el panel el ahorro de cuota (5 h y semanal) y su coste equivalente en API

Fecha de la investigación y de consulta de fuentes: **2026-10-06**. No se tocó el repo ni la configuración.
Convención: **[V]** verificado (con fuente o `fichero:línea`, o medido aquí), **[I]** inferido, **[?]** no se sabe.

---

## Conclusión por métrica

| Métrica | Veredicto | Supuesto que hay que declarar |
|---|---|---|
| **(c) Coste equivalente en API** | **Viable como estimación**, en dos cifras: cota baja y estimación central | Modelo de Claude que habría leído el fichero, conversión chars→tokens, y N (cuántas veces más se relee de la caché). N se puede **medir** en los transcripts para los últimos ~30 días |
| **(a) % de la cuota de 5 h** | **Viable solo como estimación calibrada, y aún sin validar** | Que la cuota de la suscripción se consume en proporción al coste a precio de lista. Anthropic **no** lo dice: hay que calibrarlo con datos propios y validarlo antes de mostrarlo |
| **(b) % de la cuota semanal** | Igual que (a), con un factor de calibración propio | Ídem; además hay límites semanales por familia de modelo (p. ej. Fable aparte) |
| Cuota en **tokens** (absoluta) | **No viable** | Anthropic no publica la capacidad de las ventanas en tokens ni en mensajes |

En resumen, (c) se puede hacer ya con honestidad. (a) y (b) dependen de una calibración que hoy no existe. Esa calibración tiene que pasar un control capaz de fallar antes de enseñarse; si no lo pasa, (a) y (b) no se muestran.

**Novedad de la ampliación (ver §5):** los transcripts guardan los **rechazos** de cuota. Cada uno es un punto en el que la ventana estaba al 100 %, así que da un ancla sin gastar cuota:
- La única ventana de 5 h rechazada (2026-10-01) costó **≈ $126 a precio de lista** en esta PC.
- La semana rechazada (2026-10-01) costó **≈ $400**.

Son un punto de cada tipo: bastan para un orden de magnitud, no para validar la proporcionalidad. Además, los experimentos de §5 indican que **chars/4 subestima los tokens de Claude** (dan ~2,2 chars/token) y que **los subagentes escriben en caché a 5 min y el hilo principal a 1 h**. Las dos cosas cambian la fórmula de (c).

---

## 1. Qué se mide hoy

**[V] Fuente única de la contabilidad:** `src/local_delegate/server.py:579-643` (`_accounting`). La importa `web/metrics.py:206` y tiene un espejo JS en el panel, `web/metrics.py:1676-1698` (`acct`), que el test `tests/test_metrics.py:648` (`test_paridad_acct_entre_python_y_el_js_del_panel`) ejecuta con node y compara con la de Python.

- **«Contexto conservado»** (`saved`, expuesto como `tokens_context_saved`, `metrics.py:391`):
  - Solo cuenta si `source == "path"`. Una llamada `inline` da 0 (`server.py:618-619`).
  - Texto: `chars_in // CHARS_PER_TOKEN`, con `CHARS_PER_TOKEN = 4` (`config.py:351`). **Siempre por caracteres**, aunque el backend haya dado tokens reales (`server.py:620-621`). Además, son tokens del tokenizador *local* y no los de Claude.
  - Imagen: el token real del backend, o 0 si no lo hay (`server.py:622-625`).
  - Se le suma la salida escrita a fichero (`output_to_file`, `server.py:630-631`).
  - Se cuenta **una vez** por delegación aunque se trocee.
- **«Coste local»** (`tokens_local_input`): `tokens_in` real del backend sumando todas las llamadas, con `chars/4` como respaldo y el evento marcado `estimated` (`server.py:611-616`). **«Generado en local»** es `tokens_out`.
- **Unidad:** «tok», una magnitud aproximada (chars/4). No es un token de Claude ni dinero.
- **Supuestos implícitos de «Contexto conservado»:**
  1. Contrafactual: sin la delegación, Claude habría leído el fichero **entero**. No tiene por qué: podía leer por franjas o no leerlo.
  2. Es una cifra **bruta**: no resta la respuesta de la tool, que sí entra al contexto. Medido aquí en el log de uso con chars/4: en septiembre fueron 976 509 tok de ahorro bruto frente a 72 126 tok de salida que sí entró; en octubre, 630 682 frente a 39 038.
  3. No resta las **relecturas**. Medido aquí en los transcripts: de 168 delegaciones con `path` fuera de los bancos de prueba, solo **5** van seguidas de un `Read` del mismo fichero. Si se cuentan también los `Bash`/`PowerShell` que nombran el fichero (heurística laxa: incluye `grep`), son **50**. La relectura real queda entre el ~3 % y el ~30 %.
  4. Cuenta **una sola vez**, aunque en la realidad el contenido se habría releído en cada turno siguiente (ver §3).
- **[V] El log no guarda el modelo de Claude.** `_log_event` (`server.py:453-574`) guarda `model`, que es el modelo **local** que respondió, más `client` (nombre y versión del cliente MCP), `path`, `ts`, `chars_*` y `tokens_*`. No guarda ni el modelo de Claude ni `session_id`.
  - **[I]** Se puede recuperar cruzando `ts` + `path` del log con el `tool_use` del transcript `~/.claude/projects/**/*.jsonl`. Cada mensaje `assistant` trae `message.model` (p. ej. `claude-opus-5-5`) y `sessionId`.
  - **[V]** Solo para los últimos ~30 días: el transcript más antiguo que queda es del 2026-09-03. Claude Code borra a los 30 días (`cleanupPeriodDays`, según la doc de costes). El log de uso, en cambio, llega hasta julio.

## 2. Cuotas de la suscripción

**Dato oficial [V]:**
- Hay una ventana de sesión de **5 h** y un límite **semanal** que aplica a todos los modelos y se reinicia a una hora fija asignada a la cuenta. Max 5x y Max 20x son **5× y 20× la asignación por sesión de Pro**. **No se publica ninguna cifra** en tokens ni en mensajes: depende de la longitud, los ficheros, el modelo, las funciones y el esfuerzo («no fixed message count»). Anthropic además se reserva limitar «in other ways… at our discretion» (help center, artículo del plan Max).
- El uso de claude.ai, Claude Code y Claude Desktop cuenta contra **el mismo** límite (help center, «How do usage and length limits work»).
- **El JSON del statusline trae los porcentajes** (doc oficial del statusline): `rate_limits.five_hour.used_percentage`, `rate_limits.five_hour.resets_at`, `rate_limits.seven_day.used_percentage` y `rate_limits.seven_day.resets_at`. Los porcentajes van de 0 a 100 y `resets_at` en segundos epoch.
  - Condiciones: el objeto solo existe para suscriptores Pro/Max (o tras un gateway con límite de gasto) y solo **después de la primera respuesta** de la sesión. Cada ventana puede faltar por separado y desaparece cuando pasa su `resets_at`.
  - Trae además `cost.total_cost_usd`, que la doc describe como «estimated… computed client-side at list price», y un objeto `prompt_cache` con `ttl`, `requests`, `hit_ratio`, etc.
- `/usage` muestra las barras del plan y un desglose **aproximado** de atribución por skill, subagente y **servidor MCP**. Ese desglose se calcula con el historial local, «so usage from other devices or claude.ai is not included» (doc de costes). La atribución mide lo que *consumieron* las peticiones con resultados de ese MCP, no lo que se ahorró.
- **El mecanismo de las relecturas es oficial:** «Claude Code sends your full conversation with every request… re-reads that history at the cached token rate». En suscripción, el TTL de la caché es **1 h** (5 min si se tira de usage credits) (doc de costes, «Why usage climbs in a long session»).
- Los transcripts locales traen `usage` por mensaje con `input_tokens`, `cache_creation_input_tokens` (desglosado en `ephemeral_1h`/`ephemeral_5m`), `cache_read_input_tokens` y `output_tokens`, y una línea `cost-state` con `totalCostUSD` y `modelUsage` por modelo. Verificado aquí leyendo un transcript real.

**De terceros, no oficial [V que existe / I que sea estable]:**
- Las cabeceras de respuesta `anthropic-ratelimit-unified-5h-utilization`, `-5h-reset`, `-5h-status` y sus equivalentes `7d` las llevan las peticiones autenticadas con suscripción. La utilización viene como fracción de 0 a 1. Están documentadas por proyectos de la comunidad (PRs de opencode y crush), no por Anthropic. Leerlas exigiría hacer peticiones con el token OAuth del usuario: no conviene.
- `ccusage` **no conoce la cuota**: agrupa en bloques de 5 h desde el primer mensaje, y el límite se lo das tú (`--token-limit`) o toma el máximo de bloques anteriores (`--token-limit max`).
- El issue anthropics/claude-code#29721 pedía la contribución por sesión a las ventanas de 5 h y 7 d, y que se publicaran los límites absolutos. Se cerró como **«not planned»**. Lo que planteaba sobre si cada tipo de token pesa distinto quedó sin respuesta.

**No se sabe [?]:**
- Cuántos tokens o dólares equivalen al 100 % de cada ventana.
- Si la cuota pondera los tokens igual que el precio de API (lecturas de caché a 0,05×, salida a 5×, etc.) o de otra forma.
- Si las lecturas de caché cuentan para la cuota, y cuánto. **[I]** Que cuentan algo se deduce de la frase oficial «draws usage for the whole conversation».

**Consecuencia:** el porcentaje de la ventana se puede **leer** (statusline), pero no se puede **traducir** a tokens ahorrados sin calibrarlo.

## 3. Coste en API

**Precios oficiales (platform.claude.com/docs/en/about-claude/pricing, consultado el 2026-10-06), USD por MTok:**

| Modelo | Entrada base | Escritura caché 5 min | Escritura caché 1 h | Lectura de caché | Salida |
|---|---|---|---|---|---|
| Claude Fable 5.1 | 10 | 12,50 | 20 | 0,25 (0,025×) | 50 |
| Claude Opus 5.5 | 4 | 5 | 8 | 0,20 (0,05×) | 20 |
| Claude Sonnet 5.5 | 2 | 2,50 | 4 | 0,20 | 10 |
| Claude Haiku 4.5 | 1 | 1,25 | 2 | 0,10 | 5 |

Modificadores oficiales:
- Contexto de 1M sin recargo desde 4.6.
- `inference_geo: "us"` multiplica por 1,1.
- Fast mode de Opus 5.5: 8 de entrada y 40 de salida.
- La doc avisa de que los modelos 4.7 y posteriores usan un tokenizador que da «~30 % más tokens» para el mismo texto. **[I]** Por eso chars/4 probablemente **subestima** los tokens de Claude.

**[V] Control de la tabla:** se recalculó el coste de sesiones cerradas a partir de su `usage` y se comparó con el `totalCostUSD` que calcula Claude Code a precio de lista:
- Cuatro sesiones pequeñas cuadran al céntimo (0,32 / 0,30 / 0,33 / 0,29).
- Una sesión grande queda un 6 % por debajo (47,38 frente a 50,33): causa sin investigar.
- Una sesión dio 0 porque la tabla de la prueba no tenía `claude-opus-5`. Es justo el fallo que el control debe atrapar.

Es un control que **puede** dar un resultado distinto, y sirve como guardián de una tabla desactualizada.

**Por qué un token no se paga una sola vez [V, doc de costes]:** un `tool_result` entra en la petición siguiente como escritura de caché (en suscripción, con TTL de 1 h, a 2× la entrada base) y después se **relee como lectura de caché en cada petición** hasta que la sesión termina, se compacta o se limpian los resultados viejos de tools. Si el usuario vuelve tras más de 1 h, el contenido se reescribe, lo que es un sobrecoste adicional que se ignora.

**Fórmula propuesta.** Sea `T` = tokens de Claude ahorrados netos = ahorro bruto − tokens de la respuesta de la tool, con `T ≈ chars/4 × k_tok`, donde `k_tok` es un factor de tokenizador declarado (1,0 por defecto, o calibrado). Precios del modelo `m`: `P_w1h`, `P_r`.
- **Cota baja:** `C_min = T × P_w1h(m)`. Una sola escritura. Si se quiere la cota más conservadora posible, `T × P_in(m)`.
- **Estimación:** `C_est = T × (P_w1h(m) + N × P_r(m))`.
- **N** = número de peticiones a la API **posteriores** a la delegación en el mismo hilo (sesión principal o subagente), hasta el fin del hilo o el primer `compact_boundary`. Se calcula del transcript. Limitaciones:
  - La limpieza automática de resultados viejos de tools no deja una marca equivalente fiable en el transcript, así que N es una **cota alta** de las relecturas.
  - El contrafactual cambia la propia sesión: con el fichero dentro habría compactado antes.

**[V] N medido aquí** con un script de solo lectura sobre los transcripts que quedan, excluyendo los bancos `Temp-banco-*`: 166 delegaciones con `path`, 140 de ellas en subagentes.
- p10 = 7, p25 = 25, **mediana = 49,5**, p75 = 92, p90 = 215, máximo = 390, media 76,8.
- 0 compactaciones en esos hilos.

**Orden de magnitud ilustrativo** (no es una cifra para el panel). Septiembre, ahorro bruto 976 509 tok y neto ≈ 904 383 tok, suponiendo todo en Opus 5.5 y `k_tok = 1`:
- Cota baja ≈ **$7,2**.
- Estimación con N = 49,5 ≈ 7,2 + 904 383 × 49,5 × 0,20 / 10⁶ ≈ **$16**.
- Incluye eventos de prueba sin filtrar, y la relectura del ~3–30 % la reduciría.

## 4. Diseño propuesto

**Qué se puede afirmar con honestidad:**
1. **«A precio de API habría costado entre $X (cota baja) y ~$Y (estimación)»**, con desplegable de supuestos: modelo asumido, chars/4 × k_tok, N mediana de los últimos 30 días o N por evento cuando el transcript sigue existiendo, y una marca «neto de la respuesta de la tool».
   - Etiqueta: «**equivalente estimado**, no es dinero que hayas ahorrado: tu suscripción es de tarifa plana».
   - Por evento: si se encuentra en el transcript, se usan su modelo y su N reales; si no, se marca `estimated` (el patrón que ya existe en `_accounting`).
2. **«≈ Z % de una ventana de 5 h / de la semana»**, **solo** si la calibración pasa el control. Si no, el panel muestra «no calibrado» y nada más.

**Cómo calibrar (a) y (b), sin red:**
- Ampliar el statusline del usuario, previo permiso, porque es su configuración, para que anexe a un JSONL local `(ts, session_id, five_hour.used_percentage, seven_day.used_percentage, resets_at)`.
- En paralelo, el coste a precio de lista de **todas** las sesiones locales se saca de los transcripts.
- Factor `κ_5h = Δ% / Δ$lista` dentro de una misma ventana (lo mismo para la semanal). El ahorro en cuota sería `C_est × κ`.
- **Supuesto declarado:** la cuota se consume en proporción al coste de lista. No está confirmado; el issue #29721 lo deja abierto.
- **Contaminación:** claude.ai, la Mac y Claude Desktop gastan la misma cuota y no salen en los transcripts de esta PC. Solo sirven ventanas de uso exclusivo de esta PC, o hay que descartarlas.
- **Control que puede fallar:** calibrar `κ` en la mitad de las ventanas y predecir Δ% en la otra mitad. Si el error mediano supera un umbral fijado **antes** de mirar (p. ej. ±25 %), (a) y (b) no se publican.
- **Validación contra juicio humano:** comparar con lo que el usuario ve en Settings > Usage en un par de ventanas concretas.

**Qué NO se puede afirmar:**
- «Ahorraste N tokens de tu cuota»: no hay cuota en tokens.
- «Ahorraste $Y»: en suscripción no hay factura por token.
- Cualquier % sin calibrar, ni un % que mezcle 5 h y semanal.
- Tampoco que el contrafactual sea seguro: Claude podría no haber leído el fichero.

**Precios versionados:**
- Una tabla en el paquete (p. ej. `precios.toml`) con la `fuente` (URL), la fecha `consultado = 2026-10-06` y todos los modelos que aparecen en los transcripts.
- Sin red en tiempo de ejecución. Un aviso de `doctor` si la tabla tiene más de 90 días o si un transcript trae un modelo sin precio.
- El cotejo `usage × tabla` contra `cost-state.totalCostUSD` como guardián (ver §3). **[I]** Una alternativa es fiarse del `costUSD` de Claude Code y no mantener tabla propia, pero ese coste es por sesión y no por delegación, así que la tabla sigue haciendo falta para el cálculo por evento.
- Por la regla de la casa, una release que lo toque actualiza CHANGELOG, README y `docs/wiki/Savings-and-metrics.md`.

**Antes de construir:**
- El vault no tiene nada sobre «cuota» como métrica en `projects/local-delegate/`.
- El backlog §4.1 trata de adopción (comandos slash, plugin, trabajos en segundo plano) y no choca con esto.
- El backlog sí recuerda que «El panel NO tiene filtros».
- **[I]** Esto encaja en un SDD propio, porque toca la contabilidad única, el espejo JS y el test de paridad, y la config del statusline del usuario.

---

## 5. Fuentes de la comunidad, experimentos y afirmaciones verificadas (ampliación)

### 5.1 Lo que dice la comunidad (todo es hipótesis hasta probarlo)

| Quién | Fecha | Qué dice | Choca con |
|---|---|---|---|
| Help center, «Usage limit best practices» (oficial) | consultado el 2026-10-06 | «cached portions count less against your limits than new content»; al volver tras una pausa, «your first message counts that content in full again» | Con quien diga que la caché no cuenta. Confirma que cuenta, **pero no dice cuánto** |
| HN 49491631 (tuit de @claudedevs; comentario de *kedihacker*) | hace ~37 días (≈ 2026-08-30) | Titular «reduce limits by 25 % from September 14». El comentario corrige: se pasa de +50 % temporal a +25 % permanente, que es **−17 %** respecto al nivel anterior | El resumen del buscador decía «permanently raised by 25 %». **Las dos versiones son la misma noticia con distinta base: la cuota cambia por decisión comercial, y el ancla de §5.3 caduca** |
| HN 44713757 (anuncio de los límites semanales) | 2025 | Max 5x ≈ «140–280 h de Sonnet 4 y 15–35 h de Opus 4» por semana | Horas, no tokens; son modelos ya retirados. Obsoleto |
| Blogs (truefoundry, wmedia, morphllm, tokensforgood; consultados el 2026-10-06) | 2026 | «~45 / 225 / 900 mensajes por 5 h» (Pro / Max 5x / Max 20x); «cap on active compute hours»; un semanal «solo Sonnet» | Entre ellos (mensajes, horas, tokens) y con el oficial («no fixed message count»). Sin dato primario: **se descartan** |
| Claude-Code-Usage-Monitor (Maciek-roboblog, GitHub) | consultado el 2026-10-06 | Planes «Pro ~44k, Max5 ~88k, Max20 ~220k tokens» y un modo custom con el **P90 de las sesiones de las últimas 192 h** | Con el oficial: son cifras **inferidas** por el autor. Con mis datos: una sola ventana rechazada movió 312 M de lecturas de caché |
| ccusage (ryoppippi) | consultado el 2026-10-06 | No conoce la cuota: bloques de 5 h desde el primer mensaje, y el límite lo pones tú o es el máximo histórico (`--token-limit max`) | — |
| anthropics/claude-code#29721 | cerrado «not planned» | Pide la contribución por sesión y los límites absolutos; deja abierto si cada tipo de token pesa distinto | — |
| anthropics/claude-code#51406 (*eddiehernandez*) | 2026-04-21, cerrado «not planned» | La ventana de «5 h» se agota por tokens y contexto, no por tiempo. Anecdótico, sin datos | — |
| anthropics/claude-code#75408 (*bunnyfingers*, v2.1.202) | 2026-07-07, **abierto** | `rate_limits.five_hour.used_percentage` es el valor de la **última respuesta de esa sesión**, no una lectura en vivo, y difiere entre terminales (54 % frente a 58 %) | Afecta al diseño: hay que guardar cada lectura con su hora y no restar lecturas de sesiones distintas |
| anthropics/claude-code#52326 y #31820 | 2026 | Errores del campo: a veces trae un epoch en vez del %, o valores como 900 % | Hay que sanear: descartar <0 o >100 |
| anthropics/claude-code#85964 (*johnkim-orcait*, v2.1.228, Team) | 2026-08-12, cerrado como duplicado | `rate_limits` solo trae `five_hour` y `seven_day` de toda la cuenta; los límites semanales **por modelo** que enseña `/usage` (p. ej. «Fable 5 — 24 %» con `seven_day` en 13 %) no llegan | La métrica (b) no puede ser por modelo |
| PRs de opencode (#49651) y crush (#3870) | 2026 | Cabeceras `anthropic-ratelimit-unified-5h-utilization` y `-7d-…`, una fracción de 0 a 1 que equivale al % del statusline | — |
| Vídeos de YouTube (p. ej. «Why Claude Code Hits Its Usage Limit So Fast», «Claude Usage Limits Explained») | 2026 | Por título y descripción son divulgación y tutoriales de `/usage` y el statusline, sin medición propia | **No los transcribí**: no aportan dato primario que no tengamos. Si se quiere, el candidato es el primero, con `analizar-multimedia` |

Lo que sí vi en el **binario instalado** (Claude Code **2.1.291**, `~/.local/bin/claude.exe`, con `grep -a` y sin ejecutar nada):
- Las cadenas `anthropic-ratelimit-unified-5h-utilization`, `-7d-utilization`, `-5h-reset`, `-7d-reset`, `-representative-claim`, `-overage-*` y `-grace-*`.
- La ruta `api/oauth/usage`.
- Los cubos `seven_day_opus` y `seven_day_sonnet`.

Confirma que el cliente **consume** esas cabeceras y ese endpoint, no cómo calcula el servidor. El Agent SDK (`claude_agent_sdk/types.py`, copia en `~/.claude/backups/...`) expone además `RateLimitEvent` con `utilization` de 0,0 a 1,0.

### 5.2 Experimentos ejecutados (baratos, sin gastar cuota y sin tocar la configuración)

| Experimento | Qué se hizo | Resultado |
|---|---|---|
| **E1: campos de `usage` en los transcripts** | Leer un transcript real | **Confirmado.** Cada `assistant` trae `message.model`, `usage.input_tokens`, `cache_creation_input_tokens` con desglose `ephemeral_5m` / `ephemeral_1h`, `cache_read_input_tokens`, `output_tokens` (con `thinking_tokens`), `service_tier` y `speed`. Hay líneas `cost-state` con `totalCostUSD` y `modelUsage`. Ningún campo de % de cuota en mensajes normales |
| **E2: TTL de la caché por hilo** | Desglosar las escrituras de caché por hilo en una ventana | **Matiza la doc.** Hilo principal: solo `ephemeral_1h` (171 909 tok, 0 a 5 min). Subagentes: **solo `ephemeral_5m`** (21,8 M, 0 a 1 h). La doc dice «an hour on a subscription», pero eso vale solo para el hilo principal. Como 140 de 166 delegaciones van en subagentes, su cota baja se calcula con la escritura a 5 min |
| **E3: el statusline recibe `rate_limits`** | Leer el script del usuario y su config de oh-my-posh | **Indicio fuerte.** `~/.claude/statusline.ps1` pasa el stdin a `oh-my-posh claude`, y `Documents/claude.omp.json` ya pinta `.RateLimits.FiveHour.UsedPercentage` y `.RateLimits.SevenDay.UsedPercentage`, así que el usuario ya ve esos % en su barra. **No capturé el JSON crudo**: habría que tocar `statusLine` (ver E9) |
| **E4: rechazos guardados en los transcripts** | Buscar `rateLimitType` en todos los transcripts | **Confirmado y útil.** 13 eventos (11 de `five_hour`, 2 de `seven_day`) dentro de mensajes `assistant`, con `status: "rejected"`, `resetsAt`, `overageStatus` y `overageDisabledReason: "out_of_credits"`. **No traen el % de uso**, pero marcan el instante en que la ventana llegó al 100 % |
| **E5: ancla de capacidad** | Sumar a precio de lista todo el uso local (358 transcripts, 23 303 peticiones) dentro de cada ventana rechazada | **5 h** (21:30 → rechazo el 2026-10-01 a las 01:14 UTC): 1 537 peticiones, **$126,41**. Tokens: 312 M de lectura de caché, 12,1 M de escritura a 5 min, 0,1 M a 1 h, 133 k de salida. **Semana** (desde el 2026-09-27 09:00 → rechazo el 2026-10-01 a las 18:41): 5 661 peticiones, **$400,45**. Límites: no incluye claude.ai, la Mac ni Desktop (sería una cota **baja** de la capacidad); se supone que la ventana empieza en `resetsAt − 5 h`; y hay un solo punto de cada tipo |
| **E6: N, las relecturas de caché por delegación** | Contar peticiones posteriores a cada delegación con `path` en el mismo hilo | **Medido** (§3): mediana 49,5, p90 215, sin compactaciones. N cuenta peticiones, no tokens releídos: la limpieza automática de resultados de tools podría cortarlo antes (sin medir) |
| **E7: relectura del mismo fichero** | Buscar `Read` (o comandos que lo nombran) del mismo `path` después de delegar | Entre 5 y 50 de 168 (≈ 3–30 %): el ahorro real es menor que el bruto |
| **E8: chars/token de Claude** | Resultado grande de **una** tool (20–90 k chars) frente a los tokens nuevos de la petición siguiente (`cache_creation + input − output` del turno anterior) | **Indicio de que chars/4 subestima.** `Read`: 152 casos, mediana **2,26 chars/token** (p10 1,11; p90 9,75). `Bash`: 13 casos, mediana **1,99** (p10 1,45; p90 2,36). Ruido conocido: avisos del sistema pegados al mensaje, números de línea de `Read`, y salidas persistidas a fichero. Si se confirma, los tokens de Claude serían **~1,8× los de chars/4** |
| **E10: tabla de precios contra Claude Code** | Recalcular el coste de sesiones cerradas con la tabla oficial y compararlo con `cost-state.totalCostUSD` | Cuatro cuadran al céntimo; una grande difiere un 6 %; una no tenía precio porque faltaba `claude-opus-5`. **El control puede fallar y falló una vez**: sirve de guardián |

Scripts (solo lectura) en `scratchpad/scripts/`: `n_relecturas2.py`, `relecturas*.py`, `ventana_rechazo.py`, `chars_por_token*.py`.

### 5.3 Experimentos diseñados (necesitan al usuario o gastan cuota)

**E9: capturar el JSON real del statusline.** Coste: un turno corto (Haiku), ≈ 0 % de la ventana.
1. El usuario lanza una sesión **aparte**, sin tocar su `settings.json`: `claude --model haiku --settings <scratch>/captura-statusline.json`. Ese fichero define `statusLine.command` como un script que copia el stdin a `<scratch>/statusline-*.json` y después llama al `statusline.ps1` de siempre.
2. Escribe «hola» y sale.
- **Confirma:** el JSON trae `rate_limits.five_hour.used_percentage` (y su tipo, entero o decimal), `resets_at` y `seven_day`.
- **Refuta:** no aparece `rate_limits` con suscripción Max tras la primera respuesta.
- Antes de lanzarlo, comprobar que `--settings` añade a la configuración y no la reemplaza, para que los hooks y MCP de siempre no cambien. Mejor hacerlo fuera de una ventana de medición de adopción, porque los hooks de esa sesión también escriben telemetría.

**E11: ¿la cuota es proporcional al coste de lista?** Coste: 0 de cuota extra (es pasivo), pero necesita cambiar el `statusLine` del usuario **con su permiso**: el mismo envoltorio de E9, que anexe `ts, session_id, five_hour%, seven_day%, resets_at` a un JSONL local. Duración: 2–3 semanas.
- Para cada par de lecturas de la **misma sesión** (por #75408), comparar Δ% con Δ$ a precio de lista de **todas** las sesiones locales en ese intervalo (sacado de E1).
- Ajustar una regresión con un peso por cada tipo de token y modelo.
- **Confirma** «proporcional al coste»: el factor κ = Δ%/Δ$ se mantiene estable (CV < 25 %) y predice ventanas reservadas con error mediano < 25 %.
- **Refuta**: κ varía con la mezcla (p. ej. las ventanas cargadas de lecturas de caché gastan proporcionalmente más o menos de lo que dice el precio), o el error > 25 %.
- Excluir las ventanas en que se usó la Mac o claude.ai: el usuario las marca, o se detectan por saltos de % sin uso local.

**E12: ¿cuánto pesa la lectura de caché en la cuota?** Coste: apreciable, del orden de 5–15 % de una ventana de 5 h. Se corre **juntos** y en un momento en que la cuota no haga falta.
- Una sesión con Haiku carga un prefijo grande (~150 k tokens).
- Fase A: 20 peticiones cortas que solo leen el prefijo (casi todo `cache_read`). Anotar el % antes y después (E9 o `/usage`).
- Fase B: el mismo volumen de tokens como **entrada nueva** (`/clear` y volver a cargar, o esperar a que caduque).
- **Confirma** «la cuota sigue el precio»: Δ%_A / Δ%_B ≈ 0,1 (el multiplicador de lectura de Haiku).
- **Refuta**: el cociente ≈ 1 (la caché no abarata la cuota) o ≈ 0 (no cuenta).
- Si el % es entero, cada fase tiene que mover ≥ 10 puntos para que la diferencia se distinga de la resolución. **Este es el control que puede dar un resultado distinto.**

**E13: confirmar chars/token sin ruido.** Coste: un turno.
- En una sesión limpia se lee **un** fichero conocido de ~40 k chars sin `offset`, y se mide la diferencia de `cache_creation + input` respecto al turno anterior.
- Se repite con un `.py`, un `.md` en español y un `.jsonl`.
- **Confirma** el ~2,2 de E8 si sale 1,8–2,6; **lo refuta** si sale ≈ 4.

### 5.4 Afirmaciones y su verificación

| Afirmación | Fuentes | Estado |
|---|---|---|
| El JSON del statusline trae el % de la cuota de 5 h y de la semanal | Doc oficial del statusline; #75408; config oh-my-posh del usuario | **Pendiente de E9** (indicio fuerte: la barra del usuario ya lo pinta) |
| Ese % es de la última respuesta de la sesión, no en vivo | #75408 | Pendiente de E11 (se verá al comparar sesiones paralelas) |
| No hay % por modelo en el statusline | #85964; doc del statusline | Pendiente de E9 |
| Los transcripts traen `usage` por mensaje, con el modelo y el TTL de la caché | Doc de costes; lectura directa | **Verificada por nosotros (E1)** |
| En suscripción la caché dura 1 h | Doc de costes | **Refutada en parte (E2):** 1 h en el hilo principal, **5 min en los subagentes** |
| Los transcripts guardan los rechazos de cuota | — (hallazgo propio) | **Verificada (E4)**, sin % de uso |
| Anthropic no publica la cuota en tokens ni en mensajes | Help center (Max, límites); #29721 | Verificada documentalmente: no aparece en ninguna fuente oficial consultada |
| «Pro ~44k / Max5 ~88k / Max20 ~220k tokens» | Claude-Code-Usage-Monitor | **Refutada como cifra de capacidad por E5**: una ventana rechazada movió cientos de millones de tokens (sobre todo lectura de caché), así que, si esas cifras significan algo, no son tokens brutos de la API |
| «~45 / 225 / 900 mensajes por 5 h» | Blogs | Contradice a la fuente oficial («no fixed message count»); no se adopta |
| La cuota se mide en tokens ponderados por modelo / proporcional al coste | Help center («model choice» influye); comunidad (especulación) | **Pendiente de E11** |
| Las lecturas de caché cuentan para la cuota, pero menos | Help center («count less»); doc de costes («draws usage for the whole conversation») | Oficial y cualitativa; **el peso, pendiente de E12** |
| 100 % de 5 h ≈ $126 de lista; 100 % semanal ≈ $400 (esta PC) | — (E5) | **Medido, con un solo punto de cada uno**; cota baja (falta el uso de otras superficies) y caduca si Anthropic cambia los límites (HN 49491631) |
| chars/4 aproxima los tokens de Claude | Doc de precios (FAQ: «~4 characters») y la propia doc avisa de +30 % desde 4.7; `config.py:351` | **Indicio en contra (E8: ~2,2 chars/token)**; pendiente de E13 |
| Cada token entra una vez y luego se relee N veces | Doc de costes | Mecanismo oficial; **N medido (E6)**; la limpieza de resultados de tools no se ha medido |
| La tabla de precios cuadra con lo que calcula Claude Code | Doc de precios; `cost-state` | **Verificada en 4 de 6 sesiones (E10)**; una con un 6 % de diferencia, sin investigar |
| El cliente lee las cabeceras `anthropic-ratelimit-unified-*` y el endpoint `api/oauth/usage` | PRs de opencode y crush; issue de CodexBar | **Verificada la presencia en el binario 2.1.291**; el comportamiento no se probó (usarlas exigiría el token OAuth: **no recomendado**) |

### 5.5 Qué cambia en el diseño de §4

- **(c):**
  - Cota baja = `T × P_w` con `P_w` = **escritura a 5 min** si la delegación ocurrió en un subagente y **a 1 h** si fue en el hilo principal.
  - `T` se calcula con `k_tok` (1,0 hasta que E13 lo fije; mostrar «puede ser ~1,8× mayor»).
  - N y el modelo, por evento cuando el transcript existe.
- **(a) y (b):**
  - Hasta tener E11, como mucho: «**orden de magnitud**: una ventana de 5 h llena costó ~$126 de lista en esta PC el 2026-10-01». Con eso el ahorro en % sería `C_est / 126` como **cota alta**, porque la capacidad real es mayor si otras superficies gastaron.
  - Rotularlo «estimación con un solo punto de calibración».
  - Que el propio panel lo retire si E11 la refuta.
- **Recalibración automática sin red:** cada nuevo rechazo de los transcripts (E4) es otro punto de calibración gratis. El panel puede enseñar «n puntos de calibración; dispersión X %» y no mostrar el % hasta que n ≥ 3 y la dispersión < 25 %. Es un control que puede fallar.

---

## Fuentes (consultadas el 2026-10-06)

- Precios de la API: https://platform.claude.com/docs/en/about-claude/pricing
- Statusline (JSON, `rate_limits`, `cost`, `prompt_cache`): https://code.claude.com/docs/en/statusline
- Costes de Claude Code (`/usage`, relecturas de caché, TTL de 1 h en suscripción, atribución por MCP, `modelPricing`): https://code.claude.com/docs/en/costs
- Plan Max: https://support.claude.com/en/articles/11049741-what-is-the-max-plan
- Límites compartidos entre superficies: https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work
- Claude Code con Pro/Max: https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan
- ccusage, bloques de 5 h: https://ccusage.com/guide/blocks-reports
- Issue de contribución por sesión (cerrado «not planned»): https://github.com/anthropics/claude-code/issues/29721
- Cabeceras `anthropic-ratelimit-unified-*` (comunidad): https://github.com/anomalyco/opencode/pull/49651 y https://github.com/charmbracelet/crush/pull/3870
- Help center, «Usage limit best practices» (la caché «counts less»): https://support.claude.com/en/articles/9797557-usage-limit-best-practices
- HN, cambio de límites del 14 de septiembre: https://news.ycombinator.com/item?id=49491631 · anuncio de los límites semanales: https://news.ycombinator.com/item?id=44713757
- Issues de anthropics/claude-code: #75408 (el % es de la última respuesta), #52326 y #31820 (valores erróneos), #85964 (sin cubos por modelo), #51406, #29721. Están en https://github.com/anthropics/claude-code/issues/<n>
- Claude-Code-Usage-Monitor: https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor
- Blogs descartados por no tener dato primario: https://www.truefoundry.com/blog/claude-code-limits-explained, https://wmedia.es/en/tips/claude-code-usage-limits-5-hour-weekly, https://www.morphllm.com/claude-code-usage-limits, https://tokensforgood.ai/claude-code-usage-limits
- YouTube (no transcritos): https://www.youtube.com/shorts/Og8y_dS7ieA, https://www.youtube.com/shorts/nlUYz_028sE
- Binario local: `%USERPROFILE%\.local\bin\claude.exe` (2.1.291); `~/.claude/statusline.ps1`; `~/Documents/claude.omp.json`.
- Locales: `src/local_delegate/server.py:453-643`, `src/local_delegate/web/metrics.py:206,391,1197-1222,1672-1734`, `src/local_delegate/config.py:351`, `tests/test_metrics.py:648`, `docs/wiki/Savings-and-metrics.md`, vault `projects/local-delegate/backlog.md` §4.1 y §5.
- Scripts de medición (solo lectura, en el scratchpad): `scripts/n_relecturas2.py`, `scripts/relecturas.py`, `scripts/relecturas_read.py`.

## Llamadas a `local-delegate`

3 llamadas:
- `local_summarize(path=docs/wiki/Savings-and-metrics.md)`.
- `local_summarize(path=vault backlog.md)`: la §4.1 la leí luego literal con `sed`, porque el resumen la dejaba en una lista sin detalle.
- `local_extract(path=página del statusline guardada)`: devolvió JSON no parseable y truncado. Los campos los verifiqué después con `Grep` literal.

No usé `local_explain_code`: `_accounting` es corta y había que citar sus líneas.

En la ampliación no hubo llamadas `local_*` nuevas. Los transcripts los procesé con scripts de Python de solo lectura que devuelven agregados, así que su contenido nunca entró al contexto. Las páginas web las resumió WebFetch.
