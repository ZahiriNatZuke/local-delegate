# Revisión adversarial del gate `plan` — SDD `cli-completion`

Revisor: agente revisor del plan (solo lectura). Fecha: 2026-10-20. Base: `main` en `465fc97`.
Artefactos: `plan.md` contra `spec.md`, `research.md` y el código real. Llamadas `local_*`: 0
(prohibidas por el brief). No dejo procesos vivos: solo lecturas con `sed`/`grep`/`git ls-files`.

## Veredicto

**BLOQUEADO**, con 1 bloqueante y 7 mayores. Ninguno obliga a rehacer el diseño ni a investigar de
nuevo: son correcciones del texto del plan. Con los cambios propuestos abajo basta una re-revisión
ligera de esos puntos.

El plan está bien trabajado en lo grueso: los lotes son mezclables, la propiedad de ficheros evita
choques en paralelo (L2a ∥ L3a y L4 ∥ L5 no comparten ficheros), las cifras «25 → 26» están casi
todas y el cerrojo `pesado.sh`, el `-n 2` y la regla de nada huérfano figuran en las reglas comunes.

## Matriz REQ → lote → prueba (comprobada)

| REQ | Lote | Prueba en el plan | Observación |
|---|---|---|---|
| 001 | L2a, L2b | `test_completion_cli.py` | Entre L2a y L2b `completion fish` y `completion bash` dan 2: ver menor 5 |
| 002 | L2a, L2b | `test_completion_render.py::test_static*` | OK |
| 003–007 | L1 | `test_completion_model.py`, `test_cli_backend_params.py` | Solo corre en Python 3.11: mayor 4 |
| 008–010 | L2a, L2b | `test_completion_render.py` | OK |
| 011–017 | L2a, L2b | `test_completion_powershell.py`, `test_completion_posix.py` | REQ-015 `completion ` cambia entre L2a y L2b: menor 5 |
| 018–020 | L2a | `test_completion_powershell.py` | OK |
| 021 | L2b | `test_completion_posix.py` | `/bin/bash` 3.2 se puede saltar en silencio: mayor 5 |
| 022 | L2b | `test_completion_posix.py` | zsh solo en el CI de macOS (aceptado por la spec) |
| 023 | L3b | `test_completion_install.py` | OK |
| 024, 025 | L3a | `test_shell_profiles.py` | El camino del HOME real no se prueba instalado: mayor 6 |
| 026 | L3a, L3b | `test_completion_install.py` | Idioma del fichero: bloqueante 1 |
| 027 | L3a, L3b | `test_shell_profiles.py` | **Falta** el control positivo «fichero borrado, el perfil carga sin error»: menor 3 |
| 028 | L3a | `test_profile_blocks.py` | La copia `.bak` no aparece en las acciones de L3b: menor 4 |
| 029–032 | L3b, L5 | `test_completion_install.py`, E2E | OK |
| 033 | L4 | `test_doctor_completion.py` y guardianes | `doctor.py:71` queda fuera: menor 2 |
| 034 | L4 | `test_update_completion.py` | OK |
| 035 | todos | guardianes | OK |
| 036 | L2a, L5 | `install-smoke` | Fin de línea de las plantillas en Windows: menor 6 |
| 037 | L2a, L2b | guardián, `ci.yml` | `matrix.include` rompe `test_ci_gate.py` (mayor 2); el guardián con xdist no es fiable (mayor 1) |
| 038 | L2a, L2b | casos (a)/(b) | OK |
| 039 | L5 | E2E | `.bash_profile` en macOS necesita shell de inicio de sesión: menor 7 |
| 040 | L7 | `evidence/live/` | Ver mayor 6 |
| 041 | L4, L6 | `test_wiki.py`, conformidad | Fin de línea de `Language.md` mal anotado: menor 1 |

Todos los REQ tienen lote y prueba. Los huecos están en la calidad de algunas pruebas, no en la
cobertura.

## Hallazgos

### Bloqueante

