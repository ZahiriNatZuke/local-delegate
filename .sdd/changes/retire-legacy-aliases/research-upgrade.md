# Investigación: impacto de la 0.38.0 en las instalaciones existentes y en la documentación

Alcance: lo que ve el usuario al actualizar a la 0.38.0 cuando se retiran los nombres de
`src/local_delegate/deprecations.py:51-91` (`DEPRECATED_NAMES`). El código interno lo mapea otro
agente. Todo es lectura; no se ha modificado nada fuera de este fichero. No se imprimió ningún valor
de token o clave (solo nombres).

## 0. Qué se retira (recordatorio)

| Clase | Nombre viejo → nuevo | Fuente |
|---|---|---|
| Retirado sin sucesor (deja de avisarse) | `LOCAL_DELEGATE_MODEL_FAST`, `_MAX_CHARS_FAST`, `_FALLBACK_FAST` | `deprecations.py:54-56` (`warn_until="0.37.0"`) |
| Subcomando | `recalcular-coste` → `recompute-cost` | `deprecations.py:58` |
| Opción | `--reiniciar-calibracion` → `--reset-calibration` | `deprecations.py:59` |
| Variable (la leen los hooks) | `LD_HOOK_READ_BLOQUEAR` → `LD_HOOK_READ_BLOCK` | `deprecations.py:60-62` |
| Variable (la leen los hooks) | `LD_HOOK_READ_INTERRUPTOR` → `LD_HOOK_READ_SWITCH_FILE` | `deprecations.py:63-69` |
| Variable | `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO` → `LOCAL_DELEGATE_STRUCTURED_SUMMARY` | `deprecations.py:70-75` |
| Variable | `LOCAL_DELEGATE_COSTE_RESPALDO` → `LOCAL_DELEGATE_COST_FALLBACK` | `deprecations.py:76-78` |
| Fichero interruptor (lo lee el hook) | `~/.claude/local-delegate-bloqueo-apagado` → `local-delegate-block-off` | `deprecations.py:80-86` |
| Doble escritura | `enfriamiento.json` (además de `cooldown.json`) | `deprecations.py:90`, `cooldown.py:53-63` |

## 1. Actualización desde 0.34.x, 0.35.x, 0.36.x y 0.37.x

### 1.1 Qué escribió cada versión en disco o en la configuración de los clientes con nombres viejos

**Hallazgo principal: ninguna versión escribió por su cuenta una variable vieja ni el interruptor
viejo.** Las variables y el interruptor los pone el usuario a mano, siguiendo la documentación.

- `install` nunca escribe variables `LD_HOOK_*` ni las cuatro renombradas en `settings.json`, en
  `~/.claude.json` ni en `~/.codex/config.toml`. `git grep` de los ocho nombres viejos en
  `src/local_delegate/install.py` de `v0.34.0`, `v0.35.0`, `v0.36.1` y `v0.37.0`: 0 coincidencias.
  La entrada MCP stdio solo lleva `LOCAL_DELEGATE_BASE_URL`, `LOCAL_DELEGATE_AUTOSTART` y la
  referencia a `LOCAL_DELEGATE_API_KEY` (`install.py:1135-1140`, `:1143-1167`); en Codex, lo mismo
  más `env_vars` (`install.py:1305-1312`). En HTTP, solo la cabecera con `${LOCAL_DELEGATE_WEB_TOKEN}`.
- La **0.34.0 documentaba** los nombres viejos como la forma de configurar: `README.md:198` y
  `:291`, `docs/wiki/Configuration.md:38`, `:204`, `:261-280`, `docs/recipes/claude-code-hooks.md:51-63`
  y `docs/wiki/Integration-install.md:114` (todo en `v0.34.0`). El sitio típico es el bloque `env`
  de `~/.claude/settings.json` (lo heredan los hooks), el perfil de la shell o el lanzador del
  daemon.
- **Hooks instalados** (`~/.claude/hooks/local-delegate/`): son copias del paquete. Los de 0.34.x
  leen solo los nombres viejos (`LD_HOOK_READ_BLOQUEAR`, interruptor viejo, `enfriamiento.json`); los
  de 0.35–0.37 leen los dos (`resources/hooks/hook_common.py:171-180`, `:288-344`, `:593-609`). Sus
  argumentos en `settings.json` no llevan nombres viejos (solo `--enabled`). El hook
  `anotar_llamada.py` (0.34) se retira por `_RETIRED_SCRIPTS` (`install.py:113-118`) y la skill
  `delegacion-local` por `_RETIRED_SKILLS` (`install.py:126`); las dos listas son **permanentes**, así
  que un salto 0.34 → 0.38 los sigue limpiando.
