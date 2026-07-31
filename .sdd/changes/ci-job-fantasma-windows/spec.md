# Especificación (modo lite): el job de Windows puede colgarse y bloquear un merge sin límite

## El problema, medido

**Dos veces en dos días**, `test (windows-latest)` se quedó en `in_progress` **con todos sus pasos
terminados en `success`**, bloqueando el merge:

| Fecha | PR | Duración del run | Lo normal |
|---|---|---|---|
| 2026-07-30 | #77 | **1954 s** (32 min) | 60–125 s |
| 2026-07-31 | #86 | **651 s** y subiendo, hasta cancelarlo a mano | 60–125 s |

De 22 runs recientes de `ci.yml`, **solo esos dos** pasan de 300 s. No es una degradación
gradual: son dos cuelgues.

## El diagnóstico, con evidencia

La API del job colgado devuelve esto:

```
status: in_progress          completed_at: null
pasos: Set up job ✔  checkout ✔  Install uv ✔  Sync deps ✔
       Tests (pytest) ✔  Post Install uv ✔  Post checkout ✔  Complete job ✔
```

**Todos los pasos completados, incluido `Complete job`.** El runner terminó su trabajo en 86 s; lo
que falta es que GitHub marque el job como cerrado. O sea, **el cuelgue es posterior a nuestro
código**.

Se descartó **por ejecución** la hipótesis más razonable —un proceso hijo huérfano que retiene los
handles del job, que es el fallo clásico en Windows—: la suite corrió completa en esta máquina
Windows y **no dejó ni un proceso nuevo**. Lo único que lanza procesos desacoplados
(`update._spawn_detached`, un `serve` con `DETACHED_PROCESS`) va doblado en los tests.

**Lo que no podemos arreglar** es la infraestructura de GitHub. **Lo que sí** es que un cuelgue
suyo se convierta en una espera indefinida: `ci.yml` **no declara `timeout-minutes` en ningún
job**, así que rige el default de GitHub, **360 minutos**. `codeql.yml` (20) y `vendor-audit.yml`
(10) sí lo declaran: el criterio ya existe en el repo y falta justo en el workflow que se cuelga.

## Requisitos

- **REQ-001:** Todos los jobs de `ci.yml` declaran `timeout-minutes`, con margen amplio sobre su
  duración real y muy por debajo de las 6 horas del default.
- **REQ-002:** El valor elegido queda **justificado en el propio fichero**, con la duración
  observada, para que nadie lo suba «por si acaso» sin datos.
- **REQ-003:** Un push nuevo a una rama de trabajo **cancela el run anterior de esa misma rama**,
  para que un run colgado no siga ocupando ni confundiendo el estado del PR.
- **REQ-004:** `main` queda **excluida** de esa cancelación: un run sobre `main` se termina
  siempre.
- **REQ-005:** El síntoma y su diagnóstico quedan escritos donde se buscan, para no volver a
  investigarlo desde cero: **el reloj de la interfaz no distingue «tarda» de «terminó y nadie lo
  marcó»**, y se comprueba mirando los *steps* del job.

## Escenarios de aceptación

### Escenario: el job vuelve a colgarse

- **Dado** un `test (windows-latest)` que termina sus pasos y no cierra
- **Cuando** pasa el tiempo declarado
- **Entonces** el job **falla por timeout** y se puede relanzar, en vez de bloquear el merge
  durante horas

### Escenario: alguien empuja un arreglo mientras el run anterior sigue colgado

- **Dado** un run colgado en una rama de trabajo
- **Cuando** se empuja un commit nuevo a esa rama
- **Entonces** el run anterior se cancela solo

### Escenario: push a `main`

- **Dado** un run en curso sobre `main`
- **Cuando** entra otro push a `main`
- **Entonces** el anterior **no** se cancela

## Comportamiento en los bordes

- **Un timeout no es un fallo de código y no debe leerse como tal.** Por eso el valor va
  justificado: si un job legítimamente creciera hasta rozarlo, lo que toca es subir el número con
  datos, no reintentar a ciegas.

## No objetivos

- **Arreglar la causa raíz**, que está en la infraestructura de GitHub y no es nuestra.
- Reducir la matriz de sistemas: existe porque cazó una fuga de handles que **solo** ocurría en
  Windows.
- Reintentar el job automáticamente. Un reintento automático esconde el problema en vez de
  acotarlo, y aquí interesa que se vea.

## Trazabilidad

- REQ-001 · REQ-002 · REQ-003 · REQ-004 → `.github/workflows/ci.yml`
- REQ-005 → `docs/wiki/Repo-hardening.md` + `CHANGELOG.md`
