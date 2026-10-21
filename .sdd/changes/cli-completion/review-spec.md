# Revisión adversarial del gate `spec` — SDD `cli-completion`

Fecha: 2026-10-20. Revisor: agente de revisión (solo lectura; sin MCP `local-delegate`).
Objeto: `spec.md` contra `research.md`, `research-repo.md`, `research-shells.md`, el prototipo del
laboratorio (`scratchpad/completion-lab/proto.bash`) y el código de `main` (`465fc97`).

## Veredicto

**BLOQUEADA**, por dos contradicciones que hacen la spec inaplicable tal como está escrita
(hallazgos 1 y 2). Las dos se arreglan cambiando el texto, sin rediseñar nada. Hay además siete
hallazgos mayores, todos baratos. Con los bloqueantes y los mayores resueltos, la spec queda en
condiciones de aprobarse: la base técnica es sólida y las citas al código son exactas.

## Citas comprobadas contra el código (todas exactas)

`install.py:150-161` (`is_simulated_home`), `:222-232` (`Action.literal`), `:235-237` (`_backup`),
`:254-259` (`_write_text`, siempre UTF-8), `:262-266` (`_read_text` devuelve `""` si no es UTF-8),
`:291` (`rstrip`), `:420-421` (`strip`), `:1051-1062` (`language_dir`); `cli.py:203-212` (salida
temprana sin clientes), `:225-227` (salida 2 sin componentes), `:469` y `:600` (`nargs="?"`),
`:480-485`, `:592-597` (`role`/`key` sin `choices`), `:1510-1513` (`recalcular-coste` sin `help`),
`:1536-1542` (`SUPPRESS`), `:1554` (`--clients` con `append`); `update.py:292-294` (salta lo que
no tiene cliente), `:326-330` (`plan_catalog_refresh`); `checks.py:5` y `:2186`;
`tests/test_checks.py:93`, `:1194`, `:1210-1216`; `tests/test_doctor.py:267`;
`tests/test_doctor_english.py:89`; `tests/test_wiki.py:35-48`;
`docs/wiki/Integration-install.md:182` y `:340`; `deprecations.py:58-59`; `backend_params.py:33` y
`:77`; `benchmark.py:1536`; `config.py:203-216`; `pyproject.toml:74-75`;
`tests/test_cli_english.py:34-56`; `tests/test_smoke.py:215-233`. También comprobé que el parser
tiene hoy **12** subcomandos visibles más el oculto `recalcular-coste` (13 en `choices`), lo que
cuadra con REQ-012.

## Hallazgos

### 1. Bloqueante — REQ-002 prohíbe lo que REQ-018 y REQ-021 exigen

- **Evidencia**: REQ-002 (`spec.md:57-64`) prohíbe `$(…)` en los tres scripts. Pero REQ-018
  (`spec.md:254`) **obliga** a usar `$([char]0xNNNN)` en PowerShell. Y el prototipo de bash en el
  que se basa REQ-021 completa con `COMPREPLY=($(compgen -W '…' -- "$cur"))`
  (`completion-lab/proto.bash:41-55`), que también es `$(…)`. En bash 3.2, sin `mapfile`, no hay
  otra forma limpia de hacerlo.
- **Riesgo**: el test estático de REQ-002 rechazaría los scripts correctos, o quien implemente
  relajaría el analizador a ojo, sin un criterio escrito.
- **Cambio**: redactar REQ-002 como una **lista blanca**. En PowerShell solo se admite
  `\$\(\[char\]0x[0-9A-F]{4}\)`. En bash y zsh solo se admite `$(compgen …)`. Cualquier otro `$(`,
  o cualquier `$(` cuyo primer token sea `local-delegate`, `python`, `py` o `uv`, hace fallar el
  test. Se mantiene el control positivo `$(local-delegate --version)` y se añade un segundo:
  `$(Get-Date)` en PowerShell, que también debe marcarse.

### 2. Bloqueante — el veredicto del nuevo check depende del idioma y rompe un invariante que ya existe

