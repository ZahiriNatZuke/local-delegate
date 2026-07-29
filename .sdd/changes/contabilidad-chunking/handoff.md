# Handoff — `contabilidad-chunking`

## Estado actual

- **SDD:** gates `spec`, `plan`, `quality` y `conformance` aprobados; queda `memory`.
- **Rama:** `feat/contabilidad-chunking`, commit `e574df2`, sobre `main` en `dcc614c` (0.13.1).
- **CI local:** 277 tests, ruff limpio, `node --check` OK.
- **Sin publicar:** la entrada va en `Unreleased`. Publicar exige confirmación explícita del usuario.

## Qué cambió

- El dashboard mide ahora **el coste** además del ahorro: KPI «Coste local» con los tokens de
  entrada reales sumando **todas** las llamadas, y las llamadas al backend junto al número de
  delegaciones.
- Las cuentas usan **el token real que reporta el backend**; `chars ÷ 4` queda de respaldo y el
  panel declara cuántos eventos hubo que estimar.
- `local_describe_image` deja de inflar el ahorro ×46: el evento declara `input_unit: "bytes"`.
- **Una sola implementación de la contabilidad**, en `server.py`. Había tres.
- OpenTelemetry descartado como fuente de métricas, con el porqué en `Architecture.md`.

## Decisiones que no se derivan del código

1. **OTel descartado, y por qué.** El middleware del SDK instrumenta el **borde MCP**, no las
   llamadas al backend; `opentelemetry-api` es solo la mitad emisora y sin `opentelemetry-sdk` los
   spans son `NonRecordingSpan`; recogerlos exigiría un colector corriendo, y el dashboard tiene que
   funcionar recién instalado. Escrito en la wiki para no re-evaluarlo dentro de tres meses.
2. **El ahorro de texto NO se toca, a propósito.** Es el contenido contado **una vez** aunque se
   trocee: el overhead lo pagó la GPU, no el contexto de Claude. Un arreglo mal enfocado habría
   roto un KPI sano. Está escrito en la wiki para que nadie lo "corrija".
3. **`chunks` en el log siempre ha significado llamadas, no trozos** — confirmado con `git log -S`
   hasta el commit que introdujo el chunking. Por eso el histórico queda bien contabilizado sin
   migrar nada.
4. **La contabilidad vive en `server.py`, no en `metrics.py`**, porque `metrics` ya importa
   `server` (la otra dirección haría ciclo) y porque es donde está `_log_event`, que define el
   formato del log.

## Lecciones para el proyecto

- **Contar las superficies antes de arreglar una.** El research encontró dos y había **tres**: el
  agregado de `/api/stats`, el JS del panel y `local_status`. La tercera apareció al revisar el
  diff, no al planificar.
- **Un KPI puede contradecirse a sí mismo en silencio:** el panel sumaba sobre la lista topada a
  5000 eventos mientras mostraba al lado el total real.
- **Los mismos datos, dos lenguajes, dos redondeos:** `Math.round` en JS contra `//` en Python.

## Siguiente paso

Abrir el PR contra `main`, esperar los checks y verificar el CI completo con `gh run list` después
del merge (no solo los checks del PR).

## Memoria

- Nota canónica: pendiente en el gate `memory` — `projects/local-delegate/contabilidad-chunking.md`
  en el vault, más el puntero en `MEMORY.md` y la actualización del backlog.
