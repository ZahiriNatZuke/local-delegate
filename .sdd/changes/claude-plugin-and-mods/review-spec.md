# Revisión de la especificación — `claude-plugin-and-mods`

Gate: **especificación** (`spec.md`, 134 líneas). Revisión de solo lectura, 2026-10-21. Se
contrastó con `brief.md`, `research.md`, los cuatro `research-r*.md`, el código de
`src/local_delegate/` y, en lectura, la configuración real de esta PC (sin tocarla).

## Veredicto

**No aprobable tal cual.** Hay cinco hallazgos bloqueantes; dos de ellos (1 y 2) piden una decisión
del usuario porque chocan con «el MCP va dentro del plugin». Resueltos los cinco, el resto son
cambios de redacción y criterios y la spec pasaría a **aprobable con cambios**.

---

## A. Bloqueantes

### 1. El MCP del plugin solo sirve con el daemon local: rompe la Mac y el modo por defecto
- **Gravedad:** bloqueante. **REQ:** 002, 005, 006, 012, 017.
- **Evidencia:** REQ-002 fija `.mcp.json` a `http://127.0.0.1:9393/mcp` (`spec.md:29-30`). Pero el
  modo por defecto de `install` es **stdio** (`install.py:1676` `mcp_mode: str = "stdio"`,
  `cli.py:99`), y la Mac va por stdio con `--base-url` contra el backend de la PC porque **no tiene
  daemon** (memoria `topologia-mac-contra-la-pc.md`: «`--mcp-mode http` apunta a un daemon que en la
  Mac no existe»). REQ-006 además retira la entrada de `~/.claude.json`, que es justo la que hoy
  funciona en la Mac. Lo mismo para REQ-012 (chat de Desktop con `mcp-remote` contra
  `127.0.0.1:9393`): en la Mac no hay nada escuchando.
- **Corrección:** la spec tiene que decir qué MCP lleva el plugin en cada modo. Opciones: (a) el
  `.mcp.json` del plugin lanza por stdio un ejecutable propio (`local-delegate-mcp` o
  `local-delegate mcp-proxy`) que lee la configuración de local-delegate (modo, `base-url`, nombre
  de la variable de la key) y, en modo http, hace de puente al daemon; (b) el plugin solo trae MCP
  en modo http y en stdio la entrada sigue en `~/.claude.json` (y entonces REQ-004 y REQ-006 valen
  por modo); (c) `userConfig` con la URL y el modo, rellenado por `install`. Añadir un REQ: «con
  `--mcp-mode stdio`, tras `install` las 11 tools responden en Claude Code» y probarlo en la Mac.

### 2. `install` crea él mismo el duplicado de tools en la pestaña Code de Desktop
- **Gravedad:** bloqueante. **REQ:** 006, 009, 012, 014.
- **Evidencia:** la entrada `local-delegate` de `claude_desktop_config.json` **también se carga en la
  pestaña Code** y gana a igual nombre (`research-r2-claude-desktop.md:17-19`, `:48-55`, doc
  oficial citada). El MCP del plugin tiene otro nombre (`plugin:local-delegate:local-delegate`,
  `research-r1-plugin-format.md:121-125`), así que no se deduplica: dos juegos de 11 tools
  (`research-r2-claude-desktop.md:202-209`). REQ-006 promete «sin duplicados» (`spec.md:48`), pero
  REQ-012 **escribe** esa entrada (`spec.md:69-73`) y REQ-009 solo **avisa** de ello
  (`spec.md:61-62`). Además el boceto del mod fija tools por la regex `/__local_(\w+)$/`
  (`research-r4-mod-design.md:61`), que casa con los dos prefijos: con el duplicado se fijarían 8
  tools (~4 000 tokens) en vez de 4. En esta PC la entrada ya existe (escrita a mano, con
  `mcp-remote@latest` y token literal: `research-r2-claude-desktop.md:92`), así que el duplicado
  aparece aunque `install` no escriba nada.
- **Corrección:** decidir y escribir en la spec una de estas: (i) medir en T0 si la regla «mismo
  nombre ⇒ gana Desktop» se aplica también al `.mcp.json` de un plugin (si sí, la pestaña Code se
  queda con la entrada de Desktop y el nombre viejo: el mod y los hooks lo tienen que aceptar, y
  hay que decirlo); (ii) el mod oculta (`isDeferred`/filtro) el juego duplicado cuando ve los dos;
  (iii) volver a la opción (b) de R2 (MCP fuera del plugin), que es lo que el informe recomendaba.
  En todo caso, REQ-014 tiene que fijar **un solo** juego de tools, y REQ-012 tiene que decir qué
  hace con una entrada que ya existe y no escribió `install` (sustituir con copia, conservar,
  preguntar en `--dry-run`).

