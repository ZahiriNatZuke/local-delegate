# Specification: Renombrado a inglés de lo publicado y salidas en español e inglés

Insumos: [`brief.md`](brief.md) (decisiones del usuario y de la sesión principal, que esta spec no
reabre), [`research.md`](research.md) y sus dos detalles
([`research-rename.md`](research-rename.md), [`research-i18n.md`](research-i18n.md)). Cuando un
requisito cita una sección («rename §1c», «i18n §1f»), es de esos dos ficheros. Revisión:
[`review.md`](review.md) (ronda 1 y la respuesta a ella).

Convención de nombres: los nombres nuevos marcados **(propuesto)** son la propuesta de esta spec en
inglés; el revisor de la spec puede cambiarlos, y una vez aprobada la spec quedan fijos para el plan.

Numeración: los requisitos conservan el número de la ronda 1 para que la revisión se pueda cotejar;
los añadidos en la ronda 2 (REQ-043 a REQ-047) van dentro del frente al que pertenecen.

## Summary

Al terminar este cambio:

1. **Frente A, renombrado.** Todo identificador y término de máquina del paquete (CLI, variables
   de entorno, claves y valores de los datos que se escriben, API del panel, contrato de salida de
   las tools, ids de `doctor`, ficheros que se instalan o se crean en el disco del usuario,
   módulos, y luego el código interno, los tests y los scripts) está en inglés. Quien tiene la
   0.34.0 actualiza sin que nada deje de funcionar: los nombres viejos de CLI y variables siguen
   valiendo con aviso durante dos versiones menores, y **todo dato ya escrito se sigue leyendo para
   siempre**, sin reescribirlo.
2. **Frente B, idioma.** Todo texto para personas (CLI con su ayuda, `doctor`, salidas y errores de
   las tools, hooks, panel, `install`/`update`/`test-window`, llama-swap, skill, bloque gestionado y
   bloque de catálogo de los subagentes) existe en español e inglés. El idioma por defecto sale de
   una regla única y ejecutable (REQ-018); `install` lo deja fijado para los procesos que no tienen
   sesión (daemon, hooks); se puede fijar a mano con una variable; el panel tiene selector propio
   por visitante. Las descripciones de las tools pasan a **solo inglés** y el modelo local responde
   en el idioma elegido. Comandos, opciones y demás términos de máquina no se traducen.

El orden es obligatorio: el frente A antes que el B (brief, «Desired outcome»; detalle en REQ-035).

## Requirements

### Frente A: renombrado

**Herramientas de cierre**

- **REQ-044 — Detector de nombres en español versionado en el repo (ola A0).** La primera ola del
  frente A mete en `scripts/` el detector de nombres en español de la investigación
  (`scripts/detect_spanish_names.py`, propuesto) con:
  - su léxico **congelado** como fichero de datos versionado (`scripts/data/spanish_lexicon.json`,
    propuesto), **sin datos de terceros**: es el conjunto de palabras que aparecen en los
    identificadores, claves y nombres de fichero del propio repo, clasificadas una vez como español
    o inglés, más heurísticas que no necesitan datos ajenos (ñ, tildes, sufijos españoles). El
    procedimiento de generación queda documentado junto al fichero. Ejecutar el detector no necesita
    `wordfreq` ni red; `wordfreq` solo puede usarse, si acaso, como herramienta fuera del repo para
    proponer la clasificación al generarlo, y ninguno de sus datos se versiona. Una palabra que
    aparezca después en el repo y no esté en el léxico se informa como «sin clasificar» (no cuenta
    como 0), para que el léxico no se quede viejo en silencio;
  - un tokenizador de JS para el bloque `<script>` del panel que no añade dependencias; si se
    propone una (p. ej. `esprima`), pasa antes Socket con puntuación ≥ 0,7, y si no, es propio;
  - sus tests (`tests/test_detect_spanish_names.py`, propuesto), de dos clases:
    - **regresión** (no son control, porque el léxico sale del mismo repo y se cumplen por
      construcción): detecta al menos 29 de los 30 nombres españoles conocidos de rename §0 y 0 de
      los 54 ingleses, y el tokenizador de JS encuentra declarados los cinco nombres de control
      (`tokensClaude`, `aplicarBackend`, `acct`, `fmtNum`, `decimales`);
    - **control de las heurísticas** con un conjunto de palabras **reservadas** que no aparecen en
      el repo (españolas con ñ, con tilde y con sufijos españoles; inglesas que podrían confundirse),
      versionado aparte del léxico: las españolas se detectan y las inglesas no;
  - un **control de la clasificación** del léxico: una muestra aleatoria (semilla registrada) de al
    menos **100 palabras** del léxico, revisada a mano palabra por palabra, con un error ≤ 2 %
    (como mucho 2 mal clasificadas); la muestra, la semilla y el resultado se guardan en
    `evidence/` de la carpeta del cambio. Si se supera el 2 %, se corrige el léxico y se repite con
    otra muestra;
  - las palabras «sin clasificar» **bloquean** el cierre de REQ-016 hasta que se clasifiquen.

  Si al generar el léxico se usa `wordfreq` fuera del repo, se ejecuta con `uv run --with` y versión
  fijada, previa auditoría de Socket. Los escáneres de la
  investigación están conservados como insumo de esta ola en
  `tools/research-scanners/` de la carpeta del cambio (copiados del scratchpad de la sesión, sin
  rutas privadas); no son la pieza final.

**Superficie pública: CLI y variables**

- **REQ-001 — Subcomando y opción del CLI con nombre nuevo y alias.** `recalcular-coste` pasa a
  `recompute-cost` (propuesto) y `--reiniciar-calibracion` a `--reset-calibration` (propuesto), con
  los mismos valores (`five_hour`, `seven_day`) y el mismo efecto. Los nombres viejos siguen
  aceptándose, producen el mismo resultado y escriben en `stderr` un aviso que nombra el nombre
  nuevo y la versión de retirada (REQ-004); con el nombre nuevo no sale ningún aviso. Toda salida,
  ayuda o texto que hoy imprime el nombre viejo (incluido el `COMANDO` de `valoracion.py` que
  muestran el panel y `doctor`) muestra el nuevo.
- **REQ-002 — Variables de entorno con nombre nuevo y alias, en el paquete y en los hooks.** Las
  cuatro variables pasan a: `LD_HOOK_READ_BLOCK` (propuesto, antes `LD_HOOK_READ_BLOQUEAR`),
  `LD_HOOK_READ_SWITCH_FILE` (propuesto, antes `LD_HOOK_READ_INTERRUPTOR`),
  `LOCAL_DELEGATE_STRUCTURED_SUMMARY` (propuesto, antes `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO`) y
  `LOCAL_DELEGATE_COST_FALLBACK` (propuesto, antes `LOCAL_DELEGATE_COSTE_RESPALDO`). El nombre viejo
  sigue surtiendo el mismo efecto **tanto en el paquete como en los scripts de hooks instalados**.
  Si están las dos, gana la nueva. Las dos formas quedan dentro del aislamiento de entorno de la
  suite (el guardián `tests/test_aislamiento_entorno.py`, o su sucesor renombrado, falla si una se
  lee fuera de la puerta común).
- **REQ-003 — Aviso de nombres obsoletos, repartido por proceso.** El check `config.rol_retirado`
  se sustituye por uno solo, `config.deprecated_names` (propuesto), que avisa (estado de aviso, no
  de fallo) de cada nombre obsoleto en uso: las variables renombradas de REQ-002, las tres variables
  del rol `fast` retirado que hoy cubre `config.rol_retirado`, y el fichero interruptor viejo de
  REQ-012. Cada aviso nombra el nombre viejo, el nuevo y la versión de retirada. Reparto:
  - `doctor` mira el entorno de la shell en la que corre y el bloque `env` del `settings.json` de
    Claude Code, y la existencia del interruptor viejo;
  - el daemon y el servidor MCP por stdio, que `doctor` no ve, avisan ellos mismos en `local_status`
    de cada nombre obsoleto que hayan leído;
  - los hooks, **solo cuando la telemetría está encendida** (`LD_HOOK_TELEMETRY_LOG`, opcional),
    añaden a sus eventos la clave `deprecated_names` (propuesto: lista de nombres viejos leídos en
    esa invocación), y `doctor` informa de los nombres que aparezcan en la cola del fichero (eventos
    de los últimos 7 días, sin recorrerlo entero). Sin telemetría, el aviso de los hooks lo cubre lo
    que `doctor` ya mira (shell y `env` de `settings.json`), de donde los hooks heredan casi siempre.

  La tabla de checks de `docs/wiki/` y su test reflejan el cambio en la misma ola.
- **REQ-004 — Horizonte de los alias, comprobado por la suite.** Cada alias (subcomando, opción,
  variable, fichero interruptor) registra la **primera versión publicada** que contiene su
  renombrado (la fija el PR de release, no la ola; mientras no se publica, `pyproject.toml` aún dice
  la versión anterior). Funciona con aviso en esa versión y en las dos versiones menores
  siguientes, y se retira en la tercera (si se publica renombrado en 0.N, vive en 0.N, 0.N+1 y
  0.N+2 y desaparece en 0.N+3). Dos tests: uno falla cuando la versión del paquete alcanza la de
  retirada de un alias que sigue presente; otro comprueba que la versión registrada de cada alias
  coincide con la entrada del CHANGELOG que lo anuncia.

