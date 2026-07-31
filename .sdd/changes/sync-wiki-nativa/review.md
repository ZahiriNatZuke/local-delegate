# Result review: La wiki nativa se sincroniza sola desde docs/wiki

## Verdict

`conforms-with-notes`

## Specification comparison

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 dispara con `docs/wiki/**` | Sí | Sí | Mutante sobre el `paths` |
| REQ-002 borra las huérfanas | Sí | Por revisión | No ejercitable sin escribir en la wiki real |
| REQ-003 convierte lo que sale | Sí | Sí | 18 enlaces, 0 restantes |
| REQ-004 conserva lo interno | Sí | Sí | 18 enlaces intactos |
| REQ-005 conserva el ancla | Sí | Sí | — |
| REQ-006 no empuja sin cambios | Sí | Por revisión | `git diff --cached --quiet` |
| REQ-007 nada huérfano del índice | Sí | Sí | — |

## Findings

1. **Menor — el push real a la wiki queda pendiente del merge.** Es lo único que no se puede
   ejercitar antes, y falla en rojo si falla. Se comprobará en el primer push a `main`.
2. **Informativo — el change encontró un defecto que el enunciado no anticipaba.** El backlog
   hablaba solo de sincronizar; la medición destapó **18 enlaces publicados rotos** en 6 páginas.
   Se arreglan aquí porque publicar la wiki tal cual habría dejado el defecto en su sitio con la
   sensación de que el punto estaba cerrado.
3. **Informativo — cambia el contrato de la wiki**: pasa a ser un artefacto generado y editarla
   desde la web deja de tener efecto duradero. Documentado en `Publishing.md`.

## Required follow-up

- **Al mergear:** comprobar que el workflow corrió y que la wiki quedó con las once páginas al día.
  Es la verificación que no cabía antes.
