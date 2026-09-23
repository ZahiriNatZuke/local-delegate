# Handoff — resumen-por-secciones

Estado 2026-09-23: implementado, medido y **retirado por el criterio escrito antes de medir**. Rama
`feat/resumen-por-secciones` (último commit `6bcb4c2`), sin PR.

- **Se queda:** `local_summarize(focus=...)`; los campos `secciones`/`focus` del log; el aviso y el
  registro de `length` cuando un trozo de map-reduce se corta (antes, `stop` en silencio).
- **Apagado por defecto:** el resumen por secciones (`LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO=1`), con
  su código y sus tests. Etapa 1: 100 % de títulos (con introducción y subsecciones). Etapa 2
  (`claude -p`): v2 3/9, v3 1/9; Claude relee 6/9 **para comprobar**, no por lo que falta.
- **Siguiente palanca (backlog 0b):** citas literales con su número de línea, para que Claude pueda
  comprobar sin releer. El banco está listo: `scripts/experimento_adopcion.py --piloto --variantes
  v0 --repeticiones 3 --fuentes benchmarks/resumen-estructurado/fuentes`, y la etapa gratis con
  `scripts/medir_resumen_estructurado.py`.
- **Para medir:** el 26B ocupa ~11,7 GB de RAM; lanzar como proceso independiente y cerrar apps
  pesadas, o Claude Code mata el comando.

Detalle: `verification.md`. Vault: `projects/local-delegate/jornada-2026-09-23-la-confianza-y-no-la-cobertura.md`.