**Datos persistidos**

- **REQ-005 — Escritura solo en el formato nuevo, con una excepción temporal.** Desde la versión que
  renombra cada formato, el paquete y los hooks escriben únicamente nombres en inglés: nombres de
  fichero, claves y valores de enumeración. Afecta a todos los formatos de rename §1c con algo en
  español y a `vendor.json` (que la tabla de rename §1c no recogía, pero sí
  `evidence/persisted-data-scan.json`):
  - `usage-YYYYMM.jsonl` (`bloqueo_id`, `secciones`, `fallo_conexion` y los valores de
    `error_class`, `fallback_class` y la causa de conexión);
  - `enfriamiento.json` → `cooldown.json` (propuesto);
  - `enfriamiento-eventos.jsonl` → `cooldown-events.jsonl` (propuesto, con los valores de `evento`
    y `clase`);
  - `atribucion-YYYYMM.json` → `attribution-YYYYMM.json` (propuesto, con `cruce`);
  - `coste-agregados.json` → `cost-aggregates.json` (propuesto);
  - la telemetría de hooks (claves `motivo`, `bloqueo`, `camino`, `rutas` y sus valores, incluidos
    los de estado del bloqueo);
  - los temporales de REQ-012 y la salida de `benchmark --output`;
  - del paquete: `precios.json`, `densidad.json` y su directorio `resources/datos/`, y
    `resources/vendor/vendor.json` (`_acerca_de`, `files[]._procedencia`), junto con quien los
    escribe o comprueba (`scripts/vigilante_precios.py` y su workflow `vigilante-precios.yml`;
    `scripts/check_vendor.py` y el workflow `vendor-audit.yml`). Los ficheros del paquete viajan con
    su lector en el mismo wheel: cambian a la vez que él y no necesitan lectura dual.

  **Excepción:** mientras vivan los alias de REQ-004 de la versión que renombra el enfriamiento, el
  daemon escribe además `enfriamiento.json` en el formato viejo, para que los hooks de una versión
  anterior (que leen ese fichero) sigan viendo los modelos enfriados. La excepción tiene versión de
  retirada y la cubre el test de horizonte de REQ-004. Su test cubre los tres eventos (`entra`,
  `reentra`, `limpia`) y comprueba que los dos ficheros dan el mismo estado tras cada uno.

  La prosa guardada como valor (`fallback_reason`, motivo del respaldo, etiqueta de una ventana de
  prueba) no es término de máquina: es del frente B (REQ-033).
- **REQ-006 — Lectura dual para siempre, sin perder historia.** **Todo** lector de un formato de
  REQ-005 que vive en el disco del usuario, sin excepción, acepta el nombre de fichero, las claves y
  los valores viejos y los nuevos, mezclados en un mismo fichero y en ficheros distintos, sin fecha
  de caducidad. Son lectores, como mínimo, todos los de la columna «Lo leen» de rename §1c: el
  daemon, el panel (`web/metrics.py`), `doctor`, `recompute-cost`, `pace.py`, `atribucion`,
  `coste`, `cuota`, `valoracion`, `transcripts`, los hooks, `scripts/medir_adopcion.py`,
  `scripts/medir_enfriamiento.py`, `scripts/experimento_adopcion.py`,
  `scripts/medir_resumen_estructurado.py`, `scripts/_banco_claude.py`, y los lectores de la salida
  de `benchmark` (`analizar_benchmark.py`, `hoja_pares.py`, `hoja_revision.py`,
  `construir_corpus.py`), que leen también el corpus y las hojas ya guardados de F2. Un dato viejo
  leído da el mismo resultado (métrica, coste, estado, etiqueta del panel) que su equivalente nuevo.
  Según la clase de fichero:
  - **Estado vigente** (`enfriamiento.json`/`cooldown.json`): si existen los dos, gana el nuevo.
  - **Cachés de historia que no se pueden regenerar** (`atribucion-*`/`attribution-*`,
    `coste-agregados`/`cost-aggregates`): el arrastre se hace **una sola vez**, cuando el fichero
    nuevo aún no existe: se siembra desde el viejo, en formato nuevo, aplicando la misma regla de
    fusión que ya usa esa caché (en atribución, una entrada solo la sustituye otra de cruce mejor; en
    cuota, la identidad del punto, `(fuente, tipo, inicio, fin)`, y su vigencia, de modo que lo
    caducado no se arrastra; los valores de enumeración del viejo, `fuente` incluida, se traducen al
    formato nuevo **antes** de juntar, para que un mismo punto no entre dos veces). Desde ese
    momento solo se lee el nuevo para esa caché, y el viejo queda intacto. Las `marcas` arrastradas
    que tienen equivalente de máquina (REQ-033) pasan a ese valor; las que no, se copian tal cual.
    Controles que distinguen: una segunda corrida no cambia el recuento de entradas ni los
    `descartes`; un punto caducado no reaparece tras dos corridas; un cruce `exacto` del viejo no se
    pierde frente a uno `ventana` del nuevo; un punto viejo con `fuente=rechazo` y su gemelo nuevo dan
    un solo punto.
  - **Registros que solo crecen** (`usage-*`, `enfriamiento-eventos`/`cooldown-events`,
    telemetría): se leen siempre los dos.

  Ningún lector reescribe en el sitio un fichero viejo. Lo demuestra un test por formato con filas
  de los dos formatos, con control positivo: un lector que solo entienda el formato nuevo hace fallar
  el test, y un escritor de caché que no siembre, o que arrastre en cada corrida, hace fallar alguno
  de los controles de arrastre.
- **REQ-007 — Medición P-4 con los dos formatos.** `scripts/medir_enfriamiento.py` (o su sucesor,
  ver REQ-046) da el mismo informe sobre un tramo de eventos y log en formato viejo, en formato nuevo
  y mezclado, y su test lo demuestra con filas de los dos formatos. La medición de los 90 días
  (~2026-12-14, ventana abierta desde 2026-09-15T19:26:41Z) cuenta los eventos escritos antes y
  después del cambio sin perder ninguno.
- **REQ-046 — Los comandos de medición documentados siguen funcionando hasta cerrar sus
  mediciones.** Hasta que P-4 se cierre (medición de los 90 días hecha), el comando de P-4 tal como
  está escrito en los procedimientos vigentes
  (`.sdd/changes/delegacion-precisa-y-fiable/verification.md` y
  `.sdd/changes/daemon-reparte-el-backend/verification.md`) sigue funcionando sin cambios, con su
  nombre de script y sus opciones (`--desde`…). Si la ola de `scripts/` lo renombra antes, deja el
  nombre viejo como envoltorio, añade a esos procedimientos (de SDD ya cerrados) una **nota fechada**
  con el nombre nuevo en vez de reescribir lo escrito, y apunta en el backlog del proyecto la
  retirada del envoltorio tras cerrar P-4, con su fecha. La verificación de esa ola ejecuta el
  comando documentado y guarda la salida. Las opciones de los scripts de
  `scripts/` entran en el renombrado (REQ-015), con esta salvedad.
- **REQ-008 — Ficheros escritos por terceros.** `cuota-statusline.jsonl`, que escribe el
  statusline del propio usuario, se busca también como `quota-statusline.jsonl` (propuesto); si
  existen los dos, se leen los dos. La wiki documenta el nombre nuevo y que el viejo sigue valiendo.

**API del panel y su espejo JS**

- **REQ-009 — API del panel y JS en inglés, con paridad.** Los 81 campos de respuesta en español de
  `/api/*`, los identificadores propios del JS del panel y los ids del DOM pasan a inglés. La función
  de contabilidad del servidor y su espejo JS siguen dando el mismo resultado sobre las mismas filas,
  y el test de paridad que corre node sigue pasando y **falla si se renombra un lado sin el otro**
  (control positivo registrado en la verificación). Los diccionarios del JS indexados por valores
  persistidos (motivos de la telemetría de hooks, causas de conexión, roles) aceptan el valor viejo y
  el nuevo (REQ-006).

**Contrato de salida para modelos**

- **REQ-010 — Contrato de `local_extract` y marcadores, en un solo cambio anunciado.** Las subclaves
  de `_local_delegate` pasan a `truncated`, `warning`, `read_server_side.{chars, approx_tokens}`,
  `fallback.{answered_by, instead_of, reason, class}` y `raw` (propuestos); los marcadores pasan a
  `[local-delegate warning: …]`, `[local-delegate fallback: …]` y `[local-delegate: input truncated
  …]` (propuestos). El prefijo `[local-delegate error]` no cambia. Se emite **solo** la forma nueva
  (sin emisión doble), en la **misma versión publicada** que las descripciones de tools en inglés
  (REQ-027), como pide el brief; por eso, aunque es un renombrado, se programa con REQ-027 en el
  frente B (ver Traceability). El CHANGELOG de esa versión lo anuncia como cambio incompatible con la
  tabla vieja → nueva, y la página de la wiki que documenta el contrato lo refleja.