- **Ficheros de datos** en el directorio de logs (`%LOCALAPPDATA%\local-delegate` en Windows):
  `enfriamiento.json`, `enfriamiento-eventos.jsonl`, `atribucion-AAAAMM.json`,
  `coste-agregados.json`. Su lectura dual **no** está en `DEPRECATED_NAMES` y el plan del SDD anterior
  dice que «no se retira nunca» (`.sdd/changes/english-names-bilingual-output/plan.md:2245-2252`).
  **Contradicción a decidir en la spec:** `waves/A5b-2.md:127` decía «Ola R (0.38.0): retirar la
  lectura de `coste-agregados.json`». Recomiendo seguir el plan (no retirarla).
- **Temporales** de los hooks (`local-delegate-bloqueos.jsonl`, `local-delegate-llamadas/`,
  `local-delegate-salud-*.json`): lectura dual en `hook_common.py:643`, `:695` y en el daemon; tampoco
  están en el registro. No cambian en la 0.38.0 salvo que la spec lo decida.
- **Tarea programada / lanzador**: el paquete no crea el lanzador del daemon (en esta PC es un
  script propio del usuario, ver §2); `update` solo para y arranca la tarea `LocalDelegateDaemon`
  (`update.py:47`, `:647-655`). No hay nombres viejos que escriba el paquete ahí.

### 1.2 ¿Los migra o retira `install`/`update` de la 0.38.0?

Hoy, no:

- `update` repara hooks, registro de hooks, skill y bloque gestionado (`update.py:171-188`, `:280-351`)
  y reescribe los hooks con la versión nueva (estado `warn` de `scaffold.hook_files`). **No toca el
  bloque `env` de `settings.json` ni renombra el interruptor.**
- Lo único que hace con los nombres viejos es **avisar**: corre los mismos checks que `doctor`
  (`update.py:859-864`) y pasa el `fix_hint` del check `config.deprecated_names` a las notas
  (`update.py:345-351`). El check mira la shell, el `env` de `settings.json`, los interruptores
  viejos y la telemetría de hooks (`checks.py:1892-1953`), **todo a partir de `DEPRECATED_NAMES`**.
- REQ-012 de la spec anterior (`spec.md:236-254`) solo exigía retirar por `install` el hook y la
  skill viejos (hecho y permanente) y prometía que el interruptor viejo «sigue apagando mientras viva
  su alias». No exigía migrar variables.

**Consecuencia directa:** si la 0.38.0 borra las entradas de `DEPRECATED_NAMES`, el check deja de
verlas y ni `doctor` ni `update` dicen nada. Es exactamente el «fallo mudo» que el propio check
describe (`checks.py:1898-1902`) y que motivó avisar del rol `fast` durante siete menores.

### 1.3 Qué se rompería en silencio al instalar la 0.38.0

| Nombre viejo aún puesto | Efecto en 0.38.0 | ¿Ruidoso? |
|---|---|---|
| `LD_HOOK_READ_BLOQUEAR=1` (en `env` de `settings.json` o shell) | el bloqueo de lectura queda **apagado** (default `0`) | **silencioso** |
| `LD_HOOK_READ_INTERRUPTOR=<ruta>` | el hook vuelve a mirar `~/.claude/local-delegate-block-off`; el fichero de la ruta propia ya no apaga | **silencioso**; si el usuario tenía `LD_HOOK_READ_BLOCK=1` y el interruptor en su ruta, el bloqueo **se enciende** sin querer |
| `~/.claude/local-delegate-bloqueo-apagado` existe | deja de apagar; con `LD_HOOK_READ_BLOCK=1` el bloqueo **se enciende** de golpe | **silencioso** y molesto (el usuario lo había apagado a propósito) |
| `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO=1` | el resumen por secciones se apaga | silencioso |
| `LOCAL_DELEGATE_COSTE_RESPALDO=…` | el coste se valora con el respaldo declarado; el panel nombra el respaldo en uso, pero no dice por qué cambió | casi silencioso |
| `recalcular-coste`, `--reiniciar-calibracion` en scripts o tareas | `argparse` da «invalid choice»/«unrecognized arguments» | ruidoso (bien) |
| `LOCAL_DELEGATE_*_FAST` | ya no tenían efecto; solo deja de avisarse | sin impacto funcional (previsto) |
| Hooks viejos (0.34) con daemon 0.38 sin haber corrido `update` | no ven el enfriamiento (`enfriamiento.json` ya no se escribe) y siguen bloqueando hacia un modelo parado; además siguen leyendo solo `LD_HOOK_READ_BLOQUEAR` | silencioso; contradice lo que prometió el CHANGELOG 0.35.0 («al revés no se pierde nada: el daemon … sigue escribiendo `enfriamiento.json`», `CHANGELOG.md:~456-461`) |
| `enfriamiento.json` viejo que queda en disco | el hook nuevo solo lo lee si no hay `cooldown.json` (`hook_common.py:598-605`); sus `hasta` están vencidos → no bloquea nada | inocuo |

