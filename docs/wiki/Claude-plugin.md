# Entrega por plugin de Claude Code

Desde el SDD `claude-plugin-and-mods`, `local-delegate install` entrega los **hooks** de Claude
Code como un **plugin** (`local-delegate@local-delegate`) en lugar de escribirlos en
`~/.claude/settings.json`. El resto de la integración (entrada MCP, skill, bloque de memoria,
subagentes) sigue como cuenta [Instalación de la integración](Integration-install.md): el MCP
**no** va dentro del plugin.

## Qué instala

| Pieza | Dónde | Notas |
|---|---|---|
| Marketplace `local-delegate` | el que viaja en el paquete (`resources/claude-plugin/`) | `claude plugin marketplace add <carpeta>` |
| Plugin `local-delegate@local-delegate` | caché de plugins de Claude Code, ámbito `user` | `claude plugin install … --scope user --config ld_bin=<intérprete> --config language=<es\|en> --json` |
| Hooks | `hooks/hooks.json` del plugin | cada hook corre `<ld_bin> -I -m local_delegate.hook <nombre>`, con `ld_bin` el intérprete del entorno de `uv tool` |
| Interruptor del hook de lectura | `read-hook.json` en el directorio de datos | `{"active": true\|false, "since": …}`: la capa *activa* |
| Estado de instalación | `install-state.json` en el directorio de datos | qué piezas puso `install`; `uninstall` solo quita lo que figura ahí |

Al migrar desde la entrega por settings (0.39 o anterior), `install` comprueba primero que el
plugin quedó instalado y habilitado, y solo entonces retira nuestros hooks de `settings.json` y
borra `~/.claude/hooks/local-delegate/`. Deja una copia de `settings.json`
(`settings.json.local-delegate-plugin.bak`). Si el hook de lectura estaba registrado, el
interruptor queda encendido. Los hooks ajenos de `settings.json` no se tocan.

## Cuándo se elige el plugin

`--claude-delivery plugin|settings` lo decide a mano. Sin la opción, `install` elige el plugin
cuando se cumple todo esto:

- `claude` está en el `PATH` y su versión es **2.1.292** o posterior;
- no se está dentro de WSL;
- `local-delegate` corre desde una instalación de **`uv tool`** (con `uvx` o un entorno editable no
  hay un intérprete estable que darle al plugin como `ld_bin`);
- con `--home` simulado, el sistema es uno donde está comprobado que `claude plugin` respeta
  `CLAUDE_CONFIG_DIR` (Windows, Linux y macOS).

