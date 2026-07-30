# Changelog

Todos los cambios notables de este proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

### Added
- **El `doctor` comprueba que `local-delegate` exista como comando.** Toda la documentación manda
  correr `local-delegate <algo>`, pero la instalación recomendada (`uvx local-delegate-mcp
  install`) **no deja ese comando en ninguna parte**: `uvx` monta un entorno efímero y lo borra al
  terminar. El andamiaje quedaba perfecto y el primer comando de la doc respondía «command not
  found». Ahora sale `[FALT]` con el arreglo (`uv tool install local-delegate-mcp`), y el propio
  `install` lo avisa al terminar en vez de dejar que lo descubras.
- **El `doctor` avisa si el daemon sirve una versión distinta de la instalada.** Un daemon es un
  proceso largo: tras actualizar sigue corriendo el código con el que arrancó, y los clientes
  hablan con la versión vieja sin que nada lo diga — el síntoma es «actualicé y el arreglo no
  está». Ahora es `[WARN]` con la comparación explícita.

## [0.14.0] - 2026-07-30

### Fixed
- **El instalador dejaba los hooks rotos en Windows, y con `UserPromptSubmit` eso bloquea todos los
  prompts del usuario.** El comando se registraba como `python C:\Users\...\hook.py` sin comillas;
  Claude Code lo entrega a un shell, que interpreta cada `\` como escape y lo borra, así que al
  intérprete le llegaba `C:UsersYohan.claudehooks...` y el hook moría con «can't open file». Ahora
  la ruta va **siempre entre comillas y con barras `/`** —Python las acepta en Windows—, que
  funciona en sh, cmd y PowerShell. Si te pasó: borra las entradas de local-delegate de
  `~/.claude/settings.json` y reinstala con esta versión.
- **`doctor` daba por CAÍDO un backend vivo que respondía 401.** Ahora distingue «no responde» de
  «responde 401/403 — está arriba y falta la credencial en este entorno», que se reporta `[ -- ]`
  en vez de mandarte a arrancar un servicio que ya está corriendo.

### Added
- **`doctor` ve por fin el sistema entero, no solo el backend.** Nace un registro único de
  comprobaciones (`checks.py`) con las **once** piezas del andamiaje —clientes, hooks copiados,
  hooks registrados, skill, memoria, entradas MCP de Claude y Codex, daemon, `/models` y las dos
  versiones del backend—, cada una con un `probe` **sin efectos**. Hasta ahora cada subcomando
  sabía un pedazo: `doctor` solo miraba el backend, `install` escribía sin verificar y nadie
  miraba el daemon. Cuatro estados (`[ OK ]`, `[WARN]`, `[FALT]`, `[ -- ]`) y, cuando algo falta,
  la línea de abajo dice qué comando lo arregla. Nuevo flag `--home DIR` para diagnosticar contra
  un HOME simulado.
- **Lo que no se pudo comprobar sale `[ -- ]`, nunca «falta».** Un cliente que no está instalado o
  un archivo sin permisos no son una ausencia: reportarlos como falta llevaría a que un arreglo
  automático sobrescribiera configuración ajena. `[ -- ]` no cuenta para el exit code, que
  conserva su semántica de siempre (0 sin avisos, 1 con al menos uno).
- **El dashboard mide ahora el coste, no solo el ahorro.** Nuevo KPI **Coste local** con los tokens
  de entrada que consumió de verdad el backend sumando **todas** las llamadas, y el KPI de
  delegaciones muestra al lado las **llamadas reales al backend**. Hasta ahora N llamadas se
  registraban como un evento y el panel no distinguía una delegación resuelta en una llamada de una
  que quemó la GPU dieciséis veces: el dato (`chunks`, `tokens_in`) ya estaba en el log y nadie lo
  leía. `/api/stats` expone `backend_calls`, `tokens_local_input` y `estimated_events`.

### Changed
- **Las cuentas usan el token real que reporta el backend**, no la estimación `chars ÷ 4`, que ahora
  es solo el respaldo para cuando el backend no da `usage`. El panel indica cuántos eventos del rango
  hubo que estimar. Medido sobre un log real, la estimación se desviaba entre **+8 %** y **+613 %**
  según la tool.
- **Los KPIs se sirven de `/api/stats` en vez de recalcularse en el navegador**: una sola
  implementación de la contabilidad. De paso cierra una incoherencia latente — el panel los sumaba
  sobre la lista de eventos **topada a 5000** mientras mostraba al lado el total real, así que en
  rangos grandes **subestimaba**.
- El **ahorro de contexto no cambia de definición** para texto: sigue siendo el contenido leído
  server-side contado **una vez** aunque se trocee. El trabajo extra de trocear lo paga la GPU, no
  el contexto de Claude, y por eso vive en el KPI de coste.

### Fixed
- **`local_describe_image` inflaba el ahorro ×46.** Su `chars_in` son **bytes de la imagen**, y el
  dashboard los dividía entre 4 como si fueran caracteres de texto: un solo PNG aportaba más ahorro
  fantasma que todo el resto del log junto. El evento declara ahora `input_unit: "bytes"` y esos
  casos se contabilizan con el token real. **El KPI «Contexto conservado» bajará** al aplicarse la
  corrección: es el arreglo de un defecto, no una regresión.

## [0.13.1] - 2026-07-29

### Changed
- **El panel «En curso» del dashboard ya no se queda en blanco cuando no hay nada corriendo:**
  enseña la **última delegación terminada** con cuánto hace, su tool, su modelo, su duración y el
  tamaño de la entrada, y el contador sube en vivo. Antes solo mostraba lo que se estaba
  ejecutando **en ese instante**, y como una tarea mecánica dura 2-4 segundos, el panel estaba
  vacío casi siempre: se delegaba, terminaba, y quien miraba el dashboard un momento después no
  veía **nada** — parecía que no había pasado. Se comprobó grabando el DOM durante una delegación
  real de 3,4 s. (El refresco al volver a la pestaña ya existía; el problema no era ese.)

### Fixed
- **`local_extract` con `path` devolvía siempre un error en vez de los datos.** La línea de ahorro
  («leído server-side: N chars…») se anexaba al texto del resultado, y como esta tool **parsea** su
  salida, ese sufijo convertía un JSON perfecto en uno imparseable: la respuesta acababa siendo
  `{"_local_delegate": {"error": "respuesta no parseable como JSON", …}}`. Afectaba justo al modo
  que ahorra contexto —el que vale la pena usar— y no al de `text`, que es por donde pasaban
  **todos** los tests de esa tool; de ahí que nadie lo viera. El dato de ahorro no se pierde: pasa a
  `_local_delegate.leido_server_side`, que es donde va lo que no son datos. Se apareció usando el
  propio MCP para revisar esta documentación.

### Changed
- **Revisión completa del README y la wiki.** Lo que estaba mal: el README recomendaba fijar
  `local-delegate-mcp==0.11.0` para el rollout remoto, y ese consejo hoy **rompe la instalación**
  —las versiones anteriores a la 0.12.2 piden `mcp` sin techo y mueren con el SDK 2.x—; había dos
  párrafos seguidos explicando lo mismo del map-reduce; la tabla de versiones probadas seguía en
  0.11.0; los ejemplos de configuración remota fijaban esa misma versión; y dos links internos
  estaban rotos. Lo que faltaba: Python 3.11+ en los requisitos, el subcomando `benchmark` —que no
  estaba documentado en ninguna parte—, y en *Troubleshooting* los tres fallos que este proyecto sí
  ha tenido (`Connection closed` por un major de dependencia y dónde está el traceback de verdad,
  el `421` del SDK 2.x fuera de loopback, y el dashboard enseñando gráficos viejos por la caché de
  24 h). *Publishing* recoge ahora `bump_version.py`, el CI completo con `install-smoke` y
  `vendor-audit`, y el paso de regenerar la captura del README.

## [0.13.0] - 2026-07-29

### Changed
- **Migración al SDK `mcp` 2.x.** El import pasa de `mcp.server.fastmcp.FastMCP` a
  `mcp.server.mcpserver.MCPServer`, y el daemon fija la ruta del MCP con
  `streamable_http_app(streamable_http_path=…)` porque el major sacó los campos de transporte de
  `Settings`. Las 11 tools conservan nombre, firma y salida: **la equivalencia es el criterio de
  éxito**, así que esta entrega no añade ninguna capacidad de las que 2.x trae. El techo se sube a
  `mcp>=2,<3` en vez de quitarse: la lección de la 0.12.1 fue que un rango sin techo es una bomba
  de tiempo, no que ese techo concreto sobrara.
- **Una sola librería HTTP: `httpx` sale y entra `httpx2`.** El SDK 2.x usa `httpx2`, y mantener el
  cliente propio en `httpx` habría dejado las dos instaladas para siempre. `httpx2` es de pydantic
  y marca 100 en las cinco dimensiones de Socket. Como efecto colateral, `respx` sale de las
  dependencias de desarrollo —declara `httpx>=0.25.0` y no soporta `httpx2`—: su sitio lo ocupa
  `tests/backend_mock.py`, construido sobre `httpx2.MockTransport`. Los 233 tests siguen ahí.

- **`local_extract` devuelve un objeto validado, no una cadena con JSON dentro.** Quien llamaba
  tenía que hacer un `json.loads` del resultado —y antes limpiar el aviso de truncamiento, que iba
  como texto **delante** del JSON y lo hacía imparseable—. Ahora las claves son exactamente las
  pedidas, y los dos casos que no son datos viajan bajo la clave reservada `_local_delegate`:
  `{"truncado": true, "aviso": …}` cuando hubo que recortar la entrada, y `{"error": …, "crudo": …}`
  cuando el modelo no devolvió JSON o el backend falló. **Cambio de contrato**: quien parseara la
  salida a mano debe quitar ese paso. Los clientes que no leen salida estructurada siguen recibiendo
  el JSON como texto, así que para ellos no cambia nada.
- **Las 11 tools se declaran como de solo lectura y de dominio cerrado** (`annotations`), y el
  servidor se presenta con `title`, `description` y `website_url`. Las anotaciones son las mismas
  para todas porque todas son de la misma naturaleza: ninguna toca los datos de quien llama —el log
  de uso es contabilidad interna del servidor— y ninguna sale a un mundo abierto, solo al endpoint
  configurado y a los archivos bajo las raíces permitidas.

### Fixed
- **El handshake ya dice qué versión de `local-delegate` corre.** `serverInfo.version` reportaba la
  versión **del SDK**, de modo que un `initialize` no servía para saber qué versión del paquete
  había enfrente. Ahora el server la declara con el `version=` que acepta `MCPServer`.

## [0.12.4] - 2026-07-29

### Changed
- **Chart.js sube de 4.4.1 a 4.5.1**, dos minors de atraso que el vigilante nuevo sacó a la luz en
  su primera corrida. Es el estreno del proceso, y funcionó de punta a punta: el aviso lo dio el CI,
  la copia se bajó del **tarball oficial de npm** —no de un CDN— y se verificó byte a byte, OSV no
  conoce vulnerabilidades para 4.5.1, y el dashboard se comprobó a ojo antes y después (mismos seis
  gráficos, cero errores de consola). Se actualiza también `chart.js-LICENSE.md`: sigue siendo MIT,
  cambia el rango de años del copyright.
  De paso caen **dos sitios que todavía clavaban la versión a mano** —un assert de
  `tests/test_metrics.py` y los tests de versión del vigilante—, que ahora la leen del manifiesto.
  Era exactamente el problema que `vendor.json` vino a resolver, y solo se ve cuando actualizas.

### Added
- **El JavaScript vendorizado deja de estar sin vigilancia.** `resources/vendor/` son 205 KB de
  Chart.js que ninguna herramienta miraba: Dependabot solo ve manifiestos, CodeQL analiza el
  Python y Socket cubre dependencias declaradas. No había ni un hash registrado, así que un cambio
  en ese fichero no dejaba rastro y un CVE publicado mañana no avisaba a nadie. Ahora hay un
  manifiesto (`resources/vendor/vendor.json`, que viaja en el wheel y es la **fuente de verdad de
  la versión**), un `scripts/check_vendor.py` de **solo stdlib** y un workflow propio
  `vendor-audit.yml` que corre en cada PR y en un cron semanal —los CVE se publican cuando les
  toca, no cuando hay PRs—. **Rompen el CI** un hash que no cuadra y una vulnerabilidad confirmada
  por OSV.dev; **solo avisan** que exista una versión más nueva y que OSV o npm no respondan: un CI
  que se pone rojo porque alguien publicó algo, o porque un servicio ajeno está caído, se acaba
  ignorando. El manifiesto documenta además la trampa que hace perder una tarde a quien verifique
  a mano: jsDelivr antepone a veces un banner propio de 274 bytes, así que comparar el hash contra
  su URL puede dar distinto sin que nada esté adulterado. Nada de esto entra en el runtime del
  paquete. El vigilante se estrenó con 4.4.1 —una versión de estado conocido— y su primer encargo
  fue subirla, que es el cambio de arriba.

### Fixed
- **`scripts/bump_version.py` se caía en la consola de Windows.** Imprime un `→` para marcar qué
  archivos cambia, y en una consola cp1252 —lo normal en Windows— eso es un `UnicodeEncodeError`
  que aborta el bump. Se descubrió preparando esta misma versión. Falla imprimiendo y no
  escribiendo, así que nunca dejó un bump a medias, pero un release que se cae con un traceback de
  codificación invita a hacer el bump a mano, que es justo lo que ese script existe para evitar.
- **`.gitattributes` impide que git normalice los finales de línea del contenido vendorizado.** Con
  `core.autocrlf=true` —el valor por defecto de Git for Windows— el checkout convertía los LF del
  blob de Chart.js en CRLF: 205 139 bytes en vez de 205 125. Un wheel construido en esa máquina
  llevaría un JavaScript distinto del que se publica desde Linux, y la comprobación de integridad
  nueva fallaría en cualquier clon de Windows sin que nadie hubiera tocado nada.

## [0.12.3] - 2026-07-29

### Changed
- **`platformdirs` y `filelock` quedan acotadas por debajo del major siguiente** (`<5` y `<4`). Para
  quien instala, el efecto es solo futuro: cuando salga `platformdirs` 5 o `filelock` 4, una
  instalación nueva se quedará en la serie que el proyecto probó en vez de saltar a ciegas. Ninguna
  instalación existente cambia de resolución, porque los techos van por encima de lo que ya se usa.
  Es la misma lección de la 0.12.1, generalizada: el wheel publicado es inmutable y resuelve libre
  **para siempre**, así que `install-smoke` —que corre cuando corre el CI— no puede cubrir un major
  que salga después del release; el techo, que viaja dentro del wheel, sí.
  `fastapi`, `uvicorn` y `httpx` **no** llevan techo, y el porqué de cada una está junto a su línea
  en `pyproject.toml`. El criterio completo, con su alcance y su coste, está en
  `docs/wiki/Repo-hardening.md`.

### Added
- **`scripts/release.py`: un comando para todo el release.** Construye, crea la GitHub Release con
  las notas sacadas de la sección del `CHANGELOG.md`, le adjunta wheel y sdist, y crea el tag que
  dispara `publish.yml`. Antes el tag se hacía a mano y dejaba fuera dos pasos que había que
  recordar cada vez —adjuntar los artefactos y crear la Release, que el workflow **no** crea—; en
  la 0.12.2 se olvidaron los dos. Aborta antes de tocar nada remoto si la versión no está en los
  tres archivos, si `main` no está sincronizada con el remoto, o si el tag o la release ya existen:
  **PyPI es inmutable** y publicar mal no se deshace. Tiene `--dry-run`.

## [0.12.2] - 2026-07-28

### Fixed
- **El paquete dejó de arrancar con el SDK `mcp` 2.0.0.** El SDK publicó un major que elimina
  `mcp.server.fastmcp` (el módulo pasó a `mcp.server.mcpserver`), y `local-delegate-mcp` declaraba
  `mcp>=1.2` **sin techo**: `uvx` resolvía al major nuevo y el proceso moría en el import antes de
  poder hablar MCP. El cliente solo enseña `MCP error -32000: Connection closed`, que es el
  síntoma del proceso muerto, no la causa — **el traceback real está en el `Server stderr`** del
  log del cliente (en macOS, `~/Library/Caches/claude-cli-nodejs/<proyecto>/mcp-logs-local-delegate/`).
  Afectaba a **toda instalación nueva** de la 0.12.1 en cualquier sistema. La dependencia queda
  acotada a `mcp>=1.2,<2`; migrar a la API 2.x es un cambio aparte. Quien aplicara el workaround
  `--with "mcp<2"` puede retirarlo, pero no está obligado.

### Added
- **Job `install-smoke` en el CI: el paquete construido se instala con resolución libre y se le
  exige un handshake MCP real.** Es el único job que **no** usa `uv.lock`, y esa es su razón de
  ser: el lock fija versiones buenas conocidas y por eso el CI estuvo verde mientras el paquete
  publicado estaba roto para todo el mundo. Instala con `--refresh` y `--resolution highest`
  porque un entorno limpio no implica caché limpia, y un check que no puede fallar no vigila nada.
  Cubre también al resto de dependencias: si cualquiera publica un major que rompa el import, este
  job lo detecta antes que un usuario.
- `scripts/check_install_handshake.py`, que hace esa comprobación y devuelve códigos de salida
  distintos para un fallo de import (regresión de dependencia) y uno de red o de arranque.
- **`setup_repo_security.sh` sirve para cualquier repositorio.** Los checks requeridos dejan de
  estar hardcodeados: `--checks "a|b|c"` (separador `|`, porque los nombres de job llevan comas y
  paréntesis) o `--check` repetible, y `--no-code-scanning` para repos sin CodeQL, donde exigir
  esa regla bloquearía los PR. Antes de aplicar **comprueba que alguien reporta cada check** y
  aborta si no: exigir uno que nadie publica deja todos los PR esperando para siempre. La
  comprobación mira la rama por defecto y el PR más reciente, y consulta *check-runs* **y**
  *commit statuses* — Actions publica lo primero, integraciones como Vercel lo segundo, y
  mirando solo check-runs `Vercel` parecía no existir.

### Changed
- `scripts/setup_repo_security.sh` protege **`~DEFAULT_BRANCH`** en vez de la rama literal —la
  regla sigue a la rama por defecto y no se queda protegiendo un nombre viejo si se renombra— y
  añade la regla **`code_scanning`**: que el job de CodeQL termine en verde no basta, puede acabar
  bien habiendo encontrado una alerta. Las dos mejoras vienen de comparar con el ruleset que ya
  tenía `angular-template-project`, al alinear los tres repos.

## [0.12.1] - 2026-07-27

### Fixed
- **Los estados vacíos del dashboard usaban otra tipografía.** `.empty` no declaraba
  `font-family`, así que heredaba la sans del `body` mientras todo su entorno —nombres de
  modelo, badges, chips, tabla, pie— va en monoespaciada. Se veía sobre todo en «sin datos
  (requiere llama-swap ≥ v236)», y el mismo panel llegaba a enseñar **dos** estados vacíos con
  tipografías distintas, porque el de tools usa `.tchip`, que sí la declara. Afectaba a los
  ocho estados vacíos del panel.

### Added
- **`scripts/update_to_latest.sh`**: pone este cliente en la última versión publicada. Pensado
  para la máquina que usa `uvx` con la versión fijada —la Mac que apunta al backend de la PC—,
  donde cada release obligaba a editar el pin a mano en `~/.claude.json` y `~/.codex/config.toml`.
  Consulta PyPI, cambia **solo** el número de versión (con copia `.bak`), precarga la caché de
  `uvx` y comprueba que arranca. Idempotente, con `--dry-run`, y no toca la API key ni ninguna
  otra entrada MCP. Si no hay pin, lo dice y no toca nada: `uvx` ya resuelve la última.

## [0.12.0] - 2026-07-27

### Added
- **`local_summarize` y `local_lint_summary` ya no truncan la entrada: hacen map-reduce.** Un
  documento que no cabe en el modelo se resume por partes y luego se resumen los resúmenes,
  jerárquicamente si hace falta (tope de 3 niveles). Antes se cortaba en
  `max_chars_for(modelo)` con un aviso, o sea que se resumía el principio y el resto se
  descartaba — en un log de CI eso significa perderse justo los errores del final, que suelen
  ser los que importan. El chunking de la 0.11.0 resolvía el caso de *transformar* (traducir,
  reescribir), donde concatenar las salidas es correcto; *reducir* pide otro diseño. Como allí:
  N llamadas, **un** evento de log con `chunks: N` y el progreso visible en «En curso».
  Verificado con un documento de 145.584 caracteres, procesado entero en 16 pasadas.

### Changed
- La documentación del backend remoto fija ya **0.11.0** en vez de 0.10.0: el rollout controlado
  de la Mac pasa a la versión vigente.
- **El CI corre los tests en Linux, Windows y macOS.** El paquete es multiplataforma de verdad
  —rutas, locks entre procesos y llamadas a Win32 por ctypes— y hasta ahora solo se probaba en
  Ubuntu: la fuga de handles que arregló la 0.11.0 era **exclusiva de Windows** y ningún job
  podía verla. El lint, el formato y la validación del JS siguen corriendo una sola vez, en un
  job aparte, porque su veredicto no depende del sistema.

### Added
- **`scripts/dev/`**: los bancos de prueba que la suite automática no cubre — un backend
  OpenAI-compatible falso y lento (para ver el panel «En curso» de verdad y ejercitar el
  chunking sin GPU), un comprobador del dashboard con la zona horaria forzada vía Playwright, y
  el procedimiento del instalador contra un HOME simulado. Se habían montado durante el
  desarrollo de la 0.11.0 y se perdieron al cerrar la sesión; reconstruir un banco de pruebas
  es la forma más fiable de acabar no verificando nada.

### Fixed
- **El instalador reescribía entero el `CLAUDE.md` del usuario en Windows.** `write_text` usa el
  terminador de línea de la plataforma, así que añadir el bloque de la regla de delegación a un
  archivo guardado en LF lo convertía a CRLF: el diff salía completo en rojo y, en un archivo
  compartido entre una Mac y un Windows, generaba conflictos. Ahora se escribe con el
  terminador que el archivo ya tenía, y `uninstall` vuelve a dejarlo **byte a byte** como
  estaba (verificado en Windows, no solo en Linux). Afectaba también a `settings.json` y al
  `config.toml` de Codex.
- Los archivos con `#!` (los tres hooks empaquetados y `scripts/bump_version.py`) no tenían el
  bit de ejecución en git. Solo se nota en sistemas POSIX —en Windows ese bit no existe, así
  que un `ruff check` local no puede verlo— y rompía el lint del CI.
