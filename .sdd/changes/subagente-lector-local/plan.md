# Implementation plan v4.1: que el hilo principal delegue en la tool directa

Sobre la spec v2 (aprobada 2026-09-22). El plan v3 del subagente queda en `plan-v3-subagente.md`;
de él se reutiliza el **banco de pruebas** y las reglas del experimento, que ya pasaron cuatro
rondas de revisión adversarial (`review.md`). La v4 la bloqueó una quinta ronda (B1–B7); esta v4.1
las corrige y cita cada una.

Rutas: todo lo de hooks vive en `src/local_delegate/resources/hooks/`.

## Approach

Todo el cambio vive en los hooks de Claude Code y en scripts del repo:

- Las variantes van detrás de `LD_HOOK_OFERTA` (`v0` por defecto = textos actuales byte a byte).
  Publicar la ganadora es cambiar el valor por defecto; retirarlas es borrar su código.
- **La receta de V1 se genera, no se escribe a mano (B1):** la tabla guarda el **nombre completo**
  `mcp__local-delegate__local_summarize` y `mcp__local-delegate__local_extract`, que es el que usan
  el hilo principal y `select:`. La ruta es siempre **absoluta** (B2). Solo se ofrece para lo que
  el hook ya bloquea hoy (prosa > 8 KB).
- **La receta va en condicional (B3):** «si no tienes la tool cargada, cárgala con `ToolSearch`
  y `select:<nombre>`; luego llámala con `path=<ruta>`». El hook no puede saber si las tools están
  diferidas; T4 comprueba que lo estén en las sesiones del experimento.
- La medición en uso real **amplía `scripts/medir_adopcion.py`**, que ya cruza bloqueos con
  delegaciones por `bloqueo_id`.

## Banco de pruebas (`scripts/_banco_claude.py`), heredado del plan v3

- Directorio de trabajo neutro en `%TEMP%`, `--model opus` fijo; el `CLAUDE.md` global del
  usuario forma parte del entorno medido y se declara.
- Entorno de hooks por `--settings <fichero>`: `LD_HOOK_OFERTA`, `LD_HOOK_TELEMETRY_LOG` **propio
  de cada corrida** (B4), `LD_HOOK_READ_BLOQUEAR=1` y `LD_HOOK_READ_INTERRUPTOR` apuntando a una
  ruta temporal inexistente. Nunca se toca el fichero global de apagado.
- **Control de precedencia al inicio de cada tanda:** una corrida con `LD_HOOK_ENABLED=0` sobre
  prosa > 8 KB; si aparece un deny, `--settings` no manda y la tanda aborta.
- **Estado de las tools (B3):** cada corrida se lanza con `--output-format stream-json --verbose`
  y se lee el mensaje `init`: tiene que estar `ToolSearch` y las `mcp__local-delegate__*` tienen
  que figurar como diferidas (o, si Claude Code no lo expone, se anota y se comprueba en el
  transcript si hizo falta `ToolSearch`). Si no coincide con lo que supone la receta, la tanda no
  vale.
- Rutas absolutas; `local_status` y una llamada de prueba antes de la primera corrida.
- Orden intercalado con semilla fija. Reintentos por infraestructura: 2 como mucho; a la tercera
  la tanda aborta.
- Ventanas horarias (+10 min de margen) y `session_id` de cada corrida en `verification.md` y en
  `benchmarks/ventanas-excluidas.json`.
- Anuncia corridas y coste estimado y pide confirmación.

## Ordered tasks

0. **Dependencia y exclusiones previas** (B5, nota 3)
   - Mezclar el PR #219 en `main` y rebasar la rama **antes de T1**: T1 toca el hook de prompt y el
     test byte a byte de V0 compara con `main`.
   - Escribir en `benchmarks/ventanas-excluidas.json` las sesiones de prueba del 2026-09-22 que
     corrieron con el entorno global: todas las de `entrypoint == "sdk-cli"` de ese día en
     `~/.claude/projects/` (se sacan sus `session_id` y sus ventanas de los transcripts con un
     script que no guarda rutas), incluidas las de `%TEMP%\banco-lector` y del spike.

1. **Telemetría de la variante (REQ-103, B4, nota 2)**
   - Files or modules: `hook_common.py`: `oferta()` lee `LD_HOOK_OFERTA` (válidos `v0|v1|v2`;
     uno desconocido cuenta como `v0` y se registra tal cual en `oferta_pedida`); `record()` añade
     `oferta` a todo evento. `suggest_delegate_prompt.py`: sus eventos pasan a usar
     `contexto_de(payload, __file__)` (llevan `session_id` y `version`, que hoy no llevan) y el
     estado del bloqueo. Read y Shell ya registran `version` y `bloqueo`.
   - Requirements covered: REQ-103.
   - Verification (`tests/test_hook_common.py`, `tests/test_hook_recipes.py`): `oferta` en los
     eventos de los tres hooks, también en el de prompt cuando no sugiere; `session_id` y
     `version` en los del de prompt; valor desconocido → `v0`; la telemetría sigue sin guardar
     prompt, comando ni ruta.
   - Rollback or recovery: campos opcionales.

