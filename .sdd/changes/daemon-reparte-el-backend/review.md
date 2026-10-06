# Result review: Daemon: no se pelea por el modelo, aprovecha el cargado, avisa de la lentitud y deja la residencia configurable

## Revisión de la spec

Revisión adversaria de `spec.md` (11:33), en solo lectura, el 2026-10-06. La contrasté con `brief.md`
(incluidos los cambios de última hora), `research.md`, `insumos/llamaswap-grupos.md`, el código
(`server.py`, `cadenas.py`, `checks.py`, `autostart.py`, `config.py`, `llamaswap_config.py`, `cli.py`),
la spec y el plan de F3 (`delegacion-precisa-y-fiable`), el plan de `panel-cuentas-y-estados-honestos`,
el código de llama-swap v255 del scratchpad (`w255/`, `ls255/`, `docs-v255/`) y `config.yaml` real
(leído con las claves ocultas, sin tocarlo).

### Veredicto

**No se aprueba el gate de la spec: hay que corregirla.** El objetivo está bien planteado y casi todo
está bien fundado: la lectura de `EvictionFor`, el diagnóstico de `cadenas.py`, el descarte de ruamel
y los criterios escritos antes de medir. Pero quedan dos defectos de diseño que pueden **bloquear el
daemon** o dejar el turno sin definir. Además, la spec no se actualizó con el TTL de 120 s. Y varios
controles no pueden dar un resultado distinto o miden una magnitud diferente de la que decide la
regla.

### BLOQUEANTE

**1. Turno y plaza en un salto de respaldo: pueden bloquearse mutuamente.**
- Evidencia: REQ-004 dice que quien espera turno no ocupa plaza. REQ-006 dice que, si una operación
  cambia de modelo a mitad, suelta su turno y pide otro. Pero hoy el salto ocurre **dentro** de la
  plaza: `_run_chat` hace `with _chat_slots:` alrededor de `_con_respaldo` (`server.py:1117-1125`),
  porque así lo exige REQ-017 de F3 (`delegacion-precisa-y-fiable/spec.md`, «la llamada del respaldo
  ocupa la misma plaza»). Con `MAX_CONCURRENT_REQUESTS = 2` puede pasar esto: dos operaciones que
  comparten el turno del 26B fallan, saltan a Qwen3.6 y se quedan esperando turno **con las dos
  plazas ocupadas**. Mientras tanto, la tercera operación, la que tiene el turno del 26B, no consigue
  plaza para su siguiente trozo. Nadie avanza hasta que vencen los 600 s.
- Arreglo: escribir que, cuando el salto necesita un modelo que choca con el turno, la operación
  **suelta la plaza**, espera el turno nuevo y vuelve a pedir plaza. Hay que enmendar de forma
  explícita REQ-017 de F3, o bien prohibir los saltos a un modelo que choca mientras otros comparten
  el turno. Hace falta un escenario con dos plazas, dos saltos simultáneos y una operación troceada
  que tiene el turno, y un mutante que mantenga la plaza; el test debe fallar por el assert del
  progreso, no por un timeout.

**2. El turno no está definido: cuál se pide antes de saber el modelo, cómo entra la afinidad en la cola y qué estructura tiene.**
- Evidencia:
  - REQ-003 pide el turno «del modelo al que va» **antes** de la primera llamada, y REQ-012 decide el
    modelo **al obtener** el turno. Es circular. Si el 26B tiene el turno (el daemon tiene una
    llamada en vuelo contra él), un `local_classify` con la celda aprobada puede hacer dos cosas, y
    la spec no dice cuál:
    - pide el turno del 4B: espera a que el 26B termine y pierde la afinidad;
    - se une al turno del 26B: se cuela por delante de quien espera otro modelo, contra REQ-005.
  - Si se cuela, aparece la inanición que REQ-005 quería evitar: una serie de tareas mecánicas por
    afinidad mantiene vivo el turno del 26B indefinidamente.
  - REQ-008 habla de «el modelo que lo tiene», en singular, y el título dice «grupo de conflicto».
    Pero la relación «chocan» de REQ-001 no es transitiva. Con un residente opcional (`--fijar`,
    `persistent` y `exclusive: false`), el 4B y el 26B conviven y los dos chocan con un tercero. El
    turno tiene que ser un **conjunto** de modelos compatibles entre sí, no un único modelo.
- Arreglo: definir la máquina de estados en la spec. Una petición de turno lleva el **conjunto de
  modelos aceptables** (el del rol más los alternativos aprobados). Se concede en el acto solo si el
  conjunto activo incluye uno de ellos **y** no hay nadie esperando delante (REQ-005 se aplica también
  a la afinidad). Al conceder el turno, se elige el modelo con REQ-012 y ese modelo entra en el
  conjunto activo. Añadir escenarios para:
  - afinidad con alguien esperando: la tarea mecánica no se cuela;
  - afinidad sin nadie esperando: se une al turno;
  - un residente compatible que no espera.

### IMPORTANTE

**3. La spec y el research siguen con TTL de 300 s, y el margen de 60 s no responde a la carrera que dice cerrar.**
- Evidencia: `config.yaml` tiene hoy `ttl: 120` en los cuatro de texto y `30` en el 12B: lo
  comprobé, y coincide con `config.yaml.pre-ttl-120-20261006.bak` cambiando solo cuatro líneas.
  Sin embargo:
  - los escenarios usan `ttl: 300` (`spec.md:272`, `:279`) y «5 modelos con TTL 300» (`:321`);
  - el control «quedan 240 s» (`:420`) es imposible con un TTL de 120;
  - `research.md:89` y `:144` siguen con 300;
  - REQ-030 sugiere 300.

  Sobre el margen: el research cierra la carrera decidiendo «justo antes de enviar»
  (`research.md:180-186`). La ventana entre consultar y enviar son como mucho las dos consultas, de
  1 s cada una. En cuanto la petición llega, llama-swap reinicia el reloj del TTL. Un margen de 60 s
  sobre un TTL de 120 tira la mitad de la ventana útil. Y el escenario «quedan 30 s → va al 4B»
  descarga un modelo que podía servir, justo lo contrario del objetivo del cambio.
- Arreglo: pasar escenarios, controles y research a 120/30. Elegir el margen según lo que de verdad
  tiene que cubrir (la latencia de la consulta más el desfase de reloj, del orden de 5–10 s) o
  justificar 60 s con un dato. Reescribir el par de controles, por ejemplo «quedan 3 s → rol» y
  «quedan 40 s → alternativo».

**4. El TTL que le queda a un modelo es una estimación, y la spec no lo trata como tal.**
- Evidencia: llama-swap v255 no expone ese dato. `GET /running` (`w255/srv_api.go:350-369`) da el
  `ttl` **efectivo**, ya resuelto con `globalTTL` (`src_load.go:139-140`), pero no la última
  actividad. `modelStatus` (`srv_apigroup.go:98-134`) tampoco. La estimación
  `ttl − (ahora − última fila de /api/metrics/activity)` se apoya en supuestos que nadie ha
  verificado:
  - que el reloj del TTL empieza al **terminar** la última petición y no corre mientras hay
    peticiones en vuelo. La implementación de `process` no está en el scratchpad: `process.go` es
    solo la interfaz, de 70 líneas;
  - que la fila se escribe sin retraso;
  - que el reloj de la Mac coincide con el de la PC (REQ-017).

  Además, la estimación da **falsos negativos justo en el caso que motiva el cambio**: si el 26B
  lleva más de 60 s atendiendo una petición de otro cliente, su última fila es vieja y parece «sin
  margen». Y la v255 ya ofrece la pieza que falta: `GET /api/events` manda al conectar una foto de
  **todas** las peticiones en vuelo, con su modelo (`srv_apigroup.go`, «initial payload»,
  `sendInFlight(s.inflight.Current())`; los campos están en `swaputil/events.go:60-72`).
- Arreglo:
  - Añadir como fuente de certeza la foto de peticiones en vuelo de `/api/events`: un modelo con una
    petición en vuelo, de quien sea, está cargado.
  - Tomar «ahora» de la cabecera `Date` de la respuesta del backend, no del reloj local.
  - Que la prueba con el llama-swap de prueba verifique también cuándo empieza a contar el TTL.
  - Registrar en el log cuándo la afinidad se equivocó: el alternativo tuvo que cargarse, lo que se
    ve en un `espera_ms` del orden de una carga.

**5. El tope absoluto de 600 s para esperar turno choca con las operaciones largas legítimas, y no se dice qué pasa al vencer.**
- Evidencia: la espera de una operación es la suma de todas las que tiene delante en la cola. Solo
  `commit_msg` tardó 198 s el 10-01, y el techo de 156k son 13 llamadas. Con dos o tres operaciones
  largas delante, se superan los 600 s sin que nada vaya mal, y la que vence «sigue sin turno»: el
  vaivén de modelos vuelve justo cuando más pesa. Además, la spec no dice:
  - si la operación vencida cuenta como dueña del turno para las que esperan detrás;
  - qué pasa con una espera cuya llamada canceló el cliente: queda en la cola como espera fantasma y,
    por REQ-005, frena a las demás.
- Arreglo: que la red de seguridad mida la **falta de progreso** de quien tiene el turno (ninguna
  llamada al backend termina en N veces `HTTP_TIMEOUT`), no el tiempo total de espera. Definir
  también qué pasa al vencer y con las esperas canceladas.

**6. Las cadenas de respaldo dependen de la afinidad, que puede no implementarse; y con un solo grupo `swap`, `cargado` casi nunca existe.**
- Evidencia: REQ-019 y REQ-021 usan la matriz y el margen (REQ-010 y REQ-013), pero REQ-018 tumba
  REQ-010 a 017 si no se aprueba ninguna celda. Además:
  - Tras un fallo **de capacidad** al cargar X, llama-swap ya desalojó a los demás miembros del grupo
    `swap` (`EvictionFor`, `ls255/internal/router/group.go:70-104`). Con la topología de hoy,
    `cargado` está siempre vacío, y REQ-021 equivale en la práctica a «la capacidad nunca salta».
  - Las tools del rol largo no tienen ninguna celda (Non-goals), así que `long → cargado` nunca se
    resuelve.
- Arreglo: decir qué hace `cargado` sin el bloque B: queda vacío, y las cadenas efectivas son
  `code → long`, `long → code` y `mechanical → long`. Escribir en claro la consecuencia de REQ-021:
  hoy un fallo de capacidad no tiene respaldo, cuando antes saltaba al 4B. Y ordenar el plan para que
  C no consuma piezas que B puede no producir.

**7. La spec cita la decisión D-4 de F3, pero también cambia otros requisitos de F3 que no nombra.**
- Evidencia: además de D-4 (`delegacion-precisa-y-fiable/spec.md:529-533`), REQ-020 y REQ-021
  cambian:
  - **REQ-004 de F3** (`:283-296`): la regla «primero el residente», que sin grupo persistente cae al
    mecánico;
  - **REQ-018 de F3** (`:352-354`): la capacidad saltaba al residente;
  - la premisa de **D-3**.

  El plan de F3 dice que un residente no persistente «**reabre la spec y su gate**»
  (`delegacion-precisa-y-fiable/plan.md:636-640` y `:733-738`), y F3 todavía tiene gates abiertos.
- Arreglo: citar en REQ-020 y REQ-021 todos los requisitos de F3 que se enmiendan. Dejar constancia
  de la enmienda en F3 (una nota en su spec o en su `state.json`) y meter la decisión del usuario en
  «Decisiones» como enmienda de F3, no solo de D-4.

**8. El control del umbral de lentitud valida una magnitud distinta de la regla, y con datos que el daemon de la PC nunca verá.**
- Evidencia: `scratchpad/sdd-daemon/umbral_lento.py` usa la mediana de **toda la ventana** de
  `metrics.db`, que mezcla todos los clientes y las tandas de benchmark. La regla (REQ-025), en
  cambio, usa la **mediana móvil de los últimos 50 eventos** del log propio, con un mínimo de 10.
  Además, las filas que el control exige marcar (570, 571 y 573) son **llamadas de la Mac**
  (`insumos/llamaswap-grupos.md` §3) y nunca entran en el log del daemon de la PC. Y la regla no
  tiene en cuenta el tamaño del contexto: la generación se ralentiza con prompts largos, así que el
  26B con 30k de entrada puede salir «lento» sin estarlo.
