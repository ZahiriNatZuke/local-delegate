# Revisión del gate `spec`: parámetros por rol en las peticiones al backend

Revisor adversarial. Fecha: 2026-10-20. Base: `main` en `f2dd267` (comprobado con
`git rev-parse`). Artefactos leídos: `brief.md` (decisiones 1–10), `spec.md` entero (por franjas) y
`research.md` (resumen con `local_summarize` y franjas con `grep`).

## Veredicto

**APROBABLE CON CAMBIOS.**

La spec cubre las diez decisiones del usuario y sus citas al código son casi todas exactas. Pero
tiene una contradicción interna (hallazgo 1) y un hueco de diseño (hallazgos 2 y 3) que, juntos,
hacen que el razonamiento en el rol `mechanical` falle o se apague en silencio. Hay que corregirlos
antes de aprobar. Son cambios de redacción y de un par de reglas, no de alcance. Ninguno obliga a
volver a investigar.

## Hallazgos

### 1. La temperatura del rol choca con «las claves del producto siempre ganan» — importante

- **REQ afectados**: REQ-010 y REQ-012 (también REQ-011).
- **Evidencia**: `server.py:2337-2345`. `_run_chat` mete `temperature` y `max_tokens` en el mismo
  `payload` que `messages` y `stream`. REQ-012 dice que los parámetros de rol se fusionan «por
  debajo de las claves del producto, que siempre ganan». Leído al pie de la letra, la temperatura de
  la tool gana siempre y REQ-010 no se cumple nunca. REQ-011, a su vez, cambia `max_tokens`, que
  también es una clave del producto.
- **Cambio propuesto**: en REQ-012, sustituir «por debajo de las claves del producto» por una regla
  de fusión explícita en tres capas:
  1. claves de contrato (`model`, `messages`, `stream`, `response_format`): las pone el producto y
     ganan siempre;
  2. `temperature`: la del rol, si existe, pisa la de la tool;
  3. `max_tokens`: el tope de la tool más el presupuesto (REQ-011).

  Añadir a la aceptación de REQ-012 un caso con `temperature` configurada en el rol que compruebe
  que el cuerpo lleva la del rol.

### 2. El presupuesto de razonamiento no tiene techo y desborda el contexto — bloqueante

- **REQ afectados**: REQ-011 y REQ-004 (rango de `reasoning_budget_tokens`).
- **Evidencia**:
  - `config.py:327-331`: `mechanical` admite 20 000 caracteres de entrada, `long` 48 000 y `code`
    20 000.
  - `config.py:488`: `CHUNK_MAX_TOKENS` vale 2048.
  - En `D:\Projects\llms\llama-swap\config.yaml`, `gemma3-4b` (el modelo de `mechanical`) corre con
    `--ctx-size 8192`, `qwen36-35b-a3b` con 16 384 y `gemma4-26b-a4b` con 38 400.
  - 20 000 caracteres son unos 5 000–7 000 tokens, y más 2048 de salida ya rozan los 8192. Un
    presupuesto de unos cientos de tokens basta para desbordar. REQ-004 acepta hasta 2³¹−1.
  - `failures.py:159-162`: el desborde de contexto llega como 400 (`REQUEST`).
- **Cambio propuesto**:
  - **(a)** Poner un techo absoluto al rango de REQ-004 (por ejemplo, 1–8192) y exigir que el
    presupuesto sea ≥ 1 cuando `enable_thinking` está encendido. Hoy un presupuesto de 0 cuenta
    como «presupuesto efectivo», y la decisión 9 no lo pretende.
  - **(b)** Con razonamiento encendido, rebajar el tope de entrada del troceado de ese rol en
    `presupuesto × caracteres por token`, con la misma estimación que ya usa el troceado. Así el
    total sigue cabiendo en el contexto.
  - **(c)** Si no se adopta (b), que `backend-params set` y `doctor`/`local_status` avisen (sin
    añadir un check) cuando `max_chars_for_role/≈3 + tope + presupuesto` supere el `ctx_size` del
    modelo del rol leído de la config de llama-swap (`llamaswap_config.py:246,365` ya lo parsea).
  - Aceptación: un test con `mechanical.reasoning_budget_tokens` alto y una entrada de 20 000
    caracteres que compruebe que cada trozo cabe (b) o que hay aviso (c).

### 3. El reintento sin parámetros oculta el desborde y duplica llamadas — bloqueante

- **REQ afectados**: REQ-015, junto con REQ-011, REQ-010 y REQ-018.
- **Evidencia**: `server.py:2031-2038` (reintento ante `http_400`). Según `failures.py:159-162`,
  el 400 incluye el desborde de contexto. Con el hallazgo 2, el primer intento con razonamiento da
  400 por desborde. REQ-015 reintenta sin parámetros de rol (por tanto, sin presupuesto y sin
  `enable_thinking`) y funciona. El usuario pidió razonar, la tool «funciona» sin razonar y lo único
  que queda es `backend_params_rejected: true`. Además:
  - en una operación troceada, **cada trozo** repite el par 400 → reintento, y se duplica el
    procesado del prompt, que es lo caro con entradas grandes;
  - la secuencia más larga es: con parámetros → sin parámetros → sin esquema (REQ-015 y
    `JSON_SCHEMA=auto`) → respaldo, y luego otra vez en el respaldo;
  - no se dice si el reintento conserva el `max_tokens` sumado;
  - si se descartan los parámetros, la temperatura vuelve a la de la tool y cambia el resultado
    respecto a lo configurado, sin que el panel lo distinga.
- **Cambio propuesto**:
  - **(a)** Que el primer 400 con parámetros marque la operación (en `_CurrentModel`, junto a los
    parámetros de REQ-012) y que los trozos siguientes vayan directamente sin parámetros. Cero
    reintentos repetidos por trozo.
  - **(b)** Que el reintento sin parámetros vuelva también al `max_tokens` de la tool. Decirlo.
  - **(c)** Que `backend_params` siga en el evento con los valores intentados, más
    `backend_params_rejected: true`, y que el panel pinte `paramschip` en estado «rechazado» (con
    su `title` del catálogo), para que no parezca que se aplicaron.
  - **(d)** Medir en la aceptación el número exacto de POST: un test con backend falso que cuente
    las llamadas en una operación de 3 trozos con 400 → debe haber 3 + 1, no 6.
  - Opcional: no reintentar sin parámetros si el texto del 400 indica desborde de contexto
    (`exceed`/`context`), y dejar que falle como `REQUEST` visible.

### 4. Un aviso podría arrastrar el valor crudo de la variable — importante

- **REQ afectados**: REQ-008 y REQ-006.
- **Evidencia**: REQ-008 manda copiar el patrón `(value, problem, raw)` de `output_language`
  (`config.py:448-462`), cuyo `raw` existe «para el aviso» (comentario en `config.py:451`). REQ-006
  prohíbe repetir valores en los avisos.
- **Cambio propuesto**: que REQ-008 diga que de `raw` solo se usan en avisos el rol y la clave de
  cada trozo, nunca el texto tras `=`. Que el test centinela de REQ-006 se aplique también a la
  variable: `code.foo=SENTINEL-7Q;code.top_k=SENTINEL-8R`.

### 5. Parseo del formato plano sin reglas para casos límite — importante

- **REQ afectado**: REQ-008.
- **Evidencia**: la spec dice «un trozo mal formado se quita sin arrastrar a los demás», sin decir
  qué es mal formado. No hay valores válidos con `;` ni `=`: la lista cerrada solo tiene números,
  booleanos y un enum.
- **Cambio propuesto**: fijar la gramática.
  - Separar por `;` e ignorar trozos vacíos (un `;` final no avisa).
  - Quitar espacios alrededor.
  - Separar por el **primer** `=` y luego por el **primer** `.`. Un trozo con un segundo `=`, sin
    `=` o sin `.` es mal formado.
  - Si una clave se repite para el mismo rol, gana la última y se avisa.
  - Los números se parsean con las reglas de `set`, y `on`/`off`/`true`/`false` igual que en `set`.
  - Aceptación: un test parametrizado con `a=b=c`, `code.top_k`, `top_k=1`, `;;`, una clave
    duplicada y `code.top_k=1e400` (da `inf` → se rechaza).

### 6. `ENVIRONMENT_VARIABLES` no se rellena solo — menor

