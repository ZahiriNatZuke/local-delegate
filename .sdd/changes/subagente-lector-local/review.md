# Review: Subagente que solo reenvía a las tools local_*

## Revisión adversarial del plan v1 — 2026-09-22 — BLOQUEAR

Revisor independiente (`personal-sdd-plan-reviewer`). Seis bloqueantes:

- H1 El brazo A de la calibración choca con el bloqueo de lectura encendido en la PC.
- H2 REQ-006 no computable: N de turnos proyectados libre, sin métrica de coste, sin método de
  cruce ni repeticiones.
- H3 REQ-007b mide otra cosa que la regla: «delegación correcta» y «supera» sin definir; V0 sale con
  cero por construcción.
- H4 Nada garantiza que cada corrida corrió con su variante.
- H5 Las corridas contaminan P-4, la medición de adopción y la futura REQ-010.
- H6 REQ-010 consume un artefacto (curva de A, tamaño por invocación) que ninguna tarea produce.

No bloqueantes: H7 cwd/modelo/orden sin fijar; H8 rutas relativas y `ALLOWED_DIRS`; H9 parámetro
libre en el presupuesto; H10 ciclo de import `agents`↔`install`; H11 empaquetado sin verificar;
H12 uninstall sin `--agents`, `update` y `doctor`; H13 V3 sin verificar; H14 ramas negativas
incompletas; H15 T4 sin comprobar respuesta correcta.

Plan v2 los atiende uno a uno (citados en plan.md).

## Revisión adversarial del plan v2 — 2026-09-22 — BLOQUEAR

H6 cerrado; H1–H5 abiertos por: N1 el brazo A no puede leer entero ≥100 KB (`Read` corta ~25 k
tokens) y la guarda repetiría sin fin; N2 la regla de T8 no coincidía con REQ-007b y dejaba pasar
franjas; N3 estado del bloqueo sin fijar en T8 y validez dependiente del desenlace; N4 muestra de N
contaminada (sesiones `-p`, reads denegados, compactaciones, «turno» sin definir). Notas: conteo
del doctor (`_NUMERO` sin «veintidós»), asimetría de hooks A/B, tipos de tarea, R=2 discrimina
poco, P-4 contaminada tras las ventanas.

**Diagnóstico:** dos rondas bloqueando en el mismo sitio (el brazo A medido) → el método, no el
detalle. El usuario aprobó enmendar REQ-005 (A por modelo de coste con control) y REQ-007b
(correcta/supera). Plan v3 escrito sobre la spec enmendada.

## Revisión adversarial del plan v3 — 2026-09-22 — BLOQUEAR (correcciones puntuales)

Método validado; N1, N3, N4, H1, H2 (diseño), H4, H5 y las notas de la ronda 2 cerrados. Tres
bloqueantes de redacción: B1 control del modelo de A circular (ajustaba y comprobaba con la misma
corrida) y medida de tokens mal definida (delta de `cache_creation`; sumas sin deduplicar por
`message.id`); B2 la tabla de precios única fallaría: el hilo principal escribe caché a 1 h y el
subagente a 5 min, y `modelUsage` no lo separa; B3 T8 exigía un margen de 2 que REQ-007b no dice.

Corregido en plan v3.1: delta de contexto total deduplicado; control con ajuste (16 KB) y
predicción independiente (8 KB, K=3 turnos, ±10 %); tabla por modelo y duración desde
`usage.cache_creation.ephemeral_*`; escritura de A a 1 h; coste del subagente desde `subagents/`;
precedencia explícita de «no concluyente»; T8 alineado con REQ-007b (margen 1); estado del bloqueo
en `record()`; volcado por Bash definido (ruta o nombre en el comando y resultado > 2 KB).

## Verificación de correcciones — 2026-09-22 — APROBAR

v3.1: B1, B2, B3 cerrados; el control nuevo introdujo N5 (un `claude -p` no produce turnos de
seguimiento; la condición sobre `cache_read` fallaba siempre) y N6 (±2 % de Haiku contra
`modelUsage` que puede incluir otras llamadas). v3.2: seguimientos reales con `--resume`, condición
(b) reescrita, validación de Haiku condicionada, doble resta eliminada. Veredicto: **APROBAR**, sin
bloqueantes; dos notas incorporadas (seguimientos seguidos con el mismo entorno y distinguir caché
perdida; declarar precios de Haiku sin validar junto a REQ-006).

## Plan v4 (spec v2, sin subagente) — 2026-09-22

- **Ronda 5 (v4) — BLOQUEAR:** B1 la receta habría dicho `select:local_summarize` (el nombre real
  lleva `mcp__local-delegate__`) y el test propuesto no lo cazaba; B2 el hook de Shell guarda la
  ruta relativa, así que su huella no cruza con la del daemon (defecto que ya afecta a V0); B3 sin
  guarda si las tools no son diferidas; B4 eventos del hook de prompt sin `session_id`; B5 línea
  base con eventos sin `oferta`, fechas relativas y sesiones `claude -p` del día; B6 faltaba el
  cruce por ruta y el filtro de sesiones nuevas; B7 el criterio de retirada de V2 no podía
  dispararse.
- **Ronda 6 (v4.1) — BLOQUEAR:** B1–B7 cerrados; N1 filtro de versión dejaba vacía la base; N2 el
  log de uso no guarda sesión; N3 la huella de Shell arreglada inflaría la variante frente a la
  base. Corregidos: `--version` por ventana, cruce por huella + tiempo + `client`, tasa decisiva
  solo sobre `Read`.
- **Verificación — BLOQUEAR condicionado:** la telemetría de hooks tampoco guarda `client`;
  corregido a «solo usos cuyo `client` es el de Claude Code» y eventos sintéticos con el esquema
  real. El revisor: «Con eso, apruebo». Aplicado literal.