### 1.4 Caso importante: la Mac en 0.34 que salta a la 0.38.0

La Mac usa MCP stdio vía `uvx` con versión fijada y delega en el backend de la PC; no tiene daemon
(`update.py:927-930`, rama «no hay daemon»). Al saltar:

- **Bien**: `update` 0.38 reescribe los hooks (0.34 → 0.38), borra `anotar_llamada.py` y su registro,
  borra la skill `delegacion-local`, actualiza el pin de `uvx` (`update.py:490-510`) y el bloque
  gestionado. La lectura dual de datos (si se mantiene) absorbe `coste-agregados.json`,
  `atribucion-*.json` y el formato viejo de logs.
- **Mal**: la Mac **nunca pasó por la etapa de aviso** (0.35–0.37). Si en su `settings.json`, su
  perfil de zsh o el `env` de algún cliente tiene `LD_HOOK_READ_BLOQUEAR`, `LD_HOOK_READ_INTERRUPTOR`,
  el interruptor viejo o las dos variables del servidor, todo deja de funcionar **sin ningún aviso**,
  porque la 0.38 ya no conoce esos nombres. No pude mirar la Mac (no hay acceso desde aquí); el
  usuario tendría que comprobarlo o correr `doctor` con la 0.37 antes de saltar.
- Entre `uv tool upgrade`/pin nuevo y `update`, conviven hooks 0.34 con servidor 0.38: los hooks no
  ven el enfriamiento (fila de la tabla anterior). Se cierra al correr `update`.

### 1.5 Propuesta

1. **Seguir avisando aunque el alias ya no funcione** (lo más importante). En vez de borrar las
   ocho entradas, convertirlas en «retiradas»: sin efecto, pero el check sigue nombrándolas y diciendo
   el sucesor, con un `warn_until` amplio (propuesta: `0.40.0`; el precedente del rol `fast` fue de la
   0.30 a la 0.37). Hoy la clase `retired` exige `new=None` y la pista dice «quítala»
   (`deprecations.py:17-19`, `checks.py:1945-1950`): habría que permitir `new` en un retirado para
   que la pista diga «renómbrala a X», o crear una clase nueva (`renamed_retired`). **Es decisión de
   spec** y toca el guardián de clases de `tests/test_deprecations.py`; lo marco para que el
   especificador lo decida, no lo improviso.
   - El hook necesita lo mismo: sin el alias en `hook_common.py:288-292`, el evento de telemetría no
     dirá `deprecated_names`. Propuesta: que el hook siga **detectando** (sin aplicar) los nombres
     viejos y los anote, para que `doctor` los vea en la cola de 7 días.
2. **Migración automática en `update`** (opcional, recomendable para el salto desde 0.34): una acción
   nueva, visible en el plan y en `--dry-run`, que
   - renombra en el bloque `env` de `~/.claude/settings.json` cada clave vieja a la nueva conservando
     el valor, **solo si la nueva no está** (si están las dos, borra la vieja: ya ganaba la nueva);
   - renombra `~/.claude/local-delegate-bloqueo-apagado` a `local-delegate-block-off` si el nuevo no
     existe (si existen los dos, borra el viejo).
   - **No** toca la shell, el perfil ni el lanzador del daemon: ahí solo avisa (regla de no escribir
     configuración ajena a ciegas, `update.py:15-17`).
   Encaja con el patrón existente (`install` ya reescribe `settings.json` para los hooks). Si no se
   quiere migrar, al menos el punto 1.
