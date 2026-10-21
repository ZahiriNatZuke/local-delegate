# Especificación: autocompletado de la CLI (`completion powershell|zsh|bash`)

## Contexto

Hoy la CLI `local-delegate` no completa nada con Tab: hay que saberse de memoria 12 subcomandos de
primer nivel, sus subcomandos (`llamaswap residency`, `test-window …`, `backend-params …`), unas 125
opciones y listas cerradas como los roles o las 21 claves de `backend-params`. El usuario lo pidió
el 2026-10-20 (backlog §1.12, punto 1b). La recomendación aprobada es un **generador propio sin
dependencias** que recorre el parser `argparse` y emite un script **estático** por shell:

- **PowerShell** (7 y Windows PowerShell 5.1) en la PC Windows;
- **zsh** en la Mac;
- **bash** por completitud (Linux y Git Bash).

Además, `install` puede dejarlo cargado en el perfil del shell, de forma opcional, idempotente y
reversible.

Mandan las decisiones de la sesión principal (encargo del redactor, puntos 1–10) y el
[brief](brief.md). La base técnica, con `fichero:línea`, está en [research.md](research.md), que
consolida [research-repo.md](research-repo.md) y [research-shells.md](research-shells.md). Donde
el código obliga a matizar una decisión, se dice en «Desviaciones propuestas».

### Vocabulario

- **Script**: el texto que imprime `local-delegate completion <shell>`. Es estático: no llama a
  Python ni a `local-delegate` al cargarse ni al pulsar Tab.
- **Modelo**: el árbol común que el generador saca del parser y del que salen los tres scripts.
  Cada **nodo** es una ruta de subcomandos (`()`, `("backend-params",)`,
  `("backend-params", "set")`…) con sus subcomandos, sus opciones y sus posicionales.
- **Valores fijos**: la lista cerrada que se ofrece para una opción o un posicional: `choices` de
  argparse o el atributo propio `completion_values`.
- **Valor libre**: una opción o un posicional que toma valor y no tiene valores fijos. Se deja al
  completado de rutas nativo del shell.
- **Fichero de completado**: el script guardado en disco por `install`, uno por shell.
- **Bloque de carga**: las líneas entre marcadores que `install` añade al perfil del shell y que
  solo cargan el fichero de completado.
- **Perfil**: el fichero de arranque del shell: `profile.ps1` de `CurrentUserAllHosts` en
  PowerShell, `.zshrc` en zsh, `.bashrc` o `.bash_profile` en bash.
- **Manifiesto**: `installed.json` en el directorio de completado; dice qué shells, ficheros y
  perfiles tocó `install`, en qué idioma y con qué versión (REQ-043).
- **Idioma configurado**: el que devuelve `install.plan_language(...)`; es el que usan `install` y
  `update` al generar.
- **HOME simulado**: `--home` apuntando fuera del HOME real (`install.is_simulated_home`,
  `install.py:150-161`).

## Requisitos

### Subcomando y generador

- **REQ-001 — Subcomando `completion`.** `local-delegate completion <shell>` con
  `shell ∈ {powershell, zsh, bash}` debe escribir el script en la salida estándar y salir con 0.
  - Debe escribir **bytes UTF-8 con fin de línea LF** en `sys.stdout.buffer`, en todas las
    plataformas: un `\r` rompe bash y zsh.
  - Un shell desconocido debe dar el error de argparse traducido y salir con 2.
  - El subcomando no lee la red ni el backend, ni escribe en disco.

  *Aceptación*: tests con `cli.run(["completion", s])` y `capsysbinary` para los tres shells:
  salida 0, ningún `b"\r"`, decodifica como UTF-8. `cli.run(["completion", "fish"])` sale con 2 y
  el mensaje sale del catálogo. `tests/test_smoke.py:215-233` lo despacha sin cambios.

- **REQ-002 — Script estático (lista blanca).** Los scripts no ejecutan nada fuera de sí mismos.
  - Las **únicas** sustituciones de comando admitidas son:
    - PowerShell: `$([char]0xNNNN)`, con la expresión `\$\(\[char\]0x[0-9A-F]{4}\)`;
    - bash: `$(compgen …)`;
    - zsh: ninguna.
  - La expansión aritmética `$((…))` no es una sustitución de comando y se admite en bash y zsh;
    el analizador la distingue de `$(`.
  - Cualquier otra `$(`, o una cuyo primer token sea `local-delegate`, `python`, `py` o `uv`, hace
    fallar el test.
  - Tampoco se admiten `Invoke-Expression`/`iex`, `eval` ni comillas invertidas que ejecuten
    comandos en bash o zsh.
  - Los nombres de los ejecutables solo pueden aparecer en la línea de registro (`-CommandName`,
    `#compdef`/`compdef`, `complete … -F`) y en la cabecera.

  *Aceptación*: un analizador de lista blanca recorre los tres scripts reales y no marca nada. Dos
  controles positivos que el analizador debe marcar: un script bash de prueba con
  `$(local-delegate --version)` y uno de PowerShell con `$(Get-Date)`.

- **REQ-003 — Modelo desde el parser real.** El generador (`src/local_delegate/completion.py`,
  nombres en inglés) debe construir el modelo recorriendo `cli.build_parser()`, sin listas a mano
  de subcomandos ni de opciones.
  - Cada nodo lleva: sus subcomandos visibles con su ayuda; todas las cadenas de opción visibles
    (`-h` y `--help` incluidas) con su ayuda, su aridad (bandera, valor obligatorio o valor
    opcional) y sus valores fijos; y sus posicionales **en orden**, cada uno con sus valores fijos.
  - El generador no debe modificar el parser, y debe construirlo con `build_parser()` en el idioma
    pedido (REQ-042).

  *Aceptación*:
  - test que compara el conjunto de rutas del modelo con las rutas que salen de recorrer los
    `_SubParsersAction` del parser con otro código independiente;
  - test de que un subcomando nuevo añadido a un parser de prueba aparece en el modelo sin tocar
    el generador.

- **REQ-004 — Excluir lo oculto.** No deben ofrecerse:
  - las acciones con `help=argparse.SUPPRESS` (`--reiniciar-calibracion`, `cli.py:1536-1542`;
    `benchmark --api-key`, `benchmark.py:1536`);
  - los subparsers que no tienen entrada en `_choices_actions` (sin `help`, como
    `recalcular-coste`, `cli.py:1510-1513`);
  - cualquier nombre que `deprecations.py` registre como `cli_command` o `cli_option`
    (`deprecations.py:58-59`), aunque tuviera `help`.

  *Aceptación*: los tres scripts no contienen `recalcular-coste`, `--reiniciar-calibracion` ni
  `--api-key`. El control positivo es un parser de prueba con un subcomando con `help` cuyo nombre
  se registra como retirado en un `DeprecatedName` de prueba: no sale.

- **REQ-005 — Valores fijos.** Se ofrecen como valores fijos los `choices` de argparse y el
  atributo propio `completion_values` (tupla de cadenas) de una `Action`, que solo lee el
  generador.
  - `backend-params set` y `unset`: `role` → `backend_params.ROLES` (`backend_params.py:33`) y
    `key` → las claves de `backend_params.ALLOWED_KEYS` (`backend_params.py:77`), en su orden.
  - `backend-params reset [role]` → `ROLES`.
  - **No** se añade `choices=` a esas acciones.

  *Aceptación*:
  - test del modelo: los posicionales de `("backend-params", "set")` son
    `[ROLES, tuple(ALLOWED_KEYS), libre]`;
  - test de no regresión: `cli.run(["backend-params", "set", "foo", "temperature", "1"])` sigue
    imprimiendo el texto de `unknown_role` del catálogo (`cli.py:480-485`), y no un error de
    argparse.

- **REQ-006 — Construcciones no soportadas.** El modelo cubre:
  - las acciones `store`, `store_true`, `store_false`, `store_const`, `append`, `append_const`,
    `count`, `help`, `version` y `_SubParsersAction`;
  - `nargs` `None`, `"?"` y `0`.

  Ante cualquier otra (`nargs` `"*"`, `"+"`, un entero mayor que 1, `REMAINDER`, `prefix_chars`
  distinto de `-`, alias de subparser, opciones cortas que no sean `-h`), el generador debe lanzar
  `UnsupportedConstructError` nombrando la ruta y la acción. No debe emitir un script parcial.

  *Aceptación*:
  - guardián: generar los tres scripts sobre el parser real no lanza;
  - control positivo: un parser de prueba por cada construcción no soportada hace lanzar con la
    ruta en el mensaje.

