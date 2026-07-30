# Handoff: Registro unico de comprobaciones del andamiaje y doctor que ve el sistema entero

## Current state

- SDD status: `closing` (pendiente solo el merge del PR y el registro en memoria).
- Last completed gate: `conformance` (aprobado; `conforms-with-notes`).
- Current revision: rama `feat/checks-andamiaje` sobre `main` en `6a1dabc`.

## What changed

- Nace `src/local_delegate/checks.py`: las **once** comprobaciones del andamiaje en una tupla
  estática, cada una con un `probe(ctx)` que **no escribe**, cuatro estados y un `fix_hint` de
  texto. No hay registro dinámico, ni entry points, ni herencia.
- `doctor.py` pasa a **consumir** el registro: imprime los once agrupados con los prefijos de
  siempre más `[FALT]`, conserva `--config`, `--online`, la comparación con
  `RECOMMENDED_VERSIONS` y los issues de GitHub, y gana `--home DIR`.
- Tests: `tests/test_checks.py` nuevo y `tests/test_doctor.py` ampliado; el HOME simulado vive en
  `tests/conftest.py` (`make_home` / `snapshot`) y lo arman las funciones del propio `install`.
- Docs: sección nueva en `docs/wiki/Integration-install.md` con las dos tablas (qué mira cada
  check, qué significa cada estado) y entrada en `Unreleased` del CHANGELOG.
- `install.py` **no se tocó**.

## Decisions

- **`unknown` nunca es `missing`.** Cliente ausente, permisos o JSON ilegible dan `unknown` y no
  cuentan para el exit code. Es lo que impide que B y C sobrescriban configuración ajena, y con
  un HOME totalmente vacío eso significa once `[ -- ]` — la regla (REQ-003) manda sobre el
  ejemplo del escenario de la spec.
- **`_compare_line` y los issues se envuelven, no se reescriben**: el probe de versiones le quita
  el prefijo a la línea que ya armaba `doctor` y deja que el renderizador lo ponga. Por eso
  `--online` sigue mostrando el sufijo de GitHub y la compuerta de soak sin duplicar lógica.
- **Nada de caracteres fuera de cp1252 en la salida.** Una flecha `→` en el `fix_hint` mataba el
  diagnóstico en la consola de Windows justo cuando algo estaba mal.
- **Los hooks de una instalación anterior (`args` + scripts en otra ruta) son `warn`, no `ok`** —
  pero **sí se ejecutan**: `args` es el *exec form* del schema de Claude Code. El primer intento
  decía que estaban muertos, copiando un comentario de `install.py` que era falso; se corrigieron
  los dos. Si vuelve a aparecer esa afirmación en el repo, es un error conocido.
- **El backend caído cuenta como aviso** (exit 1), donde antes no; lo pide el escenario de
  aceptación y queda en el CHANGELOG.

## Next action

- Merge del PR (squash) y verificación del CI completo con `gh run list`.
- Después, el change **B** `update-reinicia-daemon`: su `plan.md` hay que **reescribirlo** para
  consumir `checks.CHECKS` en vez de traer lógica propia. El contrato ya existe: `probe` mira,
  `fix_hint` dice, y quien escribe es B (y luego C con `install --clients auto`).
- Aparte de la cadena: esta PC necesita un `local-delegate install` para migrar sus hooks
  heredados; el diagnóstico los marca `[WARN] 3 de 3 en el formato heredado`.

## Memory

- Canonical note: pendiente en el vault (`projects/local-delegate/`), junto al backlog.
- Indexes updated: pendiente.