- **REQ afectado**: REQ-008.
- **Evidencia**: `config.py:465-476`. Las variables que se leen al llamar entran en el inventario
  porque se llaman una vez al importar, en el bucle `for _reader in (...)`. El inventario se congela
  en `config.py:579`.
- **Cambio propuesto**: que REQ-008 diga que el lector nuevo se añade a ese bucle, o que el lector
  vive en `config.py` y no en `backend_params.py`. Si no, el test de pertenencia que ya pide la spec
  fallará por la razón correcta, pero conviene que la spec lo anticipe.

### 7. La caché por `mtime` debe incluir la identidad del fichero — menor

- **REQ afectado**: REQ-009.
- **Evidencia**: REQ-002 escribe con `mkstemp` + `os.replace`. En NTFS `st_mtime_ns` tiene una
  resolución de 100 ns, que basta. Pero en un recurso de red o en FAT (2 s), dos `set` seguidos con
  el mismo tamaño (`top_k 20` → `top_k 30`) dejan `mtime` y tamaño iguales. `os.replace` sí cambia
  el `st_ino` (el índice del fichero en NTFS).
- **Cambio propuesto**: invalidar por `(st_mtime_ns, st_size, st_ino)`, usar `st_mtime_ns` y no
  `st_mtime`, y añadir el test de dos `set` seguidos del mismo tamaño en el mismo proceso.

### 8. La comparación byte a byte es frágil tal como está escrita — importante

- **REQ afectado**: REQ-022.
- **Evidencia**: el cuerpo lo serializa httpx con `json=` (`server.py:1330-1339`). Bytes y orden
  de claves dependen de la versión de httpx (separadores, `ensure_ascii`). Los `messages` dependen
  del idioma vigente (`LOCAL_DELEGATE_OUTPUT_LANGUAGE`, `language.json`) y de los prompts, que se
  mueven en `main`. Los nombres de modelo y de respaldo dependen de la configuración. «El evento del
  log no gana campos» choca con los campos variables (`ts`, `ms`).
- **Cambio propuesto**:
  - Comparar el JSON parseado conservando el orden (`json.loads(..., object_pairs_hook=list)`) en
    lugar de los bytes. Fijar idioma, modelos y cadena de respaldo con los ayudantes `_env*` de
    `tests/conftest.py`.
  - Generar las fixtures con un script versionado (`scripts/…` o un `conftest` con una marca)
    ejecutado sobre `f2dd267`, y anotar en la fixture el commit de origen.
  - Para el log, comparar el **conjunto de claves** del evento, no sus valores.
  - Usar una imagen mínima para el camino de visión.
  - Mantener el control positivo de la estrategia de verificación (un mutante que añade una clave)
    y comprobar qué assert dispara.

### 9. Esquema de tools congelado contra un `main` que se mueve — menor

- **REQ afectado**: REQ-014.
- **Evidencia**: la lista fija se toma de `f2dd267`. Cualquier argumento nuevo y legítimo que se
  añada después a una tool hará fallar este test sin que tenga que ver con este cambio.
- **Cambio propuesto**: dos asserts.
  - **(a)** Una instantánea, con un mensaje de fallo que diga «si añadiste un argumento a propósito,
    actualiza la instantánea».
  - **(b)** Una guarda permanente e independiente de la instantánea: ningún parámetro de ninguna
    tool se llama como una clave del catálogo de REQ-004, una reservada de REQ-005, `role`,
    `backend_params`, `extra_body` ni `reasoning*`. La (b) es la que protege la decisión 5 a largo
    plazo.

### 10. La marca de «razonó» no ve todo el razonamiento — importante

- **REQ afectados**: REQ-018 y REQ-019 (decisión 7: «sobre todo, si razonó»).
- **Evidencia**: `reasoning_chars` solo suma `message.reasoning_content`. En cambio:
  - `_strip_think` (`server.py:1468-1476`) quita los bloques `<think>` del `content` de modelos que
    no separan el razonamiento;
  - `chars_out_raw` ya mide el texto antes de ese post-proceso (`docs/wiki/Savings-and-metrics.md:33`);
  - research §2 dice que en Qwen el exceso de razonamiento llega a `content` sin etiquetas.

  En esos casos la llamada razonó y el panel no lo marca.
- **Cambio propuesto**: que `reasoning_chars` sume también los caracteres que `_strip_think`
  quitó, sin guardar el texto. Que la wiki diga que el exceso sin etiquetas de Qwen no se puede
  contar. Aceptación: un backend falso que devuelve `<think>…</think>respuesta` sin
  `reasoning_content` da `reasoning_chars > 0`.

### 11. Panel: diálogo nuevo o el que ya existe, y accesibilidad de la fila — menor

- **REQ afectado**: REQ-019.
- **Evidencia**: ya hay dos `<dialog>`: `helpDlg` (`web/metrics.py:1758`) e `infoDlg` («help wide»,
  `:1776`, abierto en `:3223`). Las filas de `drawActivity` (`:3097`) hoy no se pueden pulsar.
- **Cambio propuesto**:
  - Que la spec decida si se reutiliza el patrón de `infoDlg` (estilos, cierre al pulsar fuera,
    `:3233`) o se crea un tercero.
  - Exigir que la fila se pueda activar con el teclado (`tabindex`, Enter) y que su `aria` salga
    del catálogo.
  - Decir que las marcas son iconos o etiquetas cortas del catálogo, sin frase. Las dos marcas son
    lo único nuevo en la fila, y el detalle va al diálogo, como piden las reglas del panel.
  - Las capturas en claro y oscuro deben incluir la fila **sin** marcas (formato viejo) junto a una
    con marcas.

### 12. Benchmark: el esfuerzo que fija el caso o el modelo no exige presupuesto — menor

- **REQ afectado**: REQ-020.
- **Evidencia**: `benchmark.py:1019-1028`. `effective_reasoning` da prioridad a
  `case.raw["reasoning_effort"]` y luego al del modelo. Hoy los corpus llevan `null` (90 casos en
  `benchmarks/*/cases.json`), pero el formato lo admite. REQ-020 solo habla de la opción
  `--reasoning-effort`.
- **Cambio propuesto**: que la exigencia de `--reasoning-budget` se aplique al esfuerzo
  **efectivo**, venga de donde venga. Aceptación: un caso con `reasoning_effort: "high"` y sin
  presupuesto termina con error.

### 13. `reasoning_effort` de producto sin efecto propio — menor (alcance)

- **REQ afectados**: REQ-004 y REQ-011.
- **Evidencia**: research §2 y la decisión 9 dicen que, solo, no enciende nada. Con
  `enable_thinking`, la spec lo manda en la raíz. En cambio, el benchmark de REQ-020 lo manda dentro
  de `chat_template_kwargs`, y la plantilla de llama.cpp lo lee de ahí.
- **Cambio propuesto**: alinear los dos caminos (producto y benchmark) en el mismo destino, o
  justificar en la spec por qué difieren. Si en la raíz no tiene efecto medible con los modelos del
  catálogo, valorar mandarlo dentro de `chat_template_kwargs` como en el benchmark. La prueba en
  vivo debería mostrar una diferencia entre `low` y `high` con `enable_thinking` encendido. Si no la
  hay, documentarlo.

### 14. Las citas de la cabecera de `doctor` apuntan a la función de idioma — menor

- **REQ afectado**: REQ-016.
- **Evidencia**: `doctor.py:48-66` es `language_lines()`, el modelo que hay que imitar, y no el
  sitio de la cabecera. La cita sirve como patrón.
- **Cambio propuesto**: decir «una función `backend_params_lines()` con el mismo patrón que
  `language_lines()` (`doctor.py:48-66`)».

## Alcance

- **Sobra un poco**: REQ-015 no lo pidió el usuario. Es una mitigación de research. Es razonable,
  pero solo si se acota como en el hallazgo 3. Si no, se vuelve el mayor riesgo del cambio.
- **Falta para la decisión 7**: que la marca «razonó» vea también el razonamiento entre etiquetas
  (hallazgo 10) y el estado «parámetros rechazados» (hallazgo 3c). El resto de la decisión 7 está
  cubierto: log con nombres y valores de la lista cerrada, marcas, diálogo de detalle, lectura del
  formato viejo y capturas en claro y oscuro.
