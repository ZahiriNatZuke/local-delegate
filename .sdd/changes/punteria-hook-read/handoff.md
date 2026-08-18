# Handoff

## Qué se cerró

El hook `suggest_delegate_read` avisaba en 572 de 852 lecturas y sólo 29 apuntaban a algo
delegable. Ahora se calla ante código y ante lecturas acotadas, y los umbrales suben de 8/32 KB a
32/100 KB. La telemetría registra `ext` y el motivo del descarte.

Mergeado en **PR #146** (`9453893`), con los 13 checks en verde —CodeQL incluido, que es el que no
sale en `gh run list`.

## Decisiones que sobreviven a este cambio

- **La conversión cero no era un problema de redacción.** Un control con `claude -p` sobre un
  archivo de 114 KB mostró que el modelo delega solo cuando la tarea es una transformación global,
  con hook y sin él. Lo que fallaba era la puntería. Antes de reescribir un aviso que se ignora,
  mide si el aviso hacía falta.
- **`markitdown` se obedece siempre con una línea de descripción y sin skill.** No es la prosa: es
  que si le das un PDF, `Read` no sirve. `delegacion-local`, mucho mejor escrita, se invocó 0 veces
  en 49 sesiones porque compite contra `Read`, que siempre funciona. La obediencia viene de que la
  alternativa no exista.
- **Se descartó el hook que bloquea** (`permissionDecision: deny`). El prototipo funciona y está
  medido, pero el control negativo dice que el modelo ya delega solo en esos casos.
- **Excluir todo el código deja sin aviso a `local_explain_code`.** Aceptado a conciencia: 562
  lecturas de código en 14 días contra 8 llamadas históricas a esa tool. Si hace falta recuperarlo,
  el sitio es `suggest_delegate_prompt`, que ve la intención y no el tamaño en disco.

## Qué queda abierto

- **Las tools del MCP llegan diferidas en 43 de 49 sesiones.** Es la causa con más peso real de la
  no-adopción: 601 tools compitiendo, 208 de ellas sin un solo uso en 14 días (MCP_DOCKER 50,
  Postman 41, Figma 33, Canva 32, Cloudflare 23, Drive 11). No se arregla en este paquete: la
  mayoría son conectores de la cuenta de claude.ai y se desactivan en su panel de conectores, no en
  disco.
- **Esta máquina corre una 0.24.0 instalada desde el repo**, con el hook nuevo dentro. La versión
  dice 0.24.0 y el código es el de `main`. Se normaliza en la próxima release.
- El panel no muestra todavía la puntería, aunque el dato (`ext`, `motivo`) ya se registra.

## Estado del entorno tras el cierre

`local-delegate doctor`: todo a punto. Daemon pid 20152, backend arriba, credencial correcta, hook
instalado idéntico al del repo y verificado en vivo (un `.py` grande no dispara; `CHANGELOG.md` de
116 KB sí).