- **Evidencia**: REQ-033 (`spec.md:451-458`) da `warn` si el fichero no es igual a
  `render(shell)` «en el idioma vigente», y el detalle «idioma o contenido distinto» lo hace
  explícito. Pero `doctor` sale con 1 ante cualquier `warn` (`doctor.py:180-191`). Además,
  REQ-022 de un SDD anterior exige el mismo veredicto en es y en en (`tests/test_doctor_english.py:3`
  y `:87-89`).
- **Riesgo**: con el completado instalado en `es`, basta `LOCAL_DELEGATE_LANG=en local-delegate doctor`
  para que el diagnóstico salga en rojo, con código 1. Los tests no lo ven porque trabajan sobre un
  HOME simulado vacío, donde el check da `ok`.
- **Cambio**: la parte de **contenido** se compara contra `render(shell, lang=<lang de la cabecera>)`,
  que detecta un cambio de versión o de árbol sin depender del idioma de la sesión. El `warn` por
  idioma solo salta si el `lang` de la cabecera difiere de la **preferencia persistida**
  (`language.json`), no del idioma de la sesión con la variable de entorno. Para eso REQ-033
  necesita `render(shell, lang=…)`. Test nuevo: fichero en `es`, preferencia `es`, `doctor` con
  `LOCAL_DELEGATE_LANG=en` → `ok`. Control positivo: preferencia `en` → `warn`.

### 3. Mayor — `auto` crea un perfil de 5.1 que con la política por defecto da error en cada arranque

- **Evidencia**: REQ-024 (`spec.md:329-330`) mete Windows PowerShell 5.1 en `auto` siempre que
  `powershell.exe` exista, que es siempre. En los Windows de escritorio, la ExecutionPolicy por
  defecto de 5.1 es `Restricted`. Hoy, sin perfil, eso no se nota. En cuanto `install` **crea**
  `WindowsPowerShell\profile.ps1`, cada `powershell.exe` arranca con el error «running scripts is
  disabled». La spec deja la detección de la política fuera de alcance (`spec.md:622`).
- **Cambio, sin coste extra**: la consulta de REQ-025 ya lanza cada edición. Que devuelva también
  `Get-ExecutionPolicy` (en la misma línea Base64). Con `auto`, se salta la edición cuya política
  efectiva sea `Restricted` o `AllSigned`, con un aviso del catálogo. Con un shell explícito se
  escribe igual, pero se avisa. Con HOME simulado, la política se inyecta. Hay que sacar «detectar
  la ExecutionPolicy» de «Fuera de alcance» y añadir un test con doble (`Restricted` → se salta,
  salida 0).

### 4. Mayor — la desviación 5 deja un falso OK, y hay una alternativa barata

- **Evidencia**: el check solo mira los ficheros de completado (`spec.md:451-452`; desviación 5,
  `spec.md:604-606`). Si el bloque desaparece del perfil (el usuario lo borra, OneDrive cambia
  `Documents` de sitio, se reinstala el perfil), `doctor` dice `ok` y el Tab no funciona. Es
  justo el falso OK que la memoria «escritura, diagnóstico y reparación» pide evitar. El caso
  contrario (bloque presente y ficheros borrados) sale como «no instalado (opcional)».
- **Alternativa barata**: `install` escribe un manifiesto pequeño,
  `<dir>/completion/installed.json`, con `{shell, profile, created}` por cada perfil tocado.
  `doctor` lee ese manifiesto, sin lanzar ningún shell, y comprueba que cada perfil tiene el bloque
  completo y que apunta a su fichero. Si no, da `warn` («bloque ausente en <perfil>») con
  `fix_hint` `local-delegate install --shell-completion`. Esto cuesta unas lecturas de fichero, no
  los 0,5 s de lanzar dos PowerShell. Y de paso:
  - `uninstall` limpia la unión del manifiesto y los candidatos, así que no depende de volver a
    preguntar a PowerShell (con OneDrive la ruta puede haber cambiado);
  - `created: true` resuelve sin adivinar si hay que borrar un perfil que queda vacío
    (hallazgo 12).
- **Cambio**: sustituir la desviación 5 por el manifiesto, añadir los estados del check y sus
  tests (bloque borrado → `warn`, que es el control positivo), y quitar la línea de
  `spec.md:623`.

