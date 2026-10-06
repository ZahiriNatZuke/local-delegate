# Research: Panel: coste equivalente a precio de API y % de cuota sin calibrar

Fecha: **2026-10-06**. Convención: **[V]** verificado aquí (fuente oficial con fecha, `fichero:línea`
o medido con un script de solo lectura), **[I]** inferido, **[?]** no se sabe.

Insumo de partida: `insumos/viabilidad-cuota.md`. Esta research **no lo repite**: verifica lo que
ese documento da por bueno y afecta al diseño, y corrige lo que no aguantó.

**Scripts.** Los de la primera versión vivían en el scratchpad de una sesión y no todos se
conservaron; el del cotejo, además, no implementaba la regla de la spec. Desde la reescritura de la
spec, **toda cifra que la spec cita sale de un script guardado en `insumos/scripts/`** (solo lectura,
solo agregados, sin texto de conversaciones). Ver §0.

---

## 0. Actualización tras la revisión de la spec (2026-10-06)

| Script | Qué reproduce | Resultado |
|---|---|---|
| `cotejo.py` | Cotejo de la tabla con la regla de la spec (REQ-013/014) y sus mutantes | **142 de 142** juzgables dentro (sin búsqueda web, 138: las 4 de Haiku). Mutantes: quitar `claude-opus-5` → 39 sin precio; lectura de Opus 5.5 ×0,8 → 37 fuera, ×1,25 → 10; salida ×0,8 → 33, ×1,25 → 6; escritura a 5 min ×1,25 → 7, ×0,8 → 0; escritura a 1 h ×0,8 → 75, ×1,25 → 0; entrada ×1,25 → 0 |
| `atribucion_n.py` | Cruce log ↔ transcript, `N` por grupo, densidad y coste por evento (ventana 2026-09-06 → 2026-10-06T14:30Z) | 96,5 % de las líneas de `claude-code` casan solas; `N` mediano: principal 127 (14 casos, Opus 5), subagente 40 (135, Opus 5.5); `T` = 1,84 MTok (0,91 con chars/4); cota baja $11,50, estimación $92,69. Reproduce el $38,51 y el $19,84 del insumo de atribución con su filtro |
| `calibracion.py` | Puntos de rechazo y del statusline con la regla nueva | Rechazos: 5 h $125,71, semana $397,68; statusline (corte 15:00:30Z): un par de 5 h contaminado, el semanal con Δ% = 1 |
| `criterio.py` | Dispersión, deriva y aritmética de los escenarios | Los números de los escenarios de la spec |
| `densidad.py` | La tabla de `insumos/densidad-por-modelo.md` desde `insumos/datos/densidad-resultados.jsonl` | Idéntica a la del insumo |

Correcciones a esta research que salen de ahí:

- **El 108 de 108 no se reproducía** (el script de entonces daba 104 de 108: no sumaba la búsqueda
  web, buscaba el modelo por prefijo y usaba otra tolerancia). Con la regla de la spec, hoy, sale
  **142 de 142**; los transcripts rotan, así que el número cambia de un día a otro.
- **Mutantes**: los conteos de §3 eran de otra regla y no decían qué modelo se mutaba. Los válidos
  son los de `cotejo.py` (mutando Opus 5.5). Un tercer punto ciego: la entrada de Opus 5.5 ×1,25 no
  se ve, porque casi toda la entrada va por caché.
- **Rechazos (§4)**: $125,71 y $397,68 con `calibracion.py` (una petición por `message.id`, tabla de
  `precios.json`), frente a $126,41 y $400,35 de `anclas.py`. La diferencia (~0,6 %) es de método; la
  spec ya no usa estas cifras como capacidad, solo como comprobación.
- **Densidad (§6)** queda sustituida por `insumos/densidad-por-modelo.md`: dos familias de
  tokenizador, cinco clases de contenido, y el formato de `Read` (numera las líneas) explica el 2,02
  de prosa medido aquí (sin numerar sale 2,23).
- **Modelo y hilo (§7)** quedan sustituidos por la atribución por delegación
  (`insumos/atribucion-modelo-esfuerzo.md` y `atribucion_n.py`). Las cifras «140 de 168» (§7) y
  «140 de 166» (`viabilidad-cuota.md`) eran de dos barridos distintos; la spec cita solo las de
  `atribucion_n.py`: 149 delegaciones de texto por `path` atribuidas (135 de Opus 5.5 en subagente
  y 14 de Opus 5 en el principal), 3 sin cruce y 91 de pruebas.