### 3. Los hooks de lectura se contradicen entre F1 y F4, y la mitad de la regla queda sin dueño
- **Gravedad:** bloqueante. **REQ:** 002, 008, 018, 020.
- **Evidencia:** REQ-002 mete en `hooks.json` «los mismos eventos que hoy escribe `install`»
  (`spec.md:31-32`), y REQ-008 los gobierna con un interruptor (`spec.md:55-58`). REQ-020 dice que
  con el plugin el hook de lectura «no se registra» (`spec.md:105-106`); como `hooks.json` es fijo,
  eso solo puede significar que cambia el contenido del plugin entre 0.40 y 0.41, y la spec no lo
  dice. Además «el bloqueo de lectura» son **tres** entradas: `Read`, las tools `read_*` de otros MCP
  y `Bash|PowerShell` (`install.py:77-91`, y el comentario de `install.py:79-81`: «son una regla sola
  declarada sobre dos caminos; encender uno sin el otro la muda de sitio»). El mod de REQ-018 solo
  intercepta `Read`. Si REQ-020 quita las tres, `cat informe.md` vuelve a pasar; si quita solo la de
  `Read`, la spec no lo dice.
- **Corrección:** REQ-020 debe enumerar qué entradas de `hooks.json` desaparecen en 0.41 y cuáles
  siguen (propuesta: se va solo `Read`; `Bash|PowerShell` y `read_*` siguen con el mismo
  interruptor), y que el mod escriba la misma telemetría (`blocks.jsonl`) para no cortar la serie
  de la ventana P-4 y del bloqueo encendido (memorias `ventana-p4-y-medicion-f1.md`,
  `bloqueo-lectura-encendido.md`). REQ-002 debe decir «los eventos de la 0.39 en 0.40; en 0.41,
  según REQ-020».

### 4. El cambio de prefijo deja sin permisos y sin tools al usuario real
- **Gravedad:** bloqueante (rompe la adopción, que es lo que se mide). **REQ:** 004, 007, 009, 021.
- **Evidencia:** en esta PC, `~/.claude/settings.json` tiene `permissions.allow`
  `"mcp__local-delegate__*"`; **54** ficheros de `~/.claude/agents` citan `mcp__local-delegate__`, y
  la sección «Modo orquestador» de `~/.claude/CLAUDE.md` (fuera del bloque gestionado) hace
  `ToolSearch("select:mcp__local-delegate__local_summarize,…")` (2 apariciones en el fichero). R1
  avisa que el renombrado rompe permisos (`research-r1-plugin-format.md:25-29`). REQ-004 no nombra
  los permisos; REQ-007 solo toca los agentes que `--agents` reconoce por su ancla
  (`agents.py:34-35`), no los editados a mano; nadie mira las referencias fuera del bloque
  gestionado. Resultado: cada llamada del modelo a una tool del plugin pide permiso (esperar
  cuesta: memoria `obediencia-no-viene-de-la-prosa.md`) y los agentes del orquestador cargan
  nombres que no existen. La medición de REQ-021 mediría eso, no las tools fijas.
- **Corrección:** añadir a REQ-009 un check «referencias al prefijo viejo sin el nuevo» en
  `permissions.allow`/`deny`, `~/.claude/agents/*.md` y `CLAUDE.md` fuera del bloque, con la línea
  exacta a añadir (regla del proyecto: dar la regla de permiso lista para copiar). Decidir si
  `install` añade la regla `mcp__plugin_local-delegate_local-delegate__*` a `permissions.allow`
  (hoy `install` no escribe permisos: `grep permissions install.py` = 0) o solo la propone. Criterio
  verificable: tras `install` en HOME simulado con esas tres referencias, `doctor` da `warn` con las
  tres y el texto a copiar.

### 5. La lectura resumida puede acabar en una escritura destructiva
- **Gravedad:** bloqueante para F4. **REQ:** 018, 019.
- **Evidencia:** con la variante elegida el motor guarda el resumen como contenido leído
  (`research-r4-mod-design.md:19-23`). REQ-019 solo mira `Edit` (`spec.md:101-104`). El caso grave es
  `Write`: si el modelo «ya leyó» el fichero (el resumen) y lo reescribe entero, el fichero queda
  con el resumen. Tampoco cubre `--resume`, que R4 marca como riesgo
  (`research-r4-mod-design.md:22-23`, `:169-170`). Y la prueba propuesta no discrimina: en `-p` el
  control negativo también editó (`research-r4-mod-design.md:12-16`); si la regla «leer antes de
  editar» no existe en interactivo, REQ-019 se cumple siempre. «O el mod fuerza la lectura real
  cuando el modelo va a editar» no dice cómo se sabe que va a editar.
