# Specification: Panel: coste equivalente a precio de API y % de cuota sin calibrar

Versión 2 (2026-10-06): reescrita tras `review.md` (3 bloqueantes, 9 importantes), la ampliación del
brief (vigilante semanal, densidad por modelo y contenido) y las «Decisiones del usuario
(2026-10-06)». Versión 2.1 (mismo día): corrige la «Segunda pasada» (6 importantes y 6 menores) con
las decisiones de la sesión principal. Las respuestas punto por punto están al final de
`review.md`.

## Summary

El panel enseña cuánto habría costado, a precio de lista de la API de Anthropic, el contexto que
las delegaciones evitaron meter en Claude: **«Equivalente estimado a precio de API: entre $X y
~$Y»**. Cada delegación se valora con **el modelo, el hilo y el esfuerzo de quien la pidió**, no con
un modelo supuesto para todo; cuando falta el dato, un respaldo declarado lo cubre y una barra de
cobertura dice cuántas delegaciones van con dato real y cuántas con supuesto. Los caracteres se
pasan a tokens de Claude con una **densidad por familia de tokenizador y tipo de contenido**, no con
`chars/4`. La tabla de precios viaja en el paquete y un **vigilante semanal del CI** abre un PR cuando
cambia la página oficial. Al lado, un bloque de cuota que dice **«sin calibrar»** hasta que un
criterio escrito aquí, antes de mirar los datos, diga lo contrario, y que vuelve solo a «sin
calibrar» si la calibración deriva.

Nada de esto es dinero ahorrado ni un trozo de cuota medido: la suscripción es de tarifa plana y
Anthropic no publica la cuota en tokens. El panel no lo afirma nunca.

Evidencia: `research.md` y los insumos `viabilidad-cuota.md`, `densidad-por-modelo.md` y
`atribucion-modelo-esfuerzo.md`. **Toda cifra de esta spec sale de un script de solo lectura
guardado en `insumos/scripts/`**, citado junto a ella; los scripts devuelven solo agregados. Las
que leen transcripts son reproducibles mientras estos existan (Claude Code los borra a los 30 días).

## Dependencia: el contrato con `panel-cuentas-y-estados-honestos`

Este cambio **consume** el contrato que fija la spec hermana (sección «Contrato con
`coste-api-y-cuota`», REQ-007 y REQ-008) **tal cual**, y no lo redefine:

- **Campos por evento** de `_accounting` / `acct`: `chars_saved_text` / `charsSavedText`
  (caracteres), `bytes_saved_image` / `bytesSavedImage` (**bytes**), `chars_saved_output` /
  `charsSavedOutput` (caracteres), `chars_returned` / `charsReturned` (caracteres), `saved`,
  `returned`, `net` (tokens de Claude), `failed`, `tool`, `model`, `source`, `unit`.
- **Función única de conversión**: `tokens_claude(cantidad: int, *, tipo: str, evento: dict) -> int`
  en `server.py` y `tokensClaude(cantidad, tipo, e)` en el JS del panel, con `tipo` ∈ {`"text"`,
  `"returned"`, `"output"`, `"image"`}. Este cambio **sustituye su cuerpo** (REQ-031) y no toca su
  firma ni quién la llama. El hermano dice que `evento` es «la fila cruda del log»; aquí es esa
  misma fila **fundida** con el relleno y la densidad resuelta (REQ-006, REQ-033): un superconjunto
  de claves que se añade en el mismo lector de Python, así que la firma no cambia.
- Los dos cambios salen en la **misma versión** (lo exige el hermano): ninguna release publica
  tokens de Claude calculados con `chars ÷ 4`.
- Las cifras **en caracteres** del escenario de septiembre del hermano no cambian. Las cifras
  **en tokens** (bruto 873 270, devuelto 72 342, neto 800 928) sí cambian con la función nueva: las
  documenta este cambio en su verificación (REQ-036), no se editan en la spec hermana.

Orden de implementación: primero el hermano, luego este. Ningún requisito que use el contrato se
puede verificar antes.

## Definiciones

- **Delegación atribuible**: una línea del log de uso de una tool `local_*` que salió bien
  (`failed` falso), según el contrato.
- **Hilo** de una delegación: el transcript donde está su `tool_use`: el principal
  (`<sesión>.jsonl`) o el de un subagente (`<sesión>/subagents/agent-<id>.jsonl`).
- **Familia de tokenizador**: `nueva` (Claude 4.7 y posteriores) o `anterior` (Sonnet 4.6 y
  anteriores, Haiku 4.5), según la página oficial de precios. Sale del modelo de quien llamó.
- **Clase de contenido**: `prosa`, `codigo`, `log`, `estructurado`, `diff` u `otro` (REQ-032).
- **`c`**: caracteres del fichero por token de Claude, de la tabla de densidad (REQ-030).
- **`T`** de un evento: tokens de Claude netos de texto =
  `tokens_claude(chars_saved_text, tipo="text", evento=e) − tokens_claude(chars_returned,
  tipo="returned", evento=e)`. Puede ser negativo. En una imagen vale 0 (REQ-038).
- **`P_w(m, hilo)`**: precio de escritura de caché de `m`: a 5 min en un subagente, a 1 h en el
  principal (medido en todos los transcripts: el principal escribe solo a 1 h y los subagentes solo
  a 5 min; `research.md` §1).
- **`P_r(m)`**: precio de lectura de caché de `m`.
- **`N`** y **caducidades** de una delegación: ver REQ-043.
- **`H`, plazo de borrado de los transcripts**: `cleanupPeriodDays` de `~/.claude/settings.json`,
  o 30 si no está o no es un entero positivo (enmienda 1). Lo leen el comando, que lo guarda en
  `coste-agregados.json`, y `doctor`, que ya lee ese fichero para los hooks; el panel lo toma del
  JSON (nunca de `~/.claude`, REQ-073) y, sin JSON, usa 30.
- **Punto de calibración**: un par (Δ% de una ventana, Δ$ a precio de lista en ese intervalo) de un
  tipo de ventana (`five_hour` o `seven_day`). Su **capacidad** es `C = Δ$ × 100 / Δ%`, en USD por
  ventana llena.

## Requirements

### A. Atribución por delegación: modelo, hilo y esfuerzo de quien llama

Lo que se sabe (`insumos/atribucion-modelo-esfuerzo.md`): Claude Code manda en cada `tools/call` el
`_meta["claudecode/toolUseId"]`, idéntico al `tool_use_id` de los hooks y del transcript. El hook
trae `agent_id`, `agent_type` y `effort`, pero **nunca** el modelo, que solo está en el transcript.

- **REQ-001 — `tool_use_id` en el log.** El middleware `clients.observar_cliente`
  (`clients.py:254`) lee `_meta["claudecode/toolUseId"]` de la petición y lo pone en un
  `ContextVar`, igual que hace hoy con el nombre del cliente. `_log_event` (`server.py:453`) lo
  escribe como `tool_use_id`. Si el cliente no lo manda (Codex, scripts), la línea no lleva el campo.
  Observar nunca rompe una tool: cualquier excepción se traga.
- **REQ-002 — hook `PreToolUse` nuevo.** Un script de `resources/hooks/`, solo stdlib, con matcher
  `mcp__local-delegate__.*`, escribe una nota corta `{tool_use_id, ts, agent_id, agent_type,
  effort, transcript_path}` en un fichero propio junto al de `hook_common.ruta_de_notas()` (el de
  `anotar_bloqueo`). `effort` sale del campo `effort.level` de la entrada del hook y **nunca** de la
  variable `CLAUDE_EFFORT` (se hereda del proceso padre: medido en el insumo, P1 b). El hook no
  imprime nada, sale con 0 y no bloquea. Lo instala `install` como los demás. Como el formato vive
  en dos sitios (hook y servidor), hay un test de ida y vuelta: escribe con el hook y lee con el
  servidor, como el de `_bloqueo_reciente` (`server.py:423`).
- **REQ-003 — resolución al escribir la línea.** `_log_event` busca la nota por `tool_use_id` (las
  de más de 10 min no cuentan) y escribe:
  - `caller_kind`: `subagent` si la nota trae `agent_id`, `main` si no;
  - `caller_agent_type`: el de la nota, solo en subagentes;
  - `caller_effort`: el `effort` de la nota; si falta y el modelo resuelto tiene
    `admite_esfuerzo: false` en la tabla (Haiku 4.5), `n/a`, que **no** cuenta como dato que falta;
  - `caller_model`: el `message.model` normalizado de la línea del transcript que trae ese
    `tool_use_id`. Se busca **solo** en el fichero que señala la nota (el del subagente si hay
    `agent_id`) y **solo** en sus últimos 256 KB, con un presupuesto de 50 ms. No se guarda nada
    más del transcript;
  - `caller_src`: `hook+transcript` si hay modelo, `hook` si hay nota pero no se encontró la línea
    (la carrera medida: en `PreToolUse` estaba escrita en 5 de 6 casos).

  Sin nota, la línea no lleva ningún campo `caller_*`. La línea nunca lleva el id de sesión.