**`doctor`**

- **REQ-011 — Ids y grupos de checks en inglés.** `config.coste` pasa a `config.cost` (propuesto) y
  los grupos `entorno`, `andamiaje`, `servicio` a `environment`, `scaffold`, `service` (propuestos);
  `backend` no cambia. La salida JSON de `doctor` y las cabeceras usan los ids nuevos; el CHANGELOG
  lo anuncia. El número de checks no cambia (25): REQ-003 sustituye a `config.rol_retirado`. El test
  de la wiki que cuenta «las N piezas» sigue en verde.

**Ficheros en el disco del usuario**

- **REQ-012 — Nombres nuevos en disco y retirada de los viejos por `install`.** Pasan a inglés:
  - el interruptor `~/.claude/local-delegate-bloqueo-apagado` → `local-delegate-block-off`
    (propuesto);
  - el hook `anotar_llamada.py` → `record_call.py` (propuesto);
  - la skill `delegacion-local` → `local-delegation` (propuesto);
  - los temporales `local-delegate-bloqueos.jsonl` → `local-delegate-blocks.jsonl`,
    `local-delegate-llamadas/` → `local-delegate-calls/` y `local-delegate-salud-<huella>.json` →
    `local-delegate-health-<huella>.json` (propuestos);
  - la cookie `ld_sesion` → `ld_session` con su prefijo firmado `ld-sesion|v1` → `ld-session|v1`
    (propuestos);
  - en los subagentes del usuario que `install` actualiza (`agents.py`), el bloque de catálogo y su
    regla, que hoy nombran la skill `delegacion-local` (REQ-029).

  Tras `install` o `update` sobre una 0.34.0: el hook viejo y la skill vieja ya no existen en ninguno
  de los destinos donde se instalan, su registro en la configuración del cliente desaparece, y el
  bloque gestionado y los bloques de catálogo de los subagentes nombran la skill nueva. El interruptor
  viejo sigue apagando el bloqueo mientras viva su alias (REQ-004) y `doctor` lo avisa (REQ-003).
  Una cookie con el nombre viejo obliga a autenticarse una vez y no produce ningún error.
- **REQ-013 — Retirada de skills instaladas.** `install` sabe retirar skills por nombre igual que hoy
  retira scripts de hooks: una skill que el paquete ya no instala y figura en la lista de retiradas
  se borra de cada destino de skills, y una skill del usuario con otro nombre no se toca jamás. Lo
  demuestra un test con las dos situaciones.

**Módulos y superficie interna**

- **REQ-014 — Módulos del paquete en inglés, sin romper los scripts.** Los 14 módulos de
  `src/local_delegate` en español (rename §1h) se renombran, y la importación de `hook_common` desde
  el paquete sigue resolviendo. Para **cada** script de `scripts/`, la verificación de toda ola que
  renombre módulos o funciones de `src/` registra: `--help` ejecutado sin error y una corrida mínima
  sobre fixtures, o, si el script no admite una corrida sin datos reales, `get_file_problems` de
  PyCharm sin referencias sin resolver. Control positivo registrado: renombrar
  `atribucion.test_reason` sin tocar `scripts/medir_adopcion.py` hace fallar ese control.
- **REQ-015 — Identificadores internos, tests y scripts en inglés.** Funciones, clases, variables,
  parámetros, constantes, atributos y claves internas de `src/`, del JS del panel, de `tests/`
  (incluidos los 1 383 nombres `test_*` y los 41 módulos) y de `scripts/` (14 módulos, con sus
  opciones de línea de comandos salvo REQ-046) pasan a inglés, en olas posteriores a las de lo
  publicado. Ningún test se pierde: el número de tests recogidos por la suite al cerrar es ≥ al de
  antes del cambio más los añadidos.
- **REQ-016 — Cierre medible del frente A.** El detector de REQ-044, ejecutado sobre `src/`,
  `tests/`, `scripts/` y el JS del panel (identificadores, claves de cadena, valores de enumeración
  persistidos, ids del DOM), sobre las claves y valores de los `.json` de `src/**/resources`, y sobre
  los nombres de fichero y directorio del paquete y de los scripts, da **0** hallazgos fuera de una
  lista de excepciones. La lista está en la carpeta del cambio y cada entrada lleva su motivo, que
  solo puede ser: alias de compatibilidad (REQ-001/002/012, con su versión de retirada), lectura de
  formato viejo (REQ-005 excepción, REQ-006/007/008), envoltorio de REQ-046, dato de un tercero que
  no controla el paquete, dato de prueba del propio detector (sus tests y su léxico; enmienda del
  2026-10-12 tras la ola A0), o **pendiente**: lo que el frente A renombra pero se publica en el B (las
  subclaves y marcadores de REQ-010, que salen en B2). Dos controles: al **cerrar el frente A**, el
  detector da 0 fuera de la lista y la sección «pendiente» contiene solo lo de REQ-010; al **cerrar el
  cambio** (tras B2 y el resto de B), se re-ejecuta y la sección «pendiente» está vacía. En las dos
  corridas, los tests de control de REQ-044 siguen en verde.
- **REQ-017 — Comportamiento funcional idéntico.** Fuera de nombres, avisos de alias y textos, nada
  cambia: con las mismas entradas, las tools, el daemon, los hooks y el panel producen los mismos
  resultados, decisiones y métricas. Lo verifica la suite existente renombrada sin cambiar lo que
  afirma (salvo nombres) y, en vivo, una pasada de cada tool dentro de una ventana de prueba
  (REQ-038).

### Frente B: idioma

**Elección del idioma**

- **REQ-018 — Regla única del idioma, con precedencia ejecutable.** El idioma vigente de un proceso
  se resuelve así, en este orden, y el primer paso que da resultado decide:
  1. `LOCAL_DELEGATE_LANG` (propuesto), si su valor es válido según REQ-019. Un valor no válido se
     ignora (se sigue al paso 2) y se avisa (REQ-019). Origen: «variable».
  2. El fichero de preferencia de REQ-047, si existe y su valor es válido según la misma gramática.
     Uno ilegible o no válido se ignora con aviso. Origen: «preferencia».
  3. Sistema. **POSIX (Linux y macOS):** el locale efectivo es el primer valor no vacío de `LC_ALL`,
     `LC_MESSAGES` y `LANG`. Si `LANGUAGE` tiene valor y el locale efectivo no es «no declarado»,
     manda el **primer elemento** de la lista de `LANGUAGE` (`es:en` → `es`); si no, manda el locale
     efectivo. `C`, `POSIX`, `C.UTF-8` y el vacío cuentan como «no declarado». **Windows:** el idioma
     de la **interfaz** del usuario (no el formato regional; p. ej. una interfaz en inglés con formato
     regional `es-ES` da inglés); en Windows `LANG`, `LC_*` y `LANGUAGE` **no se consultan** (Git Bash
     y MSYS los definen a menudo como `en_US.UTF-8`). Origen: «sistema».
  4. Si lo obtenido empieza por `es` (sin distinguir mayúsculas, con o sin región), español;
     cualquier otro valor, o «no declarado», o un error al consultar, inglés. Origen: «reserva»
     cuando no se obtuvo nada.

  La regla está implementada **una sola vez, dentro de `hook_common.py`**, que el paquete ya importa
  y que `install` ya copia con los hooks, así que no hace falta un fichero nuevo que copiar (el
  check `scaffold.hook_files` sigue cubriendo la copia). Un test comprueba que el paquete no contiene
  otra función de detección, y el guardián de aislamiento de entorno falla si algún código lee `LANG`,
  `LC_*`, `LANGUAGE` o llama a la API de idioma de Windows fuera de esa función. Los tests prueban la
  función real con el entorno, el fichero de preferencia y la API de plataforma inyectados, con un
  caso que distinga cada paso de la precedencia (control positivo), entre ellos: `LANGUAGE=es:en`
  con `LANG=en_US.UTF-8` → `es`; `LANGUAGE=es` con `LANG=C` → inglés; `LC_ALL=en_US.UTF-8` con
  `LANG=es_ES.UTF-8` → inglés; `LANG=C.UTF-8` → inglés; Windows con interfaz `en-US` y formato
  regional `es-ES` → inglés; Windows con `LANG=en_US.UTF-8` e interfaz `es-ES` → español; preferencia
  `es` con el sistema en inglés → español; `LOCAL_DELEGATE_LANG=en` con preferencia `es` → inglés;
  `LOCAL_DELEGATE_LANG=fr` con `LANG=es_ES.UTF-8` y sin preferencia → español y aviso.
- **REQ-019 — Elección explícita con una sola variable.** `LOCAL_DELEGATE_LANG` fija el idioma de
  todo proceso que la vea: CLI, servidor MCP por stdio, daemon HTTP (un idioma para todos sus
  clientes MCP) y hooks, por encima de la preferencia de REQ-047. Valor válido: `es` o `en`, con o
  sin región, sin distinguir mayúsculas (gramática `^(es|en)([-_]([A-Za-z]{2}|[0-9]{3}))?$`); `es-MX`,
  `en_US` y `es-419` son válidos; `fr` o `english` no lo son. No hay opción de línea de comandos para
  el idioma. `doctor` muestra el idioma vigente de su proceso y su origen («variable», «preferencia»,
  «sistema» o «reserva») y avisa de un valor no válido; `local_status` hace lo mismo para el proceso
  servidor (incluido el daemon, que corre sin la shell del usuario).
