# Verificación: autocompletado de la CLI (`completion powershell|zsh|bash`)

Gate de calidad y lote L7 (verificación en vivo, REQ-040), hechos el 2026-10-21 sobre `main`
con todos los lotes L1–L6 mezclados (PR #359–#367).

## Entorno

- Revisión: `17d76593178cc8a197d36116da0f0361128ed7c1` (`origin/main`, PR #365), en el worktree
  `D:/Projects/ld-wt-compl-l7`, rama `docs/completion-close`.
- Windows 11 Enterprise LTSC 2024 (10.0.26200); Python 3.11.15; uv 0.10.12; pwsh 7.6.6;
  Windows PowerShell 5.1; Git Bash 5.3.15. Sin `zsh` ni `bash` 3 en esta PC (los cubre el CI de
  macOS).
- Wheel construido desde esa revisión: `local_delegate_mcp-0.37.0-py3-none-any.whl`, instalado en
  un venv temporal del scratchpad (`venv-cc`). **No** se tocó `uv tool`, el daemon ni la tarea
  programada.
- Comandos pesados (`uv sync`, la suite, `uv build`, `uv pip install`) con el cerrojo
  `bash ~/.claude/scripts/pesado.sh`, de uno en uno, desde la tool Bash.

## Gate de calidad

### Suite completa en local

`bash ~/.claude/scripts/pesado.sh uv run pytest -q -rs -n 2` (tras
`uv sync --all-extras --group dev --group ui`):

**4113 pasados, 0 fallidos, 28 saltados, 2 avisos** en 216,85 s. Los intermitentes conocidos
(`test_a_ttl_counts_from_request_end`, timeouts de node en `test_dashboard_cost.py`) no
aparecieron. Los dos avisos son el `DeprecationWarning` de `anyio.abc.BlockingPortal` dentro de
`starlette/testclient.py` (dependencia, no código del repo).

Saltos clasificados (lista de `-rs`):

| N.º | Motivo | Clasificación |
| --- | --- | --- |
| 13 | `tests/test_completion_posix.py`: `shell 'zsh' not found` | Esperado: no hay zsh en esta PC; obligatorio y verde en el CI de macOS (guardián, abajo) |
| 11 | `tests/test_completion_posix.py`: `shell 'bash3' not found` | Esperado: `/bin/bash` 3.2 solo existe en macOS; obligatorio y verde allí |
| 1 | `tests/test_completion_powershell.py:276`: `the limit is of Windows PowerShell 5.1` | Por diseño: el caso de REQ-020 solo aplica a la edición 5.1 y se salta en la de pwsh |
| 1 | `tests/test_completion_install.py`: enlaces simbólicos sin privilegio en Windows | Del sistema: crear enlaces exige privilegio; corre en Linux y macOS |
| 1 | `tests/test_checks.py`: `chmod` no quita permisos de lectura en Windows | Del sistema, anterior a este SDD |
| 1 | `tests/test_dashboard_ui.py:1624`: solo aplica al CI, que sí instala el navegador | Anterior a este SDD |

Ningún salto de `pwsh`, `powershell` ni `bash` (Git Bash): los tres shells de esta PC corrieron.
La salida íntegra quedó en el scratchpad de la sesión (`quality-suite.txt`); no se versiona.

### Ruff

- `uv run ruff check`: `All checks passed!`
- `uv run ruff format --check`: `316 files already formatted`

### CI de `main` y CodeQL

- Run de CI del último commit de `main` (`17d7659`, push):
  [39549628850](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/39549628850),
  `success`, 13 de 13 jobs en verde (`test` en Windows, Ubuntu y macOS, `test-lang-es`, `lint`,
  `secrets`, `install-smoke`, `cli-python-matrix` 3.11–3.15, `ci-gate`). En el mismo push, CodeQL
  ([39549628771](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/39549628771)),
  Wiki y Vendor audit en `success`.
- `gh pr checks 365`: 19 de 19 en `pass` (incluye `Analyze (python)`, `CodeQL`, GitGuardian, las
  dos de Socket, `audit` y `ci-gate`).
- Alertas abiertas de code scanning en `refs/heads/main`: **0**
  (`gh api ".../code-scanning/alerts?ref=refs/heads/main&state=open" -q length`).

### Guardián de shells (REQ-037) en los tres sistemas

Logs del job `test` del run 39549628850 (descargados con `gh api .../actions/jobs/<id>/logs`):

| Sistema | Job | `COMPLETION_TEST_REQUIRE_SHELLS` | Resultado de pytest | Mensaje del guardián |
| --- | --- | --- | --- | --- |
| Windows | [119055620500](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/39549628850/job/119055620500) | `pwsh,powershell,bash` | 4026 pasados, 53 saltados | ausente |
| Ubuntu | [119055620574](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/39549628850/job/119055620574) | `bash,pwsh` | 4002 pasados, 77 saltados | ausente |
| macOS | [119055620643](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/39549628850/job/119055620643) | `zsh,bash,bash3,pwsh` | 4026 pasados, 53 saltados | ausente |

«Mensaje del guardián ausente» quiere decir que no aparece `COMPLETION_TEST_REQUIRE_SHELLS: no
test passed for the required shell(s)` (`tests/conftest.py:451-454`), que es lo que escribe
cuando un shell obligatorio queda con cero pruebas pasadas, y que el job sale con 0. El guardián
decide por las pruebas **pasadas** de cada shell (`user_properties`), así que no hace falta leer
los `skipped` a ojo. Los valores coinciden con los finales de REQ-037. En los mismos logs, el paso
«Instalador end-to-end» (REQ-039) muestra la fase `== autocompletado del shell ==` con
«+ Tab ofrece `mechanical`» en pwsh y powershell (Windows), bash y pwsh (Ubuntu), zsh, bash 3 de
inicio de sesión y pwsh (macOS), el control de REQ-027 y la «vuelta atrás exacta».

## Verificación en vivo (L7, REQ-040)

Guion: `evidence/live/l7_live.py`, ejecutado con el python del venv temporal
(`venv-cc/Scripts/python.exe -I l7_live.py <evidence/live> <scratch>`) y
`LOCAL_DELEGATE_LANG=es`, así importa y ejecuta el `local-delegate.exe` del wheel, no el del repo.
Cada salida está en `evidence/live/`. Tras la ejecución, el hook de `ruff` del commit obligó a
reescribir el guion en estilo (`dict(...)` a literales y formato), sin cambiar lo que hace.

### Paso 3: solo lectura sobre el HOME real

Ruta de perfil y política de cada edición, preguntadas con la misma consulta que usa `install`
(`shell_profiles.query_powershell`, REQ-025):

| Edición | Perfil (`$PROFILE.CurrentUserAllHosts`) | Política real | ¿Bloquea? |
| --- | --- | --- | --- |
| pwsh 7.6 | `C:\Users\Yohan\Documents\PowerShell\profile.ps1` | `Bypass` | no |
| Windows PowerShell 5.1 | `C:\Users\Yohan\Documents\WindowsPowerShell\profile.ps1` | `RemoteSigned` | no |

`LOG_DIR` = `C:\Users\Yohan\AppData\Local\local-delegate`; directorio de completado
`C:\Users\Yohan\AppData\Local\local-delegate\completion` (no existe).

`local-delegate.exe install --shell-completion --dry-run --no-hooks --no-skill --no-memory --no-mcp --no-client-cli`
salió con 0 y enseñó las rutas reales de los dos perfiles (los dos como `created: true`: hoy no
existen), el bloque de carga literal, el fichero en `LOG_DIR\completion\local-delegate.ps1` y el
manifiesto (`evidence/live/step3-dry-run-stdout.txt`).

sha256 antes y después (`evidence/live/step3-real-home-dry-run.json`): **iguales**.

| Ruta | Antes | Después |
| --- | --- | --- |
| `Documents\PowerShell\profile.ps1` | no existe | no existe |
| `Documents\PowerShell\Microsoft.PowerShell_profile.ps1` | `0a33bfaf06b40f3ebdb7c0dd4df8473f317d11449209185d89a0d3af2f8849f1` | `0a33bfaf06b40f3ebdb7c0dd4df8473f317d11449209185d89a0d3af2f8849f1` |
| `Documents\WindowsPowerShell\profile.ps1` | no existe | no existe |
| `LOG_DIR\completion\` | no existe | no existe |

No se escribió en el perfil real ni en `LOG_DIR\completion\`.

### Paso 4: instalado sobre un HOME temporal

- HOME temporal `<scratch>/home-cc` con `.claude`, `.codex` y `.config/opencode`, y los perfiles
  sembrados como en el E2E: el de 5.1 en cp1252 con tildes y CRLF, el de pwsh en UTF-8 con BOM.
- `install --home <home-cc> --no-client-cli --shell-completion`: salida 0; escribió
  `local-delegate.ps1` e `installed.json` en `<home-cc>/.local/share/local-delegate/completion`
  (`evidence/live/step4-install.txt`).
- Completado con `TabExpansion2` tras cargar el perfil temporal con dot-source, un proceso por
  edición, `-NoProfile -NonInteractive`, directorio de trabajo vacío y la **política real**: ninguna
  de las dos bloquea, así que **no** hizo falta `-ExecutionPolicy Bypass`. `powershell.exe` se
  lanzó **sin** `PSModulePath` (filtro de `shell_profiles.query_environment`, comprobado con un
  `assert` en el guion).

| Edición | Casos | Resultado | Evidencia |
| --- | --- | --- | --- |
| pwsh 7.6 | 23 de REQ-012–015 + control `zzz` | **24/24 OK** | `step4-complete-pwsh.txt` / `.json` |
| Windows PowerShell 5.1 | igual (REQ-013 con `serve --l`, ver REQ-020) | **24/24 OK** | `step4-complete-powershell.txt` / `.json` |

Cada caso imprime `CompletionText` y `ToolTip`. Los tooltips salen en español con tildes en las
dos ediciones (p. ej. `recompute-cost` → «…el relleno de atribución…», `backend-params reset` →
«vacía un rol entero…»), también en 5.1, que lee el script ASCII con `$([char]0xNNNN)`.

- `doctor --home <home-cc>`: `[ OK ] autocompletado del shell: powershell: al día en el idioma es,
  cargado desde …\PowerShell\profile.ps1, …\WindowsPowerShell\profile.ps1`
  (`evidence/live/step4-doctor.txt`). El `doctor` sale con 1 por un único `[WARN]` ajeno al
  autocompletado (credencial del backend en el HOME simulado).
- `uninstall --home <home-cc> --no-client-cli`: salida 0. Los dos perfiles vuelven **byte a byte**
  a lo sembrado (sha256 iguales: `18fa97bf…1186` el de 5.1, `845a18c5…0860` el de pwsh), sin
  copias `*.local-delegate.bak` y sin ficheros en el directorio de completado
  (`evidence/live/step4-summary.json`, `step4-uninstall.txt`).

### Paso 6: limpieza

Borrados el venv `venv-cc`, el HOME `home-cc` y los directorios de trabajo. Los únicos
`pwsh`/`powershell` vivos al acabar eran ajenos (el lanzador del backend
`start-local-delegate-secure.ps1` y la terminal del usuario); ninguno lanzado por esta
verificación.

## Evidencia por requisito

| REQ | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-012 | 7 casos en vivo por edición (13 de primer nivel, `ba`, `backend-params`, `llamaswap`, `test-window`, `BACKEND-PARAMS` no baja, `--version backend-params`) | OK en pwsh y 5.1 | `evidence/live/step4-complete-*.txt`; `tests/test_completion_powershell.py`, `tests/test_completion_posix.py` |
| REQ-013 | `install --mcp`, `serve --` (pwsh) / `serve --l` (5.1), `--clients` repetible | OK | ídem |
| REQ-014 | `--mcp-mode `, `--mcp-mode=h` → `--mcp-mode=http`, `--log-level w`, `--role `, `--reset-calibration `, `--shell-completion ` y `--shell-completion --d` | OK | ídem |
| REQ-015 | `set `, `set code ` (21 claves), `set code top_p ` vacío, `unset vision t`, `reset `, `completion ` | OK | ídem |
| REQ-017 | control `local-delegate zzz` sin candidatos | OK | ídem |
| REQ-037 | guardián con la variable en los tres sistemas; test estático de `ci.yml` | verde | tabla del guardián arriba; `tests/test_completion_ci_shells.py`; controles positivos del ayudante y del guardián con `-n 2` anotados en las PR #362 y #363 |
| REQ-038 | casos (a) sin coincidencias y (b) sin cargar en cada fichero de integración; inversión comprobada a mano | existen y fallan al invertirlos | `tests/test_completion_powershell.py` (fase `unloaded` y `no_match_*`), `tests/test_completion_posix.py`; inversión anotada en las PR #362 («Controles positivos») y #363 («Controles (a) y (b) invertidos … fallan») |
| REQ-039 | fase de autocompletado del E2E en los tres sistemas | verde | logs del paso «Instalador end-to-end» del run 39549628850 |
| REQ-040 | pasos 1 y 2 de la spec con el binario del wheel | OK, con la desviación 1 | `evidence/live/` |

Resto de la matriz §4 del plan, atado a pruebas de `main` (todas en la suite local verde y en el
CI):

| REQ | Pruebas |
| --- | --- |
| 001 | `tests/test_completion_cli.py` |
| 002, 008–010, 042 | `tests/test_completion_render.py`, `tests/test_i18n_override.py` |
| 003–007 | `tests/test_completion_model.py`, `tests/test_cli_backend_params.py` (005); también en `cli-python-matrix` 3.11–3.15 |
| 011–020 | `tests/test_completion_powershell.py`, `tests/test_completion_posix.py`; 016 con readline real en el E2E de Ubuntu |
| 021, 022 | `tests/test_completion_posix.py` (`bash`, `bash3`, `zsh`; los dos últimos en macOS) |
| 023, 029–032, 043 | `tests/test_completion_install.py`, `scripts/check_install_e2e.py` |
| 024–028, 044–046 | `tests/test_shell_profiles.py`, `tests/test_profile_blocks.py`, `tests/test_completion_install.py`, E2E (`.bashrc.bak`) |
| 033, 041 | `tests/test_doctor_completion.py`, `tests/test_wiki.py` |
| 034 | `tests/test_update_completion.py` |
| 035 | guardianes de i18n, nombres y ayuda de la suite |
| 036 | `pyproject.toml` sin dependencias nuevas; job `install-smoke` en verde |

## Comprobaciones de calidad

- [x] Suite del proyecto en verde (4113 pasados, 0 fallidos).
- [x] `ruff check` y `ruff format --check` limpios.
- [x] CI de `main` en verde, 0 alertas de CodeQL; GitGuardian y Socket en `pass` en la PR #365.
- [x] Sin cambios ajenos: la rama solo añade `verification.md` y `evidence/live/`.

## Desviaciones y riesgo residual

1. **El `--dry-run` no enseña la política de una edición que no bloquea.** REQ-040 pide que la
   salida muestre «la política de cada edición»; `install` solo la menciona cuando bloquea
   (`install.completion.policy_blocks`) o no se pudo comprobar (`install.completion.policy_unknown`).
   Con `Bypass` y `RemoteSigned` la salida calla. La política quedó en la evidencia con la misma
   consulta del producto (`query_powershell`), así que la verificación es completa, pero el texto
   de la spec no se cumple al pie de la letra. Para el gate de conformidad: aceptarlo como
   desviación o añadir una línea informativa en `install`.
2. **`PSModulePath` no se quita en el ayudante de pruebas ni en el E2E en Windows.**
   `tests/completion_shells.py:105` y `scripts/check_install_e2e.py:187` hacen
   `env = dict(os.environ); env.pop("PSModulePath", None)`, pero en Windows `os.environ` guarda
   las claves en mayúsculas (`'PSMODULEPATH' in dict(os.environ)` da `True` y `'PSModulePath'`,
   `False`), así que el `pop` no quita nada y `powershell.exe` hereda el `PSModulePath` de pwsh 7.
   El producto está bien: `shell_profiles.query_environment` compara en mayúsculas. Las pruebas
   pasan igual porque lanzan con `-ExecutionPolicy Bypass` y no llaman a `Get-ExecutionPolicy`;
   aquí se vio que, con el `PSModulePath` heredado, `Get-ExecutionPolicy` falla en 5.1 (no carga
   `Microsoft.PowerShell.Security`), y que la primera pasada del guion de L7, con ese mismo
   `pop`, no pudo leer la política de 5.1. En la pasada buena se usó el filtro del producto, y 5.1
   completó con `RemoteSigned` y sin `Bypass`. Arreglo propuesto (fuera del alcance de L7): usar
   `query_environment` o comparar en mayúsculas en esos dos sitios.
3. `doctor --home` sale con 1 por un `[WARN]` de la credencial del backend en el HOME simulado; el
   check del autocompletado está en `ok`.
4. zsh y bash 3 no existen en esta PC: su verificación real es la del CI de macOS (guardián y E2E
   en verde).
5. La verificación en vivo fijó `LOCAL_DELEGATE_LANG=es` para que el idioma no dependiera del
   `language.json` (el HOME simulado no lo lee).

## Paso manual opcional para el usuario (L7, paso 5)

No se hizo porque necesita una consola interactiva. Si quieres ver el Tab y el Ctrl+Espacio de
PSReadLine sin tocar tu perfil real, desde la raíz del repo en `main`, en PowerShell:

```powershell
$tmp = Join-Path $env:TEMP 'ld-cc-manual'
uv build
uv venv "$tmp\venv"
uv pip install --python "$tmp\venv\Scripts\python.exe" (Get-ChildItem dist\*.whl | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
New-Item -ItemType Directory -Force "$tmp\home\.claude" | Out-Null
& "$tmp\venv\Scripts\local-delegate.exe" install --home "$tmp\home" --no-client-cli --shell-completion
pwsh -NoProfile -NoExit -Command ". '$tmp\home\Documents\PowerShell\profile.ps1'"
#   en esa consola: local-delegate backend-params set <Tab>, y <Ctrl+Espacio> para ver la lista con tooltips
#   para 5.1: powershell -NoProfile -NoExit -Command ". '$tmp\home\Documents\WindowsPowerShell\profile.ps1'"
#   al salir (exit), deshacer y borrar:
& "$tmp\venv\Scripts\local-delegate.exe" uninstall --home "$tmp\home" --no-client-cli
Remove-Item -Recurse -Force $tmp
```