- **Fidelidad a las decisiones 1–10**:

  | Decisión | Dónde la cubre la spec | Estado |
  | --- | --- | --- |
  | 1 | REQ-001 | Cubierta |
  | 2 | REQ-004 a REQ-007 | Cubierta. `chat_template_kwargs` en crudo pasa a reservada y solo se expone `enable_thinking`: es un estrechamiento coherente con la decisión 9 |
  | 3 | REQ-010 | Cubierta, salvo el hallazgo 1 |
  | 4 | REQ-003 y REQ-008 | Cubierta |
  | 5 | REQ-014 | Cubierta |
  | 6 | Prueba en vivo de la estrategia de verificación | Research ya respondió que `reasoning_effort` no vence a `--reasoning off`; la spec verifica `enable_thinking`. Correcto, pero conviene escribir en la spec que la decisión 6 queda respondida en negativo |
  | 7 | REQ-018 y REQ-019 | Cubierta, salvo el hallazgo 10 |
  | 8 | REQ-013 | Cubierta. `server.py:2387` ya anula el rol con `explicit` |
  | 9 | REQ-011 | Cubierta, salvo el hallazgo 2 |
  | 10 | REQ-020 | Cubierta, salvo el hallazgo 12 |

  Ningún REQ contradice una decisión.

## Verificabilidad

Casi todos los criterios de aceptación son tests concretos. Los que no:

- **REQ-021** («revisión del diff de los cuatro ficheros contra esta lista») es una revisión manual.
  Basta con que la haga el revisor del resultado con la lista de nueve puntos. Se acepta, pero
  añadiría un test barato en `tests/test_wiki.py` que compruebe que `Configuration.md` nombra
  `backend-params` y `LOCAL_DELEGATE_BACKEND_PARAMS`.
- **REQ-019** (capturas): verificable, pero conviene fijar el criterio de aceptación de cada
  captura:
  - la marca se ve y no se solapa;
  - el diálogo no tiene filas vacías;
  - el contraste es legible en los dos temas.
- **REQ-009**, la parte en vivo («sin `/mcp` ni reinicio»): verificable con la ventana de prueba y
  el log. Correcto.

## Pregunta abierta de la spec: el idioma de la documentación

**Opinión: mantener la lectura de la spec.** Lo comprobé: `docs/wiki/` (13 páginas), `README.md` y
`CHANGELOG.md` existen solo en español y no hay versión en inglés. El «es/en» del brief se cumple
con los textos para personas del catálogo i18n (REQ-017), igual que en el frente B. Traducir la
documentación aquí sería un cambio de política del repo, mezclado con un cambio de producto. Si el
usuario quiere la documentación bilingüe, debe ser un cambio aparte que traduzca todo, no solo esta
sección. Lo que sí pediría es que la ayuda de `backend-params --help` y los textos de `show` estén
en es/en (ya lo dice REQ-017). Conviene confirmarlo con el usuario al aprobar el gate, con una sola
pregunta de sí o no.

## Citas muestreadas

| # | Cita de la spec o de la trazabilidad | Qué afirma | Resultado |
| --- | --- | --- | --- |
| 1 | `server.py:2427` | `self.role = None` tras un salto | OK |
| 2 | `server.py:2032-2038` | Reintento sin esquema ante `http_400` | OK |
| 3 | `server.py:726` | `_log_event` | OK |
| 4 | `server.py:1354-1363` | `ChatResult` en `_post_chat` | OK |
| 5 | `server.py:4684,4694` | `local_delegate` con `role="mechanical"` | OK |
| 6 | `server.py:5526-5534` | Roles en `local_status` | OK |
| 7 | `server.py:2337-2347` | Construcción del `payload` | OK (y revela el hallazgo 1) |
| 8 | `server.py:4412` | `classify` con `max_tokens=16` | OK |
| 9 | `server.py:1468-1476` | `_strip_think` | OK |
| 10 | `config.py:448-476` | Patrón `(value, problem, raw)` de `output_language` | OK |
| 11 | `config.py:579` | `ENVIRONMENT_VARIABLES` | OK |
| 12 | `cli.py:460-476`, `:1389` | `_add_test_window_parser` y su registro | OK |
| 13 | `test_windows.py:268-322` | `mkstemp` + `os.replace` + `FileLock` | OK |
| 14 | `web/metrics.py:557-560` | Lectura de `test_windows` en el panel | OK |
| 15 | `web/metrics.py:3095-3131` | `drawActivity` | OK (empieza en 3097) |
| 16 | `web/metrics.py:1758,1776` | Diálogos existentes | OK |
| 17 | `web/metrics.py:517-541` | `/api/events` | OK |
| 18 | `doctor.py:48-66` | «Cabecera» de `doctor` | Parcial: es `language_lines()`, el patrón y no el sitio (hallazgo 14) |
| 19 | `failures.py:185-201` | Razonamiento que agota `max_tokens` da `CONFIGURATION` | OK |
| 20 | `failures.py:159-162` | 400 da `REQUEST`, incluido el desborde de contexto | OK |
| 21 | `tests/test_checks.py:93` | 25 checks | OK |
| 22 | `tests/test_benchmark.py:336-343` | Forma actual de `reasoning_kwargs` | OK |
| 23 | `tests/test_environment_isolation.py:155` | Guarda de la puerta `_read` | OK |
| 24 | `tests/test_i18n_parity.py:97,103,136` | Paridad, superficie y claves literales | OK |
| 25 | `tests/test_wiki.py:219,241` | Tabla y recuento del `doctor` en la wiki | OK |
| 26 | `tests/test_metrics.py:1570` | Test de `fbchip` | OK |
| 27 | `tests/test_dashboard_js.py:583` | URLs de `fetchData` | OK |
| 28 | `docs/wiki/Savings-and-metrics.md:33`, `README.md:196-221`, `CHANGELOG.md:7` | Sitios de la documentación | OK |

Resultado: 27 OK y 1 parcial, ninguna KO.

## Cambios exigidos para aprobar

1. Regla de fusión en tres capas en REQ-012 (hallazgo 1).
2. Techo y presupuesto ≥ 1 en REQ-004/REQ-011, y tope de entrada rebajado o aviso contra `ctx_size`
   (hallazgo 2).
3. REQ-015 acotado: una marca por operación, vuelta al `max_tokens` de la tool, estado «rechazado»
   visible y recuento de POST en la aceptación (hallazgo 3).
4. Avisos de la variable sin `raw` y gramática del formato plano (hallazgos 4 y 5).
5. REQ-022 con JSON ordenado, entorno fijado y claves del evento en lugar de bytes (hallazgo 8).
6. `reasoning_chars` que cuente también los `<think>` quitados (hallazgo 10).

Los menores (6, 7, 9, 11–14) pueden resolverse en el plan si el autor lo prefiere, siempre que
queden anotados.

## Evidencia recomendada para el gate si se aprueba

- `spec.md` revisada, con un diff que muestre los seis cambios exigidos.
- Respuesta del usuario a la pregunta del idioma de la documentación.
- En `state.json`, el gate `spec` aprobado con referencia a esta revisión. No lo edito yo: va por
  el flujo del harness.

## Segunda pasada (2026-10-20)

Revisé `spec.md` con 23 REQ y la sección «Cambios tras la revisión», más el brief con la decisión
11. Leí las franjas de REQ-004 a REQ-023, Trazabilidad y Preguntas abiertas.

### Veredicto: **APROBADO CON NOTAS**

- Los 14 hallazgos están resueltos **dentro de los REQ**, no solo anotados en la tabla final:
  - el 1 en REQ-012 (capas y test de `temperature`);
  - el 2 en REQ-004 (1–8192) y REQ-023;
  - el 3 en REQ-015 (una vez por operación, recuento 3 + 1, `max_tokens` y `temperature` de la
    tool) y REQ-019 (estado rechazado);
  - el 4, el 5 y el 6 en REQ-008;
  - el 7 en REQ-009;
  - el 8 en REQ-022;
  - el 9 en REQ-014;
  - el 10 en REQ-018;
  - el 11 en REQ-019;
  - el 12 y el 13 en REQ-020 y REQ-011;
  - el 14 en REQ-016.
- La decisión 11 está en REQ-021 y en Preguntas abiertas.
- Ningún REQ contradice el brief.
- REQ-012, REQ-015 y REQ-023 casan entre sí: REQ-011 nombra a REQ-015 y REQ-023 como las dos
  excepciones a la suma del presupuesto, y las dos vuelven al `max_tokens` de la tool.

