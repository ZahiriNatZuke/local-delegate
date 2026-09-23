# Implementation plan: Subagente que solo reenvía a las tools local_* (idea 1 de backlog §4.1)

Versión 3 (2026-09-22). La v1 y la v2 las bloqueó la revisión adversarial (`review.md`). La v3
sigue a la **enmienda de REQ-005 y REQ-007b** aprobada por el usuario: el brazo A deja de medirse
con corridas (inviable) y pasa a un modelo de coste con control. Cada corrección cita su hallazgo
(H1…H15 de la ronda 1, N1…N4 y notas de la ronda 2).

## Approach

Un recurso empaquetado (`resources/agents/local-delegate-lector.md`) que el instalador copia a
`~/.claude/agents/` con un marcador de propiedad, con las reglas que ya protegen los ficheros del
usuario. El agente no lleva `local_delegate` en `tools`, así que queda fuera de `agents.pending()`.

Nada de la etapa 2 se construye hasta que la calibración (T5) pase REQ-006; nada se ofrece por
defecto hasta que el experimento (T8) elija variante. Las variantes viven detrás de
`LD_HOOK_OFERTA` (por defecto `v0` = comportamiento actual).

### Banco de pruebas común (`scripts/_banco_claude.py`)

- **Directorio de trabajo neutro y fijo** en `%TEMP%` (sin memoria de proyecto) y `--model opus`
  fijo. El `CLAUDE.md` global del usuario forma parte del entorno medido y se declara (H7).
- **Entorno de hooks por `--settings <fichero>`** (`LD_HOOK_OFERTA`, `LD_HOOK_TELEMETRY_LOG` de
  la tanda, `LD_HOOK_ENABLED`, `LD_HOOK_READ_BLOQUEAR`, y `LD_HOOK_READ_INTERRUPTOR` apuntando a
  una ruta temporal inexistente para que el fichero global de apagado no interfiera). Nunca se
  toca el fichero global (H1, N3).
- **Control de precedencia al inicio de cada tanda** (ronda 2): una corrida con
  `LD_HOOK_ENABLED=0` sobre prosa > 8 KB. Si aparece un deny, `--settings` no manda sobre el
  `env` del usuario y **la tanda aborta** (no reintenta).
- **Rutas absolutas**; antes de la primera corrida, `local_status` y una llamada de prueba con
  `path` para detectar `ALLOWED_DIRS` (H8).
- **Orden intercalado con semilla fija** (H7).
- **Reintentos:** una corrida inválida por infraestructura (error de API, MCP caído) se repite
  como mucho 2 veces; a la tercera, la tanda aborta (N1, N3).
- **Ventanas horarias** de cada tanda, con 10 minutos de margen al final (los modelos quedan
  calientes), en `verification.md` y en `benchmarks/ventanas-excluidas.json` (H5, nota 5).
- Cada script **anuncia corridas y coste estimado y pide confirmación**.

### Ficheros de prueba (H14, H15)

Documentos **del propio repo** (README, CHANGELOG, páginas de `docs/`, un log de CI, un diff)
copiados al banco con **un hecho plantado** (frase única con un código aleatorio por corrida).
Para la imagen, una captura existente del repo con una pregunta de respuesta conocida. Sin datos
del vault. Se versiona el generador y la lista de fuentes, no copias.

## Ordered tasks

### Etapa 1

1. **El agente y su render**
   - Files or modules: `resources/agents/local-delegate-lector.md` (nuevo); `agents.py`: función
     que recibe la ruta del recurso como parámetro (sin importar `install`: ciclo, H10) y detección
     del marcador.
   - Requirements covered: REQ-001, REQ-001b, REQ-004, REQ-007c.
   - Verification (`tests/test_agents.py`): exactamente las 7 tools, `model: haiku`,
     `omitClaudeMd: true`, `maxTurns: 4`; sin `local_delegate` → `is_delegator` falso; prompt con
     literalidad, «nunca afirmes lo que no hiciste», ruta absoluta obligatoria y «local-delegate
     no está disponible». **Presupuesto (H9):** constantes medidas en research —base 2 274 tokens,
     421 por esquema (4 210 / 10)— y suma de los esquemas reales de las 7 tools con
     `asyncio.run(server.mcp.list_tools())`. Control positivo: con las 11 supera 6 000.
   - Rollback or recovery: borrar el recurso.