- **Precios (§2)**: los ids de todos los modelos salen ahora de «Models overview» y «Model IDs and
  versioning» (consultadas el 2026-10-06): `claude-fable-5-1`, `claude-sonnet-5-5`,
  `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-opus-4-5` (con fecha, que se
  normaliza), `claude-sonnet-4-6`, `claude-sonnet-4-5`. Prototipo en `insumos/scripts/precios.json`.
- **Statusline (§5)**: 144 filas al corte de las 15:00:30Z, de una sola sesión; `effort` (un objeto)
  falta en 82 y está en 62.
- **Usos de `CHARS_PER_TOKEN` (§8)**: `server.py:1189` y `:2394` **no** son tokens del modelo local:
  hablan a Claude. La clasificación completa está en la spec, REQ-034.

---

## 1. Lo que cambia respecto al insumo (resumen)

| Afirmación del insumo | Resultado aquí | Efecto en el diseño |
|---|---|---|
| Tabla de precios de 4 modelos | **Incompleta [V]**: faltan Opus 5, Fable 5 y Sonnet 5, que son justo los que más aparecen en los transcripts (Opus 5 es el modelo del hilo principal en 10 695 peticiones). Fable 5 lee caché a **$1**, no a $0,25 como Fable 5.1 | La tabla del paquete lleva todos los modelos vistos, y un modelo sin precio es un fallo del control |
| E10: «4 sesiones cuadran al céntimo, una difiere un 6 %, causa sin investigar» | **La causa es el método [V]**: el `usage` de los mensajes del transcript **no** cubre todo lo que Claude Code factura (ver §3). Contra los totales de `cost-state` la tabla cuadra en **142 de 142** filas (`cotejo.py`, §0; el «108 de 108» de antes no se reproducía) | El control se hace contra `cost-state.modelUsage`, nunca contra la suma de mensajes |
| Anclas de E5: 5 h ≈ $126, semana ≈ $400 | **Reproducidas** ($126,41 y $400,35, todo Opus 5.5) **pero sesgadas a la baja [V]**: salen de sumar mensajes del transcript, que en sesiones de Opus 5.5 recogen entre el 69 y el 77 % del coste que Claude Code calcula | Son cotas bajas por dos vías (otras superficies y transcript incompleto). No sirven solas para calibrar |
| ~2,2 chars/token (E8, con ruido) | **Confirmado con lectura controlada [V]**: 1,94–2,15 chars de fichero por token de Claude (Opus 5.5), según el contenido | chars/4 **subestima ~1,9–2,1×** los tokens de Claude |
| Subagentes escriben caché a 5 min, hilo principal a 1 h (E2, una ventana) | **Confirmado en todos los transcripts [V]**: principal 59,5 M tokens a 1 h y 0 a 5 min; subagentes 53,4 M a 5 min y 3 760 a 1 h | El TTL lo decide el hilo; la cota baja usa la escritura del hilo supuesto |
| Rechazos guardados en los transcripts (E4, 13 eventos) | **Confirmado, y son 2 ventanas, no 13 puntos [V]**: 11 registros con el mismo `resetsAt` (una ventana de 5 h) y 2 con el mismo `resetsAt` semanal, duplicados entre el hilo principal y los subagentes | Hay que deduplicar por `(rateLimitType, resetsAt)`: hoy hay **1 punto de cada tipo** |

---

## 2. Precios vigentes (fuente oficial)

**Fuente:** https://platform.claude.com/docs/en/about-claude/pricing — consultada el **2026-10-06**.
USD por millón de tokens (MTok).

| Modelo (id en transcripts) | Entrada | Escritura 5 min | Escritura 1 h | Lectura de caché | Salida |
|---|---|---|---|---|---|
| Claude Fable 5.1 | 10 | 12,50 | 20 | 0,25 (0,025×) | 50 |
| Claude Fable 5 (`claude-fable-5`) | 10 | 12,50 | 20 | **1** | 50 |
| Claude Opus 5.5 (`claude-opus-5-5`) | 4 | 5 | 8 | 0,20 (0,05×) | 20 |
| Claude Opus 5 (`claude-opus-5`) | 5 | 6,25 | 10 | 0,50 | 25 |
| Claude Opus 4.8 / 4.7 / 4.6 / 4.5 | 5 | 6,25 | 10 | 0,50 | 25 |
| Claude Sonnet 5.5 | 2 | 2,50 | 4 | 0,20 | 10 |
| Claude Sonnet 5 (`claude-sonnet-5`) | 2 | 2,50 | 4 | 0,20 | 10 |
| Claude Sonnet 4.6 / 4.5 | 3 | 3,75 | 6 | 0,30 | 15 |
| Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) | 1 | 1,25 | 2 | 0,10 | 5 |

