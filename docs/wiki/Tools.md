# Catálogo de tools

Las **once** tools `local_*` que expone el servidor MCP, con su firma exacta, lo que devuelven y la
letra pequeña que solo estaba en el código. El [README](../../README.md) tiene la tabla de una
ojeada; esta página es la referencia.

## La regla que gobierna todas: pasa `path`, no el contenido

Casi todas aceptan `text` (o `code`, o `diff`) **y** `path`. No son equivalentes:

- Con **`text`**, el contenido pasa por tu contexto antes de llegar a la tool. Ya lo pagaste.
- Con **`path`**, el archivo lo lee el **servidor**, y el contenido no entra a tu contexto jamás.
  Ahí está el ahorro, y por eso todo lo que hay debajo insiste en lo mismo.

Con backend remoto (la Mac delegando en la PC), la ruta se resuelve **en la máquina donde corre el
MCP**, no donde está el modelo. Ver [Backend remoto](Remote-backend.md).

## De un vistazo

| Tool | Qué hace | Modelo | Si la entrada no cabe |
|---|---|---|---|
| [`local_summarize`](#local_summarize) | Resume texto o archivo | mecánico / largo (auto) | **map-reduce** |
| [`local_classify`](#local_classify) | Devuelve UNA etiqueta de una lista | mecánico | trunca |
| [`local_extract`](#local_extract) | Extrae campos → objeto ya validado | mecánico / largo (auto) | trunca y **lo dice** |
| [`local_boilerplate`](#local_boilerplate) | Genera código y lo **escribe en disco** | código | (la spec es corta) |
| [`local_delegate`](#local_delegate) | Escape genérico texto→texto | mecánico, o el que pases | **trozo a trozo** |
| [`local_lint_summary`](#local_lint_summary) | Resume salida de lint/tests/CI | mecánico / largo (auto) | **map-reduce** |
| [`local_commit_msg`](#local_commit_msg) | Mensaje de commit desde un diff | código | **map-reduce** |
| [`local_translate`](#local_translate) | Traduce texto o archivo | mecánico / largo (auto) | **trozo a trozo** |
| [`local_explain_code`](#local_explain_code) | Explica código en prosa | código | trunca |
| [`local_describe_image`](#local_describe_image) | Imagen → texto | visión | — |
| [`local_status`](#local_status) | Diagnóstico de solo lectura | — | — |

Las dos formas de trocear **no** son la misma, y la diferencia se nota en el resultado:

- **map-reduce** — resume cada trozo y funde los resúmenes. Sirve para *reducir*: el resultado es
  más corto que la entrada.
- **trozo a trozo** — transforma cada trozo y concatena. Sirve para *transformar* conservando el
  tamaño (traducir, reescribir); fundir aquí perdería contenido.

El presupuesto de cada trozo se mide en **caracteres** y sale del modelo destino
(`LOCAL_DELEGATE_MAX_CHARS_*`, ver [Configuration](Configuration.md)).

---

## `local_summarize`

```python
local_summarize(text=None, path=None, max_words=150, focus=None) -> str
```

Resume un texto o archivo. Prefiérela a leer el archivo con `Read` cuando pasa de ~200 líneas o
~10 KB y solo necesitas el sentido, no el literal.

| Parámetro | | |
|---|---|---|
| `text` | opcional | El texto a resumir. Usa esto **o** `path`. |
| `path` | opcional | Ruta al archivo, leído por el servidor. **Preferible.** |
| `max_words` | `150` | Tope de palabras del resumen. |
| `focus` | opcional | Qué te interesa (p. ej. `"cifras de configuración"`): el resumen lo prioriza y conserva literales sus datos concretos. Va saneado a una línea de 200 caracteres. |

Enruta sola al modelo de contexto largo cuando la entrada es grande. Si aun así no cabe, hace
map-reduce: el log del panel guarda **una** entrada con `chunks: N`, no N entradas. Si algún
trozo se corta por `max_tokens`, el resultado lo avisa y el log lo registra (`finish_reason:
length`, `truncated_out`).

### Resumen por secciones (experimental, apagado)

Con `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO=1` y un documento Markdown que va al modelo largo, el
resumen sigue la estructura: una línea `## <título>` por sección, en orden, con la introducción y
las subsecciones, y el servidor completa las que el modelo se salte. Está **apagado por defecto**:
mejora mucho la salida (100 % de títulos en los documentos de prueba, frente a 0–11 % en prosa),
pero en la medición con `claude -p` no redujo las veces que Claude vuelve a leer el fichero, que
lo hace para comprobar datos. Detalle en `.sdd/changes/resumen-por-secciones/verification.md`.

## `local_classify`

```python
local_classify(text, labels) -> str
```

Devuelve **una** de las etiquetas de `labels`, sin prosa alrededor. Los dos parámetros son
obligatorios. Una llamada, siempre: si el texto no cabe, se trunca.

## `local_extract`

```python
local_extract(fields, text=None, path=None) -> dict
```

Extrae campos estructurados. **Devuelve un objeto ya validado**, con exactamente las claves que
pediste — no una cadena que haya que parsear.

| Parámetro | | |
|---|---|---|
| `fields` | **obligatorio** | Nombres de los campos, que son las claves del JSON. |
| `text` / `path` | opcional | La fuente. `path` no gasta contexto. |

Dos cosas que conviene saber y solo estaban en el código:

- **Si hubo que truncar la entrada, lo dice en el propio objeto**, con la clave reservada
  `_local_delegate`. Antes ese aviso iba como texto delante del JSON, donde obligaba a limpiar la
  cadena antes de poder parsearla.
- Pide al backend un JSON restringido por schema (`LOCAL_DELEGATE_JSON_SCHEMA=auto`); si el backend
  no lo soporta, reintenta en modo libre.
- **Si respondió un modelo de respaldo**, lo dice en `_local_delegate.respaldo` (qué modelo
  respondió, en lugar de cuál y por qué), nunca dentro de los campos pedidos.

## `local_boilerplate`

```python
local_boilerplate(spec, language, target, overwrite=False) -> str
```

Genera código desde una especificación. **Escribe el resultado en `target` y devuelve solo un
recibo** de dos líneas (ruta, tamaño y los tokens que no entraron al contexto). Si respondió un
modelo de respaldo, el aviso va en el recibo, detrás; el fichero solo lleva lo que generó el modelo.

| Parámetro | | |
|---|---|---|
| `spec` | **obligatorio** | Qué debe hacer el código. |
| `language` | **obligatorio** | `python`, `typescript`, … |
| `target` | **obligatorio** | Ruta **absoluta** del archivo. Los directorios que falten se crean. |
| `overwrite` | `False` | Pisar `target` si existe. Sin él **falla antes de generar nada**. |

`target` es obligatorio **a propósito**: como parámetro opcional, el ahorro dependería de que quien
llama se acuerde de usarlo, y de eso hay tres mediciones seguidas con cero adopción. El código
generado no vuelve a tu contexto; para verlo, abre el archivo.

> **Cambió en la 0.27.0.** Antes devolvía el código. Si tienes una integración vieja que esperaba
> recibirlo, ahora recibe el recibo.

## `local_delegate`

```python
local_delegate(task, input, output_format, model=None, chunk="auto") -> str
```

La tool de escape: cualquier tarea texto→texto que no tenga tool propia.

| Parámetro | | |
|---|---|---|
| `task` | **obligatorio** | Qué hacer, en una frase. |
| `input` | **obligatorio** | El texto de entrada. |
| `output_format` | **obligatorio** | Qué forma debe tener la salida. **No es decorativo**: es lo que hace revisable el resultado. |
| `model` | auto | Fuerza un modelo del catálogo permitido. |
| `chunk` | `"auto"` | Cómo trocear si no cabe. |

Trocea **trozo a trozo**, porque una tarea genérica puede ser una transformación y fundir los
trozos perdería contenido.

## `local_lint_summary`

```python
local_lint_summary(path=None, text=None, max_words=200) -> str
```

Resume la salida de lint, tests o CI: qué falló, dónde y por qué, sin las mil líneas de ruido. Es
la tool para cuando un comando escupe más de lo que cabe — vuelca la salida a un archivo y pasa
`path`. Map-reduce si hace falta.

## `local_commit_msg`

```python
local_commit_msg(diff=None, path=None, style="conventional") -> str
```

Mensaje de commit a partir de un diff.

| Parámetro | | |
|---|---|---|
| `diff` / `path` | opcional | El diff. Para uno grande, vuélcalo a archivo y pasa `path`. |
| `style` | `"conventional"` | Estilo del mensaje. |

Hace map-reduce sobre el diff, y eso importa más de lo que parece: un diff que no cabe y se
**trunca** produce un mensaje que solo describe el principio del cambio.

**Idioma.** El prompt pide el mensaje entero (primera línea y cuerpo) en el idioma que fija
`LOCAL_DELEGATE_COMMIT_LANGUAGE` (`es`, `en`…; ver [Configuration](Configuration.md)). Sin la variable,
pide el idioma predominante de los textos del diff. Antes no pedía ninguno y el modelo elegía:
medido sobre 30 commits de un repo documentado en español, uno de los modelos escribió 17 en inglés.

## `local_translate`

```python
local_translate(target_lang, text=None, path=None) -> str
```

Traduce. `target_lang` es obligatorio; la fuente va en `text` o `path`. Trocea **trozo a trozo**,
que es lo correcto al traducir: el resultado debe conservar el tamaño del original.

## `local_explain_code`

```python
local_explain_code(code=None, path=None, question=None) -> str
```

Explica código en prosa, con el modelo de código. Con `question` responde algo concreto en vez de
dar la explicación general. Una llamada: si el archivo no cabe, se trunca.

## `local_describe_image`

```python
local_describe_image(path, question=None, max_words=200) -> str
```

Describe una imagen o responde una pregunta sobre ella, con el modelo de visión. `path` es
obligatorio — la imagen la lee el servidor, no la adjuntas tú.

Es **imagen→texto** y nada más: no genera ni edita imágenes. El tope de tamaño lo pone
`LOCAL_DELEGATE_MAX_IMAGE_MB` (8 MB por defecto).

## `local_status`

```python
local_status() -> str
```

Diagnóstico de solo lectura: backend, catálogo de modelos, ruta del log, VRAM y RAM del sistema,
las cadenas de respaldo resueltas (con el paso `loaded`, y «sin residente» o «residente: X» según
haya en la config de llama-swap algún modelo con TTL efectivo 0) y los modelos enfriados, con el
tiempo que les queda y cuántas veces seguidas han vuelto a entrar. Además, el **turno** del daemon
(«Turno: sí (choques: …; en uso: …; esperan: N)» o «Turno: no (<motivo>)») y el **ritmo de
referencia** de cada modelo (la mediana de tok/s con la que se decide «lento», y cuántas muestras
tiene).
**No llama al backend de chat**, así que sirve para saber si el backend responde, pero **no**
prueba que la credencial funcione — para eso hace falta una tool que ejerza el modelo de verdad.
Para el diagnóstico completo de la instalación, `local-delegate doctor` (ver
[Instalación](Integration-install.md)).

---

## Qué modelo usa cada perfil

Cuatro perfiles, todos cambiables por entorno (ver [Configuration](Configuration.md)):

| Perfil | Variable | Por defecto | Lo usan |
|---|---|---|---|
| mecánico | `LOCAL_DELEGATE_MODEL_MECHANICAL` | `gemma3-4b` | resumir, clasificar, extraer, traducir, delegar |
| contexto largo | `LOCAL_DELEGATE_MODEL_LONG` | `gemma4-26b-a4b` | los mismos, cuando la entrada es grande |
| código | `LOCAL_DELEGATE_MODEL_CODE` | `qwen36-35b-a3b` | boilerplate, commit-msg, explicar código |
| visión | `LOCAL_DELEGATE_MODEL_VISION` | `gemma4-12b` | describir imágenes |

El salto de mecánico a largo es **automático** y se decide sondeando el tamaño: bytes del archivo
para `path`, caracteres para `text`.

## Turno: dos tools que no se quitan el modelo

En el daemon, con un llama-swap local y `LLAMASWAP_CONFIG` legible, cada delegación **pide turno**
antes de su plaza de concurrencia. Dos modelos **chocan** si cargar uno desaloja al otro, con la
misma regla que llama-swap (mismo grupo con `swap: true`, o uno `exclusive` y el otro no
`persistent`). Una delegación cuyo modelo choca con lo que está en uso **espera**, en cola; una con
un modelo compatible pasa sin esperar si tampoco choca con lo que piden las de delante. Así, un
resumen y un mensaje de commit lanzados a la vez ya no se desalojan el modelo el uno al otro: el
segundo espera y luego carga el suyo.

- El panel enseña esa espera como **espera local** («esperando turno del daemon (en uso: …)»), y el
  log guarda cuánto duró (`turn_wait_ms`).
- Un salto de respaldo **suelta** su plaza y pide turno para el modelo nuevo, al final de la cola.
- Red de seguridad: si la primera de la cola lleva `LOCAL_DELEGATE_TURN_MAX_S` (600 s) esperando
  **y** el daemon lleva otros tantos sin que empiece ni termine ninguna llamada al backend, se le
  concede igual (`turn: "forced"` en el log).
- Sin topología (sin `LLAMASWAP_CONFIG`, router `matrix`, backend remoto…) no hay turno y todo va
  como antes; `local_status` dice por qué. Los procesos que no pasan por el daemon (un `stdio`
  suelto, la Mac) no piden turno.
- Una espera de turno más la inferencia puede pasar del plazo de tu cliente MCP: ver
  [plazos de los clientes](Integration-install.md#plazos-de-los-clientes-mcp).

## Afinidad: usar el modelo que ya está cargado

Si el modelo grande ya está en memoria, a veces es mejor usarlo para una tarea mecánica que
desalojarlo para cargar el pequeño. El daemon lo hace **solo** donde una medición previa lo aprobó:
una celda «tool → modelo alternativo» que pasó, frente al modelo del rol, el criterio de aprobación
escrito antes de medir (`benchmarks/afinidad-2026-10/veredicto.json`). Hoy hay **cuatro celdas aprobadas**, todas frente
al rol mecánico (`gemma3-4b`); la de commit se midió frente al rol de código:

| Tool | Alternativo | Estado |
| --- | --- | --- |
| `local_translate` | `gemma4-26b-a4b` | aprobada |
| `local_translate` | `qwen36-35b-a3b` | aprobada |
| `local_lint_summary` | `gemma4-26b-a4b` | aprobada |
| `local_delegate` | `gemma4-26b-a4b` | aprobada |
| `local_classify`, `local_extract` (los dos alternativos); `local_lint_summary` y `local_delegate` con `qwen36-35b-a3b` | — | rechazadas |
| `local_commit_msg` | `gemma4-26b-a4b` | rechazada, frente a `qwen36-35b-a3b` (el rol de código); además, por decisión del usuario, sin afinidad de commit |

`local_summarize` queda fuera, y nunca se va de código o largo al modelo mecánico ni con `model`
explícito. Con una celda aprobada, el alternativo se usa si está en uso por el propio daemon o
**cargado con margen**: `ready` en `/running`, sin un cambio de modelo pendiente de otro cliente que
lo desalojaría, y con TTL 0, una petición en vuelo o al menos `LOCAL_DELEGATE_AFFINITY_MARGIN_S` (5 s)
de TTL por delante. Si alguien espera turno, la afinidad no se cuela. Si el rol ya está cargado, se
usa el rol.

- **Huella.** Cada celda se midió con un GGUF, unos flags (`-ncmoe`, contexto, cachés, `--reasoning`,
  `--mmproj`) y unos prompts concretos. Si la config vigente difiere, la celda no se usa y `doctor`
  avisa («afinidad sin base»). En **otra máquina**, donde las rutas de los GGUF medidos no existen,
  la afinidad queda **inerte** y `doctor` lo dice en el detalle, sin `[WARN]`.
- **Si falla el alternativo**, se prueba el modelo del rol y luego su cadena, también por un fallo
  de capacidad (la afinidad la eligió el daemon, no quien llama). Fuera de la afinidad, un fallo de
  capacidad sigue sin respaldo si no hay nada en `loaded` (ver [Configuration](Configuration.md#respaldo-entre-modelos)).
- Con el modelo del rol en enfriamiento no hay afinidad: va a la cadena del rol, como siempre.
- En el log: `routing: "affinity"`, `model_requested` (el del rol), `affinity_foreign_flight` y, si
  el alternativo hubo que cargarlo, `affinity_failed`; si el alternativo falló, `affinity_dropped` y
  `affinity_dropped_class`. **No cuenta como respaldo** en el panel. Ver
  [Savings & metrics](Savings-and-metrics.md#qué-se-mide).

## Cuándo NO delegar

Estas tools son para pasos mecánicos con un formato de salida claro. Lo que pide criterio,
arquitectura, razonamiento encadenado o cruzar varias fuentes **no** se delega: el ahorro no
compensa un resultado que hay que rehacer.

## Ver también

- **[Savings & metrics](Savings-and-metrics.md)** — cómo se cuenta el ahorro de cada llamada.
- **[Backend remoto](Remote-backend.md)** — dónde se resuelve `path` cuando el modelo está en otra máquina.
- **[Troubleshooting](Troubleshooting.md)** — qué hacer cuando una tool responde `401` o el backend no está.
