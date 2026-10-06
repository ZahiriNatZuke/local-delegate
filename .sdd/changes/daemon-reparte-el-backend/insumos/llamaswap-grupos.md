# Grupos de llama-swap y esperas por cambio de modelo

Investigación de solo lectura, 2026-10-06. No se tocó nada: ni la config, ni el lanzador, ni el daemon, ni el repo. No se cargó ningún modelo. `metrics.db` se consultó sobre una **copia** (db + wal + shm) en el scratchpad.

## Respuesta corta

- **El swap entre los tres modelos grandes es una necesidad física, no una elección de configuración.** Con la reserva de la PC compartida (2 GB de VRAM para el resto del sistema), el residente `gemma3-4b` deja unos 11 GB libres, y cada modelo grande ocupa entre 9 y 10,5 GB. Dos a la vez no caben, ni en VRAM ni en RAM.
- **El caso del 2026-09-30 no fue sobre todo una espera por swap.** De los ~468 s que sumaron las 4 llamadas de la Mac, unos **95 s** fueron bloqueo real por `gemma4-26b-a4b`, y eso solo en 2 de las 4 llamadas. Las dos primeras no esperaron a nadie: el grupo `swap` estaba vacío. El grueso del tiempo se fue en **inferencia degradada**: `qwen36-35b-a3b` iba a 7–20 tok/s y procesaba el prompt a 19–116 tok/s, cuando su mediana es de 41 y 439. Es lo que se espera cuando los expertos mapeados en RAM se están leyendo de disco (presión de RAM; ese mismo día la PC se quedó sin recursos por tres `jest` simultáneos).
- **En 30 días hubo 2 episodios de bloqueo por el grupo `swap`**, con 12 peticiones afectadas y unos 520 s en total. Solo 2 de esas peticiones son de la Mac. El otro episodio (2026-10-01) **lo provocó la propia PC**: `local_commit_msg` y `local_lint_summary` corrieron en paralelo y se quitaron el modelo seis veces.
- Hay otros costes de latencia que pesan más que el swap: la cola dentro del mismo modelo (`-np 1` con 2 peticiones simultáneas del daemon) y las cargas en frío que provoca el TTL.
- **Recomendación: no tocar los grupos.** Si se quiere actuar, lo barato y sin riesgo de OOM está en el **daemon**, no en llama-swap (ver «Recomendación»).

---

## 1. Cómo están definidos hoy los grupos y qué hace cada opción en la v255

### Qué corre

- El proceso vivo es `D:\Projects\llms\llama-swap-v255\llama-swap.exe --config D:\Projects\llms\llama-swap\config.yaml -watch-config --listen 127.0.0.1:9292` (`--version` → `v255 (7761aa1)`). Arrancó el 2026-10-03 a las 10:17.
- Ojo: el `llama-swap.exe` que hay en `D:\Projects\llms\llama-swap\` es la **v238**, y el de WinGet que usa `start-swap.ps1` es la **v235**. Ninguno de los dos es el que corre. El comentario de `start-swap.ps1` («Sirve los 4 modelos… un modelo a la vez») está desfasado.

### Config vigente (`config.yaml`, 2026-09-15)

| Modelo | Grupo | `ttl` | Flags relevantes |
| --- | --- | --- | --- |
| `gemma3-4b` | `resident` | 600 | `-ngl 99`, ctx 8192 |
| `qwen35-2b` | `swap` | 300 | `-ngl 99`, ctx 8192 (sin rol) |
| `gemma4-26b-a4b` | `swap` | 300 | `-ncmoe 12`, ctx 38400, `--load-mode mmap`, `-np 1` |
| `qwen36-35b-a3b` | `swap` | 300 | `-ncmoe 20`, ctx 16384, `--load-mode mmap`, `-np 1` |
| `gemma4-12b` | `swap` | 30 | ctx 8192, `--load-mode mmap`, `-np 1` |

```yaml
groups:
  resident: { persistent: true,  swap: false, exclusive: false, members: [gemma3-4b] }
  swap:     {                    swap: true,  exclusive: false, members: [gemma4-26b-a4b, qwen36-35b-a3b, qwen35-2b, gemma4-12b] }