- **REQ-007 — Fichas seguras.**
  - Cada valor fijo y cada nombre de subcomando debe cumplir `^[A-Za-z0-9_.:/+-]+$`.
  - Cada cadena de opción debe cumplir `^--?[A-Za-z0-9][A-Za-z0-9_-]*$`.
  - Si no, el generador debe lanzar `UnsafeTokenError` con la ruta y el valor, y no emitir nada.

  *Aceptación*: el guardián de REQ-006 cubre también esto sobre el parser real. El control
  positivo son parsers de prueba con `choices=["a b"]`, `choices=["x;y"]` y `choices=["ñ"]`, que
  hacen lanzar.

- **REQ-008 — Descripciones en el idioma pedido.**
  - PowerShell (tooltip y texto de lista) y zsh (`_describe`) deben llevar la ayuda de cada
    subcomando y opción, en el idioma con que se genera (REQ-042).
  - Las ayudas con `%(...)s` o `%%` se expanden como lo hace argparse. Los saltos de línea y los
    espacios repetidos se colapsan.
  - Una entrada sin ayuda lleva su propio nombre como descripción.
  - bash no lleva descripciones (no las muestra). Su script es idéntico en los dos idiomas **salvo
    la línea de cabecera**.

  *Aceptación*: test con `render(s, lang="es")` y `render(s, lang="en")`:
  - los scripts de PowerShell y zsh difieren y contienen la ayuda de `backend-params` en el idioma
    pedido, comparada contra `t_lang(<lang>, "cli.help.backend_params")`;
  - los dos de bash son iguales al quitar la primera línea.

- **REQ-009 — Cabecera.**
  - Cada script debe empezar con una cabecera de comentario ASCII que diga la versión del paquete,
    el shell y el idioma, y que es generado: `# local-delegate <versión> completion <shell> lang=<xx> (generated; do not edit)`.
  - En zsh, la primera línea es `#compdef local-delegate local-delegate-mcp` y la cabecera va en la
    segunda.
  - La cabecera lleva `lang=` también en bash, aunque su cuerpo no dependa del idioma (REQ-008).
  - `completion.header_version(text)` devuelve la versión de la cabecera, o `None`.

  *Aceptación*: test de la forma de la cabecera en los tres y de `header_version` (también con un
  texto sin cabecera).

- **REQ-010 — Salida determinista.** Con la misma versión, el mismo idioma y el mismo parser, dos
  generaciones dan bytes idénticos. El orden es el de declaración en el parser.

  *Aceptación*: test que genera dos veces cada shell y compara bytes.

- **REQ-042 — Generar en un idioma dado.** `completion.render(shell, *, lang=None)` genera en
  `lang` (o en el idioma vigente si es `None`).
  - Para eso, un gestor de contexto nuevo, `i18n.override(lang)`, hace que dentro del bloque
    `i18n.lang()`, `t()` y el armazón de argparse (`i18n.argparse_gettext`) usen ese idioma.
  - El generador construye el parser **dentro** de ese bloque. Al salir se restaura el estado
    anterior, también ante una excepción.
  - `local-delegate completion <shell>` usa el idioma vigente del proceso.

  *Aceptación*:
  - `render("powershell", lang="en")` con la suite en `es` da la ayuda inglesa, y al salir
    `i18n.lang()` vuelve a ser `es`;
  - lo mismo con una excepción lanzada dentro del bloque.

- **REQ-011 — Ejecutables registrados.** Los tres scripts deben registrar `local-delegate` y
  `local-delegate-mcp`, sin variantes `.exe`: el laboratorio mostró que PowerShell y bash
  resuelven `local-delegate.exe` y la ruta completa con el nombre corto (research-shells §1,
  hallazgo 1; §3).

  *Aceptación*: los tests de integración de REQ-019 completan con las líneas `local-delegate-mcp
  ins`, `local-delegate.exe ins` y `& "C:\x y\local-delegate.exe" ins` en PowerShell, y
  `local-delegate-mcp ins` en bash y zsh.

### Comportamiento común de los tres scripts

Los tres scripts implementan el mismo recorrido. Sobre las palabras **anteriores** al cursor:

- bajan por subcomandos con comparación **sensible a mayúsculas**;
- saltan el valor de las opciones que lo llevan;
- ignoran las `--opción=valor` ya completas;
- cuentan los posicionales consumidos.

Para la palabra actual ofrecen, filtrando por prefijo, el primer caso que aplique:

1. los valores de la opción anterior;
2. los de la forma `--opción=`;
3. las opciones del nodo, si la palabra empieza por `-`;
4. los subcomandos del nodo más los valores fijos del siguiente posicional.

- **REQ-012 — Subcomandos en todos los niveles.**

  *Aceptación*, en los tres shells:
  - `local-delegate ` → los 13 subcomandos de primer nivel visibles (los 12 de hoy más `completion`);
  - `local-delegate ba` → `backend-params`;
  - `local-delegate backend-params ` → `show set unset reset`;
  - `local-delegate llamaswap ` → `residency`;
  - `local-delegate test-window ` → `start stop add list`;
  - `local-delegate BACKEND-PARAMS ` **no** baja al subcomando (sensible a mayúsculas);
  - `local-delegate --version backend-params ` → los cuatro de `backend-params`.

- **REQ-013 — Opciones del nodo.** Si la palabra actual empieza por `-`, se ofrecen todas las
  opciones visibles del nodo actual.
  - Las de tipo `append` se siguen ofreciendo aunque ya se hayan usado.
  - No se filtran las mutuamente excluyentes.

  *Aceptación*:
  - `local-delegate install --mcp` → `--mcp-mode`;
  - `local-delegate serve --` → `--host --port --log-level --help` (en PowerShell 5.1 se prueba con
    `--l`, ver REQ-020);
  - `local-delegate install --clients claude --cl` → `--clients`.

- **REQ-014 — Valores de opción.** Tras una opción con valores fijos se ofrecen sus valores, y en
  la forma `--opción=prefijo` también.
  - En PowerShell, la forma `=` llega como una palabra y el resultado insertado es
    `--opción=valor`.
  - En bash, `=` es palabra aparte (`COMP_WORDBREAKS`) y se completa con prefijo vacío tras `=`.
  - En zsh se usa `compset -P '*='`.
  - Una opción de valor opcional (`nargs="?"`) ofrece sus valores, salvo que la palabra empiece por
    `-`: entonces se ofrecen opciones.

  *Aceptación*:
  - `install --mcp-mode ` → `stdio http`;
  - `install --mcp-mode=h` → `--mcp-mode=http` (PowerShell) o `http` tras `=` (bash y zsh);
  - `serve --log-level w` → `warning`;
  - `benchmark --role ` → los 4 roles;
  - `recompute-cost --reset-calibration ` → `five_hour seven_day`;
  - `install --shell-completion ` → `auto powershell zsh bash`;
  - `install --shell-completion --d` → `--dry-run`.

- **REQ-015 — Posicionales por posición.** Los valores fijos de un posicional se ofrecen solo en su
  posición.

  *Aceptación*:
  - `backend-params set ` → los 4 roles;
  - `backend-params set code ` → las 21 claves;
  - `backend-params set code top_p ` → nada propio (valor libre);
  - `backend-params unset vision t` → `temperature top_k top_p typical_p` (las claves que empiezan por `t`);
  - `backend-params reset ` → los 4 roles;
  - `completion ` → `powershell zsh bash`.

- **REQ-016 — Valores libres al completado nativo.** Para un valor libre, el script no ofrece
  candidatos propios y deja actuar al completado de rutas del shell:
  - PowerShell: no devolver nada;
  - bash: `COMPREPLY` vacío, con el registro `complete -o default` (existe en 3.2), para que
    readline complete rutas sin partirlas por los espacios;
  - zsh: `_files`.

  *Aceptación*:
  - `install --home ` en PowerShell devuelve rutas del directorio de trabajo (una carpeta de prueba
    con un fichero conocido);
  - en bash, `COMPREPLY` queda vacío y la compspec registrada (`complete -p local-delegate`)
    incluye `-o default`; además, la prueba con readline real (paso 3b de REQ-039, Linux) completa un fichero
    cuyo nombre lleva un espacio;
  - en zsh se comprueba la llamada a `_files` con el doble de la prueba determinista.

- **REQ-017 — Sin coincidencias, vacío.** Un prefijo que no casa con nada devuelve cero candidatos
  propios.

  *Aceptación*: en los tres shells, `local-delegate zzz` y `backend-params set zzz` devuelven cero
  candidatos (control positivo obligatorio de REQ-038).