- **Corrección:** REQ-019 nuevo: «tras una lectura resumida de F, el mod intercepta `Edit`,
  `Write` y `NotebookEdit` sobre F y los rechaza con el mensaje "lee F con `offset`/`limit` antes de
  modificarlo" hasta que haya una lectura real». Verificable en `-p` (no depende de la regla del
  motor) con un control positivo (sin mod, `Write` pasa) y uno negativo (con mod, `Write` se rechaza
  y F queda intacto, comprobado por hash). Añadir el caso `--resume` a las pruebas en vivo o
  declararlo límite documentado.

---

## B. Huecos (no bloqueantes, pero el plan los necesita escritos)

### 6. Hooks por subcomando: latencia y `PATH` sin requisito
- **REQ:** 003. El trampolín `local-delegate` tardó **1 127 ms** en arrancar
  (`research-r1-plugin-format.md:159-160`); con el hook de lectura encendido eso se paga en cada
  `Bash`, `PowerShell` y `Read`, y en cada prompt. Y en macOS, desde la app, `~/.local/bin` puede no
  estar en el `PATH` (`research-r1-plugin-format.md:161-165`); un `UserPromptSubmit` que no arranca
  puede **bloquear cada prompt** (`install.py:1102-1105`).
- **Corrección:** presupuesto de latencia (p. ej. p95 ≤ 300 ms por hook, medido con 20 invocaciones)
  y arranque perezoso del subcomando; ruta absoluta por `userConfig` (`${user_config.ld_bin}`,
  `research-r1-plugin-format.md:163-165`) rellenada por `install`, con check en `doctor`; y que un
  nombre de hook desconocido salga con 0 sin texto (compatibilidad entre un `hooks.json` viejo y un
  paquete nuevo durante `update`).

### 7. La skill del plugin pierde el idioma
- **REQ:** 002. Hoy `install` copia `SKILL.md` en el idioma vigente (`install.py:359-372`,
  `research-r3-install-surface.md:13`); un plugin trae un fichero fijo. La spec no dice qué idioma
  lleva ni cómo sigue a `LOCAL_DELEGATE_OUTPUT_LANGUAGE`/`language.json` (REQ-028 de proyecto).
- **Corrección:** decidir (skill bilingüe en un solo fichero, dos skills, o la skill sigue copiada
  por el CLI) y escribirlo; la regla del proyecto exige salidas es/en.

### 8. De dónde sale el marketplace y cómo se garantiza la versión
- **REQ:** 001, 005, 010. La spec no dice si `install` añade el marketplace desde GitHub
  (`ZahiriNatZuke/local-delegate[#ref]`) o desde la carpeta del plugin empaquetada en la wheel
  (`research-r1-plugin-format.md:220-221`). Con GitHub sin `#ref` fijo, el plugin (código que
  ejecuta hooks y un mod sin sandbox) no es el que se auditó con el paquete y la versión puede no
  coincidir (REQ-009 lo marcaría siempre). R1 avisa que con versión fija hay que correr
  `claude plugin marketplace update` antes de `claude plugin update`
  (`research-r1-plugin-format.md:342-343`); REQ-010 solo nombra el segundo.
- **Corrección:** fijar la fuente (propuesta: carpeta dentro del paquete instalado, o GitHub con
  `#v<versión>`), y REQ-010 con los dos comandos y el orden respecto a `uv tool upgrade`.

### 9. Qué ve quien viene de la 0.39.0, y la vuelta atrás
- **REQ:** 005, 006, 010, 011. Falta: (a) si `update` en una instalación 0.39 (entrega por settings)
  **migra** al plugin o sigue como está y solo lo sugiere; (b) dónde se guarda la vía elegida (como
  `language.json`) para que `doctor`/`update` no la adivinen; (c) `--claude-delivery settings` con
  el plugin puesto: debe desinstalarlo y reponer settings en el mismo paso, sin hueco ni duplicado;
  (d) bajar a la 0.39 deja el plugin y la 0.39 repone settings → hooks dobles que su `doctor` no
  ve: documentar «`uninstall` antes de bajar» o hacer que la 0.40 lo diga; (e) sesiones abiertas
  durante la migración (avisar de reiniciarlas).