**1. L3b se contradice en el idioma del fichero de completado y no prevé cómo cambiar de idioma.**
- Evidencia: el paso 2 de L3b (`plan.md:321-328`) aplica el autocompletado «justo tras resolver
  `home`», **antes** de `_resolve_clients` y de construir `opts`. Pero los pasos 3 y 4
  (`plan.md:330-340`) piden renderizar «con el idioma ya resuelto por el paso de idioma de
  `install` (`install.plan_language`)». `plan_language(opts)` necesita un `Options`
  (`install.py:1075-1106`), que solo existe después de `_install_options` (`cli.py:223`), y la
  acción que escribe `language.json` se aplica dentro de `inst.apply` de los clientes
  (`install.py:1307-1311`). Además `i18n` no tiene ningún mecanismo para generar en un idioma
  distinto del vigente: solo tiene `current`, `lang`, `t` y `t_lang` (`i18n.py:34-72`). Y
  `build_parser()` usa `t()` en todas las ayudas.
- Riesgo: el idioma vigente del proceso (`i18n.current()`: variable, luego `language.json` de
  `config.LOG_DIR`) puede diferir del que `plan_language` escribe. Pasa, por ejemplo, con una
  preferencia `system` vieja que se sobrescribe, o con HOME simulado, donde `language_dir(opts)`
  no es `config.LOG_DIR`. Entonces `install` deja un fichero en un idioma y el `doctor` siguiente
  lo marca `warn` (REQ-033), lo que rompe REQ-026 y REQ-029. Y el implementador tendría que
  inventarse una API de `i18n`, que el brief prohíbe («si algo invalida el plan, para»).
- Cambio propuesto: fijar en L3b:
  1. una API explícita, `completion.render(shell, *, lang: str | None = None)`, que construye el
     parser bajo un gestor de contexto nuevo `i18n.override(lang)`, con su test: `render("powershell", lang="en")` con la suite en `es` da la ayuda inglesa y deja `i18n.lang()` intacto al salir;
  2. el orden: resolver `targets` primero (un `--clients` inválido no debe escribir nada), luego
     calcular el idioma con `install.plan_language(...)` sobre un `Options` mínimo (o una función
     extraída que no necesite clientes), y después planificar el autocompletado antes de la rama
     `if not targets` (`cli.py:203`);
  3. que `i18n.override` pertenezca a L2a (fichero `i18n.py`, LF), para que L3b y L4 lo usen.

### Mayores

**1. El guardián de shells obligatorios no es fiable con `pytest-xdist`.**
- Evidencia: el CI corre `uv run pytest -q -n auto --dist loadgroup` (`.github/workflows/ci.yml:161`
  y `:220`). El plan deja elegir entre un «directorio común» y `xdist_group`
  (`plan.md:214-218`, `:506`). Con un directorio común, el guardián puede correr en otro
  trabajador **antes** que las pruebas de shell: verde o rojo según el reparto. Con
  `xdist_group`, depende del orden alfabético de los ficheros dentro del grupo.
- Cambio: hacer el guardián en `tests/conftest.py` con `pytest_terminal_summary` o
  `pytest_sessionfinish` en el **proceso controlador**. Allí xdist ya ha reenviado todos los
  informes. Se marcan las pruebas de shell (marcador `shell("pwsh")`, etc.); si un shell de
  `COMPLETION_TEST_REQUIRE_SHELLS` tiene cero pruebas `passed`, se fija `session.exitstatus = 1`
  con un mensaje. Control positivo: una ejecución local con la variable apuntando a un shell
  inexistente tiene que salir en rojo. Así sobra mirar a ojo en los logs si hubo `skipped`
  (`plan.md:221-223`, `:254-256`), que con `-q` sin `-rs` ni siquiera se ve.

**2. `matrix.include` rompe `tests/test_ci_gate.py`.**
- Evidencia: `_jobs_declared_in_ci` lanza `AssertionError` ante cualquier matriz con `include` o
  `exclude` (`tests/test_ci_gate.py:279-285`). El plan ofrece `matrix.include` como primera opción
  (`plan.md:183-185`).
- Cambio: quitar esa opción y fijar la variable con una expresión en el `env` del paso, por
  ejemplo `${{ matrix.os == 'windows-latest' && 'pwsh,powershell,bash' || matrix.os ==
  'macos-latest' && 'zsh,bash,bash3,pwsh' || 'bash,pwsh' }}`. Escribir en el plan los **valores
  finales** de cada sistema (hoy L2b dice «`bash` en Windows y ubuntu; `zsh,bash` en macOS»,
  `plan.md:237-238`, que se lee como si se perdieran `pwsh` y `powershell`).

