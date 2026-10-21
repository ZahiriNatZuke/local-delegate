# Brief — SDD ligero `backlog-minor-leftovers`

## Objetivo

Cerrar los restos menores que dejaron tres SDD ya cerrados (backlog del vault
`projects/local-delegate/backlog.md`, §1.13, §1.14 y §1.15). Ninguno incumple una spec; son
pulido, tests que faltaban y tres decisiones de producto que el usuario tomó el 2026-10-21:

- El panel **sigue el tema del sistema** (`prefers-color-scheme`) mientras el usuario no haya
  elegido con el botón; su elección guardada manda.
- `doctor` **avisa (WARN)** si un `settings.json` no es UTF-8 aunque sea JSON válido.
- `doctor` **avisa (WARN)** de que existe `~/.claude/settings.json.retired-names.bak` (puede llevar
  claves del `env`) y sugiere borrarla; el aviso desaparece al borrarla.

Ya resuelto por la sesión principal (fuera del repo): `lanzar-tanda-afinidad.ps1:30` usaba
`LOCAL_DELEGATE_COMMIT_IDIOMA`; ahora `LOCAL_DELEGATE_COMMIT_LANGUAGE` (§1.15.2).

Sin acción en este SDD, a propósito: §1.15.3 (cubrir `settings.local.json`, `~/.claude.json` y el
lanzador solo si aparece un caso real) y §1.15.5 (retirar los 7 nombres en la 0.41.0; lo pedirá el
test de horizonte).

## Reglas comunes a todos los lotes

- **Primer paso**: carga las tools de `local-delegate` (son diferidas):
  `ToolSearch("select:mcp__local-delegate__local_summarize,mcp__local-delegate__local_extract,mcp__local-delegate__local_lint_summary,mcp__local-delegate__local_boilerplate,mcp__local-delegate__local_commit_msg,mcp__local-delegate__local_explain_code")`.
  Antes de empezar, decide qué pasos te conviene pasarles (ficheros grandes con `path`, salida de
  tests volcada a fichero → `local_lint_summary(path=…)`, borrador de commit con
  `local_commit_msg`). En la entrega, lista las llamadas `local_*` hechas («0» exige motivo). Si
  una devuelve `[local-delegate error]`, hazlo tú y sigue.
- **Worktree propio** en ruta corta `D:/Projects/ld-wt-<lote>` (en el scratchpad falla por ruta
  larga), rama desde `origin/main`. No trabajes en el checkout principal `D:/Projects/local-delegate`.
- **Comandos pesados de uno en uno en toda la máquina**: suite, `uv sync`, navegador headless, con
  `bash ~/.claude/scripts/pesado.sh <comando>` **desde la tool Bash** (el `bash` de PowerShell es
  WSL). pytest con `-n 2`. Ejemplo: `bash ~/.claude/scripts/pesado.sh uv run pytest -n 2 -q > /ruta/salida.txt 2>&1`.
- **Todo el código y los comentarios en inglés**; los textos que ve el usuario, por el catálogo i18n
  en es **y** en (`src/local_delegate/resources/i18n/{es,en}/*.json`).
- **Fin de línea**: el repo mezcla LF y CRLF fichero a fichero. Comprueba con `git ls-files --eol`
  antes y después de editar y conserva el de cada fichero (`write_text` de Python convierte sin
  avisar; el heredoc de Bash colapsa barras invertidas).
- `CHANGELOG.md`: solo una línea en `[Unreleased]` (sección que toque). Hay otros lotes en paralelo:
  si chocáis, rebasa y junta. No toques `README.md`; `docs/wiki/` solo si tu lote lo pide.
- **Commits firmados SIN coautoría de Claude** (sin línea `Co-Authored-By`). Mensajes en español,
  estilo del repo: `fix(área): … (SDD backlog-minor-leftovers, <lote>)`.
- PR en español contra `main`. Antes de dar el lote por cerrado: `gh pr checks <n>` todo verde
  (no basta `gh run list`: code scanning, Socket y GitGuardian solo salen ahí) y CodeQL del PR a 0
  incluido `note`: `gh api "repos/{owner}/{repo}/code-scanning/alerts?ref=refs/pull/<n>/merge&state=open"`.
  Las alertas se **arreglan**, no se descartan. Esperas de CI con tope (40 min), nunca un bucle sin
  salida. **No mezcles el PR**: lo mezcla la sesión principal.
- No toques el daemon, `~/.claude` ni el `uv tool` instalado. Nada de secretos ni datos reales en
  tests, capturas o evidencias.
- **Nada huérfano**: al acabar, para servidores, navegadores y esperas que hayas lanzado, y
  confírmalo en la entrega.

## Entrega (cada lote)

`.sdd/changes/backlog-minor-leftovers/evidence/<lote>.md` en su worktree (se sube en su PR), y un
resumen en español en la respuesta: qué cambió por punto del backlog, tests añadidos y prueba de que
fallaban antes por el assert correcto, suite y ruff, número de PR y estado de `gh pr checks` y
CodeQL, llamadas `local_*`, y confirmación de que no deja procesos.