Modificadores oficiales que tocan al cálculo [V]:

- **Búsqueda web: $10 por 1 000 búsquedas** (`webSearchRequests`). Es la causa de las 4 filas que no
  cuadraban (todas de Haiku: 4, 2, 81 y 4 búsquedas; la diferencia es exactamente 1 céntimo por
  búsqueda).
- `inference_geo: "us"` multiplica por 1,1 y Claude Code lo aplica en su coste (doc de costes). En
  los transcripts de esta PC vale siempre `not_available`.
- Fast mode: Opus 5.5 a 8/40 y Opus 5 / 4.8 a 10/50; los multiplicadores de caché se aplican encima.
  En esta PC `speed` es `standard` o falta: **0 peticiones en fast**.
- «Claude 4.7 and later models … use a newer tokenizer … approximately 30 % more tokens for the
  same text». Sonnet 4.6 y anteriores (y Haiku 4.5) usan el anterior.
- Los ids de modelo llegan con sufijos que la tabla tiene que normalizar: `[1m]`
  (`claude-opus-5[1m]`) y fecha (`claude-haiku-4-5-20251001`).

## 3. Cómo calcula Claude Code su coste, y qué guardan los transcripts

**Oficial [V]** (code.claude.com/docs/en/costs y /statusline, consultadas el 2026-10-06):

- `cost.total_cost_usd`: «Estimated session cost in USD, computed client-side at list price unless a
  `modelPricing` table is in effect». Se reinicia a $0 con `/clear` (desde v2.1.211).
  `modelPricing` solo lo aceptan los *managed settings*; en esta PC no hay.
- Con residencia de datos aplica el 1,1×. Incluye todas las llamadas de la sesión.
- Los transcripts se borran a los `cleanupPeriodDays` (30 por defecto). El más antiguo que queda es
  del 2026-09-03.

**Medido [V]:**

- Cada transcript escribe líneas `type: "cost-state"` con `sessionId`, `startTime`, `totalCostUSD`,
  `hasUnknownModelCost` y `modelUsage` por modelo (`inputTokens`, `outputTokens`,
  `cacheReadInputTokens`, `cacheCreationInputTokens`, `thinkingTokens`, `webSearchRequests`,
  `costUSD`). **157 líneas en 104 transcripts.** `modelUsage` **no** separa la escritura de caché a
  5 min de la de 1 h.
- *(Cifras de esta viñeta y la siguiente sustituidas por las de `cotejo.py`, §0.)* **La tabla
  oficial cuadra con Claude Code** cuando se aplica a los totales de `modelUsage`: en 108
  de 108 filas (modelo × sesión con coste ≥ $0,05), el `costUSD` cae dentro de la banda
  [toda la escritura a 5 min, toda a 1 h] con la búsqueda web incluida. El precio de escritura
  implícito tiene mediana exactamente en el de 1 h (8 para Opus 5.5, 10 para Opus 5).
- **El control puede fallar, y se midió cuánto** (perturbando un precio y contando filas fuera de la
  banda, sobre las mismas 108): modelo ausente → 33 filas sin precio; lectura ×0,8 → 69 fuera;
  lectura ×1,25 → 36; salida ×0,8 → 61; salida ×1,25 → 12; escritura 5 min ×1,25 → 11; entrada
  ×1,25 → 5. **Punto ciego:** no detecta una escritura a 1 h **sobrevalorada** (×1,25 → 0 fuera) ni
  una escritura a 5 min infravalorada, porque la banda las absorbe. Queda escrito como límite.
- **El `usage` de los mensajes del transcript no es el coste.** Comparando sumas de mensajes con
  `modelUsage` de la misma sesión (43 filas de ≥ $1): escritura de caché mediana 0,98; lectura de
  caché mediana 0,92 (p10 0,76); salida mediana 1,00 pero p10 0,22; entrada mediana 0,08. En las
  sesiones grandes de Opus 5.5 con muchos subagentes, el transcript recoge el **69–77 %** del coste
  (p. ej. $250 de $347). **[I]** Peticiones que no se escriben en el transcript (sugerencias de
  prompt, clasificador del modo auto, compactación) y la salida de los subagentes, que en el
  transcript queda con el valor del arranque del streaming (en este mismo hilo se ven
  `output_tokens` de 3 y 8). Consecuencia: **todo coste reconstruido sumando mensajes es una cota
  baja**.