No bloqueo por nada. Las notas S1 y S2 son defectos de redacción de REQ-023: arreglarlos cuesta
dos frases. Conviene hacerlo en la spec antes del gate del plan, o como mínimo que el plan los
recoja de forma explícita.

### Hallazgos nuevos

**S1. La relación de caracteres por token que cita REQ-023 no existe en el troceado — importante,
REQ-023.**

- **Evidencia**:
  - El troceado trabaja en caracteres (`MAX_CHARS_BY_ROLE`, `config.py:327-331`). La única
    relación del código es `CHARS_PER_TOKEN = 4` (`config.py:513`), que sirve para la contabilidad
    del log (`server.py:1030-1032`) y no para trocear.
  - Para código y español, 4 caracteres por token **se queda corto**: la densidad varía hasta el
    doble (memoria «presupuesto en chars, límite en tokens»).
  - Si se queda corto, REQ-023 cree que la llamada cabe, el backend desborda con un 400 y REQ-015
    quita **todos** los parámetros del resto de la operación, también los de muestreo. Queda
    visible (`backend_params_rejected`), pero es justo lo que REQ-023 quería evitar.
- **Cambio**:
  - Que REQ-023 nombre la fuente: `config.CHARS_PER_TOKEN` con un margen conservador explícito
    (por ejemplo, contar a 2,5 caracteres por token, o sumar un 25 %), o una constante propia con
    esa justificación.
  - Que la estimación cuente `system` + `user`, no solo la entrada.
  - Que la aceptación incluya una entrada densa (código) cerca del límite.
  - Así el plan no tiene que «localizar» algo que no está.

**S2. El test de control de REQ-023 no puede pasar tal como está escrito — importante, REQ-023.**

- **Evidencia**:
  - El primer test fija un presupuesto de 8192 y un `ctx_size` de 8192.
  - El control («con una entrada corta: la llamada sí lleva el razonamiento») no dice que cambie
    esos valores. Con ellos, cualquier entrada da
    `tokens + max_tokens_de_la_tool + 8192 > 8192`, y la llamada **nunca** lleva razonamiento.
  - Es la misma pregunta de «qué produce los insumos del control» de la regla de la casa.
- **Cambio**: que el control use un presupuesto de 512 con el mismo `ctx_size` de 8192, o un
  `ctx_size` mayor. Añadir el caso límite: una entrada que justo cabe y otra que pasa por un token
  según la estimación de S1.

**S3. Leer el `ctx_size` por modelo no es una función que ya exista — menor, nota para el plan.**

- **Evidencia**:
  - `llamaswap_config.py:246,365` parsea los flags dentro de la estimación de VRAM. No hay una
    función `ctx_size(model)`.
  - Leer la config necesita YAML, que es el extra `[llamaswap]` (`_require_yaml`, `:51`).
  - El nombre del rol tiene que casar con la clave del modelo en `config.yaml`.
  - En la Mac, que delega en el backend de la PC sin su config, siempre se usará 8192. Allí el rol
    `long` (`gemma4-26b-a4b`, 38 400 de contexto) se saltará el razonamiento con entradas
    medianas.
- **Para el plan**:
  - una función nueva con caché por `mtime`, la misma de REQ-009;
  - sin YAML o sin el modelo, 8192 y un aviso en `local_status`;
  - documentar lo de la Mac en el punto 8 de REQ-021.

**S4. REQ-023 no dice qué hacer con la visión — menor, nota para el plan.**

- **Evidencia**: la entrada de `local_describe_image` es una imagen. No se estima en caracteres.
- **Para el plan**: excluir el rol `vision` de la comprobación de REQ-023, con el riesgo
  documentado, o estimar la imagen con un número fijo de tokens. Decidirlo de forma explícita.

**S5. REQ-015: cuándo se marca el rechazo si el reintento sin parámetros también falla — menor,
nota para el plan.**

- **Evidencia**: si el reintento sin parámetros vuelve a dar 400, la causa no eran los
  parámetros. Aun así, la spec marca la operación como rechazada y el panel pinta «parámetros
  rechazados».
- **Para el plan**:
  - marcar `backend_params_rejected` y desactivar los parámetros en la operación **solo si** el
    reintento sin parámetros funcionó;
  - si también falló, seguir el flujo de hoy sin la marca.

**S6. La justificación del techo de 8192 exagera un poco — menor, solo redacción.**

- **Evidencia**: «Un presupuesto mayor no cabría con ninguna entrada útil en dos de los tres
  modelos». Es falso para `qwen36-35b-a3b`: 16 384 de contexto dejan sitio para 9 000 de
  presupuesto, 2048 de tope y unos 5 000 de entrada.
- **Cambio**: decir que el techo es una elección conservadora (el contexto del modelo menor), y que
  REQ-023 y el aviso de `set` cubren lo que no quepa. El valor 8192 me parece bien: coherente con el
  brief y con REQ-023.

### Comprobación de que REQ-023 se puede verificar

- Se puede verificar si se arreglan S1 y S2.
- El aviso de `set` (código 0 y fichero escrito) y el caso de `ctx_size` desconocido se pueden
  probar tal como están.
- `reasoning_skipped: "context"` y que la entrada no se recorte se pueden probar con el backend
  falso que ya pide la spec.

---

# Revisión del plan (gate `plan`, 2026-10-20)

Revisor adversarial. Fuentes: `brief.md` (decisiones 1–11 y reglas), `spec.md` (23 REQ, aprobada) y
`plan.md` (10 lotes, 19 tareas), todo leído entero. Contrastado con el código en `f2dd267`.

## Veredicto: **APROBADO CON NOTAS**

El plan es ejecutable y cubre los 23 REQ. La propiedad de ficheros es exclusiva por ola y el orden en
serie del embudo es correcto. Las reglas de ejecución están completas. No hay nada que lo haga
inviable. **Una condición**: enmendar el texto de REQ-012 (P1) **antes de lanzar C1**. Lo mejor es
hacerlo ya, porque la regla del propio plan («si choca con la spec, manda la spec») dejaría a la
sesión limpia ante una contradicción literal. Conviene meter en el plan P2–P6 antes de lanzar los
lotes afectados. El resto son notas.

## Comprobación de la desviación de REQ-012 (capa del rol en `_call_model`)

**Es correcta técnicamente.** Lo muestra el código:

- `_run_chat` arma el `payload` (`server.py:2337-2347`) **antes** de saber a qué modelo va. El
  destino real lo elige `call()`, dentro de `_with_fallback`: es `op.pick()` (`server.py:2196-2200`),
  que puede devolver el alternativo de la afinidad, o el destino de un salto (`:2268-2270`). Solo
  `_attempt` → `_call_model(target, …)` (`:2052`, `:2019`) recibe el modelo que de verdad se llama,
  y REQ-023 lo necesita para `model_context_size`.
- El `http_400` solo se ve en `_call_model` (`:2030-2040`), que ya hace ahí el reintento sin esquema.
  REQ-015 exige el reintento sin parámetros **antes** de ese, así que tiene que ir en el mismo sitio.
- Hay un precedente: `_call_model` ya deriva `request_body = {"model": model, **payload}`
  (`:2028`). Aplicar la capa 2 sobre una copia no muta el `payload` compartido entre intentos.

**Exige enmendar el texto de REQ-012.** La spec dice literalmente «El cuerpo de cada llamada real se
arma en `_run_chat` (`server.py:2337-2347`), por capas». Ver P1.

## Hallazgos

**P1 — Alta (condición antes de C1) — REQ-012, T10, §1 y §6 del plan.**
- **Evidencia**: arriba. El plan reconoce la desviación (§1 «Embudo», §6 primera fila), pero la deja
  a criterio de «la revisión». Su cabecera dice que, si choca con la spec, manda la spec. Una sesión
  limpia leería dos órdenes contrarias.
- **Cambio**:
  - enmendar REQ-012 en `spec.md`: «Las capas 1 (base de la tool) y 3 (contrato) las arma
    `_run_chat` (`server.py:2337-2347`) como hoy. La capa 2 (rol) se aplica en `_call_model`
    (`:2019`) sobre una copia del cuerpo, justo antes de `_post_chat`, porque solo ahí se conocen el
    modelo destino real (afinidad y respaldo, REQ-023) y el `http_400` (REQ-015)»;
  - anotarlo en «Cambios tras la revisión» de la spec;
  - quitar del plan el condicional de §1 («Si la revisión del plan lo considera desviación…») y la
    primera fila de §6, o dejarla como resuelta.

  No cambia ningún comportamiento ni aceptación: basta con una nota en el gate de la spec, sin
  revisión completa.

