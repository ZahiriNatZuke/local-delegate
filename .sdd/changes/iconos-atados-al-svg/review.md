# Result review: Los PNG de la marca quedan atados al favicon.svg

## Verdict

`conforms-with-notes`

## Specification comparison

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 manifiesto con el sha del SVG | Sí | Sí | `site/icons.json` |
| REQ-002 falla si el SVG cambió | Sí | Sí, mutante | Con el comando en el mensaje |
| REQ-003 hash de cada PNG | Sí | Sí, mutante | Cubre regenerar por fuera del script |
| REQ-004 conjuntos iguales | Sí | Sí, mutante | `og-image.png` excluido con su razón |
| REQ-005 un comando | Sí | Sí | Ejecutado de verdad |
| REQ-006 falla claro sin playwright | Sí | Por revisión | No se ejercitó desinstalándolo |
| REQ-007 no deja el servidor vivo | Sí | Por revisión | `finally` con `shutdown` + `server_close` |

## Findings

1. **Menor — el hash no compara píxeles.** Detecta «este PNG no salió de este SVG», no «dibuja
   otra cosa». Regenerar con otro chromium obligará a commitear PNG nuevos sin que la marca haya
   cambiado. Es el precio de no meter un navegador en el CI, y está escrito.
2. **Menor — REQ-006 y REQ-007 se verifican por revisión**, no por ejecución: desinstalar
   playwright para probar el mensaje costaría más de lo que aporta.
3. **Informativo — el pendiente daba por necesario rasterizar en el CI y no lo era.** El fallo
   real es «los PNG se quedan viejos», y eso lo detecta un hash del origen.
4. **Informativo — los PNG cambiaron de tamaño al regenerarlos** (1669→2116, 424→488). Los
   originales venían de otro navegador. Los tests de dimensiones y de `<link sizes>` siguen
   pasando, así que la marca no cambió: cambió la codificación.

## Required follow-up

- Ninguno para cerrar.
