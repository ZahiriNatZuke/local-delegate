# Result review: Sube el Chart.js vendorizado a 4.5.1

## Verdict

`conforms-with-notes` — cumple los cinco requisitos; las notas son límites de la verificación, no
trabajo sin hacer.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 · el blob es el dist de 4.5.1, con procedencia verificada contra la fuente canónica | sí | sí | Tarball oficial de npm y jsDelivr dan los mismos 208 522 bytes y el mismo `sha256 48444a82…f54a` |
| REQ-002 · manifiesto al día, con nota de procedencia de lo observado | sí | sí | `vendor.json`: versión, `source` apuntando al tarball, hash, bytes y la nota del banner reescrita —incluido que a 4.5.1 **no** se lo pusieron— |
| REQ-003 · licencia acorde a la versión | sí | sí | Diff: sigue MIT, `2014-2022` → `2014-2024`. Actualizada |
| REQ-004 · el vigilante verde y **sin avisos** | sí | sí | «Integridad OK», «OSV no conoce ninguna para 4.5.1», «está al día». exit 0, cero `AVISO` |
| REQ-005 · el dashboard pinta, comprobado mirándolo, con línea base previa | sí | sí | 4.4.1 → 6 instancias, 5 canvas pintados, 0 errores. 4.5.1 → lo mismo. Capturas de ambas |

## Findings

1. **(La que importa) La actualización destapó dos fuentes de verdad paralelas.** `test_metrics.py`
   afirmaba `"Chart.js v4.4.1"` y los tests del vigilante pasaban versiones literales. Eran
   exactamente el problema que `vendor.json` vino a resolver, **sobrevivieron al cambio que lo
   introdujo**, y solo se manifiestan al actualizar. Corregido de raíz: los dos leen del manifiesto.
   Deja una lección aplicable a cualquier «fuente de verdad única» que se introduzca: el día que se
   crea no se sabe si quedó alguna copia; se sabe la primera vez que el valor cambia.
2. **El procedimiento documentado tenía un defecto de origen: bajaba de un CDN.** Estaba escrito de
   memoria, sin haberse ejecutado nunca. Además no decía nada de la licencia, que también cambia.
   Corregido, y ya probado una vez.
3. **La caché de 24 h del endpoint disfraza el resultado.** Al verificar, el navegador seguía
   diciendo `4.4.1` con el servidor sirviendo ya los bytes nuevos. Anotado en la wiki: sin eso, el
   siguiente que verifique concluirá que la actualización «no se aplicó».
4. **(Menor, sin acción) El canvas `spark` sale con cero píxeles en ambas versiones.** No es
   regresión —es idéntico antes y después— y responde a que el rango «Hoy» tiene pocos eventos.
   Mirarlo sería otro cambio.

## Required follow-up

Ninguno para cerrar. Fuera de este change:

- **Publicar.** Esto queda en `Unreleased` y no mejora nada para quien instala hasta que salga una
  versión. Es decisión del usuario.