- **ruff 0.16.0** (solo desarrollo). Promueve a estables reglas que sacaban 79 avisos en código
  hoy limpio; se aplican los arreglos que son mejora real (`datetime.UTC`, `re.MULTILINE`,
  `removeprefix`, `typing.Self` en los `__enter__`, `fromisoformat` sin el reemplazo de `Z` que
  3.11 ya no necesita) y se **ignoran con su motivo** las que chocan con decisiones deliberadas:
  `BLE001`/`S110` (diagnóstico, sysinfo e instalador son best-effort y nunca deben lanzar) y
  `PLW1510` (`subprocess.run` comprueba el returncode a mano para dar un mensaje propio). El
  formateador excluye los `.md`: 0.16 formatea los bloques Python embebidos y reescribía
  documentación histórica.

### Fixed
- **El origen del cómputo mentía detrás de un túnel.** `backend_origin()` clasifica por el host
  de `BASE_URL`, así que un `ssh -L 9292:…` o un port-forward de Tailscale —el backend remoto
  visto en `127.0.0.1`— se reportaba como **cómputo local**, justo en la topología Mac→PC que el
  proyecto recomienda. Un túnel es transparente por diseño y no hay forma fiable de detectarlo,
  así que se añade `LOCAL_DELEGATE_BACKEND_ORIGIN=local|remote` para declararlo; `auto` (el
  default) mantiene la heurística de siempre y un valor inválido cae a `auto` en vez de romper
  el arranque.