3. **`doctor`**: el check `config.deprecated_names` en `warn` con el texto «ya no tiene efecto desde
   la 0.38.0; renómbrala a X» (catálogo es/en). Opcional: un aviso aparte si existe `enfriamiento.json`
   y no `cooldown.json`, para recordar que los hooks viejos necesitan `update`.
4. **CHANGELOG `[0.38.0]`** con «Lo que rompe y cómo actualizar» (ver §3.3), incluyendo una línea
   para quien salta desde la 0.34: «corre `local-delegate doctor` con tu versión actual antes de
   actualizar, o `update` justo después, y renombra lo que diga».
5. Mantener la lectura dual de datos y de temporales (no está en el registro; el plan anterior dice
   «nunca»). Resolver la contradicción con `waves/A5b-2.md:127`.

## 2. Esta PC (solo lectura)

| Sitio | Nombres encontrados | ¿Viejos? |
|---|---|---|
| Variables de usuario de Windows | `LOCAL_DELEGATE_AUTOSTART`, `LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS`, `LOCAL_DELEGATE_WEB_TOKEN` | no |
| Variables de máquina | ninguna `LD_*`/`LOCAL_DELEGATE_*` | — |
| `~/.claude/settings.json` → `env` | `CLAUDE_CODE_USE_POWERSHELL_TOOL`, `LD_HOOK_READ_BLOCK`, `LD_HOOK_TELEMETRY_LOG` | no (ya renombrada a `LD_HOOK_READ_BLOCK`) |
| `~/.claude/settings.local.json` | sin bloque `env` | — |
| Hooks registrados | `record_call.py`, `suggest_delegate_read.py --enabled` (Read y MCP), `suggest_delegate_shell.py --enabled`, `suggest_delegate_prompt.py` | no (sin `anotar_llamada.py`) |
| Hooks instalados | `~/.claude/hooks/local-delegate/hook_common.py` y `suggest_delegate_read.py` contienen los alias: son los de la 0.37, se sustituyen con `update` | esperado |
| Telemetría de hooks | 158 eventos con `deprecated_names: LD_HOOK_READ_BLOQUEAR`, el último el **2026-10-13**; ninguno después | histórico, ya resuelto |
| Tarea `LocalDelegateDaemon` | `conhost --headless powershell -File D:\Projects\llms\llama-swap\start-local-delegate-secure.ps1` | — |
| Lanzador `start-local-delegate-secure.ps1` | `LOCAL_DELEGATE_REMOTE_API_KEY`, `LOCAL_DELEGATE_API_KEY`, `LD_HOOK_TELEMETRY_LOG`, `LOCAL_DELEGATE_STRUCTURED_SUMMARY`, `LOCAL_DELEGATE_WEB_TOKEN` | no |
| `~/.claude.json` (MCP `local-delegate`) | `http` a `127.0.0.1:9393/mcp`, cabecera `Authorization`, sin `env` | no |
| `~/.codex/config.toml` | `LOCAL_DELEGATE_WEB_TOKEN` | no |
| Perfiles de shell (PowerShell 5/7, bash) | ninguno de los nombres | — |
| Interruptores en `~/.claude/` | no existe ni `local-delegate-bloqueo-apagado` ni `local-delegate-block-off` | — |
| Directorio de logs | `enfriamiento.json`, `enfriamiento-eventos.jsonl`, `coste-agregados.json`, `atribucion-2026{07..10}.json` junto a `cooldown.json` y `cost-aggregates.json` | datos viejos; inocuos si se mantiene la lectura dual |
| `~/.claude/scripts`, `agents`, `skills`, `CLAUDE.md`, `~/.codex/AGENTS.md` | ninguno de los nombres | — |

**Qué habría que cambiar aquí antes de instalar la 0.38.0: nada.** Todo lo que usa el bloqueo y el
resumen estructurado ya va con nombre nuevo. Solo queda, tras instalar, correr `update` para cambiar
los hooks 0.37 por los 0.38 (ya lo hace el flujo normal de release). `enfriamiento.json` queda
huérfano y se puede borrar a mano cuando se quiera; no molesta.