**3. Ningún test puede llegar al `$PROFILE` real por accidente: falta una guarda en la suite.**
- Evidencia: `is_simulated_home` compara con `Path.home()` (`install.py:149-161`), y la suite
  parchea `Path.home` a un `tmp_path` en varios sitios (`tests/test_install_clients.py:41-50`,
  `tests/test_install_opencode.py:38`, `tests/test_install_header.py:36`…). Un test que llame
  `install`/`uninstall` con `--home` igual a ese `Path.home` parcheado se toma por HOME **real**.
  L3b hace que `uninstall` quite el bloque **siempre** (`plan.md:323-324`) y que pregunte la ruta
  a `pwsh`/`powershell.exe`. Esa respuesta sale de la carpeta *Documents* de Windows, no de
  `Path.home`, así que apunta al **perfil real del usuario**. Hoy ningún test hace esa
  combinación (`tests/test_install_clients.py:164-166` usa `install` sin la opción), pero basta
  uno nuevo. `config.LOG_DIR` sí está aislado (`tests/conftest.py:49-60`); los perfiles no.
- Cambio: en L3a, un fixture autouse en `tests/conftest.py` que sustituye la consulta por defecto
  de `shell_profiles` (el `run` y el respaldo con `ctypes`) por un doble que **falla** si se llama.
  El único caso real de pwsh (`test_shell_profiles.py`) lo desactiva de forma explícita. Y un test
  guardián de que el fixture está activo, siguiendo el patrón de `tests/test_aislamiento_entorno.py`.

**4. El modelo depende de atributos privados de `argparse` y solo se prueba en Python 3.11.**
- Evidencia: `requires-python = ">=3.11"` (`pyproject.toml:6`). La matriz de Python
  (`ci.yml:232-252`, versiones 3.11–3.15) solo corre `test_cli_english.py` y
  `test_cli_renamed_names.py`. El generador lee `_actions`, `_choices_actions` y
  `_SubParsersAction` (`plan.md:136-140`), que han cambiado entre versiones (3.14 añadió
  `deprecated=` y color en la ayuda).
- Cambio: en L1, añadir `tests/test_completion_model.py` al paso «CLI tests» de
  `cli-python-matrix`, y en L2a `tests/test_completion_render.py`. Son rápidos y sin shells, así
  que no hace falta tocar el `timeout-minutes` de 5 min del paso.

**5. `/bin/bash` 3.2 de macOS se puede saltar en silencio.**
- Evidencia: L2b prueba «además en `/bin/bash` si existe y es 3.x» (`plan.md:247-248`). El `bash`
  del PATH de `macos-latest` es el de Homebrew (5.x), así que REQ-021 («`/bin/bash` 3.2 de macOS»)
  solo se cumple si esa rama corre, y nada obliga a que corra.
- Cambio: un nombre propio en el registro y en la variable, `bash3`, resuelto como `/bin/bash`
  con la versión comprobada. Que `COMPLETION_TEST_REQUIRE_SHELLS` de macOS lo incluya
  (`zsh,bash,bash3,pwsh`).

**6. La verificación en vivo no recorre el camino del HOME real, que es el que usará el usuario.**
- Evidencia: L7 instala con `--home <scratch>/home-cc` (`plan.md:436`), es decir, con HOME
  simulado. Con HOME simulado nunca se pregunta `$PROFILE` y el fichero va a
  `<home>/.local/share/...` (REQ-025, REQ-026). La consulta Base64 de UTF-16, el respaldo de
  *Documents* y `config.LOG_DIR` solo se prueban con dobles y con un test unitario de L3a. Es
  justo la trampa de la memoria «probar la pieza no es probar el uso».
