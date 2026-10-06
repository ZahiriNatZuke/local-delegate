# Densidad de entrada (caracteres por token) por modelo, contenido y esfuerzo

Insumo del cambio `coste-api-y-cuota`. Responde a la objeción de que los 2,02 / 1,94 / 2,15
caracteres por token de `research.md` §6 se midieron con un solo modelo (Opus 5.5) y tres tipos de
texto, y a la pregunta de si el esfuerzo (effort) cambia el consumo.

## 1. Criterio fijado antes de medir

Escrito a las **2026-10-06T14:27:31Z**, antes de la primera llamada de medición.

Definiciones:

- **Cuerpo** de una celda = tokens de entrada totales (`input_tokens` + `cache_creation_input_tokens`
  + `cache_read_input_tokens`) de la llamada con el texto, menos los de la llamada de control del
  mismo modelo (mismo prompt sin el texto). **Densidad** = caracteres del texto / tokens del cuerpo.
- **R_ctrl** = diferencia absoluta en tokens entre dos controles seguidos del mismo modelo.
- **Ruido relativo r** = el mayor de: R_ctrl / tokens del cuerpo; la diferencia relativa entre dos
  repeticiones de una misma celda (se repite Opus 5.5 × prosa); y un suelo de 0,5 %.

Reglas:

1. **La resta es válida** si los dos controles de cada modelo dan el mismo total (R_ctrl = 0). Si no
   dan lo mismo, R_ctrl entra en el ruido y se anota.
2. **La densidad depende del modelo** para un contenido si la dispersión entre modelos,
   (máx − mín) / mín, supera **max(3·r, 3 %)**.
3. **La densidad depende del contenido** dentro de un modelo si la dispersión entre contenidos
   supera **max(3·r, 10 %)**.
4. **El esfuerzo no cambia la entrada** si la diferencia de tokens de entrada entre dos niveles, con
   el mismo texto y modelo, es ≤ R_ctrl (lo esperado: 0 tokens).
5. **El esfuerzo cambia la salida** si los rangos de las 3 repeticiones de cada nivel no se solapan
   (el mínimo de uno supera el máximo del otro). Se informa la razón entre medias.
6. **Recomendación**: si la regla 2 se cumple en 3 o más de los 5 contenidos → **una densidad por
   modelo**; si además la regla 3 da una dispersión > 25 % dentro de los modelos → **por modelo y
   contenido**; si no → **una global** con margen = la mitad de la mayor dispersión observada.

## 2. Método

- `claude -p --model <id> --output-format json --max-turns 1 --strict-mcp-config`, Claude Code
  2.1.291, desde un directorio vacío del scratchpad, una llamada detrás de otra. El texto va por
  stdin dentro de `<texto>…</texto>` con la instrucción «No investigues ni uses herramientas:
  responde únicamente con la palabra ok». La palabra «investigues» está puesta a propósito: el hook
  `suggest_delegate_prompt.py` del usuario inyecta ~60 tokens de aviso cuando el prompt contiene
  «resum», «pytest», «extrae»… y calla si aparece una palabra de su lista `_HOST_ONLY`. Así ni el
  control ni las celdas reciben inyección, y la resta no depende del contenido.
- Tokens de entrada = `input_tokens` + `cache_creation_input_tokens` + `cache_read_input_tokens`
  del campo `usage` (coincide con `modelUsage`, que en todas las llamadas solo tuvo el modelo pedido).
- Textos fijados en el scratchpad (`textos/`), recortados a ≤ 10 000 caracteres por línea completa:

| Contenido | Origen | Caracteres |
|---|---|---:|
| prosa | `docs/wiki/Architecture.md` (prosa en español con un diagrama de texto) | 9 543 |
| python | `src/local_delegate/server.py`, desde la primera `def` tras el carácter 20 000 | 9 958 |
| log | salida real de `pytest -v` de 4 ficheros de tests del repo (88 tests) | 8 543 |
| json | `usage-202610.jsonl` del daemon (primeras líneas) | 9 700 |
| diff | `git show 95a65ee`, sin la línea `Author:` | 9 873 |