2. **V1: receta lista en los hooks de lectura (REQ-101, B1, B2, B3)**
   - Files or modules: `hook_common.py` (tabla `TOOLS_RECETA` con nombres completos y función que
     arma la receta en condicional); `suggest_delegate_read.py` y `suggest_delegate_shell.py`
     (rama por variante). **Shell (B2):** la ruta del comando se convierte en absoluta con
     `payload["cwd"]` antes de la huella, de `anotar_bloqueo` y de la receta. Eso cambia la huella
     y la nota también en `v0` (no su texto): es deliberado —con una ruta relativa el cruce ya
     fallaba, porque el daemon la resuelve desde su propio directorio— y se anota en el CHANGELOG.
   - Requirements covered: REQ-101 (V0, V1).
   - Verification:
     - Con `v0`, el texto emitido es idéntico byte a byte al actual (comparado con `main`).
     - Con `v1`, contiene `ToolSearch`, `select:` y el nombre completo, y la ruta absoluta.
     - **Nombre (B1):** un test comprueba que cada nombre de `TOOLS_RECETA` es
       `mcp__` + `install.SERVER_NAME` + `__` + un nombre del registro del servidor. Mutante: quitar
       el prefijo → falla ese test.
     - **Cruce de punta a punta (B2, nota 4):** con `cat docs/x.md` (relativa) y con una ruta con
       espacios y comillas, la nota del hook y la huella que calcula el servidor para la ruta de
       la receta coinciden (`_bloqueo_reciente` devuelve el id). Mutante: sin la conversión a
       absoluta → falla el cruce con la relativa.
   - Rollback or recovery: `LD_HOOK_OFERTA=v0`.

3. **V2: permiso en el hook de prompt (REQ-101, B7)**
   - Files or modules: `suggest_delegate_prompt.py`.
   - Requirements covered: REQ-101 (V2), REQ-105 (insumo del criterio de retirada).
   - Verification: con `v2` y un prompt que menciona un fichero, una ruta o un log → permiso con
     los nombres completos; sin mención → como `v0`; eventos del sistema → silencio; nunca
     «MANDATORY». **Señal medible (B7):** el evento registra `disparo` = `ruta` | `extension` |
     `log` (qué patrón activó la oferta), sin el texto del prompt. Control positivo: el mismo
     prompt sin la mención no emite permiso ni `disparo`.
   - Rollback or recovery: `LD_HOOK_OFERTA=v0`.

4. **Control instalado**
   - Verification: reinstalar desde el árbol con el daemon parado (memoria
     `daemon-y-uv-tool-trampas`) y `local-delegate update`; ejecutar los hooks instalados con
     payloads reales por variante. Con el banco, una corrida por variante: su evento con la
     `oferta` y el `session_id` esperados en su log; el estado de diferido y `ToolSearch`
     registrado (B3); **en V1 el modelo que sigue la receta carga la tool y obtiene resultado sin
     error**; y con #219 ya mezclado, el prompt de `claude -p` deja su evento (no se filtra).

5. **Experimento de adopción y elección (REQ-102)**
   - Files or modules: `scripts/experimento_adopcion.py`; `benchmarks/adopcion-directa/tareas.json`
     (8 tareas: 2 docs, 2 logs de CI como `.txt`, 1 CHANGELOG, 1 diff como `.txt`, 1 salida de lint
     como `.txt`, 1 README; todas prosa > 8 KB) y el generador de ficheros con **hecho plantado**
     a partir de documentos del propio repo.
   - Requirements covered: REQ-102, REQ-107.
   - Verification:
     - R = 3 por tarea y variante (8 × 3 × 3 = 72 corridas); estimación de coste y confirmación.
     - **Válida** solo si el log de esa corrida tiene el evento del hook de prompt con su
       `session_id`, la `oferta` y el estado de bloqueo esperados; si no, reintento (banco).
     - **Correcta** = hecho plantado en la respuesta y, en el transcript principal, ni `Read`
       completo del fichero, ni `Read` con `offset`/`limit` del fichero, ni volcado por Bash
       (Bash o PowerShell cuyo comando contenga la ruta o el nombre del fichero y cuyo resultado
       supere 2 KB).
     - **Supera a V0 en una tarea** = más corridas correctas que V0 en esa tarea. Límite que se
       escribe junto al resultado: con R = 3 basta una corrida (nota 5); lo acota el mínimo de 3
       tareas de 8.
     - **Elección:** la que supera a V0 en más tareas, mínimo 3 de 8; desempate en este orden:
       menor coste medio (`costUSD`) sobre sus corridas válidas; después la más simple (V1 < V2).
     - Si gana una, cambia el valor por defecto de `LD_HOOK_OFERTA`. **Si ninguna gana, se borra
       el código de V1 y V2**; la conversión a ruta absoluta del hook de Shell se queda (arregla
       el cruce también en V0).
     - Resultado, ventanas y `session_id` en `verification.md`; nota en el vault.