- Cambio: añadir a L7 un paso **de solo lectura** con el HOME real: `local-delegate.exe install
  --shell-completion --dry-run --no-hooks --no-skill --no-memory --no-mcp` desde el venv
  temporal. La salida guardada en `evidence/live/` debe enseñar las rutas reales de los dos
  perfiles (pwsh y 5.1) y del fichero en `LOG_DIR`, y se toma el `sha256` del `$PROFILE` real
  antes y después: tiene que ser igual. Es lectura pura (REQ-031 permite leer perfiles y preguntar
  la ruta), pero la sesión principal debe confirmarlo con el usuario porque roza la regla «no
  toques el perfil real». Añadir también `local-delegate.exe doctor` con el HOME temporal para ver
  `scaffold.shell_completion` en `ok`.

**7. Los prototipos de los que parten L2a y L2b viven en un scratchpad efímero.**
- Evidencia: `plan.md:187-189` y `:240-243` remiten a `completion-lab/gen.py`, `proto.ps1`,
  `proto.bash` y `proto.zsh`. Esos ficheros están en el scratchpad de **esta** sesión
  (`research-shells.md:7`). Un relevo a una sesión nueva los pierde, y los agentes de worktree solo
  los ven por ruta absoluta.
- Cambio: antes de lanzar L2a, copiarlos a `.sdd/changes/cli-completion/evidence/lab/` (solo los
  `proto.*`, `gen.py` y los `test-*` que cita research-shells) y que el plan apunte allí.

### Menores

1. **Fin de línea mal anotado**: `docs/wiki/Language.md` es **LF** (`git ls-files --eol`), no CRLF
   como dice `plan.md:87`. Corregir la tabla.
2. **Cifra suelta sin guardián**: `src/local_delegate/doctor.py:71` dice «the 25 checks» y
   `tests/test_doctor_english.py:3` dice «los mismos 25 checks». Ningún test los vigila. Añadirlos
   a L4. El resto de sitios está bien listado: `checks.py:5`, `:2186`, las cinco frases de
   `tests/test_checks.py:1208-1214` (con `_NUMBER_WORDS[26] = "veintiséis"`; la frase «ver los
   otros veinticinco» sale de `_NUMBER_WORDS_WITHOUT_NOUN[25]`, que ya existe),
   `tests/test_checks.py:93`, `tests/test_doctor.py:267`, `tests/test_doctor_english.py:89`,
   `tests/test_wiki.py:35-48` y `Integration-install.md:182` y `:340`.
3. **Falta el control positivo de REQ-027** («con el fichero borrado, cargar el perfil no da error
   y no completa»). No está en ningún lote. Asignarlo a L5 (en el shell real, tras borrar el
   fichero de completado y antes de `uninstall`) o a L3b con un shell real.
4. **La copia `.bak` de REQ-028 no aparece en las acciones de L3b** (`plan.md:329-338`). L3a
   devuelve bytes sin escribir, así que la acción de L3b tiene que llamar a `_backup`
   (`install.py:235-237`) antes de escribir, y `test_completion_install.py` debe comprobarlo.
5. **Expectativas que cambian entre L2a y L2b**: con `choices=("powershell",)`, REQ-015
   (`completion ` → tres shells) y REQ-001 (`completion bash` sale con 0) solo se pueden afirmar
   en L2b. Decir en L2a qué subconjunto se prueba y que L2b amplía esas expectativas.
6. **Fin de línea de las plantillas**: el runner `windows-latest` usa `core.autocrlf=true`
   (precedente en `.gitattributes`, entradas `vendor/**` y `hooks/*.py`). Las plantillas
   `bash.bash` y `zsh.zsh` llegarían con CRLF al checkout de Windows y a un wheel construido allí.
   Añadir en L2a `src/local_delegate/resources/completion/** -text` (o `text eol=lf`) a
   `.gitattributes`, y leer la plantilla de forma que nunca deje pasar `\r`. El test de REQ-001
   (ningún `b"\r"`) en Windows lo cazaría, pero mejor evitarlo.
7. **E2E de bash en macOS**: `.bash_profile` solo lo lee un shell de inicio de sesión. REQ-039
   dice `bash -i` (`spec.md:535`), que lee `.bashrc`. Para la fase `--shell-completion bash` de
   macOS (`plan.md:404`), usar `/bin/bash -l -i` (o `--login`) y decirlo en L5.
