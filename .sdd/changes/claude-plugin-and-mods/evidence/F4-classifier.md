# Evidencia — Clasificador único de lectura (F4-classifier)

Rama `feat/plugin-F4-classifier`, worktree `D:/Projects/ld-wt-F4-classifier`, sobre `main` en
`a528294`. Cubre REQ-019 y la telemetría por vía de REQ-004/REQ-021.

## Qué se hizo

- `resources/hooks/read_classifier.py` (stdlib): reglas portadas de `scripts/measure_read_paths.py`
  (las que etiquetaron el corpus), con el alcance del contrato: `grep`, `awk`, `python`, `git show`,
  `nl`/`jq`…, imágenes, PDF y otros MCP salen `unclassifiable`. Detecta escrituras (`Edit`, `Write`,
  `MultiEdit`, `NotebookEdit`, `>`/`>>`, `tee`, `sed -i`, `Set-Content`/`Add-Content`/`Out-File`,
  `cp`/`mv`/`Copy-Item`/`Move-Item`). Con varias lecturas gana una escritura (guarda de REQ-022);
  entre lecturas, la de mayor alcance.
- `hook_entry.py`: subcomandos `classify`, `classify --list-tools` y `record-read` (fuera de
  `HOOKS`, que sigue siendo el contrato con `hooks.json`); salen siempre con 0.
- Hooks de settings: sin reglas propias (`shlex`, `VERBS`, `BOUNDING_FLAGS` fuera); cada evento lleva
  `via` y `scope`. `record_decision` en cada hook escribe la línea del hook más `decision` y
  `source: "mod"`, y la nota de bloqueo cuando la decisión bloquea.
- `hook_common.version_de`: huella combinada script + clasificador para los dos hooks de lectura.
  `HASHED_HOOKS` intacto; `scripts/data/hook_hashes_after.json` regenerado una sola vez.

## Decisiones del contrato que el plan dejaba abiertas

- `--list-tools`: lista JSON; `mcp__*` es un prefijo.
- `kind: other` → `path`/`bytes`/`range` `null`, `scope: unclassifiable`, `via: none`. Para `write`,
  `scope: unclassifiable`. Una lectura sin fichero resoluble (`cat $F`) → `unclassifiable`, `path: null`.
- `range`: `[primera, última]`, `última` `null` = hasta el final; solo con `scope: range`.
- `record-read`, valores de `decision` (`hook_common.MOD_DECISIONS`), los que manda `mod/read.js`
  (#414): `summarized` y `auto_summarized` cuentan como bloqueo (`blocked: true`,
  `reason: large_prose`); `read_whole` y `dismissed` (`large_prose`, sin bloqueo),
  `summary_failed` (`summary_failed`) y `warned` (`unclassifiable`). Cualquier otra se registra con
  `reason: mod_decision`. `test_record_read_knows_every_mod_decision` lee `read.js` y lo ata.

## Corpus

`test_corpus` usa 662 de las 759 filas: las demás no se pueden reproducir desde el texto anonimizado
(truncado a 40 tokens, `git show rev:ruta` sin los dos puntos, intérpretes con ruta). El filtro es el
propio script de la medición sobre el texto anonimizado; `test_corpus_keeps_most_rows` exige ≥ 550 y
todas las vías cubiertas. Siete filas `read_whole` con `offset`/`limit` se esperan `range` (la
medición lo supo por el resultado).

## Mutantes

1. Quitar `get-content` de las reglas → 33 fallos: `test_corpus[… Get-Content …]` en
   `assert scope in scopes` (`'whole' in []`, `'partial' in []`, `'range' in []`) y
   `test_rules_the_anonymised_corpus_cannot_show[PowerShell-Get-Content notes.md-…]`.
2. `grep -c` como lectura entera → 7 fallos: `test_corpus[… shell_grep …]` en
   `assert 'unclassifiable' in ['whole']` y `test_rules…[Bash-grep -c TODO notes.md-…]`.

## Tests que fallaban antes del cambio

Con el código de hooks y `hook_entry` de `main` (clasificador presente): 13 fallos, cada uno por su
razón — `classify`/`record-read` inexistentes (stdout vacío → `JSONDecodeError`), huella sin cambio
(`'9bbf6aa4' != '9bbf6aa4'`), hook sin `import read_classifier`, y `head X` bloqueado.

## Fuera de la lista «Posee»

`tests/test_hook_entry.py` (la huella esperada del hook de lectura ahora es combinada),
`scripts/data/hook_hashes_after.json` (lo exige `test_hook_boundaries`), `docs/wiki/Configuration.md`,
`docs/recipes/claude-code-hooks.md`, `CHANGELOG.md`, `scripts/data/spanish_lexicon.json` (once palabras
inglesas nuevas) y `tests/data/uncatalogued_exceptions.json` (los nombres de tool del clasificador).

## Pendiente

`scripts/measure_read_paths.py` lleva una copia de las reglas: debería importar el clasificador.

## Suite

`pytest -n 2` completa: 5130 pasan y 2 fallaban por el léxico y el catálogo de textos; arreglados, sus
ficheros y los de hooks, wiki y recetas en verde (832 + 63). `ruff check .` y `ruff format --check .`
limpios.

## Llamadas `local_*`

`local_commit_msg` (borrador del mensaje de commit desde el diff). La lectura del plan, la spec y el
código se hizo por franjas porque hacía falta el texto literal para editar.