### PowerShell

- **REQ-018 — Solo ASCII y dos formas de carga.** El script de PowerShell debe tener todos sus
  bytes menores que `0x80`.
  - Cada carácter no ASCII va como `$([char]0xNNNN)` dentro de comillas dobles (pares de
    sustitutos para fuera del BMP), con `` ` ``, `"` y `$` escapados.
  - Debe funcionar sin BOM en Windows PowerShell 5.1 y pwsh 7, tanto con dot-source del fichero
    como con `local-delegate completion powershell | Out-String | Invoke-Expression`.

  *Aceptación*:
  - test de bytes (`max(script) < 0x80`) en `es`;
  - test de integración en 5.1 y 7: tras cargarlo por las dos vías, el tooltip de
    `backend-params` es idéntico (con tildes) a `t("cli.help.backend_params")` en `es`.

- **REQ-019 — Compatibilidad con 5.1 y sesión limpia.**
  - El script no usa `?:`, `??`, `??=`, `?.`, `&&`/`||` entre canalizaciones, `` `u{…} ``,
    `using namespace` ni `[CompletionResult]::new`.
  - Todas sus tablas viven dentro del scriptblock: cargarlo no deja variables nuevas en la sesión.
  - Los resultados se emiten uno a uno como `System.Management.Automation.CompletionResult` con
    `CompletionText`, `ListItemText`, tipo (`ParameterName` para opciones y `ParameterValue` para
    el resto) y `ToolTip`.
  - El recorrido usa `-ccontains` y solo las palabras con `Extent.EndOffset < $cursorPosition`.

  *Aceptación*:
  - test estático de sintaxis prohibida;
  - integración en 5.1 (`powershell.exe` con `PSModulePath` quitado del entorno) y en 7 con
    `TabExpansion2` sobre los casos de REQ-011 a REQ-017, más el cursor a mitad de línea
    (`local-delegate backend-params set code` con el cursor tras `backend-params`);
  - recuento de variables antes y después de cargar: diferencia 0.

- **REQ-020 — Límite conocido de 5.1.** En Windows PowerShell 5.1 el motor no llama al completador
  con `-` o `--` a secas (research-shells §1, hallazgo 4). No se intenta esquivar: se documenta
  (REQ-041), y los tests de 5.1 usan al menos una letra tras `--`.

  *Aceptación*: test en 5.1 que documenta el límite: `serve --` da cero resultados y `serve --l`
  da `--log-level`. Si un día 5.1 sí completara `--`, el test lo diría.

### bash y zsh

- **REQ-021 — bash compatible con 3.2.**
  - El script no usa `declare -A`, `compopt`, `mapfile`/`readarray`, `${var,,}`/`${var^^}` ni
    `-o nosort`.
  - Usa `case` y `compgen -W`, y registra con
    `complete -o default -F _local_delegate local-delegate local-delegate-mcp`.

  *Aceptación*:
  - test estático de construcciones prohibidas;
  - integración con `COMP_WORDS`/`COMP_CWORD` simulados (incluido `=` como palabra) en el bash del
    sistema: Git Bash en Windows (nunca el de WSL), bash de ubuntu y `/bin/bash` 3.2 de macOS;
  - en macOS, esa prueba lanza `/bin/bash` por ruta y comprueba `BASH_VERSINFO[0] == 3` (shell
    `bash3` de REQ-037).

- **REQ-022 — zsh.** El script de zsh debe:
  - empezar por `#compdef local-delegate local-delegate-mcp`;
  - definir `_local_delegate` con recorrido propio sobre `words[2,CURRENT-1]`;
  - usar `_describe` con `:` y `\` escapados en las descripciones, `compadd` para valores fijos,
    `compset -P '*='` y `_files`;
  - terminar con el patrón `loadautofunc`/`compdef` (vale para `source` y para `fpath`);
  - llevar la guarda `(( $+functions[compdef] )) || { autoload -Uz compinit && compinit -i; }`
    antes de `compdef`.

  *Aceptación*:
  - prueba determinista con `zsh -f` y dobles de `compadd`/`_describe`/`compset`/`_files` sobre los
    casos de REQ-012 a REQ-017;
  - prueba real con `zpty` + `compinit -u -D` (humo: `local-delegate backend-params set ` → los 4 roles;
    `local-delegate completion ` → `bash powershell zsh`);
  - prueba de las dos cargas: `source` del fichero y fichero `_local-delegate` en `fpath`.

### `install`, `uninstall`, `update` y `doctor`

- **REQ-023 — Opción `--shell-completion`.** La tienen `install` y `uninstall` (no
  `update`), con `nargs="?"`, `const="auto"`, `action="append"` y
  `choices=("auto", "powershell", "zsh", "bash")`.
  - Se puede repetir (`--shell-completion powershell --shell-completion bash`), como `--clients`
    (`cli.py:1554`). No acepta listas separadas por comas.
  - Sin la opción, `install` no toca ni ficheros de completado ni perfiles.
  - Qué hace en `uninstall`: REQ-032.

  *Aceptación*:
  - tests del parser en los dos subcomandos: sin valor → `["auto"]`; repetida → las dos;
    `--shell-completion fish` → 2;
  - `update --shell-completion` → 2;
  - test con HOME simulado: `install` sin la opción deja igual el snapshot de perfiles y del
    directorio de completado.

- **REQ-024 — Qué shells se resuelven.**
  - **`auto`**:
    - Windows: cada edición de PowerShell cuyo ejecutable exista (`pwsh` y `powershell`, buscados
      con `shutil.which`), salvo las que salta REQ-044;
    - macOS: zsh;
    - Linux y demás: bash, y además zsh si el nombre base de `$SHELL` es `zsh`.
  - **`powershell` explícito**: en Windows, las dos ediciones que existan, con la misma regla de
    REQ-044.
  - **«bash existe» en Windows** quiere decir que hay Git Bash, con la misma derivación desde `git`
    que REQ-037. `System32\bash.exe` (WSL) no cuenta.
  - Un shell pedido cuyo ejecutable no existe se salta con un aviso del catálogo, sin escribir nada
    para él y sin cambiar el código de salida.
  - La búsqueda de ejecutables, la plataforma y `$SHELL` son inyectables para los tests.

  *Aceptación*: tests parametrizados por plataforma, `$SHELL` y ejecutables presentes (dobles),
  incluidos:
  - «Windows sin pwsh» (solo 5.1);
  - «`powershell` pedido sin ninguna edición» (aviso, salida 0);
  - «`bash` en Windows con solo `System32\bash.exe`» (aviso, nada escrito).

- **REQ-025 — Ruta del perfil y política de ejecución.**
  - **PowerShell con HOME real**: una sola consulta por edición devuelve la ruta
    `$PROFILE.CurrentUserAllHosts` y la política efectiva:
    `-NoProfile -NonInteractive -Command "[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($PROFILE.CurrentUserAllHosts + [char]10 + (Get-ExecutionPolicy)))"`.
    - Va con `stdin` cerrado y tope de 20 s, y quita `PSModulePath` del entorno al lanzar
      `powershell.exe`. En las dos ediciones quita además `PSExecutionPolicyPreference`, que guarda
      la política de ámbito `Process` del padre (p. ej. un PowerShell abierto con
      `-ExecutionPolicy Bypass`) y falsearía la política consultada.
    - Python decodifica la salida en Base64 de UTF-16 LE y separa por el salto de línea. Así sirve
      para `Documents` redirigido por OneDrive y para rutas con tildes.
    - Si la consulta falla, la ruta de respaldo sale de la carpeta conocida *Documents*
      (`SHGetKnownFolderPath(FOLDERID_Documents)` por `ctypes`) más `PowerShell\profile.ps1` o
      `WindowsPowerShell\profile.ps1`. La política queda como «desconocida» (REQ-044).
    - En macOS y Linux (pwsh), el respaldo es `~/.config/powershell/profile.ps1`.
  - **zsh**: `${ZDOTDIR:-$HOME}/.zshrc`.
  - **bash**: `~/.bash_profile` en macOS (Terminal abre shells de inicio de sesión) y `~/.bashrc`
    en el resto, Git Bash incluido.
  - **HOME simulado**: nunca se pregunta al shell y se ignora `ZDOTDIR`.
    - Las rutas salen del HOME simulado: `<home>/Documents/PowerShell/profile.ps1` y
      `<home>/Documents/WindowsPowerShell/profile.ps1` en Windows,
      `<home>/.config/powershell/profile.ps1` fuera de Windows, `<home>/.zshrc` y
      `<home>/.bashrc`/`.bash_profile`.
    - La política se inyecta; por defecto, `RemoteSigned`.

  *Aceptación*:
  - tests con dobles del subproceso: decodificación de una ruta con `ó` y espacios y de la
    política; respaldo cuando el proceso falla o vence el tope; `PSModulePath` ausente del entorno
    pasado a `powershell.exe` y `PSExecutionPolicyPreference` ausente en las dos ediciones; `ZDOTDIR` respetado con HOME real e ignorado con HOME simulado;
  - un test en Windows (se salta fuera) que llama de verdad a `pwsh` y compara con la ruta que da
    `pwsh -NoProfile -Command $PROFILE.CurrentUserAllHosts`.

- **REQ-026 — Fichero de completado.**
  - Se escribe en `<dir>/completion/` con los nombres `local-delegate.ps1`, `local-delegate.bash` y
    `_local-delegate` (zsh, válido también para `fpath`).
  - `<dir>` lo calcula **una sola función**, `shell_profiles.completion_dir(home, data_dir=None)`,
    que usan `install`, `uninstall`, `update` y el check:
    - `data_dir`, si se da;
    - si no, `config.LOG_DIR` con HOME real o con `LOCAL_DELEGATE_LOG_DIR` fijada;
    - con HOME simulado sin esa variable, `<home>/.local/share/local-delegate` (desviación 2).
  - El contenido es **byte a byte** `render(shell, lang=L)`, donde `L` es el **idioma configurado
    del producto** en ese momento: `install.plan_language(...).lang`, con su regla de hoy
    (`install.py:1075-1105`). Es el mismo idioma con que
    `install` escribe la skill y `update` refresca el catálogo (`update.py:326-330`).
  - Se escribe sin `.bak` (es nuestro) y de forma atómica (temporal + `os.replace`).
  - Las dos ediciones de PowerShell comparten el mismo `local-delegate.ps1`.

  *Aceptación*:
  - test con HOME simulado: los ficheros existen y son iguales a `render(shell, lang=L)`;
  - test con `data_dir` explícito;
  - test de que no queda `.bak` del fichero de completado;
  - test de que `doctor --home <tmp>` encuentra lo que escribió `install --home <tmp>`;
  - test con `LOCAL_DELEGATE_LANG=en` y la suite en `es`: el fichero sale en `en`.

- **REQ-027 — Bloque de carga.**
  - Va entre los marcadores ASCII `# >>> local-delegate completion >>>` y
    `# <<< local-delegate completion <<<`, y contiene **solo** la carga condicionada del fichero.
  - PowerShell: `if (Test-Path -LiteralPath "<ruta>") { . "<ruta>" }`, con la ruta escrita con el
    mismo escape ASCII de REQ-018.
  - bash: `[ -f '<ruta>' ] && . '<ruta>'`.
  - zsh: `[[ -f '<ruta>' ]] && source '<ruta>'`.
  - En bash y zsh, la ruta va entre comillas simples con `'` escapada como `'\''`; en Windows,
    con barras `/`.
  - El bloque es ASCII también cuando la ruta tiene caracteres no ASCII en PowerShell. En bash y
    zsh la ruta va en UTF-8.

  *Aceptación*:
  - tests del texto del bloque con una ruta con `ó`, espacio y `'`;
  - integración (REQ-039): el bloque carga el fichero en el shell real;
  - control positivo: con el fichero borrado, cargar el perfil no da error y no completa (paso 4
    del E2E, REQ-039).