8. **Mensaje engañoso sin clientes**: con `--shell-completion` y ningún cliente, el flujo sigue a
   la rama `if not targets`, que imprime `cli.install.no_client.nothing_written`
   (`cli.py:203-212`) y devuelve 0 aunque el autocompletado haya fallado. L3b debe ajustar el
   mensaje cuando se escribió el autocompletado y devolver 1 si hubo fallos; el test de REQ-030
   debe afirmar ese texto.
9. **L4 ∥ L6 sobre el mismo fichero**: los dos editan `docs/wiki/Integration-install.md` (CRLF).
   El plan ya mezcla L6 el último; añadir «L6 rebasa sobre L4 antes de abrir la PR» como en L3b.
10. **Vuelta atrás**: el plan no la menciona. Basta una línea: cada lote se revierte con
    `git revert` de su PR (ninguno migra datos) y, para el usuario, `uninstall` quita perfiles y
    ficheros.
11. **Salidas de `uninstall` en los tests existentes**: `tests/test_install_english.py:50-72`
    compara la salida de `uninstall` en inglés. Con L3b, `uninstall` imprime acciones nuevas.
    Añadir ese fichero (y `test_install.py`) a la lista de tests de L3b, para no descubrirlo en la
    suite completa.

## Comprobado y correcto

- **Propiedad de ficheros**: L2a ∥ L3a no comparten fichero (`cli.py`/`cli.json` frente a
  `install.py`/`install.json`). L4 ∥ L5 tampoco (`completion.py`, `checks.py`, `update.py` y wiki
  frente a `ci.yml` y el script E2E). L2a → L2b → L3b en serie sobre `cli.py` y `ci.yml`.
- **Fin de línea**: `cli.py` e `install.py` en CRLF, y `checks.py`, `update.py`, `ci.yml`, el
  catálogo, `CHANGELOG.md` y los tests en LF, como dice el plan (salvo `Language.md`).
- **Guardianes**: `HELP_PATHS` es una lista fija (`tests/test_cli_english.py:34-56`) y L2a la
  amplía. `test_smoke.py:210-231` despacha todo subcomando registrado sin cambios. No hay test que
  exija documentar cada subcomando u opción, así que L2a y L3b no rompen la documentación antes
  de L6. `test_wiki.py:219` exige la fila de cada check, y es de L4.
- **Construcciones del parser**: solo `-h` como opción corta y `nargs="?"` en dos posicionales
  (`cli.py:469`, `:600`); `recalcular-coste` es un parser propio sin `help`, no un alias
  (`cli.py:1510-1513`), y `deprecations.py:58-59` registra los dos nombres.
- **`update` sin `REPAIRS`**: `plan_repairs` salta lo que no tiene cliente (`update.py:288-294`).
  El paso propio junto a `plan_catalog_refresh` (`update.py:326-330`) es correcto.
- **Runners**: Windows trae pwsh, 5.1 y Git Bash (`shutil.which("git")` →
  `...\Git\cmd\git.exe`, y `parents[1]/bin/bash.exe` es correcto); ubuntu trae bash y pwsh; macOS
  trae zsh y pwsh. `install-smoke` corre en ubuntu (`ci.yml:267-288`) y el wheel con hatchling
  incluye `resources/` (`pyproject.toml:84-87`).
- **Comandos pesados y procesos**: cerrojo `pesado.sh` desde la tool Bash, `-n 2`, `timeout=` y
  `stdin=DEVNULL` en subprocesos, y cierre sin huérfanos por lote y en L7. Correcto.
- **Gates**: calidad (suite, ruff, `gh pr checks`, CodeQL a 0, cero saltos), conformidad (revisor
  de resultado con la matriz) y memoria (nota en el vault, puntero y backlog) bien definidos y
  comprobables. Con el mayor 1, «cero saltos» pasa a comprobarse con el guardián, no a ojo.

## Evidencia recomendada para aprobar en la re-revisión

- L3b reescrito con el orden «clientes → idioma → autocompletado → rama sin clientes» y la API
  `render(shell, lang=…)` con `i18n.override` en L2a.
- Guardián en el controlador (`pytest_terminal_summary`) y valores finales de
  `COMPLETION_TEST_REQUIRE_SHELLS` con expresión, no `matrix.include`.
