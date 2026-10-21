# Investigación: scripts de autocompletado por shell (SDD `cli-completion`)

Fecha: 2026-10-20. Máquina: Windows 11 (26200), pwsh 7.6.6, Windows PowerShell 5.1.26100,
Git Bash (MSYS2) con bash 5.3.15. Sin usar el MCP `local-delegate`.

Laboratorio (todo fuera del repo):
`C:\Users\Yohan\AppData\Local\Temp\claude\D--Projects-local-delegate\ffbfb0a5-8272-479c-9bf0-c44cb9d212bb\scratchpad\completion-lab\`

- `gen.py`: prototipo de generador **solo con la biblioteca estándar** que, a partir de un árbol
  estático de dos niveles (`install`, `backend-params set|show|reset`, `completion` con argumento
  posicional de valores fijos), emite los tres scripts. Uso: `py -I gen.py powershell|bash|zsh`.
- `proto.ps1`, `proto.bash`, `proto.zsh`: scripts generados (versión final del prototipo).
- `test-ps.ps1`, `test-profile.ps1`, `test-misc.ps1`, `test-names.ps1`, `test-dash.ps1`,
  `test-legacy.ps1`, `test-load.ps1`, `test-ascii.ps1`: pruebas de PowerShell con `TabExpansion2`.
- `test-bash.sh` (bash con `COMP_WORDS` simulado), `test-bash-pty.sh` (bash real con readline en un
  pty, vía `script`, en WSL).
- `test-zsh.zsh` (zsh real con `compinit` y `zpty`), `test-zsh-stub.zsh` (función llamada fuera de
  ZLE con dobles de `compadd`/`_describe`), `test-zsh-modes.zsh` (sin `compinit`, modo `fpath`,
  modo `eval`).
- `others\`: scripts generados por `uv` 0.10.12 y `gh` 2.102.0 para comparar.

## Documentación oficial consultada (2026-10-20)

- Register-ArgumentCompleter (7.6, con enlace a 5.1):
  https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/register-argumentcompleter
- about_Profiles: https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_profiles
- about_Character_Encoding (5.1):
  https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_character_encoding?view=powershell-5.1
- Bash, Programmable Completion: https://www.gnu.org/software/bash/manual/html_node/Programmable-Completion.html
- Zsh, Completion System: https://zsh.sourceforge.io/Doc/Release/Completion-System.html
- Código leído: pip 26.2.1 `pip/_internal/commands/completion.py` (del Python 3.14 del sistema; el
  `.venv` del repo no trae pip), click 8.4.2 `click/shell_completion.py` (del `.venv`).

Citas que fijan decisiones:

- Native: el scriptblock recibe por posición `$wordToComplete`, `$commandAst` y `$cursorPosition`;
  `-CommandName` es `String[]`; devolver `CompletionResult(completionText, listItemText,
  resultType, toolTip)` da tooltip y entrada de lista (Ctrl+Espacio). «Returning an array of values
  causes PowerShell to treat the entire array as one tab completion value»: hay que emitir los
  resultados uno a uno por la canalización.
- Perfil: `$PROFILE` es CurrentUserCurrentHost; «put the items that you use in all the host
  applications into your `$PROFILE.CurrentUserAllHosts` profile». «In Windows, the location of the
  Documents folder can be changed by folder redirection or OneDrive». «The Restricted execution
  policy is the default. It prevents all scripts from running, including the profiles».
- 5.1: «Without the BOM, Windows PowerShell misinterprets your script as being encoded in the legacy
  "ANSI" codepage».
- bash: «If the command word is a full pathname, Bash searches for a compspec for the full pathname
  first. If there is no compspec for the full pathname, Bash attempts to find a compspec for the
  portion following the final slash.»
- zsh: los ficheros con `#compdef` en `fpath` se vuelven autocargables cuando se llama a
  `compinit`; `compdef` asocia una función de completado a un comando ya existente.

## 1. PowerShell (pwsh 7 y Windows PowerShell 5.1)

### Resultado del prototipo con `TabExpansion2` (salida real, recortada)

`pwsh -NoProfile -File test-ps.ps1 -Script proto.ps1` (ejecutado desde una carpeta vacía):

