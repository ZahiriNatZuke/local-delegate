# Plan de implementación: autocompletado de la CLI (`completion powershell|zsh|bash`)

Desarrolla [spec.md](spec.md) (REQ-001…REQ-046 y desviaciones 1–8) sobre la base de
[research.md](research.md). Reglas comunes en [brief.md](brief.md). Los prototipos del laboratorio
están copiados en [evidence/lab/](evidence/lab/) (`gen.py`, `proto.ps1`, `proto.bash`, `proto.zsh`
y los `test-*` que cita research-shells); el scratchpad original es efímero. La release queda
**fuera**.

## 1. Resumen y orden de lotes

### Diseño en una página

```
cli.build_parser() ──► completion.build_model() ──► Model (nodos por ruta)
        ▲                          │                    │
  i18n.override(lang)   completion_values (backend-params)
                                                        ├─► render_powershell() + resources/completion/powershell.ps1
                                                        ├─► render_bash()       + resources/completion/bash.bash
                                                        └─► render_zsh()        + resources/completion/zsh.zsh
completion.render(shell, lang=None)
   ├─► `local-delegate completion <shell>` (stdout, bytes UTF-8, LF, idioma vigente)
   ├─► install --shell-completion: <dir>/completion/<fichero> + installed.json + bloque de carga en cada perfil
   ├─► doctor (scaffold.shell_completion): fichero == render(shell, lang=<manifiesto>) y bloque en cada perfil listado
   └─► update: reescribe los ficheros listados que difieren de render(shell, lang=<idioma configurado>)
```

- **Módulos nuevos** (en inglés):
  - `src/local_delegate/completion.py`: modelo, validación, render de los tres shells, cabecera,
    manifiesto, `plan_refresh`.
  - `src/local_delegate/shell_profiles.py`: shells que se resuelven, ruta del perfil y política de
    PowerShell, `completion_dir`, texto del bloque de carga.
- **`i18n.override(lang)`**: gestor de contexto nuevo en `src/local_delegate/i18n.py` (REQ-042).
- **Ayudantes de perfil** en `install.py`: `upsert_profile_block` y `remove_profile_block`
  (desviación 1), por bytes, con enlaces (REQ-045) y copia propia (REQ-046).
- **Plantillas** en `src/local_delegate/resources/completion/`, como ficheros de texto con
  `-text` en `.gitattributes`. Llevan los huecos `@@HEADER@@` y `@@TABLES@@`, que Python rellena;
  la lógica del recorrido vive en la plantilla y los datos en las tablas.
- **Algoritmo común**: el de research-shells §6.1, extendido con posicionales en secuencia
  (`backend-params set role key value`) y opciones de valor opcional (`--shell-completion`).

### Lotes (cada uno, una PR contra `main`)

| Lote | Contenido | Depende de | REQ |
|---|---|---|---|
| **L1** | Modelo del generador, validación, `completion_values` en `backend-params`, tests en `cli-python-matrix` | — | 003–007 |
| **L2a** | `i18n.override`, render PowerShell, cabecera, `completion powershell`, tests con pwsh/5.1, guardián de shells | L1 | 001, 002, 008–010, 011–020, 035–038, 042 (parte PowerShell) |
| **L2b** | Render bash y zsh, `completion bash|zsh`, tests con bash, `bash3` y zsh | L2a | 002, 008–017, 021, 022, 037, 038 (parte POSIX) |
| **L3a** | `shell_profiles.py` (rutas, política), ayudantes de perfil por bytes, fixture que protege el perfil real | L1 | 024, 025, 026 (directorio), 027 (texto), 028, 044 (detección), 045, 046 |
| **L3b** | `install`/`uninstall --shell-completion`, manifiesto, orden fijo, independencia de clientes | L2b, L3a | 023, 026, 027, 028 (escritura), 029–032, 043 (escritura), 044 (salto) |
| **L4** | Check `scaffold.shell_completion`, refresco en `update`, tabla y cifras | L3b | 033, 034, 043 (lectura), 041 (tabla) |
| **L5** | E2E en `scripts/check_install_e2e.py` y wheel instalado en `install-smoke` | L3b | 016 (readline real), 027 (control), 036, 039 |
| **L6** | Documentación: README, wiki, `Language.md`, CHANGELOG | L4, L5 (redacción en paralelo) | 041 |
| **L7** | Verificación en vivo con el binario instalado y cierre de gates | L6 | 040 y cierre |

Son **9 lotes**. Cada uno es mezclable por separado y deja `main` en verde: hasta L3b no existe la
opción de `install`, y hasta L2b el subcomando solo acepta `powershell`.

**Vuelta atrás**: cada lote se revierte con `git revert` de su PR, porque ninguno migra datos.
Para el usuario, `uninstall --shell-completion` quita perfiles y ficheros.

### Qué va en paralelo

- **Edición y lectura en paralelo** (agentes distintos, worktrees distintos):
  - con L1 mezclado: **L2a ∥ L3a**. Comparten solo `tests/conftest.py`, en secciones distintas: el
    guardián de shells (L2a) y el fixture de perfiles (L3a). El segundo en mezclarse rebasa sobre
    el primero.
  - con L3b mezclado: **L4 ∥ L5** (L4: `checks.py`, `update.py`, `completion.py`, wiki y tests de
    doctor; L5: `scripts/check_install_e2e.py` y `ci.yml`).
  - **L6** se redacta en paralelo con L4/L5. **Rebasa sobre L4** antes de abrir la PR (los dos
    tocan `Integration-install.md`) y se mezcla el último.
- **En serie**: L2a → L2b (los dos poseen `completion.py`, la línea `choices` del subcomando y el
  `env` de `ci.yml`), y L2b + L3a → L3b.
- **Comandos pesados, de uno en uno en toda la máquina**, desde la tool **Bash** y con el cerrojo
  `bash ~/.claude/scripts/pesado.sh <comando>`. Son pesados:
  - la suite de pytest (`-n 2` como máximo);
  - los ficheros de pruebas que lanzan shells reales;
  - `uv build`, `uv sync`, `uv venv` y `uv pip install`;
  - `scripts/check_install_e2e.py`.

  Un fichero de tests unitarios que tarda segundos puede ir sin cerrojo. Nunca el `bash` de
  PowerShell (es WSL).

### Propiedad de ficheros por lote

