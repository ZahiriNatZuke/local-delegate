# Investigación consolidada — SDD `cli-completion`

Fecha: 2026-10-20. Base: `main` en `465fc97` (0.37.0). Consolida dos investigaciones, que siguen
siendo la fuente con todo el detalle:

- [research-repo.md](research-repo.md): parser, i18n, `install`/`uninstall`/`update`, tests, CI,
  documentación y guardianes del repo.
- [research-shells.md](research-shells.md): PowerShell 7 y 5.1, zsh y bash, con prototipo y
  pruebas en el laboratorio del scratchpad (`completion-lab/gen.py`, `proto.*`, `test-*`).

Más una tercera pasada del redactor de la spec (2026-10-20) sobre el código de escritura de
`install.py` y la tabla de reparaciones de `update.py`, que cambia dos decisiones (ver §4).

## 1. Hechos que fijan el diseño

| Hecho | Evidencia | Consecuencia |
|---|---|---|
| Un único `build_parser()` construye todo el árbol, sin efectos salvo resolver el idioma | `src/local_delegate/cli.py:1334-1521`, `i18n.py:33-36` | El generador puede recorrer el parser real en proceso |
| Arrancar Python cuesta 0,8–2,1 s (importar el paquete arrastra el servidor MCP) | `__init__.py:9`, `entrypoint.py:22`; medido en research-repo §1 y research-shells §1 | Script **estático**; nunca llamar a Python al pulsar Tab ni al abrir el shell |
| Los `help=` pasan por el catálogo y cambian con el idioma | `cli.py:460-1693`, `benchmark.py:1477-1556` | Las descripciones quedan en el idioma de quien genera; hay que regenerar al cambiarlo |
| `backend-params set/unset` tienen `role` y `key` sin `choices` | `cli.py:592-597`; `backend_params.py:33` (`ROLES`), `:77` (`ALLOWED_KEYS`) | Atributo propio en la `Action`; `choices=` cambiaría los rechazos traducidos (`cli.py:480-485`) |
| Ocultos: `recalcular-coste` (sin `help`), `--reiniciar-calibracion` y `benchmark --api-key` (`SUPPRESS`) | `cli.py:1510-1525`, `cli.py:1536-1542`, `benchmark.py:1536`; `deprecations.py:58-59` | Filtro por `SUPPRESS`, por ausencia en `_choices_actions` y por `deprecations.py` |
| Construcciones del parser real: solo `nargs=None`, `"?"` (dos posicionales: `cli.py:469`, `cli.py:600`) y banderas; única corta `-h`; varios `append` | `grep nargs=` en `cli.py`/`benchmark.py`; research-repo §1 | El modelo cubre posicionales en secuencia, `?` y `append`; el resto se rechaza con guardián |
| Dos ejecutables al mismo `main` | `pyproject.toml:74-75` | Registrar `local-delegate` y `local-delegate-mcp` |
| Directorio de datos del producto: `config.LOG_DIR` = `platformdirs.user_data_dir("local-delegate")`, sobreescribible con `LOCAL_DELEGATE_LOG_DIR` | `config.py:203-216` | El fichero generado va en `LOG_DIR/completion/` |
| Con `--home` simulado, `install` no toca el directorio de datos | `install.py:1051-1062` (`language_dir`), `install.py:150-161` | Hace falta una regla para el sandbox (§4) |
| `install` sale con 0 antes de planificar si no hay clientes, y con 2 si no hay componentes | `cli.py:203-212`, `cli.py:225-227` | El autocompletado se planifica aparte, antes de esas salidas |
| Bloques gestionados reutilizables | `install.py:285-299` (`upsert_block`, `managed_block`), `install.py:417-421` (`remove_block`) | Mismo mecanismo de marcadores |
| `doctor` tiene 25 checks y la wiki los cuenta en palabras | `checks.py:2111-2181`, `tests/test_wiki.py:35-48`, `tests/test_wiki.py:243-246`, `docs/wiki/Integration-install.md:182` | Un check nuevo exige fila en la tabla, «veintiséis» en la wiki y la entrada 26 en `_CHECK_COUNT_WORDS` |
| `update` repara por `(componente, cliente)` y salta las reparaciones sin cliente presente | `update.py:288-294` | El refresco del autocompletado no cabe en `REPAIRS` (§4) |
| E2E del instalador en los tres sistemas | `scripts/check_install_e2e.py:80+`, `.github/workflows/ci.yml:177-179` | Sitio de la prueba «instalado en el perfil» |
| Wheel limpio instalado en ubuntu | `ci.yml:267-288` (`install-smoke`) | Sitio barato para probar el **binario instalado** en CI |

## 2. Hechos de los shells (laboratorio)

- **PowerShell**: `Register-ArgumentCompleter -Native` funciona igual en 7.6 y 5.1; los resultados
  se emiten uno a uno; las palabras previas se toman de `CommandElements` con
  `Extent.EndOffset < $cursorPosition`; `--opt=valor` llega como una palabra; sin respuesta del
  completador, PowerShell cae al completado de rutas (research-shells §1, hallazgos 2–5).
- **Codificación de PowerShell**: un script UTF-8 sin BOM se rompe en 5.1 y por
  `Invoke-Expression` en las dos ediciones; **solo ASCII** con `$([char]0x..)` funciona en todos
  los caminos (research-shells §1, hallazgo 8).
