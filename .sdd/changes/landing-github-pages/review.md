# Revisión del resultado: La landing vive en el repo y se publica en GitHub Pages

## Veredicto

`conforms-with-notes` — el resultado cumple los seis requisitos, verificados hoy por ejecución. La
nota es **de proceso, no de producto**: la traza SDD se rellenó a posteriori.

## Comparación contra la especificación

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | Página bilingüe; un test dedicado exige que los dos idiomas tengan exactamente las mismas claves. |
| REQ-002 | sí | sí | Las tres últimas ejecuciones de `pages.yml` en `success`. Disparadores por `paths`, más `workflow_dispatch`. |
| REQ-003 | sí | sí | El build sustituye `__LD_VERSION__` por `0.17.0` y la página publicada lo trae ya sustituido. |
| REQ-004 | sí | sí | `--check` responde «sin marcadores pendientes» y falla el despliegue si sobrevive alguno. |
| REQ-005 | sí | sí | Cero recursos de terceros en el HTML servido. |
| REQ-006 | sí | sí | Se publica `site/`; `docs/` no entra. |

## Hallazgos

1. **De proceso, y es el motivo de este cierre:** los artefactos SDD se commitearon en plantilla.
   El trabajo salió bien —tests verificados al revés, dos defectos cazados en la propia revisión
   del PR— pero **la especificación no lo guió**, así que `spec` y `plan` se aprueban como
   registro de lo entregado y así queda dicho en su evidencia.

2. **Menor, ya mitigado por diseño:** la versión que anuncia la página es la del último
   despliegue. Como `pyproject.toml` está entre los `paths` que disparan el workflow, cada release
   la pone al día sola.

3. **Ninguno de corrección, seguridad o alcance.** La página no lleva credenciales, no sale a la
   red y no toca el paquete.

## Seguimiento requerido

Ninguno antes del cierre. La deuda que sí queda viva —**que nada obliga a regenerar la captura del
README**— es de otro alcance y se ataca en su propio cambio.