Si falla alguna, `install` usa la entrega por settings y **avisa del motivo**. Con
`--claude-delivery settings` no avisa: es lo que se pidió, y queda anotado para que `update` no lo
deshaga (ver [Cómo deshacerlo](#cómo-deshacerlo)).

```bash
local-delegate install --dry-run                     # muestra la vía elegida y los comandos `claude plugin …`
local-delegate install                               # plugin si se cumplen las condiciones
local-delegate install --claude-delivery settings    # vuelve a settings.json (desinstala el plugin)
```

Volver a settings necesita `claude` en el `PATH`, para desinstalar el plugin. Si no está, no se
vuelve: quedarían los hooks duplicados. Por la misma razón, si el plugin está puesto y ahora no se
puede usar (CLI vieja o ausente), `install` lo deja como está y no registra hooks en settings.

## El hook de lectura

- `--enable-read-hook` enciende la capa activa (escribe `{"active": true}`).
- `--disable-read-hook` la apaga (`{"active": false}`). Con `uninstall`, es la única forma de
  apagarla. Las dos opciones son excluyentes.
- El apagado en caliente sigue siendo crear `~/.claude/local-delegate-block-off`: afecta solo a la
  capa que *bloquea*, no a la activa.

### Cómo pregunta el mod de lectura al clasificador

El clasificador vive solo en Python (`read_classifier.py`). Para cada llamada que puede llevar a
una decisión, el mod le pregunta primero **al daemon**, por `POST /api/hook/classify` (y una vez
por sesión `POST /api/hook/classify-config`), con el token del panel y solo desde `127.0.0.1`. La
respuesta es la misma, byte a byte, que la de `hook classify` y `hook classify --config`: las dos
salen de la misma función. Como el daemon no tiene el entorno de Claude Code, el mod manda en la
petición las variables que lee el clasificador (`LD_HOOK_READ_ENABLED`, `LD_HOOK_READ_BLOCK`,
`LD_HOOK_READ_SWITCH_FILE`, `LD_HOOK_READ_SUGGEST_KB`, `LOCAL_DELEGATE_LOG_DIR`, `LOCALAPPDATA`,
`XDG_DATA_HOME`, `USERPROFILE` y `HOME`) y el daemon usa esas y no las suyas. Si no hay token, el
daemon no responde en 300 ms, contesta 401, no tiene la ruta (otra versión) o la respuesta no vale,
el mod lanza el proceso de siempre (`python -I -m local_delegate.hook classify`) y deja de
preguntarle al daemon durante 5 minutos.

Las decisiones (`record-read`) van igual desde la 0.41.1: primero `POST /api/hook/record-read`, que
escribe la misma línea que `hook record-read` con el entorno que manda el mod (las variables de
arriba más `LD_HOOK_TELEMETRY_LOG` y `LD_HOOK_ENABLED`), y si el daemon no la toma, el proceso. El
daemon solo escribe en **su** telemetría: el destino que manda el mod tiene que ser el mismo fichero
que `LD_HOOK_TELEMETRY_LOG` en el entorno del daemon (el lanzador). Si es otro, o el daemon no la
tiene, responde 403 sin escribir nada y escribe el proceso. Las tres rutas `/api/hook/*` exigen
`Content-Type: application/json` y rechazan cualquier petición con `Origin`, haya token o no: una web
abierta en el mismo equipo también llega desde `127.0.0.1` (revisión de seguridad del 2026-10-23;
antes valía cualquier `.jsonl` absoluto). En la 0.41.0 solo iba por el proceso, y las decisiones tomadas en el diálogo
(`summarized`, `read_whole`, `dismissed`) no llegaron nunca a la telemetría. Si ninguna de las dos
vías la toma, el mod deja rastro (una línea en el log de depuración y otra en
`hook-failures.jsonl`, sin ruta ni contenido) y la vuelve a intentar al empezar la siguiente
llamada a una tool.

Cada decisión lleva un `id` que el mod pone una sola vez y manda por todas las vías (daemon, proceso
y reintento); `record-read` mira la cola de la telemetría (los últimos 64 KB) y no escribe un `id`
que ya está. Si el daemon no contesta dentro de su tope (1 s), la línea no se da por perdida ni se
lanza el proceso a la vez: espera a la siguiente llamada, que la reintenta con el mismo `id`, y solo
si ese intento también falla queda el rastro. Así una línea que el daemon escribió tarde no sale
dos veces (prueba en vivo del 2026-10-23).

### Leer literal un fichero que llegó resumido

Lo que el mod cuenta es **cuánto del fichero se ha leído en la sesión**, no el tamaño de cada
tramo: las franjas literales (`Read` con `offset`/`limit`, `sed -n`, `head`…) se suman, y la que
haría llegar al 80 % de las líneas del fichero cuenta como lectura entera y también se resume. El
resumen lo dice con números: hasta cuántas líneas se pueden leer literales («hasta 79 de sus 100
líneas») y, si fue una franja la que se resumió, cuántas se llevan leídas y cuántas quedan. Para
editar basta **una** lectura literal del fichero: libera la guarda de escritura, así que lo práctico
es leer solo el tramo que se va a cambiar.

### El hook de lectura y el mod de lectura

La opción `read_mod_enabled` del plugin sale **encendida por defecto** desde la 0.41: sin valor
guardado cuenta como encendida, y solo `false` la apaga (desde el menú de configuración del plugin
en Claude Code). Quien la guardó en `false` con la 0.40.0 la conserva apagada: se enciende en ese
mismo menú. Las sesiones abiertas siguen con el mod que cargaron al empezar: tras actualizar o
cambiar la opción, abre una sesión nueva. Con ella encendida, el mod de lectura y los hooks de lectura
(`Read` y `Bash|PowerShell`) no actúan los dos sobre la misma lectura. `hooks.json` no cambia: los
hooks siguen declarados y **se apartan** solo cuando el mod va a hacer exactamente lo que habrían
hecho ellos, es decir, cuando se cumplen las cuatro condiciones a la vez:

1. la opción `read_mod_enabled` está encendida (llega al hook como
   `CLAUDE_PLUGIN_OPTION_READ_MOD_ENABLED`; sin valor guardado la variable no llega, y en un hook
   del plugin cuenta como encendida);
2. el latido de **la misma sesión** (`heartbeats/<sesión>.json` en la carpeta de datos del plugin)
   dice `read_mod_active` y que `process.run` respondió, y tiene menos de 24 h. El mod lo escribe
   al iniciar la sesión, así que vale desde la primera lectura;
3. la capa que *bloquea* está encendida (en «solo registrar» el mod no actúa y el hook registra);
4. la vía es clasificable: una lectura de un fichero en disco con alcance conocido, por `Read`,
   `Bash` o `PowerShell`. Las tools de otros MCP o un `git show HEAD:x` las sigue tratando el hook.

Al apartarse, el hook deja en `blocks.jsonl` una línea con `step_aside: "read_mod_active"`,
`reason: "step_aside"`, la vía, el alcance y la huella del fichero; la decisión del mod va en su
propia línea (`source: "mod"`). Si falta cualquiera de las cuatro condiciones, el hook actúa como
en la 0.40: si el mod se apaga o falla, el hook vuelve. Los hooks de lectura que sigan en
`settings.json` no ven la opción del plugin y no se apartan; `doctor` lo avisa en «mod de lectura y
hooks de lectura coordinados» (`mod.read_overlap`), igual que avisa si la opción está encendida con
la capa activa apagada (entonces no actúa ninguno).

**Verificación.** Antes de encenderlo por defecto se probó en vivo con `claude -p` en Windows: el
control positivo (sin el mod, `Write` pasa), el negativo (con el mod, tras un resumen, `Write` se
rechaza y el fichero no cambia), la guarda tras `--resume`, que el hook se aparta y el latido.
**Pendiente de verificar en sesión interactiva**: que aparezcan los botones «resumir con el modelo
local / leer entero» y que el resumen llegue como resultado, que `Edit` se rechace tras el resumen
y se acepte tras un `Read` con `offset`/`limit`, y que la guarda siga activa tras `--resume` en
una sesión de terminal.

## Claude Desktop (`install --desktop`, solo Windows)

El chat de Claude Desktop no pasa su entorno a los MCP ni expande `${VAR}`, así que no se le
puede dar el token en la config. `install --desktop` escribe en
`%APPDATA%\Claude\claude_desktop_config.json` una entrada `local-delegate` que lanza el puente:

```json
{"command": "C:\\…\\local-delegate.exe", "args": ["desktop-bridge"]}
```

`local-delegate desktop-bridge` es un MCP stdio que reenvía al `/mcp` del daemon (la URL sale de
`daemon.json`; `--url` la cambia para pruebas) y **lee el token él mismo**:
`LOCAL_DELEGATE_WEB_TOKEN` de `HKCU\Environment` y, si no está, del entorno. La entrada no lleva
`env` ni token.

- Solo se toca la clave `local-delegate`; antes de escribir se guarda una copia rotada del fichero
  en la misma carpeta (hasta tres).
- Si ya había una entrada `local-delegate` que no puso `install` (por ejemplo, una escrita a mano),
  `--desktop` la reemplaza y avisa dónde quedó la copia. Si esa entrada llevaba un token escrito,
  borra la copia.
- En macOS y Linux, `--desktop` se niega con un error y no escribe nada.
- Reinicia Claude Desktop para que cargue la entrada.
- Si Desktop cierra el puente (cierra su stdin) con una delegación en curso, el puente no la
  espera: tras medio segundo de margen manda `notifications/cancelled` por cada petición que siga
  abierta, corta sus conexiones, cierra la sesión con `DELETE` y sale en 3 s como mucho. El daemon
  cancela la delegación (deja de esperar turno, corta el envío en curso para que el backend deje
  de generar, no manda más trozos, suelta la plaza y la quita de `inflight.json`) y la apunta en el registro de uso con `ok: false`,
  `error: "cancelled"` y `cancel_reason`. Lo mismo pasa con cualquier cliente que mande
  `notifications/cancelled` (el Esc de Claude Code), cierre la sesión o corte la conexión.

## Cómo comprobarlo

```bash
claude plugin list --json        # aparece "local-delegate@local-delegate", habilitado
local-delegate doctor            # estado del andamiaje
```

Con el plugin, `~/.claude/settings.json` no debe tener hooks de `local-delegate` ni existir
`~/.claude/hooks/local-delegate/`. Los hooks del plugin van siempre declarados y, medido en
Windows, añaden a una llamada `Bash` +80 ms de mediana con la capa de lectura apagada y +125 ms con
ella encendida. En Desktop, la tool aparece en el chat tras reiniciarlo.

El CI ejercita la secuencia completa contra la CLI real en los tres sistemas, en un HOME simulado:
`uv run python scripts/check_plugin_install.py <binario claude>` (migración desde settings con el
bloqueo encendido, idempotencia, vuelta a settings, `uninstall` y la orden de `prompt` leída del
`hooks.json` instalado).

## Cómo deshacerlo

```bash
local-delegate install --claude-delivery settings   # solo volver a los hooks en settings.json
local-delegate uninstall                            # quitarlo todo
```

`uninstall` lee `install-state.json` y quita **solo lo que figura en él**: el plugin y su
marketplace, la entrada de Desktop y lo que `--agents` añadió a los subagentes. Una pieza que ya
estaba antes de `install` se queda. Si `install --desktop` había reemplazado una entrada ajena,
`uninstall` **no la repone** (podía llevar el token): quita la nuestra y dice en qué copia está la
anterior. Al final borra el interruptor del hook de lectura y el estado.

La vuelta atrás de una instalación ya migrada es `install --claude-delivery settings`, y `update` la
**respeta**: `install` con ese flag deja escrito en `install-state.json` que la vía la eligió el
usuario (`"claude_delivery_explicit": true`), y con esa marca `update` repara los hooks en
`settings.json` en vez de migrar al plugin. Para volver al plugin, `install` sin el flag o con
`--claude-delivery plugin`: los dos quitan la marca. Una instalación vieja sin la marca (o sin
estado) sí se migra al plugin en el siguiente `update`.

## Bajar a la 0.39

La 0.39 no conoce el plugin: ni lo instala ni lo quita. Por eso, **antes de bajar, `uninstall` con
la 0.40**, y después instala la 0.39 y su `install` como siempre:

```bash
local-delegate uninstall                                   # con la 0.40: quita plugin y marketplace
uv tool install --force "local-delegate-mcp[llamaswap]==0.39.0"
local-delegate install                                     # la 0.39 vuelve a los hooks en settings.json
```

Si bajas sin `uninstall`, el plugin se queda y su `ld_bin` sigue apuntando al intérprete de
`uv tool`, que ahora tiene la 0.39. Cada hook arranca ese intérprete con
`-I -m local_delegate.hook`, que en la 0.39 no existe: carga el paquete (medido: **0,7–1,2 s**,
porque carga el servidor) y sale con código 1, un error **no bloqueante**, en cada llamada. No bloquea nada,
pero frena cada prompt y cada tool, y si además corres el `install` de la 0.39 tendrás los hooks
dos veces. Para arreglarlo después, quita el plugin a mano:

```bash
claude plugin uninstall local-delegate@local-delegate --scope user
claude plugin marketplace remove local-delegate
```