- **Corrección:** un REQ «Migración y vuelta atrás» con esos cinco puntos y una prueba por cada uno
  en HOME simulado.

### 10. «Lo que puso `install`» necesita estado
- **REQ:** 011, 012. `uninstall` debe quitar el marketplace «si lo puso `install`» y la entrada del
  chat «que escribió» (`spec.md:67-68`), pero no hay registro de quién puso qué; en esta PC la
  entrada de Desktop la escribió el usuario.
- **Corrección:** fichero de estado de la instalación (qué piezas escribió, con versión y fecha) y
  la regla para entradas preexistentes.

### 11. HOME simulado, `--no-client-cli` y `--dry-run` con la vía plugin
- **REQ:** 005. `claude mcp --scope user` escribe siempre en el HOME real y por eso se apaga con HOME
  simulado (`cli.py:104-107`); `claude plugin install` seguramente igual
  (`research-r3-install-surface.md:200`). La spec no dice qué hace `install` en esos casos (¿usa
  `CLAUDE_CONFIG_DIR`? ¿cae a settings?) ni qué muestra `--dry-run` (los comandos `claude plugin …`
  sin ejecutarlos).

### 12. Piezas de la R3 que la spec no menciona
- **Pin `==versión`:** `plan_pin` reescribe `~/.claude.json` (`update.py:520-538`); con plugin hay que
  sacar a Claude Code de ahí (`research-r3-install-surface.md:197`).
- **`service.daemon_auth`** tiene que leer la cabecera del plugin, no la de `~/.claude.json`
  (`research-r3-install-surface.md:198`).
- **Skill retirada y duplicada:** borrar `~/.claude/skills/local-delegation` está en REQ-006, pero no
  `_RETIRED_SKILLS` (`install.py:128`) ni que el bloque de `CLAUDE.md` cite la skill con su nombre
  nuevo `local-delegate:local-delegation`.
- **WSL:** sin plugins ni mods (`research-r2-claude-desktop.md:58-63`); decir que ahí sigue la vía
  settings y que `doctor` dentro de la distro no espera plugin.
- **Versión de cada superficie:** REQ-005 mide la versión del `claude` del `PATH`, pero la pestaña
  Code de Desktop y VS Code traen la suya (mods: Desktop ≥ 2.1.286, VS Code ≥ 2.1.299,
  `research-r1-plugin-format.md:286-290`). Decir qué pasa si una superficie es más vieja.

### 13. Variable del token sin valor
- **REQ:** 002. Con `${LOCAL_DELEGATE_WEB_TOKEN}` sin definir, Claude Code manda el texto literal
  `${…}` y el daemon da 401 (`research-r1-plugin-format.md:119-120`). Usar
  `${LOCAL_DELEGATE_WEB_TOKEN:-}` (probado: `:110`) y que `doctor` avise de daemon con token +
  variable ausente en el entorno de Claude Code.

---

## C. Requisitos ambiguos o no verificables (con criterio propuesto)

14. **REQ-005** «2.1.292 salvo que la medición diga otra»: fijar el número en el plan y que el
    test lo lea de una constante. **REQ-002** «los agentes si los hay»: no hay ninguno empaquetado
    (`resources/` no tiene `agents/`); decir «ninguno en esta versión» o cuáles.
15. **REQ-016** se apoya en la marca `toolu_plugin_…`, que **ninguna** investigación midió (`grep`
    en los cinco informes: solo aparece en la spec). `$.mcp.call` puede no llevar `tool_use_id`, y
    entonces sus filas caerían en «sin atribuir». Criterio: prueba en vivo de una llamada del mod y
    de una del modelo en la misma sesión, y comprobar en el log que se distinguen por un campo
    concreto que la spec nombre.
16. **REQ-018** «ofrece resumir / leer entero»: no dice si pregunta siempre (R4 desaconseja: esperar
    cuesta, `research-r4-mod-design.md:156-158`) o resume por defecto con «leer entero» después;
    ni qué hace donde no hay diálogo (`$.ui.ask` rechaza en `-p`, `:151`; subagentes); ni qué
    umbral (8 KB sugiere, 100 KB fuerte, solo prosa: `:159-161`). El brief pedía «variante con
    botones»: que lo confirme el usuario.
