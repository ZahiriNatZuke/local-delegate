# Brief: El cancelled del CI en main tiene causa conocida y firma reconocible

## Problem

`main` acumula runs `cancelled` de `ci.yml` sin que nada esté roto: **3 de los últimos 40**, todos
con `test (windows-latest) → cancelled` y los otros seis jobs en `success`, `ci-gate` incluido.

El pendiente decía que «no deja rastro» y proponía elegir entre reintento, `timeout-minutes` o
dejar de contarlo. **La investigación cambió la pregunta**: no hacía falta elegir remedio, hacía
falta corregir un diagnóstico.

Tres sitios del repo —`ci.yml:71-74`, `scripts/ci_gate.py` y `docs/wiki/Repo-hardening.md:46-57`—
afirmaban que `timeout-minutes` **no dispara** sobre este cuelgue, deducido de haber visto el job
más de 10 minutos vivo con el límite en 8 (PR #88).

**Es falso.** Los tres runs `cancelled` de `main` del 2026-07-31 (`30652987094`, `30654961990`,
`30660878897`) murieron a los **13:00 exactos** desde el inicio del job, y con estados internos
**distintos**: dos con `Tests (pytest)` todavía `in_progress`, uno con todos los pasos en
`success` (`Complete job` incluido). Trece minutos clavados con tres estados distintos solo lo
explica un temporizador, y **13 = 8 del límite + 5 de gracia**. Los «más de 10 minutos» observados
eran el periodo de gracia.

## Desired outcome

Quien vea un `cancelled` sepa en diez segundos si es el cuelgue conocido o una avería, sin volver
a investigarlo desde cero.

## In scope

- Corregir el diagnóstico en los tres sitios que lo repiten.
- Un límite propio para el paso `Tests (pytest)`, que es el otro hallazgo de la medición.
- Tests que aten los números al texto que los explica.

## Out of scope

- **Reintento automático del job.** Enmascararía un cuelgue real, y GitHub no tiene retry nativo de
  jobs.
- **Bajar el límite del job.** Aceleraría el fracaso sin evitarlo; 8 min ya son ~4x el peor caso.
- **Arreglar el cuelgue de GitHub.** Es suyo y no tiene solución oficial (discusión #161434).
- Diagnosticar *por qué* pytest se cuelga en Windows: **no hay log** (`BlobNotFound`), así que
  cualquier causa sería inventada.

## Constraints and risks

- **El límite del paso cambia la conclusión** de `cancelled` a `failure` cuando quien se cuelga es
  pytest. Es deseable —falla antes y con log— pero es un cambio visible.
- Si quien se cuelga es el runner, el límite del paso no rescata: no hay proceso que matar. Manda
  el del job.

## Open questions

- Ninguna. La pregunta del pendiente («¿qué remedio?») se disuelve al medir: el remedio ya estaba
  puesto y lo que faltaba era saberlo.