- Fast mode y residencia no intervienen en esta PC (ver §2).

## 4. Rechazos de cuota en los transcripts

**Dónde están [V]:** en líneas `type: "assistant"` con `message.model = "<synthetic>"` e
`isApiErrorMessage: true`, dentro de la clave **`quotaLimits`**. Campos: `rateLimitType`
(`five_hour` | `seven_day`), `status` (`rejected`), `resetsAt` (epoch s), `overageStatus`,
`overageDisabledReason` (`out_of_credits`), `isUsingOverage`, `unifiedRateLimitFallbackAvailable`,
`upgradePaths` y, en 11 de 13, `lowPriority*`. **No traen porcentaje.**

**Cuántos hay [V]:** 13 registros en 11 transcripts, pero solo **dos ventanas**:

| Tipo | Registros | `resetsAt` (UTC) | Inicio supuesto | Primer rechazo | Coste de lista sumando mensajes |
|---|---|---|---|---|---|
| 5 h | 11 | 2026-10-01 02:30 | 2026-09-30 21:30 | 2026-10-01 01:14:41 | $126,41 (1 536 peticiones) |
| semana | 2 | 2026-10-04 09:00 | 2026-09-27 09:00 | 2026-10-01 18:41:10 | $400,35 (5 648 peticiones) |

Cada evento se duplica entre el transcript principal y el del subagente que lo sufrió: la clave de
un punto es `(rateLimitType, resetsAt)`. El «inicio supuesto» es `resetsAt − 5 h` o `− 7 d`.

Sesgos de un punto de rechazo, los dos **hacia abajo** del coste real de una ventana llena:
1. otras superficies (claude.ai, la Mac, Desktop) gastan la misma cuota y no salen aquí;
2. la suma de mensajes recoge ~70–92 % de lo que Claude Code cuenta (§3).

Y uno de vigencia: la cuota cambia por decisión comercial (HN 49491631, cambio del 14 de
septiembre). Un punto de antes de un cambio conocido no vale.

## 5. Registro del statusline (E11, activo desde el 2026-10-06)

**[V]** `~/.claude/cuota-statusline.jsonl`: 16 filas a las 14:08 UTC, todas con las claves
`ts, session_id, model, five_hour, five_reset, seven_day, seven_reset, cost_usd`. Porcentajes
**enteros**. El JSON crudo (`cuota-statusline-muestra.json`) trae además `prompt_cache`,
`context_window`, `fast_mode` y `rate_limits` con `five_hour` y `seven_day` solamente.

- La doc oficial muestra decimales en su ejemplo (`23.5`); esta PC entrega enteros. El lector tiene
  que aceptar los dos.
- Resolución: con enteros, el error de un Δ% entre dos lecturas es de hasta ±1 punto. Para que eso
  pese menos de un 10 %, el Δ% de un punto de calibración tiene que ser **≥ 10 puntos**.
- Solo escriben filas las sesiones interactivas que pintan statusline. `claude -p`, el SDK,
  Desktop, claude.ai y la Mac no aparecen.
- `cost_usd` es por sesión y vuelve a 0 con `/clear`: un Δ negativo es un reinicio, no un dato.
- Primer indicio, **no es un punto**: en 3 min la sesión subió de $15,39 a $17,39 y el 5 h pasó de
  18 a 19 %. Con la ancla de $126 serían ~1,6 %; la resolución entera no permite decir más.

## 6. Experimento: caracteres por token de Claude

> **Sustituido** por `insumos/densidad-por-modelo.md` (ver §0). Se conserva como historia del
> método: es la medida con `Read` que explica por qué existe la columna «formato `Read`».

**Pregunta:** ¿cuántos caracteres de fichero cuesta un token de Claude? El insumo da ~2,2 (E8, con
ruido conocido); el código usa 4 (`config.py:351`).

**Diseño, con el criterio escrito antes de medir** (el de E13 del insumo): se confirma si sale entre
1,8 y 2,6; se refuta si sale ≈ 4.