- **REQ-028 — El resto del perfil no cambia.** Fuera del bloque, el perfil queda **byte a byte**
  igual.
  - Se conserva la codificación: UTF-8 con y sin BOM, UTF-16 LE/BE con BOM, y ANSI (bytes que no
    son UTF-8 válido, como un perfil de 5.1 en cp1252 con tildes).
  - Se conserva el fin de línea dominante.
  - El perfil se escribe en su sitio, siguiendo enlaces simbólicos (REQ-045).
  - Antes de modificarlo se hace una copia propia (REQ-046).
  - **No se toca y se informa** un perfil que:
    - no se puede leer;
    - tiene bytes NUL sin BOM de UTF-16 (sería un UTF-16 sin marca y se corrompería);
    - tiene un marcador sin su pareja (un `# >>>` sin `# <<<` o al revés).
  - Un **error de escritura** (solo lectura, fichero bloqueado) se informa con el patrón de hoy
    (`install.not_written`, `install.py:410`). Los demás shells siguen, y el código de salida es el
    de `apply` con fallos.
  - No se reutilizan `_read_text`/`_write_text` tal cual (desviación 1).

  *Aceptación*: tests de ida y vuelta (`install` y luego `uninstall`) con perfiles semilla en cada
  codificación y fin de línea, comparando los bytes de antes y de después. Más:
  - un perfil con NUL sin BOM y otro con un marcador huérfano: no se tocan y hay aviso;
  - un perfil de solo lectura: aviso de no escrito, salida 1, y los demás shells sí se escriben.

  El caso ANSI es el control positivo: con `_read_text` + `upsert_block` el contenido se perdería.

- **REQ-029 — Idempotencia.** Un segundo `install --shell-completion` con la misma versión e idioma
  no cambia ningún byte de perfiles, ficheros de completado ni manifiesto, y lo informa como «ya al día».

  *Aceptación*: test con snapshot tras la primera y la segunda pasada; el E2E (REQ-039) instala
  dos veces.

- **REQ-030 — Independiente de los clientes, con orden fijo.** `_run_install`, tanto en
  `install` como en `uninstall`, sigue este orden:
  1. resuelve los clientes (un `--clients` inválido sale con 2 **sin escribir nada**);
  2. calcula el idioma con `install.plan_language(...)` sobre unas `Options` mínimas;
  3. planifica y aplica el autocompletado;
  4. sigue con la rama «ningún cliente» (`cli.py:203-212`) o con el flujo de clientes.

  - El autocompletado no cuenta como «sin componentes» (`cli.py:225-227`).
  - `install --shell-completion` en una máquina sin Claude, Codex ni opencode escribe el
    autocompletado, dice que lo escribió (no solo «no se escribió nada» de
    `cli.install.no_client.nothing_written`) y sale con 0, o con 1 si la escritura del
    autocompletado falló.
  - Con `--no-hooks --no-skill --no-memory --no-mcp --shell-completion` no sale con 2.

  *Aceptación*: los tres tests con HOME simulado vacío, afirmando el texto nuevo del catálogo y el
  código de salida (también el de fallo, con un perfil de solo lectura). Test de que
  `--clients nope --shell-completion` sale con 2 y no crea nada.

- **REQ-031 — `--dry-run`.** En `install` y en `uninstall`, imprime cada acción (fichero de
  completado, bloque con su texto literal como `Action.literal`, `install.py:222-232`, y manifiesto)
  y no escribe nada. Puede leer los perfiles y preguntar la ruta y la política al shell.

  *Aceptación*: tests con snapshot antes y después, idénticos, en `install --dry-run` y en
  `uninstall --dry-run` (este, tras una instalación real); la salida de `install` contiene el
  marcador de inicio.