- Arreglo: repetir **la regla exacta** (ventana de 50, mínimo 10, `tokens_out ≥ 8`) por origen: las
  filas de la PC, cruzadas con `usage-*.jsonl` como hizo el insumo, y las de la Mac con su log. Medir
  los falsos positivos en prompts de más de 10k tokens. Si los hay, comparar la mediana por tramos de
  tamaño de entrada.

**9. La evaluación del corpus nuevo (REQ-040 a 043) no garantiza que pueda distinguir.**
- **a) Repetir corridas a temperatura 0 no aporta información.** `local_classify` y `local_extract`
  van a `temperature=0.0` (`server.py:2310` y `:2359`). Las 5 corridas con semillas distintas
  (`benchmark.py:1238`) salen prácticamente idénticas, así que «mediana» y «al menos 4 de 5»
  dependen de una sola muestra por caso. Hay que decirlo y comprobar `response_sha256`.
- **b) Los pares de commit_msg no son independientes.** Los 30 pares son 6 casos por 5 corridas, y
  la prueba de signos los trata como independientes. Falta una condición por caso: por ejemplo,
  ningún caso con Qwen3.6 preferido en las 5 corridas, o el 26B no peor en al menos 4 de los 6.
- **c) La hoja no demuestra que el juicio distinga calidades.** «≠ peor» se cumple también cuando el
  juez no ve diferencias: muchos empates y el 26B queda aprobado sin haber distinguido nada. Las
  trampas solo prueban que el usuario presta atención. Hay que añadir pares de control con un
  mensaje que se sabe peor, por ejemplo de `qwen35-2b` o del tipo de F2 «se quedó con el bump y
  omitió el arreglo» (`protocolo-f2.md:525-527`). Si el usuario no los rechaza, la celda queda
  `sin base`. Y conviene un tope de empates.
- **d) Para `local_summarize` se reutiliza una métrica que ya falló.** «Salen los términos
  esperados» es la cobertura de términos que en F2 salió a cara o cruz (memoria «si no es el indio
  es la flecha»; `research.md:225-227`). Hay que cambiarla por hechos verificables (cifras, nombres,
  una conclusión concreta) o por juicio a ciegas.
- **e) El caso ambiguo de classify castiga respuestas defendibles.** Eso mete ruido, no capacidad de
  distinguir. Hay que aceptar el conjunto de etiquetas defendibles o quitar el caso.
- **f) Falta el orden de los dos desenlaces.** No se dice qué gana cuando el criterio 1 falla y
  también fallan otros: ¿`sin base` o `rechazada`? Hay que escribir que gana `sin base`.
- Lo que sí está bien: los criterios están escritos antes de medir, la regla para elegir los 5
  commits es mecánica, el programa produce el veredicto y un test lo ata al código.

**10. Matriz tool × modelo: no se define una celda sin evaluar ni qué pasa cuando el modelo cambia por dentro.**
- Evidencia: REQ-010 y REQ-011 dicen que las celdas fuera de las direcciones permitidas «no
  existen». Pero no dicen qué pasa con:
  - un modelo nuevo en el rol (una variable de entorno cambia `MODEL_LONG`);
  - una cuantización o unos flags distintos bajo el **mismo id** (por ejemplo, otro `-ncmoe`).

  En el segundo caso, la aprobación seguiría vigente sin haberse medido.
- Arreglo: escribir que una celda ausente de `veredicto.json` no se usa. Guardar en el veredicto la
  huella del modelo evaluado (ruta del GGUF y flags relevantes del `cmd`) y que `doctor` avise si ya
  no coincide.

**11. `--fijar` no puede aprobar ningún modelo con el estimador actual.**
- Evidencia: `estimate_model_vram` (`llamaswap_config.py:198-253`) cuenta **todos** los pesos como
  VRAM y no lee `-ncmoe`. Qwen3.6 (fichero de 17,7 GB) supera por sí solo los 14 GiB, y el 26B
  (13,6 GB más el KV) casi también. Con eso, `--fijar gemma3-4b` se rechaza, y es justo la
  combinación que se **midió** y cabe: residente más 26B, 13 804 MiB
  (`insumos/llamaswap-grupos.md` §2). El escenario negativo pasa siempre y no hay ninguno positivo.
- Arreglo: que el cálculo tenga en cuenta `-ncmoe`, o admitir cifras medidas por modelo (por ejemplo
  `--vram-modelo ID=GB`, con la tabla de F2 como origen). Añadir el escenario positivo «`--fijar
  gemma3-4b` con la config de hoy se acepta».

**12. CLI de residencia: credencial, la Mac, comprobar la recarga y la vuelta atrás.**
- **a) Credencial.** `/running` (y `/logs` o `/api/events`) exigen la API key (`apiKeys` en la
  config). La key la lee `config.API_KEY` (`config.py:67`), y en esta PC vive en el lanzador del
  daemon, no en la shell del usuario. Lo mismo pasa con `LLAMASWAP_CONFIG`. La spec no dice qué
  hacer ante un 401, y pedirle la key al usuario está vetado (memoria «verificación contra el
  backend real»). Arreglo: obtener el estado a través del daemon, que tiene la key, o definir que un
  401 significa «no se sabe»: se niega salvo con `--ahora` y lo explica.
- **b) Delegaciones de la Mac.** `inflight.json` solo ve los procesos de esta máquina, y `/running`
  solo muestra lo que ya está cargado. La foto de peticiones en vuelo de `/api/events` (hallazgo 4)
  ve también las de la Mac.
- **c) Un OK falso tras escribir.** «Comprueba que llama-swap sigue respondiendo» no distingue tres
  situaciones:
  - recargó con la config nueva;
  - **rechazó** la config y sigue con la vieja (`w255/llama-swap.go`: «failed to reload config»);
  - **no vigila** el fichero: `autostart` solo pone `-watch-config` si
    `LLAMASWAP_WATCH_CONFIG=1` (`autostart.py:59-60`).

  Arreglo: confirmar la recarga con `ConfigFileChangedEvent` en `/api/events` o con «configuration
  reloaded» en `/logs`, e informar de las tres salidas.
- **d) No hay vuelta atrás.** Se hace la copia, pero no hay ni requisito ni prueba para restaurarla.
  Y restaurar con una copia normal es una escritura **no atómica**, que puede disparar la recarga a
  medio escribir (`research.md:196-198`). Arreglo: añadir `residencia --restaurar <bak>` por el
  mismo camino atómico y con las mismas negativas, con su test.

**13. La edición quirúrgica solo está probada para cambiar un valor, no para mover bloques.**
- Evidencia: `scratchpad/sdd-daemon/quirurgico.py` solo **reemplaza un escalar** (el `ttl`). Pero
  `--ninguno` y `--fijar` borran un grupo, añaden miembros, crean grupos e insertan `ttl:` donde
  falta. Además, las dos configs del control tienen el mismo estilo de volcado de PyYAML. Gracias a
  la autocomprobación, lo frágil acaba en **negativas** y no en un fichero roto, pero el CLI puede
  quedar inservible con configs reales.
- Arreglo: tabla de casos de prueba con:
  - secuencias sangradas y sin sangrar;
  - comentarios en la misma línea y entre miembros;
  - un modelo sin `ttl`, insertado después de un `cmd` entre comillas en varias líneas o de un
    escalar `|`/`>`;
  - un grupo al final del fichero sin salto de línea final;
  - **fin de línea mixto**: existe uno real, `config.yaml.pre-b10909-20260915.bak` («CRLF, LF»);
  - BOM;
  - anclas, alias y `<<:` (rechazar);
  - claves duplicadas;
  - claves entre comillas;
  - la sintaxis `routing.router.settings.groups`.

  Y en Windows, reintentar `os.replace` si da una violación de compartición.

**14. La lista de ficheros compartidos con `panel-cuentas-y-estados-honestos` está incompleta.**
- Evidencia: la tabla de propiedad de su `plan.md` (`:35-48`) incluye también:
  - `src/local_delegate/config.py`: aquel añade una constante y este, tres variables;
  - `src/local_delegate/doctor.py`;
  - `tests/test_checks.py` y `tests/test_doctor.py`;
  - `tests/test_observabilidad_respaldo.py`: aquí cambian el respaldo y la afinidad;
  - `tests/test_fallos_integracion.py`;
  - `tests/test_sondeo_backend.py` y `tests/test_panel_estados.py`, que son nuevos;
  - `CHANGELOG.md` y `scripts/dev/capture_dashboard.py`, que es el mock del panel y tendrá que
    llevar los campos nuevos;
  - `docs/wiki/Troubleshooting.md`, `Daemon.md` y `Remote-backend.md`;
  - en `server.py`, la zona `_models_with_status`/`_llamaswap_running` (`:2982-3017`), que aquí
    también se toca por `/running`.

  Y falta `tests/test_wiki.py`: su `_NUMERO_DE_CHECKS` cambia con los checks nuevos de topología y
  residencia.
- Arreglo: completar la lista y avisar de que los números de línea del research se moverán al
  rebasar.

### MENOR

- **15. El camino feliz sí hace una consulta de red.** El paso 1 de REQ-012 («si el modelo del rol
  está cargado») necesita `/running` salvo que haya una llamada propia en vuelo. Así que «sin
  consultas de red» solo es cierto cuando la tool no tiene celdas aprobadas. Hay que reescribirlo.
- **16. El redondeo del escenario de lentitud no cuadra.** Con 15 / 40 sale 0,375, que redondea a
  0,38, no a 0,37. Fijar la mediana exacta (por ejemplo, 40,5).
- **17. La cifra del mutante es de ruamel.** «Un mutante con `safe_dump` cambia 38 líneas» es la
  cifra de ruamel. Con PyYAML el mutante falla por otras líneas: se pierden los comentarios de la
  cabecera y cambian las comillas de `apiKeys`. Hay que corregirla.
- **18. El veredicto de residencia contradice a `--ninguno`.** «Sin residente (recomendado)» sale
  aunque haya un modelo con TTL efectivo 0 en un grupo `swap`, que se queda cargado en reposo
  indefinidamente: justo lo que el usuario no quiere. Que el veredicto exija «ningún TTL efectivo 0»,
  igual que `--ninguno`.
- **19. El TTL sugerido no es el del usuario.** REQ-030 sugiere 300, y el usuario eligió 120.
  Sugerir el TTL de los demás modelos de texto.
- **20. La dirección de visión de REQ-011 está vacía.** Solo `gemma4-12b` lleva `--mmproj`, y ya es
  el modelo del rol. Quitarla o decirlo.
- **21. Falta el desempate entre dos alternativos.** Si hay dos alternativos aprobados y cargados a
  la vez (solo es posible con un residente opcional), la spec no dice cuál se elige.
- **22. Los alias en la consulta de actividad.** `/api/metrics/activity` admite `?model=` repetido:
  hay que consultar el id real y sus alias.
- **23. Calcular la mediana sin releer el log en cada llamada.** Leer dos meses de JSONL por evento
  es caro. Mejor una ventana en memoria que se siembra al arrancar.
- **24. Hoja de commit.** Las trampas («el mensaje de **otro** commit») son demasiado fáciles: mejor
  un commit de la misma zona del código. Y si la hoja se repite, que lleve pares en otro orden y
  trampas nuevas.
- **25. La regla de los 5 commits puede dar menos de 5.** Hay que definir cómo se completa, por
  ejemplo ampliando hacia atrás.
- **26. Las recargas no se cuantifican.** El brief dice que el research cuantifica las recargas y no
  lo hace: falta cuántas habrá y su coste, porque cada una deja una carga en frío de 6 a 14 s.
- **27. El orden de llegada estricto obliga a un cambio de más.** En el escenario de la inanición:
  26B, Qwen3.6 y luego tres del 26B suman dos cambios. Una ventana corta en la que se permita unirse
  dejaría uno solo. Es una decisión para el usuario.