- **5.1 no llama al completador con `-` o `--` a secas** (límite del motor; hallazgo 4).
- El mecanismo antiguo `TabExpansion` (pip) ya no funciona en pwsh 7.6 (hallazgo 10).
- Lanzar `powershell.exe` desde pwsh o Git Bash hereda `PSModulePath` y rompe 5.1: quitarlo del
  entorno del subproceso (research-shells §1, «Trampa de laboratorio»).
- Un fichero sin extensión `.ps1` no se ejecuta con dot-source.
- **zsh 5.9** (contenedor): `#compdef` + `_describe` + `compadd` + `compset -P '*='` + `_files`, con
  el patrón `loadautofunc`/`compdef` de click, vale para `source` y para `fpath`; sin `compinit`
  falla (research-shells §2).
- **bash 3.2 y 5.3**: sin `declare -A`, `compopt`, `mapfile`; `=` es palabra aparte en
  `COMP_WORDS`; el prototipo con `case` y `compgen -W` da lo mismo en las dos (research-shells §3).
- Los runners: macOS trae zsh y `/bin/bash` 3.2; Windows trae pwsh, 5.1 y Git Bash; ubuntu trae
  bash y pwsh, no zsh (a confirmar en el primer run). En esta PC no hay zsh, y el `bash` de
  PowerShell es WSL.
- Coste por Tab de 1–5 ms; carga del fichero por dot-source, 7–19 ms; por `Invoke-Expression`
  desde el binario, 0,8–2,1 s.

## 3. Decisiones (de la sesión principal, confirmadas por la investigación)

1. `local-delegate completion {powershell,zsh,bash}` imprime un script estático por stdout.
2. Generador sin dependencias en `src/local_delegate/completion.py`; plantillas como recursos en
   `src/local_delegate/resources/completion/`; excluye lo oculto; registra los dos ejecutables.
3. Valores fijos: `choices` + atributo propio `completion_values` en las acciones de
   `backend-params`; ids dinámicos fuera.
4. Construcciones no soportadas y valores inseguros: error claro del generador más guardián sobre
   el parser real.
5. Descripciones en el idioma de la CLI; PowerShell solo ASCII y compatible con 5.1; bash 3.2;
   zsh con `#compdef` y guarda de `compinit`.
6. `install --shell-completion [auto|powershell|zsh|bash]`, opt-in, fichero aparte en el
   directorio de datos y bloque gestionado ASCII que solo lo carga.
7. `uninstall` siempre lo quita; `update` regenera; `doctor` lo diagnostica.
8. `AllSigned`/`Restricted` y el límite de 5.1 con `--`: solo documentación.
9. Pruebas con shells reales más guardián de que no se saltan en CI; E2E en los tres sistemas.
10. Verificación final con el binario instalado; release fuera.

## 4. Lo que la tercera pasada añade o corrige

- **`_read_text`/`_write_text` no sirven tal cual para un perfil de shell**
  (`install.py:254-266`): `_read_text` devuelve `""` si el fichero no es UTF-8, así que un perfil
  de Windows PowerShell 5.1 guardado en ANSI con tildes se leería vacío y `upsert_block` lo
  **reemplazaría entero** por el bloque. Además `remove_block` hace `strip()` del fichero
  (`install.py:420-421`) y `upsert_block` hace `rstrip()` (`install.py:291`): el perfil no volvería
  byte a byte a como estaba. Hacen falta dos ayudantes nuevos que preserven codificación y bytes
  (desviación 1 de la spec).
- **Ruta del perfil de PowerShell preguntada al shell**: la salida de un proceso PowerShell se
  decodifica con la página de códigos de la consola (research-shells §1, hallazgo 8), así que una
  ruta con tildes llegaría rota. Se pide la ruta codificada en Base64 de UTF-16 (texto ASCII).
- **`update` no puede reparar por `REPAIRS`** (`update.py:292-294` exige un cliente presente): va
  como paso propio, igual que `plan_catalog_refresh` (`update.py:326-330`).
- **Sandbox `--home`**: el directorio de datos no se toca (`install.py:1051-1062`); el fichero
  generado va dentro del HOME simulado.
- **El check compara el contenido entero**, no solo la versión de la cabecera: así también detecta
  un cambio de idioma.

## 5. Descartado

| Opción | Motivo |
|---|---|
| `argcomplete` | Dependencia nueva, PowerShell flojo, arranca Python en cada Tab (brief) |
| `shtab` | Dependencia nueva, sin PowerShell (brief) |
| Completado dinámico (pip, click, cobra/gh) | 0,8–2,1 s por Tab (research-repo §1) |
| `local-delegate completion … \| Invoke-Expression` en el perfil | 0,8–2,1 s por shell; solo como alternativa documentada |
| Script entero dentro del perfil | Perfil grande y regenerarlo reescribe un fichero del usuario en cada `update` |
| `TabExpansion` (mecanismo antiguo) | No funciona en pwsh 7.6 (research-shells §1, hallazgo 10) |
| `_arguments` de zsh (lo que usa clap/uv) | Mucho más difícil de generar bien; `_describe` + recorrido propio iguala a los otros shells |
| `choices=` en `backend-params` | Cambia los rechazos traducidos (`cli.py:480-485`) |
| Lista separada por comas en `--shell-completion` | El repo ya usa `append` repetible (`--clients`, `--target`) |
| `fpath` antes de `compinit` como carga por defecto en zsh | El bloque se añade al final de `.zshrc`, después del `compinit` del usuario; `source` funciona en ese orden |