### Trampa encontrada en la resta: el suelo varía con los MCP

Los dos primeros controles de Opus 5.5, **sin** `--strict-mcp-config`, dieron **44 262** y
**44 965** tokens: 703 de diferencia, un 16 % del cuerpo de un texto de 10 000 caracteres. La lista
de tools cambia según qué servidores MCP conecten en cada arranque (en esta sesión fallan
`MCP_DOCKER` y `pycharm`). Con `--strict-mcp-config` (flag del proceso, no toca la configuración
del usuario) el suelo quedó fijo: **39 490 / 39 490**. Todo lo que sigue se midió así.
Consecuencia para quien repita esto: **sin aislar los MCP, la resta no es estable**.

## 3. Controles (suelo de cada modelo)

| Modelo | Control 1 | Control 2 | R_ctrl |
|---|---:|---:|---:|
| claude-opus-5-5 (con MCP) | 44 262 | 44 965 | 703 (descartado) |
| claude-opus-5-5 | 39 490 | 39 490 | 0 |
| claude-sonnet-5-5 | 39 456 | 39 456 | 0 |
| claude-haiku-4-5-20251001 | 37 061 | 37 061 | 0 |
| claude-opus-5 | 40 447 | 40 447 | 0 |
| claude-fable-5-1 | 40 995 | 40 995 | 0 |

Repetición de una celda (Opus 5.5 × prosa): 43 775 y 43 775, diferencia 0. Por tanto
**r = 0,5 %** (el suelo fijado en el criterio). El tokenizador es determinista: el ruido de esta
medición es cero en cuanto se aísla el suelo.

## 4. Densidad de entrada: caracteres por token

Cuerpo = total de la celda − control del mismo modelo. Entre paréntesis, los tokens del cuerpo.

| Modelo | prosa | python | log | json | diff | dispersión entre contenidos |
|---|---:|---:|---:|---:|---:|---:|
| claude-opus-5-5 | 2,23 (4 285) | 2,41 (4 125) | 1,92 (4 456) | 1,88 (5 170) | 2,22 (4 450) | 28,7 % |
| claude-sonnet-5-5 | 2,23 (4 285) | 2,41 (4 125) | 1,92 (4 456) | 1,88 (5 170) | 2,22 (4 450) | 28,7 % |
| claude-opus-5 | 2,23 (4 285) | 2,41 (4 125) | 1,92 (4 456) | 1,88 (5 170) | 2,22 (4 450) | 28,7 % |
| claude-fable-5-1 | 2,23 (4 285) | 2,41 (4 125) | — | — | — | — |
| claude-haiku-4-5-20251001 | 3,01 (3 166) | 3,12 (3 190) | 2,41 (3 538) | 2,22 (4 377) | 2,90 (3 401) | 40,9 % |
| **dispersión entre modelos** | 35,3 % | 29,3 % | 25,9 % | 18,1 % | 30,9 % | |

- **Opus 5.5, Sonnet 5.5, Opus 5 y Fable 5.1 dan exactamente el mismo número de tokens** en cada
  contenido medido, token a token. Comparten tokenizador. **Haiku 4.5 usa otro**, de una generación
  anterior: entre un 15 % y un 26 % menos tokens para el mismo texto.
- Fable solo se midió con prosa y código, como pedía el encargo (es el modelo caro).
- `claude-opus-4-8` aparece en los transcripts (519 mensajes desde el 2026-09-06) y no se midió;
  `claude-sonnet-5` (104) tampoco. Los más usados son `claude-opus-5` (29 761) y `claude-opus-5-5`
  (18 594), los dos medidos.

### Comparación con `research.md` §6 y efecto del formato de `Read`

`research.md` midió 2,02 (prosa) y 2,15 (Python) leyendo con la tool `Read`, que antepone a cada
línea su número y un tabulador. Medí los mismos textos de prosa y Python con ese formato
(`{n:6d}\t{línea}`), contando los caracteres **del fichero original**, que es lo que el daemon
conoce cuando delega:

| Opus 5.5 | sin numerar | con formato `Read` | aumento de tokens |
|---|---:|---:|---:|
| prosa | 2,23 (4 285) | **2,00** (4 762) | +11 % |
| python | 2,41 (4 125) | **2,03** (4 906) | +19 % |

Con el formato `Read`, la prosa reproduce el 2,02 de `research.md`. Así que **el número que
conviene depende de por dónde habría entrado el texto**: lo que Claude habría leído con `Read` cuesta
~2,0 caracteres por token; lo que habría llegado como salida de Bash (logs, JSON, diffs) va sin
numerar y queda en 1,9–2,2.

## 5. Esfuerzo (Opus 5.5)

**Entrada.** El mismo prompt (diff + «responde ok») con `--effort low`, `--effort high` y sin flag
(el esfuerzo por defecto del usuario) dio **43 940** tokens las tres veces; la tarea de resumen dio
**43 938** con `low` y con `high` en las seis llamadas. Diferencia 0 = R_ctrl. **Confirmado: el
esfuerzo no cambia los tokens de entrada**, ni del texto ni del suelo (prompt de sistema y tools).

**Salida.** Tarea idéntica «resume este diff en una sola línea», 3 repeticiones por nivel,
intercaladas (low, high, low, high, low, high):

| Esfuerzo | `output_tokens` por repetición | Media | Rango |
|---|---|---:|---|
| low | 148, 123, 136 | 135,7 | 123–148 |
| high | 211, 279, 189 | 226,3 | 189–279 |

Los rangos no se solapan (189 > 148). **Confirmado: el esfuerzo sí cambia la salida**; `high`
gasta **1,67 veces** los tokens de salida de `low` en esta tarea. Las seis respuestas visibles
eran una sola línea de longitud parecida, así que la diferencia es casi toda razonamiento. Con
salidas tan cortas el efecto sobre el coste de la llamada es pequeño frente a la entrada; en tareas
largas no se puede extrapolar sin medirlas.

## 6. Veredicto según el criterio

| Regla | Resultado |
|---|---|
| 1. Resta válida | Sí, con `--strict-mcp-config` (R_ctrl = 0 en los cinco modelos). Sin aislar los MCP, no (703 tokens). |
| 2. Depende del modelo | Sí en los 5 contenidos (18–35 % > 3 %). Pero solo por Haiku 4.5: los cuatro modelos de la familia 5 son idénticos. |
| 3. Depende del contenido | Sí: 28,7 % en la familia 5 y 40,9 % en Haiku 4.5 (> 10 %). |
| 4. El esfuerzo no cambia la entrada | Confirmado (diferencia 0). |
| 5. El esfuerzo cambia la salida | Confirmado (×1,67, rangos sin solaparse). |
| 6. Recomendación | Dispersión > 25 % dentro de los modelos → **por modelo y contenido**. |

## 7. Recomendación para la spec

1. **La regla del criterio da «por modelo y contenido», y en la práctica se reduce a dos familias
   de tokenizador por tipo de contenido**, no a una fila por modelo:
   - Familia 5 (`claude-opus-5-5`, `claude-sonnet-5-5`, `claude-opus-5`, `claude-fable-5-1`):
     prosa 2,23 · Python 2,41 · log 1,92 · JSON 1,88 · diff 2,22 caracteres por token (texto sin
     numerar); prosa 2,00 y Python 2,03 con formato `Read`.
   - Haiku 4.5: prosa 3,01 · Python 3,12 · log 2,41 · JSON 2,22 · diff 2,90.
   - Un modelo no medido (p. ej. `claude-opus-4-8`) usa la familia 5 y se marca «estimado». Ojo
     con el sentido del error: menos caracteres por token significa más tokens ahorrados contados,
     así que aplicar la familia 5 a un modelo de tokenizador más eficiente **infla** el ahorro.