- **28. No se comprobaron los plazos de los clientes MCP.** Falta ver qué hacen Claude Code y Codex
  con una llamada que espera hasta 600 s de turno más la inferencia.
- **29. La copia de `init-llamaswap` se sigue pisando.** Su `.bak` fijo (`cli.py:573-578`) se pisa
  en cada ejecución. Conviene alinearlo con REQ-033.
- **30. El llama-swap de prueba no debe escribir en el `metrics.db` real.** Tiene que usar su propio
  `store` o ninguno, porque esa base se está midiendo.

### Lo que la revisión comprobó y está bien

- REQ-001 reproduce `EvictionFor` y `AddDefaultGroupToConfig` de la v255 (`group.go:70-104`,
  `src_config.go:294-336`), con los valores por defecto correctos.
- El diagnóstico de `cadenas.py` es exacto: `residente()` cae al mecánico y `doctor` dice «residente
  gemma3-4b» (`cadenas.py:53-77`, `checks.py:1363-1364`).
- Las cifras de los incidentes cuadran con el insumo: 6 cambios y 199 s; unos 47 s de la Mac;
  6,8–20 tok/s.
- Las citas de D-4 (`:529-533`) y de REQ-018 de F3 son correctas en lo que dicen. Lo que les falta
  se explica en el hallazgo 7.
- El research justifica bien que no haga falta ninguna dependencia nueva.

### Llamadas `local_*`

**0.** No cargué las tools. Ya no queda ningún modelo residente, así que cualquier llamada habría
descargado el que estuviera cargado y cargado otro, y habría añadido filas a `metrics.db`, que se está
midiendo (P-4 y F1). Además, la revisión necesitaba el texto literal para citar `fichero:línea`, así
que leí los ficheros grandes por franjas y con `grep`.

## Verdict

Choose one: `conforms`, `conforms-with-notes`, or `does-not-conform`.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | | | |

## Findings

- List correctness, security, maintainability, or scope findings in severity order.

## Required follow-up

- Identify work that must be completed before closure.

## Respuesta a la revisión

Corrección de `spec.md` y `research.md` del 2026-10-06 (tarde). Se mantienen los números de requisito
cuando el significado no cambia. Los nuevos son REQ-037 (enmienda de F3), REQ-038 (`--restaurar`) y
REQ-039 (credencial y vigía de recarga). La investigación nueva está en `research.md`, «Correcciones
tras la revisión de la spec», con el código de llama-swap v255 bajado a `scratchpad/ls255v2/`
(`process_command.go`, `store.go`, `logging.go`).

### Bloqueantes e importantes

| # | Hallazgo | Resolución | Dónde quedó |
| --- | --- | --- | --- |
| 1 | Turno y plaza pueden bloquearse en un salto de respaldo | Orden único de adquisición: turno antes que plaza, y nunca se pide turno con plaza en la mano. Un salto suelta la plaza y sale del turno antes de pedir el nuevo, al final de la cola. Se demuestra que el grafo de esperas no tiene ciclos: quien tiene plaza solo espera a cosas externas con tope. Hay escenario con dos plazas, dos saltos simultáneos y una troceada con el turno; el mutante que conserva la plaza falla en el assert de progreso a los 2 s, con la red de seguridad a 60 s para que no lo tape | REQ-004, REQ-006, «Por qué turno y plaza no pueden bloquearse», escenario «dos saltos a la vez no bloquean», control «Bloqueo turno/plaza», REQ-037 (enmienda de REQ-017 de F3) |
| 2 | Turno circular, afinidad colándose y turno de un solo modelo | Máquina de estados: la operación calcula sin red su conjunto aceptable. El turno es un conjunto `activos` con reservas, y la concesión depende solo de la compatibilidad y del orden de llegada. El modelo se elige después, con una función pura sobre la foto observada. La afinidad no se cuela; la única excepción escrita (E-1) es para un modelo compatible con todo lo que se usa y lo que se espera, con justificación y cota. Escenarios: afinidad con alguien esperando, afinidad sin nadie y residente compatible | REQ-003, REQ-005, REQ-012, tres escenarios nuevos, control «Turno: orden y E-1» |
| 3 | TTL de 300 en la spec y margen de 60 s sin justificar | Todo pasa a 120/30. Margen de 5 s deducido de cómo cuenta el TTL la v255: desde el final de la última petición, congelado con peticiones en vuelo y con un tic de 1 s. La foto se toma con la plaza en la mano, así que la carrera son milisegundos. Pares de control «quedan 3 s → rol» y «quedan 40 s → alternativo». La prueba de la carrera puede subir el margen | REQ-013, escenarios de afinidad, control «Carrera real y semántica del TTL», `research.md` «Cómo cuenta el TTL» |
| 4 | El TTL restante es una estimación; `/api/events` da lo que falta | Se usa `/api/events` (foto de las peticiones en vuelo de todos los clientes) y `ts_created` de la actividad, con la semántica del TTL leída en `process_command.go`, y la prueba lo comprueba en ejecución. **Discrepo en dos puntos, con evidencia:** (a) «un modelo con una petición en vuelo está cargado» no es cierto: el rastreador registra la petición en el middleware, antes de la cola del router (`inflight.go:380-395`). Por eso se exige `ready` y se trata como «cambio pendiente» una petición en vuelo para un modelo que choca y no está listo. (b) La cabecera `Date` no hace falta: la afinidad solo corre con backend local (la Mac está fuera), que comparte el reloj, y `Date` tiene resolución de 1 s. Se registra `afinidad_fallida` cuando no había peticiones ajenas en vuelo (si las había, la espera puede ser de cola y no de carga) | REQ-013, REQ-016, REQ-017, escenarios «trabajando para otro cliente» y «cambio pendiente», `research.md` «Qué expone la v255» |
| 5 | Tope absoluto de 600 s; qué pasa al vencer; esperas canceladas | La red mide **falta de progreso** de `activos`: ninguna llamada al backend empieza ni termina en 600 s; cada llamada termina en 180 s como mucho. Al vencer, la cabeza se concede **forzada** (`turno: "forzado"`). Cancelación: si el SDK la entrega al hilo, sale de la cola; si no, la operación se ejecuta como hoy y no queda una espera fantasma. Lo comprueba una tarea contra el SDK instalado. El valor de 600 s es del usuario; el cambio de lo que mide está en «Decisiones» | REQ-007, escenario «sin progreso», control «Red de seguridad sin progreso» |
| 6 | `cargado` depende de B; con un solo grupo casi nunca existe | Sin B la matriz está vacía y `cargado` no tiene miembros, sin consultar la red. Cadenas efectivas escritas: `code → long`, `long → code`, `mechanical → long`. Consecuencia escrita: hoy un fallo de capacidad no tiene respaldo. C no puede depender de piezas de B | REQ-019, REQ-020, REQ-021 |
| 7 | F3 enmendada en más puntos de los que se citan | Tabla con cada punto de F3 y su texto (REQ-004, REQ-017, REQ-018, D-3, D-4, P-3, el requisito de VRAM y tres escenarios), y cómo se registra: un punto en «Cambios respecto al original» de la spec de F3, un evento en su `state.json` con el harness y una nueva aprobación del gate `spec` de F3 por el usuario, antes de mezclar C. No se tocó la carpeta de F3 | REQ-037 |
| 8 | El control del umbral mide otra magnitud con datos de la Mac | El control repite la regla exacta (ventana de 50, mínimo 10, `tokens_out ≥ 8`, agrupando por evento) sobre las filas de la PC. Las filas de la Mac quedan solo como control positivo de la regla, declarado como tal. Se añade el control por tamaño de entrada, que decide de antemano si la referencia va por tramos | REQ-025, controles «Umbral de lentitud» y «Lentitud y tamaño de la entrada», nota en `research.md` |
| 9a | Repetir a temperatura 0 no informa | Una corrida por caso y más casos distintos (8/8/4/4/4 en las mecánicas, 30 en commit). El techo conserva 3 corridas porque es una prueba de fiabilidad | REQ-040, REQ-041 |
| 9b | Los 30 pares no son independientes | 30 commits distintos con una corrida cada uno; la regla de selección da 104 candidatos | REQ-040, `research.md` «Plazos, cancelación y temperatura» |
| 9c | La hoja no prueba que el juicio distinga | Se integran las 3 trampas del brief como prueba de discriminación: misma zona, lo secundario y genérico, todas con buen formato. La hoja solo vale si el usuario marca como peor al menos 2 de las 3. No se añade tope de empates: con las trampas superadas, muchos empates significan calidad parecida, que es justo lo que pide la no inferioridad | REQ-042, criterio 0 de la celda de commit |
| 9d | `local_summarize` reutiliza la métrica que falló en F2 | Queda fuera de la matriz, declarado en Non-goals | REQ-011, Non-goals |
| 9e | El caso ambiguo de classify mete ruido | Conjunto de etiquetas aceptables declarado antes de medir; un caso que solo se sostiene con una respuesta discutible se quita | REQ-040 |
| 9f | Orden de los desenlaces | Escrito: si falla el criterio 1 (o el 0 en commit), `sin base` gana; si no, cualquier otro fallo da `rechazada` | Criterio de aceptación de las celdas |
| 10 | Celda sin evaluar y cambios bajo el mismo id | Clave (tool, alternativo, modelo del rol) y huella (GGUF, flags, sha del prompt). Una celda ausente o con la huella distinta no se usa y `doctor` avisa | REQ-010, escenario «la huella cambió» |
| 11 | `--fijar` no puede aprobar nada con el estimador actual | Primero `--vram-modelo` (cifras medidas); después el estimador ampliado con `-ncmoe` (bytes de los tensores de expertos sacados de los offsets del GGUF), solo si pasa el control contra lo medido (−3 %/+10 %). Escenario positivo «fijar el 4B se acepta» con números | REQ-031, control «Estimador de VRAM», `research.md` «Estimador de VRAM» |
| 12a | Credencial | El CLI pregunta al daemon (que tiene la key) por endpoints nuevos tras el token web; si no, usa la key del shell; si no, «no se sabe»: se niega salvo con `--ahora`, sin pedir la key | REQ-039, escenario «sin credencial» |
| 12b | Delegaciones de la Mac | Las negativas usan la foto de `/api/events`, que ve todos los clientes | REQ-034 |
| 12c | Un OK falso tras escribir | Vigía suscrita a `/api/events` antes de escribir, con cuatro salidas: recargó, rechazó (y restaura la copia), no vigila y caído. Por qué una suscripción y no `/logs`: el log no lleva hora por defecto | REQ-034, REQ-039, `research.md` «Recarga de la config» |
| 12d | Sin vuelta atrás | `--restaurar <bak>` por el camino atómico, con las mismas negativas; control con un lector en bucle y un mutante que copia en dos pasos | REQ-038, control «Restaurar» |
| 13 | La edición quirúrgica solo probó un escalar | Tabla de casos en el control (sangrías, comentarios, inserción tras `cmd` plegado y tras escalares de bloque, sin salto final, fin de línea mixto real, BOM, comillas, sintaxis `routing`) y rechazo de anclas, alias, `<<:` y claves duplicadas. Reintento de `os.replace` en Windows | REQ-033, control «Edición quirúrgica» |
| 14 | Lista de ficheros compartidos incompleta | Completada contra el `plan.md` de aquel, **reescrito a las 11:54**: aparecen `_run_chat` con `esperando_plaza`, `_inflight_start`, `sondear_backend`, `tests/conftest.py` y `tests/test_delegacion_conexion.py`. **Hallazgo nuevo:** su panel usa «esperando turno» para «llama-swap aún no la atiende» (su REQ-022, fila 9). Una llamada que espera nuestro turno caería ahí y el panel culparía a llama-swap; REQ-027 lo resuelve ampliando su fila 3 («en cola local») | «Ficheros compartidos», REQ-008, REQ-027 |

### Menores