- **REQ-004 — relleno a posteriori.** El comando del CLI (REQ-070) casa cada línea del log de los
  últimos `H` días (el plazo de borrado, «Definiciones») que no tenga `caller_model`, o a la que le falte `N`, con su `tool_use` en los
  transcripts:
  - si la línea tiene `tool_use_id`, el cruce es exacto;
  - si no, son candidatos los `tool_use` de la misma tool con el `ts` de la línea dentro de
    [`tool_use` − 1 s, `tool_result` + 2 s] (o `tool_use` + 15 min si falta el resultado). Con un
    candidato, casa. Con varios, **el único desempate** es el `path` igual (comparado en memoria,
    normalizado). Si sigue habiendo más de uno, la línea queda `ambigua`; con ninguno, `sin_cruce`.

  Medido con `insumos/scripts/atribucion_n.py` (del 2026-09-06 a las 14:30Z del 2026-10-06): de 229
  líneas de `claude-code`, 166 casan solas, 55 tras desempatar por `path`, 7 son ambiguas y 1 no
  aparece (**96,5 %** únicas). Las 40 de cliente `mcp` (scripts de medición) no aparecen.
- **REQ-005 — dónde queda el relleno.** El comando escribe, junto al log y por mes,
  `atribucion-AAAAMM.json`: una entrada por línea del log, con valores `caller_model`,
  `caller_kind`, `caller_effort`, `n`, `caducidades`, `cruce` (`exacto` | `ventana` |
  `ventana+path` | `ambiguo` | `sin_cruce`) y `banco` (el transcript está en una carpeta de proyecto
  cuyo nombre contiene `Temp`: bancos y pruebas). Sin ids de sesión, sin rutas ni texto. Una entrada
  existente no se borra nunca; se sustituye solo por una de cruce mejor (`exacto` > `ventana` =
  `ventana+path` > `ambiguo` = `sin_cruce`).

  **Clave de la entrada**, que tiene que ser única por línea:
  - si la línea tiene `tool_use_id` (REQ-001), la clave es ese id;
  - si no (el histórico), `(ts, tool, ordinal)`, donde `ordinal` es la posición de la línea entre
    las de su misma `(ts, tool)` en el orden del fichero (0, 1, 2…). El log solo crece por el final,
    así que una línea nueva no cambia el ordinal de las anteriores.

  `(ts, tool)` sola **no** sirve: `ts` va en segundos (`server.py:488`) y dos subagentes llaman a la
  vez a la misma tool. Medido con `insumos/scripts/clave_relleno.py` sobre los 4 logs de esta PC
  (409 líneas, ninguna con `tool_use_id` todavía): `(ts, tool)` repite 3 claves (6 líneas);
  `(ts, tool, chars_in, chars_out)` repite 1 (2 líneas); `(ts, tool, ordinal)` **0**. Test: dos
  líneas del mismo segundo y la misma tool dan dos entradas distintas, y añadir una tercera no
  cambia las claves de las dos primeras.
- **REQ-006 — fusión al leer, en un solo sitio.** Al cargar el log, el código Python que hoy lo lee
  para `/api/stats` y `/api/events` funde en cada fila los campos de `atribucion-AAAAMM.json`. Por
  campo, el orden es único: **(1)** el valor de la línea del log; **(2)** el del relleno; **(3)** el
  respaldo (REQ-008). En el mismo paso se resuelve la densidad de la fila (REQ-033).
  `/api/events` entrega las filas ya fundidas y resueltas, así que el JS no funde ni resuelve nada.
- **REQ-007 — barra de cobertura.** Cada delegación atribuible cae en **un** tramo, en este orden de
  comprobación:
  1. `excluido`: el cliente está en la lista declarada de clientes que no son Claude
     (`codex-mcp-client` → «no es Claude») o de pruebas (`mcp` → «pruebas»), o el relleno la marcó
     `banco` (también «pruebas»: el rótulo dice «pruebas (scripts y bancos)»);
  2. `al momento`: la línea del log trae `caller_model`;
  3. `por relleno`: el relleno trae `caller_model`;
  4. `pendiente`: no hay modelo, la línea tiene menos de `H` días y no está marcada `ambiguo` ni
     `sin_cruce` (su transcript aún puede existir);
  5. `supuesto`: el resto.

  El panel muestra los cinco tramos con su número junto a la cifra en dólares. **Sin la barra no
  hay cifra.** Los tramos `pendiente` y `supuesto` se valoran con el respaldo; `excluido` no suma.
  Medido con `atribucion_n.py` sobre las delegaciones de texto por `path` de esa ventana: 149
  `por relleno`, 3 `supuesto`, 91 `excluido` (pruebas).
- **REQ-008 — respaldo declarado y visible.** Una delegación sin modelo se valora como
  **`claude-opus-5-5` en subagente**, el grupo más frecuente medido (135 de las 149 atribuidas;
  `atribucion_n.py`). Se puede cambiar con una variable de entorno leída con los helpers `_env*`
  (`modelo` o `modelo:main|subagent`; con solo `modelo`, el hilo es `subagent`, el declarado).
  Orden: variable > valor declarado. Un valor inválido no rompe
  el panel: se usa el declarado y el panel lo dice. El rótulo de la barra nombra el respaldo
  («3 de 152 con modelo supuesto: Opus 5.5 en subagente»).
- **REQ-009 — el esfuerzo se guarda y se enseña, pero no entra en la fórmula.** La entrada no
  depende del esfuerzo. Medido con `densidad.py` (Opus 5.5, el mismo diff): la tarea «ok» da
  **43 940** tokens de entrada sin flag, con `low` y con `high`; la tarea «resumen» da **43 938** en
  las seis llamadas, tres con `low` y tres con `high`. Dentro de cada tarea, cero de diferencia; así
  que no cambia `c` ni `T`. Puede cambiar `N`, pero hoy no se puede medir: las
  149 delegaciones atribuidas se pidieron todas con `high` (`atribucion_n.py`). El desglose del
  coste (REQ-047) agrupa por modelo, hilo **y esfuerzo**, para que el efecto se vea cuando haya datos
  con otros niveles.

### B. Tabla de precios

- **REQ-010 — la tabla.** El paquete incluye un recurso de datos con `fuente` (URL oficial),
  `consultado` (fecha del **último cambio** de la tabla; la pone el vigilante, REQ-021),
  `busqueda_web_por_1000` y, por id de modelo, entrada, escritura a 5 min, escritura a 1 h, lectura
  de caché y salida en USD/MTok, más `familia` (`nueva` | `anterior`) y `admite_esfuerzo`. A la
  fecha cubre los 13 ids de la página oficial que no están retirados (prototipo:
  `insumos/scripts/precios.json`): `claude-fable-5-1`, `claude-fable-5`, `claude-opus-5-5`,
  `claude-opus-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-opus-4-5`,
  `claude-sonnet-5-5`, `claude-sonnet-5`, `claude-sonnet-4-6`, `claude-sonnet-4-5`,
  `claude-haiku-4-5`. Los ids salen de las páginas oficiales «Models overview» y «Model IDs and
  versioning», no del nombre comercial.
- **REQ-011 — búsqueda por id exacto.** Antes de buscar se quitan el sufijo `[1m]` y el sufijo de
  fecha `-AAAAMMDD` (`claude-haiku-4-5-20251001` → `claude-haiku-4-5`). Después, la búsqueda es
  **exacta**: `claude-opus-5` no toma el precio de `claude-opus-5-5`, ni `claude-fable-5` el de
  `claude-fable-5-1`. Un id sin entrada da **«sin precio»**, nunca 0 ni el precio de un parecido.
- **REQ-012 — sin red en ejecución.** Ni la carga de la tabla ni `/api/stats` abren sockets hacia
  fuera.
- **REQ-013 — cotejo.** Una función pura recibe filas «modelo × sesión» con los totales de Claude
  Code (`inputTokens`, `cacheCreationInputTokens`, `cacheReadInputTokens`, `outputTokens`,
  `webSearchRequests`, `costUSD`) y devuelve por fila `dentro`, `fuera` o `sin_precio`. Una fila
  está **dentro** si su `costUSD` cae en [coste con toda la escritura a 5 min, coste con toda a 1 h]
  + búsqueda web, ± máx($0,005; 0,5 % de `costUSD`). Las filas con `costUSD` < $0,05 no se juzgan.
  El **veredicto** falla si hay al menos una fila `fuera` o `sin_precio`.
- **REQ-014 — cotejo sobre los datos reales.** El comando del CLI (REQ-070) aplica el cotejo a las
  líneas `cost-state` de los transcripts. Por clave `(sessionId, startTime)` toma **la última por
  posición en el fichero** (el total de una clave nunca baja en orden de aparición: 153 de 153
  claves, `cotejo.py`). Guarda fecha, versión de la tabla, filas juzgadas, `fuera` y los modelos
  `sin_precio`.

  Medido con `insumos/scripts/cotejo.py`, que implementa esta regla tal cual: **142 de 142** filas
  juzgables dentro, 0 fuera, 0 sin precio. Sin la búsqueda web salen 138 de 142: las 4 de Haiku que
  explica `research.md` §2. (El «108 de 108» de la versión anterior no se reproducía: el script de
  entonces no sumaba la búsqueda web y daba 104 de 108.)
- **REQ-015 — check de `doctor`.** No lee transcripts: lee el último cotejo guardado, el log de uso
  y los `atribucion-AAAAMM.json`. Se evalúa en este orden y gana la primera que se cumple:
  1. `warn` por **relleno pendiente** (REQ-075), se haya lanzado el comando alguna vez o no;
  2. `warn` si el último cotejo falló, nombrando los modelos;
  3. `ok` si el último cotejo pasó;
  4. `unknown` si no hay cotejo (máquina sin transcripts, comando nunca lanzado).

  Si se cumplen 1 y 2, el mensaje dice las dos cosas. Nunca `missing`. **No avisa por la edad de `consultado`**: con el vigilante
  semanal, esa fecha es la del último cambio de precios y puede ser vieja con la tabla al día. Lo
  que delata una tabla desfasada en esta máquina es el cotejo contra lo que cobra Claude Code.
