# Revisión adversarial 1 de la spec y el plan (#586)

Revisor: agente revisor (solo lectura, más este fichero). Fecha: 2026-11-10 10:49 (hora de Uruguay).
Sin llamadas al backend. Scripts ligeros sobre una copia del prototipo en el scratchpad; ningún
fichero de esta carpeta se tocó salvo este.

## Veredicto

**APROBABLE CON CAMBIOS.** La estructura es buena: la puerta va antes del código, la spec dice lo
que el aviso no ve, el prompt no se toca y hay tabla de mutantes. Pero hay dos agujeros por los que
puede repetirse lo del #621: el conjunto nuevo de REQ-004 no está obligado a traer las formas que
dan avisos en falso (con 9 casos escritos a mano saqué 4 en respuestas correctas), y los topes de
REQ-022 no limitan el coste real del detector (16 s por debajo de los dos topes). Los dos se arreglan
en la spec antes de aprobar las puertas `spec` y `plan`.

## Lo que comprobé y se sostiene

- `python evaluate.py` sobre una copia regenera `outputs/evaluation.json` **idéntico byte a byte**
  (sha256 `591926ad…bbc` antes y después).
- La estricta da VP 6, FP 0 y FN 6 en las cuatro corridas (g3-extract 4/0/5, g3-proxy 2/0/1, g4-proxy
  0/0/0, g4-extract 0/0/0); por el producto con `gemma3-4b`, 4 de 9. Sin la guarda, VP 6, FP 1
  (`g4-proxy/03/closes_issue`) y FN 6. Control de intercambio: 238 de 308. Todo coincide con la spec.
- Las referencias de código que cita el plan son exactas: `server.py:7971-7975` (rol antes de leer),
  `:8141-8182` (normalización), `:8213-8236` (`late_notices`), `config.py:316` (umbral).
- `has_table` del prototipo es lineal: las cinco entradas hostiles de 1 000 000 de caracteres tardan
  0,001–0,043 s.
- Afinidad: `local_extract` no tiene ninguna celda en `matrix.py:114-120`, así que el turno por
  afinidad no interfiere con el cambio de rol.

## Hallazgos

### 1. Bloqueante: el conjunto nuevo de REQ-004 puede pasar sin ver las formas que dan avisos en falso

Escribí 9 casos a mano (`adverse.py` en el scratchpad; salida escrita a mano, sin modelo). En las
respuestas **correctas** el detector estricto da **4 avisos en falso de 20 claves sin cruce**:

| Caso | Forma | Resultado |
| --- | --- | --- |
| A3 | El mismo número en dos filas; la fila propia tiene una etiqueta sinónima («Licensed seats» frente a `user_limit`) | FP: `user_limit` → fila «Projects» |
| A7 | El valor correcto de A es una subcadena de la fila de otra clave pedida (`100` dentro de «1000/day, 100 per user») | FP |
| A8 | La celda de la fila propia pasa de 60 caracteres y la misma palabra corta («Unlimited») está en la fila de otra clave. **El falso positivo sale de la propia guarda.** | FP: `projects` → «Storage» |
| A9 | Plural irregular: `words("retries")` da `retrie`, no `retry`; pasa lo mismo con el plural español en `-es` (`regiones` da `regione`) | FP: `retry_count` → «workers» |

Y 3 falsos negativos de 5 cruces: un valor repetido (A1, ya documentado), etiquetas en español con
claves en inglés (A4) y `\|` escapado en Markdown (A6, la celda se parte y el valor cruzado ya no casa).
Hay 2 aciertos: la celda vacía (A2) y el `rowspan` (A5).