- Instrumento: este mismo hilo. Cada petición a la API deja en el transcript
  `input + cache_creation + cache_read`; la diferencia entre una petición y la siguiente es lo que
  entró entre ellas: el bloque `tool_use`, el `tool_result` y un recordatorio fijo de 105 chars.
- Una lectura con `Read` por mensaje, sin texto ni razonamiento antes de la llamada, con `offset` y
  `limit` para que el hook no bloquee y la deduplicación de Claude Code no devuelva «sin cambios».
- **Control del sobrecoste fijo:** dos lecturas de una línea, una antes y otra después de las
  grandes. La segunda (sin razonamiento previo) dio **195 tokens** con 111 chars de resultado, así
  que el sobrecoste por llamada es ~150 tokens (±50).
- Tres tipos de contenido de ~15 000 chars cada uno: prosa en español con tildes, prosa en español
  sin tildes con tablas, y Python. Los caracteres «de fichero» se cuentan como los cuenta el
  producto (`len` del texto, sin `\r`).

**Resultados [V]** (modelo `claude-opus-5-5`):

| Contenido | Chars de fichero | Chars que entregó `Read` (con números de línea) | Δ tokens | Chars de fichero por token | Chars de `Read` por token |
|---|---|---|---|---|---|
| Prosa ES con tildes (`salida-grande-va-a-fichero/research.md`, 283 líneas) | 15 070 | 16 093 | 7 613 | **2,02** | 2,16 |
| Prosa ES sin tildes, con tablas (`protocolo-f2.md`, 232 líneas) | 15 069 | 16 228 | 7 911 | **1,94** | 2,09 |
| Python (`server.py`, 355 líneas) | 15 027 | 16 801 | 7 155 | **2,15** | 2,40 |
| Lote de 8 lecturas en paralelo (mixto, con razonamiento previo) | ~82 300 | 87 911 | 40 883 | **2,07–2,10** | 2,21–2,24 |
| Dos lecturas del insumo (prosa ES; una con razonamiento previo) | 15 701 / 18 658 | 16 192 / 19 218 | 7 580 / 8 999 | 2,11 / 2,11 | 2,18 / 2,17 |

(Δ tokens neto = Δ − ~150 de sobrecoste; para el lote, − ~1 200 por las 8 llamadas y hasta ~400 de
razonamiento, de ahí el rango.)

**Veredicto: confirmado.** 1,94–2,15 chars de fichero por token, dentro de la banda de
confirmación y lejos de 4. Respecto a `chars // 4`, los tokens de Claude son **×1,86 a ×2,06**.

**Incertidumbre y límites:**
- ±50 tokens de sobrecoste sobre ~7 500 → ±0,7 % por medida. La variación entre contenidos (±5 %) pesa
  más que el error de medida.
- **Un solo tokenizador**: Opus 5.5 (familia 4.7+). Sonnet 4.6 y anteriores y Haiku 4.5 usan el
  anterior, con ~30 % menos tokens según la doc: **~2,7 chars/token [I]**, sin medir. De 168
  delegaciones con `path`, solo 1 la pidió Haiku.
- No se midió JSON, logs ni lockfiles, que son el mercado real del producto. El tokenizador local
  ya mostró que esa clase de contenido es mucho más densa (`server.py:1648`: 1,57 en `uv.lock`). La
  cifra puede ser peor para logs, no mejor.
- Lo que el producto cuenta son chars de fichero; lo que Claude habría pagado con `Read` incluye
  los números de línea (+6 a +12 % de tokens). Usar chars de fichero es la elección conservadora.

## 7. Qué modelo y qué hilo piden las delegaciones

> **Sustituido** por la atribución por delegación (ver §0): las cifras de esta tabla son de un
> barrido anterior y la spec ya no las cita.

**[V]** Delegaciones `local_*` con `path` en los transcripts que quedan, sin bancos de prueba:

| Modelo | Hilo | Delegaciones |
|---|---|---|
| `claude-opus-5-5` | subagente | **140** |
| `claude-opus-5` | principal | 21 |
| `claude-fable-5` | principal | 4 |
| `claude-sonnet-5` | principal / subagente | 1 / 1 |
| `claude-haiku-4-5-20251001` | subagente | 1 |