2. **Instalación, retirada, reparación y empaquetado** (H11, H12)
   - Files or modules: `install.py` (`plan_install` junto a `_agents_action`; `plan_uninstall`
     retira el agente **siempre que lleve el marcador**); `checks.py` (check nuevo «agente
     lector»: `OK` si no se pidió, `WARN` si está desactualizado, para que `update` lo reponga);
     `update.py`; `cli.py`; conteos del doctor en `checks.py`, `_NUMERO` de `tests/test_checks.py`
     (añadir «veintidós» y corregir la frase «los otros {n}», que con 21 diría «veintiún»), tabla
     de la wiki.
   - Requirements covered: REQ-002, REQ-003.
   - Verification (`tests/test_agents.py`, `tests/test_checks.py`, `tests/test_update.py`):
     instalación limpia; segunda corrida sin cambios; fichero ajeno intacto byte a byte en
     install/uninstall/update; `--dry-run` literal; `.bak`; CRLF; `update` repone uno
     desactualizado. **Wheel:** `uv build` y el `.md` dentro del `.whl`.
   - Rollback or recovery: `local-delegate uninstall`.

3. **Verificación instalada del agente**
   - Requirements covered: REQ-001, REQ-001b, REQ-007c.
   - Verification: instalar desde el árbol con el daemon parado (memoria
     `daemon-y-uv-tool-trampas`); con el banco, `@"local-delegate-lector (agent)"` resume un
     fichero → transcript con solo las 7 tools, una llamada con `path` absoluto, respuesta igual a
     la salida de la tool, primer turno ≤ 6 000 tokens. Sin MCP (`--strict-mcp-config` con config
     vacía) → «no está disponible». Control positivo de `@"… (agent)"` y `maxTurns` en `-p` (H13).

4. **N: turnos tras una lectura** (H2, N4)
   - Files or modules: `scripts/medir_turnos_tras_lectura.py` (nuevo).
   - Requirements covered: REQ-005 (insumo).
   - Verification: transcripts del usuario de los últimos 60 días, **solo hilo principal y
     `entrypoint == "cli"`** (fuera `sdk-cli` —las sesiones `-p`, incluidas las del banco— y
     `claude-desktop`), fuera las de cwd en `%TEMP%`. Cuenta solo `Read` de prosa cuyo
     `tool_result` no es error ni deny y cuyo **contenido devuelto** pesa ≥ 8 KB. **Turno** = cada
     `message.id` distinto de asistente posterior (cada uno relee la caché). La cuenta **se corta**
     en un `compact_boundary` o al final de la sesión. **N = mediana**, con su distribución y el
     tamaño de muestra, en `verification.md` **antes** de T5. Sin rutas (REQ-012). Test con
     transcripts sintéticos que incluyen una sesión `sdk-cli`, un deny y una compactación.