17. **REQ-008**: el fichero `local-delegate-bloqueo-apagado` está **retirado y sin efecto desde la
    0.38.0**; el vigente es `local-delegate-block-off` (`deprecations.py:108-114`). Además falta la
    precedencia entre el estado nuevo, `LD_HOOK_READ_BLOCK` (`config.py:214`) y el fichero.
18. **REQ-015**: `/local-lint <comando>` ejecuta un comando por `$.process.run` sin shell: decir
    cómo se parten los argumentos (comillas en Windows), el límite de 30 s
    (`research-r4-mod-design.md:80-81`) y qué pasa si un admin veta `process.run` (`:86`) o en la
    pestaña Code si no funciona (pregunta abierta de la spec).
19. **REQ-021**: (a) «si no sube» sin umbral: fijar uno (p. ej. ≥ +10 puntos y ≥ 30 sesiones); (b)
    la base 25/111 es **cota baja** por 164 filas sin `tool_use_id` del 30-sep al 8-oct
    (`research.md:57-59`): rehacer la base solo desde el 8-oct para no inflar la subida; (c) Codex
    como control no discrimina: 0 delegaciones y 1 sesión en la ventana
    (`research-r4-mod-design.md:209-210`; memoria `control-que-no-discrimina.md`); quitarlo o usar
    otro control; (d) la 0.40 cambia a la vez plugin, permisos, skill y tools fijas: una subida no se
    puede atribuir a las tools fijas; (e) decir que el script cuenta por `tool_use_id` sin depender
    del prefijo.

## D. Seguridad, plataforma y acceso anticipado

20. **Token literal en Desktop (REQ-012):** cada `install`/`update` deja una copia `.bak` de
    `claude_desktop_config.json` con el token en claro, y esa entrada se carga también en la pestaña
    Code. Pedir: copias con permisos de solo usuario y rotación (una sola copia), `doctor` sin
    imprimir nunca el valor, y que la opción literal exija confirmación o flag explícito.
21. **`mcp-remote` fijado:** la regla del usuario exige Socket ≥ 0,7 al añadir una dependencia; la
    spec no lo pide. REQ-012 debe decir que la versión vive en una constante auditada en cada
    release y de dónde «sube» `update`. En macOS, `npx` lanzado desde la app puede no estar en su
    `PATH` (Homebrew): check en `doctor`.
22. **Mod sin sandbox:** pedir que lea solo `LOCAL_DELEGATE_WEB_TOKEN` (nombre literal), que solo
    hable con `127.0.0.1` y no registre el token; que si la API de mods cambia o el mod falla, el
    MCP, los hooks y la skill sigan funcionando (degradación probada); y un check de `doctor` sobre
    el estado del mod. F4 apagada por defecto hasta verificar (REQ-019 lo insinúa; decirlo para
    REQ-014/017 también, por ser acceso anticipado).
23. **CI con `claude`:** las pruebas sin cuenta instalan Claude Code en los tres SO; fijar versión
    exacta y auditarla (Socket), como el resto de dependencias.

## E. Alcance

24. Coherente con las decisiones del usuario (`research.md:62-70`) salvo: los nombres de los
    comandos cambian de `/local:resumir…` (brief) a `/local-summarize…` (justificado: sin `:` y
    código en inglés, `spec.md:82-84`), y REQ-018 no recoge la «variante con botones» del brief
    (ver 16). Las dos cosas deberían confirmarse con el usuario.
25. Falta en «Fuera de alcance»: la skill para el chat de Desktop (R2 propone un zip para subirlo a
    mano, `research-r2-claude-desktop.md:222`) y WSL. Escribirlo evita que el plan lo dé por hecho.
26. Recordatorio para el plan: la release toca CHANGELOG, README y `docs/wiki/` (memoria
    `regla-release-toca-tres-sitios.md`); la spec solo nombra la wiki en REQ-009.

---

## Evidencia que falta antes de aprobar
- T0 de Desktop: herencia de la variable **y** si «mismo nombre ⇒ gana Desktop» se aplica al MCP
  de un plugin (hallazgo 2).
- Decisión sobre el MCP en modo stdio y en la Mac (hallazgo 1).
- Marca real de las llamadas del mod en el log (hallazgo 15).

## Evidencia recomendada para el gate cuando se apruebe
- Spec revisada con los hallazgos 1–5 cerrados y 6–19 con criterio escrito.
- Tabla pieza × verbo (install/doctor/update/uninstall) × vía (plugin/settings) en la spec o como
  anexo, con una fila por cada pieza de la tabla de `research-r3-install-surface.md:7-20`.