**P2 — Media — REQ-006 (aceptación huérfana en `show` y `doctor`), T8, T9.**
- **Evidencia**: REQ-006 exige que ningún centinela aparezca en el aviso, en `show`, en `doctor`, en
  `local_status` ni en el log.
  - `local_status` lo cubre `test_status_hides_sentinels` (T14), y el log
    `test_sentinels_never_in_log` (T13).
  - T9 **no tiene** test de centinelas, aunque la matriz cita «T8/T9».
  - El `test_messages_never_echo_value` de T8 cubre el valor de un `set` inválido, **no** `show`
    con un fichero o una variable que llevan `SENTINEL-7Q` y `SENTINEL-8R`.
- **Cambio**: añadir `test_show_hides_sentinels[file|env]` a T8 (texto y `--json`), y
  `test_doctor_hides_sentinels[file|env]` a T9.

**P3 — Media — REQ-017 (aceptación huérfana), T3 y T5.**
- **Evidencia**: REQ-017 pide «un test que recorre los avisos en `es` y en `en` con los centinelas de
  REQ-006». `test_override_warnings_never_carry_values` (T3) no fija el idioma. Los tests de T5
  comprueban que el texto existe y qué marcadores lleva, pero no lo renderizan con centinelas.
- **Cambio**: en T5, `test_rendered_warnings_hide_sentinels[es|en]`. Recorre **todos** los códigos
  con `warning_text()` y entradas que contienen los centinelas, con `LOCAL_DELEGATE_LANG` fijado
  por `reload_config`.

**P4 — Media — REQ-011 (aceptación a medias), T6 y T10.**
- **Evidencia**: REQ-011 pide, por fichero y por variable con `enable_thinking` sin presupuesto, que
  «**el cuerpo** no lleva `chat_template_kwargs` y hay aviso». T6
  (`test_thinking_without_budget_from_file_and_env_is_dropped`) lo prueba sobre `effective()`, no
  sobre el cuerpo, y ningún test de T10 lo prueba. Además, la spec rechaza el
  «`unset`/`reset` del presupuesto»: T6 implementa el `reset` (paso 4), pero solo prueba el `unset`.
- **Cambio**:
  - T10: `test_thinking_without_budget_body_has_no_template_kwargs[file|env]`;
  - T6: `test_reset_budget_rejected_while_thinking_on` (con `reset code` y con `reset` global).

**P5 — Baja — REQ-013 (evento), T13.**
- **Evidencia**: «El evento no lleva `backend_params`» está en el paso 5 de T13, pero no tiene test
  con nombre.
- **Cambio**: `test_explicit_model_event_has_no_backend_params` en T13.

**P6 — Media — Prueba en vivo (§4.4, paso 2), T19.**
- **Evidencia**: el plan dice «`schtasks /Run` de la tarea del daemon (ver memoria…)». La sesión
  limpia no tiene el nombre de la tarea, y `/Run` sobre una tarea en marcha no reinicia el daemon.
  El producto para y arranca con `schtasks /End /TN LocalDelegateDaemon` y luego
  `/Run /TN LocalDelegateDaemon`, comprobando entre medias que el proceso murió (`update.py:47`,
  `:593-601`, `:696`). Tampoco se comprueba que la CLI y el daemon lean el mismo `LOG_DIR`. Si
  no es el mismo, el paso 4 (`set` con el daemon arrancado) escribe un fichero que el daemon no ve,
  y REQ-009 en vivo falla por el entorno.
- **Cambio**:
  - escribir los dos comandos, con el nombre de la tarea y la comprobación de que el proceso murió;
  - o mejor, usar el mecanismo del propio producto si `local-delegate update` admite reiniciar sin
    publicar;
  - añadir antes del paso 4 una comprobación de que la ruta que imprime `backend-params show`
    coincide con el `LOG_DIR` del daemon (por `local_status` o `doctor`);
  - añadir este riesgo a §6.

**P7 — Baja — Regla 4 (LF/CRLF), T16.**
- **Evidencia**: la regla dice «los tests en **LF**». `git ls-files --eol` da `i/crlf` en
  `tests/test_dashboard_ui.py`, que es justo el fichero que posee T16 (también `test_clients.py`,
  `test_ctrl_c.py`, `test_questions.py`, `test_smoke.py` y `test_vendor.py`).
- **Cambio**: en la regla 4, «los tests en LF **salvo** `test_dashboard_ui.py` y los otros cinco en
  CRLF; comprobar siempre con `git ls-files --eol`», y anotarlo en T16.

**P8 — Baja — T6, paso 5 (puntero de patrón erróneo, heredado de la trazabilidad de la spec).**
- **Evidencia**: `web/metrics.py:557-560` es la carga de `open_test_windows`, no una caché por
  `mtime`. El patrón bueno es el que cita T7: `topology.py:541`, con la clave
  `(path, st.st_mtime_ns, st.st_size)`, a la que REQ-009 añade `st_ino`.
- **Cambio**: en T6, sustituir el puntero por `topology.py:541`.

**P9 — Baja — T11, paso 4, y §6 fila 5 (decisión que se deja abierta).**
- **Evidencia**: ya hay precedente. El reintento sin esquema son dos POST dentro de **un** `Attempt`
  (`server.py:2032-2038` y `:2052-2053`), y `chunks` y `attempts` no lo ven como llamada aparte.
- **Cambio**: fijar en el plan que el POST extra del rechazo va dentro del mismo `Attempt`, como el
  reintento sin esquema. `reasoning_chars` se suma igual (T13, paso 3). El recuento de POST de
  REQ-015 se mide en el backend falso, no en `attempts`. Con eso desaparece el riesgo de reabrir
  REQ-018.

**P10 — Baja — §6, fila «Map/reduce concurrente».**
- **Evidencia**: `server.py` no tiene `ThreadPoolExecutor`, `submit` ni `as_completed`: los trozos y
  los pasos de map/reduce van en serie.
- **Cambio**: el `threading.Lock` de `_RoleParams` no estorba y puede quedarse, pero la fila de
  riesgo debería decir que hoy no hay concurrencia. Así nadie persigue una carrera inexistente si
  el recuento de POST sale mal por otra causa.

**P11 — Baja — Tabla de lotes y olas (dependencia implícita A1 → L0).**
- **Evidencia**: A1 figura con «Depende de: —», pero el paso 7 de T3 edita
  `tests/test_tool_signatures.py`, que posee T2 (L0).
- **Cambio**: en la tabla, «A1: depende de L0 **para mezclar**», o sacar el paso 7 a una tarea
  pequeña de A2.

**P12 — Baja — Citas (muestreadas 40, todas existen salvo un desfase).**
- **Desfase**: `_attempt` se cita en `:2043`, y está en `:2044`.
- **Líneas de la spec**: REQ-014 cita `:4326`, `:4412`… (líneas del cuerpo). El plan usa las de
  `def` (`4301`, `4396`, `4447`, `4588`, `4621`, `4702`, `4803`, `4945`, `4989`, `5108`, `5496`),
  que son las correctas. Conviene una línea en T2 que diga que estas mandan sobre las de la spec.
- **Verificadas**:
  - `server.py`: 726, 1101, 1120, 1206, 1330, 1354-1363, 1468, 2019, 2146, 2306, 2365, 2387, 2427,
    2503, 2546, 2593, 2955, 2994, 3059, 3172, 3255, 3474, 4684, 4694, 5526-5534 y 5638;
  - `config.py`: 327, 343, 406, 448, 454, 467, 488, 513 y 579;
  - `llamaswap_config.py`: 51, 240 y 487;
  - `cli.py`: 390, 460, 1208 y 1389;
  - `doctor.py`: 48 y 120;
  - `web/metrics.py`: 517, 1776, 2873, 3095, 3209, 3223 y 3233;
  - `benchmark.py`: 993, 1004, 1019, 1031, 1288 y 1417;
  - tests: `test_checks.py:93`, `test_metrics.py:1570`, `test_dashboard_js.py:583`,
    `test_fallback.py:662`, `test_environment_isolation.py:155`, `test_wiki.py:219,241`,
    `test_i18n_parity.py:97` y `conftest.py:24,50,182-199,201`;
  - otros: `ci.yml:161,186-218` y `test_windows.py:243,268`.