### 5. Mayor — reescribir un perfil enlazado (dotfiles) lo convierte en un fichero normal

- **Evidencia**: REQ-026 exige escritura atómica (temporal + `os.replace`) para el fichero de
  completado (`spec.md:378`). REQ-028 no dice cómo se escribe el perfil. En macOS y Linux es
  habitual que `~/.zshrc` o `~/.bashrc` sean un enlace simbólico a un repositorio de dotfiles. Si
  quien implemente reutiliza el patrón atómico, `os.replace` cambia el enlace por un fichero
  normal y desengancha el repositorio del usuario.
- **Cambio**: REQ-028 debe decir que el perfil se escribe **en su sitio, siguiendo enlaces**
  (resolver con `Path.resolve()` y escribir el destino, sin `os.replace` sobre el enlace), y que
  la `.bak` va junto al destino. Test POSIX: `.zshrc` como enlace a `dotfiles/zshrc`; tras
  `install` y `uninstall` sigue siendo un enlace y el destino es byte a byte el mismo.

### 6. Mayor — la `.bak` pisa una copia que el usuario ya tuviera

- **Evidencia**: `_backup` copia sobre `path.bak` sin comprobar si ya existe (`install.py:235-237`).
  En un perfil de shell, `~/.bashrc.bak` o `~/.zshrc.bak` suelen ser **copias del propio
  usuario**. REQ-028 la reutiliza tal cual (`spec.md:407`, `:590`). Encima, `uninstall` la vuelve
  a pisar con la versión que lleva el bloque, y después de una ida y vuelta queda una `.bak`
  huérfana en `Documents\PowerShell\`.
- **Cambio**: en los perfiles, la copia va con un nombre propio,
  `<perfil>.local-delegate.bak`, que nunca pisa un fichero ajeno. Hay que decir qué hace
  `uninstall` con ella (recomendado: borrarla si el perfil quedó byte a byte igual a la copia).
  Test: con un `.bashrc.bak` sembrado, la ida y vuelta lo deja intacto.

### 7. Mayor — no está definido qué hace un `uninstall` parcial

- **Evidencia**: REQ-032 dice «con o sin opción», pero REQ-023 declara `--shell-completion` como
  opción **solo de `install`** (`spec.md:317`), y `uninstall` comparte
  `_add_common_install_args` (`cli.py:1689-1693`). Tal como está escrito,
  `uninstall --clients codex`, o `uninstall --no-hooks`, también borra el autocompletado, y no hay
  forma de quitar **solo** el autocompletado.
- **Cambio**: fijar la regla. Recomendación:
  - `uninstall --shell-completion` quita solo el autocompletado (la opción pasa a ser común);
  - un `uninstall` sin restricciones (sin `--clients`/`--target` ni `--no-*`) lo quita también;
  - un `uninstall` restringido a clientes o componentes no lo toca.

  Además, decir de forma explícita que en `uninstall` este paso también va antes de
  `cli.py:203-212` y de `:225-227`, igual que REQ-030 lo dice para `install`. Tests de los tres
  casos.

### 8. Mayor — `update` no dice en qué idioma regenera, ni prueba el caso sin clientes

- **Evidencia**: `run_update` escribe la preferencia de idioma (`update.py:833-841`) después de
  planificar (`plan_repairs`). El paso hermano usa de forma explícita `language.lang`
  (`update.py:326-330`). REQ-034 (`spec.md:470-478`) no fija el idioma. Además, la desviación 3
  existe justo para el caso sin clientes, pero ninguna aceptación lo prueba.
- **Cambio**: «regenera en el idioma de `install.plan_language(...)`, el mismo que usa
  `plan_catalog_refresh`». Test: HOME simulado **sin ningún cliente** y fichero viejo → una
  acción.

### 9. Menor — REQ-008 y REQ-009 chocan en bash

- **Evidencia**: REQ-009 pone `lang=<xx>` en la cabecera de los tres scripts (`spec.md:145`).
  REQ-008 exige que el de bash sea «idéntico en los dos idiomas» (`spec.md:141`).
- **Cambio**: «idéntico salvo la línea de cabecera», o quitar `lang=` de la cabecera de bash (y
  entonces el check de bash no necesita el idioma).

### 10. Menor — en bash, `compgen -f` parte las rutas con espacios

- **Evidencia**: REQ-016 usa `compgen -f` (`spec.md:237`) dentro de `COMPREPLY=($(…))`, como hace
  el prototipo (`proto.bash:43`). Eso parte las rutas por los espacios, y sin `compopt` (prohibido
  en 3.2) no se arregla dentro de la función.
- **Cambio**: registrar con `complete -o default -F _local_delegate …` (existe en 3.2) y, ante un
  valor libre, devolver `COMPREPLY` vacío, como en PowerShell. Hay que ajustar REQ-021 y REQ-016,
  y que el fichero conocido del test tenga un espacio en el nombre.

### 11. Menor — un perfil con NUL o con marcadores huérfanos no tiene regla

- **Evidencia**: REQ-028 cae a `latin-1` si el fichero no es UTF-8 (`spec.md:585-586`). Un UTF-16
  **sin BOM** cae ahí y quedaría corrompido al meterle bytes ASCII. Tampoco se dice qué pasa con un
  `# >>>` sin su `# <<<`: `managed_block` devuelve `None` (`install.py:294-299`), con lo que se
  añadiría un segundo bloque y `uninstall` cortaría hasta el primer final que encuentre.