El log de uso no guarda el modelo de Claude (`server.py:453-574`). El supuesto por defecto que
menos se equivoca en esta PC es **Opus 5.5 en un subagente**: escritura a 5 min ($5) y lectura a
$0,20. **El supuesto cambia el resultado**: Opus 5 en el hilo principal escribe a $10 y lee a $0,50
(2× la cota baja, 2,5× las relecturas).

## 8. Current behavior (código)

- `_accounting` (`server.py:579-643`) es la única fuente de las cuentas. `saved = chars_in //
  CHARS_PER_TOKEN` solo si `source == "path"` y la unidad es `chars` (`server.py:618-625`). Las
  imágenes cuentan su token **local** (`:622-623`), y `output_to_file` suma `tokens_out` **locales**
  (`:630-631`).
- `CHARS_PER_TOKEN = 4` (`config.py:351`) se usa con **dos significados distintos**: tokens de
  Claude (`server.py:367` recibo de la salida a fichero, `:621` `saved`, `:1189` coletilla de
  ahorro de `_savings_feedback`, `:2394` `tokens_aprox`) y tokens del modelo **local** (`:614` y
  `:616`, respaldo cuando el backend no da `usage`). *(Corregido tras la revisión: la primera
  versión ponía `:1189` y `:2394` del lado local. Tabla completa en la spec, REQ-034.)* Para el local, el
  propio código documenta otras densidades (3,12 en prosa `.md`, 1,57 en `uv.lock`; `server.py:1648`).
- El panel recibe `chars_per_token` en `/api/stats` (`web/metrics.py:414`) y tiene un espejo JS de
  `_accounting` (`acct`, `web/metrics.py:1676`) atado por
  `tests/test_metrics.py:648` (`test_paridad_acct_entre_python_y_el_js_del_panel`).
- `docs/wiki/Savings-and-metrics.md` documenta «Contexto conservado» con `chars/4`.

## 9. Impact map

| Área | Responsabilidad hoy | Impacto esperado | Evidencia |
|---|---|---|---|
| `config.py` | `CHARS_PER_TOKEN = 4` para Claude y para el local | Separar la densidad de Claude (2,1 y su banda) de la del local, que no se toca | `config.py:351`; §6 |
| `server.py` `_accounting` | `saved` en chars/4 | Depende de la cifra neta del otro cambio; este aplica la densidad de Claude | `server.py:579-643` |
| `server.py:367` | Mensaje «≈N tokens que no entraron a tu contexto» | Con la densidad de Claude | `server.py:367` |
| `web/metrics.py` | `/api/stats`, espejo JS `acct`, KPIs | Bloque de coste equivalente y bloque de cuota; espejo y paridad | `metrics.py:206,391,414,1676` |
| Recurso nuevo en el paquete | — | Tabla de precios versionada (fuente, fecha, modelos, alias) | §2 |
| CLI | — | Un comando que lee transcripts **bajo demanda** y escribe solo agregados (cotejo de precios, N, puntos de calibración) | §3–§5 |
| `checks.py` / `doctor` | 21 checks | Edad de la tabla y resultado del último cotejo; la tabla del doctor en la wiki tiene guardián | `checks.py:5`; memoria «tres sitios» |
| `tests/test_captura.py` | Mock de los `/api/*` que pide la página | Endpoint nuevo → su mock | brief |
| Docs | wiki, README, CHANGELOG | `Savings-and-metrics.md` y la tabla del doctor | regla de la casa |

## 10. Existing conventions

- Cuentas en Python **y** en el espejo JS, con test de paridad que corre el JS con node.
- Opciones nuevas por los helpers `_env*` (guardianes en `tests/test_aislamiento_entorno.py`).
- Lo que corre el usuario va al CLI; lo que corre el repo, a `scripts/` (el wheel no empaqueta
  `scripts/`).
- `probe` del doctor nunca escribe; lo no comprobable es `unknown`, no `missing` (`checks.py:8-14`).
- Eventos con datos estimados se marcan (`estimated`); 0 antes que un número inventado
  (`server.py:625`).
- LF y CRLF mezclados por fichero: `server.py` es CRLF (3 170 de 3 170 líneas).

## 11. Dependencies and integrations

- **Cambio `panel-cuentas-y-estados-honestos`** (en especificación): define que los fallos no
  cuentan y la cifra **neta** (descuenta la respuesta de la tool). Este cambio la consume y le aplica
  la densidad de Claude. Ese brief deja fuera la corrección de chars/4 y la asigna aquí.