- Fixture autouse que impide la consulta real de `$PROFILE`.
- `cli-python-matrix` con los tests del modelo y del render.
- `bash3` en macOS, el paso de solo lectura con el HOME real en L7 (pendiente de confirmar con el
  usuario) y los prototipos copiados a `evidence/lab/`.

## Segunda ronda

Fecha: 2026-10-20. Revisados `plan.md` (691 líneas, «Cambios tras la revisión») y `spec.md` (46
REQ, con REQ-042 a REQ-046 nuevos) contra el código. Llamadas `local_*`: 0. Sin procesos vivos.

### Veredicto

**APROBADO CON CAMBIOS MENORES.** Los 1 + 7 hallazgos de la primera ronda están resueltos, todos
comprobados en el texto: el orden clientes → idioma → autocompletado, `i18n.override`, el guardián
en el controlador, la expresión en lugar de `matrix.include`, el fixture contra el perfil real,
`cli-python-matrix`, `bash3`, la lectura del HOME real en L7 y los prototipos en `evidence/lab/`
(los ficheros están). Queda **un mayor nuevo**, acotado a L3b y a una línea de la spec y del plan:
L1, L2a y L3a pueden arrancar ya; L3b no debe lanzarse hasta corregirlo.

### Matriz con los REQ nuevos

| REQ | Lote | Prueba | Estado |
|---|---|---|---|
| 042 (`render(lang=)`, `i18n.override`) | L2a | `test_i18n_override.py`, `test_completion_render.py` | OK; el riesgo con `_argparse_in_language` (`cli.py:1696-1710`) está anotado |
| 043 (manifiesto) | L3b (escritura), L4 (lectura) | `test_completion_install.py`, `test_doctor_completion.py`, `test_update_completion.py` | OK; incluye manifiesto roto en los tres verbos |
| 044 (política) | L3a (detección), L3b (salto) | `test_shell_profiles.py`, `test_completion_install.py` | OK, salvo el menor 2 |
| 045 (enlaces) | L3a, L5 | `test_profile_blocks.py` | OK (se salta en Windows sin privilegio; corre en Linux y macOS) |
| 046 (copia propia) | L3a, L3b, L5 | `test_profile_blocks.py`, E2E con `.bashrc.bak` | OK |

El resto de la matriz (`plan.md:580-608`) cuadra con la spec. Todos los REQ tienen lote y prueba.

### Propiedad de ficheros

Sin conflictos nuevos. L1 → L2a → L2b tocan `ci.yml` en serie. L2a ∥ L3a comparten solo
`tests/conftest.py`, en secciones distintas, y el plan lo declara con rebase (`plan.md:64-66`).
L3b y L4 tocan `completion.py` en serie. L4 ∥ L5 siguen sin ficheros comunes, y L6 rebasa sobre L4.

### Hallazgos nuevos

**Mayor 1. La regla «`uninstall` sin restricciones» cuenta `--no-client-cli` como restricción.**
- Evidencia: `spec.md:513-514` y `plan.md:404-405` dicen «sin `--clients` distinto de `auto`, sin
  `--target` y sin ningún `--no-*`». `--no-client-cli` es un `--no-*` (`cli.py:1602-1606`), pero
  no restringe componentes ni clientes: es el procedimiento del sandbox. El E2E lo pasa en todas
  sus llamadas, `uninstall` incluido (`scripts/check_install_e2e.py:95` y `:145`). Con la regla
  literal, el `uninstall` del E2E (REQ-039) y el de L7 con `--no-client-cli` **no** quitarían el
  autocompletado. Y `--agents`, `--dry-run`, `--python` y `--home` tampoco son restricciones,
  aunque la regla no lo diga.
- Cambio: definirla por los datos, no por la forma de la opción: «sin restricciones» = los cuatro
  componentes activos (`args.hooks`, `skill`, `memory` y `mcp` en `True`), `--clients` ausente o
  solo `auto`, y `--target` ausente. Añadir a `test_completion_install.py` el caso
  `uninstall --no-client-cli` → **sí** lo quita, más los dos de control que ya están
  (`--clients codex` y `--no-hooks` → no lo tocan).