| # | Hallazgo | Resolución | Dónde quedó |
| --- | --- | --- | --- |
| 15 | El camino feliz sí consulta la red | Reescrito: no hay red sin celdas aprobadas, con el modelo en uso propio o con backend remoto; si no, hasta tres consultas de 1 s, solo en la primera llamada | Non-functional |
| 16 | Redondeo del escenario | Mediana 40,5 → 0,37 | Escenario de lentitud |
| 17 | Cifra del mutante de ruamel | Corregida: con `safe_dump` falla por los comentarios de cabecera y las comillas de `apiKeys`; el número lo da el test | Control «Edición quirúrgica» |
| 18 | Veredicto «sin residente» con TTL 0 | Sin residente solo si ningún modelo tiene TTL efectivo 0 | REQ-029, REQ-023 |
| 19 | TTL sugerido | El más frecuente entre los demás modelos sin `--mmproj` (hoy, 120) | REQ-030 |
| 20 | Dirección de visión vacía | Quitada, y se dice por qué | REQ-011 |
| 21 | Desempate entre alternativos | Con una petición en vuelo; más TTL restante; orden de la cadena; id | REQ-012 |
| 22 | Alias en la actividad | llama-swap resuelve al id real (`swaputil/http.go:242-246`); se consulta por el id real y la prueba con el llama-swap de prueba lo comprueba; si no, se piden también los alias | Edge cases, control «Carrera real» (c) |
| 23 | Mediana sin releer el log | Ventana en memoria que se siembra al arrancar | REQ-025 |
| 24 | Trampas demasiado fáciles; hoja repetida | Trampa de la misma zona (otro commit que toca el mismo fichero) más otras dos de buen formato; una hoja repetida lleva otro orden y trampas nuevas | REQ-042 |
| 25 | La regla puede dar menos de 5 commits | Cómo se amplía, escrito; hoy hay 104 candidatos | REQ-040 |
| 26 | Recargas sin cuantificar | Medido: 5 cargas en frío de más en 20,8 días (~70 s) con TTL 120 frente a 300 | `research.md` «Cuántas cargas en frío de más» |
| 27 | Orden estricto: un cambio de más | Se deja estricto y se pasa al usuario como decisión (recomendado: estricto) | «Decisiones», punto 9 |
| 28 | Plazos de los clientes MCP | **Queda abierto**: no se pudo comprobar sin el cliente; es una tarea del plan, y se documenta en la wiki | Edge cases, `research.md` |
| 29 | `.bak` fijo de `init-llamaswap` | Pasa al nombre con fecha | REQ-035 |
| 30 | El llama-swap de prueba y el `metrics.db` real | Usa su propio `store` en una carpeta temporal. Además, la ventana de la tanda real se anota para excluirla de P-4 y F1 | Controles, REQ-041 |

### Lo que queda abierto

- El plazo real de Claude Code y Codex para una tool MCP (hallazgo 28).
- Si el SDK MCP instalado entrega la cancelación al hilo de la tool (REQ-007): una tarea lo comprueba;
  los dos resultados ya tienen comportamiento escrito.
- Las decisiones nuevas para el usuario, en «Decisiones que necesitan al usuario» de `spec.md`. Las
  principales: los 600 s como «sin progreso», la lectura `c ≥ v` de «no pierde», 30 commits
  distintos, `local_summarize` fuera y la restauración automática si llama-swap rechaza la config.

### Llamadas `local_*`

**0.** Cargué `local_summarize` y `local_extract` como pedía el encargo, pero no las usé. No hay
residente, así que cualquier llamada habría descargado el modelo cargado y añadido filas a
`metrics.db`, que se está midiendo. Además, la corrección necesitaba el texto literal para citar
`fichero:línea`: la spec de F3, el código de llama-swap y el plan del panel, que se leyeron por
franjas y con `grep`.

## Segunda pasada

Revisión de `spec.md` corregida (12:08), en solo lectura, el 2026-10-06. La contrasté con `brief.md`,
`research.md` («Correcciones tras la revisión de la spec»), la spec de `panel-cuentas-y-estados-honestos`
(versión de las 12:10) y su `plan.md`, la spec de F3, `server.py` y el código de llama-swap v255 del
scratchpad (`ls255v2/`, `ls255/`, `docs-v255/`). Cada veredicto lo comprobé en el texto de `spec.md`,
no en la tabla de respuesta.

### Veredicto

**La spec todavía no se puede aprobar.** Las correcciones están bien hechas y resuelven casi todos los
hallazgos de la primera pasada. La demostración de que turno y plaza no se bloquean se sostiene, y lo
que dice del TTL de la v255 es correcto. Pero aparece un **bloqueante nuevo**: la spec redefine la fila
«en cola local» del panel con unos campos (`esperando_plaza`, `esperando_turno`) que la spec ya
aprobada del panel sustituyó por el campo genérico `espera_local`. Hay además dos hallazgos importantes
nuevos: cuándo se vuelve a evaluar la concesión del turno, y un supuesto sin escribir del que depende la
red de seguridad.

### Tabla de veredictos de la primera pasada

| # | Hallazgo | Veredicto | Comprobación en `spec.md` |
| --- | --- | --- | --- |
| 1 | Turno y plaza pueden bloquearse en un salto | **Resuelto** | REQ-004 (el turno siempre antes que la plaza), REQ-006 (el salto suelta la plaza y sale de `activos` antes de pedir turno), la demostración del grafo de esperas, el escenario «dos saltos a la vez no bloquean» con `TURNO_MAX_S = 60` y assert de progreso, y REQ-037 (enmienda de REQ-017 de F3). Ver «Bloqueo mutuo» abajo |
| 2 | Turno circular, afinidad que se cuela, turno de un solo modelo | **Resuelto**, con un hueco nuevo | REQ-003 define el conjunto aceptable, `activos` con reservas, `A'` y la elección después de obtener la plaza. REQ-005 trae E-1 con justificación y cota, y hay tres escenarios. El hueco (qué eventos vuelven a evaluar la concesión) va como hallazgo nuevo 2 |
| 3 | TTL de 300 y margen de 60 s | **Resuelto** | En `spec.md` ya no queda ni un 300 ni un 240. Los escenarios usan 120, están los pares «quedan 3 s → rol» y «quedan 40 s → alternativo», y REQ-013 fija un margen de 5 s. Ver «TTL» abajo |
| 4 | El TTL restante es una estimación; `/api/events` | **Resuelto**, y las dos discrepancias **se sostienen** | REQ-013 (foto de `/api/events` y condiciones a-c), REQ-016 (`afinidad_fallida`) y los escenarios «trabajando para otro cliente» y «cambio pendiente». Ver «Discrepancias» abajo |
| 5 | Tope absoluto de 600 s, vencimiento y esperas canceladas | **Parcial** | REQ-007 ya mide la falta de progreso y define la concesión forzada y la cancelación. Faltan dos cosas: quién dispara la comprobación de los 600 s (hallazgo nuevo 2), y que la justificación depende de que `HTTP_TIMEOUT` sea menor que 600 s, cuando se puede configurar (hallazgo nuevo 3) |
| 6 | `cargado` depende de B | **Resuelto** | REQ-019 (sin B, `cargado` queda vacío sin consultar la red, y C no depende de B), REQ-020 (cadenas efectivas) y REQ-021 (consecuencia escrita) |
| 7 | F3 enmendada en más puntos | **Resuelto** | La tabla de REQ-037 recoge REQ-004, REQ-017, REQ-018, D-3, D-4, P-3, el requisito de VRAM y tres escenarios. Comprobé las líneas que cita de la spec de F3 (`:283`, `:351-355`, `:528-533`, `:234-235`, `:505-507`, `:376`, `:384`, `:435`) y `plan.md:738` de F3. El registro y la nueva aprobación del gate de F3 van antes de mezclar C |
| 8 | El control del umbral mide otra magnitud | **Resuelto** | REQ-025 (ventana en memoria y tramos decididos por un control), y los controles «Umbral de lentitud: la regla exacta» (filas de la PC; las de la Mac solo como control positivo) y «Lentitud y tamaño de la entrada» |
| 9a | Repetir a temperatura 0 | **Resuelto** | REQ-040 y REQ-041: una corrida por caso y más casos. El techo conserva 3 corridas, y está justificado |
| 9b | Los pares de commit no son independientes | **Resuelto** | 30 commits distintos, con regla mecánica y la forma de ampliar escrita |
| 9c | La hoja no prueba que el juicio distinga | **Resuelto**; lo del tope de empates es una **discrepancia justificada** | Criterio 0: 3 trampas, la hoja vale con 2 de 3, y tras dos repeticiones fallidas la celda queda `sin base`. No pone tope de empates porque, superadas las trampas, un empate indica calidad parecida, que es justo lo que pide la no inferioridad. El razonamiento se sostiene |
| 9d | Métrica de summarize que ya falló | **Resuelto** | Queda fuera de la matriz (REQ-011, Non-goals) |
| 9e | Caso ambiguo de classify | **Resuelto** | REQ-040: el conjunto de etiquetas aceptables se declara antes de medir |
| 9f | Orden de los desenlaces | **Resuelto** | Está escrito para las celdas mecánicas y para commit |
| 10 | Celda sin evaluar y cambios bajo el mismo id | **Resuelto** | REQ-010: clave de tres elementos, huella (GGUF, flags y sha del prompt), una celda ausente cuenta como `sin base` y `doctor` avisa. Escenario «la huella cambió» |
| 11 | `--fijar` imposible con el estimador | **Resuelto** | REQ-031 usa primero `--vram-modelo`, y el estimador con `-ncmoe` solo si pasa su control. El escenario positivo trae cifras que cuadran (3,19 + 10,29 = 13,48 ≤ 14) |
| 12a | Credencial | **Resuelto** | REQ-039: primero el daemon, después la key del shell y, si nada funciona, «no se sabe», sin pedir la key. Escenario «sin credencial» |
| 12b | Delegaciones de la Mac | **Resuelto** | REQ-034 usa la foto de `/api/events` |
| 12c | Un OK falso tras escribir | **Resuelto** | REQ-034: la vigía se abre antes de escribir y hay cuatro salidas. Control «Recarga» |
| 12d | Sin vuelta atrás | **Resuelto** | REQ-038 y el control «Restaurar», con el mutante que copia en dos pasos |
| 13 | Edición quirúrgica probada solo con un escalar | **Resuelto** | Control «Edición quirúrgica» con la tabla de casos y los rechazos, y el reintento de `os.replace` en REQ-033 |
| 14 | Ficheros compartidos con el panel | **Parcial** | La lista de ficheros está completa, pero cita el contrato del panel de las 11:54, que ya no vale: ver el bloqueante nuevo 1 |

### Bloqueo mutuo entre turno y plaza

Intenté construir un ciclo y no encontré ninguno. Probé estos casos:

- **Tres operaciones y dos saltos a la vez**, el escenario de la spec. A y B sueltan su plaza antes de
  ponerse en la cola, así que C consigue plaza y termina. No hay ciclo.
- **Un salto mientras otra operación espera.** El salto sale de `activos` y se pone al final de la cola.
  Las que esperan delante de él no dependen de él para nada. No hay ciclo.
- **El cliente cancela a mitad de camino.** Lo comprobé en el SDK instalado: `mcp` 2.2.0 ejecuta las tools
  síncronas con `anyio.to_thread.run_sync(functools.partial(fn, **kwargs))`, sin `abandon_on_cancel`
  (`.venv/Lib/site-packages/mcp/server/mcpserver/utilities/func_metadata.py:164`). La cancelación nunca
  llega al hilo, así que se aplica la segunda rama de REQ-007: la operación sigue como hoy y no deja
  ninguna espera fantasma. No hay ciclo.
- **Concesión forzada.** Deja en `activos` dos modelos que chocan. llama-swap va alternando entre ellos,
  pero cada llamada termina como mucho en `HTTP_TIMEOUT`. Es un vaivén, no un bloqueo.
- **Llamadas anidadas con una plaza ocupada.** Los trozos de una operación van uno detrás de otro
  (`server.py` no crea ejecutores ni hilos propios), y `_con_respaldo` no vuelve a llamar a `_run_chat`.
  Quien tiene una plaza solo espera a la red, y esa espera tiene tope.