- **REQ-016 — modelo sin precio, evento a evento.** Una delegación cuyo modelo (resuelto o de
  respaldo) no está en la tabla no suma dólares: se cuenta aparte, junto a la cifra («k delegaciones
  de modelos sin precio, fuera de la suma: `<ids>`»). Si **todas** quedan así, no hay cifra.

### C. Vigilante semanal de precios y límites (CI)

El patrón del repo es `.github/workflows/vendor-audit.yml`: workflow propio con cron, script de
solo stdlib en `scripts/`. No existen workflows llamados `vigilante-vendorizado` ni
`vigilante-captura-readme`, como decía el brief.

- **REQ-020 — workflow propio.** Un workflow con cron semanal y `workflow_dispatch`, que corre un
  script de `scripts/` (solo stdlib, sin instalar nada). Solo ese workflow tiene permisos de
  escritura: `contents: write`, `pull-requests: write` y **`actions: write`** (para lanzar los checks,
  REQ-025). La red se usa **solo** aquí.
- **REQ-021 — precios: un PR cuando cambian.** El script descarga la página oficial de precios,
  extrae la tabla «Model pricing» y la compara con la del paquete:
  - nombre comercial → id por una regla fija: «Claude ‹Familia› ‹X.Y›» → `claude-‹familia›-‹x›-‹y›`
    y «Claude ‹Familia› ‹X›» → `claude-‹familia›-‹x›`, quitando notas al pie (`<sup>…</sup>`) y
    paréntesis. La página de precios no trae ids, así que la deducción es inevitable; es la misma
    forma que documenta «Model IDs and versioning» (sin fecha desde la 4.6, y con la fecha quitada
    por REQ-011 antes). Si una deducción sale mal, el fallo es seguro: el id no casa, el evento sale
    «sin precio» y el cotejo lo caza (REQ-014, REQ-015). El PR lista los ids nuevos para revisarlos a
    mano. Las filas marcadas «retired» o «limited availability» se ignoran;
  - si algo cambia (un precio, un modelo nuevo, la búsqueda web), abre **un** PR (rama de nombre
    fijo; si ya está abierto, lo actualiza) con la tabla nueva y `consultado` = fecha del día;
  - un modelo que **desaparece** de la página no se borra de la tabla (los transcripts viejos lo
    siguen necesitando): el PR lo dice;
  - los commits del PR salen **firmados**: el ruleset de `main` lo exige y un `git commit` + `push`
    desde el runner queda `BLOCKED`. Se crean por la API de contenidos de GitHub, que firma los
    commits del bot. Los checks del PR los lanza el propio vigilante (REQ-025).
- **REQ-022 — falla en voz alta.** El job termina con error, y **no** como «sin cambios», si: la
  página no responde; no encuentra la cabecera de la tabla; extrae menos de 5 filas; o una celda
  de precio no se puede leer como número. Un parseo vacío nunca pasa por «sin cambios».
- **REQ-023 — límites: un aviso cuando cambia la página.** El mismo workflow descarga la página de
  ayuda de límites de uso
  (`https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work`), extrae
  el texto del artículo normalizado (sin HTML, espacios colapsados) y lo compara con el guardado en
  el repo. Si cambia, abre un PR que actualiza ese texto: el diff **es** el aviso, y el cuerpo dice
  cómo reiniciar la calibración a mano (REQ-057). Falla en voz alta si el texto extraído tiene menos
  de 500 caracteres o no aparece el título. Esto **sustituye** a la fecha de cambio de límites
  mantenida a mano: no hay campo `limites_cambiaron`.
- **REQ-024 — controles del vigilante, en la suite normal (sin red).** Con copias guardadas de las
  dos páginas en `tests/` (fixtures del test, que el vigilante **no** toca):
  - la de precios intacta da exactamente una tabla **esperada congelada en el propio test**, no la
    del paquete. Así el PR del vigilante, que cambia la tabla del paquete, no rompe el test;
  - la misma página con un precio alterado da un diff con ese precio frente a la esperada; con la
    cabecera de la tabla renombrada, el script falla;
  - la de límites: el test compara contra su propio texto esperado, no contra el texto guardado
    del repo que actualiza el PR de límites (REQ-023); con un párrafo cambiado da un diff, y
    vaciada, falla.
- **REQ-025 — los checks del PR del vigilante.** Un PR abierto con `GITHUB_TOKEN` no dispara los
  workflows de `pull_request`, pero `workflow_dispatch` sí se puede lanzar con ese token. El ruleset
  de `main` (`protect-main`, id 19859628; leído el 2026-10-06 con
  `gh api repos/ZahiriNatZuke/local-delegate/rulesets/19859628`, **no** con el endpoint de branch
  protection, que da 404) exige:
  - checks de estado `ci-gate`, `lint`, `test (ubuntu-latest)`, `test (macos-latest)` y `secrets`,
    que son jobs de `ci.yml` (`secrets` es gitleaks dentro de `ci.yml`, no una app externa);
  - el check `Analyze (python)`, job de `codeql.yml`;
  - la regla `code_scanning` de CodeQL (alertas `errors` y de seguridad `high_or_higher`);
  - rama al día con `main` (`strict_required_status_checks_policy`).

  Por eso, tras crear o actualizar su PR, el vigilante lanza por `workflow_dispatch` sobre la rama
  del PR **`ci.yml` y `codeql.yml`**, a los que este cambio añade ese disparador (no tienen
  condiciones que dependan del evento: comprobado con `grep`). Si `main` avanzó, antes actualiza la
  rama por la API («update branch»; el commit lo hace GitHub) y vuelve a lanzar los dos.

  Socket y GitGuardian **no** son checks requeridos por el ruleset: son apps externas que reciben el
  aviso del PR por su cuenta; si no informan, el PR no se bloquea por ellas.

  Queda una incógnita [I] que el plan comprueba con una ejecución real: si el análisis de CodeQL
  lanzado sobre la rama cumple la regla `code_scanning` del PR. Si el PR sigue `BLOCKED` por esa
  regla (o por `require_extra_approval_for_unattributed_changes` con commits del bot), el vigilante
  lo dice en un comentario del PR y la salida es cerrarlo y reabrirlo a mano: la reapertura por una
  persona dispara los workflows de `pull_request` con normalidad. En ese caso se le vuelve a llevar
  la decisión al usuario.

### D. Densidad: de caracteres a tokens de Claude

- **REQ-030 — la tabla de densidad.** El paquete incluye, junto a la de precios, una tabla de `c`
  por familia, columna (`sin_numerar` | `formato_read`) y clase, en **centésimas**, con la fecha de
  la medida. Valores medidos el 2026-10-06 (`insumos/densidad-por-modelo.md`, recalculables con
  `insumos/scripts/densidad.py`; prototipo en `insumos/scripts/densidad.json`):

  | Familia | Columna | prosa | codigo | log | estructurado | diff |
  |---|---|---:|---:|---:|---:|---:|
  | nueva | sin numerar | 2,23 | 2,41 | 1,92 | 1,88 | 2,22 |
  | nueva | formato `Read` | 2,00 | 2,03 | — | — | — |
  | anterior | sin numerar | 3,01 | 3,12 | 2,41 | 2,22 | 2,90 |
  | anterior | formato `Read` | — | — | — | — | — |

  Opus 5.5, Sonnet 5.5, Opus 5 y Fable 5.1 dan **el mismo número de tokens** en cada texto
  medido; Haiku 4.5 usa el tokenizador anterior. «—» es «sin medir». La tabla guarda con qué modelos
  se midió cada familia (`nueva`: esos cuatro; `anterior`: solo Haiku 4.5). Un evento de un modelo
  de la familia que no está en esa lista (Opus 4.5–4.8, Sonnet 4.5/4.6/5, Fable 5) lleva la marca
  `densidad de la familia`, que se cuenta en los supuestos (REQ-044).
- **REQ-031 — la función sustituta.** `tokens_claude(cantidad, *, tipo, evento)` devuelve
  `cantidad × 100 // c100`, con `c100` elegido así:
  - **familia**: la de `evento["caller_model"]` en la tabla de precios (ya fundido, REQ-006); sin
    modelo, la del respaldo (REQ-008); con un modelo que no está en la tabla, `nueva`, y el evento
    se marca `familia supuesta`;
  - `tipo="text"`: clase de la entrada (REQ-032); columna `formato_read` si `source == "path"`
    (lo que Claude habría leído con `Read`, que numera las líneas), `sin_numerar` si no;
  - `tipo="returned"`: lo que la tool devolvió a Claude no va numerado: columna `sin_numerar`,
    clase `estructurado` para `local_extract`, `codigo` para `local_boilerplate` y `prosa` para el
    resto;
  - `tipo="output"`: columna `sin_numerar`, clase `codigo` para `local_boilerplate` y `prosa` para
    el resto;
  - `tipo="image"`: **0**. El log guarda bytes, no dimensiones, y sin dimensiones no hay forma de
    saber los tokens de Claude de una imagen;
  - en un evento de imagen, **cualquier** `tipo` da 0, también `"returned"`: la imagen sale entera
    del neto (REQ-038).

  **Respaldo de celda**, en este orden y con un solo camino: (1) la celda exacta; (2) la misma
  clase en `sin_numerar`; (3) la mayor `c` de la columna `sin_numerar` de la familia (la que menos
  tokens da). (2) y (3) dan menos tokens que la celda real, nunca más, porque la numeración solo
  añade tokens. El evento lleva el origen: `medida`, `sin_numerar` o `conservadora`. Medido con
  `atribucion_n.py`: de 152 entradas de texto por `path`, 109 usan una celda medida y 43 el
  respaldo (2); ninguna el (3).