6. **Medición en uso real y criterio (REQ-104, REQ-105, B5, B6)** — solo si T5 publica una
   variante
   - Files or modules: `scripts/medir_adopcion.py`: `--hasta`; `--excluir INICIO,FIN` repetible y
     lectura de `benchmarks/ventanas-excluidas.json` (ventanas y `session_id`); `--oferta`, que
     cuenta un evento **sin** `oferta` como `v0` (B5); **dos cruces (B6):** por `bloqueo_id` (el
     actual) y, para lo que no tenga id, por huella de ruta —el log de uso guarda `path` y se le
     calcula la huella con `huella_de_ruta`— dentro de 10 minutos tras la lectura, **solo con usos cuyo
     `client` es el de Claude Code** (el filtro va del lado del log de uso: ni el log guarda la
     sesión ni la telemetría de hooks guarda `client`; ronda 6, N2 y su verificación); y un **filtro real de sesiones
     nuevas** (solo las cuyo primer evento es posterior al inicio de la ventana y con la versión
     de hook **que se pasa por `--version` para esa ventana**: la base usa `a1485d36` y la variante
     la de la release; N1). **Tasa de delegación decisiva** = lecturas grandes del camino
     **`Read`** bloqueadas o avisadas que acabaron en `local_*` / esas lecturas. El camino Shell se
     informa **aparte** y no decide: desde T2 sus huellas son absolutas y cruzan, en la base no, y
     mezclarlos inflaría la variante sin que la oferta hiciera nada (N3). Además: escapes, errores
     de tool y eventos de V2 con `disparo` en sesiones cuyo transcript no menciona ningún fichero
     (B7; se revisan los transcripts de esas sesiones, sin guardar su texto).
   - Requirements covered: REQ-104, REQ-105, REQ-107.
   - Verification: tests con telemetría y log sintéticos (aceptado por id, aceptado por huella,
     escape, ventana y sesión excluidas, evento sin `oferta` contado como `v0`, sesión vieja
     descartada, formato desconocido → error claro, falso disparo de V2 detectado). **Los datos
     de uso sintéticos siguen el esquema real del log** (sin `session_id`; con `client`, `path`,
     `ts`, `tool`) y **los eventos de hook sintéticos también** (sin `client`; con `version`,
     `session_id`, `path_sha`) (N2). Controles positivos: sin la regla «sin campo = v0», la base de prueba da 0
     bloqueos (B5); una base sintética con la versión vieja no sale vacía si se le pasa su
     `--version` (N1); añadir a la base bloqueos de Shell con ruta relativa no cambia la tasa
     decisiva (N3).
   - **Línea base con fechas fijas (B5):** del **2026-09-15T21:03:55Z** (cambio de versión de hook,
     un único tramo con el bloqueo encendido) **al instante de la release**, excluyendo las
     sesiones de T0 y T4; si esa ventana tiene menos de 14 días, se usa entera y se dice. Se
     escribe en `verification.md` con el criterio de REQ-105 copiado literal y la fecha de inicio
     de la medición **antes** de publicar.
   - Rollback or recovery: solo lee.

7. **Documentación, release y memoria (REQ-106)**
   - CHANGELOG (incluida la huella absoluta del hook de Shell), README, `docs/wiki/` (hooks y
     `LD_HOOK_OFERTA` solo si se publica una variante), `docs/recipes/claude-code-hooks.md`; nota en
     el vault con el resultado de REQ-102; memoria del proyecto: fecha del tramo nuevo de versión
     de hooks.
   - Verification: tests de la wiki verdes; las tres superficies coherentes con lo publicado.

## Test strategy

- Unit: variantes (texto por variante, `v0` byte a byte), nombres completos contra el registro,
  telemetría, cruces por id y por huella, tasa, parsers de transcripts.
- Integration: hooks como subproceso con payloads reales capturados; cruce hook → servidor.
- End-to-end: T4 y T5 con el banco; evidencia por transcript.
- Security: pre-commit; los scripts no guardan contenido ni rutas.
- Controles: cada test nuevo con control positivo o mutante que muestre qué assert dispara.

## Migration and compatibility

- Solo Claude Code. Por defecto nada cambia en los textos hasta que T5 decida; la huella del hook
  de Shell sí cambia (absoluta) desde T2, y eso arregla un cruce que ya fallaba.
- Tramo nuevo de versión de hooks desde T1–T3: anotar la fecha.
- Cuota: T4 unas 4 corridas; T5 72 más los controles de precedencia. Cada script pide confirmación.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