La demostración se sostiene, pero le faltan dos cosas por escribir:

- **Plazas en manos de una operación sin turno.** Una operación sin turno (REQ-002) puede tener una
  plaza. Eso no rompe la demostración, porque tampoco espera nada del daemon, pero conviene decirlo.
- **Esperas que se quedan paradas sin motivo.** No es un ciclo, pero la cola deja de avanzar cuando
  podría: ver el hallazgo nuevo 2.

### TTL de llama-swap v255, comprobado en el código

Lo que afirma la spec es **correcto**:

- `lastUse` es la hora en que **terminó** el último `ServeHTTP` (`ls255v2/process_command.go:132`). Se
  guarda en un `defer` al salir de `ServeHTTP`, junto con `inflight.Add(-1)` (`:804-808`), y es el único
  sitio donde se escribe (`:806`).
- La gorrutina del TTL hace una comprobación cada segundo (`:346-363`). Si hay alguna petición dentro del
  proceso, se salta la comprobación (`if p.inflight.Load() != 0 { continue }`), así que el reloj
  **queda congelado**. Si no hay ninguna, descarga el modelo cuando `time.Since(lastUse) > ttlDuration`.
- `ts_created` se fija con `time.Now()` en `record` (`docs-v255/src_metrics.go:137-143`). `record` se
  llama **en el mismo hilo**, justo después de `next.ServeHTTP` (`docs-v255/src_mm.go:78-82`), y la hora
  se guarda truncada al segundo (`ls255v2/store.go:210`, `entry.Timestamp.Unix()`). Por eso `ts_created`
  nunca es anterior a `lastUse`, y el truncado deja la estimación del lado prudente.
- Hay un detalle que la spec no cita y que confirma uno de sus casos límite: `lastUse` no tiene valor al
  arrancar. Un modelo precargado con TTL mayor que 0 se descarga en la primera comprobación, lo que
  cuadra con el caso «recién cargado por precarga: no cuenta».

**El margen de 5 s.** Se apoya en el código, que sí comprobé: la carrera dura lo que va del cálculo a
`inflight.Add(1)`, que son milisegundos. **No se apoya en una medición de la carrera**, porque esa
medición es el apartado (b) del control «Carrera real» y todavía no se ha hecho. Así que la spec
exagera al decir que el margen «lo fija la carrera real». Además, el apartado (b) casi no puede fallar
(milisegundos frente a 5 s): sirve para confirmar que todo está en orden, pero no decide el margen. El
que sí puede fallar y decide es el apartado (a): una petición de 3 s con `ttl: 2` que se descarga entre 2
y 4 s después de terminar. Si el TTL contara desde que empieza la petición, la descarga llegaría entre
0 y 1 s después y el control fallaría. Doy el margen por justificado, porque cubre con mucha holgura
una ventana que, según el código, es de milisegundos. Hay que corregir el texto (menor): decir «lo
justifica el código y lo comprueba la prueba» y quitar que el margen «cubre el tic», porque esa
comprobación de cada segundo retrasa la descarga, no la adelanta.

### Las dos discrepancias con la primera pasada

- **(a) Que haya una petición en vuelo no prueba que el modelo esté cargado: se sostiene.**
  `CreateInflightMiddleware` registra la petición (`t.Add`) antes de llamar a `next.ServeHTTP`
  (`ls255/internal/server/inflight.go:377-395`). En `modelChain`, ese middleware y el de métricas
  envuelven a `dispatch`, es decir, al router con su cola y su carga
  (`ls255/internal/server/server.go:302-325`). Una petición en vuelo puede estar esperando a que su
  modelo se cargue. La spec lo resuelve bien: exige `ready`, y trata como «cambio pendiente» una petición
  en vuelo hacia un modelo que choca y no está `ready`.
- **(b) La cabecera `Date` no hace falta: se sostiene.** La afinidad solo actúa con el backend en la
  propia máquina (REQ-002 y REQ-017), que tiene el mismo reloj que llama-swap. Además, `Date` solo
  precisa hasta el segundo, menos que el reloj local. Matiz para el plan: `ahora` tiene que salir de
  `time.time()`, la hora del sistema, que se puede comparar con `ts_created`. No vale `time.monotonic()`.

### Si la spec recoge al pie de la letra las decisiones del usuario

| Decisión (brief) | En la spec | Veredicto |
| --- | --- | --- |
| 26B frente a Qwen3.6 en commit_msg: el usuario elige el del 26B al menos tantas veces como el del modelo de código | Criterio 2: `c ≥ v` sobre los pares reales | Fiel |
| Los «me da igual» no suman a ninguno | «los empates par a par no suman a nadie» | Fiel |
| Inventa algo en menos de 1 de cada 10 | Criterio 1: «fiel = no» en menos del 10 %, es decir, 2 de 30 como mucho (el 10 % de 30 son 3, y «menos de 3» son 2) | La cuenta está bien. Hay un matiz de redacción: hallazgo nuevo 6 |
| Hacen falta 2 de 3 trampas; si no, la tanda no vale y se repite | Criterio 0 | Fiel. Añade «hasta dos veces; si no, `sin base`», una ampliación razonable y declarada |
| `local_summarize` fuera | REQ-011 y Non-goals | Fiel |
| El código y el largo nunca caen al mecánico | REQ-011, REQ-020 y el escenario «código nunca cae al mecánico» | Fiel |
| 600 s | REQ-007 los cuenta como 600 s «sin progreso», no como espera total | Cambia lo que se mide. Está declarado como decisión 1, **pendiente** de que el usuario la confirme |
| Umbral de 0,5 | REQ-025 | Fiel |
| La Mac y Claude Desktop fuera | Summary, REQ-017, Non-goals y casos límite | Fiel |

La spec añade a la regla de commit dos condiciones previas (el techo y la fiabilidad, en el criterio 3)
que pueden **rechazar** una celda que la regla del usuario aprobaría. Están declaradas como decisión 4, y
el usuario tiene que confirmarlas antes del gate.

### Hallazgos nuevos

**BLOQUEANTE**

**1. La spec redefine la fila «en cola local» del panel en vez de rellenar `espera_local`.**
- Evidencia: la spec del panel (versión de las 12:10, REQ-022,
  `panel-cuentas-y-estados-honestos/spec.md:303` y `:317-329`) ya establece que **toda** espera dentro de
  local-delegate se publica en un solo campo, `espera_local`, con el motivo como texto (hoy `"plaza"`). La
  fila 3 vale para **cualquier** motivo y, sobre el turno de este cambio, dice que «solo tiene que
  escribir `espera_local` con su propio motivo… no hace falta tocar la tabla ni `estadoModelo`». Su
  `plan.md:412` ya prueba un motivo que el panel no conoce (`"turno_grupo"`), y su `plan.md:402` tiene un
  mutante para la lista blanca de claves de `/api/inflight`. Esta spec, en cambio:
  - en REQ-008 usa `esperando_plaza`, que ya no existe, y una clave nueva, `esperando_turno`;
  - en REQ-027 **reescribe la condición de la fila 3**: «todas esas llamadas llevan `esperando_plaza`
    **o** `esperando_turno`»;
  - en «Ficheros compartidos» cita «el ayudante de `esperando_plaza`».

  Implementada así, rompe el contrato del panel. Con la lista blanca de `/api/inflight`, la clave
  `esperando_turno` ni siquiera llegaría al panel, y la espera de turno caería en la fila 9, que es
  justo lo que REQ-027 quiere evitar.
- Arreglo:
  - REQ-008: mientras espera turno, `espera_local: "turno"`, escrito con el ayudante del panel. Cuando ya
    tiene turno y espera plaza, `espera_local: "plaza"`. Así se cumple solo «nunca las dos a la vez»,
    porque es un único campo. La lista de modelos de `activos` y la posición en la cola van en claves
    aparte (por ejemplo, `turno_en_uso` y `turno_posicion`) que no deciden la fila, y hay que añadirlas a
    la lista blanca de `/api/inflight`.
  - REQ-027: quitar la redefinición de la fila 3. Al panel solo hay que añadirle palabras para el motivo
    `"turno"`, en el `title` y en «En curso» («esperando turno del daemon (en uso: <modelos>)»), algo que
    la spec del panel deja como opcional.
  - Corregir «Ficheros compartidos» y cualquier escenario que cite los campos viejos.
  - Añadir un test: con `espera_local: "turno"`, la fila dice «en cola local» y el `title` nombra el
    turno. Un mutante que escriba la clave vieja tiene que hacerlo fallar.

**IMPORTANTE**

**2. La concesión no se vuelve a evaluar en todos los momentos en que puede cambiar.**
- Evidencia: REQ-003 solo la evalúa «cuando llega una petición y cada vez que una operación sale de
  `activos`». Hay otros cuatro momentos que cambian el resultado y no la provocan:
  - **cuando una reserva se reduce al elegir modelo** (REQ-003, «Elección»). Contraejemplo: con `activos`
    vacío llega W1, un `local_classify` con dos celdas aprobadas, y se queda con la reserva {4B, 26B,
    Qwen3.6}. Llega W2, un `local_lint_summary` para el 26B, y se queda en la cola porque el 26B choca con
    el 4B y con Qwen3.6, que están en la reserva. W1 elige el 26B. Ahora W2 ya podría unirse, pero nadie
    vuelve a mirar la cola hasta que W1 termina, y con 13 trozos eso son minutos. Es la serialización del
    mismo modelo que prohíbe el escenario «el mismo modelo no se serializa de más»;
  - **cuando la cabeza sale de la cola porque la cancelan**: la siguiente, que quizá sea compatible,
    sigue esperando hasta que alguien salga de `activos`;
  - **cuando vencen los 600 s sin progreso**: si no llega nadie ni sale nadie, la condición no se
    comprueba nunca, y la red de seguridad no salta justo cuando hay un atasco, que es lo único para lo
    que sirve. El escenario «sin progreso» da por hecho un temporizador que la spec no define;
  - **cuando cambia la topología** (REQ-009).
- Arreglo: escribir que la concesión se evalúa también cuando una reserva se reduce, cuando una espera
  sale de la cola y cuando cambia la topología. Escribir además quién comprueba la red de seguridad; por
  ejemplo, cada espera se despierta al menos una vez por segundo y mira si toca forzar la concesión.
  Añadir un escenario con su mutante para la reserva que se reduce (W2 entra antes de que W1 termine) y
  otro para el temporizador (la red salta sin que nadie llegue ni salga).

**3. La red de seguridad da por hecho que `HTTP_TIMEOUT` vale 180 s, pero se puede configurar.**
- Evidencia: REQ-007 se justifica diciendo que «cada llamada al backend termina como mucho en
  `HTTP_TIMEOUT` (180 s)». Pero `HTTP_TIMEOUT` sale de `LOCAL_DELEGATE_TIMEOUT` (`config.py:68`). Si se
  configura por encima de `TURNO_MAX_S`, una sola llamada normal (por ejemplo, una carga en frío seguida
  de una generación larga) puede pasar 600 s sin que «empiece ni termine» ninguna llamada. Entonces la
  red forzaría la concesión con una operación sana en marcha, y volvería el vaivén de modelos.
- Arreglo: que el plazo efectivo sin progreso sea `max(TURNO_MAX_S, HTTP_TIMEOUT + margen)`, o que `doctor`
  avise y el daemon suba el plazo cuando `TURNO_MAX_S ≤ HTTP_TIMEOUT`. Añadir un escenario con
  `LOCAL_DELEGATE_TIMEOUT=900`. Escribir también qué modelo recibe una concesión forzada cuando la cabeza
  de la cola es un salto: «el modelo del rol de su `A`» no existe si `A = {destino}`, y lo correcto es el
  destino.

**MENOR**

- **4. El paso 3 de REQ-012 puede elegir un rol que choca.** La frase «el paso 3 siempre tiene el rol
  disponible» es cierta al conceder el turno, pero la elección llega después. Si en ese intervalo se van
  las operaciones cuyos modelos formaban `A'` y queda otra que choca con el rol (solo posible tras una
  concesión forzada), el paso 3 elige el rol y fuerza un cambio de modelo en mitad de una operación
  ajena. Arreglo: al elegir, el rol solo vale si es compatible con `modelos(activos)` sin contar la
  propia operación; si no, la operación vuelve a la cola.
