# Revisión de conformidad: autocompletado de la CLI (`completion powershell|zsh|bash`)

Gate de conformidad del SDD `cli-completion`, hecho el 2026-10-21 sobre `main` en `3540860`
(PR #359–#367 y el arreglo #369), desde cero y sin fiarse de los informes de los lotes. Se leyó el
código de `main` (checkout principal, solo lectura), la spec entera, el plan §4–§5 y
`verification.md` con `evidence/live/`. Sin el MCP `local-delegate` (prohibido por el brief).

## Veredicto

**`conforms-with-notes`**

Los 46 REQ están implementados y tienen al menos una prueba que puede fallar o una evidencia
concreta: **37 cumplen sin nota, 9 cumplen con nota y ninguno incumple**. No hay hallazgos
bloqueantes ni mayores. Las ocho desviaciones de la spec se aprueban. Las dos desviaciones que dejó
la verificación en vivo (política de cada edición en la salida y `PSModulePath` en las pruebas) las
cierra el #369, comprobado abajo y en la sección «Tras el arreglo #369» de `verification.md`.

### Qué se comprobó por ejecución

- Pruebas del cambio y guardianes, con el cerrojo (`pesado.sh`, `-n 2`): `test_completion_*`,
  `test_shell_profiles`, `test_profile_*`, `test_doctor_completion`, `test_update_completion`,
  `test_i18n_override`, `test_i18n_parity`, `test_no_uncatalogued_text`, `test_cli_english`,
  `test_detect_spanish_names`, `test_wiki`, `test_checks`, `test_doctor`, `test_doctor_english`,
  `test_cli_backend_params`, `test_smoke`: **785 pasados, 27 saltados, 0 fallidos**. Los saltos son
  23 de zsh/bash3 (no existen en esta PC), un enlace simbólico sin privilegio, el caso de 5.1 en la
  edición de pwsh y un `chmod` previo a este SDD. pwsh 7, Windows PowerShell 5.1 y Git Bash
  corrieron de verdad.
- Controles positivos de REQ-037 repetidos aquí: `COMPLETION_TEST_REQUIRE_SHELLS=zsh` sale en rojo
  (13 errores) y `COMPLETION_TEST_REQUIRE_SHELLS=bash` con `-k "not bash"` sale en rojo con el
  mensaje del guardián del controlador.
- `local-delegate completion powershell|bash|zsh`: salida 0, cero `\r`, PowerShell con todos los
  bytes `< 0x80` (máximo 126), cabecera con versión 0.37.0, shell y `lang=es`, 13 subcomandos de
  primer nivel con `completion`, claves de `backend-params set` en su orden, tooltip de
  `backend-params` con `$([char]0x00E1)`. `completion fish` sale con 2.
- `gh pr checks 369`: 19/19 en `pass` (CodeQL, GitGuardian, Socket, los tres sistemas,
  `install-smoke`, `test-lang-es`, `ci-gate`); runs de `main` tras el #369 en `success`.
- Dry-run de solo lectura sobre el HOME real con el binario de `main` (es y en): enseña la ruta y la
  política de cada edición; `sha256` de los perfiles y de `LOG_DIR/completion` iguales antes y
  después (`evidence/live/after369-*`).
- Ida y vuelta en un HOME simulado vacío con el binario de `main`: `install --shell-completion` y
  `uninstall` salen con 0; quedan dos carpetas vacías (hallazgo menor 1).

## Comparación con la spec

| REQ | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 | Sí (`cli.py:685-703`) | Sí (`tests/test_completion_cli.py`) | Con nota: el test de «no escribe en disco» solo mira el directorio de trabajo (`test_completion_cli.py:52-57`), no el de datos; el código no escribe (hallazgo menor 7) |
| REQ-002 | Sí | Sí (`test_completion_render.py:161-178`, con los dos controles positivos) | — |
| REQ-003 | Sí (`completion.py:124-171`) | Sí (`test_completion_model.py:79`, `:102`, `:112`) | — |
| REQ-004 | Sí (`completion.py:152`, `:188-191`, `:203`) | Sí (`test_completion_model.py:138-213`, `test_completion_render.py:255`) | `--api-key` se busca por palabra: `--api-key-env` existe y es legítima |
| REQ-005 | Sí (`cli.py:660-682`, `completion.py:235-242`) | Sí (`test_completion_model.py:215-243`, `test_cli_backend_params.py`) | — |
| REQ-006 | Sí (`completion.py:39-56`, `:142-232`) | Sí (`test_completion_model.py:317-357`, un parser por construcción) | Más estricto que la spec con `nargs=1` (también lanza); aceptable |
| REQ-007 | Sí (`completion.py:58-61`, `:206-247`) | Sí (`test_completion_model.py:362-405`, con `a b`, `x;y`, `ñ`) | — |
| REQ-008 | Sí (`completion.py:250-255`) | Sí (`test_completion_render.py:315`, `:450`, `:459`) | — |
| REQ-009 | Sí (`completion.py:275-327`) | Sí (`test_completion_render.py:293`, `:440`) | — |
| REQ-010 | Sí | Sí (`test_completion_render.py:309`) | — |
| REQ-011 | Sí (registro en las tres plantillas) | Sí (`test_completion_powershell.py:224`, con `& "C:\x y\local-delegate.exe" ins`; `test_completion_posix.py`) | — |
| REQ-012 | Sí | Sí (PowerShell 5.1/7 y Git Bash aquí; zsh en el CI de macOS; en vivo 24/24 por edición) | — |
| REQ-013 | Sí | Sí (`test_completion_powershell.py:253`; posix) | — |
| REQ-014 | Sí | Sí (`test_completion_powershell.py:281`, `:291`; posix; en vivo) | — |
| REQ-015 | Sí | Sí (`test_completion_powershell.py:302`; posix; en vivo) | — |
| REQ-016 | Sí (`complete -o default`, `_files`, PowerShell sin respuesta) | Sí (`test_completion_powershell.py:314`; readline real en el E2E de Ubuntu) | — |
| REQ-017 | Sí | Sí (`test_completion_powershell.py:321`; posix) | — |
| REQ-018 | Sí (`completion.py:330-348`) | Sí (`test_completion_render.py:238`; `test_completion_powershell.py:359`, dot-source e `iex` en 5.1 y 7) | — |
| REQ-019 | Sí (`resources/completion/powershell.ps1`) | Sí (`test_completion_render.py:221-226`; `test_completion_powershell.py:334`, `:340`, `:346`) | — |
| REQ-020 | Sí (documentado) | Sí (`test_completion_powershell.py:269`) | — |
| REQ-021 | Sí (`resources/completion/bash.bash`) | Sí (`test_completion_render.py:393-413`; Git Bash aquí, bash 3.2 en macOS por el guardián) | — |
| REQ-022 | Sí (`resources/completion/zsh.zsh`) | Sí (`test_completion_render.py:421`; zsh determinista, `zpty` y dos cargas en el CI de macOS) | Sin zsh en esta PC: la evidencia real es el CI de macOS con el guardián en verde |
| REQ-023 | Sí (`cli.py:1800-1811`) | Sí (`test_completion_install.py:94-127`) | — |
| REQ-024 | Sí (`shell_profiles.py:122-196`) | Sí (`test_shell_profiles.py:60-135`, incluido WSL) | — |
| REQ-025 | Sí (`shell_profiles.py:62-367`) | Sí (`test_shell_profiles.py:161-329`; consulta real en `:456`) | — |
| REQ-026 | Sí (`shell_profiles.py:461-483`, `install.py:670-707`) | Sí (`test_completion_install.py:131-178`, `:345`; `test_shell_profiles.py:374`) | — |
| REQ-027 | Sí (`shell_profiles.py:491-511`) | Sí (`test_shell_profiles.py:398-434`; E2E paso 4) | — |
| REQ-028 | Sí (`install.py:482-625`) | Sí (`test_profile_blocks.py:64-326`, control ANSI en `:326`; `test_completion_install.py:208`, `:299`, `:660`) | — |
| REQ-029 | Sí | Sí (`test_completion_install.py:178`; E2E instala dos veces) | — |
| REQ-030 | Sí (`cli.py:217-301`) | Sí (`test_completion_install.py:193-262`) | — |
| REQ-031 | Sí | Sí (`test_completion_install.py:264`, `:276`) | Con nota: la ruta «sin componentes» del dry-run acaba sin la línea final de dry-run (hallazgo menor 4) |
| REQ-032 | Sí (`cli.py:195-207`, `install.py:826-962`) | Sí (`test_completion_install.py:299-463`, todos los casos de la aceptación) | Con nota: en un HOME simulado quedan `Documents/` y `.local/share/local-delegate/` vacías (hallazgo menor 1) |
| REQ-033 | Sí (`checks.py:2106-2221`) | Sí (`test_doctor_completion.py`, 16 casos; cifras a 26 con `test_wiki.py`, `test_checks.py`, `test_doctor*.py` en verde) | Con nota: un `lang` vacío en el manifiesto hace que el veredicto dependa del idioma de la sesión (hallazgo menor 6) |
| REQ-034 | Sí (`update.py:361-403`, `:893`) | Sí (`test_update_completion.py`, 7 casos) | Con nota: la función se llama `update.plan_completion_refresh`, no `completion.plan_refresh` como dice la desviación 3; motivo documentado (ciclo de import que marca CodeQL) |
| REQ-035 | Sí (catálogos `install.json`, `doctor`, `cli`) | Sí (guardianes de i18n, nombres y ayuda en verde) | Con nota: comentarios y docstrings nuevos en español en varios módulos (hallazgo menor 5) |
| REQ-036 | Sí (`resources/completion/*`; `pyproject.toml` sin dependencias nuevas, solo un marcador de pytest) | Sí (`install-smoke` en verde con los tres shells y `TabExpansion2`) | — |
| REQ-037 | Sí (`tests/conftest.py:412-455`, `ci.yml:166`) | Sí (`test_completion_ci_shells.py`; controles positivos repetidos aquí; CI en verde) | — |
| REQ-038 | Sí | Sí (casos (a) y (b) en cada fichero; inversión anotada en las PR #362 y #363) | — |
| REQ-039 | Sí (`scripts/check_install_e2e.py:178-520`, `ci.yml:188-190`, 6 min) | Sí (paso E2E en los tres sistemas, también en el CI del #369) | — |
| REQ-040 | Sí (tras el #369: `install.py:759-761`, `shell_profiles.py:390-405`, `cli.py:253-254`) | Sí (`test_completion_install.py:595`, `:643`; `evidence/live/after369-*` y L7) | Con nota: con HOME simulado la línea dice la política supuesta (`RemoteSigned`) como si fuera la efectiva (hallazgo menor 3) |
| REQ-041 | Sí (README «Instalación rápida», wiki con todas las piezas pedidas, `Language.md`, CHANGELOG) | Sí (`test_wiki.py`; revisión contra la lista de la spec) | — |
| REQ-042 | Sí (`i18n.py:52-66`, `completion.py:293-308`) | Sí (`test_i18n_override.py`, 6 casos; `test_completion_render.py:329`) | — |
| REQ-043 | Sí (`completion.py:500-598`) | Sí (`test_completion_install.py:466-503`; lectura rota en los tres verbos) | Con nota: el esquema no exige que `lang` sea un idioma conocido (hallazgo menor 6) |
| REQ-044 | Sí (`install.py:762-766`, `shell_profiles.py:370-387`) | Sí (`test_completion_install.py:534-562`; `test_shell_profiles.py:360-364`) | — |
| REQ-045 | Sí (`install.py:469-479`, `:603-625`) | Sí (`test_profile_blocks.py:235-259` corrió aquí; `test_completion_install.py:673` en Linux y macOS) | — |
| REQ-046 | Sí (`install.py:464-466`, `:618-621`, `:843-850`) | Sí (`test_completion_install.py:299-343`; E2E con `.bashrc.bak`) | — |

## Desviaciones juzgadas

| Desviación | Juicio | Motivo |
| --- | --- | --- |
| 1. No reutilizar `_read_text`/`_write_text` | **Aprobada** | `upsert_profile_block`/`remove_profile_block` trabajan por bytes (`install.py:535-600`); el control positivo demuestra que los ayudantes de texto perderían un perfil ANSI (`test_profile_blocks.py:326`) |
| 2. Directorio con HOME simulado | **Aprobada** | Una sola derivación (`shell_profiles.py:461-478`), usada por `install`, `uninstall`, `update` y el check; el sandbox no sale de su HOME. Ver hallazgo menor 1 por las carpetas padre |
| 3. `update` fuera de `REPAIRS` | **Aprobada** | Paso propio que corre sin clientes (`update.py:361-403`, `:893`), comentario en el bloque de `REPAIRS` (`update.py:166-170`). Vive en `update.py` y no en `completion.py` para evitar el ciclo de import; el cambio de nombre es aceptable |
| 4. El check compara el contenido entero | **Aprobada** | `checks.py:2168` compara con `render(shell, lang=<manifiesto>)`; el test en inglés da el mismo veredicto (`test_doctor_completion.py:103`) |
| 5. Manifiesto `installed.json` | **Aprobada** | Evita el falso OK del bloque borrado (`test_doctor_completion.py:153`) y permite borrar solo lo que `install` creó |
| 6. bash en macOS en `~/.bash_profile` | **Aprobada** | `shell_profiles.py:316`; `uninstall` limpia `.bashrc` y `.bash_profile` (`shell_profiles.py:451-452`); E2E con `/bin/bash -l -i` |
| 7. `--shell-completion` repetible | **Aprobada** | `action="append"` con `choices` (`cli.py:1800-1811`); una lista con comas da 2 (`test_completion_install.py:113`) |
| 8. Política de ejecución respetada | **Aprobada** | Se salta la edición que bloquea, también con `powershell` explícito, y no se escribe `.ps1` si se saltan todas (`install.py:762-769`, `test_completion_install.py:534`) |
| Verificación en vivo, 1: el dry-run no enseñaba la política | **Resuelta por el #369** | La línea `install.completion.policy_note` sale con y sin `--dry-run`, en es y en (comprobado en el HOME real) |
| Verificación en vivo, 2: `PSModulePath` no se quitaba en las pruebas | **Resuelta por el #369** | `tests/completion_shells.py:100-108` y `scripts/check_install_e2e.py:184-189` usan `shell_profiles.query_environment` (sin distinguir mayúsculas); `Bypass` solo si la política real bloquea o no se puede consultar |

## Hallazgos

### Bloqueantes

Ninguno.

### Mayores

Ninguno.

### Menores

1. **Carpetas vacías tras la ida y vuelta en un HOME simulado.** `install --home <vacío>
   --shell-completion` crea `Documents/PowerShell/` y `Documents/WindowsPowerShell/` (Windows) y
   `.local/share/local-delegate/completion/`. `uninstall` borra los perfiles, sus carpetas
   inmediatas y `completion/`, pero deja `Documents/` y `.local/share/local-delegate/` vacías.
   `created_parent` solo mira el padre inmediato (`install.py:792-794`) y solo se borra
   `completion/` (`install.py:959-961`). Cumple la letra de REQ-032 y no afecta al HOME real
   (`Documents` y `LOG_DIR` ya existen), pero el sandbox no queda como estaba. Comprobado por
   ejecución con el binario de `main`.
2. **La protección de perfiles reales en los tests solo cubre PowerShell.** La fixture autouse
   `real_profiles_untouchable` (`tests/conftest.py:199-216`) hace fallar la consulta a PowerShell y
   la carpeta *Documents*, pero `.bashrc`/`.zshrc` salen de `Path.home()` sin consulta
   (`shell_profiles.py:351-354`). Un test que llamase `install --shell-completion` sin `--home`
   escribiría en el perfil real del runner (o aquí, con las sondas de Linux del fichero de tests, en
   `C:\Users\<usuario>\.bashrc`). Hoy ningún test lo hace (comprobado por búsqueda). Refuerzo
   sugerido: que la fixture falle también si `write_profile_edit` o `_atomic_write` apuntan dentro
   del HOME real.
3. **Con HOME simulado, la línea de REQ-040 presenta la política supuesta como efectiva.**
   `policy_note` enseña `SIMULATED_POLICY` (`shell_profiles.py:340`, `:390-405`): «con política de
   ejecución RemoteSigned» aunque nadie la haya consultado. Con HOME real es correcta. Bastaría con
   añadir «(supuesta: HOME simulado)» por el catálogo.
4. **El dry-run «solo autocompletado» no cierra con la línea de dry-run.** Con clientes presentes y
   `--no-hooks --no-skill --no-memory --no-mcp --shell-completion --dry-run` (justo el comando de
   REQ-040), `cli.py:295-299` sale con 0 sin imprimir `cli.install.dry_run`, que sí sale en las demás
   rutas (`cli.py:262-266`, `:307-310`). Se ve en `evidence/live/after369-dry-run-es.txt`. Solo
   afecta al texto.
5. **Comentarios y docstrings nuevos en español.** `shell_profiles.py` entero, la sección L3b de
   `install.py` (`:434-962`), `cli.py:189-307` y `update.py:361-374` comentan en español, mientras
   `completion.py`, `checks.py:2106-2221` y las plantillas lo hacen en inglés. Los nombres sí van en
   inglés (el detector está en verde) y los textos al usuario están en el catálogo; es una
   inconsistencia con la regla «todo el código en inglés», no un fallo de REQ-035.
6. **El manifiesto no valida `lang`.** `_valid_manifest` solo exige una cadena
   (`completion.py:542`). Con `"lang": "fr"`, `render` lanza dentro del probe y `run_all` lo
   convierte en `unknown` con «doctor.probe.failed» (`checks.py:2329-2330`) en vez del mensaje de
   manifiesto ilegible. Con `"lang": ""`, `render` usa el idioma de la sesión (`completion.py:305`) y
   el veredicto deja de ser neutral al idioma (REQ-033). Solo pasa con un manifiesto manipulado.
7. **El test de «no escribe en disco» de REQ-001 mira poco.** `test_completion_cli.py:52-57` solo
   compara el directorio de trabajo; no mira `LOG_DIR`. El código no escribe (`cli.py:685-693`), así
   que es un hueco de prueba, no de producto.

### Observaciones (sin acción obligatoria)

- Un `uninstall` sin restricciones con HOME real pregunta ahora a `pwsh` y a `powershell` (hasta dos
  procesos, tope de 20 s cada uno) aunque no haya autocompletado instalado
  (`install.py:908-917` → `shell_profiles.py:432-445`). Es coste de arranque, no un proceso
  colgado: `subprocess.run` con `timeout` mata al hijo.
- PowerShell filtra el prefijo sin distinguir mayúsculas (`OrdinalIgnoreCase` en
  `powershell.ps1`), y bash/zsh sí distinguen. La spec solo fija que la **bajada** por subcomandos
  distinga mayúsculas, y eso se cumple en los tres.
- Procesos que la CLI pueda dejar colgados: la única salida a procesos es la consulta a PowerShell,
  con `stdin` cerrado y tope; el E2E mata el grupo de procesos al vencer el tope
  (`check_install_e2e.py:212-238`). No se encontró ninguna espera sin tope.
- `uninstall` revierte todo lo que escribe `install`: bloque (byte a byte, también en ANSI, UTF-16 y
  CRLF), copia propia, ficheros de completado, manifiesto y `completion/`; con la salvedad del
  hallazgo 1.

## Seguimiento

### Obligatorio antes del cierre

Ninguno. El gate puede cerrarse con estas notas.

### Menores para el backlog

- Hallazgo 1: registrar en el manifiesto toda la cadena de carpetas que creó `install` (o borrar
  hacia arriba mientras queden vacías y las hubiera creado) para que el HOME simulado vuelva
  idéntico.
- Hallazgo 2: ampliar `real_profiles_untouchable` a las escrituras dentro del HOME real.
- Hallazgos 3 y 4: «(supuesta)» en la línea de política con HOME simulado y la línea final de
  dry-run en la ruta «solo autocompletado».
- Hallazgo 6: exigir `lang ∈ i18n.LANGUAGES` en `_valid_manifest`, con test.
- Hallazgo 7: incluir `LOG_DIR` en el snapshot del test de REQ-001.
- Hallazgo 5: decidir si los comentarios también van en inglés y, si es así, pasarlos en una ola de
  limpieza.

## Evidencia recomendada para el gate

- Esta revisión y la sección «Tras el arreglo #369» de `verification.md`.
- `evidence/live/after369-dry-run-es.txt`, `after369-dry-run-en.txt` y
  `after369-real-home-dry-run.json` (revisión `3540860`, `sha256` iguales).
- `gh pr checks 369`: 19/19 en `pass`.
