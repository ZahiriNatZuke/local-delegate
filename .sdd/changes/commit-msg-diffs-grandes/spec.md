# Specification: local_commit_msg deja de truncar diffs grandes

## Summary

`local_commit_msg` redacta el mensaje a partir del diff **entero**, no de sus primeros 20 000
caracteres. Un diff de decenas de archivos produce un mensaje que nombra el cambio real —no el
primero que aparezca por orden alfabético de rutas— y quien lo pide se entera de cuántos archivos
se tuvieron en cuenta.

## Contexto medido

Reportado desde la Mac contra un diff de 71k chars: la tool devolvió
`docs: update angular agents documentation` para un refactor de `paycorr-core`. Reproducido aquí
con `git diff 6a7959e HEAD` de este repo (164 585 chars, 44 archivos):

| Medida | Resultado |
| --- | --- |
| Entrada real | 164 585 chars, 44 archivos |
| Procesado | 20 027 chars — **7 archivos, todos de `.sdd/`** |
| Mensaje devuelto | `chore: update GitHub Actions pages artifact version` |
| Control positivo: solo el diffstat (2 987 chars, sin truncar) | `feat: agregar cambios y pruebas para aislar entorno en tests y codeql alertas abiertas` |

El control positivo dice lo esencial: **el modelo no es el problema, lo es lo que le llega**. Con
2 987 chars que describen el alcance completo el mensaje ya nombra el cambio; con 20 027 chars del
principio del diff, no.

Segunda medida, sobre el chunking existente (`_chunk_text` con presupuesto de 16 000):
**1 de 11 trozos** empieza en frontera de archivo (`diff --git`). Los otros 10 arrancan a mitad de
un hunk, con líneas `+` huérfanas cuya cabecera de archivo quedó en el trozo anterior.

Origen del defecto: `local_summarize` (`server.py:1150`) y `local_lint_summary` (`server.py:1422`)
ya leen entero y bajan a `_chat_map_reduce`; `local_commit_msg` (`server.py:1474`) se quedó con el
truncado duro contra `config.max_chars_for(config.MODEL_CODE)`.

## Requirements

- **REQ-001:** `local_commit_msg` procesa el diff completo. Para una entrada mayor que el tope del
  modelo no descarta contenido en silencio ni devuelve un mensaje derivado solo del principio.
- **REQ-002:** Cuando el diff no cabe en una llamada, los trozos se cortan en fronteras de archivo:
  todo trozo empieza en un `diff --git` (o en el marcador equivalente de un diff sin `--git`), y
  ningún archivo aparece repartido entre dos trozos salvo que él solo exceda el presupuesto.
- **REQ-003:** El paso final que redacta el mensaje recibe siempre el inventario de archivos
  afectados con su recuento de líneas, derivado del diff completo y calculado sin modelo.
- **REQ-004:** El mensaje resultante conserva el formato de hoy: primera línea `tipo(scope): resumen`
  en imperativo y ≤72 caracteres para `style="conventional"`, o imperativa ≤72 para `style="plain"`,
  con cuerpo opcional en viñetas `- `.
- **REQ-005:** Un diff que cabe en una llamada sigue el camino de hoy: una sola llamada al backend,
  sin cabecera de inventario ni aviso de troceado.
- **REQ-006:** La contabilidad no cambia de forma: N llamadas al backend producen **un** evento de
  log con `chunks: N`, como en `_chat_chunked` y `_chat_map_reduce`.
- **REQ-007:** Quien llama la tool puede saber sobre cuántos archivos y cuánta entrada se redactó el
  mensaje.

## Acceptance scenarios

### Scenario: el diff grande nombra el cambio real

- **Given** el diff de 164 585 chars y 44 archivos usado como referencia
- **When** se pide el mensaje con `local_commit_msg(path=...)`
- **Then** el mensaje refleja el contenido sustantivo del cambio, y **no** el primer archivo por
  orden alfabético, y no aparece el aviso de entrada truncada

### Scenario: los trozos respetan las fronteras de archivo

- **Given** el mismo diff y el presupuesto de troceado del modelo de código
- **When** se parte para el map
- **Then** todos los trozos empiezan en `diff --git` y la invariante `"".join(trozos) == diff` se
  mantiene

### Scenario: el diff pequeño no cambia de comportamiento

- **Given** un diff de un archivo que cabe holgadamente en el tope del modelo
- **When** se pide el mensaje
- **Then** hay exactamente una llamada al backend y la salida no lleva ni cabecera de inventario ni
  nota de troceado

### Scenario: un solo archivo más grande que el presupuesto

- **Given** un diff cuyo único archivo excede por sí solo el presupuesto de trozo
- **When** se parte
- **Then** se subdivide por límites naturales sin perder contenido, y el resultado sigue siendo un
  único mensaje de commit

## Edge cases and failure behavior

- **Entrada que no es un diff:** si no hay ningún `diff --git`, el troceado cae a los límites
  naturales de hoy (párrafos, líneas) y el inventario de archivos sale vacío; la tool no falla.
- **Fallo del backend a mitad del map:** se comporta como `_chat_map_reduce` hoy — se devuelve el
  error del backend, no un mensaje redactado a medias que parezca completo.
- **Binarios y archivos sin cuerpo de diff:** `diff --git` con `Binary files differ` o solo cambio
  de modo entra en el inventario aunque no aporte líneas.
- **Diff vacío:** entrada sin ningún archivo — la tool devuelve un error explícito en vez de pedirle
  al modelo que invente un mensaje.

## Non-functional requirements

- **Coste:** un diff grande pasa de 1 llamada a N+1. Es el precio de leerlo entero y es el mismo
  que ya pagan `local_summarize` y `local_lint_summary`; el inventario de REQ-003 se calcula sin
  modelo para no añadir una llamada más.
- **Privacidad:** el diff se sigue leyendo server-side; nada del contenido entra al contexto de
  Claude salvo el mensaje final.
- **Compatibilidad:** la firma pública de la tool (`diff`, `path`, `style`) no cambia.

## Non-goals

- Filtrar el ruido del diff —lockfiles, generados, líneas de contexto sin cambiar—. Es una mejora
  aparte, evaluable con este cambio ya medido.
- Cambiar el modelo del rol `code` ni sus topes de `max_chars`.
- Tocar el resto de tools: `local_summarize` y `local_lint_summary` ya leen entero.

## Traceability

| Requisito | Trabajo | Evidencia |
| --- | --- | --- |
| REQ-001 | Tarea 3 (map-reduce) + tarea 6 (reintento por desborde) | ✅ `verification.md`: 44 archivos y 164 585 chars procesados contra el backend real |
| REQ-002 | Tarea 1: `_split_by_diff_files` en `_SPLITTERS` | ✅ 12/13 trozos en frontera; el 13.º es `uv.lock`, previsto por el escenario 4 |
| REQ-003 | Tarea 2: `_diff_inventory` + `_format_inventory` | ✅ 0 discrepancias en 44 archivos contra `git diff --numstat` |
| REQ-004 | Tarea 3 (reduce parametrizado) + tarea 7 (prompts del map) | ✅ con matices — ver «Deviations» |
| REQ-005 | Tarea 3: camino corto intacto | ✅ 1 sola llamada, sin nota de alcance |
| REQ-006 | Tarea 3: reutiliza la contabilidad de `_chat_map_reduce` | ✅ un evento con `chunks: N` |
| REQ-007 | Tarea 4: nota de alcance en la salida | ✅ `(alcance: 44 archivos, 164,585 chars leídos enteros)` |