**P13 — Baja — Delegación local (apartados genéricos o incompletos).**
- **Evidencia**: el apartado está en **todas** las tareas y en §4.1–§4.5, y hay sección general de
  reglas. Pero algunos se quedan en relleno:
  - T2, T4, T13 y T17: el orquestador hace «`local_summarize` de la entrega» sin `focus`;
  - T16: el orquestador pone «nada especial», sin motivo;
  - T18: el agente no vuelca pytest a `local_lint_summary` ni hace el diff con `local_commit_msg`;
  - T15: no pide `local_translate` para el borrador inglés de `panel.json`, como sí hacen T5, T8 y
    T14;
  - T5, T7, T9, T14, T16 y T18 no nombran `local_commit_msg`, aunque la regla general lo cubre «por
    lote».
- **Cambio**:
  - darle a cada `local_summarize` de entrega un `focus` concreto (p. ej. T4: «registro en
    `ENVIRONMENT_VARIABLES` y guarda de aislamiento»; T13: «campos del evento y assert del
    mutante»; T17: «forma nueva de `reasoning_kwargs` y error sin presupuesto»);
  - poner motivo en T16 («entrega de un test»);
  - completar T18 y T15.
- **Bien resuelto**: no usar `local_*` sobre `server.py`, `metrics.py`, `cli.py` y `benchmark.py`
  enteros (regla 1b); `test_dashboard_states.py` pesa 33 KB, así que el `local_explain_code` de T15
  es válido.

**P14 — Baja — §4.5 (origen del evento rechazado para las capturas).**
- **Evidencia**: «escrito a mano en un `LOG_DIR` temporal», pero las capturas se toman del panel del
  daemon (`:9393`), que lee el `LOG_DIR` real.
- **Cambio**: elegir una de dos y escribir el comando:
  - (a) un segundo proceso del panel contra un `LOG_DIR` temporal, en otro puerto;
  - (b) el evento en el log real, dentro de la ventana de prueba, con su id anotado.

**P15 — Baja — T1 («8 caminos»).**
- **Evidencia**: REQ-022 nombra siete caminos; el octavo sale de contar la reducción de map/reduce
  aparte.
- **Cambio**: enumerar los ocho nombres de fixture, por ejemplo:
  - `simple`;
  - `extract_schema`;
  - `extract_schema_retry`;
  - `map_chunk`;
  - `reduce`;
  - `vision`;
  - `fallback`;
  - `delegate_explicit`.

**P16 — Baja — T17 (enum del benchmark frente al del producto).**
- **Evidencia**: `REASONING_EFFORTS = ("off", "low", "medium", "high")` (`benchmark.py:993`), y el
  enum del producto es `minimal…max` (REQ-004).
- **Cambio**: no lo exige REQ-020. Decidir de forma explícita si se dejan como están y anotarlo en
  T17, para que la sesión no lo «arregle» por iniciativa propia.

## Comprobaciones pedidas, en resumen

- **Cobertura**:
  - los 23 REQ tienen tarea y test o evidencia en la matriz (§3);
  - quedan aceptaciones huérfanas o a medias: P2 (REQ-006 en `show` y `doctor`), P3 (REQ-017),
    P4 (REQ-011 en el cuerpo y el `reset`) y P5 (REQ-013, evento);
  - el resto de aceptaciones tienen test con nombre: REQ-001–005, 007–010, 012, 014–016 y 018–023.
- **Dependencias y paralelismo**:
  - la propiedad es exclusiva por ola en `server.py` (C1 → C2 → D en serie), en `cli.json`
    (T8 → T17) y en `common.json`, `doctor.json`, `mcp.json` y `panel.json` (un dueño cada uno);
  - `config.py` solo lo toca T4, y T12 solo si elige ponerlo ahí, ya con A1 mezclado;
  - en los tests compartidos (`test_request_body_compat.py` T1 → T10, `test_tool_signatures.py`
    T2 → T3) la serie es correcta, con la salvedad de P11;
  - el orden A1 → A2 → C1 → C2 → D está bien;
  - L0 sobre `f2dd267` en su worktree (`git worktree add D:/Projects/ld-wt-l0 f2dd267 -b …`) se
    puede hacer, y hoy `main` = `f2dd267`.
- **Viabilidad**:
  - las 19 tareas tienen pasos concretos, tests con nombre, comando de verificación y criterio de
    hecho con su mutante;
  - ningún lote pasa de unas 550 líneas estimadas, y §6 prevé partirlo si se pasa;
  - existen los scripts que se citan (`extract_dashboard_js.py`, `sync_wiki.py`, `release.py`,
    `bump_version.py`) y `~/.claude/scripts/pesado.sh`.
- **Verificación**:
  - están el cerrojo, la suite con `-n auto --dist loadgroup` (que es lo que corre el CI), ruff,
    la validación del JS, `test-lang-es` (con el aviso correcto de que en Windows `LANG` no
    discrimina) y `gh pr checks`;
  - también la ventana de prueba con id y `stop`, `uv tool install --reinstall --no-cache`, el aviso
    de `/mcp` y las capturas en claro y oscuro con tres criterios;
  - faltan P6 y P14.
- **Reglas de ejecución**: están todas (worktrees en `D:/Projects/ld-wt-*`, LF/CRLF, commits
  firmados sin coautoría, `gh pr checks`, CodeQL, `_env*`, mutantes y nada huérfano). Solo hay que
  corregir P7.
- **Delegación local**: el apartado está en todas las tareas y en cada paso de verificación,
  separado entre orquestador y agente, y hay sección general. Las mejoras van en P13.
- **Riesgos y reapertura**: están completos; hay que añadir el de P6 (`LOG_DIR` de la CLI frente al
  del daemon) y matizar las filas de P9 y P10. Los puntos de reapertura (cambiar un REQ, un campo
  del log, el catálogo, la fusión o el contrato) son correctos.

## Evidencia recomendada para el gate

- P1 aplicado en `spec.md`, y en `plan.md` §1 y §6.
- P2–P6 incorporados a las tareas afectadas antes de lanzar sus lotes.
- `state.json` con el gate `plan` aprobado con notas y enlace a esta sección.

# Revisión de conformidad (gate conformance, 2026-10-20)

Revisión fresca sobre `main` = `a2ce49d` (worktree `ld-wt-close`), leyendo el código y los tests
contra cada REQ de `spec.md` y las decisiones 1–12 de `brief.md`. `verification.md` y las PR se
usaron solo como pistas. No ejecuté tests: la suite completa la corre otro agente en paralelo, así
que el «verde» de la suite y de la CI `test-lang-es` no lo afirma esta revisión.

## Veredicto

**CONFORME CON NOTAS.** Los 23 requisitos están implementados y cada uno tiene un test que fallaría
si se rompe su núcleo; las notas son de redacción de la spec, de cobertura secundaria y de
documentación de uso, y ninguna bloquea el cierre.

## Requisito por requisito

