# Verificación (modo lite): el amarillo del botón de idioma

## Entorno

- Rama `fix/amarillo-boton-idioma`, sobre `main` en `b5c51ef`.
- Sitio servido con `python -m http.server` desde `site/`; medición en Chromium vía Playwright.

## Evidencia

| Requisito | Comprobación | Resultado |
| --- | --- | --- |
| REQ-001 | La regla del idioma activo | ya no menciona `--local` ni `--local-deep` |
| REQ-002 | Contraste **medido en el navegador**, tras la transición | **13,90:1** en claro y **15,17:1** en oscuro (antes 9,34 y 11,92) |
| REQ-002 | Inactivo vs activo | el inactivo queda con fondo transparente y texto `--muted`; la diferencia es inequívoca |
| REQ-003 | La regla | una sola declaración `color`, y sin literales: `--ink` y `--paper` se invierten juntos |
| REQ-004 | Test nuevo | pasa, y **falla** con cualquiera de los dos defectos reintroducidos |
| — | Inspección visual en los dos temas | capturas del selector: activo invertido, legible y sobrio |

### El test, verificado al revés

| Defecto inyectado | Resultado |
| --- | --- |
| Vuelve el amarillo (`--local` en fondo y borde) | 1 falla, 23 pasan |
| Vuelve el `color` duplicado | 1 falla, 23 pasan |
| *(restaurado)* | **24 pasan** |

## Un error propio de medición, corregido

La primera medición dio en tema oscuro un texto `rgb(49,59,60)` que **no** cuadraba con `--paper`
(`rgb(12,22,24)`). No era el CSS: se midió **durante la transición de 160 ms** que el propio botón
declara. Repetida con espera, el valor es el esperado y el contraste coincide con el calculado
sobre el papel. Es el mismo tipo de error que el `exit 0` de una tubería: medir algo distinto de
lo que se cree medir.

## Comprobaciones de calidad

- [x] `uv run pytest -q` → 482 pasan, 1 skip.
- [x] `ruff check` y `ruff format --check` limpios; `node --check` OK.
- [x] `CHANGELOG.md` sigue CRLF puro.
- [x] Sin cambios ajenos: el diff toca `site/index.html`, `tests/test_site.py` y el `CHANGELOG`.

## Desviaciones y riesgo residual

- **Se deja `--local` en el anillo de foco, el subrayado de enlaces y el CTA**, con criterio
  escrito en la especificación: en los dos primeros el amarillo actúa como color de acento
  interactivo —un rol de UI consistente en todo el sitio— y el CTA es literalmente la vía que se
  toma. Si en el futuro se decide que el token no debe aparecer en **ninguna** UI, esas tres son
  las superficies a revisar, y quedan nombradas aquí para no volver a contarlas.