- **REQ-032 — `uninstall`.**
  - **Qué casos lo quitan**:
    - `uninstall` **sin restricciones** quita el autocompletado además de lo de los clientes. Se
      define por los datos, no por la forma de las opciones: los cuatro componentes activos
      (`args.hooks`, `args.skill`, `args.memory` y `args.mcp` en `True`), `--clients` ausente o
      solo `auto`, y `--target` ausente. `--no-client-cli`, `--agents`, `--dry-run`, `--python` y
      `--home` no cuentan como restricción;
    - `uninstall --shell-completion [shell]` quita **solo** el autocompletado de esos shells
      (`auto` = todos) y no toca clientes. Si además lleva `--clients`/`--target` explícitos, quita
      el autocompletado **y** esos clientes;
    - un `uninstall` parcial por shell quita del manifiesto solo la entrada de ese shell, y borra
      el manifiesto solo si queda sin entradas;
    - `uninstall` restringido a clientes o componentes no lo toca.
  - Este paso va también antes de la salida por «ningún cliente» y de la de «sin componentes»
    (REQ-030).
  - **Perfiles**: quita el bloque de la unión de los perfiles listados en el manifiesto (REQ-043) y
    los candidatos de REQ-025 que existan (las dos ediciones de PowerShell, `.zshrc`, `.bashrc` y
    `.bash_profile`).
  - **Ficheros**: borra los tres ficheros de completado, el manifiesto, y el directorio
    `completion/` si queda vacío. Es inocuo si no hay nada.
  - **Vuelta atrás exacta**: el perfil vuelve **byte a byte** a como estaba antes de `install`.
    - Si el manifiesto dice que `install` **creó** el perfil y este queda vacío (o solo con
      blancos), se borra.
    - Si además `install` creó su carpeta padre y queda vacía, se borra también.
    - Un perfil que ya existía no se borra nunca, aunque quede vacío.

  *Aceptación*:
  - ida y vuelta: perfil inexistente → no existe, ni su carpeta creada; perfil vacío preexistente
    → sigue existiendo y vacío; perfil con salto final → idéntico; perfil sin salto final →
    idéntico;
  - `uninstall` sin clientes y sin instalación previa: sale con 0 y no crea nada;
  - `uninstall --no-client-cli` **sí** lo quita (el procedimiento del sandbox no es una
    restricción);
  - `uninstall --clients codex` y `uninstall --no-hooks` lo dejan intacto (controles positivos del
    caso restringido);
  - `uninstall --shell-completion zsh` con zsh y bash instalados: quita zsh, deja bash y su
    entrada del manifiesto;
  - `uninstall --shell-completion --clients codex` quita el autocompletado y Codex;
  - `uninstall --shell-completion` lo quita y deja intactos hooks, skill, memoria y MCP.

- **REQ-043 — Manifiesto de instalación.**
  - `install` escribe `<dir>/completion/installed.json` (UTF-8, LF, escritura atómica) con:

    ```json
    {"version": 1, "generator": "<versión del paquete>", "lang": "<idioma>",
     "shells": [{"shell": "powershell", "file": "<ruta>",
                 "profiles": [{"path": "<ruta>", "created": true, "created_parent": false}]}]}
    ```

  - Lo leen `doctor` (REQ-033), `update` (REQ-034) y `uninstall` (REQ-032).
  - Al reinstalar se fusiona: un perfil ya listado conserva su `created` original.
  - Un manifiesto ilegible no hace lanzar a nadie: `doctor` da `unknown` y `uninstall` sigue con
    los candidatos.

  *Aceptación*:
  - tests de escritura;
  - fusión en una segunda instalación con otro shell;
  - lectura de un manifiesto roto en los tres verbos.

- **REQ-044 — Política de ejecución de PowerShell.**
  - Con la política efectiva de REQ-025, una edición cuya política impide ejecutar el fichero se
    **salta**, sin escribir perfil ni bloque para ella. Se dice con un aviso del catálogo que
    explica cómo arreglarlo (`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`).
  - Impiden ejecutarlo `Restricted`, `AllSigned` y `Undefined`; `Undefined` resuelve a
    `Restricted` en un Windows de escritorio.
  - Vale igual para `auto` y para `powershell` explícito: nunca se deja un perfil que dé error al
    abrir el shell.
  - Si la política es desconocida (consulta fallida), se escribe y se avisa de que no se pudo
    comprobar.
  - Si se saltan **todas** las ediciones, no se escribe `local-delegate.ps1` ni su entrada del
    manifiesto (si no, el check daría «ficheros sin manifiesto» para siempre).
  - El código de salida no cambia.

  *Aceptación*: tests con doble:
  - `Restricted` → se salta con aviso y salida 0;
  - `AllSigned` → se salta;
  - `RemoteSigned` → se escribe;
  - consulta fallida → se escribe y avisa;
  - con `powershell` explícito y `Restricted` → se salta;
  - las dos ediciones en `Restricted` → ni fichero `.ps1` ni entrada en el manifiesto.

- **REQ-045 — Perfiles enlazados.**
  - Si el perfil es un enlace simbólico (dotfiles), se escribe en el destino resuelto
    (`Path.resolve()`), sin `os.replace` sobre el enlace, y el enlace se conserva.
  - La copia de REQ-046 va junto al destino.

  *Aceptación*: test POSIX (se salta en Windows sin privilegio de enlaces y corre en Linux y
  macOS): `.zshrc` como enlace a `dotfiles/zshrc`; tras `install` y `uninstall` sigue siendo un
  enlace y el destino es byte a byte el mismo.

- **REQ-046 — Copia de seguridad propia.**
  - Antes de modificar un perfil, la copia va a `<perfil>.local-delegate.bak`, nunca a
    `<perfil>.bak` (que suele ser del usuario).
  - `install` solo la crea si no existe, para que guarde el estado previo a la primera
    instalación.
  - `uninstall` no la pisa si ya existe. Tras quitar el bloque, la borra si el perfil quedó byte a
    byte igual a ella. Si no existía, la crea antes de escribir, y entonces se queda, **salvo** que
    el manifiesto diga que `install` creó el perfil: entonces no se hace copia (el estado previo
    era «no existe»).

  *Aceptación*: ida y vuelta con el perfil inexistente → ni perfil, ni copia, ni carpeta; con un
  `.bashrc.bak` sembrado, la ida y vuelta lo deja intacto; tras la ida y
  vuelta no queda `.local-delegate.bak`; con un perfil editado por el usuario entre `install` y
  `uninstall`, la copia se queda.

- **REQ-033 — Check `scaffold.shell_completion` en `doctor`.** Lee el manifiesto (REQ-043) y los
  ficheros del directorio de REQ-026. No lanza shells, y su veredicto **no depende del idioma de la
  sesión**.
  - **`ok`**, «no instalado (opcional)», si no hay manifiesto ni ficheros.
  - **`ok`** si:
    - cada fichero listado es igual a `render(shell, lang=<idioma del manifiesto>)`;
    - y cada perfil listado contiene el bloque completo apuntando a su fichero.

    El detalle dice el idioma y los perfiles.
  - **`warn`**, con `fix_hint` `local-delegate update`, si un fichero difiere. El detalle dice la
    versión de la cabecera frente a la instalada, o «contenido distinto» si coinciden.
  - **`warn`**, con `fix_hint` `local-delegate install --shell-completion`, si:
    - falta un fichero listado;
    - o un perfil listado ya no tiene el bloque (borrado por el usuario o por otro programa);
    - o hay ficheros sin manifiesto.
  - **`unknown`** si el manifiesto, un fichero o un perfil listado no se pueden leer.
  - La tabla de checks de `docs/wiki/Integration-install.md` gana su fila.
  - La cifra pasa de 25 a 26 en todos los sitios que la dicen:
    - la wiki: «veintiséis» en `Integration-install.md:182` y `:340`;
    - los cinco textos del docstring de `checks.py` (`checks.py:5`, `:2186` y los que lista
      `tests/test_checks.py:1210-1216`);
    - `src/local_delegate/doctor.py:71` («the 25 checks»);
    - `_CHECK_COUNT_WORDS` (`tests/test_wiki.py:35-48`) y `_NUMBER_WORDS`
      (`tests/test_checks.py:1194`);
    - las aserciones `== 25` (`tests/test_checks.py:93`, `tests/test_doctor.py:267`,
      `tests/test_doctor_english.py:89`) y el docstring de `tests/test_doctor_english.py:3`.

  *Aceptación*: tests del probe en todos los estados, con estos casos:
  - `warn` por versión, con una cabecera 0.0.1;
  - `warn` por bloque borrado de un perfil listado (control positivo del falso OK);
  - fichero generado en `es`, con `doctor` en `LOCAL_DELEGATE_LANG=en` → `ok` en los dos idiomas,
    con el mismo veredicto (invariante de `tests/test_doctor_english.py`).

  `tests/test_wiki.py` en verde.

- **REQ-034 — `update` regenera.**
  - `update` reescribe los ficheros listados en el manifiesto que difieran de
    `render(shell, lang=L)`, con `L` el idioma configurado de REQ-026 (el de `plan_language`, como
    `plan_catalog_refresh`). Actualiza el idioma y la versión del manifiesto.
  - Así resuelve una versión nueva **y** un cambio de idioma.
  - No crea ficheros no listados ni toca perfiles.
  - Va como paso propio, no en `REPAIRS` (desviación 3), y funciona **sin ningún cliente
    presente**.
  - Una segunda pasada no planifica nada.

  *Aceptación*: tests de `update` con HOME simulado:
  - **sin ningún cliente** y fichero de una versión vieja → una acción, y queda igual a `render`;
  - fichero en `es` con el idioma configurado en `en` → una acción, y el manifiesto dice `en`;
  - segunda pasada → cero acciones;
  - sin manifiesto → cero acciones.