## [0.11.0] - 2026-07-27

### Added
- **Publicación automática en el registro oficial de MCP.** El tag `vX.Y.Z` ya publicaba en PyPI;
  ahora encadena un job que publica también `server.json` con `mcp-publisher login github-oidc`
  (sin secretos: el registro valida el namespace contra el token OIDC del workflow). Antes de
  tocar nada se comprueba que el tag, `pyproject.toml` y **las dos** versiones de `server.json`
  coinciden, y antes de publicar el descriptor se espera a que PyPI sirva la versión — el
  registro valida que el paquete exista. La coherencia de versiones se comprueba además en cada
  PR (`tests/test_release_metadata.py`).
- **`scripts/bump_version.py`:** sube la versión en los **cuatro** sitios donde vive
  (`pyproject.toml`, las dos de `server.json` y `uv.lock`) de una sola vez, y regenera el lock.
  Los guardarraíles anteriores solo *detectan* un bump a medias —y el histórico dice que pasa:
  en la 0.8.1 el lock se quedó en 0.7.0—; este lo evita. `--check` verifica la coherencia en
  local antes del push (incluido `uv.lock`, que ningún test miraba), `--dry-run` enseña el plan.
  Edita el texto en vez de reserializar, así el diff son cuatro líneas y no un reformateo.