```
load ms: 13
[local-delegate ] col=15 (61 ms) -> install | backend-params | completion
[local-delegate ba] col=17 (5 ms) -> backend-params
[local-delegate backend-params ] col=30 (3 ms) -> set | show | reset
[local-delegate backend-params set --] col=36 (1 ms) -> --role | --param | --help
[local-delegate backend-params set --role ] col=41 (2 ms) -> mechanical | long | code | vision
[local-delegate backend-params set --role=v] col=42 (2 ms) -> --role=vision
[local-delegate install --mcp-mode http --lang ] col=46 (1 ms) -> es | en
[local-delegate completion ] col=26 (1 ms) -> powershell | zsh | bash
[local-delegate.exe backend-params s] col=35 (1 ms) -> set | show
[local-delegate-mcp ins] col=22 (1 ms) -> install
[local-delegate backend-params set --role code] col=29 (1 ms) -> backend-params   <- cursor a mitad de línea
[local-delegate --version backend-params ] col=40 (1 ms) -> set | show | reset
[local-delegate install --config ] col=32 (10 ms) ->                            <- valor libre: no devuelve nada
[C:\x\local-delegate.exe ins] col=27 (1 ms) -> install
[& "C:\x y\local-delegate.exe" ins] col=33 (0 ms) -> install
```

`powershell.exe` (5.1) da lo mismo **salvo** `set --` (vacío; ver abajo). El primer Tab de la
sesión cuesta 60–100 ms (arranque del motor de completado); los siguientes, 1–5 ms.

### Hallazgos

1. **Nombres que registrar.** Con solo `-CommandName 'local-delegate'` registrado, el completador
   salta también al teclear `local-delegate.exe`, `.\local-delegate` y la ruta completa, en 7.6 y en
   5.1 (`test-names.ps1`: `HIT` en los tres casos). Hace falta registrar **los dos alias del
   paquete** (`local-delegate` y `local-delegate-mcp`, `pyproject.toml:74-75`); añadir las
   variantes `.exe` no hace daño (el prototipo las registra) pero no es necesario. El completador
   salta aunque el comando no exista en el PATH (`dbg.ps1` con `zzfake`).
2. **Palabras previas.** Recorrer `$commandAst.CommandElements` desde el índice 1 y quedarse solo
   con los elementos cuyo `Extent.EndOffset < $cursorPosition`; el que toca el cursor es
   `$wordToComplete`. Así funciona el cursor a mitad de línea (caso `col=29`). Para el texto usar
   `.Value` si el elemento es `StringConstantExpressionAst` (quita comillas) y si no
   `.Extent.Text` (en pwsh 7 `--` llega como `CommandParameterAst`, `test-dash.ps1`).
3. **`--opcion=valor`.** En PowerShell llega como **una sola palabra** (`W=[--role=v]` en 7 y en
   5.1). Hay que partirla con `^(--[^=]+)=(.*)$`, completar el valor y devolver
   `CompletionText = '--role=' + valor` (probado: `--role=vision`).
4. **Limitación de 5.1:** el motor **no llama** al completador nativo cuando la palabra es `-` o
   `--` a secas (`test-dash.ps1`: en 5 la salida sale vacía; en 7 llega `W=[--]`). Con `--r` sí
   llama. Es del motor, no del script: documentarlo («en Windows PowerShell 5.1 escribe al menos una
   letra después de `--`»).
5. **Valor libre** (opción sin `choices`): si el completador no devuelve nada, PowerShell cae al
   completado de rutas (`test-misc.ps1`: `--config pro` → `.\proto.bash,.\proto.ps1,...` en 7 y
   5.1). Es el comportamiento deseable para rutas.
6. **Mayúsculas.** `-contains` no distingue mayúsculas y argparse sí: el recorrido debe usar
   `-ccontains` (el prototipo final lo hace: `BACKEND-PARAMS` ya no entra en el subcomando). El
   filtro del prefijo puede ser `StartsWith(..., OrdinalIgnoreCase)`, porque lo que se inserta es el
   texto correcto.
7. **Datos dentro del scriptblock.** La primera versión dejaba las tablas en variables
   `$__ld*` del ámbito del perfil (contamina la sesión). En la final las tablas viven dentro del
   scriptblock: `vars leaked: 0` en 7 y 5.1 (`test-profile.ps1`). Reconstruir las tablas en cada Tab
   no se nota (1–5 ms).