5. **Calibración y compuerta REQ-006** (REQ-005 enmendado)
   - Files or modules: `scripts/calibrar_lector.py`; salida
     `benchmarks/lector-calibracion/curva-<fecha>.json` (sin rutas ni contenidos).
   - Requirements covered: REQ-005, REQ-006, REQ-012.
   - Verification:
     - **Lectura del transcript (ronda 3, B1):** un mismo `message.id` aparece en varias líneas
       con el `usage` repetido: **toda suma deduplica por `message.id`**. El **contexto** de un
       turno k es `input + cache_read + cache_creation`. Los tokens que entraron entre k−1 y k son
       `contexto(k) − contexto(k−1) − output(k−1)`, que vale igual haya acierto o fallo de caché.
     - **Precios (ronda 3, B2):** tabla por modelo **y por duración de caché** (escritura 5 min,
       escritura 1 h, lectura, entrada, salida), con fuente declarada. Las cantidades de escritura
       salen de `usage.cache_creation.ephemeral_5m_input_tokens` y `ephemeral_1h_input_tokens` del
       transcript (el hilo principal escribe a 1 h y el subagente a 5 min). **Validación:** el
       coste recalculado por modelo desde el transcript tiene que coincidir con el `costUSD` de
       `modelUsage` de ese modelo dentro de ±2 %, o la calibración no vale. Para Haiku, la
       validación solo se aplica si los tokens totales de Haiku en `modelUsage` coinciden con los
       del transcript de `subagents/`; si no coinciden (hay otras llamadas a Haiku), se declara y
       se valida solo Opus (ronda 3, N6).
     - **Control del modelo de A** (hooks apagados por `--settings`; guarda: `Read` completo sin
       deny, si no aborta), en dos corridas con ficheros de prosa que `Read` devuelve enteros:
       - **Ajuste** con ~16 KB: tokens del fichero = tokens que entraron en el turno que recibe el
         `tool_result` (la llamada a la tool ya va dentro de `output(k−1)`) → **proporción
         caracteres→tokens**.
       - **Predicción** con ~8 KB, independiente del ajuste: la fórmula predice los tokens del
         fichero. Después, **K = 3 turnos de seguimiento reales** en la misma sesión, con
         `claude -p --resume <session_id>` tres veces (una pregunta corta cada vez). Se comprueba
         que (a) los tokens predichos coinciden con los medidos dentro de ±10 %, y (b) en cada
         turno de seguimiento j, `cache_read(j) ≥ contexto(k)` —el fichero se relee de caché— y
         `cache_creation(j)` es menor que el 10 % de los tokens del fichero. Si falla, la
         calibración no vale. Los tres seguimientos se lanzan seguidos, con el mismo cwd,
         `--settings` y modelo; el informe distingue «caché perdida al reanudar» (el prefijo del
         sistema cambió) de un error de la fórmula.
     - Si Haiku no se pudo validar, el veredicto de REQ-006 lo dice junto al coste de B.
       - Los ficheros de B son **del mismo tipo** que los del control (prosa en markdown), porque
         la densidad de tokens cambia hasta el doble entre tipos.
     - **Coste A(tamaño)** = tokens(tamaño) × (escritura de caché a 1 h de Opus + N × lectura de
       caché de Opus). La respuesta final la pagan igual A y B y no entra. El informe declara que
       N ignora la caducidad de la caché (una pausa larga reescribe y encarece A): es conservador
       en contra de B.
     - **B medido**: 4 tamaños (~8, ~24, ~64, ≥100 KB; el último cruza el umbral de troceado),
       **R = 3**, hooks apagados también en B (simetría). **Coste B** = coste del subagente
       **calculado desde su transcript de `subagents/`** con la tabla validada (no el `costUSD` de
       Haiku, que puede incluir otras llamadas) + salida de Opus del turno que invoca al agente +
       tokens del resultado del agente (tokens que entraron en el turno que recibe el
       `tool_result` del Agent, según la medida de arriba; incluye los metadatos que Claude Code
       añade, que son coste real) × (escritura a 1 h + N × lectura de caché de Opus).
       **Fallo** si el subagente no llamó a `local_*` con `path` o la respuesta no contiene el
       hecho plantado. Los fallos no entran en la mediana; se cuentan aparte.
     - **Punto de equilibrio**, reglas en este orden de precedencia:
       1. Si A − mediana(B) cambia de signo más de una vez entre los tamaños probados → **no
          concluyente** (y no se aplica ninguna otra regla).
       2. Si B no es más barato en ningún tamaño → **no hay equilibrio**.
       3. Si no, el equilibrio es el menor tamaño probado en el que A > mediana(B) en él y en
          todos los mayores. Un empate cuenta como «B no es más barato». Si B sale más caro en
          ≥100 KB por el troceado, ese punto basta para que no haya equilibrio.
       El informe da además el cruce interpolado, solo como dato.
     - **REQ-006 pasa** si hay equilibrio ≤ 64 KB, el control del modelo y la validación de
       precios pasan, y B tiene como mucho 1 fallo en 12. Decisión en `verification.md` y en el
       vault.
     - Tests unitarios con datos sintéticos: equilibrio, cruce doble, empate, «nunca más barato»
       y **mutante de N** (el resultado cambia).

**Si REQ-006 no pasa:** T11 documenta solo el agente (sin `LD_HOOK_OFERTA`) y deja la nota en el
vault; T6–T10 no se hacen (H14).

### Etapa 2 (solo si T5 pasa REQ-006)

6. **Variantes de oferta en los hooks** (H4, H14)
   - Files or modules: `hook_common.py` (`LD_HOOK_OFERTA`; `record()` añade `oferta`, la versión
     del hook y **el estado efectivo del bloqueo de lectura** a **todo** evento, también a los del
     hook de prompt, que se registran en cada prompt: así T8 comprueba el estado incluso en
     corridas sin ningún `Read`); `suggest_delegate_read.py`, `suggest_delegate_shell.py` (texto V1 solo por encima de
     `UMBRAL_LECTOR_KB`, constante que un test compara con el equilibrio del último
     `curva-*.json`); `suggest_delegate_prompt.py` (V2: solo con fichero, ruta o log; permiso del
     usuario; nunca «MANDATORY»); `SKILL.md` (mención fuera de la tabla).
   - Requirements covered: REQ-007.
   - Verification: tests por variante; `v0` idéntico byte a byte al actual; V2 calla sin fichero y
     en eventos del sistema; catálogo de la skill sin cambios. Control positivo instalado: una
     corrida por variante con su evento `oferta` en la telemetría de la tanda.
   - Rollback or recovery: `LD_HOOK_OFERTA=v0`.