- **REQ-047 — Preferencia de idioma guardada por `install` para los procesos sin sesión.** El
  daemon (tarea programada, `launchd`, `systemd`, o un lanzador propio del usuario) y los hooks no
  ven el entorno de la sesión interactiva, y el paquete no instala el daemon ni escribe el `env` de
  `settings.json` (revisión ronda 2, hallazgo 1). Por eso `install` y `update` resuelven el idioma
  con REQ-018 (pasos 1, 3 y 4, sin leer la preferencia vieja) **en la sesión interactiva en la que se
  ejecutan** y lo guardan en un fichero de preferencia, `language.json` (propuesto), dentro del
  directorio de datos del paquete (`LOG_DIR`, el mismo que ya resuelven por su cuenta los hooks para
  leer el estado de enfriamiento). Ese fichero es el paso 2 de REQ-018 y llega igual al CLI, al
  servidor MCP por stdio, al daemon y a los hooks sin tocar lanzadores ni `settings.json`. Cubre
  también macOS, donde `launchd` no hereda `LANG`: por eso no se consulta `AppleLanguages`.

  El fichero guarda el idioma **y su origen** (p. ej. `{"lang": "es", "source": "variable"}` o
  `"source": "system"`). Regla de escritura de `install`/`update`:
  - si la resolución nueva viene de la variable, se escribe (es una elección explícita);
  - si viene del sistema, se escribe solo cuando no hay fichero o lo guardado también vino del
    sistema; **nunca** se pisa una elección explícita guardada;
  - **nunca** se escribe el valor de reserva (si la sesión no declara idioma, el fichero no se toca).

  `uninstall` borra `language.json` junto con lo demás que instaló `install`: es configuración que
  escribe el instalador, no un dato de medición. `doctor` y `local_status` muestran, además del
  idioma y el origen, la **ruta** del `language.json` que consultó su proceso (exista o no).

  Tests: `install` con dos idiomas de sesión del sistema (el fichero cambia); preferencia `es` de
  origen «variable» más `update` sin la variable y el sistema en inglés (no cambia); preferencia de
  origen «sistema» más `update` en reserva (no cambia); `update` con `LOCAL_DELEGATE_LANG=en` sobre
  una preferencia `es` (cambia); `uninstall` (el fichero desaparece); y la regla con el fichero
  presente y el sistema en el otro idioma. En vivo, `doctor` y `local_status` muestran el mismo
  idioma, el origen «preferencia» y la misma ruta tras instalar.
- **REQ-020 — Selector de idioma en el panel.** El panel tiene un selector ES/EN visible en la
  cabecera. La elección se guarda por visitante en el navegador (no en el servidor) y se recuerda al
  volver. Sin elección guardada, el valor inicial es el idioma del **navegador**: español si empieza
  por `es`, inglés en cualquier otro caso. (Es al revés que `site/index.html`, que sale en español
  salvo que el navegador empiece por `en`; lo decidió la sesión principal el 2026-10-12, en
  coherencia con la reserva en inglés de REQ-018.) El idioma del daemon no influye en el panel: el
  mismo daemon sirve a la vez a un visitante en español y a otro en inglés, cada uno con todo su
  texto en su idioma, incluido el que redacta el servidor (REQ-025). Cambiar el selector no exige
  volver a autenticarse ni pierde el rango de fechas ni los filtros. `<html lang>`, `<title>` y la
  descripción de la página siguen el idioma elegido.

**Superficies**

- **REQ-021 — CLI completo en el idioma elegido.** Toda salida del CLI para personas (resultados,
  errores, avisos de alias, mensajes de `install`, `update`, `uninstall`, `test-window`,
  `recompute-cost`, `benchmark` y llama-swap) y la ayuda de `--help` **incluido su armazón**
  («usage:», «options:», «show this help message and exit») salen enteras en el idioma elegido, sin
  mezcla. Los nombres de subcomandos, opciones y valores no se traducen.
- **REQ-022 — `doctor` y checks.** Títulos de check, etiquetas de estado, remedios, cabeceras de
  grupo y resumen final salen en el idioma elegido. Los ids de check y de grupo no cambian con el
  idioma.
- **REQ-023 — Salidas de las tools MCP y `local_status`.** Errores (tras el prefijo
  `[local-delegate error]`, que no se traduce), avisos tras los marcadores de REQ-010, recibos (la
  línea de «leído server-side», el recibo de `local_boilerplate`, troceado y map-reduce), el texto
  de `local_status`, las etiquetas de causa y la descripción de cadenas de respaldo salen en el
  idioma del proceso servidor. Los marcadores y claves de máquina no cambian con el idioma.
- **REQ-024 — Hooks en el idioma elegido sin importar el paquete.** Los mensajes que los hooks
  entregan al modelo y al usuario (`additionalContext`, `permissionDecisionReason`) salen en el
  idioma resuelto con REQ-018 (normalmente el fijado por REQ-047), y los scripts instalados siguen
  sin importar el paquete (el guardián que lo exige, si no existe, se crea). Siguen siendo solo
  ASCII en los dos idiomas.
- **REQ-025 — Panel entero en el idioma elegido, también lo que redacta el servidor.** Todo texto
  visible del panel (marcado, atributos visibles, cadenas del JS, KPI, diálogos, formatos de número y
  fecha, y los textos que hoy llegan ya redactados del servidor: etiquetas de causa, `detalle`, roles,
  `reason` de hooks, resumen de cada tool) sale en el idioma del selector, como muy tarde en el
  siguiente refresco de datos tras cambiarlo. Por eso esos textos no pueden depender del idioma del
  proceso servidor: o el panel los pide en el idioma del visitante, o el servidor manda claves y el
  panel los redacta (lo decide el plan). Control: con el panel en inglés, ninguna cadena del
  catálogo en español que difiera de su versión inglesa aparece en el texto visible del DOM, salvo
  datos persistidos (REQ-033); control positivo: dejar una etiqueta de una sola palabra sin traducir
  hace fallar el test.
- **REQ-026 — Formatos de número y fecha por superficie.** El CLI, `doctor` y el panel formatean
  números y fechas según el idioma (en español, punto de miles y coma decimal; en inglés, coma de
  miles y punto decimal). Las salidas MCP que lee un modelo escriben los enteros **sin separador de
  miles** y los decimales con punto, en los dos idiomas: hoy «20,027» dentro de una frase en español
  es ambiguo (en español se lee como decimal) y un número sin separador no es ambiguo para el modelo
  ni para la persona que lee el transcript.
- **REQ-027 — Descripciones de tools solo en inglés.** Los 11 docstrings de tool, sus descripciones de
  parámetros, los 11 títulos de anotación y la descripción del servidor quedan en inglés y no
  dependen del idioma elegido. Se publican en la misma versión que REQ-010, en una ola del frente B
  posterior a la que crea el catálogo. El resumen de cada tool que muestra el panel sale del catálogo
  de textos en el idioma del panel, no de la primera línea del docstring; si esa parte llega en una
  ola posterior, entre ambas el panel muestra los resúmenes en inglés, y se acepta.