- **REQ-032 — clase de contenido, sin leer el texto.** Primero por la tool: `local_lint_summary`
  → `log`, `local_commit_msg` → `diff`, `local_explain_code` → `codigo`. Si no, por la extensión del
  `path` del evento (la lista es la de `atribucion_n.py`: `.md .txt .rst .html` → `prosa`; `.py .js
  .ts .ps1 .sh …` → `codigo`; `.json .jsonl .yaml .yml .toml .lock .csv .xml .ini` →
  `estructurado`; `.log` → `log`; `.diff .patch` → `diff`). Lo demás, `otro`, que no tiene celda y
  cae en el respaldo (3).
- **REQ-033 — un solo lugar de verdad: Python resuelve, los dos lenguajes solo dividen.** Las reglas
  de REQ-031 y REQ-032 (familia, respaldo de modelo con su variable de entorno, mapa de extensiones,
  columna y respaldo de celda) viven **solo** en una función de Python,
  `resolver_densidad(evento) -> dict`. La fusión de REQ-006 la aplica a cada fila y le añade:
  - `densidad`: `{"text": [c100, origen], "returned": [c100, origen], "output": [c100, origen]}`,
    con `null` en las tres si el evento es una imagen (REQ-038);
  - `familia`, y las marcas `familia supuesta` y `densidad de la familia` cuando apliquen.

  `tokens_claude` (Python) y `tokensClaude` (JS) hacen **lo mismo y nada más**: si `tipo` es
  `"image"` o `evento.densidad[tipo]` es `null`, 0; si no, Python `cantidad * 100 // c100` y JS
  `Math.floor(cantidad * 100 / c100)`. Los mensajes en vuelo de REQ-035 llaman a la misma
  `resolver_densidad` antes de convertir. Con enteros menores que 2⁵³ y `c100 ≤ 1000`, la división en
  coma flotante no puede cruzar un entero (la distancia de un cociente no entero al entero más
  cercano es ≥ 1/1000, y el error de redondeo es menor que 10⁻⁶ para cantidades de hasta 10⁹), así
  que los dos dan el mismo resultado. `/api/stats` sigue enseñando la tabla de densidad, pero solo
  para el bloque de supuestos: el JS no la usa para calcular.
- **REQ-034 — ningún `CHARS_PER_TOKEN` para tokens de Claude.** Usos de hoy, sacados con
  `grep -rn "CHARS_PER_TOKEN\|CPT" src/`, y qué pasa con cada uno:

  | Sitio | Qué cuenta hoy | Después |
  |---|---|---|
  | `config.py:351` `CHARS_PER_TOKEN = 4` | definición | se queda, **solo** para el modelo local |
  | `server.py:614`, `:616` (respaldo de `tokens_in`/`tokens_out`) | tokens del modelo **local** | sin cambio |
  | `server.py:621` (`saved`) | tokens de Claude | ya lo cambia el hermano a `tokens_claude` |
  | `server.py:367` (recibo de `_escribir_destino`, salida a fichero) | dice tokens de Claude | `tokens_claude(…, tipo="output")` (REQ-035) |
  | `server.py:1185-1195` (`_savings_feedback`, llamado en `:1317`, `:1617`, `:1950`, y por `local_describe_image` con `feedback_label="bytes imagen"`, `:2856`) | dice tokens de Claude, pero usa primero el `tokens_in` **local** | texto: `tokens_claude(…, tipo="text")`; imagen: solo los bytes, sin tokens; el `tokens_in` local no se presenta nunca como tokens de Claude (REQ-035) |
  | `server.py:2394` (`leido_server_side.tokens_aprox` de `local_extract`) | dice tokens a Claude | `tokens_claude(…, tipo="text")` |
  | `web/metrics.py:55` y `:414` (`chars_per_token` en `/api/stats`) | constante local | se queda con ese significado; `/api/stats` añade la tabla de densidad |
  | JS `metrics.py:1215` (`CPT = 4`) y `:1222` (`tok`) | respaldo local de `acct` | solo para el coste local; lo de Claude va por `tokensClaude` |
  | JS `metrics.py:1342` (pie: «~4 chars/token») | rótulo | dice «tokens de Claude por familia y tipo de contenido; modelo local ~4 chars/token» |
  | `server.py:1648` (comentario: 3,12 y 1,57 del tokenizador local) | documentación del local | sin cambio |

  El test de cadenas prohibidas (REQ-045) comprueba además que `CHARS_PER_TOKEN` no aparece en
  `tokens_claude` ni en los tres mensajes de REQ-035.
- **REQ-035 — los mensajes a Claude.** El recibo de salida a fichero, la coletilla de ahorro y
  `tokens_aprox` dicen los caracteres y «≈ N tokens de Claude», con N de `tokens_claude` sobre la
  fila en curso (con `caller_model` si la nota del hook ya está; si no, el respaldo). La coletilla de
  `local_describe_image` dice solo los bytes leídos server-side, sin ninguna cifra de tokens.
- **REQ-036 — el escenario de septiembre en tokens.** La verificación de este cambio recalcula el
  `usage-202609.jsonl` de esta PC con la función nueva (con relleno donde aún haya transcripts, y
  respaldo donde no) y deja en `verification.md` las cifras en tokens nuevas y la cobertura. Las de
  caracteres tienen que salir idénticas a las del hermano.
- **REQ-037 — paridad.** El test de paridad del hermano añade casos cuyo resultado cambia entre la
  regla de hoy (`÷ 4`) y la nueva: uno por familia, uno con `source == "path"` (formato `Read`) y
  otro inline, uno por cada respaldo de celda (2) y (3), una imagen con `chars_returned > 0` (todo
  0, REQ-038) y un modelo fuera de la tabla. Las filas de entrada pasan **antes** por la fusión de
  Python (REQ-006), como en producción. Guarda «esto comprobó algo»: entre los resultados hay al
  menos un evento de cada origen (`medida`, `sin_numerar`, `conservadora`), uno de cada familia y una
  imagen. Y un control de que el JS no tiene reglas propias: se cambia a mano el `c100` de
  `densidad.text` en una fila ya resuelta y **las dos** copias tienen que seguir el valor nuevo; si el
  JS resolviera por su cuenta, no lo seguiría y el test falla.
- **REQ-038 — las imágenes salen enteras del neto y se enseñan aparte.** Un evento de
  `local_describe_image` (unidad distinta de `chars`) aporta 0 a `saved`, `returned` y `net`: ni lo
  que leyó ni lo que devolvió a Claude entra en «Contexto conservado», así que una imagen no puede
  dar un neto negativo. Los campos en caracteres y bytes del contrato no cambian
  (`bytes_saved_image` y `chars_returned` siguen ahí). El panel y `/api/stats` enseñan un bloque
  aparte, «Imágenes»: número de imágenes, bytes leídos server-side (Σ `bytes_saved_image`) y
  caracteres devueltos a Claude (Σ `chars_returned` de esos eventos), sin ninguna cifra de tokens de
  Claude. Tampoco entran en el coste (REQ-040).

### E. Coste equivalente

- **REQ-040 — la base.** Entran las delegaciones atribuibles que no están `excluidas` (REQ-007) con
  `chars_saved_text > 0` o `chars_returned > 0` y unidad `chars`: su `T` (Definiciones). Quedan
  **fuera**, y se cuentan aparte con su número a la vista: las imágenes (REQ-038) y la salida a
  fichero (`chars_saved_output`), cuyo contrafactual es salida generada y no lectura.
- **REQ-041 — por evento.** Con `m` y `hilo` del evento (fundidos, REQ-006):
  - **cota baja** = `T × P_w(m, hilo)`: una sola escritura;
  - **estimación** = `T × (P_w(m, hilo) × (1 + cad) + (N − cad) × P_r(m))`, donde cada caducidad es
    una reescritura.

  El periodo suma los eventos. Un `T` negativo resta: lo devuelto también entró en caché.
- **REQ-042 — de dónde sale `N`, en un solo orden.** Por evento: **(1)** `n` y `caducidades` del
  relleno (REQ-005); **(2)** si no hay, la mediana de `N` de su grupo (`modelo`, `hilo`) en el último
  agregado guardado, si el grupo tiene al menos 10 casos, con `cad` = 0 (los agregados solo cuentan
  delegaciones no `excluidas`: ni clientes de pruebas ni bancos, como `atribucion_n.py`); **(3)** si no, el `N`
  declarado de su hilo, con `cad` = 0. No hay variable de entorno para `N`. Valores declarados,
  medidos con `atribucion_n.py`: **principal 127** (14 casos, todos de Opus 5) y **subagente 40**
  (135 casos, todos de Opus 5.5). El panel dice cuántos eventos usan cada origen.
