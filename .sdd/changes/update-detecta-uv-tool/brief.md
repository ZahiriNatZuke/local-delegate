# Brief: update detecta el CLI instalado como uv tool y dice como actualizarlo

## Problem

`local-delegate update` actualiza el pin, el andamiaje y el daemon, pero **el ejecutable de
`uv tool` se queda donde estaba**: hace falta `uv tool upgrade local-delegate-mcp` aparte. Son dos
pasos donde el usuario espera uno, y el segundo no lo dice nadie.

El caso ya se dio: esta máquina tuvo el CLI en 0.16.0 con la 0.17.0 publicada, y ni `update` ni
`doctor` lo mencionaban (lo de `doctor` se arregló en el change `doctor-version-publicada`).

## Lo que decidió el experimento

Antes de diseñar nada había que responder una pregunta técnica: **¿puede `update` ejecutar el
upgrade él mismo?** Se probó de verdad, con un paquete inocuo (`cowsay`) para no tocar la
instalación real, lanzando `uv tool install <pkg>@latest --force` **desde el Python del propio
entorno de la herramienta**:

```
returncode: 2
error: failed to remove directory `…\uv\tools\cowsay\Scripts`: Acceso denegado. (os error 5)
import cowsay tras el upgrade: FALLO -> ModuleNotFoundError No module named 'cowsay'
```

Y el daño quedó hecho:

```
$ uv tool list
Failed find package `cowsay` in tool environment
$ cowsay -t hola
ModuleNotFoundError: No module named 'cowsay'
```

O sea: en Windows el upgrade **falla y además deja el entorno destruido**. Alcanza a borrar el
paquete antes de estrellarse contra el `Scripts/` que el propio proceso tiene bloqueado. Un
auto-upgrade ingenuo no es que no funcione: **rompe el CLI del usuario**.

(El experimento se limpió: `uv tool uninstall cowsay`, y se comprobó que `local-delegate-mcp`
sigue intacto en 0.17.0.)

**Decisión del usuario, con ese dato delante:** `update` **detecta y dice**, no ejecuta. Es además
lo que ya hace con la instalación editable, donde imprime `git pull` + `uv sync` sin ejecutarlos.

## Cómo se detecta, y es más limpio de lo esperado

Una instalación de `uv tool` deja un **`uv-receipt.toml` en la raíz del entorno**:

```
$ cat ~/AppData/Roaming/uv/tools/local-delegate-mcp/uv-receipt.toml
[tool]
requirements = [{ name = "local-delegate-mcp" }]
entrypoints = [{ name = "local-delegate", install-path = "…/.local/bin/local-delegate.exe", … }]
```

El `.venv` del repo **no lo tiene** (comprobado). Así que la detección es
`Path(sys.prefix) / "uv-receipt.toml"`: un fichero, sin ejecutar `uv`, sin variables de entorno y
**sin rutas específicas de cada sistema operativo** —que es lo que la haría frágil en macOS y
Linux, donde `uv tool dir` responde otra cosa—. Y el contenido permite confirmar que el tool es
**nuestro** paquete y no otro que casualmente nos ejecute.

## Desired outcome

Cuando hay una versión más nueva publicada y el CLI está instalado como `uv tool`, `update` lo
dice y da el comando exacto, explicando por qué no lo ejecuta él. El resto del comando sigue
haciendo exactamente lo mismo.

## In scope

- Detección del **modo de instalación** (editable / `uv tool` / otro) en **una sola función**.
- El mensaje de `update` para el caso `uv tool` con versión nueva disponible.
- Que el `fix_hint` del check `cli.published` —que hoy solo distingue editable de no-editable—
  consuma esa misma función, en vez de asumir `uv tool upgrade` para todo lo que no sea editable.

## Out of scope

- **Ejecutar el upgrade**, en cualquier variante: directa, desacoplada o condicionada. Descartado
  por el experimento y por decisión explícita del usuario.
- **Detectar instalaciones de `pipx`, `pip --user` o conda.** Para lo que no se reconoce se dice
  lo genérico, sin inventar un comando que podría no aplicar.
- Tocar el pin, el andamiaje o el daemon.

## Constraints and risks

- **No duplicar la definición de «cómo está instalado esto».** Ya hay dos consumidores —el
  `fix_hint` del check y el mensaje de `update`— y el repo tiene historial de verdades duplicadas
  que se separan; por eso `daemon_host_port()` se hizo pública en su día.
- **`sys.prefix` es del proceso que corre, no del que el usuario tiene en el PATH.** En esta
  máquina conviven **dos** instalaciones: la de `uv tool` (`~/.local/bin/local-delegate`, 0.17.0)
  y la editable del repo (`.venv`). Corriendo con `uv run` se ve la segunda; corriendo
  `local-delegate` a secas, la primera. El mensaje tiene que hablar de la que **está corriendo**,
  que es de la que sabe algo — decir lo contrario sería exactamente el falso diagnóstico que este
  repo ya pagó una vez.
- **Nada de rutas por sistema operativo.** `uv tool dir` responde distinto en Windows, macOS y
  Linux, y respeta `UV_TOOL_DIR` y `XDG_DATA_HOME` (los dos sin definir aquí, comprobado). El
  `uv-receipt.toml` esquiva todo eso.
- **El mensaje solo aparece cuando aporta:** si no hay versión nueva, no hay nada que decir.

## Open questions

- ~~¿Ejecutar el upgrade o solo decirlo?~~ **Resuelto por el usuario con el experimento delante:**
  solo decirlo.