Fuera de alcance, pero visto: `D:\Projects\llms\llama-swap\lanzar-tanda-afinidad.ps1:30` pone
`LOCAL_DELEGATE_COMMIT_IDIOMA`, una variable que **nunca existió en una versión publicada** (la real
es `LOCAL_DELEGATE_COMMIT_LANGUAGE`, `config.py:428`); hoy ya no hace nada. Y en el repo,
`scripts/build_corpus.py:453` y `scripts/_claude_bench.py:11` citan nombres viejos (los ve el otro
agente).

## 3. Documentación a cambiar

### 3.1 `README.md`

- `README.md:121-123`: el aviso «Los nombres viejos siguen funcionando con aviso hasta la 0.37.x y se
  retiran en la 0.38.0» pasa a pasado: «desde la 0.38.0 ya no funcionan; `doctor` dice cuáles siguen
  puestos y por cuál cambiarlos» (o borrar el aviso y dejar la tabla en el CHANGELOG).

### 3.2 `docs/wiki/` y `docs/recipes/`

- `docs/wiki/Configuration.md:38` — quitar «(antes `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO`)» o
  cambiarlo a «(hasta la 0.37, `…`)».
- `docs/wiki/Configuration.md:122-125` — la doble escritura de `enfriamiento.json` ya se retiró;
  dejar «hasta la 0.34.0 se llamaba `enfriamiento.json`; el daemon arranca desde él si no hay
  `cooldown.json`» (si se mantiene esa lectura).
- `docs/wiki/Configuration.md:212` — «(antes `LOCAL_DELEGATE_COSTE_RESPALDO`)».
- `docs/wiki/Configuration.md:541` — «(antes `LD_HOOK_READ_BLOQUEAR`)».
- `docs/wiki/Configuration.md:555-560` — quitar «antes `local-delegate-bloqueo-apagado`, que sigue
  apagando con aviso» y «(antes `LD_HOOK_READ_INTERRUPTOR`)».
- `docs/wiki/Configuration.md:566-568` — quitar «(o `enfriamiento.json`, si el daemon es de una
  versión anterior)» solo si el hook deja de leerlo; si se conserva la lectura, matizar que el daemon
  ya no lo escribe.
- `docs/wiki/Configuration.md:588-609` — la sección «Nombres viejos de variables (alias con aviso)»
  entera: título y texto pasan a «Nombres retirados en la 0.38.0»; la tabla se queda como referencia
  de qué renombrar; quitar «siguen aceptándose, ocultos en la ayuda» (603-605) y «el viejo sigue
  apagando durante el mismo plazo» (607-609). Si se adopta la migración de `update`, decirlo aquí.
- `docs/wiki/Integration-install.md:453` — fila del check «nombres obsoletos» en la tabla de checks
  (atada a su test): cambiar «nombres viejos que siguen en uso … con la versión en que se retira el
  alias» por el comportamiento 0.38 (sin efecto, pista con el sucesor) y quitar las tres `_FAST` si
  dejan de avisarse.
- `docs/wiki/Architecture.md:188` — fila de `cooldown.py`: «(`cooldown.json`, antes
  `enfriamiento.json`)» puede quedarse como historia; quitar cualquier mención a que lo sigue
  escribiendo (hoy no la tiene).
- `docs/recipes/claude-code-hooks.md:62-63` — «(antes `local-delegate-bloqueo-apagado`, que sigue
  valiendo con aviso; …)».
- Grep de «0.38» en `docs/wiki`: solo `Configuration.md:125` y `:591` (ya listadas). `Language.md`,
  `Troubleshooting.md`, `Daemon.md`, `Savings-and-metrics.md`, `Tools.md`: sin nombres viejos.
- Si se publica la 0.38.0, `docs/wiki/` es uno de los tres sitios de toda release (CHANGELOG, README,
  wiki).

### 3.3 `CHANGELOG.md`