| Fichero | Fin de línea | L1 | L2a | L2b | L3a | L3b | L4 | L5 | L6 |
|---|---|---|---|---|---|---|---|---|---|
| `src/local_delegate/completion.py` (nuevo) | LF | ● | ● | ● | | ● (manifiesto) | ● (`plan_refresh`, lectura) | | |
| `src/local_delegate/i18n.py` | LF | | ● (`override`) | | | | | | |
| `src/local_delegate/shell_profiles.py` (nuevo) | LF | | | | ● | ● (ajustes) | | | |
| `src/local_delegate/resources/completion/*` (nuevos) | LF, `-text` | | ● (ps1) | ● (bash, zsh) | | | | | |
| `.gitattributes` | LF | | ● | | | | | | |
| `src/local_delegate/cli.py` | **CRLF** | ● (`_add_backend_params_parser`) | ● (subcomando) | ● (`choices`) | | ● (`--shell-completion`, `_run_install`) | | | |
| `src/local_delegate/install.py` | **CRLF** | | | | ● (ayudantes de perfil) | ● (acciones) | | | |
| `src/local_delegate/checks.py` | LF | | | | | | ● | | |
| `src/local_delegate/doctor.py` | LF | | | | | | ● (línea 71) | | |
| `src/local_delegate/update.py` | LF | | | | | | ● | | |
| `resources/i18n/{es,en}/cli.json` | LF | | ● | | | ● | | | |
| `resources/i18n/{es,en}/install.json` | LF | | | | ● | ● | ● (update) | | |
| `resources/i18n/{es,en}/doctor.json` | LF | | | | | | ● | | |
| `tests/conftest.py` | LF | | ● (guardián) | | ● (fixture) | | | | |
| `tests/test_cli_english.py` | LF | | ● | | | | | | |
| `tests/completion_shells.py` (nuevo, ayudante) | LF | | ● | ● | | | | | |
| `.github/workflows/ci.yml` | LF | ● (`cli-python-matrix`) | ● (`env` del paso de tests, `cli-python-matrix`) | ● (valores finales) | | | | ● (`install-smoke`, paso E2E) | |
| `scripts/check_install_e2e.py` | LF | | | | | | | ● | |
| `docs/wiki/Integration-install.md` | **CRLF** | | | | | | ● (tabla y cifras) | | ● (resto) |
| `README.md` | **CRLF** | | | | | | | | ● |
| `docs/wiki/Language.md` | LF | | | | | | | | ● |
| `CHANGELOG.md` | LF | | | | | | | | ● |

Antes de editar, cada agente comprueba el fin de línea con `git ls-files --eol <fichero>`; los
ficheros nuevos se ven con `git ls-files --eol` de uno vecino. `Path.write_text` convierte sin
avisar: editar con la tool Edit o escribir bytes.

## 2. Reglas de ejecución (todos los lotes)

- Worktree por lote en ruta corta:
  `git worktree add D:/Projects/ld-wt-cc-<lote> main -b feat/cli-completion-<lote>`. En el
  scratchpad falla por ruta larga.
- Comando base de tests, desde la tool Bash y en la raíz del worktree:

  ```bash
  bash ~/.claude/scripts/pesado.sh uv run pytest <ficheros> -q -rs -n 2 > "$TMP_OUT" 2>&1; echo "exit=$?"
  ```

  `TMP_OUT` va en el scratchpad de la sesión. La salida larga se lee por franjas
  (`tail`/`grep`), **sin** el MCP `local-delegate`: está prohibido en este cambio por orden del
  usuario. La entrega de cada agente dice «llamadas `local_*`: 0, prohibido por el brief».
- Lint: `uv run ruff check` y `uv run ruff format --check` sobre los ficheros tocados.
- Commits firmados, sin coautoría de Claude. Mensajes con el formato del repo:
  `feat(completion): … (SDD cli-completion, L2a)`.
- PR contra `main`. Antes de dar un lote por cerrado, revisar **todos** los checks con
  `gh pr checks <n>` (incluye CodeQL, Socket y GitGuardian), no solo `gh run list`. Las alertas de
  CodeQL se arreglan, no se descartan.
- Pruebas que tocan perfiles:
  - siempre en HOME simulado o en `tmp_path`, nunca el `$PROFILE`, `.bashrc` ni `.zshrc` reales;
  - desde L3a, el fixture autouse lo garantiza (§3, L3a);
  - los subprocesos de shell llevan `timeout=` y `stdin=DEVNULL`;
  - PowerShell, además, `-NoProfile -NonInteractive -ExecutionPolicy Bypass`; `powershell.exe`,
    con `PSModulePath` quitado del entorno.
- Nada huérfano: al cerrar cada lote, ni shells, ni esperas, ni procesos lanzados por el agente.
  Lo confirma en la entrega.
- Si algo invalida la spec, parar y avisar a la sesión principal; no ampliar alcance.

## 3. Tareas por lote

### L1 — Modelo del generador

- **Objetivo**: `completion.build_model(parser) -> Model` y su validación, sin render.
- **REQ**: 003, 004, 005, 006, 007.
- **Posee**:
  - `src/local_delegate/completion.py` (nuevo);
  - `src/local_delegate/cli.py` (solo `_add_backend_params_parser`, `cli.py:586-602`);
  - `tests/test_completion_model.py` (nuevo);
  - `tests/test_cli_backend_params.py` (un caso de no regresión);
  - `.github/workflows/ci.yml` (añadir `tests/test_completion_model.py` al paso «CLI tests» de
    `cli-python-matrix`, `ci.yml:232-252`, sin tocar su `timeout-minutes`).
- **Pasos**:
  1. Tipos `@dataclass(frozen=True)`:
     - `Option(strings, help, arity, values)`, con `arity ∈ {"flag", "required", "optional"}` y
       `values: tuple[str, ...] | None`;
     - `Positional(help, values)`;
     - `Node(path, subcommands, options, positionals)`;
     - `Model(nodes: dict[tuple[str, ...], Node])`.
  2. Recorrido de `parser._actions`:
     - subparsers visibles por `_SubParsersAction._choices_actions`, con su `help`;
     - el resto de nombres de `choices`, como ocultos;
     - ocultos también por `SUPPRESS` y por `deprecations.DEPRECATED_NAMES` de tipo
       `cli_command`/`cli_option`.
  3. Aridad:
     - `flag`: `nargs == 0`, o acciones `store_true/false/const`, `count`, `help` o `version`;
     - `required`: `nargs is None`;
     - `optional`: `nargs == "?"`;
     - cualquier otra cosa → `UnsupportedConstructError(path, action)`. También: alias de
       subparser, `prefix_chars != "-"` y opciones cortas distintas de `-h`.
  4. Valores: `getattr(action, "completion_values", None) or action.choices`, como tupla de `str`.
  5. Validación de fichas (REQ-007) con `UnsafeTokenError`.
  6. Ayuda: expandir `%` como argparse, colapsar espacios y, sin ayuda, usar el propio nombre.
  7. En `cli.py`: `action = set_.add_argument("role", …); action.completion_values = backend_params.ROLES`
     (y `tuple(backend_params.ALLOWED_KEYS)` para `key`; `ROLES` para `reset [role]`). Sin
     `choices=`.
- **Tests** (`tests/test_completion_model.py`):
  - rutas del modelo frente a un recorrido independiente;
  - ocultos: los tres nombres reales y un `DeprecatedName` de prueba con `monkeypatch`;
  - posicionales de `backend-params set`/`unset`/`reset`;
  - aridad de `update --version` (`required`) frente a la raíz `--version` (`flag`);
  - guardián: `build_model(cli.build_parser())` no lanza;
  - un parser de prueba por cada construcción no soportada y por cada ficha insegura;
  - un subcomando nuevo aparece sin tocar el generador.

  En `tests/test_cli_backend_params.py`, el rechazo `unknown_role` sigue saliendo del catálogo.
- **Verificación**: los dos ficheros sin cerrojo; suite completa con cerrojo antes de la PR;
  `cli-python-matrix` en verde en 3.11–3.15.