**Menor 1. El guardián no puede leer el argumento del marcador desde el controlador.**
Bajo xdist, el informe que llega al controlador trae `report.keywords` con el nombre del marcador
(`shell`), no su argumento (`"bash"`). Cambio: en `pytest_runtest_setup` (que corre en el
trabajador), copiar el nombre a `item.user_properties.append(("shell", nombre))`, que xdist sí
serializa, y contar en `pytest_terminal_summary` por `report.user_properties`. El hook debe además
no hacer nada en los trabajadores (`hasattr(config, "workerinput")`). El control positivo que ya
pide L2a (`COMPLETION_TEST_REQUIRE_SHELLS=zsh` en rojo) hay que correrlo **con `-n 2`**, no en
serie.

**Menor 2. La política consultada hereda la del proceso padre.**
PowerShell guarda la política de ámbito `Process` en la variable de entorno
`PSExecutionPolicyPreference`, que heredan los hijos. Si `install` se lanza desde un PowerShell
abierto con `-ExecutionPolicy Bypass` (es el caso de la tool PowerShell de esta sesión), la
consulta de REQ-025 devuelve `Bypass` y REQ-044 escribiría un perfil que luego da error en una
consola normal. La evidencia del paso 3 de L7 también saldría engañosa. Cambio: quitar
`PSExecutionPolicyPreference` del entorno de la consulta, como `PSModulePath`, con un test en
`test_shell_profiles.py` que compruebe el entorno pasado.

**Menor 3. El fixture de L3a, si sustituye la función, rompe los propios tests de la consulta.**
`plan.md:352-357` sustituye `shell_profiles.query_powershell`. Pero los tests de decodificación,
tope y `PSModulePath` (`plan.md:370`) llaman a esa función con `run=` inyectado y se encontrarían
el doble que falla. Cambio: que el fixture sustituya el **ejecutor por defecto** (por ejemplo
`shell_profiles._default_run` y el respaldo con `ctypes`), no la función. Así el `run=` inyectado
sigue funcionando y solo falla una llamada real.

**Menor 4. L7 carga el perfil temporal sin fijar la política.**
El paso 4 de L7 (`plan.md:566-568`) usa `-NoProfile -NonInteractive -Command ". '<perfil>'"` sin
`-ExecutionPolicy Bypass`. Con HOME simulado, la política se inyecta como `RemoteSigned`
(`spec.md:407`), así que `install` escribe para las dos ediciones. Si la política real de 5.1 en
esta PC es `Restricted` (el valor por defecto de Windows de escritorio), el dot-source falla.
Cambio: usar la política que dio el paso 3. Si alguna edición la bloquea, cargar con
`-ExecutionPolicy Bypass` y anotarlo en `verification.md`, para que el fallo no se tome por un
defecto del script.

**Menor 5. Presupuesto del job `test` de CI.**
El job tiene 15 min (`ci.yml:134`), atado a `TIMEOUT_JOB_TEST` y a la firma «20:00» del comentario
(`tests/test_ci_gate.py:340-353`). El pytest de Windows ya tarda entre 4 m 13 s y 4 m 58 s
(`ci.yml:120-122`) y crece con las pruebas de pwsh y 5.1; L5 sube el paso E2E de 3 a 6 min.
Paso + E2E + checkout y sync se acercan a 15. Cambio: en L5, medir la duración del job en el
primer run. Si pasa de unos 12 min, subir el límite del job **junto con** `TIMEOUT_JOB_TEST` y el
comentario de la firma, en la misma PR. Añadirlo a la tabla de riesgos (`plan.md:641`, `:648`).

**Menor 6. Import circular y coste en `doctor`.**
El probe de L4 renderiza hasta tres scripts y, para eso, construye el parser de `cli.py`. Cambio:
importar `completion` (y con ella `cli`) **dentro** del probe, no arriba de `checks.py`, como ya
hace `cli._run_install` con `checks`. Y comprobar en `test_doctor_completion.py` que el probe sin
manifiesto no renderiza nada (estado «no instalado» sin coste).

### Evidencia recomendada para cerrar el gate

- La definición de «sin restricciones» corregida en `spec.md` (REQ-032) y en L3b, con el caso
  `uninstall --no-client-cli`.
- Los menores 1–3 escritos en L2a y L3a. Los 4–6 se pueden resolver dentro de su lote sin otra
  revisión.