### Textos, guardianes y dependencias

- **REQ-035 — Catálogo y nombres.**
  - Todo texto nuevo para personas (ayuda de `completion` y de `--shell-completion`, mensajes de
    `install`/`uninstall`/`update`, detalle y título del check) vive en
    `resources/i18n/{es,en}/*.json` con las mismas claves y marcadores.
  - `["completion"]` entra en `HELP_PATHS` (`tests/test_cli_english.py:34-56`).
  - Los nombres de código van en inglés.

  *Aceptación*: `test_i18n_parity.py`, `test_no_uncatalogued_text.py`, `test_cli_english.py` y
  `test_detect_spanish_names.py` en verde.

- **REQ-036 — Sin dependencias y plantillas empaquetadas.**
  - `pyproject.toml` no gana dependencias de runtime.
  - Las plantillas de los tres shells viven en `src/local_delegate/resources/completion/` como
    ficheros de texto, no como constantes Python, y viajan en el wheel.

  *Aceptación*: `git diff main -- pyproject.toml` sin cambios en `dependencies`. El job
  `install-smoke` ejecuta `local-delegate completion` para los tres shells contra el wheel
  instalado y comprueba la cabecera.

### Pruebas, CI y verificación

- **REQ-037 — Shells reales en CI, sin saltos silenciosos.**
  - Cada prueba de integración se salta con motivo si su shell falta, **salvo** que el shell esté
    en la variable de prueba `COMPLETION_TEST_REQUIRE_SHELLS` (lista separada por comas): entonces
    el ayudante llama a `pytest.fail`.
  - Cada prueba de shell registra su shell en `user_properties` (con `record_property("shell",
    "<nombre>")` o, desde el marcador `shell("<nombre>")`, en `pytest_runtest_setup` con
    `item.user_properties.append(("shell", nombre))`). Bajo `pytest-xdist` el controlador solo ve
    los **nombres** de los marcadores (`report.keywords`), no sus argumentos; `user_properties` sí
    viaja en el informe.
  - Un hook en `tests/conftest.py` acumula, en `pytest_runtest_logreport`, las pruebas `passed`
    por shell leyendo `report.user_properties`. En `pytest_sessionfinish`, **solo en el
    controlador** (sin `config.workerinput`), fija `session.exitstatus = 1` con un mensaje si algún
    shell obligatorio tiene cero. En los trabajadores no hace nada.
  - Nombres de shell: `pwsh`, `powershell` (5.1, solo Windows), `bash`, `bash3` (`/bin/bash` con
    `BASH_VERSINFO[0] == 3`, macOS) y `zsh`.
  - El CI fija la variable con una **expresión** en el `env` del paso de tests, no con
    `matrix.include` (que `tests/test_ci_gate.py:279-285` rechaza). Valores finales:
    - Windows: `pwsh,powershell,bash`;
    - ubuntu: `bash,pwsh`;
    - macOS: `zsh,bash,bash3,pwsh`.
  - Un test estático comprueba que `ci.yml` declara esos valores.
  - En Windows, bash es el de Git (derivado de `shutil.which("git")`, nunca `System32\bash.exe`).

  *Aceptación*:
  - control positivo del ayudante: con `COMPLETION_TEST_REQUIRE_SHELLS=zsh` en esta PC (sin zsh),
    la ejecución con `-n 2` sale en rojo;
  - control positivo del **guardián** (no del ayudante): `COMPLETION_TEST_REQUIRE_SHELLS=bash` con
    `-k "not bash"` y `-n 2` sale en rojo, porque ninguna prueba de bash llegó a pasar;
  - el test estático de `ci.yml`;
  - el primer run de CI en verde con la variable fijada.

- **REQ-038 — Controles positivos.** Cada fichero de pruebas de integración de un shell incluye:
  - (a) un caso sin coincidencias (REQ-017) que devuelve vacío;
  - (b) un caso con el completador **sin cargar**, que no devuelve candidatos propios (p. ej.
    `local-delegate backend-params set ` no da `mechanical`).

  Si (b) devolviera candidatos, la prueba no estaría midiendo el script.

  Las pruebas de integración se ejecutan con un directorio de trabajo temporal **vacío**: sin
  respuesta del completador, PowerShell completa rutas, y un directorio con ficheros falsearía (a)
  y (b).

  *Aceptación*: los dos casos existen en cada fichero y fallan si se invierte su expectativa
  (comprobado una vez a mano y anotado en `verification.md`).

- **REQ-039 — E2E «instalado» en los tres sistemas.** `scripts/check_install_e2e.py` añade, con el
  HOME temporal, una fase que:
  1. siembra los perfiles:
     - en Windows, el de 5.1 en cp1252 con tildes y CRLF y el de pwsh en UTF-8 con BOM;
     - en Linux y macOS, un `.bashrc`/`.zshrc` con contenido y un `.bashrc.bak` del «usuario»
       (REQ-046);
  2. ejecuta dos veces `install --shell-completion` (`auto`, y en macOS además `bash`);
  3. abre cada shell cargando el perfil temporal y completa `local-delegate backend-params set `,
     que debe contener `mechanical`:
     - PowerShell: `-NoProfile -ExecutionPolicy Bypass` + dot-source del perfil + `TabExpansion2`;
     - bash en Linux: `HOME=<tmp> bash -i` con `COMP_WORDS` simulado;
     - bash en macOS: `/bin/bash -l -i`, porque `.bash_profile` solo lo lee un shell de inicio de
       sesión;
     - zsh: `ZDOTDIR=<tmp>` + `zpty`;
  3b. en Linux, readline real con un `pty` de la biblioteca estándar (con tope de tiempo): `bash -i`
     con el perfil, teclear `local-delegate install --home ./d/` con un fichero `con espacio` dentro
     y Tab; el nombre se completa entero (REQ-016);
  4. control positivo de REQ-027: borra el fichero de completado de un shell, carga de nuevo el
     perfil y comprueba que no hay error y que ya no completa; luego lo repone con `install`;
  5. ejecuta `uninstall`;
  6. comprueba que cada perfil (y el `.bashrc.bak` del usuario) es byte a byte el sembrado, y que
     el directorio de completado ya no tiene ficheros.

  Cada lanzamiento lleva tope de tiempo. El paso E2E del CI sube su `timeout-minutes` de 3 a 6.

  *Aceptación*: el paso «Instalador end-to-end» del CI en verde en los tres sistemas, con la fase
  visible en el log.

- **REQ-040 — Verificación en vivo con el binario instalado.** En esta PC se ejecuta el binario
  `local-delegate.exe` de un wheel construido desde `main` e instalado en un entorno temporal (sin
  tocar el `uv tool` del daemon):
  1. **Solo lectura sobre el HOME real**:
     - se toma el `sha256` de los dos perfiles reales (pwsh y 5.1) y de `LOG_DIR/completion/`;
     - se ejecuta `install --shell-completion --dry-run --no-hooks --no-skill --no-memory --no-mcp --no-client-cli`;
     - la salida debe enseñar las rutas reales de los perfiles, la política de cada edición y la
       ruta en `LOG_DIR`;
     - se vuelven a tomar los `sha256`, que deben salir iguales.

     En este SDD no se escribe en el perfil real del usuario.
  2. **Instalado sobre perfiles temporales**:
     - `install --home <tmp> --shell-completion`;
     - en pwsh 7 y Windows PowerShell 5.1, abrir con `-NoProfile` (y con `-ExecutionPolicy Bypass`
       si la política real del paso 1 bloquea esa edición, anotado en `verification.md`), cargar el
       perfil temporal y
       completar los casos de REQ-012 a REQ-015, con el tooltip con tildes;
     - `doctor --home <tmp>` con `scaffold.shell_completion` en `ok`;
     - `uninstall --home <tmp>` deja los perfiles como antes.

  zsh real se verifica en el CI de macOS (REQ-037, REQ-039). Evidencia en
  `.sdd/changes/cli-completion/evidence/live/`.

  *Aceptación*: `verification.md` enlaza la evidencia con las salidas literales y los `sha256`.

