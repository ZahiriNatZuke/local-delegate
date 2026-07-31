# Revisión del resultado (modo lite): vigilante de la captura del README

## Veredicto

`conforms`

## Comparación contra la especificación

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | `docs/assets/dashboard.json` con `version`, `sha256`, `bytes` y `file`, generado con el mismo código del script. |
| REQ-002 | sí | sí | Ejecución real: el manifiesto registra la versión leída de `/api/status` del dashboard capturado. El borde de versión ilegible da `exit 3` sin tocar el manifiesto anterior. |
| REQ-003 | sí | sí | El test falla al alterar un byte del PNG. `-text` declarado y comprobado con `git check-attr`. |
| REQ-004 | sí | sí | El test falla si el manifiesto declara otra versión — el caso real de la 0.16.0. |
| REQ-005 | sí | sí | El mensaje trae el comando exacto y avisa de no capturar contra el daemon del 9393. |
| REQ-006 | sí | sí | La wiki remite al test y da un comando **probado**, en lugar del que no funciona. |

## Hallazgos

1. **Ninguno bloqueante.**

2. **Una corrección propia, registrada:** al aprobar la spec di por bueno que
   `python -m local_delegate.web.metrics` «sale con exit 0, así que parece que arrancó». Era
   falso —sale con **exit 3**—; el `0` venía de `head` al otro lado de una tubería. El motivo de
   REQ-006 se sostiene sin ese detalle, pero el detalle era incorrecto y quedó anotado en
   `plan.md` y `verification.md`. Es el mismo tipo de error que el proyecto ya tiene fichado:
   verificar por ejecución, **y comprobar que estás midiendo lo que crees medir**.

3. **Observación fuera de alcance, anotada y no arreglada:** el docstring del script dice que «la
   misma semilla da la misma captura», y no es del todo cierto — el eje temporal sale de
   `new Date()`, así que capturar mañana produce otro PNG. No lo introduce este cambio y no
   molesta en la práctica, porque el manifiesto se regenera junto a la imagen.

## Seguimiento requerido

Ninguno antes del cierre. Pero sí una consecuencia operativa que hay que **ejecutar**, no solo
recordar: **el PR que suba la versión a 0.18.0 fallará hasta que se regenere la captura**. Es el
comportamiento buscado; publicar pasa a incluir ese paso.
