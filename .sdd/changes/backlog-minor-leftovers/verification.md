# Verificación: restos menores de backend-params, cli-completion y retire-legacy-aliases

## Entorno

- Revisión: `64ee382` (`main` tras #383, #385, #384, #386 y #387).
- Python del CI 3.11–3.15 en ubuntu, windows y macos; local Windows 11, `uv run`, pytest `-n 2` con
  `pesado.sh`. Medición L5: `qwen36-35b-a3b`, llama.cpp b10909, llama-swap v255, daemon 0.38.0.

## Evidencia

| REQ | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | Test del diálogo con `enable_thinking` true/false (fallaba en `main` con `= true`) + captura | OK | PR #385, `evidence/L3.md`, `dialog-param-on.png`, `dialog-param-off.png` |
| REQ-002 | `pickTheme` con node (9 casos), Playwright con `emulate_media` (sin elección sigue al sistema; con elección manda ella), mutante del oyente | OK | PR #385, `evidence/L3.md`, capturas `theme-*.png` |
| REQ-003 | Test que reescribe el fichero a mitad de una operación troceada; mutante «resolver por llamada» lo tumba por el assert de parámetros y el test previo no lo veía | OK | PR #383, `evidence/L4.md` |
| REQ-004 | Medición en vivo 256–4096 + sin razonamiento, 3 repeticiones, criterio escrito antes; mínimo 4096; `backend-params` restaurado (mismo sha256); ventanas `w-20261021T180542Z` y `w-20261021T184025Z` cerradas | OK | PR #387, `evidence/L5.md`, `docs/wiki/Configuration.md` |
| REQ-005 | `install`+`uninstall` con HOME simulado deja HOME vacío; mutantes (`rmtree`, apuntar carpetas preexistentes) detectados | OK | PR #386, `evidence/L1.md` |
| REQ-006 | Fixture vigila `.bashrc`, `.bash_profile`, `.zshrc` (y `$ZDOTDIR`) | OK | PR #386 |
| REQ-007 | «supuesta» en la línea de política con HOME simulado, es/en | OK | PR #386 |
| REQ-008 | Última línea del `--dry-run` de solo autocompletado = línea de dry-run | OK | PR #386 |
| REQ-009 | Comentarios del SDD `cli-completion` en inglés en los 4 módulos | OK | PR #386 |
| REQ-010 | Manifiesto con `lang` desconocido → ilegible | OK | PR #386 |
| REQ-011 | Test compara cwd, datos, HOME y temp; mutante que escribe en HOME/temp lo tumba | OK | PR #386 |
| REQ-012 | WARN con ruta, byte y posición para `settings.json` no UTF-8; BOM válido; 12 tests + 4 mutantes | OK | PR #384, `evidence/L2.md` |
| REQ-013 | WARN por `settings.json.retired-names*.bak` sin abrirla; sin copia, nada; wiki y contadores a 27 | OK | PR #384 |

## Controles de calidad

- [x] Suite completa por lote (4153–4166 passed, 28 skipped); fallos solo del detector de nombres,
  corregidos en cada lote; CI verde en los 5 PR.
- [x] `ruff check` y `ruff format --check` limpios; fin de línea conservado (`git ls-files --eol`).
- [x] GitGuardian (hook `ggshield` y check del PR) verde; CodeQL a 0 en los 5 PR (dos `note`
  `py/empty-except` arregladas, no descartadas).
- [x] Sin cambios ajenos; `CHANGELOG.md` combinado a mano en dos rebases.

## Desviaciones y riesgo residual

- §1.15.2 se arregló fuera del repo (`lanzar-tanda-afinidad.ps1`, no versionado).
- L1: durante un mutante, un test viejo escribió `leak.txt` en el HOME real y en el temporal; se
  borraron al momento (comprobado) y el test nuevo lo detectaría.
- L5: 1024 salió peor que 256/512; con 3 repeticiones puede ser ruido. El aviso de `set` por debajo
  del mínimo no se implementa (el criterio no lo justificó).
