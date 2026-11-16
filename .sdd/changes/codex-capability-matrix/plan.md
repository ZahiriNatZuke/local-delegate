# Implementation plan: Codex: matriz de capacidades y alternativas para barra, comandos sin modelo y tools fijadas (#671)

## Approach

`omit_tools_from` se trata igual que los plazos: texto TOML conservado de la tabla anterior y
añadido al final del bloque. La regex captura la lista entera hasta `]` (también repartida en
varias líneas, con espacios o comentario), nunca la corta en el primer espacio como la de los
plazos. Una opción de tres estados decide: añadir `"deferred"`, quitar solo `"deferred"` o
conservar; los cambios se hacen sobre la lista leída con `tomllib`. Como la tabla se reescribe
entera, sale una sola clave. `doctor` lo lee de la sección (también en la rama de entrada a mano,
porque se añade a `kind`). La matriz vive en una página propia de la wiki para no pisar la sección
de hooks de Codex que toca #670. Este PR lo integra la sesión principal en serie con #669/#670: el
CHANGELOG y `docs/wiki/` se rebasan al mezclar.

## Ordered tasks

- [x] T1 — `install.py`: `_CODEX_EXPOSURE_RE` (lista entera), `codex_exposure_in`, `codex_tools_direct`, `codex_exposure` (tres estados), `Options.codex_direct_tools = None` por defecto (lo que usa `update.repair_install_options`), detalle del plan (REQ-002)
  - Files or modules: `src/local_delegate/install.py`
  - Verification: tests T4
  - Depends on: none
- [x] T2 — `cli.py`: `--codex-direct-tools` / `--no-codex-direct-tools`, paso a `Options` y aviso cuando el flag no puede tener efecto (REQ-002)
  - Files or modules: `src/local_delegate/cli.py`, i18n `cli.json`
  - Verification: tests T4
  - Depends on: T1
- [x] T3 — `checks.py`: detalle «tools directas» en `_probe_mcp_codex`, añadido a `kind` (REQ-003)
  - Files or modules: `src/local_delegate/checks.py`, i18n `doctor.json`, `install.json`
  - Verification: tests T4
  - Depends on: T1
- [x] T4 — tests con control que falla sin el cambio: flag, sin flag, lista a mano con otros valores, una línea con espacios y comentario, varias líneas, `--no` que quita solo `deferred`, lista vacía, aviso, `update` (pin y reparación), `doctor`, textos es/en (REQ-002, REQ-003, REQ-007)
  - Files or modules: `tests/test_codex_direct_tools.py`
  - Verification: pytest -n 1 del fichero y vecinos (`test_install*.py`, `test_checks.py`, `test_doctor*.py`, `test_update*.py`, `test_i18n_parity.py`); control contra `src` de `main`
  - Depends on: T1-T3
- [x] T5 — prueba con Codex real sobre la tabla que arma el instalador, en `CODEX_HOME` temporal (REQ-004)
  - Files or modules: ninguno (evidencia en verification.md)
  - Verification: `codex debug prompt-input -c mcp_servers.local-delegate.required=true`
  - Depends on: T1, T2
- [x] T6 — wiki `Codex-capabilities.md`, enlaces en README y `Home.md`, opción en `Integration-install.md`, CHANGELOG (REQ-001, REQ-005, REQ-006)
  - Files or modules: `docs/wiki/`, `README.md`, `CHANGELOG.md`
  - Verification: review
  - Depends on: T5

## Test strategy

- Unit: `codex_exposure` a través de `install` en los tres estados y con lista previa.
- Integration: `cli.run(["install", ...])` sobre HOME simulado (patrón de `test_install_timeouts.py`), `tomllib` valida la tabla; `update.run_update` y `update.plan_repairs`; `doctor` con la clave.
- End-to-end or manual: `codex debug prompt-input` con `CODEX_HOME` temporal; prueba en vivo del usuario en su Codex (wiki).
- Security and secret scanning: sin secretos; `personal-security-check` antes del commit.

## Migration and compatibility

- Sin flag no cambia nada para nadie. Se revierte con `--no-codex-direct-tools`.
- CRLF en `install.py`, `cli.py`, `README.md`, `Integration-install.md`; LF en el resto.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