- **`local-delegate install` / `uninstall`:** la instalación deja de ser solo el servidor MCP.
  Un comando registra la entrada MCP (Claude Code y Codex), copia los hooks consultivos a
  `~/.claude/hooks/local-delegate/` y los inscribe en `settings.json`, instala la skill
  `delegacion-local` y escribe un bloque gestionado con la regla de delegación en
  `~/.claude/CLAUDE.md` y `~/.codex/AGENTS.md`. Idempotente (marcadores `begin/end`, hooks
  desregistrados antes de reinscribirse), con `--dry-run`, backups `.bak`, exclusión por
  componente (`--no-hooks`/`--no-skill`/`--no-memory`/`--no-mcp`) y reversión completa. Los
  hooks, la skill y el bloque de memoria ahora viajan **dentro del paquete**
  (`src/local_delegate/resources/`).
- **Chunking de salida** en `local_translate` y `local_delegate`: las entradas largas se parten
  por límites naturales (headers Markdown → párrafos → líneas → corte duro) y se procesa un
  trozo por llamada respetando `max_tokens`, concatenando en orden y reponiendo el separador
  original en cada costura. Un documento de 20 000+ caracteres vuelve **completo** en vez de
  cortado con `[salida truncada]`; si un trozo aun así trunca, se vuelve a partir y se
  reintenta. La operación se registra como **un** evento con `chunks: N` y el panel "En curso"
  muestra el progreso `trozo i/N`. Configurable con `LOCAL_DELEGATE_CHUNK_CHARS`,
  `_CHUNK_MAX_TOKENS` y `_CHUNK_MIN_CHARS`; `local_delegate` acepta `chunk='auto'|'on'|'off'`.
