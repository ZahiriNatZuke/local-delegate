# Handoff: update dice de donde saco la version publicada y como saltarse la cache

## Current state

- **SDD status:** cerrado.
- **Último gate:** `memory`.
- **Revisión:** PR **#77** mergeado el 2026-07-30, `main` en `5afe69b`. Los 12 checks del PR y el
  CI completo de `main` (CI, CodeQL, Vendor audit) en verde. **En `Unreleased`, sin publicar.**

## What changed

`update` dice de dónde salió la versión y detecta el desfase de justo después de publicar. 438
tests (+9). Solo cambia texto de salida: ni el plan de acciones ni el exit code se tocan, y hay
un test que lo fija.

## Decisions

1. **El pendiente estaba mal diagnosticado y se corrigió con medición.** Decía que la causa es
   consultar el JSON de PyPI y que había que pasar al índice simple: `latest_version()` **ya**
   consultaba el índice simple, y cambiar al JSON habría **empeorado** el síntoma —índice simple
   `max-age=600`, JSON `max-age=900`—. Escrito en el docstring de `latest_version()` para que no
   haya que volver a medirlo.
2. **No se puede distinguir «caché stale» de «publicación sin terminar» desde el comando.** No hay
   header `Age`, y `publish.yml` tarda ~40 s. Por eso se detecta la **firma** del caso —instalada
   más nueva que publicada—, que es exacta y no una heurística.
3. **Nada de reintentos ni cache-busters.** Un comando que se cuelga esperando a un CDN ajeno es
   peor que uno que dice lo que ve.
4. **El aviso saldrá en cada `update` de una máquina de desarrollo** (el repo va por delante de
   PyPI casi siempre). Se acepta a propósito: la afirmación es cierta, y suprimirlo en
   instalaciones editables lo apagaría justo en la máquina desde la que se publica.

## Lo que queda abierto, y por qué está bien

**La causa raíz.** Aislarla exige medir durante una publicación real, y publicar necesita
confirmación explícita del usuario. Este cambio no la resuelve: hace que **la próxima publicación
deje constancia en pantalla** de si el desfase ocurrió. Cuando se publique la siguiente versión,
mirar si aparece el bloque «la instalada es MÁS NUEVA que la que anuncia PyPI» y cuánto tarda en
dejar de aparecer: eso zanja la pregunta sin adivinar.

## Incidente de infraestructura, no del código

El job `test (windows-latest)` del PR #77 quedó **29 minutos en estado fantasma**: todos sus pasos
terminaron con éxito a los 86 s —incluido `Complete job`— y GitHub siguió reportándolo
`in_progress`. GitHub Status decía «All Systems Operational». Se resolvió con `gh run rerun`, y el
job repetido tardó **66 s**, en línea con su histórico (55-67 s en los siete runs anteriores).

**Lo que vale para la próxima:** antes de culpar al código de un job lento, mirar los *steps* del
job (`gh api repos/<owner>/<repo>/actions/jobs/<id>`). El reloj de la interfaz cuenta desde el
encolado y no distingue «tarda» de «terminó y nadie lo marcó». Y ojo: `gh run cancel` puede
responder «Cannot cancel a workflow run that is completed» sobre un run que la API acababa de
enseñar como `in_progress` — el estado va con retraso en las dos direcciones.

## Next action

Nada pendiente de este change. Lo siguiente del backlog es el punto 3: `update` no actualiza el
CLI instalado como `uv tool`. Dato ya recogido para ese change: en esta máquina conviven **dos**
instalaciones —la de `uv tool` en `~/.local/bin/local-delegate` (0.17.0) y la editable del repo en
`.venv`— y `sys.prefix` es lo que distingue desde cuál se está ejecutando el proceso.

## Memory

- **Nota canónica:** pendiente de la nota de jornada en el vault (`projects/local-delegate/`).
- **Índices actualizados:** `CHANGELOG.md` bajo `Unreleased`.
- Sin secretos, credenciales ni datos personales.
