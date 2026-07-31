# Revisión del resultado (modo lite): el amarillo del botón de idioma

## Veredicto

`conforms`

## Comparación contra la especificación

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | La regla no menciona `--local` ni `--local-deep`. |
| REQ-002 | sí | sí | 13,90:1 y 15,17:1 medidos en el navegador; el inactivo es transparente con texto `--muted`. |
| REQ-003 | sí | sí | Una sola declaración `color`, sin literales: los dos tokens se invierten juntos. |
| REQ-004 | sí | sí | Test nuevo, que falla con cualquiera de los dos defectos reintroducidos. |

## Hallazgos

1. **Ninguno bloqueante.**

2. **El backlog acertaba en el síntoma y erraba en el diagnóstico del segundo detalle.** Decía
   «esa regla declara `color` dos veces (`var(--ink)` y `#0D1A1D`, que son el mismo valor) — mirar
   si es residuo». **No son el mismo valor:** coinciden solo en tema claro, porque `--ink` vale
   `#E4EBE8` en oscuro. El literal era una corrección deliberada, y borrarlo sin más habría dejado
   texto casi blanco sobre fondo amarillo. Un pendiente es una hipótesis, otra vez.

3. **Se contaron las 18 superficies antes de tocar una**, que es el error que este mismo repo
   cometió cuando corrigió el titular y dejó el botón de idioma. De ellas, 14 son de ruta y
   correctas; el CTA es literalmente la vía que se toma; el foco y el subrayado usan el amarillo
   como acento interactivo. Solo una era mezcla. Las tres discutibles quedan **nombradas** en la
   verificación, por si algún día se decide que el token no aparezca en ninguna UI.

4. **Un error propio de medición, corregido y anotado:** la primera lectura del color computado se
   tomó durante la transición de 160 ms del botón y daba un valor que no cuadraba con ningún
   token. Con espera, cuadra.

## Seguimiento requerido

Ninguno.