| REQ | Veredicto | Evidencia (código · test) | Nota |
| --- | --- | --- | --- |
| REQ-001 Fichero por rol | cumple con nota | `backend_params.py:397-399` (ruta), `:439-470` (`_read_document`: ausente o vacío = vacío; >64 KB, JSON roto o `version`≠1 → ignorado entero), `:477-498` (rol desconocido fuera), `:501-509` (`load` nunca lanza) · `test_backend_params_file.py::test_load_tolerates`, `test_load_never_raises`, `test_load_exactly_64kb_is_read` | La spec nombra `validate`; el código lo llama `validate_value` (`:214`). Solo nombre. |
| REQ-002 Escritura atómica | cumple | `backend_params.py:512-541` (`mkstemp` en el mismo directorio + `os.replace` bajo `FileLock`; borra el temporal si falla) · `test_failed_replace_keeps_original_and_no_temp`, `test_concurrent_sets_keep_both_keys` | |
| REQ-003 Subcomando | cumple | `cli.py:551-602`, registro en `cli.py:1515-1516` junto a `_add_test_window_parser`; `backend_params.py:580-664` · `test_cli_backend_params.py` (cada verbo, `test_show_json_shape`, `test_set_invalid_leaves_file_untouched` con bytes y `mtime`) | Decisión 12 (reset sin preguntar) aplicada en `backend_params.py:648-664`. |
| REQ-004 Lista cerrada | cumple | `backend_params.py:77-101` (21 claves con los rangos de la tabla), `:214-241` (un booleano no es número, `NaN`/`inf` fuera, una clave int no acepta float) · `test_backend_params_rules.py::test_catalog_has_exactly_21_keys`, `test_value_validation`, `test_every_key_has_a_valid_and_an_invalid_case` | |
| REQ-005 Reservadas | cumple | `backend_params.py:104-152` (27 reservadas + 9 aplazadas), `:380` (assert de defensa en `to_body`) · `test_reserved_and_deferred_keys_are_rejected`, `test_backend_params_server.py::test_reserved_key_never_reaches_body` | |
| REQ-006 Quitar solo la clave | cumple | `backend_params.py:179-189` (`Warning` = rol, clave y código; sin valor), `:489-495` · `test_file_and_env_drop_only_bad_key`, `test_bad_keys_dropped_rest_applied`, `test_sentinels_never_in_log`, `test_status_hides_sentinels`, `test_show_hides_sentinels`, `test_doctor_hides_sentinels` | |
| REQ-007 Fuera de rango o de tipo | cumple | Igual que REQ-006 por fichero y variable; `set` rechaza en `backend_params.py:590-594` · `test_file_and_env_drop_only_bad_key` (`top_p 1.5`, `top_k=x`), `test_set_invalid_leaves_file_untouched` | |
| REQ-008 Variable y precedencia | cumple | `config.py:472-498` (lector `(value, problem, raw)`, tope 2048, dentro del bucle `_reader`), `backend_params.py:280-319` (gramática), `:694-696` (la variable gana clave a clave) · `test_override_grammar`, `test_variable_is_registered`, `test_env_wins_key_by_key`; `test_environment_isolation.py` sin cambios desde `f2dd267` | |
| REQ-009 Sin reiniciar | cumple | `backend_params.py:677-731` (caché por `(st_mtime_ns, st_size, st_ino)` + valor crudo de la variable); `server.py:2575-2587` resuelve al empezar cada operación · `test_same_size_rewrite_is_seen[set\|in_place]`, `test_backend_params_server.py::test_file_change_applies_next_operation` (20→30, mismo tamaño); en vivo, T19 paso 4 | |
| REQ-010 Temperatura del rol | cumple | `backend_params.py:362-364`; `server.py:2553-2572` (sustituye en sitio) · `test_role_temperature_overrides_tool[*]` (incluye `local_boilerplate` sin cambio) | |
| REQ-011 Razonamiento | cumple | `backend_params.py:322-333` (sin presupuesto se ignora con aviso), `:363` y `:370-377` (suma al tope, `chat_template_kwargs`, `reasoning_effort` en la raíz), `:596-603` y `:612-622` (rechazos de `set` y `unset`) · `test_set_rejects_thinking_without_budget`, `test_unset_budget_rejected_while_thinking_on`, `test_thinking_without_budget_body_has_no_template_kwargs[file\|env]`, `test_thinking_on_classify_sums_budget`, `test_every_chunk_sums_budget`, `test_thinking_off_sends_false_and_keeps_max_tokens`; en vivo, `reasoning_chars = 1067` y `tokens_out = 956 = 700 + 256` | |
| REQ-012 Capas y respaldo | cumple con nota | `server.py:2084-2110` (capa 2 en `_call_model` sobre una copia; el `payload` no se muta), `:2553-2572` (el contrato nunca se pisa), `:2481-2509` (`_RoleParams` aparte de `_CurrentModel.role`); paso a trozos y map/reduce en `:3258-3260` y `:3522-3524` · `test_to_body_layers`, `test_params_survive_fallback_and_later_chunks`, `test_code_temperature_0_7`, `test_contract_keys_always_from_product` | Hallazgo 3: «una vez por operación» solo lo protege un test de forma indirecta. |
| REQ-013 Modelo explícito | cumple | `server.py:2590` (`explicit` → `None`), `local_delegate` en `server.py:4918` · `test_explicit_model_carries_no_params`, `test_local_delegate_without_model_uses_mechanical`, `test_explicit_model_event_has_no_backend_params`; camino `delegate_explicit` de la compatibilidad | |
| REQ-014 Sin argumentos nuevos | cumple con nota | `tests/fixtures/tool_signatures.json` (de `f2dd267`) · `test_tool_signatures.py::test_tool_parameters_match_snapshot`, `test_no_tool_parameter_is_a_backend_param`, `test_the_guard_has_the_keys_of_the_spec` | La guarda (b) exime `("local_delegate", "model")` (hallazgo 1). |
| REQ-015 Rechazo 400 | cumple con nota | `server.py:2112-2126` (una sola prueba por operación con `claim_probe`, antes del reintento sin esquema; marca solo si funciona), `:2511-2518` (tras el rechazo, el cuerpo de la tool) · `test_backend_params_rejection.py` (6 tests: esquema, 3 trozos = 4 POST, valores de la tool, 400 con y sin parámetros, una sola prueba, control sin parámetros, tool sin esquema), `test_rejected_event_keeps_tried_values` | Un reintento que falla con algo distinto de 400 no lo define la spec (hallazgo 4). |
| REQ-016 `local_status` y `doctor` | cumple | `server.py:5926-5954` (debajo de `vision`, llamada en `:5804`), `doctor.py:68-98` (`backend_params_lines`, con aviso si la variable está en tu shell) · `test_backend_params_status.py`, `test_doctor_backend_params.py`; `test_checks.py` sin cambios desde `f2dd267`; en vivo, T19 pasos 3 y 6 | |
| REQ-017 i18n | cumple | `resources/i18n/{es,en}/{cli,common,doctor,mcp,panel}.json` (pares en el diff); `test_i18n_parity.py` sin cambios · `test_backend_params_i18n.py::test_every_warning_code_has_text_in_both_languages`, `test_warning_texts_have_no_value_placeholder`, `test_rendered_warnings_hide_sentinels[es\|en]` | La CI `test-lang-es` no se comprobó aquí. |
| REQ-018 Log | cumple | `server.py:877-885` (campos aditivos, omitidos si no aplican), `:1387-1400` y `_body_failure` (`reasoning_chars` también en fallos), `:1517-1541` (`reasoning_content` + bloques `<think>`, sin texto), `:2137-2139` (suma de los POST de un intento), `:2590-2615` · `test_backend_params_log.py` (omisión, intento fallido, `<think>` sin `reasoning_content`, texto nunca en `usage-*.jsonl`, `source` solo con `env`, operación troceada) | |
| REQ-019 Panel | cumple con nota | `web/metrics.py:3131-3147` (`reasonchip`, `paramschip`, estado `rejected`), `:3149-3191` (filas sin vacías), `:3339-3357` (diálogo con el patrón de `infoDlg`, Enter), `:1811` · `test_dashboard_states.py` (casos nuevos hacia `:876-929`), `test_dashboard_ui.py::test_event_row_opens_dialog_with_enter`, `test_metrics.py:1574`; `test_dashboard_js.py` sin cambios; 4 PNG en `evidence/` | Revisé `panel-lista-claro.png` y `panel-dialogo-oscuro.png`: marcas visibles y sin solape, diálogo sin filas vacías. El diálogo pinta los booleanos como `true` y la CLI como `on` (hallazgo 5). |
| REQ-020 Benchmark | cumple | `benchmark.py:994` (enum = `off` + el del producto), `:1006-1039` y `:1095-1112` (cuerpo vía `backend_params.to_body`, presupuesto sumado), `:1133-1160` (error sin presupuesto, venga el esfuerzo de donde venga), `:1163-1174`, `:1337` y `:1394` (metadatos, solo nombres) · `test_benchmark.py` (forma nueva, errores, metadatos, `test_effort_enum_matches_product`); en vivo `off`/`low`/`high`, sin diferencia entre `low` y `high` | |
| REQ-021 Documentación | cumple con nota | `docs/wiki/Configuration.md` §«Parámetros del backend por rol» cubre los 9 puntos (fichero y subcomando; tablas de claves y reservadas; precedencia y capas; roles que cambian por tamaño; `reasoning_effort` solo no enciende + medición `low`/`high`; suma al tope y contexto; Qwen sin etiquetas; variable frente a fichero, cada máquina, la Mac con 8192; medir con el benchmark de afinidad); `Savings-and-metrics.md:40-52`; `README.md:225-229`; `CHANGELOG.md` `[Unreleased]` · `test_wiki.py::test_configuration_documents_backend_params`, `test_configuration_lists_every_backend_param_key` | Falta una advertencia de uso sobre presupuestos pequeños con Qwen3.6 (hallazgo 2). |
| REQ-022 Compatibilidad | cumple | `server.py:2583-2587` (sin valores → `None` → el cuerpo de hoy) · `test_request_body_compat.py` (8 caminos × sin fichero / roles vacíos / rol vacío, comparación ordenada con `object_pairs_hook=list`, conjunto de claves del evento; fixtures de `scripts/capture_request_bodies.py` en `46633bb`, antes de tocar `server.py`, y cada una anota `f2dd267`); en vivo, T19 paso 7 | |
| REQ-023 Contexto | cumple | `server.py:2526-2538` (fórmula con margen 2, sistema + usuario, `vision` fuera, modelo real del intento), `config.py:543`, `llamaswap_config.py:544-569` (`model_context_size`, caché, estimado 8192, nunca lanza), `backend_params.py:755-781` (aviso de `set`, `show`, `doctor` y `local_status`) · `test_backend_params_context.py` (larga, corta, límite exacto y un carácter más, densa, visión, contexto desconocido, respaldo con su propio contexto), `test_model_context_size.py`, `test_set_context_warning_exit_zero` | El aviso de «contexto estimado» solo sale para roles con el razonamiento encendido; es la lectura razonable de la spec. |

