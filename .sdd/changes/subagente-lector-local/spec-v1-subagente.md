# Specification: Subagente que solo reenvía a las tools local_* (idea 1 de backlog §4.1)

## Summary

Un subagente de Claude Code, instalado por `local-delegate install --agents`, cuyas únicas tools
son las del MCP `local-delegate` y que corre en Haiku. Claude principal le pasa una ruta y una
pregunta mecánica; el subagente llama a la tool `local_*` que corresponde y devuelve su salida sin
reescribirla. Dentro de él no existe el camino de leer el fichero.

La hipótesis a comprobar es que esto **ahorra cuota** frente a que Claude principal lea el
fichero. No se da por hecha: el subagente tiene un coste fijo por invocación (research.md: 14 k
tokens de arranque con la configuración por defecto, 2,3 k con `omitClaudeMd` y una sola tool). Por eso el cambio va en dos
etapas con una compuerta en medio:

1. **Calibración controlada** — medir el punto de equilibrio (tamaño de fichero a partir del cual
   el subagente sale más barato) antes de ofrecérselo a nadie.
2. **Oferta y medición en uso real** — solo si la calibración encuentra un punto de equilibrio
   realista, los hooks y la skill ofrecen el subagente por encima de ese tamaño, y se mide en
   sesiones reales con un criterio de éxito y de retirada escrito aquí, antes de medir.

## Requirements

### Etapa 1 — el agente y su calibración

- **REQ-001 (el agente):** El paquete incluye un subagente con:
  `omitClaudeMd: true`, `model: haiku`, y en `tools` **solo** las tools de lectura que necesita,
  listadas una a una (sin comodín): las que aceptan `path` y no escriben —
  `local_summarize`, `local_extract`, `local_translate`, `local_explain_code`,
  `local_lint_summary`, `local_commit_msg` (el hilo principal vuelca el diff a fichero con Bash y
  pasa la ruta) y `local_describe_image`. Quedan fuera `local_classify` y `local_delegate` (solo
  aceptan texto: el texto ya habría pasado por el contexto principal), `local_boilerplate`
  (escribe ficheros) y `local_status` (diagnóstico). Un solo agente enrutador, no uno por tool:
  si el principal ya sabe qué tool quiere, la llama él con `path`. Al no llevar
  `local_delegate`, el agente no tiene el ancla de `agents.py` y queda fuera de `pending()`
  (REQ-004). Su `description` dice cuándo usarlo (resumir, extraer, clasificar, traducir o explicar un fichero por su ruta). Su prompt:
  (a) elegir **una** tool `local_*` y pasarle `path`, nunca el texto; (b) devolver la salida de la
  tool **literal**, sin paráfrasis ni comentario; (c) si la tool falla, devolver el error literal;
  (d) **nunca afirmar una acción que no hizo** (research.md: el spike afirmó «READ: ok» sin haber
  llamado a `Read`).
- **REQ-001b (presupuesto de arranque):** el primer turno del subagente instalado, medido en el
  transcript con una tarea mínima dentro de un proyecto con memoria, cuesta **≤ 6 000 tokens**
  (research.md: 2 274 con una tool y `omitClaudeMd`; cada esquema añade ~400). Un test compara el
  tamaño de los esquemas de las tools elegidas contra ese presupuesto, para que una tool que
  engorde su descripción no lo rompa en silencio.
- **REQ-002 (instalación):** `install --agents` crea el fichero si falta y lo actualiza si es
  nuestro. «Nuestro» lo decide un marcador de propiedad dentro del fichero. Si existe un fichero
  con ese nombre **sin** el marcador, no se toca y el plan lo dice. `--dry-run` muestra el texto
  literal. Se deja `.bak` al actualizar, como con el resto de ficheros del usuario.
- **REQ-003 (retirada):** `uninstall --agents` borra el fichero solo si lleva el marcador.
- **REQ-004 (convivencia con `agents.py`):** el agente propio no entra en el flujo que actualiza
  agentes ajenos (`pending()`), o entra sin efectos: una segunda corrida de `install --agents`
  no produce cambios.
