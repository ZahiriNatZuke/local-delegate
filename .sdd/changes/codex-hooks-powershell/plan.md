# Implementation plan: Codex en Windows: hooks que arrancan en PowerShell, cmd y bash (#718)

## Approach

`codex_hooks.command()` en `win32`: ruta con `/`; si cumple el conjunto seguro, sin comillas; si
no, se intenta la ruta corta 8.3 con `ctypes` (`GetShortPathNameW`, en un helper que se puede
sustituir en los tests); si tampoco, `& "<ruta>"`. `_OURS` acepta un `& ` opcional delante de un
intérprete entre comillas. `doctor` (`_probe_codex_hooks`) añade un aviso propio cuando una línea
nuestra empieza por comilla; como la línea nueva es distinta, el grupo ya sale como «no es de esta
versión», y el aviso dice por qué.

## Ordered tasks

- [ ] T1 — Tests rojos: forma de la línea, arranque real en pwsh/powershell/cmd/bash con un intérprete falso, ruta con espacios, reconocimiento y aviso de `doctor` (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005)
  - Files or modules: tests/test_codex_hooks.py, tests/test_codex_hooks_shells.py, tests/test_codex_hooks_doctor.py
  - Verification: fallan sobre `main`
  - Depends on: none
- [ ] T2 — `command()`, ruta corta y `_OURS` (REQ-001, REQ-002, REQ-003, REQ-005)
  - Files or modules: src/local_delegate/codex_hooks.py
  - Verification: tests de T1
  - Depends on: T1
- [ ] T3 — Aviso de `doctor` y textos es/en (REQ-004)
  - Files or modules: src/local_delegate/checks.py, resources/i18n/{es,en}/doctor.json
  - Verification: tests/test_codex_hooks_doctor.py
  - Depends on: T1
- [ ] T4 — CHANGELOG «Sin publicar», suite completa y prueba real con Codex en un `CODEX_HOME` temporal (REQ-001)
  - Files or modules: CHANGELOG.md
  - Verification: suite con `pesado.sh`; `codex exec` deja `codex-hooks-seen.json`
  - Depends on: T2, T3

## Test strategy

- Unit: forma de la línea por plataforma; `our_name`/`python_of` con las cuatro formas.
- Integration: la línea generada lanzada como la lanza Codex (`derive_exec_args`) en cada shell
  disponible, con el marcador `shell(...)` para el guardián de shells exigidas en el CI de Windows.
- End-to-end or manual: `codex exec` contra un `CODEX_HOME` temporal dentro de `test-window`.
- Security and secret scanning: sin secretos; el diff no toca ficheros de credenciales.

## Migration and compatibility

- Las líneas viejas se reconocen y se reescriben en su sitio; el usuario reaprueba en `/hooks`.
- Linux y macOS sin cambios.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