- **REQ-043 — el algoritmo de `N`.** Dentro del hilo de la delegación:
  - una **petición** es una línea `assistant` cuyo `message.model` no es `<synthetic>`, contada una
    vez por `message.id` (con el `ts` de su primera aparición);
  - `t0` es el `ts` de la línea `user` con el `tool_result` de esa delegación (si falta, el de su
    `tool_use`);
  - **`N`** = peticiones del hilo con `ts > t0`, sin contar la que lleva el `tool_use`, y anteriores
    al primer `compact_boundary` posterior a `t0`;
  - una **caducidad** es un hueco mayor que el TTL del hilo (300 s en un subagente, 3 600 s en el
    principal) entre `t0` y la primera petición posterior, o entre dos posteriores seguidas;
  - los **percentiles** usan interpolación lineal entre rangos (la mediana de un número par de
    casos es la media de los dos centrales).

  Se prueba con un transcript sintético de `N` y caducidades conocidos de antemano, que incluye una
  línea `<synthetic>`, un `message.id` repetido y un `compact_boundary`.
- **REQ-044 — supuestos a la vista.** Junto a la cifra se ven siempre: la barra de cobertura
  (REQ-007) con el respaldo; el desglose de `N` por origen; la densidad por familia y su origen,
  con cuántos eventos llevan `densidad de la familia` o `familia supuesta`;
  «neto de la respuesta de la tool»; la fecha de la tabla de precios; el contrafactual («si Claude
  hubiera leído el fichero entero una vez con `Read`»); y **«no descuenta las relecturas del mismo
  fichero (medidas entre ~3 % y ~30 %)»** (`viabilidad-cuota.md:42`). El rótulo de la cota es
  **«cota baja con estos supuestos»**: bajo ellos lo es; si Claude hubiera releído el fichero, no.
  Sin este bloque no hay cifra.
- **REQ-045 — rótulo y frases prohibidas.** El rótulo es «Equivalente estimado a precio de API:
  entre $X y ~$Y», con la nota «no es dinero que hayas ahorrado: tu suscripción es de tarifa
  plana». Ni el panel, ni la API, ni los mensajes de la tool contienen «ahorraste $», «ahorro en
  dólares», «dinero ahorrado» (salvo en esa negación), «tokens de tu cuota», **«ahorro de cuota»** ni
  **«cuota que no gastaste»**. Este cambio reescribe los dos sitios donde están hoy:
  `web/metrics.py:805` (`<meta name="description">`: «Uso y ahorro de cuota…») y `:1199` («es cuota
  que no gastaste»). El hermano no los toca (su spec no los nombra); si al mezclar hubiera
  conflicto, gana este texto.
- **REQ-046 — cuándo no hay cifra.** Sin tabla cargable, sin barra, o con todas las delegaciones
  sin precio: el motivo, nunca $0. Un periodo sin delegaciones dice «sin delegaciones en el
  periodo».
- **REQ-047 — desglose.** Bajo la cifra, una tabla por (modelo, hilo, esfuerzo) con casos, `T`,
  cota baja y estimación. Es donde se ve que el grupo pesa más que el supuesto (REQ-048).
- **REQ-048 — cifra de referencia, para la verificación.** El cálculo del panel sobre una ventana
  tiene que dar **exactamente** lo mismo que `atribucion_n.py` corrido el mismo día sobre la misma
  ventana (mismas delegaciones, `T`, cota baja y estimación, al céntimo); cualquier diferencia es un
  defecto de uno de los dos. Como referencia, el 2026-10-06, en la ventana por defecto del script,
  la regla de esta spec da: `T` = 1,84 MTok netos (con `chars/4` serían 0,91);
  **cota baja $11,50, estimación $92,69**, de los que $62,20 son de Opus 5 en el hilo principal (14
  casos) y $30,49 de Opus 5.5 en subagente (135). La versión anterior de la spec (un solo supuesto,
  `N` = 49,5, `c` = 2,1 y 2,2) daba cota baja $8,28 y estimación $25,84 sobre los mismos eventos.
  Lo que más mueve la cifra es el
  hilo, por `N`, y el precio real de Opus 5: con el de Opus 5.5, ese grupo bajaría de $62,20 a
  $27,07. El insumo de atribución daba $38,51 porque supuso para Opus 5 el precio de Opus 5.5 y usó
  `chars/4`; `atribucion_n.py` reproduce ese $38,51 (y el $19,84 del supuesto viejo) con su filtro.

### F. Cuota: bloque «sin calibrar» y criterio de calibración

- **REQ-050 — estado por tipo de ventana.** El bloque tiene un estado por tipo (5 h y semanal):
  `sin calibrar` (por defecto) o `calibrado`. Ningún % mezcla los dos tipos.
- **REQ-051 — puntos de rechazo, solo de comprobación.** Cada rechazo de cuota de los transcripts
  (`quotaLimits` con `status: "rejected"`, en líneas `assistant` de modelo `<synthetic>`) da **un**
  punto por `(rateLimitType, resetsAt)`, aunque aparezca en varios transcripts. Intervalo: de
  `resetsAt − 5 h` (o `− 7 d`) al **primer** rechazo; Δ% = 100; Δ$ = coste a precio de lista de
  las peticiones de los transcripts en ese intervalo (una por `message.id`, con la escritura a 5 min
  y a 1 h separadas según `usage.cache_creation`). Lleva la marca **«cota baja»** y el número de
  peticiones sin precio. **No entra en la mediana ni en la dispersión**: el Δ$ de un rechazo recoge
  solo el 69–77 % del coste en sesiones grandes (`research.md` §3), un sesgo del orden del umbral.
  Medido con `insumos/scripts/calibracion.py`: 1 punto de 5 h (Δ$ = $125,71, 1 537 peticiones) y
  1 semanal ($397,68, 5 648), 0 peticiones sin precio.
