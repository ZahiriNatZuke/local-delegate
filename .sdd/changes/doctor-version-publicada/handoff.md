# Handoff: doctor compara la version instalada contra la publicada en PyPI

## Current state

- **SDD status:** cerrado.
- **Último gate:** `memory` (tras `spec`, `plan`, `quality` y `conformance`).
- **Revisión:** PR **#76** mergeado el 2026-07-30, `main` en `f05b4e2`. Los 12 checks del PR y
  el CI completo de `main` (CI, CodeQL, Vendor audit) en verde. **En `Unreleased`, sin publicar.**

## What changed

Comprobación número **trece** del registro (`cli.published`, grupo *Entorno*): compara la versión
instalada con la última publicada en PyPI y avisa `[WARN]` si la instalación se quedó atrás. El
dato sale de `update.latest_version` a través de un colaborador nuevo del `Context`
(`latest_release`), y `install` y `update` inyectan `SKIP_PYPI` para no salir a internet.

429 tests (+12), documentación de la wiki y CHANGELOG actualizados.

## Decisions

1. **La consulta corre en toda ejecución de `doctor`, no detrás de `--online`.** Decisión
   explícita del usuario: nadie corre `doctor --online` a diario, y el valor está en que la señal
   aparezca sin pedirla. Sostenible porque se midió antes: el índice simple responde en ~0.08 s, y
   el peor caso lo acota `PYPI_TIMEOUT = 2.0`. `--online` **conserva** su significado (versiones
   del backend contra GitHub) y no gobierna esta comprobación.
2. **`install` y `update` no salen a la red por el registro, y cada uno por su motivo distinto:**
   instalar unos hooks no es razón para consultar PyPI; `update` ya pregunta por su cuenta unas
   líneas más abajo y una segunda llamada sería contar dos veces lo mismo. El mecanismo es
   `SKIP_PYPI` inyectado, **no** el filtro por grupos — `cli.published` vive en `entorno`, que
   `install` sí corre.
3. **Se aceptó el `[ -- ] no se consulta PyPI en este comando` en el reporte de `install`** antes
   que añadir un `exclude` por check a `run_all`: eso sería la primera grieta hacia el framework
   que la regla 3 del módulo prohíbe.
4. **El `fix_hint` depende del tipo de instalación.** En editable, `uv tool upgrade` no actualiza
   nada; el hint pasa a `git pull` + `uv sync` sobre el repo del que sale el código.
5. **Check nuevo en vez de ampliar `cli.path`:** «¿está en el PATH?» y «¿está al día?» son dos
   preguntas distintas, y la segunda funciona aunque el comando no exista (`uvx`), porque la
   versión sale de `importlib.metadata`.

## Gotchas que costaron tiempo aquí

- **Doblar `checks._default_latest_release` con monkeypatch NO funciona.** El dataclass captura la
  referencia a la función al definir el campo, así que reasignar el atributo del módulo no cambia
  el default. Hay que doblar el **destino** (`update.latest_version`), que es lo que ya hacía
  `_stub_environment` con `daemon.query_daemon` y `doctor.backend_probe`.
- **Un colaborador que lanza `AssertionError` no hace fallar un test del registro:** `run_all`
  captura las excepciones de los probes a propósito, así que el `raise` se traga y el test pasa
  con la red ya tocada. Hay que **anotar** la llamada y aseverar sobre la anotación.
- **El filtro por grupos y `SKIP_PYPI` son dos mecanismos distintos** y no deben mezclarse en el
  mismo test. Lo cazó un test que falló con razón.

## Next action

Nada pendiente de este change. Lo siguiente del backlog es el punto 2 (`update` anuncia la versión
anterior justo tras publicar), que **hay que replantear antes de tocar**: el arreglo que proponía
el backlog viejo ya estaba aplicado. Dato medido en esta sesión y útil para ese change: el índice
simple sirve con `cache-control: max-age=600` y el JSON con `max-age=900`, o sea que
`latest_version()` **ya usa el más fresco de los dos** y cambiar de endpoint empeoraría.

## Memory

- **Nota canónica:** pendiente de la nota de jornada en el vault
  (`projects/local-delegate/`), que se escribe al cerrar la sesión.
- **Índices actualizados:** `CHANGELOG.md` (bajo `Unreleased`) y
  `docs/wiki/Integration-install.md`.
- Sin secretos, credenciales ni datos personales en la traza.