- **Cambio**: un perfil con bytes NUL y sin BOM de UTF-16, o con un marcador sin pareja, se trata
  como «no se toca, se informa». Tests de los dos casos.

### 12. Menor — borrar un perfil que queda vacío contradice «byte a byte»

- **Evidencia**: REQ-032 borra el perfil si queda vacío (`spec.md:443-444`). Un `profile.ps1`
  vacío que el usuario creó con `New-Item $PROFILE` (un paso habitual en los tutoriales)
  desaparecería. Las carpetas `Documents\PowerShell\` que creó `install` se quedan.
- **Cambio**: borrar el perfil solo si `install` lo creó (`created` en el manifiesto del
  hallazgo 4) y, en ese caso, también la carpeta padre si `install` la creó y quedó vacía.

### 13. Menor — fallo de escritura, perfil de solo lectura y `uninstall --dry-run`

- **Evidencia**: REQ-028 cubre «no se puede leer ni decodificar», pero no «no se puede escribir»
  (atributo de solo lectura o fichero bloqueado por OneDrive). REQ-031 solo habla de `install`.
- **Cambio**: un error de escritura se informa con el mismo patrón que hoy (`install.not_written`,
  `install.py:410`), los demás shells siguen y el código de salida es el de `apply` con fallos.
  `uninstall --dry-run` no escribe nada. Tests con un perfil de solo lectura y con
  `uninstall --dry-run`.

### 14. Menor — un solo resolvedor del directorio para los cuatro verbos

- **Evidencia**: REQ-026 define `<dir>` a partir de `opts` (`spec.md:373-375`), pero
  `checks.Context` no lleva `data_dir` (`checks.py:370-380`), y `doctor`, `update` y `uninstall`
  tienen que llegar al mismo sitio con el HOME simulado.
- **Cambio**: nombrar una única función, p. ej. `completion.completion_dir(home, data_dir=None)`,
  que usen `install`, `uninstall`, `update` y el check. Test de que `doctor --home <tmp>`
  encuentra lo que escribió `install --home <tmp>`.

### 15. Menor — `bash` explícito en Windows puede encontrar el de WSL

- **Evidencia**: REQ-024 busca los ejecutables con `shutil.which` (`spec.md:330-337`). En Windows,
  `which("bash")` puede devolver `System32\bash.exe` (WSL), y entonces se escribiría un `.bashrc`
  que nadie lee. REQ-037 ya resuelve esto para las pruebas.
- **Cambio**: en Windows, «bash existe» quiere decir «hay Git Bash», con la misma derivación desde
  `git` que en REQ-037.

### 16. Menor — el guardián de REQ-037 no es verificable como test

- **Evidencia**: «un test guardián comprueba que cada shell listado tiene al menos una prueba que
  se ejecutó» (`spec.md:508-509`). Un test no ve el resultado de los demás. Tampoco hay nada que
  garantice que en macOS se ejecute de verdad `/bin/bash` 3.2 (`spec.md:512`).
- **Cambio**: el ayudante de salto llama a `pytest.fail` si el shell está en
  `COMPLETION_TEST_REQUIRE_SHELLS`. El guardián pasa a ser un test estático de que `ci.yml` fija la
  variable por sistema. En macOS, la prueba de 3.2 lanza `/bin/bash` por ruta y comprueba
  `BASH_VERSINFO[0] == 3`.

### 17. Menor — tope de tiempo del E2E y sitios de la cifra 25

- **Evidencia**: el paso E2E tiene `timeout-minutes: 3` (`ci.yml:177-179`), y REQ-039 le añade dos
  `install`, el arranque de 5.1 y 7, y `zpty`. Además, `doctor.py:71` también dice «the 25
  checks» y REQ-033 no lo lista.
- **Cambio**: subir el tope del paso (p. ej. a 6 minutos) dentro de REQ-039, y añadir
  `doctor.py:71` (y los docstrings de tests que citan 25) a la lista de REQ-033.

### 18. Menor — la Mac con `uvx`

- **Evidencia**: en la topología `stdio` + `uvx` de la Mac (`update.py:868`, «no hay daemon») puede
  no haber un `local-delegate` en el PATH, y entonces `local-delegate <Tab>` no aplica.
- **Cambio**: una línea en la wiki (REQ-041): el completado funciona sobre el ejecutable instalado
  y no sobre `uvx local-delegate`.

## Alcance

- No sobra nada importante: el modelo común, la lista blanca de construcciones y las pruebas con
  shells reales están justificados por las memorias «probar la pieza no es probar el uso» y «un
  control que no discrimina».
- REQ-038(b) («comprobado una vez a mano») es aceptable como evidencia de control positivo.
- Lo que falta está en los hallazgos 3, 4, 5 y 7: la política de 5.1, el perfil desaparecido, los
  enlaces de dotfiles y el `uninstall` parcial.

## Desviaciones

- **1** (ayudantes nuevos para el perfil): justificada; las citas son exactas (`install.py:262-266`,
  `:291`, `:420-421`). Hay que completarla con los hallazgos 5, 6 y 11.
- **2** (directorio con HOME simulado): justificada, y coherente con `language_dir`
  (`install.py:1058-1062`).
- **3** (`update` fuera de `REPAIRS`): justificada (`update.py:292-294`); falta la prueba sin
  clientes (hallazgo 8).
- **4** (comparar el contenido entero): justificada, pero tiene que quedar separada del idioma de
  la sesión (hallazgo 2).
- **5** (no mirar los perfiles): **no justificada tal como está**. Hay un falso OK real y una
  alternativa sin coste de arranque (hallazgo 4).
- **6** y **7**: justificadas.

## Trazabilidad

Cada REQ tiene su verificación y casi todas pueden fallar. Faltan controles positivos en REQ-033
(bloque ausente, idioma solo de la sesión), REQ-032 (`uninstall` parcial), REQ-028 (enlace
simbólico, `.bak` ajena, NUL) y REQ-034 (sin clientes). Con los cambios de arriba, la tabla de
`spec.md:655-684` necesita filas para el manifiesto y para la política de 5.1.

## Evidencia recomendada para aprobar en la re-revisión

`spec.md` corregida con los hallazgos 1–8, la tabla de trazabilidad actualizada y la desviación 5
sustituida. Basta con releer los REQ afectados (002, 008, 016, 021, 024, 025, 028, 032, 033, 034 y
037).

## Procesos

Solo hice lecturas y un `python -c` corto para contar los subcomandos del parser. No dejo shells,
servidores ni esperas vivas.

---

## Segunda ronda

Fecha: 2026-10-20. He revisado de nuevo `spec.md` entera (943 líneas), con su sección «Cambios tras
la revisión» y las decisiones de la sesión principal. También he contrastado contra el código las
citas nuevas: `install.py:1075-1105` (`plan_language`), `i18n.py:34-72` (`lang`, `t_lang`, `reset`),
`tests/test_ci_gate.py:279-285` (rechaza `matrix.include`) y `scripts/check_install_e2e.py:95`.

### Veredicto de la segunda ronda

**APROBADA CON CAMBIOS MENORES.** Los 18 hallazgos de la primera ronda están resueltos o tienen una
decisión explícita de la sesión principal; los dos que no se aplican están anotados y son
razonables. La corrección ha metido **tres contradicciones nuevas** (A, B y C). Las marco como
mayores porque, tal como están escritas, harían fallar el E2E o dejarían el guardián de CI sin
efecto. Aun así, cada una se arregla con una frase y no hace falta otra ronda si se aplican tal como
se proponen aquí.

### A. Mayor — `--no-client-cli` cuenta como restricción y el E2E no desinstalaría el autocompletado

- **Evidencia**: REQ-032 (`spec.md:513-517`) solo quita el autocompletado en un `uninstall` «sin
  ningún `--no-*`». Pero el E2E pasa `--no-client-cli` a **todos** sus comandos
  (`scripts/check_install_e2e.py:95`). Con la regla tal como está, el paso 5 de REQ-039 no quitaría
  nada y el paso 6 fallaría. Además, `--no-client-cli` no restringe componentes: solo dice cómo se
  escribe la entrada MCP.
- **Cambio**: definir «restringido» como `--clients` distinto de `auto`, `--target`, o alguno de
  `--no-hooks`/`--no-skill`/`--no-memory`/`--no-mcp`. Que `--no-client-cli`, `--dry-run`,
  `--python` y `--home` no cuenten. Test: `uninstall --no-client-cli` quita el autocompletado.

### B. Mayor — REQ-046 deja una `.bak` huérfana justo donde REQ-032 exige borrar todo

- **Evidencia**: REQ-046 (`spec.md:592-593`) dice que, si la copia no existía, `uninstall` «la crea
  antes de escribir, y entonces se queda». Un perfil que creó `install` no tiene copia, porque
  `_backup` solo copia si el fichero existe (`install.py:235-237`). Así que `uninstall` crea
  `profile.ps1.local-delegate.bak` y después borra el perfil. La copia queda dentro de la carpeta,
  que entonces no está vacía, y eso contradice la aceptación de REQ-032 («perfil inexistente → no
  existe, ni su carpeta creada», `spec.md:532`) y la de REQ-046 («no queda `.local-delegate.bak`»).
- **Cambio**: si el manifiesto marca el perfil como `created`, `uninstall` no crea copia (o la
  borra junto con el perfil). Test: ida y vuelta con el perfil inexistente → ni perfil, ni copia,
  ni carpeta.

### C. Mayor — el guardián de REQ-037 no puede leer el argumento del marcador en el controlador

- **Evidencia**: REQ-037 (`spec.md:677-680`) cuenta las pruebas `passed` por shell en el proceso
  controlador, a partir del marcador `shell("<nombre>")`. Pero los informes que `pytest-xdist`
  reenvía al controlador solo llevan los **nombres** de los marcadores (`report.keywords`), no sus
  argumentos: el controlador ve `shell`, no `pwsh` ni `zsh`. Además, `pytest_terminal_summary` no
  es el sitio fiable para cambiar el código de salida. El sitio es `pytest_sessionfinish`, en el
  controlador (sin `workerinput`), fijando `session.exitstatus`.
- **Cambio**: cada prueba de shell registra su shell con `record_property("shell", "<nombre>")`,
  porque `user_properties` sí viaja en el informe de xdist (o se usa un marcador por shell, como
  `shell_pwsh`). El guardián va en `pytest_sessionfinish`, solo en el controlador. Hay que añadir un
  control positivo que ejercite el guardián y no el `pytest.fail` del ayudante:
  `COMPLETION_TEST_REQUIRE_SHELLS=bash` con `-k "not bash"` → sale en rojo.

### Menores nuevos

- **D. REQ-016 cita una prueba que no existe.** La aceptación (`spec.md:272-273`) y la trazabilidad
  (`spec.md:886`) remiten a una «prueba con readline real (REQ-039, Linux)» con un fichero cuyo
  nombre lleva un espacio. Pero el bash de REQ-039 usa `COMP_WORDS` simulado
  (`spec.md:717`), y readline necesita una pty. **Cambio**: o se añade ese paso a REQ-039 (con
  `script -qc` o un `pty` de Python, con tope de tiempo), o la aceptación se queda en «compspec con
  `-o default` y `COMPREPLY` vacío».
- **E. La lista blanca de REQ-002 no contempla la aritmética.** El prototipo de bash usa
  `i=$((i+1))` (`proto.bash:10`). **Cambio**: admitir `$((…))` de forma explícita, o exigir
  `(( i++ ))` y que el analizador no confunda `$((` con `$(`.
- **F. REQ-044 no dice qué pasa si se saltan todas las ediciones de PowerShell.** Si se escribe
  `local-delegate.ps1` sin entrada en el manifiesto, REQ-033 da `warn` para siempre («ficheros sin
  manifiesto»). **Cambio**: si se saltan todos los perfiles de un shell, no se escribe ni su
  fichero ni su entrada.
- **G. Falta el manifiesto en el `uninstall` parcial.** `uninstall --shell-completion zsh` debe
  quitar la entrada de zsh del manifiesto y borrarlo solo si queda vacío. Además, falta fijar qué
  pasa con `uninstall --shell-completion --clients codex`. Recomendación: lo quita todo (el
  autocompletado y Codex), o sale con 2. Una de las dos, escrita.
- **H. La descripción de `plan_language` en REQ-026 es inexacta.** Dice «variable de entorno,
  luego `language.json`, luego el sistema» (`spec.md:425-426`). En realidad, el idioma del sistema
  pisa una preferencia guardada cuyo origen sea «system» (`install.py:1093-1096`). **Cambio**:
  quitar el paréntesis y dejar «el que devuelve `install.plan_language(...)`».
- **I. Perfil listado ilegible.** REQ-033 da `unknown` si no puede leer el manifiesto o un
  fichero, pero no dice qué hace si no puede leer un **perfil** listado. **Cambio**: añadir ese
  caso a `unknown`.
- **J. PowerShell completa rutas cuando no hay respuesta.** Sin respuesta del completador,
  PowerShell completa rutas, así que los casos de REQ-017 y REQ-038 pueden devolver ficheros del
  directorio de trabajo. **Cambio**: las pruebas de integración se ejecutan en un directorio
  temporal vacío.
- **K. La verificación en vivo puede chocar con la política real.** REQ-040 paso 2 carga el
  perfil temporal en 5.1 y pwsh, pero no dice `-ExecutionPolicy Bypass`, y la política real de
  esta PC podría impedir el dot-source. **Cambio**: igual que en REQ-039, `-NoProfile
  -ExecutionPolicy Bypass`.

### Comprobado sin hallazgos

- REQ-002 como lista blanca y REQ-008/009 «salvo la cabecera»: coherentes.
- REQ-033 neutral al idioma de la sesión (compara en el idioma del manifiesto): conserva el
  invariante de `tests/test_doctor_english.py`.
- REQ-034 y desviación 4: no se contradicen. `update` ya no espera a que el check esté en `warn`,
  así que regenera tras un cambio de idioma aunque `doctor` diga `ok`.
- REQ-042: es viable con `i18n.reset`/`t_lang`, que ya existen (`i18n.py:57`, `:64`).
- REQ-025: la consulta con `[char]10 + (Get-ExecutionPolicy)` concatena bien, porque el operando
  izquierdo es una cadena.
- REQ-030 (orden fijo) y REQ-040 paso 1 (solo lectura con `sha256`): coherentes con
  `cli.py:203-227`.
- REQ-037 con expresión en `env`: compatible con `tests/test_ci_gate.py:279-285`.

### Procesos

Solo lecturas (y `sed`/`grep`). No dejo procesos vivos.
