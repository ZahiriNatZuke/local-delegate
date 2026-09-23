# Verification: Subagente que solo reenvía a las tools local_* (idea 1 de backlog §4.1)

## Environment

- Revision:
- Relevant runtime and tool versions:

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | | | |

## Quality checks

- [ ] Project-native tests pass.
- [ ] Lint, formatting, type checking, and build checks pass where applicable.
- [ ] Secret scanning passes.
- [ ] No unrelated changes are present.

## Deviations and residual risk

- Record skipped checks, known limitations, and why the evidence is still sufficient or not.


## T1 y T2 — 2026-09-22

- T1: recurso `resources/agents/local-delegate-lector.md`, `agents.own_agent_text/is_own_agent`,
  tests en `tests/test_agents.py` (tools exactas, `omitClaudeMd`, `maxTurns`, reglas del prompt,
  fuera de `pending()`, presupuesto con constantes medidas: 5 490 estimado con 7 tools, 6 794 con
  11 → control positivo). Mutantes: sin `omitClaudeMd` → falla; con `local_delegate` en tools →
  fallan tres tests.
- T2: `install.own_agent_state/own_agent_paths`, acciones de install/uninstall, check
  `scaffold.own_agent`, reparación en `update` con componente interno `agente`, ayuda de
  `--agents`, conteos del doctor (22) en `checks.py`, `_NUMERO`/`_NUMERO_SUELTO`, wiki. Tests:
  crear + idempotencia, sin flag no instala, fichero ajeno intacto byte a byte (install y
  uninstall), actualización con `.bak` y CRLF, uninstall con `mcp` lo retira, con `skill` no,
  doctor en sus cuatro estados, wheel lo contiene, `update` repone sin tocar agentes del usuario.
  Mutantes: `update` con componente `agents` → falla el test de no tocar lo del usuario;
  uninstall sin mirar el marcador → falla el test del fichero ajeno.
- Suite: 1363 passed, 2 skipped; ruff limpio.

## T3 — verificación instalada — 2026-09-22 — HALLAZGO QUE BLOQUEA REQ-001(b)

Instalado con `install --no-hooks --no-skill --no-memory --no-mcp --agents`. Banco en
`%TEMP%\banco-lector`, `informe.md` = README (17 548 caracteres).

**Cumple:** tools exactas (las 7 + `SubagentHandback`, leídas del `prompt_snapshot.tools`); sin
adjunto de instrucciones; primer turno 5 336 y 5 365 tokens (≤ 6 000; el test estimaba 5 490);
una sola llamada `local_summarize` con ruta absoluta.

**No cumple — salida literal:**

| Corrida | Salida tool | Informe | Parecido |
| --- | --- | --- | --- |
| Haiku, «5 viñetas» | 1 632 | 893 | 0,24 |
| Haiku, regla reforzada, «5 viñetas» | 982 | 801 | 0,41 |
| Haiku, «resume» sin formato | 997 | 1 909 | 0,41 |
| Sonnet (agente temporal), «resume» | 1 002 | 1 407 | 0,40 |
| Haiku + hook PreToolUse `updatedInput` en `SubagentHandback` | 2 509 | 2 226 | 0,17 |
| Haiku + hook PreToolUse `deny` si no es literal | 1 810 | 1 617 | 0,26 |

Causas: Opus añade instrucciones de formato al prompt del agente aunque el usuario no las pida, y
el agente obedece al que llama por encima de su prompt de sistema. En la corrida de 997 → 1 909 el
agente devolvió casi el doble sin acceso al fichero: **elaboración inventada**. Los hooks
`PreToolUse` sí se disparan en `SubagentHandback` (payload con `agent_id` y `agent_type`, útil para
REQ-008), pero Claude Code 2.1.280 ignora tanto `updatedInput` como `deny` en esa tool: el hook
emitió la decisión (registrado) y el informe se entregó igual, sin reintento.

Dos corridas del spike no valen (hook con error de sintaxis por el heredoc que colapsa `\n`).

Decisión pendiente del usuario: (1) aceptar reescritura; (2) spike de `SubagentStop` con `block`;
(3) replantear sin subagente, con la oferta apuntando a la tool directa.

### Opción 2 — hook `SubagentStop` con `decision: block` — 2026-09-22 — NO FUNCIONA

El hook se disparó (payload: `agent_id`, `agent_transcript_path`, `agent_type`,
`last_assistant_message`, `stop_hook_active`…), detectó la entrega no literal y emitió `block`
con el texto exacto. No hubo segunda entrega: el principal recibió la versión reescrita (parecido
0,31). Con esto, las cinco vías para forzar la literalidad fallan en Claude Code 2.1.280.