Recuento: 17 cumplen y 6 cumplen con nota (REQ-001, 012, 014, 015, 019 y 021); ninguno incumple.

## Hallazgos

1. **Menor — la guarda de REQ-014 (b) tiene una excepción que la spec no recoge.**
   `tests/test_tool_signatures.py` (constante `PRE_EXISTING`) exime `("local_delegate", "model")`.
   La letra de REQ-014 (b) dice que ningún parámetro se llame como una clave reservada, y `model` lo
   es; pero ese argumento existe desde antes del cambio y quitarlo rompería el assert (a) y a los
   clientes. El espíritu (el modelo frontera no fija parámetros de rol) se cumple: con `model=` el
   cuerpo no lleva ninguno (REQ-013). Está anotado en `verification.md` §«Desviaciones». Haría
   falta: una línea en «Cambios tras la revisión» de la spec, para que la spec y el test digan lo
   mismo.

2. **Menor — la wiki no advierte del corte con presupuestos pequeños en Qwen3.6 (hallazgo de T19).**
   `docs/wiki/Configuration.md`, bloque «Qwen y el razonamiento sin etiquetas»: explica que el exceso
   se cuela en `content` y no se cuenta, pero no que con presupuesto 256 en `code` la respuesta se
   corta por `max_tokens` (`finish_reason = length`) y sale mala. No contradice ningún REQ (ver la
   última sección). Haría falta: una frase de recomendación en la wiki, o una entrada en el
   backlog, sobre el presupuesto mínimo aconsejable por modelo.

3. **Menor — «una vez por operación» (REQ-012) no tiene un test que lo distinga de «en cada llamada».**
   `server.py:3258-3260` y `:3522-3524` resuelven al empezar. Mutante mental: resolver en
   `_call_model` con el rol de origen guardado. Ningún test fallaría, porque ninguno cambia el
   fichero a mitad de una operación troceada. El mutante que sí importa (resolver con
   `_CurrentModel.role`, que vale `None` tras un salto) lo caza
   `test_params_survive_fallback_and_later_chunks`. Haría falta, si se quiere blindar: un test que
   reescriba el fichero desde el backend falso entre el trozo 1 y el 2 y compruebe que el trozo 2
   lleva el valor viejo.

4. **Menor — REQ-015 no define qué pasa si el reintento sin parámetros falla con algo que no es 400.**
   `server.py:2112-2126`: si el reintento da timeout o 5xx, no se marca el rechazo, la prueba queda
   gastada y el flujo sigue con el resultado 400 original (reintento sin esquema, con parámetros).
   Es coherente con «solo se marca si el reintento funciona», pero la spec solo describe el caso
   «también da 400». Haría falta: nada en código; anotarlo como comportamiento aceptado.

5. **Menor — los booleanos salen con dos formatos según la superficie.** `web/metrics.py:3149-3191`
   (`eventRows`) pinta `enable_thinking = true` (se ve en `evidence/panel-dialogo-oscuro.png`),
   mientras que `show`, `doctor` y `local_status` usan `on`/`off` (`backend_params.py:192-200`).
   Ningún REQ lo exige; es coherencia de cara al usuario. Haría falta: usar `on`/`off` en el
   diálogo, si se quiere.

No hay hallazgos bloqueantes ni importantes.

**Mutantes mentales de los REQ críticos** (qué test falla si se rompe):
- REQ-009: una caché que ignora `st_mtime_ns` o `st_ino` → `test_same_size_rewrite_is_seen[in_place]`;
  parámetros resueltos al importar → `test_file_change_applies_next_operation`.
- REQ-011: no sumar el presupuesto → `test_thinking_on_classify_sums_budget`; sumarlo solo en el
  primer trozo → `test_every_chunk_sums_budget`; `set` que acepta `enable_thinking on` sin
  presupuesto → `test_set_rejects_thinking_without_budget`.
- REQ-014: un argumento nuevo en una tool → `test_tool_parameters_match_snapshot`; un argumento
  llamado como una clave o `reasoning*` → `test_no_tool_parameter_is_a_backend_param`.
- REQ-018: guardar el texto del razonamiento → `test_reasoning_text_never_logged`; no contar los
  intentos fallidos → `test_reasoning_chars_sums_failed_attempt`; no contar `<think>` →
  `test_think_tags_count_without_reasoning_content`.
- REQ-022: una clave de más, otro orden o un `1` frente a `1.0` en cualquiera de los 8 caminos →
  `test_body_matches_main`; un `_RoleParams` creado para un rol vacío → el mismo test en modo
  `empty_role`.

Ningún REQ crítico queda sin un test que lo cace.

## Fuera de alcance respetado

- Sin `LOCAL_DELEGATE_REASONING_EFFORT`, `LOCAL_DELEGATE_EXTRA_BODY` ni `extra_body` en `src/`.
- Sin parámetros por tool ni por modelo; `filters.setParams` de llama-swap sin tocar.
- Las 9 claves aplazadas se rechazan (`backend_params.py:140-152`, código `deferred_key`).
- Sin `reasoning_chars` por paso en `steps[]`.
- No se recorta la entrada ni se reduce `MAX_CHARS` (`test_long_input_skips_reasoning` comprueba
  que la entrada llega entera).
- Sin cambios en `pyproject.toml`, `uv.lock`, `benchmarks/` ni en la config de llama-swap;
  `llamaswap_config.py` solo gana el lector `model_context_size`. Sin dependencias nuevas.
- El contenido de Qwen sin etiquetas no se quita ni se cuenta; solo se documenta.
- README, wiki y CHANGELOG solo en español (decisión 11).

## El hallazgo de T19 (Qwen3.6, presupuesto 256 en `code`)

**No es un incumplimiento; es una recomendación de uso.** El producto hizo exactamente lo que
piden los REQ: mandó `enable_thinking: true` y `reasoning_budget_tokens: 256`, sumó el presupuesto
al tope (`tokens_out = 956 = 700 + 256`, REQ-011), registró `backend_params` y
`reasoning_chars = 1067` (REQ-018) y no recortó nada. Que Qwen3.6 siga «pensando» en el `content`
visible tras agotar el presupuesto es el riesgo que la spec ya reconoce (tabla de riesgos: «En Qwen
el razonamiento que pasa del presupuesto aparece en `content` sin etiquetas») y que deja fuera de
alcance («Quitar o contar el razonamiento que Qwen deja en `content`»). El rango del presupuesto
(1–8192, REQ-004) es de validación, no de calidad, y medir la calidad de un razonamiento nuevo
queda para el usuario con el benchmark de afinidad (fuera de alcance). Lo que sí conviene es el
hallazgo 2: decirlo en la wiki o llevarlo al backlog, para que nadie configure 256 en `code` con
Qwen3.6 creyendo que es un valor seguro.