- `CHANGELOG.md:7` (`[Unreleased]`, hoy solo «Añade» con el autocompletado): añadir antes una
  entradilla y la sección **«Lo que rompe y cómo actualizar»**, con el mismo formato que la 0.35.0
  (`CHANGELOG.md:~396-466`) y la 0.36.0 (`:184-221`). Contenido propuesto:
  - Tabla «Qué deja de funcionar» con las ocho filas de §0 (nombre viejo → nuevo → qué pasa si
    sigue puesto: «se ignora», «da error de argumento»).
  - «**Antes de actualizar**, corre `local-delegate doctor`: el check «nombres obsoletos» dice qué
    renombrar. Quien salta desde la 0.34 o anterior no vio nunca ese aviso: revisa el `env` de
    `~/.claude/settings.json`, el perfil de la shell y el lanzador del daemon.» (+ lo que haga
    `update` si se adopta la migración).
  - «El interruptor viejo ya no apaga el bloqueo: créalo con el nombre nuevo
    (`New-Item "$HOME\.claude\local-delegate-block-off" -ItemType File`).»
  - «El daemon deja de escribir `enfriamiento.json`. Los hooks de la 0.34 que sigan instalados no
    verán el enfriamiento: `local-delegate update` los cambia. El fichero viejo puede borrarse.»
  - «`LOCAL_DELEGATE_MODEL_FAST`, `_MAX_CHARS_FAST` y `_FALLBACK_FAST` dejan de avisarse.»
  - Si se mantiene, «la lectura de los ficheros de datos viejos no cambia».
- Las líneas de la 0.35.0 (`CHANGELOG.md:~410-431` tabla con «alias con aviso hasta la 0.37.x» y
  «Plazos», y la frase de «hooks viejos con daemon nuevo … sigue escribiendo `enfriamiento.json`»)
  **no se tocan**: son historia de esa versión.

### 3.4 Skill y bloque gestionado que instala el paquete

- `src/local_delegate/resources/skills/`, `resources/memory/` (bloque de `CLAUDE.md`/`AGENTS.md`):
  **0 coincidencias** con los nombres viejos. No hay que cambiar nada.
- `src/local_delegate/resources/i18n/{es,en}/cli.json:288` (`cli.recompute_cost.reset_mismatch`)
  nombra `--reiniciar-calibracion`: desaparece con el alias (lo ve el agente del código; el guardián
  de claves sin uso lo pedirá).
- Docstring del hook `resources/hooks/suggest_delegate_read.py:37` «(antes
  `LD_HOOK_READ_BLOQUEAR`)»: texto interno, para el agente del código.

## 4. Precedente de estilo: la retirada del rol `fast` (0.30.0)

`CHANGELOG.md:986-1006`:

- Sección `### Removed` con la entrada en negrita y la etiqueta **(breaking)**, más el **porqué con
  datos** («164 registros … solo 5 … 3 de un test»).
- Un párrafo **«Qué notas si lo usabas»**: el síntoma exacto que verá el usuario (el error literal),
  que no gasta backend y cuáles son los roles vigentes.
- En `### Added`, el aviso de `doctor` por las variables que quedaron sin efecto, con la razón de
  diseño: «una variable que deja de hacer algo en silencio es justo el fallo mudo que este proyecto
  persigue» y «no se rompe el arranque a propósito».

Lo que conviene copiar para la 0.38.0: (1) etiqueta de incompatible y explicación corta del porqué
(se cumple el plazo anunciado en la 0.35.0); (2) un «Qué notas si aún usas un nombre viejo» por cada
grupo (variables del hook: el bloqueo se apaga o se enciende; variables del servidor: la función se
apaga; CLI: error de argumento); (3) **el mismo aviso de `doctor` sobre lo que quedó sin efecto**, que
en la 0.30 se añadió justo al retirar y es lo que hoy falta en el plan de la 0.38 (§1.5 punto 1).
Diferencia de formato: desde la 0.35 el CHANGELOG usa secciones en español («Lo que rompe y cómo
actualizar», «Añade», «Cambia», «Corrige») y tablas viejo → nuevo; la 0.38.0 debe seguir ese formato,
no el `Removed`/`Added` en inglés de la 0.30.

## Llamadas `local_*`

0. Al principio el brief prohibía el MCP; cuando llegó la autorización ya había leído lo necesario
por franjas con `grep`/`sed` (ficheros grandes leídos solo en tramos de 10–60 líneas), y lo que
quedaba eran consultas puntuales de nombres en configuración que no se prestan a resumen.

## Procesos

No se lanzó ningún servidor, espera ni proceso en segundo plano; todos los comandos fueron de
lectura y terminaron.