- **REQ-028 — El modelo local responde en el idioma elegido.** `local_summarize`,
  `local_lint_summary`, `local_explain_code` y `local_describe_image` piden al modelo responder en el
  idioma del proceso servidor, y lo hacen con independencia del idioma del documento. **No entran**:
  `local_commit_msg` (regla propia, abajo), `local_translate` (manda `target_lang`), `local_extract`
  y `local_classify` (devuelven valores y etiquetas literales de la entrada), `local_boilerplate`
  (código) y `local_delegate` (el prompt lo escribe quien llama).

  **`local_commit_msg` (enmienda del 2026-10-14, decisión del usuario tras la revisión
  `evidence/local-tools-review/report.md`):** el idioma del mensaje es, por orden,
  `LOCAL_DELEGATE_COMMIT_LANGUAGE` si está puesta, y si no el **idioma vigente del producto**
  (REQ-018/REQ-019). La regla anterior, «el idioma predominante de los textos del diff», queda solo
  como valor explícito de la variable, `diff` (sin distinguir mayúsculas), que reproduce el prompt de
  antes. Motivo: en repos bilingües el modelo elegía uno u otro idioma (reproducido). Lo comprueban
  tests de prompt: sin la variable, con idioma vigente `es` el prompt pide español y con `en`
  inglés; con la variable puesta manda ella; con `diff`, el prompt de antes; y el prompt de
  `commit_msg` no cambia con `LOCAL_DELEGATE_OUTPUT_LANGUAGE`.

  Lo comprueban, para las cuatro tools, tests de prompt y una muestra en vivo dentro de una ventana de prueba: al menos 5
  documentos por tool e idioma, todos en el otro idioma, y al menos el 90 % de las respuestas en el
  idioma vigente. El juez es un detector de idioma versionado (no el ojo), y la muestra se guarda en
  la verificación con el id de la ventana. El detector concreto y el conjunto de documentos los fija
  el plan antes de la ola B2.

  **Enmienda del 2026-10-14 (issue #260): idioma de respuesta del modelo en texto libre.** Una
  variable aparte, `LOCAL_DELEGATE_OUTPUT_LANGUAGE` (propuesto), fija **solo** el idioma en que
  esas cuatro tools piden responder al modelo, para idiomas fuera de `es`/`en` (`fr`, `pt`,
  `de`, `it` o texto libre, los mismos valores que `LOCAL_DELEGATE_COMMIT_LANGUAGE`). Reglas:
  - Prioridad: `LOCAL_DELEGATE_OUTPUT_LANGUAGE` si está puesta y es válida; si no, el idioma vigente
    de REQ-018/REQ-019. Vacía (el valor por defecto) = el comportamiento de arriba.
  - No cambia los textos de interfaz (recibos, errores, `local_status`, hooks, panel): esos siguen
    a `LOCAL_DELEGATE_LANG`. Tampoco cambia `local_commit_msg` (manda `COMMIT_LANGUAGE` o el idioma
    vigente del producto, con `diff` para la regla del diff), `local_translate` (`target_lang`) ni
    las tools excluidas arriba.
  - Valor válido: texto de 1 a 40 caracteres tras recortar espacios, sin saltos de línea ni
    caracteres de control. Un valor no válido se ignora (se sigue al idioma vigente) y se avisa.
  - En el troceado (map-reduce), la instrucción va en cada paso, no solo en el de reducción.
  - `doctor` y `local_status` muestran el idioma de respuesta efectivo y su origen («variable de
    salida» o el origen de REQ-019).
  - Se comprueba con tests del prompt por tool (la variable puesta aparece en el prompt; vacía o no
    válida, el prompt es el del idioma vigente; `local_commit_msg` no cambia con ella; `fr` y
    `português` como valores de prueba) y una muestra en vivo con la variable puesta al idioma
    **contrario** al del producto (producto `es` + variable `en`, y al revés; enmienda del
    2026-10-14: el detector solo juzga `es`/`en`): al menos 5 documentos por tool, y al menos el
    90 % de las respuestas en el idioma de la variable según el mismo detector.
- **REQ-029 — Skill, bloque gestionado y catálogo de los subagentes en el idioma vigente.** `install`
  genera en el idioma vigente de la sesión en que corre:
  - la skill (con el nombre de REQ-012) y el bloque gestionado de `CLAUDE.md`/`AGENTS.md`;
    reinstalar en el otro idioma cambia el idioma del bloque y deja **un solo** bloque (test con un
    bloque 0.34.0 en español y reinstalación en inglés);
  - el bloque de catálogo que `agents.py` inserta en los subagentes del usuario que delegan
    (`~/.claude/agents/*.md`), con su regla y el nombre nuevo de la skill. Es texto de salida que se
    instala en ficheros del usuario, así que **entra**. Hoy el sitio de inserción se reconoce por el
    encabezado «Delegación a modelos locales» (`agents.py:41`): pasa a reconocerse en los dos idiomas
    (encabezado inglés propuesto: «Delegation to local models»), y un bloque ya marcado con
    `<!-- local-delegate:catalog:begin -->` se reemplaza en cualquier idioma, también un bloque
    0.34.0. Tests: subagente con encabezado en español, en inglés, y con bloque 0.34.0.

  Un guardián exige que la skill en español y en inglés listen exactamente las mismas tools `local_*`
  con los mismos identificadores, y el catálogo de los subagentes se extrae de la skill del idioma
  vigente.
- **REQ-030 — Una sola fuente de textos por idioma.** Python y el panel toman sus textos de la misma
  fuente por idioma; los hooks, que no importan el paquete, llevan textos cubiertos por el mismo
  guardián de REQ-031. No hay dos copias de una misma frase que se puedan desincronizar sin que falle
  un test. (El mecanismo, catálogo JSON compartido u otro, lo decide el plan; ver i18n §5.)

**Guardianes**

- **REQ-045 — Ningún texto de salida fuera del catálogo.** Un guardián
  (`tests/test_no_uncatalogued_text.py`, propuesto; ola B0) falla si encuentra un literal de texto
  para personas que no pasa por el catálogo:
  - en Python, por AST, en los contextos de salida de i18n §1 (`print`, mensajes de excepción que
    llegan a consola, `help=`/`description=` de argparse, resultados y errores de tools, textos de
    `doctor`, mensajes de hooks), con la clasificación de contextos declarada en el propio guardián;
  - en el panel, por escaneo de los literales del JS y del texto y atributos visibles del HTML.

  No depende de detectar español, así que cubre las etiquetas de una o dos palabras («Latencia»,
  «Cargando»). Nace con una lista de ficheros pendientes que cada ola del frente B vacía; al cerrar
  el frente B la lista está vacía. Aparte hay una lista de **excepciones legítimas** en contextos de
  salida (JSON volcado, el prefijo `[local-delegate error]`, rutas, ids, nombres de máquina), cada una
  con su motivo y revisada en cada ola, más un test que falla si alguna excepción contiene texto para
  personas (letras con espacios entre palabras que no sean un identificador). Control positivo: un
  `print("Hola")` o una etiqueta JS de una palabra fuera del catálogo lo hacen fallar.
- **REQ-031 — Paridad entre idiomas.** Un test falla si un texto existe en un idioma y no en el otro,
  si una traducción está vacía, si los marcadores de interpolación (`{n}`, `{0}`…) no coinciden, o si
  un identificador entre comillas invertidas (variable, opción, `local_*`) no es idéntico en los dos
  idiomas. Control positivo: borrar una traducción, cambiar un marcador o un identificador lo hace
  fallar.
- **REQ-032 — Guardianes del panel y de la wiki en los dos idiomas.** Los guardianes del panel de
  tipografía y longitud («sin prosa», ninguna etiqueta de 6 o más palabras, sin párrafos) corren con
  el panel en español y en inglés. El test de la wiki que compara los títulos de checks compara contra
  los títulos en español (la wiki sigue en español) y sigue fallando si un título cambia sin su
  fila.
- **REQ-033 — Lo ya escrito se muestra tal cual.** La prosa guardada como valor en disco (motivo del
  respaldo, `fallback_reason`, etiquetas libres de ventanas de prueba) se muestra como está escrita,
  en el idioma en que se escribió, sin traducirla. Lo nuevo que se escriba como prosa se escribe en el
  idioma del proceso que lo escribe. Las `marcas` de `coste-agregados.json` («cota baja», «solo
  comprobación», «reinicio»), que hoy son prosa usada como valor de máquina, se escriben a partir de
  ahora como valor de máquina en inglés con su etiqueta en el catálogo, y las viejas se reconocen al
  leer y al arrastrar (REQ-006).
- **REQ-034 — Pruebas de humo en inglés por superficie.** Además de los tests que afirman el texto en
  español (que siguen valiendo gracias a REQ-043), hay al menos un test por superficie de REQ-021 a
  REQ-025 y REQ-029 que corre con el idioma en inglés y comprueba que ninguna cadena del catálogo en
  español que difiera de su versión inglesa aparece en la salida, salvo nombres de máquina y datos
  persistidos.
- **REQ-043 — La suite no depende del idioma de la máquina.** Un fixture automático de la suite fija
  `LOCAL_DELEGATE_LANG=es` en todos los tests, por el mecanismo de aislamiento de entorno que ya
  existe (la variable entra en `config.VARIABLES_DE_ENTORNO`). Ningún test lee el fichero de
  preferencia real del usuario: hoy la suite solo aísla `config.LOG_DIR`, y `hook_common` resuelve el
  directorio de datos por su cuenta (`LOCALAPPDATA`, `XDG_DATA_HOME`, `~/Library`), así que (a) la
  función de idioma recibe el directorio de datos como argumento (el paquete pasa `config.LOG_DIR`;
  los hooks, el directorio que resuelven), y (b) un fixture automático fija `LOCAL_DELEGATE_LOG_DIR`
  a un directorio temporal en el entorno, para que también los hooks lanzados como subproceso lo
  usen. Control positivo registrado: con `LOCALAPPDATA`/`HOME` apuntando a un directorio falso que
  contiene un `language.json` con `en`, un test que espera `es` sigue en verde; y quitando el fixture
  (b), ese mismo montaje hace fallar un test de hook lanzado como subproceso. Los tests del
  panel con Playwright, que eligen idioma por el navegador (REQ-020) y no por la variable, crean el
  contexto del navegador con `locale` explícito desde un fixture común: `es-ES` por defecto, `en-US`
  en los tests de inglés. Los tests de inglés y los de detección (REQ-018) sobrescriben lo suyo
  explícitamente. Requisito verificable: la suite pasa entera, **incluidos los tests de Playwright**,
  con `LANG=en_US.UTF-8` y con `LANG=es_ES.UTF-8` (y en los tres sistemas del CI, que corren en inglés
  o en `C.UTF-8`). Controles positivos registrados: sin el fixture de la variable y con
  `LANG=en_US.UTF-8`, fallan los asserts en español; sin el fixture de `locale` y con el navegador en
  `en-US`, fallan los asserts en español del panel.

### Transversal: proceso

- **REQ-035 — Frente A antes que B.** Ninguna ola del frente B se mezcla en `main` antes de que estén
  mezcladas las olas del frente A que tocan `src/` (lo publicado, datos, contrato, CLI y su código
  interno). Las olas de A sobre `tests/` y `scripts/` pueden solaparse con las de B solo si el plan
  les asigna ficheros disjuntos. La única pieza de A programada con B es REQ-010, por su atadura de
  versión con REQ-027.
- **REQ-036 — Uso del MCP `local-delegate` en todas las fases, con registro por ola.** La sesión
  principal y cada agente cargan las tools `local_*` al empezar y delegan los pasos mecánicos
  (ficheros grandes por `path`, salida de tests y lint volcada a fichero, extracción de campos,
  explicación de código, borradores de commit y de traducción es→en, siempre revisados). Cada ola
  deja en la carpeta del cambio un registro (`waves/<ola>.md`, propuesto) con la tabla de llamadas
  `local_*` (tool, para qué, resultado) de la sesión principal y de cada agente; una tabla con 0
  llamadas lleva su motivo. Mínimo comprobable: toda ola que corre la suite pasa su log por
  `local_lint_summary(path=…)`. El gate `conformance` no se limita a que exista el registro de cada
  ola: comprueba los mínimos (la fila de `local_lint_summary` en las olas que corren la suite; las de
  `rename_refactoring` y `get_file_problems` de REQ-037 en las que renombran, o su motivo).
- **REQ-037 — Uso del MCP de PyCharm para buscar y renombrar.** Los agentes de implementación usan las
  tools `mcp__pycharm__*`: `rename_refactoring` para renombrar símbolos de código;
  `search_symbol`, `search_text`, `search_regex`, `get_symbol_info` y `analyze_calls` para localizar
  antes de tocar; `get_file_problems` o `lint_files` para comprobar los ficheros tocados antes de la
  suite. PyCharm es un recurso único: un solo agente a la vez lo usa para renombrar, en el checkout
  principal y en la rama de la ola, y nadie edita en paralelo esos ficheros. El registro de ola de
  REQ-036 lleva también la tabla de llamadas `mcp__pycharm__*`. Mínimo comprobable: toda ola que
  renombra símbolos de Python registra al menos un `rename_refactoring` y un `get_file_problems` sobre
  los ficheros tocados, salvo que PyCharm no responda, y entonces lo dice. Tras cada
  `rename_refactoring`, el diff revisado no toca cadenas que deban conservar el nombre viejo (lectura
  de formato viejo, alias).
- **REQ-038 — Pruebas en vivo dentro de ventanas de prueba.** Toda prueba contra el MCP o el daemon
  reales se hace entre `local-delegate test-window start --label "…"` y `stop <id>`; la verificación
  registra los ids de ventana usados.
- **REQ-039 — Comandos pesados serializados.** Suite, builds, instalaciones y navegador headless se
  lanzan de uno en uno en toda la máquina con el cerrojo `pesado.sh`; la verificación lo registra.
- **REQ-040 — Cada release toca CHANGELOG, README y `docs/wiki/`, y anuncia lo que rompe.** Toda
  versión publicada dentro de este cambio actualiza los tres con los nombres nuevos, los alias
  vigentes y su versión de retirada (en español: la documentación no se traduce). Además:
  - la versión que activa el idioma anuncia el **cambio de idioma por defecto** (quien tenga el
    sistema en inglés pasa a ver en inglés el CLI, `doctor`, las salidas de las tools, los hooks y,
    tras su próximo `install`, la skill y los bloques) y cómo elegir español: ejecutar `install` con
    `LOCAL_DELEGATE_LANG=es` en la sesión, que deja la preferencia para todos los procesos (REQ-047),
    o poner la variable donde se quiera que gane a la preferencia;
  - las versiones que renombran datos anuncian que volver a una versión anterior no está soportado
    (los datos escritos después son invisibles para una 0.34.0);
  - la wiki explica la precedencia del idioma (variable, preferencia, sistema, reserva) y cómo verlo
    (`doctor`, `local_status`).
- **REQ-041 — Fronteras de tramo para las mediciones, por versión.** Quedan registrados como
  frontera de tramo, en un único fichero del repo (`scripts/data/measurement_boundaries.json`,
  propuesto): el cambio de descripciones de tools (REQ-027), el cambio de prompts del modelo local
  (REQ-028) y **cualquier** cambio de texto de los hooks en cualquier idioma (REQ-024). La frontera se
  decide por **versión**, no por fecha, porque los logs de la Mac se miden en la PC y cada máquina se
  actualiza cuando quiere. Para `usage-*.jsonl`, la versión del paquete de cada fila, que sí tiene
  orden: la clave `v`, que toda fila lleva desde F1 (enmienda del 2026-10-14: el `package_version`
  que aquí se proponía habría duplicado ese dato, así que se usa `v` y no se añade clave). Para la
  telemetría, la versión de hook que ya lleva cada evento es un hash del script, sin orden: la
  frontera es un **conjunto**, la lista por script de los hashes que quedan del lado «después»,
  generada en el PR de release a partir de `resources/hooks/`; un test exige que el hash de los
  scripts actuales esté en ese conjunto (si no, se olvidó actualizarlo). Una fila sin versión cuenta siempre como «antes» de la frontera, sin mirar la fecha
  (enmienda del 2026-10-12, revisión del plan ronda 2: con la fecha, una máquina rezagada caería en «después»).
  Lo leen por
  defecto `scripts/medir_adopcion.py` y todo script de medición de calidad del modelo local que
  compare periodos (el plan los enumera tras revisar `scripts/`; si no hay ninguno, lo deja
  escrito), que informan por separado antes y después; sus tests lo comprueban con filas de dos
  máquinas actualizadas en fechas distintas: una fila de `usage-*` con `v` anterior y
  fecha posterior, y un evento de telemetría con un hash viejo y fecha posterior, quedan los dos en
  el tramo de antes.
- **REQ-042 — Formato de línea preservado.** Cada fichero tocado conserva su final de línea (LF o
  CRLF) según `git ls-files --eol`; la verificación compara la lista antes y después.

## Acceptance scenarios

### Escenario: usuario con 0.34.0 que actualiza y usa el comando viejo

- **Given** una instalación 0.34.0 con `LD_HOOK_READ_BLOQUEAR=1` en el bloque `env` de Claude Code,
  la skill `delegacion-local` instalada y cachés `atribucion-*.json` y `coste-agregados.json`
  escritas por la 0.34.0
- **When** actualiza con `update`, ejecuta `local-delegate recalcular-coste` y luego `doctor`
- **Then** el comando hace lo mismo que `recompute-cost`, imprime un aviso que nombra
  `recompute-cost` y la versión de retirada (REQ-001); `attribution-*.json` y `cost-aggregates.json`
  contienen todos los cruces y puntos viejos más los nuevos, y los ficheros viejos siguen intactos
  (REQ-005, REQ-006); el bloqueo de lectura sigue encendido (REQ-002); la skill vieja ya no está y la
  nueva sí (REQ-012); `doctor` muestra un aviso de nombre obsoleto por la variable vieja del `env` de
  `settings.json` (REQ-003).

### Escenario: la Mac sigue escribiendo el formato viejo

- **Given** la Mac con una versión anterior que escribe `usage-*.jsonl`, telemetría y
  `enfriamiento-eventos.jsonl` con claves y valores en español, y esos ficheros copiados a la PC
  junto a los nuevos
- **When** se corren `scripts/medir_adopcion.py` y `scripts/medir_enfriamiento.py` (o sucesores) y
  se abre el panel con ese directorio de logs
- **Then** las filas de los dos formatos cuentan igual que si fueran todas nuevas, el panel muestra
  la etiqueta correcta para cada motivo y causa viejos, y ninguna fila se descarta como
  desconocida (REQ-006, REQ-007, REQ-009).

### Escenario: hooks viejos con un daemon nuevo que enfría un modelo

- **Given** hooks de una versión anterior (que leen `enfriamiento.json`) y el daemon nuevo
- **When** el daemon enfría un modelo
- **Then** el daemon escribe `cooldown.json` y también `enfriamiento.json` en el formato viejo, y el
  hook viejo deja de ofrecer delegar en ese modelo como hoy (REQ-005, excepción).

### Escenario: panel con visitantes en dos idiomas

- **Given** un daemon arrancado con idioma español, y un navegador con idioma `en-US` sin elección
  guardada
- **When** se abre el panel, se cambia el selector a ES y se recarga la página; a la vez, otro
  navegador en `es-ES` abre el mismo panel
- **Then** el primer pintado del navegador en inglés sale entero en inglés con `<html lang="en">`,
  incluidas causas y roles que manda el servidor, aunque el daemon esté en español (REQ-020,
  REQ-025); tras cambiar a ES, todo pasa a español como muy tarde en el siguiente refresco; tras
  recargar, sigue en español; el otro navegador ve español en todo momento (REQ-020); los guardianes
  de longitud pasan en los dos idiomas (REQ-032).

### Escenario: hook en un sistema en inglés

- **Given** un usuario con el sistema en inglés que ejecutó `install` desde su terminal sin
  `LOCAL_DELEGATE_LANG`
- **When** el hook de Read bloquea una lectura grande de prosa
- **Then** `install` dejó `en` en el fichero de preferencia del directorio de datos (REQ-047) y el
  hook lo leyó (REQ-018, paso 2); el motivo que ven el modelo y el usuario está en inglés y en ASCII, el evento de telemetría se escribe con claves
  y valores en inglés, y el hook no ha importado el paquete (REQ-024, REQ-005).

### Escenario: hispanohablante con Windows en inglés

- **Given** Windows con la interfaz en inglés y formato regional `es-ES`, sin `LOCAL_DELEGATE_LANG`
- **When** ejecuta `local-delegate doctor`
- **Then** sale en inglés, `doctor` dice que el idioma viene del sistema, y el CHANGELOG de esa
  versión explica cómo fijar `LOCAL_DELEGATE_LANG=es` (REQ-018, REQ-019, REQ-040).

### Escenario: datos viejos mezclados con nuevos en un mismo fichero

- **Given** un `usage-YYYYMM.jsonl` del mes del cambio con filas anteriores (`bloqueo_id`,
  `fallo_conexion: rechazada`, `error_class: timeout_lectura`) y posteriores con los nombres nuevos
- **When** el panel pide `/api/stats` del mes y `doctor` evalúa el coste
- **Then** los totales, la atribución y las causas son la suma de las dos clases de filas, con la
  misma etiqueta para el valor viejo y su equivalente nuevo (REQ-006).

### Escenario: P-4 a los 90 días

- **Given** `enfriamiento-eventos.jsonl` con eventos desde 2026-09-15 y `cooldown-events.jsonl` con
  los posteriores al cambio, más las ventanas de prueba de `test-windows.json`
- **When** el ~2026-12-14 se ejecuta la medición de enfriamiento con el comando tal como está escrito
  en el procedimiento de P-4
- **Then** el comando funciona sin cambios (REQ-046), el informe cuenta los eventos de los dos
  ficheros, aplica los mismos valores de clase viejos y nuevos y excluye los tramos de prueba igual
  que antes del cambio (REQ-007).

### Escenario: contrato de `local_extract` tras la versión del cambio

- **Given** un cliente MCP que llama a `local_extract` con una entrada que hay que truncar
- **When** recibe la respuesta
- **Then** `_local_delegate` trae `truncated` y `warning` (no `truncado`/`aviso`), la descripción de
  la tool está en inglés y documenta esas claves, y el CHANGELOG de esa versión trae la tabla
  vieja → nueva (REQ-010, REQ-027).

### Escenario: alias que llega a su versión de retirada

- **Given** un alias publicado por primera vez en 0.N y el paquete subido a 0.N+3
- **When** corre la suite
- **Then** el test de horizonte falla y nombra el alias pendiente de retirar (REQ-004).

### Escenario: CI en inglés

- **Given** la suite en un runner con `LANG=C.UTF-8`
- **When** corre entera
- **Then** pasa, porque el fixture fija `es` para los procesos y `locale="es-ES"` para el navegador
  de Playwright, y los tests de inglés y de detección pasan con su propio valor (REQ-043).

### Escenario: daemon de macOS lanzado por `launchd`

- **Given** un Mac con el sistema en español, el daemon arrancado por `launchd` (sin `LANG`) y
  `install` ejecutado desde Terminal
- **When** un cliente MCP llama a `local_status`
- **Then** el daemon responde en español con origen «preferencia», sin consultar `AppleLanguages`
  (REQ-047, REQ-018).

## Edge cases and failure behavior

- **Nombre viejo y nuevo a la vez** (variable u opción): gana el nuevo y se avisa del viejo. Si se
  pasan en el mismo comando la opción vieja y la nueva con valores distintos, el CLI lo rechaza con
  un error en vez de elegir uno en silencio (como hoy `--target` y `--clients`).
- **Hooks viejos con daemon nuevo** (el paquete se actualizó sin `install`/`update`): el daemon lee
  los temporales y la telemetría con los nombres viejos (REQ-006), y sigue escribiendo
  `enfriamiento.json` para ellos (REQ-005, excepción). **Hooks nuevos con daemon viejo** (se
  reinstaló sin reiniciar el daemon): durante esa ventana el daemon viejo no ve los temporales nuevos
  y algunas llamadas quedan sin atribuir; no hay errores. Se acepta, lo documenta el CHANGELOG, y
  `update` reinicia el daemon y cierra la ventana.
- **Hook retirado que no se puede borrar** (p. ej. `anotar_llamada.py` bloqueado en Windows durante
  `install`): si queda y el cliente aún lo invoca, falla sin ruido (sin salida que llegue al modelo ni
  bloqueo de la llamada), aunque el `hook_common` nuevo ya no tenga lo que importaba; `doctor` lo
  señala como fichero de una instalación anterior y el siguiente `install` reintenta borrarlo.
- **Panel abierto durante la actualización:** el JS viejo contra la API nueva deja tarjetas vacías
  hasta recargar; se acepta, sin errores que rompan la página.
- **`test-windows.json`** no sube su `version` en este cambio: una versión desconocida se trata como
  error en daemons viejos (rename §3.12).
- **Idioma no detectable** (vacío, `C`, `POSIX`, `C.UTF-8`, error al consultar): inglés, sin excepción
  ni aviso; `doctor` y `local_status` muestran «reserva» como origen.
- **`LOCAL_DELEGATE_LANG` no válido** (`fr`, `english`): se ignora con aviso en `doctor` (shell) o en
  `local_status` (servidor) (REQ-019).
- **`install` que cambia el idioma con procesos ya en marcha:** los hooks leen la preferencia en cada
  invocación y cambian enseguida; el daemon y los servidores por stdio pueden resolverla al arrancar,
  y entonces cambian al reiniciarse (`update` reinicia el daemon). No es un fallo; `local_status`
  dice el idioma vigente.
- **Procesos con distinto directorio de datos** (`LOCAL_DELEGATE_LOG_DIR` distinto en la shell y en el
  daemon): cada uno lee la preferencia de su directorio; el que no la encuentre sigue al paso del
  sistema. `doctor` y `local_status` muestran el origen y la ruta del `language.json` consultado,
  así que se ve qué directorio leyó cada proceso.
- **Fichero de preferencia ilegible o con valor no válido:** se ignora con aviso y se sigue al
  sistema; nunca impide arrancar.
- **Daemon compartido por PC y Mac:** un solo idioma para todos sus clientes MCP; cada visitante del
  panel ve el suyo (navegador o selector), con independencia del idioma del daemon.
- **Navegador sin idioma declarado:** inglés.
- **Navegador con `localStorage` bloqueado:** el selector funciona durante la visita y vuelve al valor
  inicial al recargar; sin errores en consola.
- **Traducción ausente en tiempo de ejecución** (fallo que los guardianes de REQ-031/045 deberían
  impedir): se muestra el texto en español en vez de una clave o un hueco.
- **Fichero interruptor viejo y nuevo:** basta con que exista cualquiera de los dos para apagar el
  bloqueo mientras viva el alias.
- **Consumidores de `doctor --json`:** los ids nuevos cambian su salida; es un cambio anunciado en el
  CHANGELOG, sin alias de ids.
- **Volver a una versión anterior:** no está soportado; una 0.34.0 no ve lo escrito en los ficheros
  nuevos (`attribution-*`, `cooldown*`, `cost-aggregates`). Los ficheros viejos quedan intactos, así
  que no pierde lo que ya tenía (REQ-040).

## Non-functional requirements

- **Compatibilidad:** Windows, Linux y macOS; sin dependencias nuevas de ejecución. Una dependencia de
  desarrollo (p. ej. `wordfreq` para generar el léxico de REQ-044, o un tokenizador de JS) pasa antes
  la auditoría de Socket (puntuación ≥ 0,7) o se usa sin instalarla en el proyecto.
- **Rendimiento de los hooks:** resolver el idioma en los hooks no añade red, no importa el paquete y
  no lanza procesos.
- **Privacidad:** ninguna evidencia del cambio lleva rutas de usuario, tokens ni contenido de logs; los
  escaneos de datos reales cuentan claves y valores, no contenido.
- **Accesibilidad:** el selector del panel es un control con nombre accesible y estado visible, y
  `<html lang>` refleja el idioma, para que los lectores de pantalla pronuncien bien.
- **Operabilidad:** el usuario ve los nombres obsoletos y el idioma vigente en `doctor` (su shell y
  `settings.json`, y lo que dejan los hooks en la telemetría) y en `local_status` (el proceso
  servidor); todo aviso dice qué hacer.
- **Seguridad:** el cambio de cookie (REQ-012) invalida las sesiones viejas sin aceptar la cookie
  vieja; los textos traducidos que se insertan en el DOM no abren inyección (se insertan como texto o
  escapados, igual que hoy).
- **Calidad del CI:** los avisos de CodeQL que aparezcan se corrigen, no se descartan.

## Non-goals

- Traducir README, `docs/wiki/` o CHANGELOG al inglés (cambio aparte; aquí solo se actualizan en
  español).
- Más idiomas que español e inglés, ni motor de plurales (es y en tienen las mismas dos formas).
- Reescribir, migrar o retraducir datos ya escritos en disco.
- Rediseñar el panel más allá del selector de idioma.
- Cambiar el comportamiento funcional de cualquier tool, hook, métrica o comando (REQ-017), incluido
  el idioma de `local_commit_msg` (REQ-028).
- Traducir comandos, opciones, ids o cualquier otro término de máquina.
- Un idioma por cliente MCP en el daemon compartido.
- La skill subida a mano a Claude Desktop: es un registro aparte que `install` no ve ni toca; queda
  con el nombre y el idioma viejos hasta que el usuario la vuelva a subir.
- Tocar el lanzador del daemon de esta PC u otros ficheros fuera del repo (el alias de REQ-002 cubre la
  variable que pone; cambiarlo es cosa del usuario cuando quiera).

## Traceability

Olas provisionales: las A0–A10 siguen rename §5; las del frente B son una propuesta inicial que fija
el plan (B0 base de idioma y catálogo, B1 CLI y `doctor`, B2 MCP, B3 hooks, B4 panel, B5 `install`,
skill y bloques). Cada ola deja su registro `waves/<ola>.md` (REQ-036/037).

| REQ | Frente / ola prevista | Evidencia esperada |
| --- | --- | --- |
| REQ-001 | A1 CLI y variables | test del alias (mismo resultado, aviso en `stderr` con versión de retirada); captura de `--help` |
| REQ-002 | A1 | test de cada variable vieja/nueva en paquete y en hook instalado; guardián de aislamiento en verde con control positivo |
| REQ-003 | A0 andamiaje + A1 + A2 (hooks) | test del check con variable vieja en la shell y en el `env` de `settings.json`; test de `local_status` con variable vieja en el entorno del servidor; test de hook que escribe `deprecated_names` y de `doctor` que lo lee; fila de la wiki y `test_wiki` en verde |
| REQ-004 | A0 + cada release | test de horizonte con control positivo subiendo la versión; test de versión registrada contra CHANGELOG |
| REQ-005 | A2–A5 | tests de escritura por formato; test de la excepción de `enfriamiento.json` con `entra`, `reentra` y `limpia`; `vendor.json` y sus workflows en verde |
| REQ-006 | A2–A5 | test por formato con filas de los dos formatos y control positivo; tests de arrastre único (segunda corrida sin cambios, caducado que no reaparece, cruce `exacto` conservado, `fuente` traducida antes de juntar) |
| REQ-007 | A4 enfriamiento | test de `medir_enfriamiento` con los dos formatos; corrida real comparada con la anterior |
| REQ-008 | A5 coste y cuota | test con los dos nombres de fichero |
| REQ-009 | A2, A3, A5 (con su productor) | test de paridad node en verde + control positivo; diccionarios JS con valores viejos |
| REQ-010 | B2 (con REQ-027; código de A6) | test de claves y marcadores; entrada del CHANGELOG |
| REQ-011 | A6 | tests de `doctor --json`; `test_checks` con los grupos nuevos; recuento de checks = 25 |
| REQ-012 | A2 (hook, interruptor, temporales), A6 (skill, cookie, subagentes) | test de `install` sobre una instalación 0.34.0 simulada; `install` real en vivo |
| REQ-013 | A0 | test de retirada de skills con skill ajena intacta |
| REQ-014 | A8 resto de `src` (y toda ola que renombre en `src/`) | registro por script (`--help`, corrida mínima o `get_file_problems`); control positivo con `test_reason` |
| REQ-015 | A7–A10 | recuento de tests antes/después |
| REQ-016 | cierre de A y cierre del cambio | dos corridas del detector guardadas: al cierre de A, 0 fuera de la lista y «pendiente» solo con REQ-010; al cierre del cambio, «pendiente» vacía; tests de control en verde en las dos |
| REQ-017 | todas las de A | suite en verde; pasada en vivo de las 11 tools en ventana de prueba |
| REQ-018 | B0 | tests de la función real con entorno, preferencia y API inyectados, un caso por paso (incluido Windows con `LANG` de Git Bash); test de implementación única en `hook_common.py`; guardián de aislamiento ampliado |
| REQ-019 | B0 | tests de la gramática y del aviso; salida de `doctor` y `local_status` con el origen |
| REQ-020 | B4 panel | test Playwright del selector, persistencia, valor inicial según idioma del navegador (`es-*` y `en-US`) y dos visitantes en idiomas distintos contra un mismo daemon |
| REQ-021 | B1 CLI | test de `--help` y de salidas en inglés |
| REQ-022 | B1 | tests de `doctor` en los dos idiomas |
| REQ-023 | B2 MCP | tests de errores, avisos, recibos y `local_status` en inglés |
| REQ-024 | B3 hooks | test de hook instalado en inglés; guardián de no importar el paquete |
| REQ-025 | B4 | test Playwright con el control de catálogo sobre el DOM en inglés y su control positivo |
| REQ-026 | B1, B2, B4 | tests de formato por superficie e idioma |
| REQ-027 | B2 (descripciones, misma versión que REQ-010); B4 (resumen del panel) | test de que las descripciones no cambian con el idioma; resumen del panel desde el catálogo |
| REQ-028 | B2 | tests del prompt por tool; test de que `local_commit_msg` no cambia; muestra en vivo (≥5 documentos por tool e idioma, ≥90 % en el idioma vigente, juzgada por detector) guardada con el id de la ventana; enmienda del 2026-10-14: tests de `LOCAL_DELEGATE_OUTPUT_LANGUAGE` (puesta, vacía, no válida, `commit_msg` intacto) y muestra en vivo con `fr` |
| REQ-029 | B5 | tests de bloque gestionado (0.34.0 → inglés, un solo bloque), de subagentes (encabezado es, en y bloque 0.34.0) y guardián de skills es/en con las mismas tools |
| REQ-030 | B0 | revisión del plan + guardián de REQ-031 cubriendo hooks |
| REQ-031 | B0 | test de paridad con control positivo |
| REQ-032 | B4 + B1 (wiki) | guardianes del panel parametrizados por idioma; `test_wiki` en verde |
| REQ-033 | B2, B4, A5 (`marcas`) | test que muestra prosa vieja tal cual; `marcas` nuevas como valor de máquina |
| REQ-034 | B1–B5 | un test de humo en inglés por superficie |
| REQ-035 | todas | orden de mezcla de los PR |
| REQ-036 | todas | `waves/<ola>.md` con la tabla `local_*`; log de suite pasado por `local_lint_summary`; gate `conformance` comprobando los mínimos |
| REQ-037 | olas de implementación | tabla `mcp__pycharm__*` en `waves/<ola>.md` con el mínimo cumplido o su motivo |
| REQ-038 | verificación en vivo | ids de ventana de prueba en `verification.md` |
| REQ-039 | todas | registro del cerrojo en la verificación |
| REQ-040 | cada release | diff de CHANGELOG, README y `docs/wiki/` en el PR de release, con los anuncios exigidos |
| REQ-041 | B0 (la versión `v` del log, que ya existía desde F1) + B2 (descripciones y prompts) + B3 (hooks) + cada release (conjunto de hashes) | fichero de fronteras por versión y conjunto de hashes; test de que el hash actual está en el conjunto; tests con filas de dos máquinas actualizadas en fechas distintas |
| REQ-042 | todas | `git ls-files --eol` antes/después |
| REQ-043 | B0 (+ B4 para el fixture de Playwright) | suite en verde, Playwright incluido, con `LANG=en_US.UTF-8` y `LANG=es_ES.UTF-8`; controles positivos sin el fixture de variable, sin el de `locale` y con un `language.json` falso en el directorio de datos real simulado |
| REQ-044 | A0 | `scripts/detect_spanish_names.py`, léxico congelado, tests de regresión y de palabras reservadas en verde; auditoría de ≥100 palabras con error ≤ 2 % en `evidence/`; resultado de Socket si hay dependencia |
| REQ-045 | B0 (nace) → B1–B5 (vacían la lista) | guardián con lista de pendientes vacía al cierre de B; lista de excepciones con motivo y su test; control positivo |
| REQ-046 | A10 scripts | corrida del comando documentado de P-4 guardada en la verificación; nota fechada en los SDD cerrados; entrada de retirada en el backlog |
| REQ-047 | B0 (lectura) + B5 (`install`/`update` escriben) | tests de escritura con origen (variable, sistema, reserva nunca escrita), de `uninstall` y de la regla con preferencia frente al sistema; en vivo, `doctor` y `local_status` con el mismo idioma, origen «preferencia» y ruta |

## Preguntas abiertas

Ninguna. Las tres de la primera versión las resolvió la sesión principal el 2026-10-12: orden de
olas (REQ-035), valor inicial del selector por el idioma del navegador (REQ-020, REQ-025) y aviso
de nombres obsoletos repartido entre `doctor`, `local_status` y la telemetría de hooks (REQ-003).
Los hallazgos de las rondas 1, 2 y 3 de la revisión se resolvieron como dicen las respuestas al final
de `review.md`.
