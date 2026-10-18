# Verification: Renombrado a inglés de lo publicado y salidas en español e inglés

## Environment

- Revision (0.36.0): rama `release/0.36.0` desde `main` en `c61206d` (frente A cerrado, B0–B5,
  B2a–B2f y B2-affinity), versión subida a 0.36.0 con `scripts/bump_version.py 0.36.0
  --boundaries`. La pasada en vivo corrió con el daemon sobre esa rama, ya como 0.36.0.
- Revision (0.35.0): rama `release/0.35.0` desde `main` en `5723ac9` (A0–A6 + arreglo #263), versión
  subida a 0.35.0 con `scripts/bump_version.py`.
- Relevant runtime and tool versions: Python 3.11.15, uv 0.10.12, Windows 11. La pasada en vivo
  corrió con el daemon sobre el código de `main` en `2bca590` (se identificaba como 0.34.0).

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-017 | Suite completa en la rama de release; pasada en vivo de las 11 tools por MCP dentro de la ventana `w-20261013T123443Z` (0.35.0 candidata) | Suite: 2565 passed, 2 skipped. Tools: 11 de 11 responden; sin regresiones de idioma en lo que lee el usuario | `evidence/live-035/tools.md` |
| REQ-038 | `install`, `doctor`, `update`, panel (claro y oscuro), comando de P-4 y avisos de alias en vivo, dentro de la ventana de prueba `w-20261013T123443Z` (abierta 2026-10-13T12:34:43Z, cerrada 13:03:12Z con `local-delegate test-window stop`) | OK; ver observaciones del propio fichero | `evidence/live-035/install-doctor-panel.md`, `evidence/live-035/panel-*.png` |
| REQ-017 (0.36.0) | Pasada en vivo de las 11 tools por MCP con la 0.36.0 candidata, en `en` (ventana `w-20261018T132615Z`) y en `es` (ventana `w-20261018T134632Z`), cambiando `language.json` con `install` | 11 de 11 sin error en los dos idiomas; salida al usuario en su idioma | `evidence/live-036/tools.md`, `evidence/live-036/answers/` |
| REQ-028 | Muestra D10: juez «solo prosa» sobre `local_status`, `local_summarize`, `local_lint_summary`, `local_commit_msg`, `local_explain_code` y `local_describe_image` en los dos idiomas | 12 de 12 en el idioma pedido | `evidence/live-036/answers/*/judge.jsonl`, `tools.md` |
| REQ-019, REQ-047 | `doctor` y `local_status` en vivo tras `install` con `LOCAL_DELEGATE_LANG=en` y `=es` | Mismo idioma, origen «preferencia» y ruta de `language.json` en los dos; el remedio D11 en su idioma | `evidence/live-036/install-doctor-panel.md` §3, `doctor-en.txt`, `doctor-es.txt` |
| REQ-012, REQ-047 | `install --mcp-mode http --web-token-env --enable-read-hook --agents` real, en `en` y luego en `es` | rc=0; skill, bloque y catálogo en el idioma; un solo bloque; `settings.json` igual en contenido; bloqueo de lectura encendido; entrada MCP de Claude Code autentica (200) | `install-doctor-panel.md` §2, `install-en.txt`, `install-es.txt` |
| REQ-024 | Hooks instalados en el `~/.claude` real, ejecutados tal cual en sh y PowerShell con `language.json` en `en` y en `es` | rc=0, ASCII, en su idioma; `deny` del bloqueo de lectura activo | `install-doctor-panel.md` §4, `hooks-en.txt`, `hooks-es.txt` |
| REQ-020, REQ-025 | Panel del daemon instalado con Playwright, contextos `es-ES` y `en-US`, claro y oscuro; cambio del selector y recarga | Idioma, selector y persistencia correctos; «Procesos del backend» solo con el `llama-swap` del backend | `install-doctor-panel.md` §5, `panel-live.json`, `panel-*.png` |
| REQ-016 | `detect_spanish_names.py --exceptions rename-exceptions.md --json evidence/close/detector.json` al cerrar el cambio | 0 fuera de la lista (había 23 nuevos de B2d-3 a B5: falsos positivos del léxico y numerales de `score_lint_fidelity.py`, apartados con motivo; la sección «Texto de salida que traduce el frente B» queda vacía); guardián nuevo en la suite | `evidence/close/detector.json`, `detector.txt`; `tests/test_detect_spanish_names.py` |
| REQ-045 | `tests/data/uncatalogued_pending/` al cerrar B | No existe ningún fichero de pendientes; el guardián pasa | log de la suite |
| REQ-040 | Diff de CHANGELOG (`[0.36.0]` con qué hace, cómo se elige el idioma, lo que rompe y la tabla del contrato), README (aviso de la 0.36.0) y wiki | En la rama de release | PR de release 0.36.0 |
| REQ-035 | Orden de mezcla en `main` (`git log --first-parent 8ec2f1d..main`) | A0 #247, A1 #249, A2 #250, A3 #251, A4 #252, A5a #253, A5b #259, A5c #261, (#248, ajeno al cambio), A6 #262, arreglo #263 | esta tabla |
| REQ-004 | `bump_version.py 0.35.0` cambió los 8 `UNRELEASED` de `deprecations.py` por `0.35.0`; `removal_version` deriva 0.38.0 en todos; `tests/test_deprecations.py` comprueba que `[0.35.0]` del CHANGELOG nombra cada `old` y `new` | OK | log de la suite de la rama de release |

Ventanas de prueba de este cambio: `w-20261013T123443Z` (0.35.0 candidata),
`w-20261018T132615Z` (0.36.0 candidata, en) y `w-20261018T134632Z` (0.36.0 candidata, es); todas
cerradas.

## Quality checks

Estado en la rama de release de la 0.36.0 (2026-10-18; el gate `quality` espera al CI del PR):

- [x] Project-native tests pass: 3196 passed, 2 skipped con `LOCAL_DELEGATE_LANG=es` y con `=en`
  (`pytest -q -n 2 --dist loadgroup` bajo `pesado.sh`): `evidence/live-036/suite-es.txt`,
  `suite-en.txt`.
- [x] `ruff check` y `ruff format --check` limpios; `bump_version.py --check` OK;
  `build_corpus.py --check` y `build_corpus.py affinity --check` OK
  (`evidence/live-036/corpus-*.txt`, comprobaciones de ficheros congelados, sin modelos).
- [x] Detector de nombres (REQ-016) a 0 fuera de la lista; sin pendientes del guardián (REQ-045).
- [ ] Secret scanning passes (lo da GitGuardian en el PR de release).
- [x] No unrelated changes are present.

`scripts/release.py 0.36.0 --dry-run` se para en la comprobación de rama (exige `main`), como en
la 0.35.0; las notas del CHANGELOG se extraen bien (224 líneas).

Estado en la rama de release de la 0.35.0 (no cierra el gate `quality`, que espera a la 0.36.0):

- [x] Project-native tests pass (2565 passed, 2 skipped).
- [x] Lint, formatting, type checking, and build checks pass where applicable (`ruff check`,
  `ruff format --check`, `bump_version.py --check`).
- [ ] Secret scanning passes (lo da GitGuardian en el PR de release).
- [x] No unrelated changes are present.

## Deviations and residual risk

- `scripts/release.py 0.35.0 --dry-run` no pasa de la comprobación de rama en `release/0.35.0`
  (exige `main`): se ejecuta tras mezclar. La extracción de notas del CHANGELOG sí se comprobó
  (212 líneas).
- El plan pedía anunciar que «`doctor --json` cambia sus ids»; `doctor` no tiene `--json`. El
  CHANGELOG dice que cambian los ids y grupos de los checks, que solo se ven en `checks.CHECKS` y
  la wiki.
- **Limitación conocida de REQ-016 (cierre del frente A, decisión 5):** el detector solo cuenta como
  valor de máquina una cadena con separador (`_`, `-`, `.`); no ve los valores de **una sola
  palabra**. No se amplió (metería cientos de rótulos y prosa). En su lugar, el barrido
  complementario por AST de `src/` y `scripts/` queda como evidencia del cierre, clasificado línea
  a línea: `evidence/A-close-4/singleword-src.tsv` (254) y `singleword-scripts.tsv` (191), con la
  leyenda en `singleword-classes.tsv`. Lo que no es texto de salida, formato viejo, dato
  congelado, contenido de caso o entrada de una persona son 21 valores internos de `scripts/`
  (`valor-interno`), traídos como pregunta abierta en `waves/A-close.md`, sección «A-close-4».
