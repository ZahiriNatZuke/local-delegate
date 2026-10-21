# Brief común — SDD `retire-legacy-aliases`

Reglas que aplican a TODOS los agentes de este cambio. Léelo entero antes de empezar; no hace falta
leer el `CLAUDE.md` global ni todo `MEMORY.md`.

## Objetivo

Preparar la **0.38.0**. En el SDD `english-names-bilingual-output` (cerrado, `.sdd/changes/english-names-bilingual-output/`)
se acordó que los nombres viejos en español renombrados en la 0.35.0 viven con aviso en la 0.35.x,
0.36.x y 0.37.x y **se retiran en la 0.38.0** (REQ-001, REQ-002, REQ-003, REQ-004, REQ-012 de esa
spec). Además, la doble escritura de `enfriamiento.json` también se retira en la 0.38.0, y las tres
variables del rol `fast` (`kind="retired"`, `warn_until="0.37.0"`) dejan de avisarse.

El guardián `tests/test_deprecations.py::test_horizon_no_deprecated_name_is_overdue_in_the_current_version`
se pone en rojo en cuanto `pyproject.toml` diga 0.38.0. Este SDD hace que pase **retirando de verdad**
lo vencido, no tocando el guardián.

Después de este SDD se publica la 0.38.0, que llevará también el autocompletado de la CLI
(SDD `cli-completion`, ya en `main`, `CHANGELOG.md` sección `[Unreleased]`).

Punto de partida:

- `src/local_delegate/deprecations.py` (registro `DEPRECATED_NAMES`, reglas de las dos clases).
- `src/local_delegate/deprecation_notices.py`, `legacy_names.py`, `cooldown.py`, `config.py`,
  `cli.py`, `checks.py` (check `config.deprecated_names`), `completion.py`,
  `resources/hooks/hook_common.py` (copia mínima para los hooks, atada por un test de igualdad).
- `scripts/data/name_exceptions.json` (excepciones del detector de nombres en español).
- Tests: `tests/test_deprecations.py`, `tests/test_cli_renamed_names.py`, `tests/test_checks.py`
  (~línea 1955) y los que salgan.
- Docs: `README.md:122`, `docs/wiki/Configuration.md:125` y `:591`, `CHANGELOG.md` (~420–432,
  sección «Plazos» de la 0.35.0).

## Reglas obligatorias

- **Usa el MCP `local-delegate`** (autorizado de nuevo por el usuario el 2026-10-21). Primer paso:
  `ToolSearch("select:mcp__local-delegate__local_summarize,mcp__local-delegate__local_extract,mcp__local-delegate__local_lint_summary,mcp__local-delegate__local_boilerplate,mcp__local-delegate__local_commit_msg,mcp__local-delegate__local_explain_code")`.
  Antes de empezar, decide qué pasos te conviene pasar por ellas para ahorrar contexto (resumir
  ficheros grandes con `path`, salida de tests/lint volcada a fichero con `local_lint_summary`,
  extraer campos, explicar código, borrador de commit) y lista en la entrega las llamadas `local_*`
  hechas (si fueron 0, di por qué). Si una devuelve `[local-delegate error]`, hazlo tú y sigue.
- **Todo el código en inglés**; solo los textos de salida al usuario van por el catálogo i18n
  (es/en) (`src/local_delegate/i18n.py`; hay un guardián de textos fuera del catálogo).
- **Sin dependencias nuevas.**
- **Comandos pesados de uno en uno en la máquina**, desde la tool **Bash** (no PowerShell: ahí
  `bash` es WSL): `bash ~/.claude/scripts/pesado.sh <comando>`. Pesado = pytest de la suite, builds,
  `uv sync`, installs. pytest con `-n 2` como máximo. Un fichero de tests suelto que tarda segundos
  puede ir sin cerrojo.
- El repo **mezcla LF y CRLF fichero a fichero**: respeta el fin de línea de cada fichero
  (`git ls-files --eol <fichero>`); `Path.write_text` convierte sin avisar; `sed -i` pasa CRLF a LF.
- **Commits firmados**, sin línea de coautoría de Claude. Rama propia, PR contra `main`; `main`
  exige CI verde, firma y **CodeQL a 0 alertas, también las de severidad `note`**
  (`py/cyclic-import`, `py/unused-import`…), con los hilos resueltos. Verifica con
  `gh pr checks <n>` y con
  `gh api "repos/ZahiriNatZuke/local-delegate/code-scanning/alerts?ref=refs/pull/<n>/merge&state=open"`.
- **No toques** el daemon, la tarea programada, `~/.claude*`, `~/.codex`, las variables de entorno
  del usuario ni su perfil del shell. Mirar en modo lectura está permitido; **nunca imprimas el valor
  de un token o una clave**, solo nombres.
- **Nada huérfano**: al terminar, ni shells, ni servidores, ni esperas en bucle vivas. Toda espera
  con tope de tiempo. Confírmalo en la entrega.
- Si algo que descubres invalida la spec o el plan, **para y repórtalo**; no improvises alcance.

## Entregables

Cada encargo dice su ruta. Todo en español, con `fichero:línea` como evidencia.