**Decisión (usuario, 2026-09-22): opción 3, replantear sin subagente.** El trabajo de T1–T2 queda
archivado en `archivo-agente-T1-T2.patch` (710 líneas) y el árbol vuelve a `main`; el agente
instalado en la PC se borró (y su `.bak`, ambos con nuestro marcador).

## Spec v2 / plan v4.1 — implementación

- **T0** (2026-09-22): PR #219 mezclado (squash `e46fe70`); rama `feat/oferta-tool-directa`.
  `scripts/sesiones_de_prueba.py` (3 tests, uno de no guardar rutas) registró 17 sesiones
  `sdk-cli` del día en `benchmarks/ventanas-excluidas.json` (18:50–22:18 UTC).
- **T1:** `oferta`/`oferta_pedida` en todo evento; el hook de prompt lleva `session_id`,
  `version` y `bloqueo`; `LD_HOOK_OFERTA` declarada en `config.py` (el guardián de aislamiento lo
  exigió). 4 tests; mutante sin `oferta` en `record()` → fallan los 4.
- **T2:** `TOOLS_RECETA` con nombres completos, `receta_v1` en condicional con la ruta por
  `json.dumps`; Read y Shell con rama por variante; Shell convierte la ruta a absoluta con `cwd`
  antes de huella/nota/receta (V0 conserva la ruta tal cual en su texto). `tests/test_oferta_directa.py`:
  V0 byte a byte contra el texto de `main`, receta, nombres contra `install.SERVER_NAME` + registro,
  ruta con espacios/apóstrofo (y comillas dobles sobre la función: Windows no las admite en
  carpetas), cruce hook → servidor con `cat` relativo en V0 y V1. Mutantes: sin prefijo → fallan
  2; sin ruta absoluta → fallan 5 (incluido V0: sin ella el hook ni siquiera mide el fichero si su
  cwd no es el de la sesión); un espacio de más en V0 → fallan 2.
- **T3:** V2 en el hook de prompt con `disparo` (`ruta`/`extension`/`log`), permiso con nombres
  completos, nunca «MANDATORY». Tests: cuatro menciones, sin mención = V0 (control), eventos del
  sistema en silencio, V0 no da permiso. Mutante «siempre dispara» → fallan 3.
- Suite: 1374 passed, 2 skipped; ruff limpio.

## T4 — control instalado — 2026-09-23

Reinstalado desde el árbol (daemon parado), `update --version 0.31.4` repuso los cuatro hooks
(idénticos al repo). **Tramo nuevo de versión de hooks desde 2026-09-23T01:14Z.** Banco en
`%TEMP%\banco-control-t4`; ventanas en `benchmarks/ventanas-excluidas.json`.

- **Precedencia:** con `LD_HOOK_ENABLED=0` por `--settings`, el `Read` completo de prosa grande no
  se bloqueó. `--settings` manda sobre el `env` del usuario.
- **Estado de las tools:** el `init` de `stream-json` lista las 234 tools pero no dice cuáles
  están diferidas; el transcript sí, en adjuntos `deferred_tools_delta` **incrementales**. El
  primer analizador se quedaba con el último delta y daba «no diferidas» con las tools ahí;
  corregido para acumular `addedNames` y restar `removedNames`, con test.
- **Primera tanda (pregunta por el dato plantado):** en V0, V1 y V2 el modelo respondió bien con
  un `Grep` del dato, sin leer ni delegar ni disparar hooks. La tarea no exigía leer (REQ-102):
  se cambió a preguntas de comprensión («Resúmelo en 5 puntos e incluye todas las cifras de
  configuración»), con test de que la pregunta no nombra el dato.
- **Segunda tanda (comprensión):** las tres corridas válidas (evento de prompt con su oferta;
  V2 con `disparo: ruta`), las tres encontraron la cifra, y **las tres delegaron
  espontáneamente** (`ToolSearch` + `local_summarize` con la ruta), **V0 incluida**. Pero las tres
  metieron después el contenido en el contexto para buscar las cifras que el resumen no traía:
  V0 con una búsqueda por Bash de más de 2 KB, V1 con dos lecturas por franjas tras el bloqueo, V2
  con una. Coste 0,34–0,36 USD cada una.

**Lectura:** con estas tareas el cuello de botella no es la oferta sino la fidelidad del resumen
local, que pierde detalles; el modelo lo compensa leyendo y paga dos veces. Con las reglas de
REQ-102 las tres variantes darían «incorrecta» y el experimento no discriminaría. Propuesto al
usuario: piloto de 9 corridas con resúmenes sin datos concretos antes de las 72, y anotar en el
backlog un parámetro de enfoque para `local_summarize`.

## T5 — piloto (3 tareas × 3 variantes) — 2026-09-23 — LAS VARIANTES NO SE DISTINGUEN