7. **Prueba previa de V3** (H13)
   - Verification: `--plugin-dir` (existe en 2.1.280) carga una skill con `context: fork` y
     `agent: local-delegate-lector`; su invocación explícita llega al agente. Si no, V3 sale del
     experimento y se anota.

8. **Experimento de adopción y elección** (REQ-007b enmendado; H3, H4, N2, N3)
   - Files or modules: `scripts/experimento_adopcion.py`; `benchmarks/adopcion-lector/tareas.json`
     (8 tareas: 2 docs, 2 logs, 1 CHANGELOG, 1 diff, 1 salida de lint, 1 imagen); y
     `scripts/medir_adopcion.py` gana `--excluir INICIO,FIN` repetible (H5).
   - Requirements covered: REQ-007b.
   - Verification:
     - **Estado del bloqueo fijado** por `--settings` (`LD_HOOK_READ_BLOQUEAR=1`, interruptor
       aislado) y registrado por corrida; si una corrida muestra otro estado, la tanda aborta.
     - **Validez independiente del desenlace:** el evento del hook de prompt, que se registra en
       todo prompt, tiene que llevar la `oferta` esperada; si no, inválida (reintentos: banco).
     - **R = 3** por tarea y variante (8 × 4 × 3 = 96 corridas; el script estima y pide
       confirmación).
     - **Correcta** según REQ-007b enmendado: hecho plantado en la respuesta y, en el transcript
       principal, ni `Read` completo, ni `Read` con `offset`/`limit` del fichero, ni **volcado por
       Bash**: cualquier llamada a Bash o PowerShell cuyo comando contenga la ruta o el nombre del
       fichero y cuyo `tool_result` supere 2 KB.
     - **Supera a V0 en una tarea** = más corridas correctas que V0 en esa tarea (REQ-007b tal
       cual; ronda 3, B3). El ruido de una sola corrida lo acota el mínimo de 3 tareas de 8.
     - **Elección:** la variante que supera a V0 en más tareas, mínimo 3 de 8. **Desempate, en
       este orden:** menor coste medio **sobre todas sus corridas válidas**; después la más simple
       (V1 < V2 < V3).
     - Si gana una variante, cambia el valor por defecto de `LD_HOOK_OFERTA`; si es V3, tarea
       nueva para empaquetarla. **Si ninguna gana, se retira el código de las variantes.**

9. **Atribución en la telemetría** — `hook_common.py` añade `agent_type` si llega (REQ-008).
   Verification: captura real instalada de un hook dentro de un subagente; test con ese payload.

10. **Medición en uso real y criterio** (H6)
    - Files or modules: `scripts/medir_lector.py`.
    - Requirements covered: REQ-009, REQ-010, REQ-012.
    - Verification: tamaño por invocación = `chars_in` de la fila del log de uso que casa por tool
      y marca de tiempo con la llamada del subagente; por encima de 100 KB, A se **extrapola** con
      la fórmula (es lineal) y se marca como extrapolado; **sesión nueva** = primer evento
      posterior a la release; excluye `ventanas-excluidas.json`. Tests con transcripts
      sintéticos (correcta, sin `local_*`, respuesta distinta, formato desconocido → error claro).
      Criterio REQ-010 copiado literal en `verification.md` con la fecha de inicio.

### Cierre

11. **Documentación, release y memoria** — CHANGELOG, README, `docs/wiki/` (instalación, hooks,
    tabla del doctor), `docs/recipes/claude-code-integration.md`; nota en el vault con REQ-006 (y
    REQ-007b si hubo etapa 2); memoria: fecha del tramo nuevo de versión de hooks. Requirements
    covered: REQ-011. Verification: tests de la wiki verdes; las tres superficies nombran el
    agente y `--agents` (y `LD_HOOK_OFERTA` solo si hubo etapa 2).

## Test strategy

- Unit: render y marcador, presupuesto, install/uninstall/update/doctor, variantes, N (con sus
  filtros), equilibrio (con mutante de N), parsers de transcripts.
- Integration: `install --agents` sobre HOME temporal; hooks como subproceso con payloads reales.
- End-to-end: T3, T5, T7 y T8 con el banco; evidencia por transcript, nunca por el informe.
- Security: pre-commit; los scripts no guardan contenido ni rutas; el agente no escribe.
- Controles: cada test nuevo con control positivo o mutante que muestre qué assert dispara.

## Migration and compatibility

- Solo Claude Code. `--agents` sigue siendo opt-in; `uninstall` retira el agente propio siempre.
- Hooks con el comportamiento actual por defecto hasta T8. Tramo nuevo de versión al publicar T6.
- Cuota: T3 ~4 corridas, T5 13 (1 control + 12 de B) más los controles de precedencia, T7 2, T8
  96. Cada script pide confirmación.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