- **5. La rama «el SDK entrega la cancelación» no se puede comprobar.** Con `mcp` 2.2.0 no la entrega
  nunca (`func_metadata.py:164`, ver arriba), así que la tarea del plan que iba a averiguarlo ya tiene
  respuesta. Hay que quitar esa rama o definir el mecanismo concreto que la activaría. Otro detalle: cada
  espera de turno ocupa uno de los 40 hilos que anyio permite por defecto. Con muchas esperas, otros
  manejadores síncronos del mismo proceso podrían quedarse sin hilo. Conviene comprobarlo en el plan.
- **6. «Fiel» no es exactamente «inventa algo».** El usuario confirmó la regla con un ejemplo: «inventa
  algo en menos de 1 de cada 10». La hoja pregunta «fiel (describe lo que hace el diff, sin inventar)»,
  que es el texto del primer punto del brief, y con eso el juez puede marcar «fiel = no» en un mensaje
  que solo se deja cosas fuera. El criterio 1 queda así más estricto de lo confirmado. Arreglo: que la
  casilla que decide pregunte «¿inventa algo que el diff no hace? (sí/no)», y que lo que falte se marque
  en «lo principal».
- **7. Las decisiones pendientes no cuadran con el brief.** La lista «Decisiones que necesitan al
  usuario» presenta como nuevas la lectura `c ≥ v` (3) y `local_summarize` fuera (5), que el brief ya da
  por confirmadas. En cambio, la 1 (600 s «sin progreso»), la 2, la 4 (las dos condiciones previas de
  commit) y de la 6 a la 10 **no** aparecen en el brief, y hay que confirmarlas antes de aprobar el gate.
- **8. El texto del margen** (ver «TTL»): cambiar «lo fija la carrera real» por «lo justifica el código
  de v255 y lo comprueba la prueba (a)», y quitar que cubre el tic.
- **9. La semilla de la tanda.** REQ-041 pide «los flags de producción» y una «semilla fija registrada»,
  pero el payload de producción no lleva semilla (`research.md`, «Plazos, cancelación y temperatura»).
  Hay que decir que la semilla es solo de la tanda y que, a temperatura 0, no cambia el resultado.

### Qué hace falta para aprobarla

1. Corregir el bloqueante 1: rellenar `espera_local` con el motivo `"turno"`, sin redefinir la fila 3.
2. Corregir los importantes 2 y 3: cuándo se evalúa la concesión, el temporizador de la red de seguridad
   y su relación con `HTTP_TIMEOUT`, cada uno con su escenario y su mutante.
3. Que el usuario confirme las decisiones que siguen pendientes, sobre todo la 1 y la 4.

Los menores se pueden corregir en el plan. Hecho esto, basta con revisar esos tres puntos; no hace
falta una tercera pasada completa.

### Llamadas `local_*`

**0.** Cargué `local_summarize` y `local_extract`, pero no las usé. Para citar `fichero:línea` la
revisión necesitaba el texto literal de la spec, de la revisión, de la spec del panel y del código Go de
v255, así que leí por franjas y con `grep`. Además, sin modelo residente, cualquier llamada habría
cambiado el modelo cargado y añadido filas a `metrics.db`, que se está midiendo.

## Respuesta a la segunda pasada

Corrección de `spec.md` del 2026-10-06, contrastada con la spec del panel de las 12:10
(`:317-329`) y su `plan.md` de las 12:14.

| # | Hallazgo | Resolución | Dónde quedó |
| --- | --- | --- | --- |
| Nuevo 1 (bloqueante) | La spec redefinía la fila «en cola local» del panel con `esperando_plaza`/`esperando_turno` | Quitada toda redefinición. Este cambio **solo escribe** `espera_local: "turno"` con el ayudante del panel y lo borra al obtener el turno; la plaza la sigue marcando el panel con `"plaza"`. No crea claves de espera ni toca la tabla ni `estadoModelo`. Los datos aparte (`turno_en_uso`, `turno_posicion`) no deciden ninguna fila y se añaden a lo que deja pasar `/api/inflight`. Al panel solo se le añaden palabras para el motivo `"turno"`. Hay escenario y control con un mutante que escribe una clave propia | REQ-008, REQ-027, escenario «la espera de turno se ve en el panel», control «Espera de turno en el panel», «Ficheros compartidos» |
| Nuevo 2 | La concesión no se vuelve a evaluar en todos los momentos | Lista de seis momentos: llega una petición; sale alguien de `activos`; se reduce una reserva; una espera sale de la cola; cambia la topología; y una comprobación al menos una vez por segundo de cada espera. Hay escenario de la reserva que se reduce, con su mutante, y control para los tres momentos nuevos | REQ-003 «Concesión», escenario «cuando una reserva se reduce», control «Momentos en que se vuelve a mirar la cola» |
| Nuevo 3 | La red de seguridad suponía `HTTP_TIMEOUT` de 180 s | El reloj de los 600 s **solo corre mientras el daemon no tiene ninguna llamada al backend en vuelo**, así que no depende de ningún plazo HTTP. Con `LOCAL_DELEGATE_TIMEOUT=900`, una llamada de 700 s no fuerza nada; está escrito y tiene escenario. Lo dispara la comprobación por segundo de la propia espera. En una concesión forzada de un salto, el modelo es el primero de su `A` en el orden de la cadena | REQ-007, escenarios «sin progreso» y «una llamada larga con un plazo HTTP mayor que 600 s», control «Red de seguridad sin progreso» (tres mutantes) |
| 5 (parcial) | Tope de 600 s | Cerrado con los nuevos 2 y 3. Los 600 s como «sin progreso» pasan a «Decisiones confirmadas» | REQ-007, «Decisiones confirmadas» |
| 14 (parcial) | Ficheros compartidos con el panel | Rehecha como tabla, fichero a fichero, contra su `plan.md` de las 12:14: qué toca aquel (y en qué tarea) y qué toca este. También qué es solo de cada uno | «Ficheros compartidos» |
| Menor 4 | El paso 3 podía elegir un rol que choca | El rol solo vale si es compatible con `modelos(activos)` sin contar la propia operación; si no (solo tras una concesión forzada), la operación vuelve a la cabeza de la cola | REQ-003 «Elección», REQ-012 |
| Menor 5 | La rama de cancelación no se puede comprobar | Quitada: con `mcp` 2.2.0 la cancelación no llega al hilo (`func_metadata.py:164`). Queda para el plan comprobar el límite de 40 hilos de anyio | REQ-007 «Cancelación», `research.md` |
| Menor 6 | «Fiel» no es «inventa» | La casilla que decide pasa a ser «inventa» (¿dice algo que el diff no hace?); lo que falta se marca en «lo principal» | REQ-042, criterio 1 de commit |
| Menor 7 | Las decisiones no cuadraban con el brief | Tres secciones: «Decisiones confirmadas» (brief, más los 600 s como «sin progreso», `c ≥ v` y `local_summarize` fuera), «Para confirmar con el usuario» (las dos condiciones previas de commit, en lenguaje llano) y «Decisiones de diseño, con recomendación» | Final de `spec.md` |
| Menor 8 | Texto del margen | Ahora dice que lo justifica el código de v255, con sus líneas (`process_command.go:132`, `:346-363`, `:804-808`; `src_metrics.go:137-143`; `src_mm.go:78-82`; `store.go:210`), y que la prueba lo comprueba. Quitado lo de «cubre el tic»: esa comprobación retrasa la descarga. `ahora` sale de `time.time()`, nunca de `time.monotonic()` | REQ-013 |
| Menor 9 | Semilla de la tanda | La semilla es solo de la tanda; producción no la manda y a temperatura 0 no cambia el resultado | REQ-041 |
| Demostración | Faltaba una operación sin turno con plaza | Añadido: tampoco espera nada del daemon | «Por qué turno y plaza no pueden bloquearse», punto 1 |

### Llamadas `local_*`

**0**, por los mismos motivos: hacía falta el texto literal de la spec del panel y de esta, y sin
residente cualquier llamada habría cambiado el modelo cargado y ensuciado `metrics.db`.

## Revisión del plan

Revisión adversaria de `plan.md` (2026-10-06, 1123 líneas). La contrasté con `spec.md` aprobada,
`brief.md`, `research.md`, los planes de `panel-cuentas-y-estados-honestos` y `coste-api-y-cuota`,
el código de `feat/panel-honesto` (`727f57d`), el harness instalado y la máquina, sin escribir nada.

### Veredicto

**Gate `plan`: no se aprueba todavía. Hacen falta cambios en el texto del plan, no en la spec.** La
estructura es sólida: trazabilidad completa entre REQ, tareas y verificación, olas bien razonadas,
controles con mutante nombrado y la config real restringida a un solo paso. Pero hay **cuatro
bloqueantes**. Uno invalida la prueba de discriminación de la hoja. Otro puede escribir la config
real de llama-swap desde un test o desde T17.3. Otro es un comando del harness que falla, con un
control (T17.2) que no puede dar otro resultado. El último es un control de procesos que choca con
el llama-swap real.

### Lo que comprobé y está bien

- **«`import local_delegate` carga `server.py`» es cierto**: `__init__.py:9` importa `entrypoint`,
  que hace `from . import autostart, config, server` (`entrypoint.py:22`). Lo ejecuté:
  `import local_delegate.config` deja `local_delegate.server` en `sys.modules` (`True`).
- **Cuenta de `doctor`**: hoy `checks.CHECKS` tiene 21 entradas (docstring «veintiún»,
  `checks.py:5`); el plan del coste lo sube a 22 (`coste-api-y-cuota/plan.md:53-54`) y este, a 24.
  `_NUMERO` (`tests/test_checks.py:1093`) y `_NUMERO_DE_CHECKS` (`tests/test_wiki.py:35`) llegan
  hoy a 21. Las entradas 23 y 24 que pide T13 son las correctas: la 23 hace falta para «ver los
  otros veintitrés».
- **Contrato del panel**: `_inflight_espera_local(entry_id, motivo)` existe (`server.py:256`),
  `inflight_snapshot` copia `espera_local` (`server.py:323-324`), la entrada en vuelo se crea por
  operación, antes de la plaza (`server.py:1401`, `:1691`, `:1908`), y `estadoModelo` busca las
  palabras de cada motivo en `PALABRAS_ESPERA` (`metrics.py:1647-1662`). T10 puede escribir
  `"turno"` sin redefinir nada.
- **El llama-swap real es v255 con `-watch-config`**: lo dice la línea de órdenes del proceso
  (`llama-swap-v255\llama-swap.exe --config …\config.yaml -watch-config --listen 127.0.0.1:9292`).
  La vigía de T17.6 debería ver «recargó».
- **Mutantes que sí mutan** (comprobados uno a uno con el guion del plan): T3 «mínimo de 10»
  (el evento 10.º tiene 9 muestras previas); T4 «`<= 3`» con 3 «inventa»; T4 «`c > v`» con 12/12/6;
  T8 «abandono sin `notify_all`» (con `tic=5.0` el mutante tarda 5 s y el assert pide 0,2 s); T10
  «dos saltos sin soltar la plaza» (A y B retienen las dos plazas y esperan un turno que C tiene,
  mientras C espera una plaza: bloqueo real, que el tope de 2 s ve antes que la red de 60 s).
- **Paralelo en las olas 1 y 3**: ninguna tarea edita `server.py` ni un fichero de otra. Se rompe
  en un sitio que no está en las tríadas (ver «T6 importa `server.py` a medio editar»).

### BLOQUEANTE