```

No hay `globalTTL`, `routing`, `scheduler` ni `concurrencyLimit`, así que rige el valor por defecto: 10 peticiones activas por modelo en llama-swap.

### Semántica según la v255, leída de la documentación y del código de la etiqueta `v255`

Fuentes descargadas a `scratchpad/docs-v255/`: `docs/kb/guides/routing/groups-and-matrix.md`, `capacity-and-queues.md`, `model-runtime/ttl-and-unloading.md`, `docs/config.example.yaml`, `internal/router/group.go`, `internal/router/scheduler/fifo.go`, `internal/router/design.md`, `internal/config/load.go` e `internal/server/metrics*.go`.

- **`groups` en el nivel superior es sintaxis heredada, y se acepta de forma permanente.** En la v255 lo canónico es `routing.router.use: group` + `routing.router.settings.groups`. `load.go` normaliza la clave vieja («permanent backwards-compat input fields») y solo da error si se usan las dos a la vez. No hace falta migrar.
- **`swap`** (por defecto `true`) gobierna cómo se comportan los miembros *entre sí*. Con `true`, solo uno a la vez: cargar uno descarga a sus hermanos. Con `false`, conviven.
- **`exclusive`** (por defecto `true`) gobierna cómo afecta el grupo a *los demás*. Con `true`, cargar un miembro descarga todo lo que esté en otros grupos que no sean `persistent`. Con `false`, no toca a nadie.
- **`persistent`** (por defecto `false`): otros grupos nunca pueden descargar a sus miembros. **No le afecta al TTL.** La documentación dice que, para tener un modelo siempre caliente, hace falta `ttl: 0` **más** el grupo `persistent`. Hoy `gemma3-4b` tiene `ttl: 600`, así que se descarga tras 10 min sin uso: 11 cargas en frío en 3 semanas, con una mediana de 6 s.
- **`members`**: cada modelo pertenece a un solo grupo.
- **`ttl`** (por modelo, en segundos; `-1` hereda `globalTTL`, `0` = nunca): descarga tras ese tiempo de **inactividad**, y el reloj se reinicia con cada petición.
- **`groupSwapper.EvictionFor`** (`group.go`): desaloja a los hermanos del mismo grupo si el grupo tiene `swap: true`, y a los de otros grupos solo si el grupo destino es `exclusive` y el otro no es `persistent`.
- **Programador FIFO** (`fifo.go`, el único que existe). Ante una petición:
  1. si ya hay un cambio en curso hacia ese modelo, se une a él;
  2. **vía rápida**: si el modelo ya está listo y no hay que desalojar a nadie, se sirve en el acto, **aunque haya peticiones en cola para otro modelo**;
  3. si choca con un cambio en curso, va a la cola;
  4. **si habría que desalojar un proceso que aún tiene peticiones en vuelo, va a la cola hasta que ese proceso se vacíe**;
  5. si no, empieza el cambio.

  La propia documentación lo resume así: «A B C A B C → A A B B C C». Consecuencia: **un cambio nunca interrumpe una petición en curso**, y quien pide el otro modelo espera a que el que está cargado termine **todo** lo que tenga en vuelo. Si el cargado sigue recibiendo peticiones solapadas, las nuevas entran por la vía rápida y quien espera puede quedarse atrás.
- **Prioridad**: `routing.scheduler.settings.fifo.priority: {modelo: n}` ordena la **cola** por modelo (mayor = antes). No adelanta a lo que ya está en vuelo ni distingue clientes.
- **Router `matrix`** (alternativa a `group`): lista combinaciones permitidas (`sets`) con `&` y `|`, y usa `evict_costs` para elegir qué desalojar. Sirve cuando las combinaciones dependen del par concreto de modelos. Aquí no aporta nada, porque la única combinación que cabe es «residente + un grande», y eso ya lo expresan los grupos.
- **`metrics.db`**: `duration_ms` se mide desde que la petición entra en el middleware, **antes** de la cola del router (`newBodyCopier` en `metrics_middleware.go:77`). Por eso **incluye la cola y la carga del modelo**, y `ts_created` es el momento en que termina. El campo `src` sale de `RemoteAddr`, y como la Mac entra por `tailscale serve`, **todas las filas dicen `ip:127.0.0.1`**: metrics.db no distingue el origen.

## 2. ¿Qué cabe a la vez en 16 GB?

Las cifras salen de la tabla de coexistencia medida el 2026-09-15 con navegador, video y las apps de siempre (`.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md`, alrededor de las líneas 2013–2047), con los mismos flags de producción. El adaptador tiene 16 311 MiB. El escritorio en reposo ocupa 710–830 MiB, y con el video en primer plano llegó a 1 996 MiB. La reserva acordada para el resto de la PC es de 2 048 MiB de VRAM y 8 GB de RAM.

| Modelo (flags de producción) | VRAM dedicada pico | RAM / disco |
| --- | --- | --- |
| `gemma3-4b` (residente) | 3 270 MiB | fichero de 2,5 GB |
| `qwen35-2b` | no medido; ~3–3,5 GB estimados (fichero Q8_K_XL de 2,8 GB + KV de 8k) | — |
| `gemma4-12b` + mmproj | 9 060 MiB | fichero de 7,1 GB |
| `gemma4-26b-a4b` `-ncmoe 12` | 10 534 MiB | fichero de 13,6 GB; ~11,7 GB de RAM del sistema |
| `qwen36-35b-a3b` `-ncmoe 20` | 10 120 MiB | fichero de 17,7 GB; al cargar deja la RAM libre en 1,8–1,9 GB |

Presupuesto para modelos con la reserva: 16 311 − 2 048 = **14 263 MiB**.

| Combinación | VRAM | ¿Cabe? |
| --- | --- | --- |
| residente + 26B | 13 804 | sí (es la elección del 2026-09-15) |
| residente + Qwen3.6 | 13 390 | sí |
| residente + 12B | 12 330 | sí |
| residente + 2B | ~6,5 GB | sí |
| 26B + Qwen3.6 (sin residente) | 20 654 | **no** |
| 26B + 12B / Qwen3.6 + 12B | 19 594 / 19 180 | **no** |
| residente + 26B + 2B | ~17 GB | **no** (WDDM desaloja al residente) |
| 12B + 2B (sin residente) | ~12,5 GB | en VRAM sí, pero no resuelve nada |

¿Y si se mandan más expertos a la CPU para que quepan 26B y Qwen3.6 juntos? Cada capa libera ~395 MiB en el 26B y ~356 MiB en Qwen3.6. Para dejar ~5,5 GB a cada uno y conservar al residente, harían falta `-ncmoe` ≈ 25 y ≈ 33. Eso tiene dos problemas:

- **la velocidad cae en picado**: el 26B ya baja a 26,9 tok/s con 16;
- **la RAM no da**: 11,7 GB del 26B más el grueso de 17,7 GB de Qwen3.6 en una PC de 32 GB que en uso normal tiene ~2 GB libres.

Con `mmap` no saldría un OOM duro, sino paginación a disco, que es justo lo que se vio el 2026-09-30.

**Conclusión: el swap entre 26B, Qwen3.6 y 12B es físico.** Que `qwen35-2b` esté en el grupo `swap` sí es una elección, pero no influye: no tiene rol y solo hay 7 usos en la historia de la base.

## 3. Cuantificación (ventana 2026-09-06 → 2026-10-06)

### Método (scripts en `scratchpad/mdb/analiza.py` y `analiza2.py`)

- **Origen**: una fila de metrics.db es «de la PC» si cae dentro del intervalo `[ts − latency_ms, ts]` de una llamada de `%LOCALAPPDATA%\local-delegate\usage-*.jsonl`. Todas las llamadas del daemon de la PC usan `backend: local`. Las demás filas son «no-PC»: la Mac u otro cliente directo. Las 4 llamadas de la Mac del 2026-09-30 que pasó el coordinador coinciden al segundo con las filas 570, 571, 573 y 574 (ver abajo).
- **Espera** (cola + carga): `duration_ms − (prompt_n / prompt_per_second + predicted_n / predicted_per_second)`, que se puede calcular porque `duration_ms` incluye la cola.
- **Bloqueo por el grupo**: la petición llega mientras **otro** modelo del grupo `swap` tiene una petición en vuelo. El bloqueo dura desde la llegada hasta que termina esa petición.
- Desde el 2026-09-16 no hubo filas con modelos del catálogo viejo en ningún episodio de bloqueo: los resultados del bloqueo son idénticos con la ventana de 30 días y con la del catálogo actual.

### Peticiones bloqueadas por otro modelo del grupo `swap`

| Fila | Llegada (UTC) | Modelo | Origen | Bloqueo | Espera total | Duración |
| --- | --- | --- | --- | --- | --- | --- |
| 572 | 09-30 12:05:02 | 26B | PC (`local_summarize`) | ~10 s | 38 s | 78 s |
| 573 | 09-30 12:05:32 | Qwen3.6 | **Mac** (`local_commit_msg`) | ~47 s | 79 s | 102 s |
| 574 | 09-30 12:05:32 | Qwen3.6 | **Mac** (`local_commit_msg`) | ~48 s | 102 s | 149 s |
| 575 | 09-30 12:06:24 | 26B | PC (`local_extract`) | ~96 s | 121 s | 152 s |
| 576 | 09-30 12:06:24 | 26B | PC (`local_extract`) | ~96 s | 153 s | 176 s |
| 577 | 09-30 12:08:57 | 12B | PC (`local_describe_image`) | ~24 s | 40 s | 43 s |
| 618–623 | 10-01 02:45–02:48 | Qwen3.6 ↔ 26B, 6 cambios | PC (`local_commit_msg` en paralelo con `local_lint_summary`) | 18–51 s cada una, **199 s** en total | — | — |

- **Total: 2 episodios, 12 peticiones, ~520 s de bloqueo.** La Mac: 2 peticiones, ~95 s. La PC: 10 peticiones, ~425 s, de los cuales 226 s se los causó la Mac el 09-30 y 199 s se los causó ella misma el 10-01, cuando `local_commit_msg` tardó 198 s y `local_lint_summary` 247 s.
- **Desalojos sin bloqueo** (el otro estaba cargado pero inactivo, así que se paga descarga + carga): 17, con mediana de 14 s y ~308 s en total.

### Para comparar: otros costes de latencia en la misma ventana

| Coste | Peticiones | Total |
| --- | --- | --- |
| Carga en frío tras vencer el TTL (sin desalojo) | 26B: 50 (mediana 14 s); Qwen3.6: 19 (mediana 14 s); 4B: 16 (6 s) | ~1 400 s |
| Cola dentro del mismo modelo (`-np 1`, el daemon manda hasta 2 a la vez) | 26B caliente: 180, mediana 0 s, máx. 121 s | ~1 150 s |
| Bloqueo por el grupo `swap` | 12 | ~520 s |
| Desalojo sin bloqueo | 17 | ~308 s |

El swap es el **tercer** coste, por detrás del TTL y de la cola del propio modelo.

### El 2026-09-30, llamada a llamada (Mac)

Estado previo:

- el 26B terminó a las 11:13:19 y su TTL de 300 s lo descargó hacia las 11:18;
- el 12B, hacia las 11:29;
- **a las 12:02:31 el grupo `swap` estaba vacío**.

| Mac (log) | Fila | Llegada | Lo que pasó | Inferencia real | Inferencia típica (mediana de Qwen3.6) |
| --- | --- | --- | --- | --- | --- |
| 12:03:27, 55,8 s, 724/14 | 570 | 12:02:31 | carga en frío de Qwen3.6 (~30 s), **sin swap** | 25,3 s (30 tok/s de prompt, 10 tok/s de salida) | ~2 s |
| 12:05:11, 160,6 s, 5439/18 | 571 | 12:02:31 | esperó a la 570 en la cola de `-np 1` (~55 s), **sin swap** | 104,7 s (53 / 6,8 tok/s) | ~13 s |
| 12:07:14, 102,4 s, 407/15 | 573 | 12:05:32 | **bloqueo de ~47 s** por el `local_summarize` de la PC en el 26B (12:05:02–12:06:20), luego descarga del 26B y carga de Qwen3.6 | 23,2 s (19 / 8,1 tok/s) | ~1,3 s |
| 12:08:01, 149,0 s, 5359/16 | 574 | 12:05:32 | el mismo bloqueo (~48 s) más la cola detrás de la 573 | 46,4 s (116 / 20,4 tok/s) | ~12 s |

- **Reparto de los ~468 s**: unos **95 s** de bloqueo por swap (20 %); unos **170 s** de exceso de inferencia (36 %), porque la inferencia real sumó 200 s cuando lo típico serían ~28 s; y el resto, carga en frío más la cola de `-np 1` entre sus propias dos llamadas simultáneas.
- **Esas 4 filas son las más lentas de toda la historia de Qwen3.6** en salida: 6,8–20 tok/s, cuando la mediana es de 41,5 y la peor del resto de la historia es 18,4. La primera petición tras cargar suele tener el prompt lento (~100–200 tok/s, se están calentando las páginas de `mmap`), pero la salida se mantiene en ~40. Una salida a 7–10 tok/s apunta a expertos leídos de disco, o sea, a presión de RAM.
- La PC también pagó: las filas 575 y 576 esperaron ~96 s a que terminara la Mac, que iba lenta por lo mismo. La 577 esperó además en el propio daemon, porque los 2 huecos de `MAX_CONCURRENT_REQUESTS` estaban ocupados: el daemon midió 148,6 s y llama-swap 42,8 s.
- **Fallos de 12:49 a 12:54**: metrics.db no tiene **ninguna** fila entre las 12:11:43 y las 18:00:54. La PC estaba inactiva y no hubo cambios de modelo en esa ventana, así que esos `connect_error` son de la VPN de la Mac, sin relación con el swap.

### Límites de la medición

- «No-PC» no es exactamente «Mac»: cualquier cliente directo contra :9292 aparece igual. Del 2026-09-30 sí hay confirmación con el log de la Mac. Para el resto de la ventana hace falta el `usage-*.jsonl` de la Mac.
- La inferencia «típica» se estima con medianas de toda la historia, y el «bloqueo» se reconstruye con las horas de inicio y fin. Son aproximaciones de ±unos pocos segundos.
- No existe un registro de la RAM libre de esa mañana. La presión de RAM es la explicación más coherente con las tasas (y con el incidente de los `jest` ese día), pero **no está medida**.

## 4. Opciones

| # | Opción | Qué resuelve | Pros | Contras | Riesgo de OOM | Cómo verificarlo antes de adoptarla (con un control que pueda salir distinto) |
| --- | --- | --- | --- | --- | --- | --- |
| A | **Dejarlo como está** | — | Cero riesgo; el bloqueo es raro (2 episodios en 30 días, 95 s para la Mac) | El día que coinciden, la Mac puede esperar ~1 min de más | Ninguno | Repetir este análisis a los 30 días con el log de la Mac. Si los episodios pasan de ~1 por semana o el bloqueo de la Mac supera ~5 min al mes, pasar a C o D. |
| B | **Grupo de coexistencia** (26B + Qwen3.6 con `swap: false`, o `matrix` con `g26 & q36`) | El bloqueo entre los dos grandes | Ninguno práctico | Con los `-ncmoe` actuales necesita 20,6 GB de VRAM. Para que entren hay que llevar `-ncmoe` a ~25/~33, con una pérdida grande de tok/s, y la RAM no alcanza (11,7 GB + ~15 GB en 32 GB) | **Alto.** Con «Prefer No Sysmem Fallback», si se pasa de VRAM es OOM. Si «cabe» a costa de RAM, hay paginación como la del 09-30 | Pasar `medir_coexistencia.py` con las 5 condiciones (incluida «el residente no baja más de 256 MiB») cargando **los dos a la vez** con video de fondo. Se espera «no cabe». El control puede dar «sí» si se mide con la PC vacía: por eso hay que medir con el escritorio cargado (P-14). |
| C | **Afinidad en el daemon**: `local_commit_msg` (o el rol `code` en general) usa el 26B si `/running` dice que es el que está cargado y Qwen3.6 no | El caso concreto de la Mac (y el ping-pong del 10-01 si se aplica también en la PC) | No carga nada nuevo: **cero riesgo de OOM**. El 26B tiene más contexto (38 400) | Es un cambio en local-delegate, no en la config. La calidad de commit_msg en el 26B no está medida (F2 eligió Qwen3.6 para `code`). La Mac tendría que consultar `/running` del backend remoto con la API key. Hay una carrera inofensiva: el modelo puede cambiar entre la consulta y la llamada | Ninguno | (1) Calidad: pasar los casos de commit del corpus de F2 por el 26B con la métrica de F2. Si queda por debajo del umbral del rol, se descarta. Es un resultado que puede salir en contra. (2) Enrutado: test con `/running` simulado («26B cargado» → 26B; «nada» → Qwen3.6) y un mutante que ignore `/running`. Hay que comprobar **qué assert dispara**. |
| D | **Serializar en el daemon por grupo**: no lanzar a la vez dos llamadas a modelos **distintos** del grupo `swap` (semáforo por grupo; las del residente siguen en paralelo) | El ping-pong que la PC se provoca a sí misma (10-01: 199 s, 6 cambios) | Barato; sin riesgo de memoria. Con `-np 1` no se pierde rendimiento, porque las llamadas al mismo modelo ya van en serie en `llama-server` | No arregla PC contra Mac (son dos daemons distintos). Es un cambio de código | Ninguno | Test con dos tools en paralelo hacia modelos distintos: hoy dan N cambios (6 en el caso real); con el semáforo, 1. Un mutante sin semáforo debe hacerlo fallar. En vivo: después de adoptarlo, contar los cambios A→B→A en menos de 5 min con `analiza2.py`. |
| E | **Prioridad FIFO** (`routing.scheduler.settings.fifo.priority: {qwen36-35b-a3b: 10}`) | Que, en la cola, Qwen3.6 pase antes que el 26B | Una línea de config; sin riesgo de memoria | **No toca el bloqueo principal**: la prioridad no adelanta a lo que está en vuelo, y la vía rápida sigue sirviendo al modelo cargado aunque haya cola. Solo cambia el orden cuando hay **varios** esperando, y es por modelo, no por cliente | Ninguno | Simulación con dos modelos pequeños en un llama-swap de prueba en :9595 (residente + 2B, ver «Medición diseñada»): mismo guion con y sin `priority`, comparando el orden de servicio. Si el orden sale igual, la opción no aporta nada. |
| F | **TTL distintos** | El 26B y Qwen3.6 con TTL de 300 s → a la baja: liberan antes RAM y VRAM | Bajar el TTL de Qwen3.6 reduce la presión de RAM (la causa probable de la lentitud del 09-30); subirlo **no cambia** el bloqueo (que depende de lo que esté en vuelo, no del TTL) | Bajarlo aumenta las cargas en frío, que ya son el mayor coste (~1 400 s en 30 días). Subirlo deja 11,7 GB o más de RAM ocupados más tiempo en una PC compartida | Subir el TTL aumenta la presión de RAM (paginación); bajarlo no tiene riesgo | Contar en metrics.db las cargas en frío por modelo y la mediana de tok/s de la primera petición antes y después del cambio, durante 2 semanas. Si las cargas en frío suben más de lo que baja la cola, revertir. |
| G | **`gemma3-4b` con `ttl: 0`** (no lo pidieron; observación) | 11 cargas en frío del residente en 3 semanas (mediana 6 s) | Lo que recomienda la documentación para «siempre caliente» | Ocupa 3,3 GB de VRAM de forma permanente, aunque eso ya es así en la práctica casi todo el día | Bajo (ya está dimensionado para convivir) | Ver en metrics.db que las cargas en frío de `gemma3-4b` pasan a 0 y que la VRAM en reposo no supera el presupuesto con el video de fondo. |

## Recomendación

1. **No tocar los grupos de llama-swap.** El swap es físico, la v255 los entiende con la sintaxis actual y el bloqueo por grupo es raro: unos 95 s para la Mac en un mes.
2. **Si se quiere actuar, empezar por la opción D (serializar en el daemon por grupo).** Elimina el único patrón que se repite y que la PC se causa sola (el ping-pong de commit_msg con lint_summary), no tiene riesgo de memoria y se verifica con un test que puede fallar.
3. **La opción C (afinidad) solo después de medir la calidad de commit_msg en el 26B** con el corpus de F2. Si pasa, resuelve también el caso de la Mac sin cargar nada nuevo.
4. **Lo que más habría cambiado el 09-30 es la presión de RAM, no los grupos.** Propuesta barata: que el daemon (o un script) marque las peticiones con tok/s de salida por debajo del 50 % de la mediana de su modelo, y registrar la RAM libre cuando pase. Así la próxima vez se distingue «esperó por swap» de «el modelo iba lento».

## Medición diseñada (no ejecutada)

- **Reproducir el bloqueo sin modelos grandes**: llama-swap v255 de prueba en :9595 (como en la sesión 9 de F2), con `gemma3-4b` y `qwen35-2b` en un grupo `swap: true` (~3 GB de VRAM cada uno, sin el residente). Guion: una petición larga al modelo A, y a los 2 s una corta al modelo B y otra al A. **Lo esperado según `fifo.go`**: la del A entra por la vía rápida antes que la del B, y B espera a que A se vacíe. Con `priority: {B: 10}`, B pasa por delante de otras peticiones **en cola**, pero no de la del A que llega con A cargado. Control: si B se sirve antes de que termine la primera del A, mi lectura del programador está mal. Hay que hacerlo con la PC sin otros pesados y con el cerrojo `pesado.sh`.
- **Confirmar la hipótesis de RAM**: la próxima vez que una llamada de Qwen3.6 salga por debajo de 20 tok/s, anotar `GlobalMemoryStatusEx` (RAM libre), los fallos de página del `llama-server` (`Get-Process … | Select PagedMemorySize64, PrivateMemorySize64` y `\Process(llama-server)\Page Faults/sec`) y los procesos `node`/`jest` vivos. Si esa lentitud aparece con la RAM libre por encima de 6 GB, la hipótesis cae.

## Llamadas `local_*`

**0.** Las tools se cargaron como pedía el encargo, pero no se usaron, por dos motivos:

- **Cualquier llamada habría cargado un modelo en llama-swap** (el 26B o Qwen3.6). Eso va contra la instrucción de «no lances modelos» y además **habría contaminado `metrics.db`**, que es justo el objeto de la medición, con una fila nueva y un posible cambio de modelo.
- Los ficheros de partida eran pequeños (config de 2,8 KB, lanzador de 3,2 KB, guías de 1–5 KB). Los grandes (`config.example.yaml` de 31 KB, `design.md` de 21 KB, `fifo.go` de 17 KB) se consultaron con `grep` y lecturas acotadas, porque hacía falta el texto literal de la semántica, no un resumen.