- **REQ-052 — puntos del statusline, uno por ventana.** Del registro
  `~/.claude/cuota-statusline.jsonl` (campos `ts`, `session_id`, `model`, `five_hour`,
  `five_reset`, `seven_day`, `seven_reset`, `cost_usd` y, desde el 2026-10-06, `effort`, que es
  opcional: falta en 82 de las 144 filas de hoy):
  1. las filas se agrupan por tipo y por su reset (`five_reset` o `seven_reset`): **un grupo, como
     mucho un punto**;
  2. el par del punto es la primera y la última fila **de una misma sesión** dentro del grupo; si
     hay varias sesiones, la de mayor Δ%; con empate, la que empieza antes. Así el % de las dos
     filas viene de la misma sesión (las sesiones en paralelo tienen % desfasados, issue
     anthropics/claude-code#75408);
  3. Δ% < 10 puntos → descarte `delta_pequeno` (con % enteros, el error de resolución pasaría del
     10 %);
  4. Δ$ = suma, en **todas** las sesiones del registro, de los incrementos de `cost_usd` entre filas
     consecutivas de una misma sesión cuya fila **posterior** cae en (`t_a`, `t_b`]; el incremento
     se cuenta entero, también el que empezó antes de `t_a`. Si `cost_usd` baja (`/clear`), el
     incremento es el valor nuevo y el punto lleva la marca `reinicio`;
  5. Δ$ = 0 → descarte `sin_uso_local` (sube el % sin uso local: otra superficie);
  6. si en (`t_a`, `t_b`] hay peticiones en transcripts de sesiones que no están en el registro
     (`claude -p`, SDK), descarte `contaminado`: consumen cuota y su coste no está en `cost_usd`;
  7. todo punto lleva la marca **«cota baja si hubo uso en otras superficies»** (claude.ai, la Mac,
     Desktop), que no se puede detectar desde aquí.

  Medido con `calibracion.py --hasta 2026-10-06T15:00:30+00:00` (el registro crece en vivo; ese
  corte deja 144 filas, todas de una sola sesión): el grupo de 5 h da un par de Δ% = 47 y Δ$ =
  $61,26, descartado como `contaminado` (70 peticiones de las mediciones del día con `claude -p`,
  $8,17 a precio de lista); el semanal, Δ% = 1, `delta_pequeno`.
- **REQ-053 — ventanas que no se solapan.** Dos puntos del mismo tipo cuyos intervalos se solapan
  no son independientes: se queda el de mayor Δ% (con empate, el más reciente) y el otro se
  descarta como `solapado`.
- **REQ-054 — vigencia y saneado, aplicados al leer.** El panel (no solo el comando) descarta los
  puntos cuyo `fin` tiene más de **60 días**, y el comando descarta las filas con un % fuera de
  [0, 100] o no numérico. Cada descarte se cuenta por motivo.
- **REQ-055 — criterio, escrito antes de mirar.** Un tipo pasa a `calibrado` si y solo si, con los
  puntos **del statusline** vigentes en orden cronológico (por `fin`) y tras aplicar la deriva:
  (a) quedan **al menos 3**; y (b) su **dispersión es menor del 25 %**, con dispersión = mediana,
  sobre los puntos, de `|C_i − mediana(C_j≠i)| / mediana(C_j≠i)`. La capacidad usada es
  `mediana(C)` de esos mismos puntos. Implementación de referencia: `insumos/scripts/criterio.py`.
- **REQ-056 — deriva.** Se recorren los puntos en orden. Con un tramo vigente que empieza en `s`,
  hay deriva en el par de puntos consecutivos (j−1, j) si el tramo tiene al menos 3 puntos antes de
  j−1 y **los dos** se alejan más del 25 % de la mediana de esos puntos, **en el mismo sentido**.
  Entonces el tramo pasa a empezar en j−1: los anteriores dejan de contar y, como quedan menos de
  3, el tipo vuelve a `sin calibrar`. Un solo punto raro no es deriva (lo absorbe la dispersión),
  y dos raros en sentidos opuestos tampoco.
- **REQ-057 — reinicio a mano.** El comando acepta `--reiniciar-calibracion five_hour|seven_day`,
  que guarda la fecha; los puntos de ese tipo con `fin` anterior dejan de contar. Es lo que se
  hace cuando el vigilante de límites avisa (REQ-023).
- **REQ-058 — comprobación contra los rechazos.** Si un tipo sale `calibrado` y su `mediana(C)` es
  menor que la `C` de un punto de rechazo vigente del mismo tipo, el bloque muestra un aviso («la
  calibración da menos capacidad que un rechazo observado: probable uso en otras superficies»). No
  bloquea: los dos son cotas bajas por vías distintas.
- **REQ-059 — sin calibrar.** El bloque muestra estado, puntos del statusline vigentes, puntos de
  rechazo (como comprobación), dispersión si hay 2 o más, descartes por motivo, si hubo deriva o
  reinicio, y **qué falta** («faltan k puntos del statusline» o «dispersión X % ≥ 25 %»). **Ningún
  %** de cuota.
- **REQ-060 — calibrado: el periodo del %.** El % se calcula sobre una ventana móvil que termina
  ahora, **independiente del periodo que elija el panel**: A = cota baja de los eventos con `ts` en
  las últimas 5 h ÷ `mediana(C)` × 100, y B = estimación de esos eventos ÷ `mediana(C)` × 100 (en el
  semanal, los últimos 7 días). Rótulo: «≈ entre A % y B % de una ventana de 5 h (lo delegado en las
  últimas 5 h; la estimación incluye relecturas que pueden caer después de la ventana); estimación
  calibrada con n puntos (dispersión X %); supone que la cuota sigue al precio de lista».
- **REQ-061 — sin fuentes.** Sin registro del statusline (otras máquinas, la Mac), el bloque lo dice
  y no puede calibrar (REQ-055 a). Sin transcripts ni registro: «no hay datos de calibración en esta
  máquina». Un fichero ilegible o una línea corrupta se salta y cuenta como descarte; el panel no
  falla.

### G. Comando del CLI: recalcular bajo demanda

- **REQ-070 — un subcomando.** Lo lanza el usuario (nombre en el plan). Lee los transcripts de
  `~/.claude/projects`, el registro del statusline y el log de uso, y escribe en el directorio de
  logs de local-delegate: `coste-agregados.json` (cotejo, agregados de `N` por grupo sin
  delegaciones `excluidas`, puntos de calibración con descartes por motivo, reinicios) y los
  `atribucion-AAAAMM.json` (REQ-005).
- **REQ-071 — fundir, no sobrescribir.** Los puntos se funden con los del JSON anterior por clave
  `(fuente, tipo, inicio, fin)`: un punto cuyo transcript ya se borró sigue ahí hasta que su
  vigencia (REQ-054) lo deje fuera. Los agregados de `N` de un mes con más de 30 días no se
  recalculan.
- **REQ-072 — privacidad.** Ni `coste-agregados.json` ni los `atribucion-AAAAMM.json` contienen
  texto de conversaciones, rutas, ids de sesión ni prompts: solo números, fechas, ids de modelo,
  niveles de esfuerzo, nombres de motivo y, como clave del relleno, el `tool_use_id` o el `ts` y la
  tool de una línea del log, que ya están en el log de la máquina (REQ-005). `coste-agregados.json`
  no lleva ni eso. Un test lo comprueba con un transcript sintético que lleva una cadena marcadora en
  un prompt, en un `tool_result` y en una ruta.
- **REQ-073 — qué lee el daemon.** El daemon y el panel **no** leen `~/.claude/projects` ni el
  registro del statusline, con **una** excepción acotada: REQ-003 lee la cola (256 KB) del único
  transcript que señala la nota del hook, para sacar `message.model` de una línea, y no guarda nada
  más. Sin los JSON del comando, el panel usa el respaldo y el `N` declarado, y el bloque de cuota
  dice que no hay datos y cómo generarlos.
- **REQ-074 — idempotente y de solo lectura en `~/.claude`.** Lanzarlo dos veces seguidas con los
  mismos datos produce los mismos ficheros, salvo la fecha. Test: la lista de ficheros de un
  `~/.claude` sintético, con tamaño, fecha de modificación y hash, es idéntica antes y después.
- **REQ-075 — que no se pierda el histórico.** Los transcripts se borran a los `H` días, y con ellos
  la posibilidad de rellenar. El check de `doctor` (REQ-015, primera regla) da `warn` si existe
  `~/.claude/projects` y hay al menos una delegación `pendiente` (REQ-007) **con más de `H` − 10 días**,
  **se haya lanzado el comando alguna vez o no**: mira la pendiente más antigua, no la fecha del
  último relleno. Sin `~/.claude/projects`, no aplica.

## Acceptance scenarios

### Scenario: la tabla cuadra con lo que calcula Claude Code

- **Given** las líneas `cost-state` de esta PC
- **When** el usuario lanza el comando del CLI
- **Then** el cotejo guardado dice todas las juzgables dentro, 0 fuera y 0 sin precio, y `doctor` da
  `ok`; el número de filas y la fecha se anotan en `verification.md` (el 2026-10-06 eran 142 de
  142, `cotejo.py`)

### Scenario: el cotejo caza un modelo que falta y un precio equivocado

- **Given** el fixture del test: filas **literales** (números de `cost-state` reales reducidos a sus
  seis campos, congelados en el test, no calculados con la tabla)
- **When** se ejecuta el cotejo con la tabla sin `claude-opus-5`, con la lectura de Opus 5.5 ×0,8,
  y con la salida de Opus 5.5 ×0,8
- **Then** cada mutante falla **por el assert del veredicto**, nombrando `claude-opus-5` como
  `sin_precio` en el primero; y una guarda comprueba que con la tabla sin mutar el fixture sale
  `dentro`

### Scenario: delegación atribuida al momento

- **Given** un subagente Opus 5.5 con esfuerzo `low` que llama a `local_summarize` con `path`; el
  hook deja su nota y el transcript del subagente tiene la línea del `tool_use`
- **When** el servidor escribe la línea del log
- **Then** lleva `tool_use_id`, `caller_kind: subagent`, `caller_agent_type`, `caller_effort: low`,
  `caller_model: claude-opus-5-5` y `caller_src: hook+transcript`, y ningún id de sesión

### Scenario: la carrera del transcript queda pendiente y la cierra el relleno

- **Given** una línea con nota del hook pero sin la línea del transcript a tiempo
  (`caller_src: hook`)
- **When** se abre el panel y luego se lanza el comando
- **Then** primero cuenta como `pendiente` y se valora con el respaldo; después, como `por relleno`,
  con su modelo, `N` y caducidades

### Scenario: dos subagentes a la vez con la misma tool

- **Given** dos líneas del log sin `tool_use_id`, de la misma tool, dentro de la ventana de dos
  `tool_use` con `path` distintos
- **When** corre el relleno
- **Then** cada una casa con su `tool_use` por el `path`; si los dos `path` fueran iguales, las dos
  quedan `ambiguo` y van a `supuesto`

### Scenario: una imagen no resta del neto

- **Given** el evento de imagen del hermano: `{"tool":"local_describe_image","source":"path",
  "chars_in":250000,"chars_out":800,"ok":true,"tokens_in":1200,"tokens_out":200}`
- **When** se contabiliza con `_accounting` y con `acct` (tras la fusión de REQ-006)
- **Then** `bytes_saved_image = 250000` y `chars_returned = 800` (contrato, sin cambio), pero
  `saved = returned = net = 0`; el bloque «Imágenes» dice 1 imagen, 250 000 bytes y 800 caracteres
  devueltos; y la imagen no aparece en «Ahorro por herramienta» con un neto negativo

### Scenario: el JS sigue a Python

- **Given** una fila ya fundida y resuelta de prosa por `path` (`densidad.text = [200, "medida"]`)
- **When** se le cambia a mano `densidad.text` a `[250, "medida"]` y se contabiliza con las dos
  copias
- **Then** las dos dan `saved = chars_saved_text × 100 // 250`; si el JS resolviera la densidad por
  su cuenta, seguiría dando `÷ 200` y el test falla

### Scenario: coste por evento con supuestos a la vista

- **Given** un evento de prosa por `path` de 1 000 000 de caracteres, sin devuelto, de Opus 5.5 en
  subagente, con `N` = 40 y 0 caducidades
- **When** se pide `/api/stats`
- **Then** `T` = 1 000 000 × 100 // 200 = 500 000 tokens, la cota baja es 500 000 × $5/MTok =
  **$2,50** y la estimación 500 000 × ($5 + 40 × $0,20)/MTok = **$6,50** (`criterio.py`); y la
  respuesta trae la cobertura, la densidad con su origen, `N` con su origen y la fecha de la tabla

### Scenario: el mismo fichero con Haiku da menos tokens

- **Given** un evento de un `.py` por `path` con `caller_model: claude-haiku-4-5`, y el mismo con
  `claude-opus-5-5`
- **When** se contabilizan
- **Then** el de Opus 5.5 usa `c` = 2,03 (familia nueva, formato `Read`, origen `medida`) y el de
  Haiku `c` = 3,12 (familia anterior: su formato `Read` está sin medir, así que usa el respaldo (2),
  origen `sin_numerar`)

### Scenario: un modelo sin precio no da $0

- **Given** un evento con `caller_model` que no está en la tabla y otro de Opus 5.5
- **When** se abre el panel
- **Then** la cifra suma solo el de Opus 5.5 y dice «1 delegación de un modelo sin precio, fuera de
  la suma»; si los dos fueran sin precio, no hay cifra y sí el motivo

### Scenario: el vigilante abre un PR o falla, pero nunca calla

- **Given** la copia guardada de la página de precios
- **When** se corre el script del vigilante contra ella intacta, con un precio cambiado y con la
  cabecera de la tabla renombrada
- **Then** intacta: la tabla esperada congelada en el test; con el precio cambiado: un diff con ese
  precio; con la cabecera renombrada: sale con error. Y el test sigue verde en el propio PR del
  vigilante, que cambia la tabla del paquete pero no los fixtures

### Scenario: con menos de tres puntos del statusline, la cuota está sin calibrar

- **Given** los datos reales de esta PC el día de la verificación
- **When** se lanza el comando y se abre el panel
- **Then** cada tipo con menos de 3 puntos del statusline vigentes sale `sin calibrar`, sin ningún
  %, y dice cuántos puntos tiene, cuántos de rechazo hay como comprobación, sus descartes por motivo
  y cuántos faltan. Los conteos de ese día se anotan en `verification.md` (el 2026-10-06, con
  `calibracion.py`, eran 0 vigentes en los dos tipos: un descarte `contaminado` en 5 h y uno
  `delta_pequeno` en el semanal)

### Scenario: varias filas de una ventana son un solo punto

- **Given** una sesión con cinco filas en una sola ventana de 5 h (10 %, 20 %, 30 %, 40 %, 50 %)
- **When** se extraen los puntos
- **Then** sale **un** punto, del par (10 %, 50 %), con Δ% = 40

### Scenario: la calibración se gana, aguanta un punto raro, deriva y se recupera

- **Given** capacidades del statusline en orden cronológico
- **When** se evalúa el criterio (`criterio.py`)
- **Then** {150, 160, 170, 175} sale `calibrado` (dispersión 7,8 %); con 300 añadido sigue
  `calibrado` (7,2 %); {100, 160, 250} sale `sin calibrar` (51,2 %); {150, 160, 170, 175, 230, 240}
  deriva y sale `sin calibrar` («faltan 1 puntos»); {150, 160, 170, 175, 230, 100} no deriva
  (sentidos opuestos) y sigue `calibrado`; y {150, 160, 170, 175, 230, 240, 235} vuelve a
  `calibrado` con mediana 235

### Scenario: los rechazos duplicados son un solo punto y no calibran

- **Given** 11 registros de rechazo de 5 h con el mismo `resetsAt` en el hilo principal y en
  subagentes
- **When** se extraen los puntos
- **Then** sale **un** punto de rechazo, marcado «cota baja» y «solo comprobación», y el tipo sigue
  `sin calibrar`

### Scenario: un punto viejo caduca aunque el JSON no se regenere

- **Given** un `coste-agregados.json` con tres puntos del statusline que dan `calibrado`, uno de
  ellos con `fin` hace 61 días
- **When** se abre el panel sin lanzar el comando
- **Then** el tipo sale `sin calibrar` («faltan 1 puntos del statusline»)

### Scenario: otra máquina sin datos

- **Given** un HOME sin `~/.claude/projects` ni registro del statusline (la Mac, un CI)
- **When** se abre el panel y se lanza `doctor`
- **Then** el bloque de cuota dice «no hay datos de calibración en esta máquina», el coste usa el
  respaldo y el `N` declarado con la barra entera en `supuesto` o `pendiente`, y el check da
  `unknown` (sin `~/.claude/projects` no aplica el aviso de relleno)

### Scenario: el comando nunca se lanzó y el histórico está a punto de perderse

- **Given** un HOME con `~/.claude/projects`, sin `coste-agregados.json` ni `atribucion-*.json`, y
  un log con delegaciones de `claude-code` sin `caller_model` de hace 21 días, con `H` = 30 (sin
  `cleanupPeriodDays`; con `H` = 90 el umbral es 80 días)
- **When** se lanza `doctor`
- **Then** el check da `warn` («hay delegaciones de hace más de `H` − 10 días sin rellenar: lanza
  `<comando>` antes de que Claude Code borre sus transcripts»), no `unknown`; con las mismas
  delegaciones de hace 10 días, da `unknown`

### Scenario: dos líneas del mismo segundo no comparten relleno

- **Given** dos líneas del log sin `tool_use_id`, con el mismo `ts` y la misma tool
- **When** corre el relleno, y después se añade al log una tercera línea igual
- **Then** hay dos entradas distintas, `(ts, tool, 0)` y `(ts, tool, 1)`, y tras añadir la tercera
  esas dos claves no cambian

### Scenario: los ficheros del comando no se llevan nada privado

- **Given** un transcript sintético con una cadena marcadora en un prompt, en un `tool_result` y en
  una ruta
- **When** se lanza el comando
- **Then** ni `coste-agregados.json` ni `atribucion-*.json` contienen la marcadora ni el id de
  sesión, y `coste-agregados.json` tampoco contiene el `tool_use_id`

## Edge cases and failure behavior

- **Carrera del transcript** (la línea aún no está escrita): `caller_src: hook`, tramo `pendiente`
  (REQ-003, REQ-007).
- **Claude Desktop (`via mcp-remote`)**: no tiene hooks. Sus 3 líneas de la ventana casaron por
  relleno (`atribucion_n.py`); si no casa, va a `supuesto`. No se sabe si `mcp-remote` reenvía
  `_meta` [N].
- **La Mac**: su daemon y su log son propios; hasta que tenga la versión nueva y sus transcripts, la
  barra sale en `supuesto`.
- **Modelo sin esfuerzo (Haiku)**: `n/a`, no cuenta como falta (REQ-003).
- **`/clear` a mitad de una ventana del statusline**: marca `reinicio` (REQ-052).
- **Sesiones en paralelo**: el par sale de una sola sesión (REQ-052).
- **Formatos de Claude Code cambiados** (`cost-state`, `quotaLimits`, `_meta`, campos del hook o
  del statusline): esas fuentes dan 0 puntos o 0 atribuciones y un motivo; `caller_src` degradado,
  nunca un dato falso ni una excepción en el panel.
- **Página oficial con otra forma**: el vigilante falla en voz alta (REQ-022).
- **Transcripts borrados a los `H` días**: los puntos guardados siguen vigentes hasta los 60 días
  (REQ-071, REQ-054); las delegaciones sin relleno pasan de `pendiente` a `supuesto`.
- **Periodo sin delegaciones**: «sin delegaciones en el periodo», no «$0,00».

## Controles: qué pueden dar distinto y quién produce sus insumos

| Control | Resultado que puede dar distinto (y por qué razón falla) | Insumo y quién lo produce |
|---|---|---|
| Cotejo real (REQ-014) | `sin_precio` si falta un modelo (medido: 39 filas quitando `claude-opus-5`); `fuera` si un precio está mal (lectura de Opus 5.5 ×0,8 → 37; salida ×0,8 → 33; escritura a 1 h ×0,8 → 75; lectura ×1,25 → 10; escritura a 5 min ×1,25 → 7; salida ×1,25 → 6). `cotejo.py` | Líneas `cost-state` (Claude Code); el resultado lo guarda el comando de REQ-070 |
| Test del cotejo (REQ-013) | sus tres mutantes fallan **por el assert del veredicto**; la guarda falla si el fixture no sale `dentro` sin mutar | Fixture literal: la tarea del plan que escribe el test |
| Vigilante (REQ-021 a REQ-024) | diff con un precio cambiado frente a la tabla congelada del test; error con la cabecera renombrada o la página de límites vacía | Copias guardadas de las dos páginas y sus tablas esperadas, en `tests/`: la tarea del plan que escribe el script |
| Checks del PR del vigilante (REQ-025) | el PR sale `BLOCKED` si falta alguno de los seis checks o la regla `code_scanning` | Una ejecución real por `workflow_dispatch` con un diff forzado: la tarea del plan del workflow |
| Atribución (REQ-001 a REQ-003) | sin `caller_model` si la nota o el transcript no están; test de ida y vuelta hook ↔ servidor | Hook y transcript sintéticos: la tarea del plan del hook |
| Relleno y `N` (REQ-004, REQ-043) | `N` distinto del conocido; `ambiguo` con dos `path` iguales | Transcript sintético de `N` conocido: la tarea del plan del comando |
| Paridad de densidad (REQ-037) | difiere si el JS conserva `÷ 4` o resuelve la densidad por su cuenta (no sigue un `c100` cambiado a mano); la guarda falla si falta un origen, una familia o la imagen | Casos que añade la tarea del plan a `test_metrics.py`, pasados por la fusión de Python |
| Imágenes fuera del neto (REQ-038) | `net` ≠ 0 en una imagen con `chars_returned > 0` | Evento de imagen del hermano |
| Clave del relleno (REQ-005) | dos líneas del mismo segundo y tool que comparten entrada, o claves que cambian al añadir una línea | Log sintético del test del comando; medida real en `clave_relleno.py` (0 repetidas) |
| Aviso de relleno (REQ-075) | `unknown` en vez de `warn` con pendientes de 21 días y el comando nunca lanzado | HOME sintético del test de `doctor` |
| Criterio de calibración (REQ-055/056) | `sin calibrar` hoy; gana, deriva y se recupera en los escenarios | Puntos: el comando de REQ-070 desde transcripts y el registro del statusline (`statusline.ps1` del usuario) |
| Vigencia al leer (REQ-054) | `sin calibrar` con un punto de 61 días sin regenerar el JSON | JSON sintético del test del panel |
| Privacidad (REQ-072) | falla si aparece la marcadora o el id de sesión, o el `tool_use_id` en `coste-agregados.json` | Transcript sintético del test del comando |
| Sin red (REQ-012) | falla si se abre un socket al cargar la tabla o pedir `/api/stats` | Test con los sockets bloqueados |
| Frases prohibidas (REQ-045) | falla si el HTML, el JS, la API o un mensaje de tool las contienen, o si `CHARS_PER_TOKEN` aparece en `tokens_claude` | El propio código |

**Puntos ciegos declarados del cotejo** (medidos con `cotejo.py`): una escritura a 1 h
**sobrevalorada** (×1,25 → 0 fuera) o una a 5 min infravalorada (×0,8 → 0) quedan dentro de la banda,
porque `cost-state` no separa los dos TTL. Y la entrada de Opus 5.5 ×1,25 tampoco se ve (0 fuera):
casi toda la entrada va por caché y su peso es despreciable.

## Non-functional requirements

- **Privacidad:** los transcripts los lee el comando que lanza el usuario, y deja solo agregados;
  el daemon, solo la cola de un transcript para un campo (REQ-073). Ninguna cifra o rótulo del panel
  cita contenido de conversaciones.
- **Rendimiento:** el panel no hace E/S sobre `~/.claude`. La resolución de REQ-003 tiene 50 ms de
  presupuesto y no retrasa la respuesta de la tool más que eso. El comando termina en segundos
  (`atribucion_n.py` tarda ~3 s sobre 425 transcripts); el plan fija el techo y lo mide.
- **Compatibilidad:** sin red en ejecución; Windows, macOS y Linux; sin dependencias nuevas. Solo se
  **añaden** claves al log y a `/api/stats`.
- **Operabilidad:** cada cifra declara su origen y su fecha; cada descarte, su motivo; cada
  delegación, su tramo de cobertura.

## Non-goals

- El experimento de cuánto pesa la lectura de caché en la cuota (E12): gasta un 5–15 % de una
  ventana y se corre con el usuario delante, en otro momento.
- Consultar la red **en ejecución**, o leer `modelPricing` de managed settings.
- Buscar el `tool_use_id` en transcripts recientes sin la nota del hook (el respaldo «sin hook» del
  insumo): lee transcripts sin saber cuál; lo cubre el relleno.
- Tokens de Claude de una imagen (sin dimensiones no se puede): las imágenes van aparte (REQ-038).
- Cuota por modelo (el statusline no la da: issue anthropics/claude-code#85964).
- Leer las cabeceras `anthropic-ratelimit-unified-*` o el endpoint `api/oauth/usage`: exigen el
  token OAuth del usuario.
- Corregir la densidad del modelo **local** (`chars/4` en el respaldo de `tokens_in/out`).
- Redefinir la cifra neta, la exclusión de fallos o los campos del contrato (son del hermano).
- Que el esfuerzo entre en la fórmula: se guarda para medirlo cuando haya datos con otros niveles.
- Publicar versión. Si una release lo incluye, toca CHANGELOG, README y `docs/wiki/`
  (`Savings-and-metrics.md` y la tabla del doctor).

## Decisiones confirmadas

Todas del 2026-10-06.

Del usuario, en el brief:
- «Contexto conservado» pasa a tokens reales de Claude aunque la cifra suba: REQ-031 (septiembre se
  recalcula en la verificación, REQ-036).
- Sin modelo supuesto para todo; atribución por delegación con respaldo declarado y visible:
  REQ-001 a REQ-008.
- Caducidad de 60 días: REQ-054. La deriva sustituye a la fecha mantenida a mano: REQ-056, REQ-023.

Del usuario, sobre la versión 2 de la spec:
- La cuota se calibra **solo con puntos del statusline**: hacen falta 3, de ventanas distintas, y
  los rechazos quedan como comprobación (sustituye a «al menos un punto del statusline»): REQ-051,
  REQ-052, REQ-053, REQ-055, REQ-058.
- Las imágenes cuentan 0 tokens de Claude en la cifra principal y se enseñan aparte: REQ-031,
  REQ-038.
- El relleno lo lanza el usuario con un comando y `doctor` avisa a los 20 días: REQ-070, REQ-075.
- El vigilante lanza los checks por `workflow_dispatch` sobre su PR: REQ-025.

De la sesión principal, en la segunda pasada:
- Las imágenes salen **enteras** del neto (tampoco su devuelto) y van en un bloque aparte: REQ-038.
- El vigilante lanza **todos** los checks que exige el ruleset (`ci.yml` y `codeql.yml`), con
  `actions: write`: REQ-020, REQ-025.
- El JS calcula igual que Python porque Python le manda la densidad ya resuelta por evento: REQ-033.
- Clave del relleno: `tool_use_id` o `(ts, tool, ordinal)`, con 0 repetidas medidas: REQ-005.
- El aviso de `doctor` salta también si el relleno no se lanzó nunca: REQ-015, REQ-075.
- El test del vigilante no depende de la tabla del paquete: REQ-024.

Aviso, no decisión: la cifra sube mucho respecto a la versión 1 (REQ-048: estimación $92,69 frente
a $25,84 en la misma ventana), sobre todo por Opus 5 en el hilo principal.

## Decisiones que necesitan al usuario

Ninguna abierta. Solo vuelve una si la ejecución real de REQ-025 muestra que el CodeQL lanzado por
`workflow_dispatch` no cumple la regla `code_scanning` del PR: entonces hay que elegir entre cerrar y
reabrir a mano cada PR del vigilante o un token de una GitHub App guardado como secreto.

## Traceability

| Requisito | Trabajo previsto | Evidencia de verificación |
|---|---|---|
| REQ-001–003 | Middleware, hook nuevo, resolución en `_log_event` | Test de ida y vuelta hook ↔ servidor; test con transcript sintético (con y sin la línea); test del presupuesto: con un transcript de 50 MB y la línea fuera de los últimos 256 KB, la lectura no pasa de 256 KB (contada con un espía sobre la lectura) y, con un reloj inyectado que agota los 50 ms, devuelve sin modelo (`caller_src: hook`); `tests/test_aislamiento_entorno.py`; prueba **instalada** con una sesión real de subagente |
| REQ-004–008 | Relleno, fusión y barra | Tests de cruce exacto, por ventana, por `path` y ambiguo; clave con ordinal (escenario del mismo segundo); fusión con su orden; barra con los cinco tramos; variable de respaldo inválida y con solo `modelo` |
| REQ-009, REQ-047 | Desglose por esfuerzo | Test con dos niveles en el log sintético |
| REQ-010–012 | Recurso de la tabla y su cargador | Test de normalización (`[1m]`, fecha) y de los pares Opus 5 / 5.5 y Fable 5 / 5.1; test con sockets bloqueados; tarea del plan que comprueba `admite_esfuerzo` de los modelos heredados en la página de cada modelo (hoy es un supuesto en `precios.json`) |
| REQ-013–016 | Cotejo, comando y `doctor` | Test con fixture literal y tres mutantes; `ok` / `warn` / `unknown` y la precedencia del aviso de relleno; ejecución en esta PC (todas dentro); tabla del doctor de la wiki al día (su guardián) |
| REQ-020–025 | Workflow y script del vigilante; `workflow_dispatch` en `ci.yml` y `codeql.yml` | Tests con las páginas guardadas y sus tablas congeladas (intacta, alterada, rota); una ejecución real con un diff forzado: el PR muestra los seis checks y la regla `code_scanning` se cumple (o se activa la salida de REQ-025) |
| REQ-030–038 | Tabla de densidad, `resolver_densidad`, `tokens_claude` sustituta y bloque de imágenes | Test de paridad con los casos de REQ-037, su guarda y el control del `c100` cambiado a mano; escenario de la imagen; septiembre recalculado en `verification.md` |
| REQ-040–048 | Cálculo en `/api/stats` y bloque del panel | Test del escenario de 1 000 000 chars ($2,50 / $6,50); test de `N` con transcript sintético; modelo sin precio; frases prohibidas; mock en `tests/test_captura.py` si hay endpoint nuevo; cifras de esta PC **idénticas** a las de `atribucion_n.py` corrido el mismo día |
| REQ-050–061 | Puntos, criterio, deriva y bloque de cuota | Tests: cinco filas = un punto; contaminado; `sin_uso_local`; solapado; caducidad al leer; escenarios de `criterio.py`; HOME vacío; panel en el navegador con los datos reales: `sin calibrar` |
| REQ-070–075 | Subcomando del CLI | Test de privacidad con marcadora; idempotencia; solo lectura (lista de ficheros con hash idéntica antes y después); fusión de puntos con un JSON previo; aviso de `doctor` con el comando nunca lanzado |

## Enmiendas posteriores a la aprobación

1. **Plazo de borrado leído, no fijo** (2026-10-06, tras la revisión del plan, bloqueante 1). El
   usuario subió `cleanupPeriodDays` a 90 ese mismo día. Con los 30 días cosidos, el comando dejaba
   sin rellenar líneas de 30 a 90 días cuyo transcript existe, y `doctor` daba un aviso de urgencia
   falso a los 20 días. Cambia: la definición nueva de `H`; REQ-004 (ventana del relleno), REQ-007
   (tramo `pendiente`), REQ-075 (aviso a `H` − 10 días; con `H` = 30 sigue siendo a los 20, como
   decidió el usuario) y el escenario de `doctor`. No cambia nada más; REQ-071 (meses de más de 30
   días no se recalculan) se queda: no pierde datos. Decisión de la sesión principal.