- **Hecho**: PR mezclada con todos los checks en verde.

### L2a — `i18n.override`, PowerShell y subcomando

- **Objetivo**: generar en un idioma dado, `render("powershell")`, el subcomando, las pruebas
  reales en pwsh 7 y 5.1 y el guardián de shells.
- **REQ**: 001, 002, 008–020 (PowerShell), 035, 036 (plantilla), 037, 038, 042.
- **Posee**:
  - `i18n.py`: `override(lang)`, gestor de contexto. Dentro, `lang()`, `t()` y
    `argparse_gettext` usan `lang`; restaura al salir, también ante una excepción; no toca la caché
    de `current()`;
  - `completion.py`: `render(shell, *, lang=None)` (construye el parser dentro de `override`),
    `render_powershell`, `ps_literal`, `header`, `header_version`;
  - `resources/completion/powershell.ps1` (nuevo) y `.gitattributes`
    (`src/local_delegate/resources/completion/** -text`);
  - `cli.py`: alta de `completion` y `cmd_completion`, con `choices=("powershell",)` en este lote;
  - `resources/i18n/{es,en}/cli.json` y `tests/test_cli_english.py` (`["completion"]` en
    `HELP_PATHS`);
  - `tests/conftest.py`, solo el guardián:
    - registro del marcador `shell("<nombre>")`;
    - `pytest_runtest_setup` (en el trabajador) copia el nombre a
      `item.user_properties.append(("shell", nombre))`, porque bajo xdist el controlador solo ve los
      nombres de los marcadores y no sus argumentos, y `user_properties` sí viaja en el informe;
    - `pytest_runtest_logreport` acumula las pruebas `passed` por shell desde
      `report.user_properties`;
    - `pytest_sessionfinish`, **solo en el controlador** (sin `config.workerinput`), fija
      `session.exitstatus = 1` con un mensaje si un shell de `COMPLETION_TEST_REQUIRE_SHELLS` tiene
      cero; en los trabajadores no hace nada;
  - tests nuevos: `tests/completion_shells.py`, `tests/test_completion_cli.py`,
    `tests/test_completion_render.py`, `tests/test_completion_powershell.py`,
    `tests/test_i18n_override.py` y `tests/test_completion_ci_shells.py` (test estático de los
    valores de `ci.yml`);
  - `.github/workflows/ci.yml`:
    - `env` del paso `Tests (pytest)` con una **expresión**, no `matrix.include` (que
      `tests/test_ci_gate.py:279-285` rechaza). En este lote, con los valores provisionales:

      ```yaml
      COMPLETION_TEST_REQUIRE_SHELLS: ${{ matrix.os == 'windows-latest' && 'pwsh,powershell' || 'pwsh' }}
      ```

      **No** se toca su `timeout-minutes` (`tests/test_ci_gate.py:324-368`);
    - añadir `tests/test_completion_render.py` a `cli-python-matrix`.
- **Pasos**:
  1. `ps_literal(s)`: el `ps_str` de `evidence/lab/gen.py`, con pares de sustitutos.
  2. La plantilla parte del recorrido de `evidence/lab/proto.ps1`, extendido con posicionales por
     índice y con la aridad `optional`. Registro con
     `-CommandName @('local-delegate', 'local-delegate-mcp')`. Tablas dentro del scriptblock y sin
     sintaxis de 7.
  3. La plantilla se lee con `importlib.resources` como bytes, y se rechaza si contiene `\r`.
  4. `cmd_completion`: `sys.stdout.buffer.write(render(shell).encode("utf-8"))`, salida 0.
  5. `tests/completion_shells.py`:
     - `find_shell(name)` resuelve `pwsh`, `powershell` (solo en Windows), `bash` (en Windows, el de
       Git: `Path(shutil.which("git")).parents[1] / "bin" / "bash.exe"`, rechazando `System32`),
       `bash3` (`/bin/bash` con `BASH_VERSINFO[0] == 3`) y `zsh`;
     - `require_or_skip(name)` llama a `pytest.fail` si el shell es obligatorio y falta; si no, lo
       salta con motivo.
  6. `tests/test_completion_powershell.py`:
     - un solo proceso por edición: un `.ps1` hace dot-source del script y recorre una tabla de
       líneas y columnas con `TabExpansion2`, imprimiendo JSON;
     - casos de REQ-011 a REQ-017, más el cursor a mitad de línea, el tooltip con tildes por
       dot-source y por `Invoke-Expression` (REQ-018) y el límite de 5.1 con `--` (REQ-020);
     - recuento de variables (REQ-019);
     - controles (a) sin coincidencias y (b) sin cargar el script (REQ-038).

     **Subconjunto de este lote**: REQ-015 se prueba sin el caso `completion `, que en L2a solo
     ofrecería `powershell`, y REQ-001 solo con `powershell` y `fish` (→ 2). L2b amplía las dos
     expectativas.
  7. Test estático de sintaxis prohibida en 5.1, de bytes `< 0x80` y de la lista blanca de
     REQ-002 (que admite `$((…))` y no lo confunde con `$(`).
  8. Las pruebas de integración se ejecutan con `cwd` en un directorio temporal **vacío**: sin
     respuesta, PowerShell completa rutas y falsearía los controles (a) y (b).
- **Tests**:
  - los ficheros nuevos;
  - `test_cli_english.py`, `test_i18n_parity.py`, `test_no_uncatalogued_text.py`,
    `test_detect_spanish_names.py`, `test_smoke.py` y `test_ci_gate.py`;
  - control positivo del ayudante: `COMPLETION_TEST_REQUIRE_SHELLS=zsh` con `-n 2` sale en rojo;
  - control positivo del **guardián**: `COMPLETION_TEST_REQUIRE_SHELLS=pwsh` con `-k "not pwsh"` y
    `-n 2` sale en rojo (ninguna prueba de pwsh llegó a pasar). En L2b se repite con `bash`.
- **Verificación**: `test_completion_powershell.py` con cerrojo (lanza pwsh y 5.1). En la PR, el
  CI en verde con la variable fijada.
- **Hecho**: PR mezclada. Los controles positivos se anotan para `verification.md` (invertir una
  vez a mano la expectativa y ver el fallo).

### L2b — bash y zsh

- **Objetivo**: `render("bash")` y `render("zsh")`, con sus pruebas reales.
- **REQ**: 002, 008–017, 021, 022, 037, 038 (POSIX).
- **Posee**:
  - `completion.py`: `render_bash`, `render_zsh` y los escapes de zsh;
  - `resources/completion/bash.bash` y `resources/completion/zsh.zsh` (nuevos);
  - `cli.py`: `choices=("powershell", "zsh", "bash")`;
  - `tests/test_completion_posix.py` (nuevo);
  - ampliaciones de `tests/test_completion_render.py`, `tests/test_completion_cli.py`,
    `tests/test_completion_powershell.py` (caso `completion ` con los tres shells),
    `tests/test_completion_ci_shells.py` y `tests/completion_shells.py`;
  - `ci.yml`, con los **valores finales**:

    ```yaml
    COMPLETION_TEST_REQUIRE_SHELLS: ${{ matrix.os == 'windows-latest' && 'pwsh,powershell,bash' || matrix.os == 'macos-latest' && 'zsh,bash,bash3,pwsh' || 'bash,pwsh' }}
    ```

