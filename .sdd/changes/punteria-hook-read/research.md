# Research: la puntería del hook de lectura

## Pregunta

El hook `suggest_delegate_read` lleva desde el 2026-07-29 sugiriendo delegar lecturas grandes.
¿Cuántas de esas sugerencias apuntan a algo que de verdad se puede delegar?

## Método

Dos fuentes independientes, cruzadas por fecha:

1. `~/.claude/hooks/telemetry.jsonl` — 10 153 eventos del hook (29-jul → 18-ago).
2. Los transcripts de Claude Code (`~/.claude/projects/*/*.jsonl`), 49 sesiones desde el 5-ago,
   que sí guardan el `file_path` de cada `Read` (la telemetría no lo guarda, a propósito).
3. `usage-*.jsonl` del daemon — las delegaciones que llegaron a ocurrir.

## Hallazgos

### La conversión es cero, y el registro no está roto

- Del 5-ago al 18-ago: **1 409 sugerencias del hook, 0 delegaciones**.
- Control positivo: un `local_summarize` lanzado el 18-ago apareció en `usage-202608.jsonl` al
  instante. Los ceros son reales, no un fallo de instrumentación.
- El aviso sí llega al modelo: el texto del hook aparece **813 veces** literalmente en los
  transcripts. No es que no se vea; es que se ignora.

### La causa no es la redacción del aviso

Control negativo medido con `claude -p` sobre un archivo de 114 KB:

| | tools que usó | delegó |
|---|---|---|
| Con un hook que bloquea (`permissionDecision: deny`) | Read (denegado) → `local_summarize(path)` | sí |
| **Sin ningún hook** | Bash (miró el tamaño) → ToolSearch → `local_summarize(path)` | **sí** |

El modelo ya delega solo cuando la tarea es una transformación global. El caso de prueba no
discriminaba. Lo que el hook tenía que explicar, el modelo ya lo sabía.

### La causa es que el hook apunta casi siempre a lo que no se debe delegar

De las 1 579 lecturas de las 49 sesiones:

| | |
|---|---|
| Con `offset`/`limit` — lectura intencionada de una franja | 542 |
| Código (`.ts`, `.py`, `.scss`…) — hace falta literal para editar | 562 |
| `.output` (salidas de comandos) | 661, **todas menores de 8 KB** |
| **Texto no-código, entero, >8 KB — lo realmente delegable** | **34** |

El hook dispara desde 8 KB y no mira la extensión ni si la lectura es acotada. Sobre las 852
lecturas cuyo archivo aún existe en disco, dispararía **572 veces** para cubrir 52 casos.

Y los dos archivos que se llevan dos tercios del peso delegable —`ESTADO.md` (103 KB × 4) y
`MEMORY.md` (27 KB × 13)— son los que el modelo lee **para usarlos como contexto de trabajo**.
Resumirlos con un modelo local lo dejaría sin el detalle que fue a buscar. Son los peores
candidatos posibles.

### Por qué importa el ruido

`markitdown` expone **una sola línea** de descripción, sin skill ni catálogo, y se obedece
siempre: si le das un PDF, `Read` no sirve y no hay alternativa. La skill `delegacion-local`,
mucho mejor escrita, se invocó **0 veces en 49 sesiones**. La obediencia no viene de la prosa:
viene de que el consejo nunca se equivoque. Un aviso que acierta el 2 % de las veces enseña a
ignorarlo, y se lo lleva por delante en los casos en que sí tenía razón.

### La telemetría no podía ver este defecto

`record()` guarda `category`, `band` y `size_kb`, pero **no la extensión**. Por eso el hook llevaba
tres semanas apuntando a código sin que el panel pudiera mostrarlo. El path no se guarda a
propósito (privacidad) y así debe seguir; la extensión sola no identifica ningún archivo.

## Simulación de las reglas candidatas

Sobre las 852 lecturas reales con tamaño conocido:

| regla | sugerencias / 14 días |
|---|---|
| actual: >8 KB, sin exclusiones | 572 |
| + excluir código | 138 |
| + excluir código y lecturas acotadas | 52 |
| + umbral 16 KB | 36 |
| **+ umbral 32 KB (propuesta)** | **29** |
| + umbral 64 KB | 16 |

## Límites de esta investigación

- Los transcripts sólo cubren esta PC. Las delegaciones hechas desde la Mac tienen su propio
  daemon y su propio `usage`, y no entran en el cruce.
- 727 de las 1 579 lecturas apuntan a archivos que ya no existen en disco; la simulación corre
  sobre las 852 restantes y asume que la proporción se mantiene.
- El peso en KB es una cota superior de lo que entró al contexto: `Read` trunca a 2 000 líneas.