Aprobado por el usuario en lugar de las 72 corridas, tras T4. `scripts/experimento_adopcion.py
--piloto --repeticiones 1`: tareas `readme`, `wiki-instalacion` y `wiki-daemon` sin hecho plantado,
pregunta «Hazme un resumen organizado siguiendo su estructura, para decidir qué partes leer con
calma» (no nombra secciones: un `Grep '^## '` la resolvería sin leer). **Correcta** = la respuesta
nombra al menos el 80 % de los títulos `##` (normalizados) **y** el contenido no entró al
contexto principal. Tests nuevos con mutantes que los hacen fallar. Banco en
`%TEMP%\banco-piloto-t5`; 9 corridas válidas al primer intento, 0,33–0,47 USD cada una (unos 3,6
USD en total).

| Tarea | V0 | V1 | V2 |
| --- | --- | --- | --- |
| readme (11 secciones) | ✗ cob. 1,00, 7 franjas | ✓ cob. 0,91 | ✗ cob. 0,73, sin leer |
| wiki-instalacion (9) | ✗ cob. 1,00, 2 franjas | ✗ cob. 0,89, 3 franjas | ✗ cob. 0,78, 2 franjas |
| wiki-daemon (5) | ✗ cob. 1,00, 1 franja | ✗ cob. 1,00, 1 franja | ✓ cob. 1,00 |

Correctas: V0 0/3, V1 1/3, V2 1/3. Coste medio: V0 0,45, V1 0,41, V2 0,37 USD.

- **Las 9 delegaron**, V0 incluida: `ToolSearch` + `local_summarize` (o `local_extract`) con
  `path`. La adopción de la primera llamada es 3/3 en las tres variantes; la oferta no cambia
  eso.
- **7 de 9 releyeron después por franjas.** El resumen local no sigue la estructura del documento
  (en palabras del modelo: «se saltaba» secciones, «mezclaba temas y no seguía el orden»), así
  que el modelo lo completa leyendo. Es el mismo cuello de botella que en T4, ahora con resúmenes
  sin cifras.
- Las dos correctas no dependen de la oferta: V1/readme se apoyó en `local_extract`, y V2/daemon
  partió el fichero por secciones con PowerShell y pidió un `local_summarize` por sección.
  V2/readme no leyó nada, pero la respuesta nombró 8 de 11 títulos y se quedó por debajo del
  umbral.
- Con una corrida por celda, 1 contra 0 es ruido. Ninguna variante supera a V0 en 3 tareas ni
  muestra una tendencia.

**Resultado (REQ-102):** las variantes no se distinguen. La oferta ya se adopta con V0; lo que
falla es la **fidelidad estructural del resumen local**, no la oferta. Según el escenario «nadie
gana» de la spec, se cierra REQ-102 sin las 72 corridas. REQ-104 y REQ-105 no aplican porque no
se publica ninguna variante. La palanca que queda es el parámetro de enfoque/estructura de
`local_summarize` (backlog §4.1).

### Retirada de V1/V2 — 2026-09-23 (escenario «nadie gana», decisión del usuario)

Alcance elegido por el usuario: se retiran las variantes y se conserva lo demás.

- **Fuera:** `LD_HOOK_OFERTA` (`config.HOOK_OFERTA`), `oferta()`, `receta_v1` y `TOOLS_RECETA`
  de `hook_common.py` (que vuelve a ser idéntico a `main`), el campo `oferta` de la telemetría, el
  permiso de V2 en el hook de prompt, `tests/test_oferta_directa.py` y los tests de `oferta` de
  `test_hook_recipes.py`. `suggest_delegate_read.py` y `config.py` vuelven a ser idénticos a
  `main`.
- **Se queda:** en el hook de Shell, la ruta absoluta con el `cwd` de la sesión, que ahora también
  va en el texto del bloqueo (antes V0 enseñaba la relativa, y el daemon la resolvería contra su
  propio directorio). En el hook de prompt, la sesión, la versión y el estado del bloqueo en todo
  evento. Y los scripts del banco y del experimento, sin `oferta` en su API.
- Tests: `tests/test_hook_shell_ruta_absoluta.py` (el texto del bloqueo de lectura, byte a byte
  contra `main`; la ruta absoluta en el texto del Shell; el cruce hook → servidor con la ruta
  ofrecida) y `test_todo_evento_del_prompt_lleva_sesion_version_y_bloqueo`. Mutantes: quitar la
  conversión a absoluta hace fallar los dos tests del Shell; quitar `**comun` de la telemetría del
  prompt hace fallar el de telemetría.
- `uv run pytest -q -p no:randomly`: 1382 passed, 2 skipped. `ruff check` y `ruff format --check`
  limpios.
- **Los hooks instalados en la PC siguen siendo los de T4** (con variantes, en V0 por defecto).
  Hasta reinstalar, el Shell enseña la ruta relativa en el texto del bloqueo.