**B1. Los pares trampa se delatan solos, así que el criterio 0 no puede comprobar que el usuario
distingue.** REQ-042 pone cada trampa «contra el mensaje de un modelo en un caso elegido al azar».
T4.5 y T5 solo corren los 30 casos del corpus, así que ese caso es **uno de los 30**: el usuario ve
dos veces el mismo diff y, en el par trampa, un mensaje que ya leyó palabra por palabra. El otro es
la trampa. Hay además dos señales de forma. El prompt de `local_commit_msg` pide «cuerpo opcional»
(`server.py:2783-2790`), así que muchos mensajes reales traerán cuerpo y las trampas, de una sola
línea, se distinguen a simple vista. Y la trampa «de la misma zona» es el asunto real de otro commit,
y los asuntos de este repo pasan con frecuencia de 72 caracteres (`727f57d` tiene 89): el contador
«primera línea: N caracteres» la marcaría. Con cualquiera de las tres, el usuario acierta las
trampas sin juzgar el contenido, el criterio 0 pasa siempre y deja de ser un control.
*Arreglo:* (1) los pares trampa usan **tres diffs más por juego, fuera de los 30**, elegidos con la
misma regla de REQ-040 (los siguientes en orden), y T5 corre los dos modelos sobre ellos: son
9 casos más en `cases.json`, marcados `trampa`, que el veredicto ya excluye de los criterios 1 y 2;
(2) cada trampa copia la **forma** del mensaje con el que se empareja: si este trae cuerpo, la trampa
lleva un cuerpo de longitud parecida, construido con la misma regla escrita en `trampas.json`;
(3) la trampa «de la misma zona» se elige entre commits con asunto de ≤ 72 caracteres (si no hay
ninguno, el siguiente fichero más cambiado). El test `test_la_hoja_no_delata_a_nadie` gana dos
asserts: ningún diff ni mensaje aparece dos veces en la hoja, y la distribución de «tiene cuerpo»
de las trampas es la misma que la de sus pares. Es una aclaración de REQ-042 («caso elegido al
azar» pasa a ser «caso de trampa fuera de los 30»): conviene que el usuario la vea, aunque no cambia
su regla.

**B2. Nada impide que un test o T17.3 escriban en la config real.** `LLAMASWAP_CONFIG` está
definida a nivel de usuario y apunta a `D:\Projects\llms\llama-swap\config.yaml` (lo comprobé en el
entorno del proceso y en el de usuario). REQ-029 resuelve la ruta así: `--config`, después
`LLAMASWAP_CONFIG` y, por último, **la ruta que da el daemon**. Hay dos caminos para tocar la config
real:
- **T17.3** dice «sobre una COPIA … en el scratchpad», pero sus órdenes **no llevan `--config`**
  (`--ttl gemma4-12b=60 --ahora`, `--restaurar`, …). Si un agente las ejecuta tal cual, escribe en la
  config real con `--ahora`, sin negativas, y descarga los modelos.
- **Tests de T11 y T13**: la variable la aísla `conftest` (se lee con `_leer`), pero el tercer paso
  no. Un test de CLI sin `--config` puede preguntar al daemon real en `127.0.0.1:9393`, con el token
  web que `doctor` ya lee del disco, y recibir la ruta real.
*Arreglo:* (1) T17.3 con `--config <copia>` en **cada** orden, escrito literal en el plan; (2) una
fixture autouse en `tests/conftest.py` (T11) que apunta la consulta al daemon a un puerto muerto, y
un test que demuestra que, sin `--config` ni `LLAMASWAP_CONFIG`, el CLI dice «no se sabe» y no abre
ningún fichero; (3) el `sha256` de la config real se anota en `verification.md` en T0 y se compara al
cerrar **cada** ola. Si cambia fuera de T17.6, se para.

**B3. La enmienda de F3 usa una transición que el harness no permite, y T17.2 no puede fallar.** F3
está en `implementing` con `spec` y `plan` aprobados. En `personal-dev-harness`
(`src/core/sdd.js:58-67`), desde `implementing` solo se puede volver a `planning`:
`transition … specifying` da «transition implementing -> specifying is not allowed». Además, **las
transiciones no tocan los gates** (`transitionSddState` solo cambia `status`), y el CLI no tiene
`reject`: el gate `spec` de F3 **sigue `approved`** pase lo que pase. T17.2 comprueba «gate `spec`
aprobado», que ya se cumple hoy, así que pasaría aunque el usuario nunca hubiera vuelto a aprobar
nada. *Arreglo:* seguir el precedente del 2026-09-15 (el historial de F3 tiene una reaprobación de
`spec` estando en `implementing`): T1 escribe la enmienda y anota su hora, y la sesión principal
pide al usuario la reaprobación con `personal-harness sdd approve delegacion-precisa-y-fiable spec
--evidence "…"`, **sin transiciones** (o, si se quiere rastro de estado, `implementing → planning`
con motivo, aprobar y `planning → plan-review → implementing`). T17.2 comprueba que en
`history` de F3 hay un evento `gate/spec/approved` **posterior** a la hora de la enmienda. El rollback
de T1 se ajusta igual.

**B4. «Ningún proceso de llama-swap queda vivo (`tasklist`)» choca con el llama-swap real.** T2
lanza el **mismo binario** que usa producción (`llama-swap-v255\llama-swap.exe`), y el real corre
siempre. Si el control se hace por nombre de imagen, falla siempre o, peor, invita a «limpiar» con
`taskkill /IM`, que tumba el backend del usuario y a los clientes que dependen de él. *Arreglo:* la
fixture apunta los PID que lanza y el control comprueba **esos** PID; en el plan, prohibido de forma
explícita matar llama-swap por nombre. Que lo diga también el encargo de T13 y T17, que reutilizan
la fixture.

### IMPORTANTE

**I1. T6 importa `server.py` a medio editar.** Para escribir la huella en `veredicto.json`,
`analizar_benchmark.py veredicto-afinidad` llama a `huella.huella`, así que pasa a importar
`local_delegate`, y con él `server.py` (ver arriba). T6 corre en paralelo con las olas 3 a 8, y T10,
T12 y T14 editan `server.py`. Es lo que la propia regla de paralelo del plan prohíbe: el veredicto
puede caerse al importar, o calcular el `sha256` del prompt sobre un fichero a medias.
*Arreglo:* T5 calcula la huella de cada celda **en la tanda** y la guarda junto a los resultados, y
el veredicto la copia sin importar el paquete. Un test de T4 lo demuestra: el subcomando corre con
`local_delegate` fuera de `sys.path`. T15 sigue recalculándola contra el código final.

**I2. Si el usuario no termina la hoja, el PR no se cierra nunca.** T16 espera a la ola 9 y T17 a
T16. Pero T15 espera a T6, y T6 espera al usuario sin fecha. «El resto queda hecho» no es cierto:
queda hecho y sin mezclar. *Arreglo:* que el plan diga qué pasa entonces. Propuesta: si T6 no ha
cerrado al terminar la ola 8, la sesión principal pregunta al usuario. O espera, o el cambio se
cierra por la salida «ninguna celda» de T15 (REQ-018: las cadenas quedan sin `cargado`) y la
afinidad pasa a un cambio aparte que reutiliza T4 a T6, con su huella. Hoy sus resultados solo se
pueden registrar como `sin base`, nunca como `rechazada`.

**I3. El criterio de los hilos de anyio se cumple siempre, así que no decide nada.** `local_status`
es síncrona (`server.py:3312`) y también pide un hilo del limitador por defecto (40). El daemon
monta el MCP y el panel en la **misma** app (`daemon.py:211-216`), y los endpoints del panel son
`def` síncronos (`inflight()`, `events()`, `metrics.py:449`, `:599`), así que comparten el mismo
limitador. Con 40 llamadas esperando, `local_status` no tiene hilo **por construcción**: la parada
de T10.10 salta siempre. Además, el riesgo no es nuevo: hoy la espera de plaza ya bloquea un hilo
(`_chat_slots.acquire()`, `server.py:1268`). *Arreglo:* que T10 mida **el mismo guion dos veces**:
con turno, y sin turno con las llamadas esperando plaza (la línea base de hoy). Que busque el N con
el que `local_status` **y** `GET /api/inflight` dejan de contestar en 2 s. El criterio queda
escrito antes de medir: se para solo si, con turno, el N es menor que en la línea base, o si es
menor que 3 veces el pico de operaciones simultáneas del log de uso. La consulta previa del CLI
(`/api/llamaswap/estado`) también es síncrona: con el limitador agotado responde «no se sabe»
(negativa segura), y debe quedar escrito.

**I4. Cuatro controles que pueden pasar por la razón equivocada o fallar por excepción:**
- *T4, `flags_del_cmd`*: la config real lleva `-ncmoe 12` en el 26B (el plan dice 16) y `-ncmoe 20`
  en Qwen3.6, **en su forma corta**. Así que el mutante «solo forma corta» **no muta** con el caso
  que nombra. *Arreglo:* corregir el 16 por 12 y añadir un `cmd` sintético con `--n-cpu-moe 20`, que
  es el que hace caer al mutante.
- *T11, claves duplicadas*: el control es `pytest.raises(ErrorResidencia)`. Sin la negativa, si el
  editor toca la **primera** aparición, la autocomprobación (`safe_load` se queda con la última)
  también lanza `ErrorResidencia`. El mutante no muta. *Arreglo:* `match="clave duplicada"` y un
  assert sobre el mensaje.
- *T4, respuestas de otra hoja*: `pytest.raises(SystemExit)`. Unas respuestas de otra hoja también
  fallan la comprobación de completitud (otros pares), así que sin el `sha256` el lector sale igual.
  *Arreglo:* las respuestas de prueba son de una hoja con los mismos pares y otra semilla (sin que
  falte ninguna), y se comprueba que el mensaje nombra el `sha256`.
- *T9, línea corrupta*: sin el `try`, `sembrar` lanza antes de llegar a
  `assert ref.muestras("x") == 12`: falla por excepción, justo lo que «Cómo se escribe el control
  positivo» prohíbe. *Arreglo:* capturarla en el test y convertirla en un `assert` con mensaje, como
  ya hace el test de REQ-028 en T14.
- Regla general: todo `pytest.raises` del plan lleva `match=`.

**I5. La ida y vuelta de T17.6 se va a negar a escribir.** Viene detrás de T17.5, que deja modelos
cargados (TTL 120, el 12B 30). La negativa de REQ-034 por «modelos en `/running`» bloquea el paso 3,
porque no usa `--ahora`. Además, los pasos 3 y 4 dejan dos `.bak` con fecha junto a la config real,
y el plan no dice qué se hace con ellos. *Arreglo:* antes del paso 3, esperar a que `/running` quede
vacío (con un tope de 3 minutos; si no, se anota y se para) en vez de usar `--ahora`, para que el
paso pruebe también la negativa y la consulta previa reales. Al final, listar los `.bak` creados y
dejar escrito si se conservan (recomendado: sí, tienen las mismas claves y permisos que la config).

**I6. La tanda puede contaminarse con otros clientes, y el criterio 6 mide latencia.** T5 pide «el
daemon sin delegaciones» al **empezar**. Pero otras sesiones del usuario, como Codex o un Claude
Code abierto, pueden delegar a mitad de las horas que dura, y la tanda va directa contra llama-swap.
*Arreglo:* que `benchmark.py` lea `/api/metrics/activity` de la ventana al terminar y marque los
casos que se solaparon con peticiones ajenas. Esos casos se repiten antes del veredicto, y el número
de repeticiones se anota.

**I7. Lo que puede discriminar la hoja, para que el usuario lo sepa antes de juzgar.** La regla es
suya y no se toca, pero el plan debería decir qué potencia tiene. Lo calculé con una binomial
(30 pares, 20 % de empates):

| Preferencia real (26B / Qwen3.6) | P(aprueba «c ≥ v») con 30 pares | con 20 | con 45 |
|---|---|---|---|
| 45 % / 35 % (algo mejor) | 0,76 | 0,74 | 0,80 |
| 40 % / 40 % (igual) | 0,54 | 0,55 | 0,53 |
| 35 % / 45 % (algo peor) | 0,30 | 0,35 | 0,25 |
| 30 % / 50 % (peor) | 0,13 | 0,19 | 0,07 |
| 25 % / 55 % (claramente peor) | 0,04 | 0,08 | 0,01 |