- **Pasos**:
  1. bash, desde `evidence/lab/proto.bash`:
     - `case "$path|$w"` y `compgen -W`, con `=` como palabra y posicionales por índice;
     - `COMPREPLY` vacío para valores libres y registro
       `complete -o default -F _local_delegate local-delegate local-delegate-mcp`;
     - sin construcciones de bash 4, y los datos como funciones `case`.
  2. zsh, desde `evidence/lab/proto.zsh`:
     - `#compdef` en la línea 1 y cabecera en la 2;
     - guarda de `compinit -i`;
     - `_describe` (escapando `\` y `:`), `compadd`, `compset -P '*='` y `_files`;
     - patrón `loadautofunc`/`compdef`.
  3. Pruebas en `tests/test_completion_posix.py`:
     - bash: un proceso `bash --norc --noprofile` con `COMP_WORDS`/`COMP_CWORD` simulados sobre la
       tabla de casos, marcado `shell("bash")`. El mismo con `/bin/bash` marcado `shell("bash3")`,
       que además comprueba `BASH_VERSINFO[0] == 3`;
     - `complete -p local-delegate` incluye `-o default`;
     - zsh determinista (`zsh -f` con dobles), zsh real (`zpty` + `compinit -u -D`, humo) y las dos
       cargas (`source` y `fpath`);
     - controles (a) y (b) en cada shell;
     - test estático de bash 3.2.
- **Verificación**: el fichero con cerrojo en esta PC (Git Bash; zsh y `bash3` se saltan con
  motivo). En la PR, el CI en verde con los valores finales: el guardián del controlador falla si
  algún shell obligatorio no se ejecutó.
- **Hecho**: PR mezclada.

### L3a — Rutas de perfil, política, ayudantes por bytes y protección del perfil real

- **Objetivo**: la parte de `install` que no depende del render. Puede ir **en paralelo con L2a**.
- **REQ**: 024, 025, 026 (directorio), 027 (texto), 028, 044 (detección), 045, 046.
- **Posee**:
  - `src/local_delegate/shell_profiles.py` (nuevo);
  - `install.py`: solo los dos ayudantes nuevos, junto a `remove_block`;
  - `resources/i18n/{es,en}/install.json`: avisos de shell no encontrado, perfil no tocado (con su
    motivo), política restrictiva y política desconocida;
  - `tests/conftest.py`: solo el fixture autouse;
  - tests nuevos: `tests/test_shell_profiles.py`, `tests/test_profile_blocks.py` y
    `tests/test_profile_guard.py`.
- **Pasos**:
  1. En `shell_profiles.py`:
     - `resolve_shells(requested, *, platform, which, shell_env) -> list[ShellTarget]`, con
       `edition ∈ {"pwsh", "powershell", None}`. En Windows, `bash` = Git Bash derivado de `git`;
     - `query_powershell(executable, *, run) -> (Path | None, policy | None)`. Usa la consulta
       Base64 de REQ-025 (ruta + `Get-ExecutionPolicy`), `timeout=20`, `stdin=DEVNULL` y un entorno
       sin `PSModulePath` (para `powershell.exe`) y sin `PSExecutionPolicyPreference` (las dos
       ediciones; si no, la política `Process` del padre, p. ej. `Bypass`, falsearía la consulta).
       El ejecutor por defecto es `shell_profiles._default_run`;
     - `profile_path(target, home, *, simulated, query)`, con el respaldo por `ctypes` +
       `SHGetKnownFolderPath` (solo Windows, envuelto en `try`) y, como último recurso,
       `Path.home() / "Documents"`;
     - `policy_blocks(policy) -> bool` (`Restricted`, `AllSigned`, `Undefined`);
     - `candidate_profiles(...)`, `completion_dir(home, data_dir=None)`, `completion_file(dir,
       shell)` y `load_block(shell, file_path)`.
  2. En `install.py`, `upsert_profile_block(path, block) -> ProfileEdit` y
     `remove_profile_block(path) -> ProfileEdit`. **No** escriben: devuelven el destino resuelto
     (siguiendo enlaces), los bytes nuevos o «sin cambios», y un motivo si no se toca.
     - Decodificación: BOM UTF-8 o UTF-16 → ese códec, conservando el BOM; si no, UTF-8
       estricto; si no, `latin-1` (ida y vuelta exacta, porque el bloque es ASCII).
     - No se toca un fichero con NUL sin BOM UTF-16, ni uno con un marcador sin pareja.
     - Fin de línea: el dominante.
     - **Inserción**: fichero vacío o inexistente → `bloque + NL`; si no, `texto + NL + bloque +
       NL`. Si el texto acababa en NL, queda una línea en blanco de separación; si no, no.
     - **Retirada**: si delante del marcador de inicio hay `NL NL`, se quitan `NL + bloque + NL`;
       si hay un solo `NL`, lo mismo, y queda el texto sin salto final; si el bloque está al
       principio, se quita `bloque + NL`.
     - Ya con bloque: se reemplaza lo de dentro sin mover nada más.
  3. La escritura de un `ProfileEdit` (la usa L3b): función `write_profile_edit(edit, *,
     backup=True)`, que
     - escribe en el destino resuelto, sin `os.replace` sobre el enlace;
     - antes, si `backup`, crea `<destino>.local-delegate.bak` solo si no existe (REQ-046). L3b
       pasa `backup=False` en `uninstall` cuando el manifiesto dice que `install` creó el perfil;
     - devuelve error, sin lanzar, ante un `PermissionError`/`OSError`.
  4. **Fixture autouse** en `tests/conftest.py`: sustituye el **ejecutor por defecto**
     (`shell_profiles._default_run`) y el respaldo con `ctypes` por dobles que **fallan** si se
     llaman. No sustituye `query_powershell`: así los tests que le inyectan `run=` siguen
     funcionando, y solo falla una llamada real. Con eso, ningún test puede llegar al perfil real, ni siquiera con `Path.home`
     parcheado (`install.is_simulated_home`, `install.py:150-161`). El único caso real de pwsh lo
     desactiva de forma explícita con un marcador. `tests/test_profile_guard.py` comprueba que el
     fixture está activo, como `tests/test_environment_isolation.py`.
- **Tests**:
  - `test_profile_blocks.py`:
    - ida y vuelta byte a byte con UTF-8 con y sin BOM, UTF-16 LE/BE, ANSI cp1252 con `ó`, CRLF y
      LF, con y sin salto final, inexistente, solo el bloque y bloque ya presente;
    - NUL sin BOM y marcador huérfano → no se toca;
    - enlace simbólico (salta en Windows sin privilegio);
    - copia propia: `.bashrc.bak` del usuario intacto y `.local-delegate.bak` creada solo si no
      existe;
    - fichero de solo lectura → error devuelto;
    - control positivo de la desviación 1: con `_read_text` + `upsert_block` el caso ANSI pierde
      contenido.
  - `test_shell_profiles.py`:
    - matriz de REQ-024 y REQ-025 con dobles, incluida la decodificación de ruta con `ó` y política;
    - `policy_blocks`;
    - con HOME simulado nunca se llama a la consulta;
    - texto del bloque con ruta con `ó`, espacio y `'`;
    - un caso real con `pwsh` que se salta fuera de Windows.
- **Verificación**: los ficheros sin cerrojo, salvo el caso real de pwsh (con cerrojo). Suite
  completa con cerrojo antes de la PR: el fixture no debe romper tests existentes.
- **Hecho**: PR mezclada. Nada de esto se usa todavía desde `install`.

### L3b — `install` y `uninstall` con `--shell-completion`

- **Objetivo**: cablear L2b y L3a en `install`/`uninstall`, con el manifiesto.
- **REQ**: 023, 026, 027, 028 (escritura), 029, 030, 031, 032, 043 (escritura), 044 (salto).
- **Posee**:
  - `cli.py`: `--shell-completion` en los parsers de `install` y `uninstall`, no en `update`;
    `_run_install`;
  - `install.py`: `plan_completion_install(...)` y `plan_completion_uninstall(...)`, que devuelven
    `Action` con `kind="profile"`, `kind="completion"` y `kind="manifest"`;
  - `completion.py`: lectura y escritura del manifiesto (`read_manifest`, `manifest_action`);
  - `shell_profiles.py` (ajustes);
  - `resources/i18n/{es,en}/{cli,install}.json`, incluido el mensaje «autocompletado escrito» de
    la rama sin clientes;
  - tests: `tests/test_completion_install.py` (nuevo), y `tests/test_install_english.py` y
    `tests/test_install.py` si su salida de `uninstall` cambia.
- **Pasos**:
  1. Parser: `--shell-completion` con `nargs="?"`, `const="auto"`, `action="append"` y `choices`
     (REQ-023), añadido aparte en `install` y en `uninstall`.
  2. `_run_install`, en este orden (REQ-030):
     1. `_resolve_clients`: un error sale con 2 antes de escribir nada;
     2. idioma: `install.plan_language(install.Options(home=home, components=set(),
        targets=targets, python_exe=…))`. Es puro y sin clientes; si hiciera falta, se extrae una
        función que no necesite `Options` completas;
     3. autocompletado:
        - en `install`, si se pidió;
        - en `uninstall`, si se pidió o si el `uninstall` no tiene restricciones. «Sin
          restricciones» se define por los datos: `args.hooks`, `args.skill`, `args.memory` y
          `args.mcp` en `True`, `--clients` ausente o solo `auto`, y `--target` ausente.
          `--no-client-cli`, `--agents`, `--dry-run`, `--python` y `--home` no cuentan.

        Se aplica con `inst.apply(actions, dry_run=args.dry_run)` y se guarda su recuento de
        fallos;
     4. `uninstall --shell-completion` sin `--clients`/`--target` explícitos termina aquí, sin
        tocar clientes; con ellos, sigue y quita también esos clientes;
     5. rama «ningún cliente» (`cli.py:203-212`): si se escribió autocompletado, lo dice con el
        texto nuevo en vez de solo «no se escribió nada», y sale con 1 si hubo fallos;
     6. flujo de clientes como hoy. Si no hay componentes de cliente y sí autocompletado, no sale
        con 2 (`cli.py:225-227`). El código final suma los fallos de los dos `apply`.
  3. Acciones de `install`, por cada `ShellTarget` resuelto:
     - edición de PowerShell con política que bloquea → aviso de REQ-044 y nada más; si se saltan
       todas las ediciones, no se escribe `local-delegate.ps1` ni su entrada del manifiesto;
     - el fichero de completado: escritura atómica sin `.bak`, contenido `render(shell, lang=L)`,
       con `L` el idioma del paso 2. «Ya al día» si los bytes coinciden;
     - el bloque por perfil con `literal=` (para `--dry-run`), escrito con `write_profile_edit`
       (copia propia antes). «Ya al día» si no cambia; un perfil no tocable se avisa y se salta;
     - el manifiesto (REQ-043), fusionando con el existente. `created` y `created_parent` salen
       de si el perfil y su carpeta existían antes del plan.
  4. Acciones de `uninstall`:
     - retirar el bloque de la unión de perfiles del manifiesto y candidatos existentes;
     - borrar el perfil y su carpeta solo si el manifiesto dice `created`/`created_parent` y
       quedan vacíos;
     - sin copia previa si el manifiesto dice `created` (`write_profile_edit(..., backup=False)`);
       en otro caso, borrar `.local-delegate.bak` si el perfil quedó igual a ella;
     - en un `uninstall` parcial por shell, quitar solo la entrada de ese shell del manifiesto y
       borrarlo solo si queda vacío;
     - borrar los ficheros, el manifiesto y el directorio `completion/` si queda vacío.
- **Tests** (`tests/test_completion_install.py`, con `make_home`/`snapshot`, `conftest.py:231` y
  `:332`, y dobles de `which` y de la consulta):
  - REQ-023: parser en los dos subcomandos; `update --shell-completion` → 2;
  - REQ-026: contenido igual a `render(shell, lang=L)`, sin `.bak`; con `LOCAL_DELEGATE_LANG=en`
    sale en `en`;
  - REQ-029: dos pasadas, snapshot igual (manifiesto incluido);
  - REQ-030: HOME vacío sin clientes, con el texto nuevo y salida 0; con perfil de solo lectura,
    salida 1; `--no-hooks --no-skill --no-memory --no-mcp --shell-completion` no sale con 2;
    `--clients nope --shell-completion` → 2 sin crear nada;
  - REQ-031: `install --dry-run` y `uninstall --dry-run` sin cambios;
  - REQ-032:
    - ida y vuelta: inexistente → ni perfil, ni copia, ni carpeta; vacío preexistente → sigue;
      con y sin salto final → idéntico;
    - `uninstall --no-client-cli` **sí** lo quita;
    - `uninstall --clients codex` y `uninstall --no-hooks` no lo tocan;
    - `uninstall --shell-completion` no toca clientes; `uninstall --shell-completion zsh` deja bash
      y su entrada; `uninstall --shell-completion --clients codex` quita el autocompletado y Codex;
    - `uninstall` sin nada instalado;
  - REQ-043: fusión al añadir otro shell, y manifiesto roto;
  - REQ-044: `Restricted` → se salta con aviso, también con `powershell` explícito; las dos
    ediciones bloqueadas → ni `.ps1` ni entrada;
  - `install` sin la opción no toca nada.
- **Verificación**: el fichero con cerrojo, más `test_install*.py`. Suite completa con cerrojo
  antes de la PR. `check_install_e2e.py` sigue en verde (no cambia todavía).
- **Hecho**: PR mezclada.

### L4 — `doctor` y `update`

- **Objetivo**: los verbos de diagnóstico y reparación.
- **REQ**: 033, 034, 043 (lectura), 041 (tabla y cifras).
- **Posee**:
  - `checks.py`: probe `_probe_shell_completion`, entrada `scaffold.shell_completion` en `CHECKS`
    (`checks.py:2111`) y docstrings con la cifra (`checks.py:5`, `:2186` y los textos que vigila
    `tests/test_checks.py:1210-1216`);
  - `doctor.py:71` («the 25 checks» → 26);
  - `update.py`: paso de refresco junto a `plan_catalog_refresh` (`update.py:326-330`) y
    comentario en el bloque de `REPAIRS` (`update.py:153-165`);
  - `completion.py`: `plan_refresh(home, data_dir, lang) -> list[Action]`;
  - `resources/i18n/{es,en}/doctor.json` (título, detalles y `fix_hint`) e `install.json`
    (mensaje del refresco);
  - `docs/wiki/Integration-install.md`: fila de la tabla del doctor y «veinticinco» →
    «veintiséis» en `:182` y `:340`;
  - tests: `tests/test_wiki.py` (entrada 26), `tests/test_checks.py` (`== 26` y
    `_NUMBER_WORDS[26] = "veintiséis"`), `tests/test_doctor.py:267`,
    `tests/test_doctor_english.py:3` y `:89`, y los nuevos `tests/test_doctor_completion.py` y
    `tests/test_update_completion.py`.
- **Pasos**:
  1. Probe:
     - importa `completion` (y con ella `cli`) **dentro** del probe, no arriba de `checks.py`, como
       hace `cli._run_install` con `checks`, para evitar el import circular y el coste;
     - sin manifiesto ni ficheros, devuelve «no instalado» sin renderizar nada (lo comprueba
       `test_doctor_completion.py`);
     - directorio por `shell_profiles.completion_dir(ctx.home)`;
     - lee el manifiesto; por cada shell, compara el fichero con `render(shell, lang=<manifiesto>)`
       y comprueba con `managed_block` que cada perfil listado tiene el bloque y que apunta al
       fichero;
     - estados de REQ-033, sin lanzar shells.
  2. `plan_refresh`: por cada fichero listado que difiera de `render(shell, lang=L)`, con
     `L = install.plan_language(install_options(opts)).lang` (como `plan_catalog_refresh`), una
     acción que lo reescribe y actualiza el manifiesto. `update` lo llama **siempre** tras
     `plan_repairs`, haya o no clientes presentes.
  3. Ajustar todas las cifras.
- **Tests**:
  - el probe en todos sus estados: versión vieja, bloque borrado (control positivo), fichero
    ausente, ficheros sin manifiesto, manifiesto roto;
  - el invariante de idioma: fichero en `es`, `doctor` en `en` y en `es` → mismo veredicto `ok`;
  - `update` **sin clientes** con fichero viejo → una acción y después cero;
  - `update` con idioma configurado `en` y fichero `es` → una acción;
  - sin manifiesto → cero acciones;
  - los guardianes de cifras y de la wiki.
- **Verificación**: los ficheros de doctor, update, checks y wiki con cerrojo; suite completa antes
  de la PR.
- **Hecho**: PR mezclada.

### L5 — E2E e instalación del wheel

- **Objetivo**: probar «instalado» de extremo a extremo en los tres sistemas y el binario del wheel
  en CI. Puede ir **en paralelo con L4**.
- **REQ**: 016 (readline real), 027 (control positivo), 036, 039.
- **Posee**:
  - `scripts/check_install_e2e.py`;
  - `.github/workflows/ci.yml`: job `install-smoke`, y el `timeout-minutes` del paso E2E de 3 a
    6, comprobando que `tests/test_ci_gate.py` lo acepta (si no, actualizándolo con su
    justificación);
  - presupuesto del job `test` (15 min, `ci.yml:134`, atado a `TIMEOUT_JOB_TEST` y al comentario
    de la firma en `tests/test_ci_gate.py:340-353`): se mide la duración del job en el primer run.
    Si pasa de unos 12 min, se sube el límite del job **junto con** `TIMEOUT_JOB_TEST` y el
    comentario, en la misma PR, o se reparte la fase E2E en un job propio. Antes de cambiarlo, se
    busca con `grep` en `tests/` cualquier otro guardián que fije ese valor.

  La búsqueda de shells se copia en mínimo dentro del script, porque `scripts/` no importa de
  `tests/`.
- **Pasos**:
  1. Fase de autocompletado tras la fase actual, con el mismo HOME temporal, según REQ-039:
     - sembrar perfiles (y `.bashrc.bak` del «usuario»);
     - instalar dos veces;
     - completar en el shell real cargando el perfil:
       - PowerShell: `-NoProfile -ExecutionPolicy Bypass`;
       - bash en Linux: `HOME=<tmp> bash -i`;
       - bash en macOS: `/bin/bash -l -i`;
       - zsh: `ZDOTDIR` + `zpty`;
     - control de REQ-027 (borrar el fichero, cargar sin error y sin completar, reponer);
     - `uninstall` y comparación de bytes.
  2. En Linux, además, readline real con `pty` de la biblioteca estándar: `bash -i` con el perfil,
     teclear `local-delegate install --home ./dir` con un fichero `con espacio` dentro y Tab, y
     comprobar que el nombre se completa entero (REQ-016).
  3. Cada subproceso con `timeout` y `stdin=DEVNULL` (salvo el pty); en Windows, 5.1 sin
     `PSModulePath`.
  4. `install-smoke`, tras el handshake:
     - `.venv-smoke/bin/local-delegate completion {powershell,bash,zsh}` con la cabecera de la
       versión del wheel;
     - en bash, cargar la salida y completar `backend-params set `, que debe dar `mechanical`;
     - con `pwsh` (viene en ubuntu), lo mismo con `TabExpansion2`.
- **Verificación**: `scripts/check_install_e2e.py` con cerrojo en esta PC (fase de Windows). En la
  PR, los logs del paso E2E en los tres sistemas muestran la fase, y el job `install-smoke` está en
  verde.
- **Hecho**: PR mezclada.

### L6 — Documentación

- **Objetivo**: los tres sitios de una release (REQ-041).
- **Posee**: `README.md` (CRLF), `docs/wiki/Integration-install.md` (CRLF, todo menos lo de L4),
  `docs/wiki/Language.md` (LF) y `CHANGELOG.md` (LF, `## [Unreleased]`, `CHANGELOG.md:7`).
- **Pasos**:
  - redactar en paralelo con L4/L5 sobre lo mezclado, con el contenido de REQ-041 y el coste
    medido de cada forma de carga (research-shells §1);
  - **rebasar sobre L4** antes de abrir la PR.
- **Tests**: `tests/test_wiki.py` y la suite completa.
- **Hecho**: PR mezclada tras L4 y L5.

### L7 — Verificación en vivo y cierre

- **Objetivo**: REQ-040 y los gates. El usuario ya dio el aprobado previo para el paso de solo
  lectura; **no** se escribe en su perfil real en este SDD.
- **Posee**: `.sdd/changes/cli-completion/{verification.md,review.md,handoff.md}` y
  `.sdd/changes/cli-completion/evidence/live/*`. `state.json` lo actualiza la sesión principal.
- **Pasos** (desde la tool Bash, con cerrojo en los pesados):
  1. `uv build` en un worktree de `main` actualizado.
  2. `uv venv <scratch>/venv-cc` y
     `uv pip install --python <scratch>/venv-cc/Scripts/python.exe dist/*.whl`. **No** se toca
     `uv tool` ni el daemon.
  3. **Solo lectura sobre el HOME real**:
     - `sha256` de los dos perfiles reales y de `LOG_DIR/completion/` (si existen);
     - `local-delegate.exe install --shell-completion --dry-run --no-hooks --no-skill --no-memory --no-mcp --no-client-cli`;
     - guardar la salida, con las rutas reales, la política de cada edición y la ruta en
       `LOG_DIR`;
     - repetir los `sha256`: deben salir iguales.
  4. **Instalado sobre perfiles temporales**:
     - `install --home <scratch>/home-cc --no-client-cli --shell-completion`, con perfiles
       sembrados como en el E2E;
     - por cada edición (`pwsh` y `powershell.exe` con `PSModulePath` vacío), con la política real
       que dio el paso 3; si esa edición la bloquea, se añade `-ExecutionPolicy Bypass` y se anota
       en `verification.md`, para que el fallo no se tome por un defecto del script:
       `-NoProfile -NonInteractive -Command ". '<perfil temporal>'; TabExpansion2 …"` sobre los
       casos de REQ-012 a REQ-015, imprimiendo `CompletionText` y `ToolTip`;
     - `doctor --home <scratch>/home-cc` con `scaffold.shell_completion` en `ok`;
     - `uninstall --home …` y comparación de bytes.
  5. Comprobación manual opcional en una consola real (PSReadLine, Tab y Ctrl+Espacio), con un
     perfil temporal (`pwsh -NoProfile -NoExit -Command ". '<perfil temporal>'"`), si el usuario
     quiere verlo.
  6. Borrar el venv y los HOME temporales, y confirmar que no queda ningún `pwsh`/`powershell`
     propio.
- **Hecho**: `verification.md` con la evidencia; gates cerrados (sección 5); PR de cierre
  `docs(completion): gates quality, conformance y memory; cierre del SDD (cli-completion)`, que
  incluye `evidence/lab/` y `evidence/live/`.

## 4. Matriz REQ → lote → prueba

| REQ | Lote | Prueba o evidencia |
|---|---|---|
| 001 | L2a (subconjunto), L2b | `test_completion_cli.py` |
| 002 | L2a, L2b | `test_completion_render.py::test_static*` |
| 003–007 | L1 | `test_completion_model.py` (+ `test_cli_backend_params.py` para 005), también en `cli-python-matrix` |
| 008–010 | L2a, L2b | `test_completion_render.py` |
| 011–017 | L2a, L2b, L5 (016 con readline) | `test_completion_powershell.py`, `test_completion_posix.py`, E2E |
| 018–020 | L2a | `test_completion_powershell.py` |
| 021, 022 | L2b | `test_completion_posix.py` (`bash`, `bash3`, `zsh`) |
| 023 | L3b | `test_completion_install.py` |
| 024, 025 | L3a | `test_shell_profiles.py` |
| 026, 027 | L3a, L3b, L5 | `test_shell_profiles.py`, `test_completion_install.py`, E2E (control de 027) |
| 028 | L3a, L3b | `test_profile_blocks.py`, `test_completion_install.py` |
| 029–032 | L3b, L5 | `test_completion_install.py`, `check_install_e2e.py` |
| 033 | L4 | `test_doctor_completion.py`, guardianes de cifras, `test_wiki.py` |
| 034 | L4 | `test_update_completion.py` |
| 035 | todos | guardianes de i18n, nombres y ayuda |
| 036 | L2a, L5 | revisión de `pyproject.toml`, `install-smoke` |
| 037 | L2a, L2b | guardián en `tests/conftest.py`, `test_completion_ci_shells.py`, CI |
| 038 | L2a, L2b | casos (a)/(b) y su inversión anotada en `verification.md` |
| 039 | L5 | paso E2E del CI en tres sistemas |
| 040 | L7 | `evidence/live/`, `verification.md` |
| 041 | L4, L6 | `test_wiki.py`, gate de conformidad |
| 042 | L2a | `test_i18n_override.py`, `test_completion_render.py` |
| 043 | L3b, L4 | `test_completion_install.py`, `test_doctor_completion.py`, `test_update_completion.py` |
| 044 | L3a, L3b | `test_shell_profiles.py`, `test_completion_install.py` |
| 045, 046 | L3a, L5 | `test_profile_blocks.py`, E2E (`.bashrc.bak`) |

## 5. Gates

- **Calidad** (al final de L6, antes de L7):
  - suite completa en `main` actualizado:
    `bash ~/.claude/scripts/pesado.sh uv run pytest -q -rs -n 2`, en verde;
  - `ruff check` y `ruff format --check` limpios;
  - el último CI de `main` con todos los checks en verde (`gh pr checks` de la última PR), con
    CodeQL a 0 alertas;
  - el guardián de shells de REQ-037 en verde en los tres sistemas (sin mirar a ojo los
    `skipped`).

  Evidencia en `verification.md`, con recuentos y enlaces a los runs. Lo marca la sesión principal
  en `state.json`.
- **Conformidad**: un `personal-sdd-result-reviewer` revisa la rama mezclada contra la spec, con la
  matriz de la sección 4, `verification.md` y la evidencia en vivo, y deja su dictamen en
  `review.md`. Las desviaciones 1–8 se revisan como aprobadas o no. Si algún REQ queda sin
  evidencia, se reabre el lote dueño.
- **Memoria**: la sesión principal, con la skill `session-memory`:
  - nota de jornada en el vault `projects/local-delegate/` con las trampas reutilizables:
    codificación de PowerShell 5.1 y de la consulta de `$PROFILE`, `_read_text` con perfiles ANSI,
    política `Restricted` y perfiles nuevos, `REPAIRS` sin cliente, `PSModulePath` heredado, Git
    Bash frente a WSL, `matrix.include` y `test_ci_gate.py`, xdist y guardianes en el controlador,
    y shells de los runners;
  - puntero en `MEMORY.md`;
  - backlog §1.12 1b marcado como hecho.

## 6. Riesgos del plan y puntos de reapertura

| Riesgo | Señal | Respuesta |
|---|---|---|
| Un runner no trae un shell supuesto (zsh o `bash3` en macOS, pwsh en ubuntu) | El guardián del controlador en rojo en el primer run | Ajustar el valor de ese sistema o instalar el shell en el job; nunca dejar un sistema sin al menos un shell obligatorio |
| Las pruebas de shell alargan el paso `Tests (pytest)` (límite de 10 min, atado a `test_ci_gate.py`) | Duración del paso en Windows > 6 min | Un proceso por shell y fichero (ya previsto); si aun así no basta, paso propio en `ci.yml` con su `timeout-minutes` |
| `i18n.override` interfiere con la caché de `current()` o con `_argparse_in_language` (`cli.py:1696-1710`) | `test_i18n_override.py` o `test_cli_english.py` en rojo | `override` no toca `current()`, solo una variable de módulo que `lang()` consulta primero; test de anidamiento con `_argparse_in_language` |
| El fixture autouse de L3a rompe tests de instalación existentes | Suite en rojo en L3a | Que el doble solo falle si se llama de verdad; los tests existentes no llaman a la consulta |
| El guardián de textos sin catálogo marca código de render | `test_no_uncatalogued_text.py` en rojo | Mover a la plantilla lo que tenga palabras; como último recurso, una excepción `verbatim` justificada en `tests/data/uncatalogued_exceptions.json` |
| Conflictos en `tests/conftest.py` (L2a ∥ L3a) o en el catálogo i18n | Conflicto de merge | Secciones distintas; el segundo en mezclarse rebasa |
| `cli.py` e `install.py` en CRLF reescritos en LF | Diff entero en la PR | Tool Edit y `git diff --stat` antes del commit |
| Plantillas con CRLF en el checkout de Windows | Test de REQ-001 (`b"\r"`) en rojo en Windows | `-text` en `.gitattributes` (L2a) y rechazo de `\r` al leer |
| La fase E2E supera los 6 min | Corte por tiempo en macOS o Windows | Medir la duración en el primer run; separar la fase en un paso propio si hace falta |
| El job `test` se acerca a sus 15 min (pytest de Windows ya en 4–5 min, más pwsh/5.1 y E2E a 6) | Duración del job > 12 min en el primer run | Subir el límite junto con `TIMEOUT_JOB_TEST` y el comentario de `test_ci_gate.py:340-353`, o repartir en otro job (L5) |
| La política de ámbito `Process` del padre falsea la consulta | `Bypass` en la salida del paso 3 de L7 desde la tool PowerShell | `PSExecutionPolicyPreference` quitada del entorno (L3a), con test |
| La consulta de `$PROFILE` tarda o se cuelga | Tope de 20 s alcanzado | El E2E usa HOME simulado y no consulta; la consulta real solo en el test de L3a (Windows) y en L7 |
| El respaldo con `ctypes` falla en algún Windows | Excepción en el test | Último recurso `Path.home() / "Documents"`, documentado |
| Algo invalida la spec (p. ej. 5.1 no completa posicionales como se espera) | Prueba real en contra | Parar el lote y reportar a la sesión principal; no improvisar |

## 7. Fuera del plan

La release va después, como en los cambios anteriores: subir la versión, publicar en PyPI, revisar
el depscore de Socket del paquete, actualizar la Mac y, si el usuario lo decide, instalar el
autocompletado en su perfil real. La decide la sesión principal con el usuario.

## Cambios tras la revisión

Revisión adversarial: [review-plan.md](review-plan.md). Decisiones de la sesión principal
aplicadas el 2026-10-20.

| Hallazgo | Cambio |
|---|---|
| Bloqueante: idioma del fichero en L3b y API de i18n inexistente | L2a añade `i18n.override` y `render(shell, lang=…)`; L3b fija el orden clientes → idioma → autocompletado → rama sin clientes |
| Mayor 1: guardián poco fiable con xdist | Guardián en el controlador con `user_properties` y `pytest_sessionfinish`, y `pytest.fail` en el ayudante (L2a) |
| Mayor 2: `matrix.include` rompe `test_ci_gate.py` | Expresión en el `env` del paso, con valores provisionales en L2a y finales en L2b; test estático |
| Mayor 3: un test podía llegar al perfil real | Fixture autouse que falla si se consulta el perfil real, con su test guardián (L3a) |
| Mayor 4: modelo probado solo en 3.11 | `test_completion_model.py` (L1) y `test_completion_render.py` (L2a) en `cli-python-matrix` |
| Mayor 5: `/bin/bash` 3.2 se saltaba en silencio | Shell `bash3` obligatorio en macOS (L2b) |
| Mayor 6: vivo sin el HOME real | L7 añade el `--dry-run` de solo lectura con `sha256` antes y después, y `doctor` sobre el HOME temporal; sin escribir en el perfil real |
| Mayor 7: prototipos en un scratchpad efímero | Copiados a `evidence/lab/`; el plan apunta allí |
| Menor 1: `Language.md` es LF | Tabla de propiedad corregida |
| Menor 2: `doctor.py:71` y `test_doctor_english.py:3` | En L4 |
| Menor 3: control positivo de REQ-027 | En L5 (paso 4 del E2E) |
| Menor 4: `.bak` en las acciones de L3b | `write_profile_edit` con copia propia (L3a), usada por L3b |
| Menor 5: expectativas entre L2a y L2b | Subconjunto explícito en L2a y ampliación en L2b |
| Menor 6: fin de línea de las plantillas | `.gitattributes` con `-text` y rechazo de `\r` (L2a) |
| Menor 7: `.bash_profile` en el E2E de macOS | `/bin/bash -l -i` (L5) |
| Menor 8: mensaje engañoso sin clientes | Texto nuevo y salida 1 con fallos (L3b, REQ-030) |
| Menor 9: L4 y L6 sobre la wiki | L6 rebasa sobre L4 |
| Menor 10: vuelta atrás | Línea en §1 |
| Menor 11: salida de `uninstall` en tests existentes | `test_install_english.py` y `test_install.py` en L3b |
| Revisión de la spec (manifiesto, política, enlaces, `.bak`, `uninstall` parcial, `update` sin clientes) | Repartidos en L3a, L3b y L4 según la matriz de la sección 4 |
| 2.ª ronda, mayor 1: `--no-client-cli` contaba como restricción | L3b define «sin restricciones» por los datos; casos `uninstall --no-client-cli` (lo quita) y `--clients codex`/`--no-hooks` (no lo tocan) |
| 2.ª ronda, menor 1: el controlador no ve el argumento del marcador | L2a: `user_properties` en `pytest_runtest_setup`, recuento en `pytest_runtest_logreport`, veredicto en `pytest_sessionfinish` del controlador; controles positivos con `-n 2` y `-k "not pwsh"`/`"not bash"` |
| 2.ª ronda, menor 2: `PSExecutionPolicyPreference` heredada | L3a la quita del entorno de la consulta, con test; fila de riesgo |
| 2.ª ronda, menor 3: el fixture rompía los tests de la consulta | L3a sustituye el ejecutor por defecto (`_default_run`) y el respaldo con `ctypes`, no `query_powershell` |
| 2.ª ronda, menor 4: L7 sin fijar la política | L7 usa la política real; `-ExecutionPolicy Bypass` anotado si bloquea |
| 2.ª ronda, menor 5: presupuesto del job `test` | L5 mide el job y sube el límite con `TIMEOUT_JOB_TEST` y el comentario, o reparte; `grep` de otros guardianes; fila de riesgo |
| 2.ª ronda, menor 6: import circular y coste en `doctor` | L4: import perezoso de `completion` en el probe y test de «sin manifiesto no renderiza» |
| 2.ª ronda de la spec (B, E, F, G, J) | L3a/L3b sin copia si `created`; lista blanca con `$((…))`; sin `.ps1` si se saltan todas las ediciones; manifiesto en `uninstall` parcial y `--shell-completion --clients`; `cwd` vacío en las pruebas (L2a) |

### Hallazgos de revisión no aplicados

Ninguno del plan. Los dos de la spec que no se aplican (aviso de `doctor` por idioma de la
preferencia; escribir igual con `powershell` explícito y política restrictiva) están en la sección
equivalente de `spec.md`.
