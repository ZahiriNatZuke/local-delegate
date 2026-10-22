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
`--claude-delivery settings` no avisa: es lo que se pidió.

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

## Cómo comprobarlo

```bash
claude plugin list --json        # aparece "local-delegate@local-delegate", habilitado
local-delegate doctor            # estado del andamiaje
```

Con el plugin, `~/.claude/settings.json` no debe tener hooks de `local-delegate` ni existir
`~/.claude/hooks/local-delegate/`. En Desktop, la tool aparece en el chat tras reiniciarlo.

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

La vuelta atrás de una instalación ya migrada es `install --claude-delivery settings`.