- **REQ-005 (calibración)** — *enmendado el 2026-09-22 con aprobación del usuario: dos revisiones
  del plan mostraron que medir el brazo A corriendo sesiones es inviable (la tool `Read` corta en
  ~25 k tokens y el bloqueo de lectura interfiere)*. La calibración compara:
  - **A (Claude lee el fichero) — modelo de coste**, no corridas: tokens del fichero × precio de
    escritura de caché del modelo principal + tokens del fichero × precio de lectura de caché × N,
    donde **N** es la mediana de turnos de API que siguen a una lectura grande en los transcripts
    reales del usuario, medida **antes** de calibrar. Los tokens del fichero y los precios se
    obtienen de fuentes declaradas en el informe.
  - **Control del modelo:** una corrida real de A con un fichero que `Read` devuelve entero, en la
    que el coste que predice la fórmula tiene que coincidir con el del transcript; si no coincide
    dentro de la tolerancia que fija el plan, la calibración no vale.
  - **B (Claude delega en el subagente) — medido** en corridas reales de al menos cuatro tamaños
    (de ~8 KB a ≥100 KB): coste del subagente, del turno principal que lo invoca y el arrastre de
    su respuesta durante N turnos. Se **comprueba en el transcript del subagente** que llamó a
    una tool `local_*` con `path` y que la respuesta es correcta; si no, la corrida es un fallo.

  El informe da el coste de A y de B por tamaño y el **punto de equilibrio**: el tamaño a partir
  del cual B cuesta menos que A. Si B nunca cuesta menos que A, no hay equilibrio.
- **REQ-006 (compuerta entre etapas):** la etapa 2 solo se implementa si la calibración da un
  punto de equilibrio **≤ 64 KB**, el control del modelo pasa y B tiene como mucho un fallo. Si no, el
  cambio se cierra aquí: el agente se queda disponible (se invoca con `@`), no se ofrece desde los
  hooks, y el resultado queda escrito en `verification.md` y en el vault.

### Etapa 2 — oferta y medición (condicionada a REQ-006)

La investigación del ecosistema (research.md) cambia el foco: **elegir el agente funciona (12/14
cuando el prompt lo pide); lo que falla es decidir delegar (0/14 con solo la descripción)**, y las
tools MCP son diferidas mientras la lista de subagentes está siempre cargada. Por eso la oferta se
elige por experimento controlado entre variantes, no por intuición.

- **REQ-007 (variantes de oferta, seleccionables):** cada variante se activa con una variable de
  entorno de los hooks, sin reinstalar, para poder compararlas:
  - **V0 — actual:** los textos nombran las tools `local_*` (línea base).
  - **V1 — nombra al agente:** el deny de `suggest_delegate_read.py` y
    `suggest_delegate_shell.py` dice «pásale la ruta y la pregunta a `local-delegate-lector`»,
    solo para ficheros por encima del punto de equilibrio.
  - **V2 — permiso permanente:** V1 más el hook de prompt, **solo cuando el prompt menciona un
    fichero, ruta o log**, formulado como permiso del usuario que nombra al agente («Tienes mi
    permiso permanente para pasarle a `local-delegate-lector` la lectura de ficheros grandes…»).
    Nunca «MANDATORY» ni en prompts sin fichero (lección de claude-octopus: secuestra turnos).
  - **V3 — skill con fork:** V1 más una skill con `context: fork` y `agent: local-delegate-lector`
    que el modelo puede invocar. Mide si invocar una skill esquiva la reticencia a usar Agent.
  La skill `delegacion-local` menciona el agente **fuera** de la tabla de tools (esa tabla es la
  fuente del catálogo).
- **REQ-007b (experimento de adopción, antes de la medición en uso real):** un script en
  `scripts/` corre con `claude -p`, en sesiones nuevas, un conjunto fijo de al menos 8 tareas
  realistas que exigen leer un fichero grande (logs, docs, un diff, una imagen), sin mencionar
  delegación en el prompt, bajo V0…V3. Cuenta por variante: delegaciones en el agente, llamadas
  directas a `local_*`, lecturas por franjas y coste total (`modelUsage`).
  *Enmendado el 2026-09-22 con aprobación del usuario:*
  - **Corrida correcta** = la respuesta contiene el hecho verificable de la tarea **y** el
    contenido del fichero no entró al contexto principal: ni `Read` completo, ni **lectura por
    franjas**, ni volcado por Bash. Delegar en el agente y llamar a `local_*` con `path`
    directamente cuentan igual: los dos ahorran.
  - **Una variante supera a V0 en una tarea** si tiene más corridas correctas que V0 en esa tarea.
  - **Se publica por defecto la variante que supera a V0 en más tareas, con un mínimo de 3 de
    8**; el plan fija el desempate. Si ninguna llega, la oferta no se publica, el código de las
    variantes se retira y el cambio se cierra con el resultado escrito (el agente sigue
    disponible con `@`).