- **Origen del cómputo en el log y el dashboard:** cada evento registra `backend`
  (`local`/`remote`, por el host del endpoint) y `backend_host`. El dashboard lo muestra en un
  donut nuevo, una insignia en el panel de backend, una columna en la actividad y agregados en
  `/api/stats`, así se distingue lo generado por el backend de esta máquina de lo generado con
  la GPU de otra (p. ej. la Mac usando la PC). Los eventos previos se muestran como `n/d`, no
  como locales. `local_status` también lo reporta.

### Security
- El repositorio incorpora CodeQL, Dependabot (dependencias y actions), `SECURITY.md` con canal
  privado de reporte, `CODEOWNERS` y `permissions:` de mínimo privilegio en los workflows.
  `scripts/setup_repo_security.sh` aplica de una vez lo que no puede versionarse: regla sobre
  `main` (PR obligatorio, CI en verde, sin force-push ni borrado), secret scanning con push
  protection, alertas de Dependabot y private vulnerability reporting.

### Changed
- **Chart.js se sirve desde el propio paquete** (`/vendor/chart.umd.min.js`) en vez de un CDN:
  el dashboard de una herramienta local-first ahora funciona sin conexión y no anuncia a un
  tercero que estás mirando tus métricas. La tipografía de marca queda como único recurso
  externo, es cosmética y se desactiva con `LOCAL_DELEGATE_WEB_FONTS=0`.
- El dashboard trabaja en la **zona horaria del equipo**: "Hoy" empieza a tu medianoche, las
  barras agrupan por tu día natural, el rango personalizado interpreta las fechas como locales
  y la tabla muestra tu hora (antes todo se calculaba en UTC, así que las delegaciones de la
  tarde/noche caían en el día equivocado o quedaban fuera de "Hoy"). El log sigue en UTC.
- El indicador de actividad tiene tres estados —`EN CURSO`, `EN VIVO`, `EN REPOSO`— y ya no
  depende del rango elegido ni del auto-refresco: se apoya en las delegaciones vivas y en el
  último evento de todo el histórico, se repinta cada segundo y descuenta el desfase entre el
  reloj del navegador y el del servidor. Los sondeos se refrescan al volver a la pestaña.
- `local_delegate` sube su techo de salida de 1024 a 2048 tokens.

### Fixed
- **Delegaciones en curso perdidas o fantasma:** `inflight.json` se publicaba a través de un
  temporal de nombre **fijo**, así que dos procesos MCP escribiendo a la vez (varias sesiones
  `stdio`, o una sesión y el daemon) se pisaban el temporal. Ahora el temporal lleva el pid.
- El sondeo del panel reescribía `inflight.json` cada 2 s aunque no hubiera cambios,
  compitiendo por el lock con las delegaciones reales; ahora solo se escribe si algo cambió y
  el sondeo nunca escribe sin el lock (una entrada recién registrada por otro proceso ya no
  puede perderse).
- Los hooks documentados usaban `{"type":"command","command":"python","args":[…]}`, formato que
  Claude Code no soporta: quedaban registrados pero **nunca ejecutaban** el script. El
  instalador y la recipe usan un único string de comando, y `install` **retira las entradas
  heredadas** de ese formato en vez de dejarlas como duplicados inertes.
- Si Chart.js no cargaba, el `Chart.register(...)` inicial abortaba el script del dashboard y se
  llevaba por delante KPIs, tabla, panel de backend e indicador de actividad. Ahora degrada a
  "sin gráficos" (además de servirse en local, con lo que el caso es ya improbable).
- `_pid_alive` en Windows llamaba a `OpenProcess` sin `restype`/`argtypes`, con lo que ctypes
  truncaba el HANDLE de 64 bits y `CloseHandle` recibía un handle inválido: el daemon filtraba
  un handle por cada sondeo del dashboard.

## [0.10.0] - 2026-07-23

### Added
- Topología remota recomendada **MCP local en Mac → backend llama-swap en PC**, con recipe de
  Tailscale Serve/HTTPS privado, Keychain/DPAPI, configuración de Claude Code y canary automatizado
  de 20 llamadas que valida auth, concurrencia, reinicio y un `path` exclusivo de macOS.
- `local-delegate benchmark`: runner reproducible para comparar modelos densos/MoE, contexto y
  offload sin promover automáticamente modelos al catálogo estable.
- `UserPromptSubmit` consultivo para intenciones mecánicas explícitas y telemetría metadata-only;
  suite A/B versionada para medir adopción y falsos positivos.
- `doctor --online` reporta edad de releases, compuerta de 7 días y hasta tres issues recientes con
  señales de crash/deadlock/regresión antes de recomendar un canary.

### Changed
- `LOCAL_DELEGATE_API_KEY` se aplica también a `/models`, `/running`, métricas del backend,
  autostart, doctor y benchmark; antes solo protegía `/chat/completions`.
- El piloto de hooks subió la adopción de 5/6 a 6/6 (+20% relativo). `UserPromptSubmit` y el flujo
  de lint quedan recomendados; `PreToolUse/Read` queda experimental y apagado por defecto porque
  avisó en 2/4 tareas negativas.
- Las versiones estables recomendadas continúan en llama-swap v238 y llama-server b9925: las
  releases más nuevas siguen en `HOLD` hasta cumplir soak y canary.

### Fixed
- La suite aísla `LOG_DIR`/`USAGE_LOG` por test para no contaminar la telemetría real del usuario
  con llamadas de fixtures.