- **REQ-041 — Documentación.** Una release toca tres sitios:
  - **README**: «Instalación rápida» menciona `--shell-completion` y `completion`.
  - **Wiki**, `docs/wiki/Integration-install.md`:
    - fila en «Opciones», fila en «Qué instala» y frase en «Garantías» (opcional, reversible,
      codificación respetada, copia propia);
    - sección nueva «Autocompletado del shell» con:
      - los tres shells y dónde escribe (fichero, manifiesto y perfil);
      - `Invoke-Expression`, `eval` y `source <(…)` como alternativas, con su coste de arranque;
      - ExecutionPolicy: `RemoteSigned` basta, y con `Restricted`/`AllSigned` la edición se salta
        con aviso (REQ-044), con cómo arreglarlo;
      - 5.1 y `--`;
      - zsh con `compinit` y `~/.zcompdump`;
      - bash en macOS;
      - regenerar tras cambiar de idioma o de versión (`update`);
      - `uninstall --shell-completion` y qué hace un `uninstall` restringido;
      - que el completado funciona sobre el ejecutable instalado (`local-delegate` en el PATH), no
        sobre `uvx local-delegate`;
    - fila del check.
  - `docs/wiki/Language.md`: una línea sobre el idioma del script.
  - `CHANGELOG.md` `[Unreleased]`.

  *Aceptación*: `tests/test_wiki.py` en verde y revisión del gate de conformidad contra esta
  lista.

## Desviaciones propuestas

1. **No reutilizar `_read_text`/`_write_text` para perfiles** (la decisión 6 decía
   reutilizarlos).
   - **Por qué**:
     - `_read_text` devuelve `""` ante un fichero que no es UTF-8 (`install.py:262-266`): con un
       perfil de 5.1 guardado en ANSI con tildes, `upsert_block` lo reemplazaría entero por el
       bloque;
     - `_write_text` siempre escribe UTF-8 (`install.py:254-259`);
     - `upsert_block` hace `rstrip()` (`install.py:291`) y `remove_block` hace `strip()`
       (`install.py:420-421`), así que el perfil no volvería byte a byte;
     - `_backup` pisa `<perfil>.bak` (`install.py:235-237`), que suele ser del usuario.
   - **Propuesta**: dos ayudantes nuevos en `install.py`, `upsert_profile_block` y
     `remove_profile_block`. Trabajan sobre bytes, conservan codificación, fin de línea y enlaces,
     y usan la copia propia de REQ-046. Siguen usando los marcadores y `managed_block` para leer.
2. **Directorio del fichero con HOME simulado.**
   - **Por qué**: la decisión 6 dice «el directorio de datos del producto», que es
     `config.LOG_DIR` (`config.py:203-216`). Pero con `--home` simulado el producto no toca ese
     directorio (`install.py:1051-1062`).
   - **Propuesta**: en ese caso, y sin `LOCAL_DELEGATE_LOG_DIR`, el fichero va en
     `<home>/.local/share/local-delegate/completion/`, para que el sandbox no escriba fuera del
     HOME simulado.
3. **`update` regenera fuera de la tabla `REPAIRS`.**
   - **Por qué**: `plan_repairs` salta toda reparación sin cliente presente
     (`update.py:292-294`), y el autocompletado no tiene cliente.
   - **Propuesta**: paso propio, `completion.plan_refresh(...)`, junto a `plan_catalog_refresh`
     (`update.py:326-330`), con un comentario en el bloque de `REPAIRS`.
4. **El check compara el contenido entero, no solo la versión de la cabecera** (la decisión 7
   hablaba de la versión).
   - **Cómo**: compara contra `render(shell, lang=<idioma del manifiesto>)`, así que detecta un
     cambio de árbol sin subir de versión.
   - **Por qué es neutral al idioma de la sesión**: no se compara contra el idioma en que se
     ejecuta `doctor`. El cambio de idioma configurado lo resuelve `update` (REQ-034).
5. **Manifiesto `installed.json`** (REQ-043). No estaba en las decisiones; lo pidió la revisión
   y lo aprobó la sesión principal. Evita el falso OK de un bloque borrado, permite borrar solo los
   perfiles que `install` creó, y deja a `uninstall` independiente de la ruta que hoy dé
   PowerShell (OneDrive puede moverla).
6. **bash en macOS escribe en `~/.bash_profile`**, no en `~/.bashrc`.
   - **Por qué**: la decisión 6 solo fijaba Linux, y en macOS Terminal abre shells de inicio de
     sesión, que no leen `.bashrc`.
   - `uninstall` limpia los dos.
7. **`--shell-completion` repetible (`append`) y no lista con comas.**
   - **Por qué**: es el patrón del repo (`--clients`, `--target`, `cli.py:1554-1561`), y así
     argparse valida cada valor con `choices` y da su error traducido.
   - La opción pasa a existir también en `uninstall` (REQ-032; decisión de la sesión principal
     tras la revisión, que matiza la decisión 7 «`uninstall` quita siempre»).
8. **Política de ejecución detectada y respetada** (REQ-044). La decisión 8 decía «solo se
   documenta»; tras la revisión, la sesión principal decidió saltar con aviso la edición que no
   puede ejecutar scripts, porque crear un perfil en 5.1 con `Restricted` da error en cada
   arranque. Se sigue sin firmar scripts.

## Fuera de alcance

- Valores dinámicos: ids de `test-window stop`, modelos de `--model`/`--pin`/`--vram-model`,
  grupos, y el `value` de `backend-params set` según la clave.
- fish, nushell, cmd.exe y Claude Desktop.
- Reconocer abreviaturas de opciones (`--mcp` por `--mcp-mode`) en las palabras previas. argparse
  las acepta; el completado no las sigue.
- Filtrar opciones mutuamente excluyentes o ya usadas.
- Firmar scripts para `AllSigned` y cambiar la ExecutionPolicy del usuario.
- Que `install` sin `--shell-completion` refresque un completado ya instalado (lo hace `update`).
- Escribir en el perfil real del usuario durante este SDD (después de la release lo decide el
  usuario).
- La release (versión, publicación en PyPI, actualizar la Mac).

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Un perfil del usuario se corrompe | Ayudantes por bytes (REQ-028), copia propia (REQ-046), enlaces respetados (REQ-045), no tocar lo dudoso, ida y vuelta byte a byte en tests y E2E |
| Un perfil de 5.1 que falla en cada arranque | REQ-044 salta la edición con política restrictiva |
| Romper Windows PowerShell 5.1 por codificación o sintaxis | Solo ASCII (REQ-018), test estático (REQ-019), integración real en 5.1 en Windows CI |
| Script congelado tras actualizar o cambiar de idioma | Manifiesto con versión e idioma, check en `warn`, `update` regenera (REQ-033, REQ-034, REQ-043) |
| `doctor` en rojo solo por el idioma de la sesión | Comparación en el idioma del manifiesto (REQ-033) |
| Falso OK con el bloque borrado | El check mira los perfiles del manifiesto (REQ-033) |
| Pruebas de shell que nunca corren en CI | `COMPLETION_TEST_REQUIRE_SHELLS`, `pytest.fail` y guardián en el controlador (REQ-037) |
| El `bash` de WSL en Windows | Git Bash derivado de `git` (REQ-024, REQ-037) |
| Consultar `$PROFILE` cuelga o devuelve ruta rota | Tope de 20 s, `stdin` cerrado, Base64, respaldo por carpeta conocida (REQ-025) |
| zsh sin `compinit` o con `~/.zcompdump` viejo | Guarda con `compinit -i`; carga por `source` (no depende del volcado); documentado |
| El guardián de textos marca código de plantilla | Plantillas como recursos (REQ-036); las filas de tabla se generan sin prosa |
| Un test toca el perfil real | Fixture autouse que hace fallar la consulta real de perfiles (plan, L3a) |
| `zsh`/`pwsh` ausentes en algún runner | Los valores de REQ-037 se ajustan al primer run, sin bajar a menos de un shell obligatorio por sistema |

## Estrategia de verificación

- **Unitarias** (rápidas, sin shells): modelo, filtros, fichas, cabecera, determinismo, render por
  idioma, rutas de perfil y política con dobles, ayudantes de perfil por codificación, enlaces y
  copia, manifiesto, `install`, `uninstall`, `update` y `doctor` con HOME simulado.
- **Integración con shells reales** (un proceso por shell y fichero, todos los casos dentro, con
  tope de tiempo): PowerShell 7 y 5.1 con `TabExpansion2`, bash con `COMP_WORDS` (también 3.2),
  zsh determinista y `zpty`.
- **E2E** en los tres sistemas (REQ-039) y **wheel instalado** en `install-smoke` (REQ-036).
- **En vivo** en esta PC con el binario del wheel (REQ-040).

## Trazabilidad