2. **Si la spec prefiere una sola constante**, el caso por defecto (Opus 5.5 en subagente) admite
   **2,15 caracteres por token con un margen de ±14 %** (de 1,85 a 2,45): cubre de 1,88 (JSON) a
   2,41 (Python sin numerar) y deja dentro el 2,00 del formato `Read`. El margen es la mitad de la dispersión entre
   contenidos (28,7 %), como fija la regla 6 para una global. Esa constante **no vale para Haiku 4.5**
   (2,2–3,1). Cualquiera de las dos opciones es mucho mejor que el 4 actual de `CHARS_PER_TOKEN`,
   que cuenta aproximadamente la mitad de los tokens reales.
3. **El tipo de contenido se puede deducir de la tool, sin clasificar el texto**: `local_lint_summary`
   recibe logs, `local_commit_msg` diffs, `local_explain_code` código, y `local_summarize` /
   `local_extract` con `path` se pueden distinguir por la extensión del fichero. Si la entrada vino
   por `path` (lo que Claude habría leído con `Read`), conviene la densidad con formato `Read`.
4. **El esfuerzo no entra en la conversión de caracteres a tokens de entrada.** Sí cambia la salida
   (×1,67 de `low` a `high` en una tarea corta); como lo que se ahorra al delegar es sobre todo
   entrada, puede ignorarse en la densidad y, como mucho, citarse como factor de la salida si la spec
   estima ahorro de salida.
5. **Para repetir la medición**: aislar el suelo con `--strict-mcp-config` y neutralizar el hook de
   prompt; si no, la resta mete ruido de cientos de tokens.

## 8. Coste, ventana horaria y telemetría

- **Ventana de las llamadas**: de **2026-10-06T14:28:30Z** a **2026-10-06T14:32:21Z** (45 llamadas
  `claude -p`, seguidas, ninguna en paralelo). Antes, hacia las 14:26Z, corrió `pytest` sobre 4
  ficheros de tests para generar el log (no lanza hooks de Claude).
- **Telemetría**: `LD_HOOK_TELEMETRY_LOG` está definida (`~/.claude/hooks/telemetry.jsonl`). En la
  ventana hay 47 eventos `UserPromptSubmit` (45 son estas llamadas, cada una con su propio
  `session_id` y `suggested=false`) y 85 `PreToolUse` que no son míos (estas llamadas no usaron
  tools). Para excluirlas de la medición de adopción: eventos `UserPromptSubmit` entre esas dos horas
  cuyo `session_id` no sea el de una sesión interactiva.
- **Coste**: la suma de `total_cost_usd` de las 45 llamadas es **7,36 USD** equivalentes a precio de
  API. Casi todo es el suelo: cada llamada con caché fría escribe ~40 000 tokens de prompt de sistema
  y tools en la caché, frente a ~4 500 del texto. `cuota-statusline.jsonl` solo registra la sesión
  interactiva padre, no las de `claude -p`:
  - antes, 2026-10-06T14:28:18Z: `five_hour` 33, `seven_day` 26, `cost_usd` 42,02;
  - después, 2026-10-06T14:32:46Z: `five_hour` 48, `seven_day` 27, `cost_usd` 48,75.

  La subida de 15 puntos en la ventana de 5 h incluye esta medición, la sesión padre y cualquier
  otro agente que corriera a la vez; no se puede atribuir entera a este experimento.
- Datos crudos: `resultados.jsonl` en el scratchpad de la sesión
  (`%USERPROFILE%\AppData\Local\Temp\claude\D--Projects-local-delegate\deec22db-aa02-4e22-b9cb-1cd13039de77\scratchpad\resultados.jsonl`),
  con `usage` y `modelUsage` de cada llamada; los textos fijados, en `…\scratchpad\textos\`.
- Llamadas a `local-delegate`: **1** (`local_summarize` con `path` sobre `research.md`, para situar
  el método del §6 sin cargar el fichero). Los números se leyeron literalmente de las salidas de
  `claude -p`, no de las tools locales.