- **Claude Code** (externo): formato de `cost-state`, `quotaLimits` y del JSON del statusline. Nada
  de eso es una API estable: el lector tiene que degradar a «sin datos», nunca romper.
- **Statusline del usuario** (`~/.claude/statusline.ps1`, fuera del paquete): produce el registro.
  Solo existe en esta PC.
- **Sin red**: los precios viajan en el paquete; ninguna consulta en ejecución.

## 12. Respuestas a las preguntas abiertas del brief

> **Actualizado tras la revisión**: (1) `N` sale por evento del relleno, si no de la mediana de su
> grupo (modelo, hilo), si no del valor declarado de su hilo (spec REQ-042); (2) ya no hay un modelo
> supuesto para todo: cada delegación se atribuye y el supuesto es solo el respaldo visible (REQ-001
> a REQ-008); (3) la calibración vive en `coste-agregados.json` y la vigencia la aplica el panel al
> leer (REQ-054, REQ-071). El texto de abajo es el de la primera versión.

1. **¿N se calcula de los transcripts o se fija?** Las dos, en capas. El paquete trae un valor
   **declarado** con su origen (mediana 49,5 de E6, fecha 2026-10-06), que es lo que usa el panel
   si no hay nada más. Un comando del CLI, lanzado por el usuario, lo recalcula de sus transcripts
   y guarda **solo el agregado**. El daemon no lee transcripts nunca. Motivo: privacidad, coste en
   cada consulta del panel, y que en la Mac y en otras máquinas no hay transcripts útiles.
2. **¿Qué modelo se asume?** Por defecto **`claude-opus-5-5` en subagente** (140 de 168), configurable.
   El modelo y el hilo supuestos se enseñan siempre junto a la cifra. Cruzar cada evento con su
   transcript (modelo y N reales por evento) queda **fuera de la primera versión**: es la decisión
   que más complica el diseño y menos cambia el orden de magnitud. Ver decisiones del usuario.
3. **¿Dónde vive la calibración y qué hace el panel sin ella?** En un JSON de agregados que escribe
   el comando del CLI en el directorio de logs de local-delegate. Sin ese fichero, el panel dice
   «sin calibrar: no hay puntos en esta máquina» y no enseña ningún %.

## 13. Risks and unknowns

- **[V] Riesgo alto:** las anclas de $126 y $400 son cotas bajas por dos vías. Con un solo punto
  por tipo no hay forma de medir cuánto.
- **[?]** Si la cuota sigue al coste de lista. Depende de E11 (pasivo, en curso) y E12 (no se corre
  en este cambio).
- **[?]** Si las relecturas que cuenta N sobreviven a la limpieza automática de resultados viejos
  de tools: N sigue siendo una cota alta de las relecturas.
- **[I]** Los transcripts no registran todas las peticiones (§3). N cuenta peticiones del
  transcript, así que puede quedarse corto. Los dos sesgos van en sentidos opuestos y no se pueden
  separar con estos datos.
- **[V]** Formatos internos de Claude Code (`cost-state`, `quotaLimits`, statusline) sin contrato:
  cambian entre versiones (el campo `prompt_cache` es de la v2.1.251).
- **[V]** Densidad medida solo con el tokenizador nuevo y sin logs ni JSON.
- **[V]** El control de precios tiene un punto ciego (§3).

## Llamadas a `local-delegate`

*(Primera versión. Las de la reescritura constan en la «Respuesta a la revisión» de `review.md`.)*

1 llamada: `local_summarize(path=docs/wiki/Savings-and-metrics.md, focus=…)`, para saber qué
documenta hoy la wiki sin leerla. Útil: dio las cifras y su unidad.

Por qué no hubo más:
- El brief y el insumo los leí **literales**, por franjas: tenía que verificar cifras concretas y
  citarlas. Un resumen no servía para comprobar números.
- Los transcripts los procesaron scripts de Python de solo lectura que devuelven agregados: así su
  contenido no entra a ningún contexto, ni al mío ni al del modelo local.
- La página larga del statusline (63 KB) quedó en un fichero, y busqué los campos con `grep` en vez
  de resumirla, porque necesitaba el texto exacto de cada uno. El insumo ya registra que
  `local_extract` devolvió un JSON truncado con esa misma página.
- `_accounting` son 65 líneas que había que citar por línea: no tenía sentido pasarlas por
  `local_explain_code`.
- Las lecturas grandes del experimento **tenían** que entrar a mi contexto: eran el instrumento.