| REQ | Lote | Verificación |
|---|---|---|
| REQ-001 | L2a, L2b | `tests/test_completion_cli.py` |
| REQ-002 | L2a, L2b | `tests/test_completion_render.py::test_static*` |
| REQ-003 | L1 | `tests/test_completion_model.py` |
| REQ-004 | L1 | `tests/test_completion_model.py::test_hidden` |
| REQ-005 | L1 | `tests/test_completion_model.py`, `tests/test_cli_backend_params.py` |
| REQ-006 | L1 | `tests/test_completion_model.py::test_unsupported*`, guardián sobre el parser real |
| REQ-007 | L1 | `tests/test_completion_model.py::test_unsafe*` |
| REQ-008, REQ-009, REQ-010 | L2a, L2b | `tests/test_completion_render.py` |
| REQ-011 | L2a, L2b | `tests/test_completion_powershell.py`, `tests/test_completion_posix.py` |
| REQ-012 a REQ-017 | L2a, L2b, L5 (readline real de REQ-016, paso 3b de REQ-039) | tablas de casos en `tests/test_completion_powershell.py` y `tests/test_completion_posix.py` |
| REQ-018, REQ-019, REQ-020 | L2a | `tests/test_completion_powershell.py` |
| REQ-021, REQ-022 | L2b | `tests/test_completion_posix.py` |
| REQ-023 | L3b | `tests/test_completion_install.py` |
| REQ-024, REQ-025 | L3a | `tests/test_shell_profiles.py` |
| REQ-026, REQ-027 | L3a (texto del bloque, directorio), L3b (escritura), L5 (control de REQ-027) | `tests/test_shell_profiles.py`, `tests/test_completion_install.py`, E2E |
| REQ-028 | L3a, L3b | `tests/test_profile_blocks.py`, `tests/test_completion_install.py` |
| REQ-029 a REQ-032 | L3b | `tests/test_completion_install.py`; E2E en L5 |
| REQ-033 | L4 | `tests/test_doctor_completion.py`, `tests/test_checks.py`, `tests/test_doctor*.py`, `tests/test_wiki.py` |
| REQ-034 | L4 | `tests/test_update_completion.py` |
| REQ-035 | todos | guardianes de i18n, nombres y ayuda |
| REQ-036 | L2a, L5 | revisión de `pyproject.toml`, job `install-smoke` |
| REQ-037 | L2a, L2b | guardián en `tests/conftest.py`, test estático de `ci.yml`, primer run de CI |
| REQ-038 | L2a, L2b | casos (a) y (b) en cada fichero de integración; anotación en `verification.md` |
| REQ-039 | L5 | `scripts/check_install_e2e.py` en CI (tres sistemas) |
| REQ-040 | L7 | `evidence/live/`, `verification.md` |
| REQ-041 | L4, L6 | `tests/test_wiki.py`, gate de conformidad |
| REQ-042 | L2a | `tests/test_completion_render.py::test_lang_override`, `tests/test_i18n_override.py` |
| REQ-043 | L3b (escritura), L4 (lectura en `doctor` y `update`) | `tests/test_completion_install.py`, `tests/test_doctor_completion.py`, `tests/test_update_completion.py` |
| REQ-044 | L3a (detección), L3b (salto) | `tests/test_shell_profiles.py`, `tests/test_completion_install.py` |
| REQ-045, REQ-046 | L3a | `tests/test_profile_blocks.py`; E2E (copia del usuario) |

## Cambios tras la revisión

Revisión adversarial: [review-spec.md](review-spec.md). Decisiones de la sesión principal
aplicadas el 2026-10-20.

| Hallazgo | Cambio |
|---|---|
| 1. Bloqueante: REQ-002 prohibía `$(…)` que REQ-018 y bash necesitan | REQ-002 reescrito como lista blanca, con dos controles positivos |
| 2. Bloqueante: el check dependía del idioma de la sesión | REQ-033 compara en el idioma del manifiesto; REQ-042 (`render(shell, lang=…)` con `i18n.override`); REQ-026 y REQ-034 generan en el idioma configurado |
| 3. Mayor: perfil de 5.1 con `Restricted` | REQ-025 consulta también la política; REQ-044 salta la edición con aviso, también con `powershell` explícito; se quita de «Fuera de alcance»; desviación 8 |
| 4. Mayor: falso OK sin mirar perfiles | REQ-043 (manifiesto) y REQ-033 (bloque ausente → `warn`); la antigua desviación 5 pasa a ser el manifiesto |
| 5. Mayor: perfiles enlazados | REQ-045 |
| 6. Mayor: `.bak` ajena | REQ-046; REQ-039 siembra un `.bashrc.bak` |
| 7. Mayor: `uninstall` parcial | REQ-023 (opción también en `uninstall`) y REQ-032 (tres casos) |
| 8. Mayor: idioma de `update` y caso sin clientes | REQ-034 |
| 9. Menor: bash idéntico frente a `lang=` en la cabecera | REQ-008 («salvo la cabecera») y REQ-009 |
| 10. Menor: `compgen -f` parte rutas con espacios | REQ-016 y REQ-021 (`complete -o default`, `COMPREPLY` vacío) |
| 11. Menor: NUL y marcadores huérfanos | REQ-028 |
| 12. Menor: borrar un perfil vacío del usuario | REQ-032 (solo si `created`) con REQ-043 |
| 13. Menor: fallo de escritura y `uninstall --dry-run` | REQ-028 y REQ-031 |
| 14. Menor: un solo resolvedor del directorio | REQ-026 (`shell_profiles.completion_dir`) |
| 15. Menor: `bash` de WSL en `install` | REQ-024 |
| 16. Menor: guardián no verificable | REQ-037 (`pytest.fail`, guardián en el controlador, test estático de `ci.yml`, `bash3`) |
| 17. Menor: tope del E2E y cifras sueltas | REQ-039 (6 min) y REQ-033 (`doctor.py:71`, `test_doctor_english.py:3`) |
| 18. Menor: la Mac con `uvx` | REQ-041 |
| Revisión del plan, bloqueante y mayores 1, 2 y 5 | REQ-030 (orden fijo), REQ-042, REQ-037 (controlador, expresión, `bash3`) |
| Revisión del plan, mayor 6 | REQ-040 (paso de solo lectura con `sha256` sobre el HOME real) |
| 2.ª ronda, A (mayor): `--no-client-cli` contaba como restricción | REQ-032 define «sin restricciones» por los datos (cuatro componentes activos, `--clients` ausente o `auto`, sin `--target`); caso `uninstall --no-client-cli` |
| 2.ª ronda, B (mayor): `.bak` huérfana de un perfil creado por `install` | REQ-046: sin copia si el manifiesto dice `created`; aceptación «ni perfil, ni copia, ni carpeta» |
| 2.ª ronda, C (mayor): el controlador no ve el argumento del marcador | REQ-037: `user_properties` y comprobación en `pytest_sessionfinish` del controlador; control positivo con `-k "not bash"` |
| 2.ª ronda, D: prueba de readline inexistente | REQ-039 paso 3b (pty, Linux) |
| 2.ª ronda, E: aritmética en la lista blanca | REQ-002 admite `$((…))` |
| 2.ª ronda, F: todas las ediciones saltadas | REQ-044: ni fichero `.ps1` ni entrada |
| 2.ª ronda, G: manifiesto en `uninstall` parcial y combinación con `--clients` | REQ-032 |
| 2.ª ronda, H: descripción inexacta de `plan_language` | Vocabulario y REQ-026 remiten a `plan_language` sin paráfrasis |
| 2.ª ronda, I: perfil listado ilegible | REQ-033 (`unknown`) |
| 2.ª ronda, J: PowerShell completa rutas sin respuesta | REQ-038: directorio de trabajo temporal vacío |
| 2.ª ronda, K: política real en la verificación en vivo | REQ-040: `-ExecutionPolicy Bypass` si la política real bloquea, anotado |
| Plan 2.ª ronda, menor 2: `PSExecutionPolicyPreference` heredada | REQ-025: se quita del entorno de la consulta, con test |

### Hallazgos de revisión no aplicados

- **Hallazgo 2, parte de «`warn` si el idioma del fichero difiere de la preferencia persistida»**:
  no se aplica. La sesión principal decidió que `doctor` sea neutral al idioma y que el cambio de
  idioma lo resuelva `update` (REQ-034), que ya regenera en el idioma configurado.
- **Hallazgo 3, «con un shell explícito se escribe igual, pero se avisa»**: no se aplica. La sesión
  principal decidió saltar también con `powershell` explícito, para no dejar nunca un perfil que
  falle al abrir.