Y el criterio «inventa ≤ 2 de 30» deja pasar un modelo que inventa de verdad en el 10 % de los
mensajes con probabilidad 0,41, y en el 15 %, con 0,15. Es decir, la regla filtra bien lo
claramente peor, pero uno algo peor pasa en 3 de cada 10 tandas. *Arreglo:* que la tabla vaya en
`verification.md` y en el mensaje de T6, para que «aprobada» se lea como «no claramente peor».

**Cómo reducir los 60–90 minutos sin perder discriminación.** Lo que más tiempo lleva es leer
33 diffs, no los clics, y el poder lo dan los pares, así que **no conviene quitar pares**:
pasar de 30 a 20 apenas cambia la tabla, pero el «menos del 10 %» pasa a «1 de 20» y los 30 son una
decisión del usuario. Lo que sí se puede quitar sin tocar la regla:
1. **«Formato» lo calcula el programa** (primera línea ≤ 72, prefijo convencional, sin adornos):
   no decide y es mecánico. Una pregunta menos por mensaje.
2. **«Lo principal» y «específico» pasan a opcionales** (plegados, «si te apetece»): no deciden.
   Como el usuario pidió criterios definidos por caso, se le propone, no se decide por él.
3. **«Inventa» sigue en los dos mensajes**: solo cuenta el del 26B, pero preguntarlo solo en uno
   rompería la ceguera.
4. **Parada anticipada honesta**: cuando las 3 trampas están contestadas y valen (2 de 3), y el
   desenlace ya no puede cambiar (el 26B suma 3 «inventa», o `v − c` supera los pares reales que
   quedan), la hoja lo dice y el usuario puede parar. El lector acepta esa hoja incompleta solo en ese
   caso, y el test lo prueba con un caso decidido y otro sin decidir.

Con 1 y 2 quedan 2 respuestas por par en vez de 9: la estimación baja a unos 45–60 minutos, y la
parada solo acorta si el 26B pierde.

**Si lo deja a medias**: el progreso queda en `localStorage`, que funciona con `file://` en Chrome y
Firefox, y el lector lista lo que falta. Bien resuelto. Falta lo del punto I2: qué pasa si no vuelve.

### MENOR

- **M1. T9 edita un fichero de T3.** «El script de T3 pasa a importar `ritmo.py`» edita
  `scripts/medir_lentitud.py`, que la tabla de propiedad da solo a T3. No hay choque, porque son de
  olas distintas, pero la tabla debe decir T3 → T9.
- **M2. Orden de `_NUMERO` en T13.** Igual que en el plan del coste: `_NUMERO[23]`, `[24]` y
  `_NUMERO_DE_CHECKS[24]` se añaden **antes** de registrar los checks. Si no, los guardianes caen por
  `KeyError`, que no vale como control.
- **M3. Dos asserts de T10 necesitan su guarda.** «Sin topología o con backend remoto, como hoy»: el
  mutante «no mirar el origen» solo muta si el test lanza **dos operaciones que chocan** a la vez,
  como en el escenario de la spec. Con una sola nunca hay `espera_turno_ms`. Guarda: el mismo guion
  con loopback sí espera. «El mismo modelo no se serializa de más»: guarda de que las dos operaciones
  se solaparon (barrera en el `backend_mock`). Si no, el mutante «turno exclusivo» no se ve.
- **M4. `clave-1.json` está al lado de la hoja.** Para un juicio a ciegas, mejor que la clave quede
  fuera de la carpeta que abre el usuario (p. ej. `benchmarks/afinidad-2026-10/clave/`) hasta que el
  lector la necesite.
- **M5. Estilo propio de cada modelo.** Aunque la hoja no lleve nombres, el usuario puede reconocer
  a cada modelo por su estilo a lo largo de 30 pares. No se puede ocultar sin cambiar lo que se juzga
  (la salida tal como llega), pero conviene decirlo en `verification.md` como límite conocido.

### Trazabilidad

REQ-001 a REQ-043 y el caso límite de los plazos tienen tarea y verificación. Todos los controles
de «Controles e insumos» de la spec tienen tarea dueña. No encontré ningún REQ sin cubrir. Lo que
falla son controles concretos (B1, B3, I3, I4), no la cobertura.

### Qué hace falta para aprobarlo

Corregir B1 a B4 e I1 a I6 en `plan.md`. El arreglo de B1 aclara REQ-042 («caso de trampa fuera de
los 30»), y conviene enseñárselo al usuario junto con la tabla de I7 y las propuestas para reducir el
tiempo, que son decisión suya. Basta con una pasada corta sobre esos puntos. Evidencia propuesta
para el gate: «Revisión adversaria del plan: 4 bloqueantes (trampas que se delatan, escritura
posible de la config real, transición del harness inválida con T17.2 vacío, control de procesos por
nombre) y 7 importantes, corregidos; import de `server.py`, cuenta de `doctor` 21→22→24 y
llama-swap v255 con `-watch-config` comprobados en la máquina».

### Llamadas `local_*`

**0.** Cargué `local_summarize` y `local_extract`, pero no las usé. La revisión necesitaba el texto
literal del plan, de la spec y de líneas concretas del código y del harness. Cada llamada habría
cargado un modelo, sin residente, y añadido filas a `metrics.db`, que está en medición (P-4, F1).

## Respuesta a la revisión del plan

Corrección de `plan.md` (revisión 2, 2026-10-06), con las decisiones de la sesión principal. Los
controles nuevos o cambiados que dependían de cómo se comporta el código se comprobaron
ejecutándolos con reimplementaciones desechables (`scratchpad/controles-plan/controles.py`).

| # | Hallazgo | Resolución | Dónde quedó |
| --- | --- | --- | --- |
| B1 | Las trampas se delataban (mismo diff y mensaje repetidos, sin cuerpo, asuntos de más de 72) | Diffs **propios**: los 9 commits siguientes de la regla de REQ-040, corridos por los dos modelos en la tanda, marcados `trampa`. Cada trampa copia la forma de su pareja (cuerpo con el mismo número de líneas, hasta 5; las dos formas escritas antes de la tanda y elegidas por el programa). La de *misma zona*, entre asuntos de ≤ 72. El test de la hoja comprueba que nada sale dos veces y que la forma coincide. Aclaración de REQ-042 escrita en `spec.md` («Aclaraciones posteriores a la aprobación»), con su motivo; la regla del usuario no cambia | T4.2, T4.4, T4.6, tests de T4; T5.2; `spec.md` |
| B2 | Un test o T17.3 podían escribir en la config real | `--config` explícito y literal en toda orden de T17.3 y en todo test; fixture autouse (T11) que apunta la consulta al daemon a un puerto muerto, con su test, y un test de que sin `--config` ni la variable el CLI dice «no se sabe» sin abrir ficheros; `sha256` de la config real anotado en T0 y comparado al cerrar **cada** ola, con parada y restauración (preguntando antes al usuario si fue él) | «Comprobación de la config real al cerrar cada ola», «Reglas comunes», T0.8, T11, T17.3 |
| B3 | Transición del harness no permitida y T17.2 que no podía fallar | Sin transiciones. La sesión principal pregunta al usuario de forma explícita; su respuesta queda como evidencia de un `approve` **nuevo** del gate `spec` de F3. T1 anota la hora de la enmienda; T17.2 busca con un script un evento `gate/spec/approved` posterior. Hoy el último es del 2026-09-15, así que el control sí puede fallar. Sin él, no se mezcla | T1, T17.2 |
| B4 | Control de procesos por nombre contra el llama-swap real | La fixture apunta sus PID y solo comprueba y termina **esos** (`taskkill /PID … /T`); prohibido matar por nombre, dicho en las reglas y en T2, T13 y T17; un test comprueba que el PID del llama-swap real sigue vivo | «Procesos», T2, T13.5 |
| I1 | T6 importaba `server.py` a medio editar | La huella la calcula T5 en la tanda (`huellas.json`); el veredicto y la hoja la copian y **no importan** `local_delegate`. Test con `sys.modules["local_delegate"] = None` en un subproceso | Diseño, T4.8, T5.1, T6, test `test_no_importa_el_paquete` |
| I2 | Si el usuario no termina la hoja, el PR no se cierra | Al cerrar la ola 8, la sesión principal pregunta. Si no termina, la celda de commit queda no aprobada, `local_commit_msg` sigue como hoy, T15 lo deja escrito y el PR se cierra igual | T6, T15, Riesgos, `spec.md` (aclaración 6) |
| I3 | El criterio de los hilos de anyio se cumplía siempre | Medición del mismo guion dos veces: línea base de hoy (esperas de plaza, sin turno) y con turno; N mínimo con el que `local_status` **o** `/api/inflight` dejan de contestar en 2 s, con la app montada como en el daemon. Se para solo si N con turno < N de la línea base o < 3 × el pico real de operaciones simultáneas (T0.6). Y la consulta previa del CLI con el limitador agotado responde «no se sabe» (test en T13) | T0.6, T10.10, T13 |
| I4 | Cuatro controles que pasaban por la razón equivocada | Huella: el 26B lleva `-ncmoe 12` en la forma corta (leído en la config real; ningún `cmd` usa la larga); dos tests, uno con el `cmd` real (mutante «solo forma larga») y otro sintético con `--n-cpu-moe 20` (mutante «solo forma corta»), **los dos comprobados**. Duplicadas: `match="clave duplicada"` (**comprobado**: sin la negativa, la autocomprobación lanza la misma clase con otro mensaje). Otra hoja: respuestas completas con los mismos pares y `match="sha256"` (**comprobado**). Línea corrupta: el test captura la excepción y la convierte en `assert` (**comprobado**). Regla general: todo `pytest.raises` con `match=` | «Cómo se escribe el control positivo», T4, T9, T11 |
| I5 | La ida y vuelta de T17.6 se negaría a escribir | Antes de escribir, espera a que `/running` quede vacío (sondeo cada 10 s, tope de 3 min, otra espera de un TTL si alguien lo usa, y si no, se para), **sin** `--ahora`, para probar también la negativa real. Los `.bak` que quedan se listan y se conservan | T17.6 |
| I6 | La tanda podía contaminarse con otros clientes | Ventana elegida con el usuario, sin otras sesiones que deleguen; al terminar, detección de peticiones ajenas en la ventana (copia de `metrics.db` y log del daemon contra las peticiones que apuntó la tanda) y repetición de los casos que se solaparon, anotando cuántos | T5 (condición 1 y paso 3) |
| I7 | Potencia de la hoja | La tabla va a `verification.md` y al mensaje de T6, para que «aprobada» se lea como «no claramente peor». Para acortar la hoja: «formato» lo calcula el programa; parada anticipada que solo responde «puedes parar»/«sigue» (la página no lleva la clave). «Inventa» más estricto y «lo principal»/«específico» opcionales quedan **pendientes del usuario**, como parámetros en un solo sitio (`reglas.json`), cerrados antes de la hoja 1 | T4.5, T4.6, T6, Riesgos |
| M1 | T9 edita un fichero de T3 | Propiedad T3 → T9 | Tabla de propiedad |
| M2 | Orden de `_NUMERO` | Las entradas 23 y 24 antes de registrar los checks | T13.4 |
| M3 | Dos asserts de T10 sin guarda | «Sin topología o remoto»: dos operaciones que chocan, con la guarda de que en loopback sí esperan. «Mismo modelo»: barrera en el `backend_mock` que demuestra que las dos se solaparon | Tests de T10 |
| M4 | Clave junto a la hoja | La clave va en `clave/`, fuera de `hoja/`, con test | T4.6, tabla de propiedad |
| M5 | Estilo propio de cada modelo | Anotado como límite conocido en el mensaje de T6 y en `verification.md` | T6, Riesgos |

### Lo que queda abierto

- Los dos valores de `reglas.json` (máximo de «inventa» y preguntas opcionales): los confirma el
  usuario a través de la sesión principal, antes de que T5 genere la hoja 1.
- El número de líneas que cambia `safe_dump` en el mutante de T11 se comprueba al ejecutar.

### Llamadas `local_*`

**0**: los controles se comprobaron con un script desechable, sin modelos; cualquier llamada habría
cargado uno y añadido filas a `metrics.db`, que está en medición.
