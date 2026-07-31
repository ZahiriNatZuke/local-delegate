# Specification: El cancelled del CI en main tiene causa conocida y firma reconocible

## Summary

El repo deja de afirmar algo falso sobre su propio CI. `timeout-minutes` **sí** actúa sobre el
cuelgue de Windows, y su firma —13 minutos exactos— queda escrita donde se busca, atada por tests
para que no vuelva a desfasarse. Además, el paso `Tests (pytest)` recibe un límite propio, que
cubre el caso en que quien se cuelga es pytest y no el runner.

## Requirements

- **REQ-001:** `ci.yml`, `ci_gate.py` y `Repo-hardening.md` dejan de afirmar que `timeout-minutes`
  no dispara, y explican la firma de 13 minutos con su aritmética.
- **REQ-002:** El paso `Tests (pytest)` declara un `timeout-minutes` propio, **menor** que el del
  job (si no, no llegaría a actuar nunca).
- **REQ-003:** Un test falla si el límite del job cambia sin que se actualice el texto que explica
  la firma.
- **REQ-004:** Un test falla si el paso pierde su límite o deja de ser menor que el del job.
- **REQ-005:** La documentación permite clasificar un `cancelled` sin reinvestigarlo.

## Acceptance scenarios

### Scenario: alguien se encuentra un cancelled en main

- **Given** un run `cancelled` con el job de Windows de ~13 minutos y el resto en `success`
- **When** consulta `Repo-hardening.md`
- **Then** encuentra que es el cuelgue conocido, que no bloquea nada y que no hay avería

### Scenario: alguien sube el límite del job

- **Given** `timeout-minutes: 8` cambiado a otro valor
- **When** corre la suite
- **Then** falla el test que ata la firma, indicando que el texto se quedó viejo

### Scenario: pytest se cuelga

- **Given** un `Tests (pytest)` que no termina
- **When** pasan 5 minutos
- **Then** el paso se corta y deja log, en vez de arrastrar el job hasta los 13 sin log

## Edge cases and failure behavior

- **Se cuelga el runner, no pytest:** el límite del paso no actúa (no hay proceso que matar) y
  manda el del job. El resultado es el de hoy, y `ci-gate` sigue dando el veredicto por los pasos.
- **GitHub cambia el periodo de gracia:** la firma dejaría de ser 13. El test no lo detectaría por
  sí solo —mide contra el número declarado, no contra la realidad de GitHub— y esa limitación
  queda escrita.

## Non-functional requirements

- **Sin cambios de comportamiento en el caso normal:** un run sano no nota nada.
- **La corrección se escribe como corrección**, diciendo qué se creía y por qué era falso. El error
  tiene valor documental: es la segunda vez que este cuelgue se diagnostica mal.

## Non-goals

- Reintentar jobs automáticamente.
- Diagnosticar la causa del cuelgue de pytest en Windows: sin log, sería inventarla.
- Tocar el cuelgue de GitHub, que no tiene solución oficial.

## Traceability

| Requisito | Trabajo | Evidencia |
| --- | --- | --- |
| REQ-001 | Tareas 1-3 | Los tres ficheros corregidos |
| REQ-002 | Tarea 1 | `ci.yml`, paso `Tests (pytest)` |
| REQ-003 | Tarea 4 | `test_el_limite_del_job_*` + mutante |
| REQ-004 | Tarea 4 | `test_el_paso_de_tests_tiene_su_propio_limite_*` + 2 mutantes |
| REQ-005 | Tarea 3 | Tabla de `Repo-hardening.md` |
