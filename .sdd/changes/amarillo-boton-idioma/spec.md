# Especificación (modo lite): el amarillo del botón de idioma es color de UI, no de ruta

## La premisa, reproducida

Confirmada por lectura del fichero, con las dos partes que decía el backlog:

```css
/* site/index.html:107 — la declaración del token */
--local: #E8B500;   /* amarillo de señal: la vía que se toma */

/* site/index.html:208-211 — el uso */
.lang button[aria-pressed="true"] {
  color: var(--ink); border-color: var(--local); background: var(--local);
  color: #0D1A1D;
}
```

Es la misma mezcla que se corrigió en el titular con el PR #67: un token con significado
semántico —«la vía que se toma»— usado como color de estado de una UI. Elegir idioma no es tomar
una ruta.

**Pero el segundo detalle del backlog resulta ser lo contrario de lo que parecía.** El `color:`
declarado dos veces **no es residuo**: `--ink` vale `#0D1A1D` en tema claro pero **`#E4EBE8` en
oscuro**, casi blanco, que sobre el amarillo daría un contraste pésimo. El `#0D1A1D` literal es
una **corrección deliberada**, y la declaración que sobra es la primera.

## Las superficies, contadas antes de arreglar una

El repo ya pagó el error de corregir una superficie sin contar las demás. Los **18** usos de
`--local`/`--local-deep`:

| Uso | Veredicto |
|---|---|
| Troncal del diagrama, remate, estaciones encendidas, `.lane.down`, bordes de sección, `.term .y`, números del cálculo (14) | **Correcto.** Ahí el amarillo *es* la vía que se toma. |
| `.lang button[aria-pressed="true"]` (L209) | **Mezcla.** Un estado de UI con un token de ruta. |
| CTA principal (L379) | **Correcto.** El botón «empieza aquí» es literalmente la vía que se toma. |
| Anillo de foco (L193) y subrayado de enlaces (L191) | **Se dejan.** Ahí el amarillo actúa como color de acento interactivo, un rol de UI consistente en todo el sitio, y no afirma «esta es la ruta buena». |

## Requisitos

- **REQ-001:** El estado activo del selector de idioma **no usa** `--local` ni `--local-deep`.
- **REQ-002:** Ese estado sigue siendo inequívocamente distinguible del inactivo, con contraste
  suficiente **en los dos temas**.
- **REQ-003:** Desaparece la declaración `color` duplicada, y **sin perder** lo que arreglaba: el
  texto tiene que contrastar con su fondo en claro y en oscuro.
- **REQ-004:** Un test ata la regla, para que nadie la revierta sin enterarse.

## Escenarios de aceptación

### Escenario: alguien cambia de idioma en tema oscuro

- **Dado** el sitio en tema oscuro
- **Cuando** se mira el botón del idioma activo
- **Entonces** se distingue del inactivo y su texto es legible, sin usar el amarillo de ruta

## No objetivos

- Tocar los 14 usos que sí son de ruta, ni el CTA, ni el foco y el subrayado.
- Rediseñar el selector de idioma más allá de su color.

## Trazabilidad

- REQ-001 · REQ-002 · REQ-003 → `site/index.html`
- REQ-004 → `tests/test_site.py`