8. **Codificación (decisivo).**
   - Fichero UTF-8 **sin BOM** con tildes: 5.1 lee `Ã³` en vez de `ó` (`test-misc.ps1`: códigos
     `00C3 00B3` en 5.1, `00F3` en 7).
   - Con BOM: correcto en las dos (`test-load.ps1`).
   - `py gen.py powershell | Out-String | Invoke-Expression`: **mal en las dos**
     (`251C 2502`), porque PowerShell decodifica la salida del proceso con
     `[Console]::OutputEncoding` (aquí `ibm850`).
   - **Script solo ASCII** (cada carácter no ASCII como `$([char]0x00F3)` dentro de comillas
     dobles, escapando `` ` ``, `"` y `$`; los emojis como par de sustitutos): correcto en 7 y 5.1
     tanto por `Invoke-Expression` como con dot-source y sin BOM (`test-ascii.ps1`,
     `test-profile.ps1`: códigos `0069 00F3 006E`). **Es la opción robusta**: elimina la cuestión
     del BOM y la de la página de códigos de la consola.
9. **Sintaxis prohibida en 5.1** (el prototipo no usa ninguna y corre en 5.1): operador ternario
   `?:`, `??`, `??=`, `?.`, `&&`/`||` de cadenas de canalización, `` `u{...} ``,
   `-Native` sigue existiendo en 5.1 (desde PS 5.0). `[CompletionResult]::new()` existe en 5.1,
   pero el prototipo usa `New-Object` por prudencia. `using namespace` (que usa `uv`) también vale
   en 5.1 pero solo al principio de un fichero: con dot-source de un fragmento o con
   `Invoke-Expression` es más seguro usar nombres de tipo completos.
10. **Mecanismo antiguo `TabExpansion`** (el que usa pip): en pwsh 7.6 **ya no funciona**
    (`test-legacy.ps1`: `[]` en 7, `[LEGACY-HIT]` en 5.1). Confirma que hay que usar
    `Register-ArgumentCompleter -Native`.

### Carga desde el perfil

| Modo | Coste por sesión | Coste por Tab | Codificación |
|---|---|---|---|
| Dot-source de un fichero generado (`. "...\completion.ps1"`) | 7–19 ms (`load ms`) | 1–5 ms | sin problemas si el script es ASCII |
| `local-delegate completion powershell \| Out-String \| Invoke-Expression` | **0,8–2,1 s** (medido: `local-delegate --version` tarda 806 ms en 5.1 y 2 100 ms en pwsh, arranque de Python) | 1–5 ms | mal si no es ASCII |

Ninguno de los dos llama a Python en cada Tab (el script es estático). Recomendación: **fichero
generado y dot-source**; `Invoke-Expression` solo como alternativa documentada.

- **Qué perfil.** `CurrentUserAllHosts` (`profile.ps1`) para que valga en la consola, VS Code y
  Windows Terminal. Rutas reales en esta PC (`$PROFILE | Select-Object *`):
  - pwsh 7: `C:\Users\Yohan\Documents\PowerShell\profile.ps1`
  - 5.1: `C:\Users\Yohan\Documents\WindowsPowerShell\profile.ps1`
  Son **dos ficheros distintos**: si se quiere completado en las dos ediciones, `install` debe
  escribir en ambos. Aquí `Documents` no está redirigido a OneDrive, pero puede estarlo: no
  construir la ruta a mano; preguntársela al propio shell (`pwsh -NoProfile -NonInteractive
  -Command '$PROFILE.CurrentUserAllHosts'`, ~250 ms) o usar la carpeta conocida *Documents*.
- **Política de ejecución.** pwsh: CurrentUser `Bypass` (en esta PC); 5.1: CurrentUser
  `RemoteSigned`. Un `.ps1` creado localmente no lleva *Mark of the Web*, así que `RemoteSigned`
  lo deja correr; con `Restricted` tampoco corre el perfil, así que no empeora nada; con
  `AllSigned` el dot-source fallaría (raro en un equipo personal: documentarlo).
- **Bloque en el perfil.** Solo ASCII (el perfil de 5.1 puede ser ANSI sin BOM y no hay que
  cambiarle la codificación), con marcadores y comprobación de existencia, y sin rutas literales
  (el nombre de usuario puede llevar tildes): usar `$env:LOCALAPPDATA`/`$HOME`. Probado en
  `temp_profile.ps1`:
  ```powershell
  # >>> local-delegate completion >>>
  if (Test-Path -LiteralPath "$env:LD_LAB_APPDATA\local-delegate\completion.ps1") { . "$env:LD_LAB_APPDATA\local-delegate\completion.ps1" }
  # <<< local-delegate completion <<<
  ```
- **Trampa de laboratorio:** lanzar `powershell.exe` desde Git Bash/pwsh hereda el `PSModulePath`
  de pwsh 7 y 5.1 no carga `Microsoft.PowerShell.Security` (`Get-ExecutionPolicy` falla). En las
  pruebas, lanzar 5.1 con `env -u PSModulePath` (o vaciándolo en el `env` del subproceso).
- **Otra trampa:** un fichero generado sin extensión `.ps1` no se ejecuta con dot-source (Windows lo
  abre con la aplicación asociada y no define nada). El fichero generado **debe** acabar en `.ps1`.

## 2. zsh

No hay zsh en esta PC: ni en Git Bash, ni en WSL Ubuntu-24.04 (`command -v zsh` vacío). Se probó en
un contenedor `alpine:3.20` (ya existente) con `apk add zsh` → **zsh 5.9**, con `docker run --rm`.

### zsh real con `compinit` y `zpty` (`test-zsh.zsh`, salida recortada)

```
=== [local-delegate ]
backend-params   Parámetros por rol
completion       Script de autocompletado
install          Instala la integración
=== [local-delegate ba]                       -> inserta «ckend-params»
=== [local-delegate backend-params set --]
--help    Muestra la ayuda
--param   Parámetro
--role    Rol
=== [local-delegate backend-params set --role ]
code        long        mechanical  vision
=== [local-delegate backend-params set --role=v]   -> inserta «ision»
=== [local-delegate install --mcp-mode http --lang ] -> inserta «e» y lista «en  es»
=== [local-delegate completion ]
bash        powershell  zsh
=== [local-delegate-mcp ins]                  -> inserta «tall»
```

### Modos de carga (`test-zsh-modes.zsh`)

```
1) source sin compinit:  /lab/proto.zsh:72: command not found: compdef
2) modo fpath (fichero _local-delegate):  registered: _local-delegate / _local-delegate
3) modo eval:  eval ms: 2.08  registered: _local_delegate
```

- **Estructura que funciona**: `#compdef local-delegate local-delegate-mcp` en la primera línea,
  una función `_local_delegate` que recorre `words[2..CURRENT-1]` y llama a `_describe` (con
  descripciones `nombre:descripción`, escapando `:` y `\`), `compadd -a` para valores fijos,
  `compset -P '*='` para `--opt=valor` y `_files` para valores libres. Al final, el mismo patrón que
  click (`click/shell_completion.py`, `_SOURCE_ZSH`):
  `if [[ "${zsh_eval_context[-1]}" == loadautofunc ]]; then _local_delegate "$@"; else compdef _local_delegate ...; fi`.
  Así el mismo fichero vale para `eval`/`source` y para `fpath`.
- `_arguments` (lo que usa `uv`/clap) es más rico pero mucho más difícil de generar bien; el
  recorrido propio + `_describe` es más simple y se comporta igual que en los otros dos shells.
- **Sin `compinit`** el script falla con `compdef: command not found`. Recomendación: guarda al
  principio, `(( $+functions[compdef] )) || { autoload -Uz compinit && compinit; }`, o avisar.
  En macOS con zsh por defecto `compinit` no siempre está en `.zshrc` (en Oh My Zsh sí).
- **Carga recomendada**: fichero generado en un directorio propio
  (`~/.local/share/local-delegate/completion/_local-delegate` o similar) añadido a `fpath` **antes**
  de `compinit` en `.zshrc` (bloque con marcadores). Alternativa: `source` del fichero después de
  `compinit` (2 ms). `eval "$(local-delegate completion zsh)"` paga el arranque de Python en cada
  sesión (0,3–2 s); es lo que documentan uv y gh, pero no es lo mejor para un `install` automático.
  Ojo: `compinit` cachea en `~/.zcompdump`; al cambiar el fichero en `fpath` puede hacer falta
  borrarlo (`compinit -D` en las pruebas lo evita).
- `ZDOTDIR` temporal para probar «instalado en el perfil» sin tocar el `.zshrc` real.

### Cómo probarlo en CI

`.github/workflows/ci.yml:131-133` ya tiene matriz `ubuntu-latest, windows-latest, macos-latest`.
`macos-latest` trae zsh (shell por defecto) y `/bin/bash` 3.2; `windows-latest` trae pwsh 7 y
Windows PowerShell 5.1. En `ubuntu-latest` zsh **no** viene por defecto (pendiente de confirmar en
la imagen actual; si hiciera falta, `sudo apt-get install -y zsh`). Las pruebas de zsh deben hacer
`skip` si no hay `zsh` y correr de verdad en macOS.

## 3. bash

### `COMP_WORDS` simulado (Git Bash 5.3.15 y bash 3.2.57 en contenedor `bash:3.2`)

Salida idéntica en las dos versiones (`test-bash.sh`):

```
[local-delegate ]                                  -> install backend-params completion
[local-delegate backend-params set --]             -> --role --param --help
[local-delegate backend-params set --role ]        -> mechanical long code vision
[local-delegate backend-params set --role =]       -> mechanical long code vision
[local-delegate backend-params set --role = v]     -> vision
[local-delegate backend-params set --role = code --param ] -> temperature top_p
[local-delegate completion ]                       -> powershell zsh bash
[local-delegate-mcp ins]                           -> install
```

Características de bash 3.2 confirmadas en el contenedor:

```
declare: -A: invalid option        <- sin arrays asociativos
type: compopt: not found           <- sin compopt
mapfile: command not found
```

### bash real con readline (WSL Ubuntu, bash 5.2, `script` como pty; `test-bash-pty.sh`)

```
[...set --role=v]  $ local-delegate backend-params set --role=vision
[...set --role=]   code        long        mechanical  vision
[local-delegate ba] $ local-delegate backend-params
[...--mcp-mode ]   http   stdio
```

- **`=` es separador de palabras** (`COMP_WORDBREAKS`): `--role=v` llega como `--role`, `=`, `v`.
  Hay que tratar `=` como palabra propia en el recorrido y, si la palabra actual es `=`, completar
  con prefijo vacío (readline reemplaza solo lo que va detrás del `=`). Confirmado con readline real.
  No depender de `_init_completion -n =` (paquete bash-completion, que en macOS no suele estar).
- **Compatibilidad 3.2**: nada de `declare -A`, `compopt`, `mapfile`, `${var,,}`; el prototipo usa
  `case "$path|$w" in ...` y `compgen -W` y corre igual en 3.2 y 5.3. `-o nosort` no existe antes
  de 4.4 (uv lo condiciona a la versión; nosotros no lo necesitamos).
- `complete -F _local_delegate local-delegate local-delegate-mcp`. Para rutas completas bash busca
  la compspec por el nombre tras la última barra (cita del manual). En Git Bash se teclea
  normalmente sin `.exe`; registrar también `local-delegate.exe` es gratis.
- Valores libres: `compgen -f -- "$cur"` (o `complete -o default`).
- Carga: `source` de un fichero generado desde `~/.bashrc` (bloque con marcadores). En macOS el
  shell de inicio de sesión lee `~/.bash_profile`, no `~/.bashrc`: decidir en la spec.

## 4. Cómo lo hacen otros

| Herramienta | Shells | ¿Estático? | Notas |
|---|---|---|---|
| pip 26.2.1 | bash, zsh, fish, powershell | **Dinámico** (llama a pip con `PIP_AUTO_COMPLETE=1` en cada Tab) | PowerShell redefine la función antigua `TabExpansion`, que **pwsh 7.6 ya no llama** (probado). |
| click 8.4.2 | bash, zsh, fish (sin PowerShell) | **Dinámico** (`_PROG_COMPLETE=bash_complete prog`) | bash exige ≥ 4.4 (`compopt`, `-o nosort`); zsh usa el patrón `loadautofunc`/`compdef`. |
| typer | bash, zsh, fish, powershell | **Dinámico** (sobre click) | No instalado aquí; no se probó. |
| gh 2.102.0 (cobra) | bash, zsh, fish, powershell | **Dinámico** (`gh __complete ...` con `Invoke-Expression`) | Registra sin `-Native` (equivale a `-Native` según la documentación). |
| uv 0.10.12 (clap) | bash, zsh, fish, powershell, … | **Estático** | PowerShell: `Register-ArgumentCompleter -Native`, ruta de subcomandos unida con `;` y un `switch` gigante; **no completa valores** de opciones (no hay `CompletionResult` para `always`), bash y zsh sí (`compgen -W "auto always never"`). 4 212 líneas en PowerShell. |

Conclusión: el único estático de referencia es clap/uv, y su PowerShell no completa valores. Lo
nuestro (estático, con valores fijos en los tres shells) no tiene un modelo que copiar tal cual; el
prototipo demuestra que se puede con tablas pequeñas y un recorrido común a los tres shells.

## 5. Pruebas automatizables (pytest)

| Shell | Cómo | Coste medido | Skip si |
|---|---|---|---|
| pwsh | `pwsh -NoProfile -NonInteractive -File test.ps1` que hace dot-source del script y llama a `TabExpansion2 $linea $col`; imprimir `CompletionText` | ~0,45 s por proceso con 19 casos (arranque ~0,25 s) | no hay `pwsh` |
| Windows PowerShell 5.1 | igual con `powershell.exe`, con `PSModulePath` quitado del entorno | ~0,66 s | no es Windows |
| bash | `bash --norc --noprofile test.sh script` que fija `COMP_WORDS`/`COMP_CWORD` y llama a la función | ~0,24 s (Git Bash) | no hay `bash` (en Windows, ojo: el `bash` del PATH puede ser WSL; usar el de Git) |
| zsh (determinista) | `zsh -f` con dobles de `compdef`, `_describe`, `compadd`, `compset`, `_files` y llamada directa a `_local_delegate` con `words`/`CURRENT` (`test-zsh-stub.zsh`) | < 0,1 s | no hay `zsh` |
| zsh (real) | `zpty` + `compinit -u -D` + Tab (`test-zsh.zsh`) | ~1–2 s; salida con ruido de terminal, mejor solo como prueba de humo | no hay `zsh` |

- Hacer **un solo proceso por shell** con todos los casos (no uno por caso) y comparar con una
  tabla esperada; así la prueba cuesta menos de un segundo por shell.
- La prueba de «instalado» (perfil temporal con el bloque de marcadores + dot-source + Tab) cuesta
  lo mismo y es la que pide el brief («probar la pieza no es probar el uso»): en PowerShell se
  simula con `-NoProfile` y dot-source del perfil temporal (no se puede redirigir `$PROFILE`); en
  zsh con `ZDOTDIR` temporal y `zsh -i`; en bash con `HOME` temporal y `bash -i` (o `--rcfile`).
- Todos los comandos con `timeout` (el prototipo se colgó una vez: una función llamada `Cp`
  chocaba con el alias `cp` de `Copy-Item`, que se quedó esperando entrada; usar `-NonInteractive`
  y `stdin` cerrado).

## 6. Recomendación

1. **Un modelo común**: el generador recorre argparse y produce un árbol
   `{ruta: {subcomandos, opciones, opciones_con_valor: {opción: [valores] | None}, posicionales: [valores]}}`.
   Los tres scripts implementan el mismo algoritmo: recorrer las palabras previas, ir bajando por
   subcomandos (comparación sensible a mayúsculas), saltar el valor de las opciones que lo llevan,
   ignorar `--x=y` ya completos, y para la palabra actual ofrecer: valores (si la anterior es una
   opción con valor o la actual es `--opt=`), opciones (si empieza por `-`) o subcomandos + valores
   posicionales.
2. **PowerShell**: un `Register-ArgumentCompleter -Native -CommandName @('local-delegate','local-delegate-mcp'[, '.exe'])`
   con las tablas **dentro** del scriptblock, `CompletionResult` con tooltip = ayuda del argparse
   (en el idioma de la CLI al generar), script **solo ASCII**, compatible con 5.1. Carga: fichero
   `.ps1` generado (p. ej. bajo `%LOCALAPPDATA%\local-delegate\`) y dot-source desde
   `$PROFILE.CurrentUserAllHosts` de **cada** edición instalada, con bloque de marcadores ASCII
   sin rutas literales.
3. **zsh**: fichero con `#compdef`, recorrido propio + `_describe`/`compadd`/`compset`/`_files`,
   patrón `loadautofunc`/`compdef`, guarda de `compinit`. Carga: directorio propio en `fpath` antes
   de `compinit` (o `source` después), bloque con marcadores en `${ZDOTDIR:-$HOME}/.zshrc`.
4. **bash**: función compatible con 3.2 basada en `case` y `compgen -W`, tratando `=` como palabra.
   Carga: `source` desde `~/.bashrc` (y decidir `~/.bash_profile` en macOS).
5. `local-delegate completion <shell>` imprime el script por la salida estándar (para quien prefiera
   `eval`/`Invoke-Expression`) y `install` escribe el fichero y el bloque del perfil; regenerar el
   fichero en cada `install`/`update` porque el árbol cambia con las versiones.

## Riesgos y preguntas abiertas

- **Codificación en PowerShell**: si el script no es ASCII, 5.1 lo rompe (sin BOM) y
  `Invoke-Expression` lo rompe en las dos ediciones. Mitigación probada: escapar todo carácter no
  ASCII. El perfil existente del usuario puede estar en ANSI: el bloque que se añade debe ser ASCII
  y no reescribir el resto del fichero con otra codificación ni otro fin de línea.
- **5.1 no completa `-`/`--` a secas** (límite del motor). Solo documentable.
- **Dos perfiles en Windows** (pwsh y 5.1) y **`Documents` redirigido por OneDrive**: pedir la ruta
  al propio shell. ¿`install` escribe en ambos o solo en el del shell detectado? Decisión de la spec.
- **ExecutionPolicy `AllSigned`** impediría el dot-source del fichero generado. ¿Se detecta y se
  avisa, o solo se documenta?
- **Comillas y caracteres especiales**: los valores de `choices` actuales son identificadores; el
  generador debería comprobar que cada valor cumple `^[A-Za-z0-9_.:/+-]+$` y, si no, entrecomillarlo
  (PowerShell) o rechazarlo con un error claro, en vez de emitir un script roto. En zsh hay que
  escapar `:` y `\` en `_describe`; en bash `compgen -W` parte por espacios.
- **Nombres con `-`**: no dan problemas como nombre de comando en ninguno de los tres; los nombres
  de función se derivan sustituyendo `-` por `_` (`_local_delegate`), y en zsh el fichero de `fpath`
  se llama `_local-delegate` (probado: se registra bien).
- **Opciones con `nargs` > 1, `append`, opciones cortas agrupadas (`-abc`) y `--` (fin de
  opciones)**: el prototipo no las cubre. Hay que revisar en el parser real si existen y decidir si
  se ignoran.
- **Tooltips/descripciones en es/en**: el script queda en el idioma de la CLI al generarlo; si el
  usuario cambia `LOCAL_DELEGATE_OUTPUT_LANGUAGE` tendrá que regenerarlo. ¿Aceptable?
- **zsh sin `compinit`** y caché `~/.zcompdump` tras actualizar el fichero de `fpath`.
- **macOS bash**: `~/.bashrc` no se lee en shells de inicio de sesión; zsh es el que importa allí.
- **CI**: confirmar si `ubuntu-latest` trae zsh; en Windows, el `bash` que encuentre pytest puede
  ser el de WSL (el brief lo advierte): fijar el de Git Bash o hacer skip.
- No se probó PSReadLine en una consola real (Tab y menú con Ctrl+Espacio): `TabExpansion2` es la
  misma API que usa PSReadLine, pero una comprobación manual final en la consola del usuario no
  sobra.

## Limpieza

Sin procesos vivos lanzados por esta investigación: WSL Ubuntu detenido (`wsl --terminate`, estado
`Stopped`), contenedores con `--rm`, imagen `bash:3.2` descargada y borrada (`docker rmi`), ningún
`pwsh`/`powershell.exe`/`zsh`/`script` propio en ejecución (el `powershell.exe` de las 17:10 es
anterior a la sesión). Dos tareas en segundo plano propias (un `find /` y una prueba colgada) se
detuvieron con `TaskStop`. No se tocaron perfiles reales ni el repo, salvo este fichero.