- **REQ-007c (arranque sin tools):** si el MCP no estaba listo cuando arrancó el subagente, sus
  tools desaparecen en silencio (anthropics/claude-code#79728). El prompt del agente le ordena
  responder «local-delegate no está disponible» y parar, sin intentar nada más. `maxTurns` bajo.
- **REQ-008 (atribución):** la telemetría de hooks guarda `agent_type` cuando el payload lo trae.
  Antes de depender de ese campo se captura un payload real, instalado, desde un subagente.
- **REQ-009 (medición en uso real):** un script en `scripts/` que lee los transcripts
  (`<sesión>/subagents/agent-*.meta.json` con nuestro `agentType`) y la telemetría, y reporta en
  una ventana: invocaciones, fallos (subagente sin llamada `local_*` o que devolvió algo distinto
  de la salida de la tool), tokens por invocación y lecturas grandes que siguieron haciéndose en
  el hilo principal. Si no encuentra los campos que espera, **falla con un mensaje claro**: el
  formato del transcript es interno.
- **REQ-010 (criterio, escrito antes de medir):** con la variante elegida en REQ-007b, ventana de
  **14 días** desde la release, solo sesiones nuevas.
  - **Se queda** si hay ≥ 10 invocaciones, ≤ 10 % de fallos y el coste medio por invocación está
    por debajo del coste que la calibración le asigna al brazo A para esos tamaños.
  - **Se retira la oferta de los hooks** si hay < 5 invocaciones, si los fallos pasan del 10 %, o
    si **un solo** transcript muestra al subagente afirmando un resultado que ninguna tool le dio.
  - Entre medias: no concluyente, se amplía la ventana a 30 días una sola vez.

### Transversales

- **REQ-011 (documentación):** CHANGELOG, README y `docs/wiki/` en la release que lo publique.
- **REQ-012 (sin datos privados):** ni el script de calibración ni el de medición guardan
  contenido de ficheros ni rutas en claro en sus informes (huella, como la telemetría).

## Acceptance scenarios

### Scenario: instalación limpia
- **Given** no existe el fichero del agente
- **When** se corre `install --agents`
- **Then** el fichero existe con el marcador, `tools` solo con las 7 tools de REQ-001,
  `model: haiku` y `omitClaudeMd: true`; una segunda corrida no cambia nada.

### Scenario: nombre ocupado por el usuario
- **Given** existe un fichero con ese nombre sin el marcador
- **When** se corre `install --agents` o `uninstall --agents`
- **Then** el fichero queda intacto byte a byte y el plan informa por qué.

### Scenario: el subagente sin camino alternativo
- **Given** el agente instalado y una sesión nueva
- **When** se le pide resumir un fichero por su ruta
- **Then** el transcript muestra una sola llamada `local_*` con `path`, y su respuesta coincide
  con la salida de la tool.

### Scenario: calibración con resultado negativo
- **Given** la calibración no encuentra punto de equilibrio ≤ 64 KB
- **When** se evalúa REQ-006
- **Then** no se toca ningún hook y el cambio se cierra con el resultado escrito.

## Edge cases and failure behavior

- Backend local caído o modelo enfriado: el subagente devuelve el error de la tool tal cual; no
  intenta otra cosa (no tiene con qué).
- La tool trocea (entradas grandes): es transparente para el subagente; la calibración usa
  ficheros que crucen el umbral de troceado para no medir solo el caso fácil.
- Formato de transcript cambiado por una versión de Claude Code: los scripts fallan con un
  mensaje, nunca devuelven ceros.

## Non-functional requirements

- Las pruebas de la calibración gastan cuota real: el script dice antes cuántas corridas va a
  hacer y pide confirmación.
- Compatibilidad: solo Claude Code (los subagentes `.md` son suyos). Codex, OpenCode y Claude
  Desktop no cambian.
- Firma de commits, ruleset de `main` y code scanning como siempre.

## Non-goals

- Comandos slash, plugin, trabajos en segundo plano y relevo (ideas 2–5 del backlog §4.1).
- Cambiar tools, modelos locales o el umbral del bloqueo de lectura.
- Forzar el uso del subagente (quitar el camino de franjas al hilo principal). El contador
  anti-franjas al estilo de Serena queda en el backlog: para editar hay que leer rangos exactos.
- Integrar el agente en `personal-dev-harness` (SDD aparte, en ese repo, cuando este cierre).

## Traceability

| Requisito | Plan | Verificación |
| --- | --- | --- |
| REQ-001…004 | por definir | tests de `install`/`agents` + prueba instalada |
| REQ-005, REQ-006 | por definir | informe de calibración en `verification.md` |
| REQ-007, REQ-007b, REQ-007c, REQ-008 | por definir (condicionado) | tests de hooks + informe del experimento de adopción + payload capturado |
| REQ-009, REQ-010 | por definir (condicionado) | informe a 14 días |
| REQ-011, REQ-012 | por definir | revisión de la release |