En el conjunto de la investigación no salió ninguno porque no tiene esas formas. REQ-004 solo pide
«celdas largas» y «claves parecidas», así que puede pasar con 0 y aun así salir a producción la
misma clase de aviso en falso que hizo retirar `ungrounded_keys` (#609). Además, 0 de 60 deja una
cota superior del 95 % de alrededor del 5 % de avisos en falso (regla del tres): no prueba que sean
pocos. Y quién construye el conjunto no está fijado: hoy lo haría quien ya conoce la guarda.

**Cambios que pido (REQ-004 y T1):**
- Cupos obligatorios: al menos 2 casos de cada una de estas formas, sobre respuestas que acierten:
  número repetido con etiqueta sinónima, valor que es subcadena de otra fila pedida, celda propia de
  más de 60 caracteres, y plurales irregulares en inglés y en español.
- Que lo escriba un agente sin acceso a `detector.py` ni a la sección «Detector A» de `research.md`.
- Si la plantilla de plurales se arregla, que sea antes de congelar el conjunto, nunca después.

### 2. Importante (casi bloqueante): los topes de REQ-022 no limitan el coste del detector

El coste crece con filas × celdas × campos × hojas, y `norm_value` se recalcula en cada comparación.
Medido con el prototipo, con 1 990 filas y 243 000 caracteres (por debajo de los dos topes): 5 campos
tardan 0,43 s, 20 campos 1,62 s y 20 campos con listas de 10 hojas **16,0 s**. Con 400 000
caracteres de líneas `a: b` y solo 3 campos tarda 1,00 s, justo en el límite, y eso para descubrir
que la entrada pasa el tope de filas.

Las pruebas hostiles de REQ-022 no fijan cuántos campos se piden, así que pasarían. Y `local_extract`
no tiene tope de campos. Con el schema cada valor es un primitivo, pero en modo libre (`auto` tras
un rechazo, u `off`) los valores pueden ser listas.

**Cambio (REQ-022 y T4):**
- Un presupuesto de comparaciones (celdas × hojas × campos) por encima del cual no corre, o
  normalizar cada celda y cada hoja una sola vez.
- El tope de filas, con salida temprana durante el análisis.
- Pruebas con al menos 20 campos y con valores lista.

### 3. Importante: la puerta T1 tiene una vía menos invasiva que reiniciar el daemon (respuesta al punto 2)

**Sí existe.** Consiste en un segundo proceso, aparte del daemon, que ejecuta el mismo código del
producto:

- **El proceso.** Puede ser una llamada única a `server.local_extract(...)`, que es lo que hacen 19
  ficheros de la suite, o `local-delegate serve --port 9394`. Se lanza con el Python del `uv tool`
  instalado (la misma versión que el daemon) y con este entorno:
  - `LOCAL_DELEGATE_LONG_INPUT_CHARS=0`;
  - `LOCAL_DELEGATE_LOG_DIR=<temporal>`: el lock y `daemon.json` del servidor van por `LOG_DIR`
    (`daemon.py:78`, `:689`), así que no choca con el daemon;
  - `LOCAL_DELEGATE_LOG=<temporal>/usage.jsonl`;
  - `LOCAL_DELEGATE_WEB_PORT=9394`;
  - una copia de `backend-params.json` en ese `LOG_DIR` temporal, porque se lee de ahí
    (`backend_params.py:398`; hoy vale `roles: {}`, de modo que la temperatura sigue en 0).
- **La credencial.** La tarea programada ejecuta `start-local-delegate-secure.ps1`, que importa la
  credencial con `Import-Clixml` y la pasa por entorno a `Start-Process`. Una copia de ese lanzador
  que solo cambie las variables de arriba y el comando, lanzada como tarea temporal con
  `schtasks /Create` y luego `/Run`, hereda la credencial sin que ningún agente la lea ni la imprima.
  Requiere el visto bueno del usuario, porque toca un fichero que maneja el secreto.
- **El turno, y la trampa.** Con `LLAMASWAP_CONFIG` puesto, ese proceso usa **su propio turno
  local**: la topología local manda aunque haya `TURN_URL` (`server.py:2565-2575`), así que el turno
  del daemon y la Mac no lo verían. Para unirlo al turno real se quita `LLAMASWAP_CONFIG` en el hijo
  y se ponen `LOCAL_DELEGATE_TURN_URL=http://127.0.0.1:9393/` y `LOCAL_DELEGATE_REMOTE_WEB_TOKEN`
  (desde la variable del token web del lanzador). La guarda contra preguntarse a sí mismo compara el
  `daemon_id` del `daemon.json` del **hijo** (`remote_turn.py:310-317`, `:846`), así que pide turno
  como lo pide la Mac. Esta combinación, un cliente de loopback de `/api/turn/*`, no está probada:
  hay que validarla con una llamada pequeña antes de la tanda.
- **Qué no prueba frente al daemon real:**
  - la capa MCP por HTTP y el middleware de cancelación (las filas de `_log_stopped`);
  - las plazas, el enfriamiento y el corte compartidos con las demás sesiones;
  - el paso `loaded` sin topología (para extract da igual: no tiene celdas);
  - lo que hace el proceso real instalado.

  Para la pregunta de T1 (cómo se porta el modelo por la ruta del producto, con su schema, su
  temperatura, su `max_tokens` y su post-proceso) es el mismo código.

**Lo que gana:** ningún corte del MCP en las sesiones abiertas, y las demás tools de las otras
sesiones no se van al modelo grande. Los cambios de modelo en el backend compartido siguen
ocurriendo; por eso se agrupan en una tanda y se avisa.

**Cambio (T1, tanda 3):** usar esta vía y dejar el reinicio solo como respaldo si falla la
validación. Lo mismo vale para la fase 1 de T7. La fase 2 sí tiene que ir por el daemon con la rama
instalada (REQ-031).

### 4. Importante: el respaldo de las tablas pequeñas pasa a ser el modelo más grande

Con el rol `long`, la cadena es `loaded -> code` (`chains.py:47-51`). Para extract, `loaded` sale
vacío (no tiene celdas), así que si `gemma4-26b-a4b` falla o está enfriado, una tabla de 900
caracteres que hoy, cuando falla `gemma3-4b`, cae en `gemma4-26b-a4b`, caería en `qwen36-35b-a3b`
(17,7 GB, el de carga más cara). No está ni medido ni en «Coste».

**Cambio:** REQ-026 y «Coste» tienen que decirlo. La convivencia con `fallback` necesita una prueba
que fije el modelo del respaldo con la regla encendida.

### 5. Importante: `role_reason` no llega a las filas de fallo, que son las más probables con el modelo grande

Las filas de cancelación, plazo propio y `queue_saturated` no las escribe `_chat`, sino
`_log_stopped` desde el token (`server.py:2163-2219`). Un argumento nuevo de `_chat` no llega ahí.
El mutante «el motivo no llega a `_log_event`» solo mira el camino bueno. Además, REQ-014 quita
`role_reason` de las respuestas de error: quien recibe un error tras esperar a que cargue el modelo
grande no se entera de por qué fue a ese modelo.

**Cambio (REQ-014, REQ-015 y T5):**
- Llevar el motivo en la entrada en vuelo o en el token, para que `_log_stopped` lo escriba.
- Una prueba con el plazo agotado.
- `role_reason` también en `_local_delegate` de las respuestas de error.

### 6. Importante: REQ-001 solo cuenta cruces, no aciertos

Por el producto, el modelo grande nunca se midió en entradas pequeñas, y por el sustituto sin
schema anidaba objetos (`research.md:150-152`). Con el schema puede fallar de otra forma, y la
puerta solo lo «anota».

**Cambio (REQ-001):** criterio de parada también sobre los 8 casos limpios (con `gemma3-4b` fueron
0 de 44 claves falladas; pido como mucho 1) y ninguna respuesta con `error`/`raw`.

### 7. Importante: la regla de la tabla deja fuera tablas reales sin decirlo

`has_table` da `False` en tres tipos de tabla:
- CSV y TSV;
- la tabla GFM de dos columnas sin tuberías externas (`Seats | Domains`, con un solo `|`);
- el separador `|-|-|`, porque la regla exige `--`.

Los extract sobre `.csv` son una entrada natural, y D1 solo midió HTML y Markdown. Sale `True` en un
diff de una tabla y en una cadena de un JSON con `<tr` (esto último ya documentado).

**Cambio:** un caso CSV en la tanda 1 de T1 (¿cruza `gemma3-4b`?), y CSV, TSV y tablas sin
tuberías externas en «Límites» (REQ-026) o dentro de la regla.

### 8. Importante: el reparto no es tan limpio como dice el plan

- **CI en rojo entre tareas.** El guardián de T6 «se pone en verde cuando entra T5» (`plan.md:64`):
  es un test en rojo en una rama empujada, y la regla del proyecto no deja ningún CI en rojo.
  Pido mover la parte del docstring a los tests de T5.
- **Marcadores de «sin dato» duplicados.** `cross_fill.py` necesita la lista de marcadores. Copiarla
  crea una segunda fuente de verdad, y como contiene «sin información», puede hacer saltar la red de
  tildes de `tests/test_no_uncatalogued_text.py`. Eso obligaría a T4 a tocar
  `tests/data/uncatalogued_exceptions.json`, que es fichero de T6. Pido sacar la lista a un módulo
  puro que importen los dos, con un único dueño declarado.

### 9. Importante: el detector que no corre no deja rastro, y no se puede apagar

Por encima de los topes, o si lanza una excepción, el detector calla: ni la respuesta ni el log lo
dicen, y el `try` se traga el fallo. Un fallo del detector en producción quedaría invisible para
siempre, y nadie podría medir cuántas veces corre de verdad. A la vez, S3 («no toca latencia») es
falso según el hallazgo 2, y ante una racha de avisos en falso haría falta publicar una versión
para quitarlo.

**Cambio:**
- Un campo solo en el log: `cross_fill: "skipped_size" | "skipped_rows" | "skipped_budget" | "error"`.
- El fallo, en el log de errores.
- Un interruptor `LOCAL_DELEGATE_EXTRACT_CROSS_FILL`, encendido por defecto.

### 10. Importante: cerrar el #586 tal como está propuesto no es honesto con quien lo abrió

El caso reportado (33 KB, rol `long`, una fila que nadie pidió) no lo arregla ninguna de las dos
piezas: la B no actúa porque esa entrada ya iba a `long`, y la A no ve esa forma (límite 1). Además,
los «cuatro intentos» fueron con páginas inventadas de 6,6 y 29 KB. Pasarlo a una tarjeta del tablero
privado borra el rastro público.

**Cambio (REQ-032):** si se cierra, que el comentario diga en la primera línea que el caso reportado
no queda arreglado, y que se abra un issue público de seguimiento con el criterio de reapertura (no
solo una tarjeta privada).

### 11. Importante: falta una superficie de documentación

`docs/wiki/Savings-and-metrics.md` documenta los campos del log (`routing` y
`affinity_dropped_class` en `:160-164`), y no está en T6 ni en REQ-025.

### 12. Menor: las cifras cuentan repeticiones

- Las 282 claves sin cruce son 130 pares (caso, clave) distintos y 123 valores no nulos distintos:
  las mismas 26 entradas, en cuatro corridas.
- Los «19 y 22» avisos en falso de las variantes amplia y parcial son unas 7 y 11 claves distintas.

D2 y REQ-026 deberían dar las cifras de claves distintas.

### 13. Menor: dos mutantes no pueden «mutar» con la definición del plan

El plan define «muta» como que la sonda dé un resultado distinto. Hay dos mutantes que no lo dan:
- **La expresión regular que retrocede:** da el mismo resultado, solo tarda más. Hay que escribir la
  expresión del mutante y definir la sonda como tiempo.
- **«`detect` sin tope de filas»:** con 2 001 filas solo cambia el resultado si la sonda trae un
  cruce.

Faltan además dos mutantes:
- uno para REQ-016 (la regla añade texto al `system`);
- uno para las filas de `_log_stopped` (hallazgo 5).

### 14. Menor: tres cabos sueltos de la spec

- REQ-004 dice «Verify: test», pero es una puerta manual con llamadas en vivo. El test solo
  repetirá las salidas grabadas.
- `brief.md` sigue con `TBD`.
- REQ-016 debería decir que los parámetros del rol `long` (`backend-params`) se aplican a esa
  llamada: hoy no hay ninguno, pero cambiar de rol cambia el cuerpo si alguien los pone.

## Respuestas por punto del encargo

1. **Requisitos que no discriminan:**
   - REQ-004: sin cupos de formas puede dar 0 sin haber mirado nada (hallazgo 1).
   - REQ-022: las pruebas hostiles no prueban el coste real (hallazgo 2).
   - REQ-015: un «si y solo si» comprobado solo por el camino bueno (hallazgo 5).
   - REQ-026 y REQ-032 son de lectura, sin criterio observable. Se aceptan, con los cambios de los
     hallazgos 4, 10 y 12.
2. **Vía menos invasiva:** sí (hallazgo 3).
3. **Umbrales:**
   - REQ-001 (como mucho 1 caso de 8) y REQ-003 (6,5 s, el doble de la mediana del sustituto) son
     reglas de parada razonables, pero sobre los mismos casos de la investigación. A REQ-001 le
     falta el criterio de aciertos (hallazgo 6).
   - REQ-004 tal como está no discrimina (hallazgo 1), y el conjunto no lo construye un ciego.
4. **Detector estricto:** las cifras se confirman. Con 9 casos adversos (25 claves): 2 VP, 4 FP y
   3 FN.
5. **`has_table`:**
   - Falsos `True`: diffs de tablas, cadenas de JSON y f-strings con `<tr` (del lado seguro).
   - Falsos `False`: CSV, TSV, tablas GFM sin tuberías externas, `|-|-|` y rejillas `<div>`.
   - El coste es lineal.
   - El troceo no le afecta: una entrada de 6000 caracteres o menos nunca se trocea, ni en
     `mechanical` (20 000) ni en `long` (48 000).
   - `path` mide en bytes y `text` en caracteres, como hoy.
6. **Decisiones del redactor:**
   - S2 (el motivo del rol fuera de `warning`): de acuerdo.
   - S3 (detector sin interruptor): en contra (hallazgo 9).
   - Topes sin aviso: es un fallo silencioso nuevo (hallazgo 9).
   - Nombres: no chocan con nada existente (`role_reason`, `cross_filled_keys` y
     `EXTRACT_TABLE_LONG` no aparecen fuera de `.sdd`). Están en inglés y el panel lee las filas sin
     romperse; falta su documentación en `Savings-and-metrics.md` (hallazgo 11).
7. **Interacciones:**
   - Respaldo: hallazgo 4.
   - Filas de fallo: hallazgo 5.
   - Afinidad: ninguna (extract no tiene celdas).
   - Cruce con otras claves: `placeholder_keys`, `recounted_keys` y `outline_copies` quedan fuera
     del examen, así que no se contradicen con el aviso.
   - Un cliente viejo no aplica la regla. Uno nuevo en la Mac provoca el cambio de modelo en la PC
     a través del turno remoto; ya está documentado.
8. **Reparto:** hallazgo 8. T3 y T4 no comparten ficheros. Ningún test existente se edita según el
   plan.
9. **Verificación:** hallazgos 5 y 13. Lo demás está bien: la prueba en vivo en dos fases con
   ventana de prueba, la tabla antes/después con controles negativos y los tres sitios de
   documentación, a los que hay que añadir `Savings-and-metrics.md`.
10. **Cierre del #586:** hallazgo 10.

## Artefactos del revisor (fuera del repo)

- Copia del prototipo y casos adversos: la carpeta `proto` del scratchpad de la sesión, con
  `adverse.py` y `run.txt`.
- Llamadas `local_*`: 1 (`local_summarize` de `research.md`). La lectura de `spec.md` la resumió el
  hook la primera vez; después la leí por rangos.

## Segunda pasada

Fecha: 2026-11-10 11:06 (hora de Uruguay). Leí la spec nueva (REQ-001 a REQ-039, `spec.md:150-416`)
y el plan nuevo entero (`plan.md:1-284`, con 34 mutantes en `:180-213`), y los contrasté con el
código. Sin backend y sin pytest.

### Veredicto

**APROBABLE CON CAMBIOS, sin bloqueantes.** Los 12 hallazgos de la primera pasada están recogidos
en requisitos y tareas concretas. Quedan cuatro cosas importantes, y la más seria es de
planificación, no de código: tal como está escrita, la puerta del aviso probablemente se cierre en
rojo y arrastre con ella al enrutado.

### 1. ¿Quedaron resueltos el bloqueante y el casi bloqueante?

**El conjunto a ciegas (bloqueante de la primera pasada): resuelto en lo que pedía.**
- REQ-004 (`spec.md:171-186`) exige un autor que no haya visto `detector.py`, la sección «Detector
  A» ni los casos de la revisión.
- Trae los cupos de las cuatro formas que dieron avisos en falso, más CSV (REQ-005), al menos 20
  casos y 100 pares distintos, `sha256` antes de pasarle el detector, la cota de la regla del tres y
  la corrección de plurales decidida antes de congelar (`plan.md:108-116`).

Queda un hueco, en el hallazgo S-1.

**El coste del detector (casi bloqueante): resuelto en el diseño, a medias en la prueba.**
- Lo resuelto (REQ-025, `spec.md:311-321`): normalizar una vez, salida temprana a las 2 000 filas,
  presupuesto calculado antes de la llamada y pruebas con 20 campos y listas de 10 hojas. Además, el
  JSON de 100 000 niveles «no lanza». Ojo, que el prototipo solo captura `ValueError` y ese caso
  lanza `RecursionError`: el requisito lo cazará bien.
- Lo que falta: el presupuesto no tiene número, y tanto el requisito como el mutante «`prepare` sin
  presupuesto» (`plan.md:190`, «devuelve `skipped_budget` **o** termina en menos de 1 s») dependen
  del reloj. Va en S-2.

### 2. ¿Las piezas nuevas rompen algo?

**La mudanza de marcadores es limpia.**
- La lista vive en `server.py:7629-7670` y `_is_no_data_marker` en `:7673-7680`.
- Los únicos usos están dentro de `server.py` (`:7571`, `:7575`, `:7697`) y en
  `tests/test_extract_placeholder_values.py:76`, `:104`, que llaman a `server._is_no_data_marker`.
  REQ-029 conserva ese nombre.
- No hay ningún otro módulo, script ni documento que importe la lista. La copia del prototipo es
  idéntica a la del producto.

**Los dos dueños de `server.py` en serie no dejan ninguna rama en rojo.**
- T4 cambia solo `:7625-7681` y T5 va después (`plan.md:44-46`, `:67-74`). T3 y T4 no comparten
  ningún fichero.
- Busqué guardianes que pudieran ponerse en rojo entre commits y no hay ninguno:
  - ninguno exige documentar cada variable de `config.ENVIRONMENT_VARIABLES`;
  - ningún test fija el contenido de `daemon._TRACED_LOGGERS` (`daemon.py:124`);
  - el único guardián de documentación, el de T6, ya va detrás de T5.

**Cambiar la excepción de fichero no debilita el guardián.**
- La excepción (`tests/data/uncatalogued_exceptions.json:415-420`) es de tipo `verbatim`, por fichero
  y texto. El guardián rechaza las que ya no aparecen
  (`tests/test_no_uncatalogued_text.py:567-573`), así que hay que moverla.
- «sin información» no aparece en ningún otro sitio de `server.py`. Moverla a `no_data.py` deja la
  misma exención, con el mismo alcance (un fichero y un texto) y el mismo motivo.

**`cross_fill: "off"` y el log de errores: bien, con un matiz.** El fichero `daemon-errors.log` solo
existe dentro de `daemon.serve` (`daemon.py:118-155`). En un proceso stdio (el Claude Code de la
Mac, el segundo proceso de T1, una sola llamada directa) el logger no tiene ese manejador y el
aviso va a stderr. Va en S-4.

### 3. ¿Es ejecutable la vía del segundo proceso?

**Sí.** Lo comprobé contra el código:
- `LLAMASWAP_CONFIG` no tiene valor por defecto (`config.py:493-494`). Sin él no hay topología, y la
  `TURN_URL` explícita se usa aunque el backend sea local (`remote_turn.py:242-264`,
  `server.py:2565-2575`).
- El turno del daemon se protege con su token web (`token_source.py:112-123`).
- `turn_leases`/`turn_api` no rechazan una petición del mismo host. La entrada `remote:` existe
  (`turn_leases.py:49`).
- La vía tiene visto bueno del usuario, comprobación previa, vuelta al daemon si algo falla,
  `/Delete` de la tarea al acabar y la lista de lo que no prueba (`plan.md:128-166`, `:224-232`).

**Un cabo, menor:** `LLAMASWAP_CONFIG` está definida como variable **de usuario** en esta máquina,
así que la tarea programada la hereda aunque el lanzador no la ponga. La copia tiene que borrarla
de forma explícita (`Remove-Item Env:LLAMASWAP_CONFIG` antes de `Start-Process`). Si no, el proceso
usa su propio turno local. La comprobación previa lo detectaría y mandaría la tanda al daemon, pero
se perdería la vía buena sin necesidad.

### 4. Hallazgos que quedan

- **S-1. Importante: el aviso en falso solo se mide si `gemma3-4b` acierta.** Los cupos de REQ-004
  van «sobre respuestas que acierten». Si `gemma3-4b` falla en un caso de cupo, esa forma queda sin
  probar, y el conjunto no se puede ampliar después. **Cambio:** que la puerta pase también la
  versión congelada del detector sobre las **respuestas anotadas a mano** del conjunto nuevo (un
  control sin modelo). Criterio: 0 avisos, y se cuentan los cupos sobre esas respuestas. Así
  trabajaban mis casos adversos.
- **S-2. Importante: el presupuesto necesita un número y una prueba que no dependa del reloj
  (REQ-025, mutante de `plan.md:190`).** Si no, el implementador lo ajusta hasta que su máquina baja
  de 1 s, y en el CI con `-n 2` la prueba puede fallar de vez en cuando. **Cambio:**
  - fijar el tope como constante en la spec;
  - que el test de `skipped_budget` cuente comparaciones;
  - dejar las pruebas de tiempo como respaldo con un margen mayor (por ejemplo 5 s);
  - que el mutante exija `skipped_budget`, sin el «o».
- **S-3. Importante: la puerta del aviso va a parar, previsiblemente, todo el cambio.** Mis casos A3,
  A7 y A8 (número repetido con etiqueta sinónima, subcadena de otra fila, celda propia larga) dan
  aviso en falso con la regla estricta tal como está, y la corrección de plurales no los toca. Son
  justo tres de los cupos de REQ-004. Con 1 aviso en falso o más, `plan.md:168-169` cierra T1 y no
  abre T2, así que también se para el enrutado, aunque pase sus propios criterios (REQ-001 a
  REQ-003). **Cambio:** dejar escrita la bifurcación antes de medir. Si falla REQ-004 y pasan REQ-001
  a REQ-003, el enrutado sigue (T3 y la parte de T5 que no es aviso) y el aviso vuelve a diseño con
  su propia puerta. Si no, se gasta una sesión del backend y el único arreglo medido queda bloqueado
  por la pieza parcial.
- **S-4. Menor: dónde va el fallo de `match`.** REQ-026 dice «se escribe en `daemon-errors.log`»,
  pero eso solo ocurre bajo el daemon; en un proceso stdio va a stderr. Hay que decirlo así.
- **S-5. Menor: el mutante de la copia de marcadores puede fallar por cómo se importa.** Si
  `cross_fill` hace `from .no_data import …`, parchear `no_data` en el test no le llega aunque no
  haya copia (`plan.md:191`). Mejor comprobar la identidad: que la lista que usa `cross_fill` sea el
  mismo objeto que la de `no_data`, y lo mismo para `server`.
- **S-6. Menor: falta el `LLAMASWAP_CONFIG` heredado** (apartado 3).

### Cifras del revisor

- 39 requisitos y 34 filas de mutantes, recontados en los ficheros.
- 0 llamadas al backend, 0 llamadas `local_*` en esta pasada (todo fueron lecturas por rangos y
  búsquedas), ningún proceso dejado vivo.