- El sdist excluye configuración local de agentes (`.codex`), evidencia interna SDD, entornos y
  builds previos; esos directorios podían colarse aunque no estuvieran trackeados por Git.

## [0.9.0] - 2026-07-23

### Added
- **Daemon singleton HTTP:** `local-delegate serve` publica MCP Streamable HTTP en `/mcp` y el
  dashboard en `/` usando un único proceso persistente y un único puerto (default
  `127.0.0.1:9393`). Un lock por usuario evita daemons duplicados; `/api/daemon` expone estado,
  PID y URLs para diagnóstico. El transporte `stdio` sin argumentos se conserva compatible.

### Changed
- `check-llamaswap` e `init-llamaswap` rechazan por defecto modelos fuera de todos los `groups`,
  porque quedarían fuera del presupuesto de VRAM/RAM. `--allow-ungrouped` permite la exclusión
  deliberada con un aviso explícito.
- El autoarranque acepta `LLAMASWAP_WATCH_CONFIG=1` para añadir `-watch-config` cuando existe
  `LLAMASWAP_CONFIG`, evitando reinicios manuales en cambios futuros del catálogo o los grupos.
- Backpressure configurable con `LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS` (default `2`). En el
  daemon singleton el límite se comparte entre todos los clientes HTTP.

### Fixed
- El daemon puede ejecutarse con `pythonw.exe` en Windows sin consola visible: si el runtime no
  define `stdout`/`stderr`, usa `NUL` para que Uvicorn inicialice su logging sin fallar.
- El dashboard identifica el proceso servidor compartido como `DAEMON MCP`, evitando confundirlo
  con un proceso nuevo por cada sesión cliente.

## [0.8.1] - 2026-07-11

### Fixed
- Dashboard, panel «Backend local»: el estado **montado/loaded** de un modelo tardaba hasta 60 s
  en reflejarse porque el status loaded/unloaded (#901) solo se refrescaba vía `/api/status` (cada
  60 s). Ahora `GET /api/backend` incluye también `models: [{id, status}]` y el poll rápido (2 s) lo
  mantiene fresco, así un modelo recién cargado se marca «montado» casi al instante.
- Dashboard, panel «Backend local»: la columna de estado («frío»/«montado») no quedaba alineada
  entre filas — `.mstate` y `.mstatus` tenían ambos `margin-left:auto`, así que flexbox repartía el
  hueco y la posición dependía del ancho (variable) del badge de rol. Ahora la columna de estado y el
  badge tienen ancho fijo y se alinean en todas las filas.

## [0.8.0] - 2026-07-11

### Added
- **`local-delegate doctor`**: nuevo subcomando (opt-in, junto a `check-llamaswap`/
  `init-llamaswap`) que diagnostica la instalación del backend local. Detecta las versiones
  instaladas de `llama-server` (desde el `cmd` del `config.yaml`, con lectura de texto — funciona
  sin el extra `[llamaswap]`) y `llama-swap` (vía `LLAMASWAP_EXE` o el PATH), comprueba si el
  backend responde, y las compara contra las versiones probadas de esta release
  (`RECOMMENDED_VERSIONS` en `doctor.py`). Con `--online` consulta además la última release
  publicada en GitHub. Exit code `1` si hay actualizaciones sugeridas. Nuevo módulo `doctor.py`.
- Dashboard: panel **«Rendimiento del backend»** que muestra las métricas de actividad que
  llama-swap ≥ v236 persiste en SQLite (#898) — total de requests, tokens in/out, y percentiles
  (p50/p95) de tokens/segundo de generación y de prompt. Nuevo endpoint proxy
  `GET /api/backend/stats` (best-effort sobre `/api/metrics/stats` de llama-swap; degrada a «sin
  datos» con otro backend o una versión vieja).
- `init-llamaswap --store-path`: escribe `store.path` en el `config.yaml` para que las métricas
  de #898 sobrevivan a los reinicios de llama-swap (sin ella son in-memory).
- Nueva página de wiki **[Backend versions](docs/wiki/Backend-versions.md)**: versiones probadas
  de llama-server/llama-swap (b9925 / v238), estructura de workspace de referencia y guía de
  `local-delegate doctor`.

### Changed
- Dashboard y `local_status`: los modelos del backend ahora muestran su estado **loaded/unloaded**
  a partir del campo `status` de `/v1/models` (#901 de llama-swap, que lo expone como objeto
  anidado `{value: …}`, verificado en vivo). `GET /api/status` devuelve `backend.models` como
  `[{id, status}]` en vez de `[id]`. Degrada limpio con backends que no exponen `status` (Ollama,
  llama-swap < v236): `status` queda en `null` y simplemente no se muestra el badge.

## [0.7.0] - 2026-07-10

### Fixed
- Dashboard: el panel «En curso» nunca mostraba delegaciones activas si el navegador
  consultaba un proceso MCP distinto del que las ejecutaba (varias sesiones de Claude Code
  abiertas a la vez, o la web arrancada manualmente con
  `python -m local_delegate.web.metrics`) — el estado `inflight` vivía solo en memoria del
  proceso que ganaba el puerto 9393. Ahora `_inflight_start`/`_inflight_end`/
  `inflight_snapshot()` leen y escriben `LOG_DIR/inflight.json` bajo `FileLock`, así
  `/api/inflight` ve las delegaciones de **todas** las sesiones activas en la máquina, no
  solo la del proceso que sirve la web. Autolimpieza de entradas huérfanas (proceso muerto o
  con más de 30 min sin cerrarse) en cada lectura, sin hilo de fondo dedicado.
- Dashboard: el mensaje vacío «Sin delegaciones en curso» heredaba `Inter` en vez de
  `JetBrains Mono` como el resto del panel «Backend local» (badges, nombres de modelo,
  contador de tiempo).

### Added
- Dashboard: el modelo que está procesando una delegación ahora se marca en el panel
  «Backend local» (punto ámbar con pulso, estado «procesando») y la tool en uso se resalta
  en los chips de «Tools MCP disponibles», cruzando el modelo/tool de cada entrada de
  `/api/inflight` contra las filas ya renderizadas.

## [0.6.0] - 2026-07-10

### Added
- Dashboard: endpoint `GET /api/status` (versión del MCP en ejecución, modelos que el backend
  expone de verdad vía `/v1/models` — antes la web solo enseñaba modelos con eventos en el
  log —, catálogo de roles y lista de tools MCP) y `GET /api/system` (RAM y VRAM de sistema
  con uso/total/% + consumo por proceso de los servicios de debajo del MCP: llama-swap,
  llama-server, ollama…, y el propio proceso MCP). Nuevo módulo `web/sysinfo.py`, todo
  best-effort y de solo lectura; la VRAM por proceso en Windows (WDDM) sale de los perf
  counters `GPU Process Memory` muestreados en un hilo de fondo con TTL, porque `nvidia-smi
  --query-compute-apps` no la reporta en ese modo.
- Dashboard: panel «Backend local» (estado del endpoint, los modelos disponibles con su rol
  del catálogo y su estado montado/frío en llama-swap, delegaciones en curso, tools MCP) y
  panel «Sistema» (barras de RAM/VRAM con umbrales de color, utilización de GPU y tabla de
  procesos). Versión del MCP visible en el header.

### Changed
- Dashboard: rango temporal por defecto ahora es **Hoy** (antes: últimos 30 días); la tabla
  de actividad reciente se pagina de 10 en 10 (antes: primeras 30 filas fijas); la
  explicación de «¿cómo se calcula el ahorro?» pasa de un `<details>` al pie a un diálogo
  modal accesible desde el icono «?» del header.
- Dashboard: iconografía rehecha en SVG — botones del header sin glifos de texto ↻/⟳/◐,
  iconos de KPI nuevos (escudo, rayo, chip, gauge) y el icono de información pasa de un
  círculo CSS con letra a un SVG nítido; marca/favicon rediseñados para leerse bien a 16px
  (cuerpo del chip al ~62% del viewBox, solo 2 pines gruesos por lado y doble chevrón » de
  delegación en el núcleo).

### Removed
- Dashboard: filas de chips de filtro Tools/Modelos — redundantes con el panel «Backend
  local» (que ya lista modelos y tools reales) y con el rango temporal server-side; los
  agregados vuelven a computarse sobre todos los eventos del rango.
- README: la imagen del demo apunta por URL absoluta a `raw.githubusercontent.com`, de modo
  que también se renderiza en la página del paquete en PyPI (los links relativos solo
  funcionan dentro de GitHub); captura regenerada con el dashboard nuevo.

## [0.5.0] - 2026-07-09

### Added
- Guardrail de **RAM de sistema** (F7.9), además del de VRAM: `check-llamaswap` e
  `init-llamaswap` ganan flags opcionales `--ram-gb`/`--ram-margin-gb` (default de margen 2.0
  GiB); si no se pasan, el comportamiento es idéntico al de 0.4.0 (compatibilidad hacia
  atrás). Motivo: verificado en vivo durante la aplicación del ritual F7.8 que `llama-server`
  mapea el GGUF también en RAM del sistema (mmap) aunque el cómputo sea 100% GPU — un
  catálogo que cabe holgado en VRAM puede igual agotar la RAM y afectar otras ejecuciones del
  MCP en máquinas con menos de 32 GB. Nuevo `estimate_model_ram()` en `llamaswap_config.py`
  (pesos del GGUF, sin KV — asume offload completo a GPU; documentado como límite inferior si
  el `-ngl` es parcial); la aritmética de peor caso por grupo se generalizó
  (`worst_case_gb()`, con `worst_case_vram_gb` como alias retrocompatible) porque es idéntica
  para VRAM y RAM (llama-swap libera ambos recursos juntos al descargar un modelo).
- `local_status` añade una línea best-effort de RAM de sistema (Windows vía `ctypes`
  `GlobalMemoryStatusEx`, Linux vía `/proc/meminfo`; macOS no implementado, nunca rompe la
  tool). Verificado en vivo: con `qwen25-coder-14b` + `gemma3-4b` cargados a la vez, el
  estimador dio 10.69 GiB de RAM peor-caso vs. ~10.30 GB medidos con `Get-Process` — conforme
  al mismo margen conservador que ya tenía el estimador de VRAM.

## [0.4.0] - 2026-07-09

### Added
- Dos CLIs opt-in (F7): `local-delegate check-llamaswap --config <path> --vram-gb <N>` valida
  el peor caso de VRAM de los `groups` de un config.yaml de llama-swap contra un presupuesto
  con margen de seguridad; `local-delegate init-llamaswap` genera/actualiza `groups` (patrón
  residente + swap) sobre un config existente, corriendo el mismo guardrail internamente antes
  de escribir (nunca escribe si no cabe, nunca sobreescribe sin `--force`, siempre deja `.bak`).
  Requieren el extra opcional `[llamaswap]` (`pip install "local-delegate-mcp[llamaswap]"`,
  dependencia `pyyaml`); sin el extra, el resto del paquete se comporta exactamente igual que
  antes. El paquete nunca toca `config.yaml` de llama-swap por su cuenta — estos comandos son
  100% opt-in.
- Módulo `llamaswap_config.py`: estimador de VRAM por modelo GGUF con dos vías. Cuando el GGUF
  trae metadatos de arquitectura (capas, cabezas KV, dimensión de cabeza) y el `cmd` del modelo
  tiene `--ctx-size` explícito, calcula pesos + KV cache real (respeta `--cache-type-k/v`); si
  falta cualquiera de las dos cosas, cae a una estimación gruesa documentada
  (`tamaño_archivo * 1.2`). Verificado contra los GGUF reales del catálogo de referencia: el
  factor plano por sí solo subestimaba hasta 1.4 GiB en el caso de contexto grande sin
  cuantizar el KV cache — de ahí la vía fina con parser de header GGUF.
- `local_status` añade una línea best-effort con los `groups` activos en `LLAMASWAP_CONFIG`
  (solo si el extra `[llamaswap]` está instalado y el archivo existe; nunca rompe la tool).
- Recipe `docs/recipes/llama-swap-groups.md`: semántica de `groups` verificada contra el
  código real de llama-swap (v235/c59816b), presupuesto de VRAM con ejemplo real, los dos
  comandos, ritual de aplicación, y por qué el paquete no toca `config.yaml` solo.

## [0.3.0] - 2026-07-09

### Added
- Nueva tool `local_describe_image(path, question=None, max_words=200)` (F6): describe una
  imagen o responde una pregunta sobre ella con un modelo local de visión. La imagen se lee
  server-side (respeta `LOCAL_DELEGATE_ALLOWED_DIRS`), valida extensión
  (png/jpg/jpeg/webp/gif) y tamaño (`LOCAL_DELEGATE_MAX_IMAGE_MB`, default 8) antes de leerla
  completa. 11 tools en total. Guardrail de alcance: solo imagen→texto, nunca genera ni edita
  imágenes.
- Rol de modelo `LOCAL_DELEGATE_MODEL_VISION` (default `qwen3-vl-8b`), fuera de
  `ALLOWED_MODELS` (ese set es solo para el escape genérico `local_delegate`, texto→texto).
- `_chat` acepta `content` multimodal (lista de bloques `text`/`image_url` OpenAI-compatible)
  además de `str`, sin duplicar el manejo de inflight/log/feedback.
- `local_status` muestra el rol `vision` en el catálogo.
- Recipe `docs/recipes/llama-swap-vision.md`: entrada de `config.yaml` con `--mmproj`
  (Qwen3-VL-8B-Instruct Q4_K_M + mmproj Q8_0, ~5.78 GB), versión de `llama-server` probada
  pineada (9743/c57607016) con advertencia de multimodal experimental, y MiniCPM-V-4.5 como
  alternativa documentada.

## [0.2.1] - 2026-07-09

### Fixed
- `local_extract`: el schema de `response_format` restringe cada propiedad a tipos
  primitivos (`string`/`number`/`boolean`/`null`) en vez de un sub-schema vacío. Con el
  sub-schema vacío, algunos modelos (verificado con `gemma3-4b`) anidaban el valor en
  vez de devolverlo plano — `{"campo": {"valor": "x"}}` en lugar de `{"campo": "x"}`.
  Encontrado verificando la 0.2.0 en producción contra el backend real.

## [0.2.0] - 2026-07-09

### Added
- Nueva tool `local_status` (solo lectura): estado del backend (`/models`), catálogo de
  roles activo con `max_chars`, stats del log del mes actual, estado de la web de
  métricas, y VRAM (`nvidia-smi`) + modelo montado en llama-swap (`/running`) best-effort.
  10 tools en total.
- `local_extract` pide `response_format` con JSON schema por defecto
  (`LOCAL_DELEGATE_JSON_SCHEMA=auto|on|off`); si el backend responde 400 en modo `auto`,
  reintenta una vez sin schema.
- Feedback de ahorro: `_chat` anexa "leído server-side: N chars ≈ M tokens que no
  entraron a tu contexto" cuando `source=path` (apagable con `LOCAL_DELEGATE_FEEDBACK=0`).
- Log rotado por mes (`usage-YYYYMM.jsonl` en `LOCAL_DELEGATE_LOG_DIR`); el `usage.jsonl`
  legado se sigue leyendo como fuente adicional, sin migrarlo.
- Dashboard: selector de rango real (Hoy/7d/30d/mes anterior/todo/personalizado) que
  refetch server-side (`GET /api/events?from=&to=`, `GET /api/stats?from=&to=`) en vez de
  filtrar client-side; solo abre los archivos de log que tocan el rango pedido.
- Visibilidad de delegaciones en curso: `GET /api/inflight` y `GET /api/backend` (proxy de
  `/running` de llama-swap), con una tarjeta "En curso" en el dashboard.
- `LOCAL_DELEGATE_ALLOWED_DIRS`: restringe opcionalmente el parámetro `path` de todas las
  tools a una lista de raíces permitidas (`;` como separador). Vacío = sin restricción.
- Docstrings de las tools que aceptan `path` indican explícitamente cuándo preferirlas
  sobre leer el archivo con `Read`.
- Recipe de hooks de Claude Code (`docs/recipes/claude-code-hooks.md` +
  `docs/recipes/hooks/`) que sugieren delegar sin bloquear nunca la tool original.
- `update_agents.py` v2: mantiene un bloque de catálogo en prosa en los agentes que
  delegan, además de la línea `tools:`.

### Changed
- `_post_chat` devuelve un `ChatResult` estructurado (`ok`, `error`, `finish_reason`,
  `tokens_in`, `tokens_out`) en vez de codificar el error en el propio texto; el log de
  uso ahora registra tokens reales del backend cuando están disponibles, `finish_reason`,
  `error`, truncados y la versión del paquete.
- Cliente `httpx` module-level con keep-alive entre delegaciones.
- Escritura del log protegida con `filelock` (best-effort: si no consigue el lock en 1s,
  escribe igual, nunca bloquea la tool).

### Fixed
- Salida truncada por `max_tokens` ahora produce un aviso visible en el texto devuelto
  (antes se truncaba en silencio); igual para la entrada truncada al leer un `path`.
- Bloques `<think>`/`<thinking>` de modelos razonadores (Qwen3, R1-distill) se eliminan
  de la salida antes de devolverla.
- `local_commit_msg` valida `style` en vez de caer a `'plain'` en silencio si el valor no
  es reconocido.
- `local_extract` enruta por tamaño de entrada (mecánico/largo) igual que las demás tools
  con `path`, en vez de usar siempre el modelo mecánico.

## [0.1.1] - 2026-07-08

### Fixed
- Dashboard: el sparkline del KPI "Contexto conservado" ya no dibuja una línea sobre el texto
  cuando el ahorro es 0; ahora se ancla al borde inferior (`y.min=0`).

### Added
- Recipes de backends en `docs/recipes/`: llama-swap (RTX 5060 Ti Blackwell) y Ollama.
- Sección *Demo* en el README con screenshot del dashboard de ahorro.
- Wiki en `docs/wiki/` (+ wiki nativa de GitHub): Architecture, Configuration, Savings & metrics, Publishing, Troubleshooting.

### Changed
- `publish.yml`: `uv publish --check-url` para hacer la publicación idempotente ante
  re-ejecuciones sobre un tag existente.

## [0.1.0] - 2026-07-07

### Added
- Servidor MCP stdio con 9 tools texto→texto (`local_summarize`, `local_classify`,
  `local_extract`, `local_boilerplate`, `local_delegate`, `local_lint_summary`,
  `local_commit_msg`, `local_translate`, `local_explain_code`).
- Cliente genérico de cualquier endpoint OpenAI-compatible (llama-swap, Ollama, LM Studio, vLLM),
  configurable por variables de entorno; sin rutas hardcodeadas (`platformdirs` para el log).
- Web de métricas embebida (dashboard de uso/ahorro) en un hilo daemon.
- Logging JSONL por llamada (`usage.jsonl`) para calcular el ahorro de contexto.
- Auto-arranque de llama-swap opcional (opt-in, `LOCAL_DELEGATE_AUTOSTART=0` por defecto).
- Empaquetado para PyPI (`local-delegate-mcp`) ejecutable con `uvx`; `server.json` para el
  registro oficial de MCP.

[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.14.0...HEAD
[0.14.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.13.1...v0.14.0
[0.13.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.13.0...v0.13.1
[0.13.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.12.4...v0.13.0
[0.12.4]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.12.3...v0.12.4
[0.12.3]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.12.2...v0.12.3
[0.12.2]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.12.1...v0.12.2
[0.12.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ZahiriNatZuke/local-delegate/releases/tag/v0.1.0
