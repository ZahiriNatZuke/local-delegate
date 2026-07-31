# Handoff: La wiki nativa se sincroniza sola desde docs/wiki

## Current state

- Estado SDD: `verifying` → cierra con el CI del PR y la comprobación posterior al merge.
- Último gate aprobado: `quality`.
- Base `9c6cb47`; rama `feat/sync-wiki-nativa`.

## What changed

- `.github/workflows/wiki.yml` (nuevo): sincroniza en push a `main` con cambios en `docs/wiki/**`.
- `scripts/sync_wiki.py` (nuevo): copia y reescribe los enlaces que se romperían al publicar.
- `tests/test_wiki.py` (nuevo): conversión, índice y `paths` del workflow.
- `docs/wiki/Publishing.md`, `CHANGELOG.md`.

## Decisions

- **Push a `main`, no el tag.** La wiki documenta `main`; atarla al release la dejaría desfasada
  entre versiones.
- **Los enlaces se convierten al publicar, no en el fuente.** `docs/wiki/` se lee dentro del repo,
  donde lo relativo es lo correcto. Convertir en el fuente arreglaría la wiki y empeoraría el repo.
- **Los enlaces entre páginas hermanas NO se convierten.** Funcionaría, pero sacaría al lector de
  la wiki en cada clic. Es el error simétrico y sale gratis cometerlo si la regla se escribe como
  «convierte todos los enlaces».
- **Un enlace que sale del repo se deja roto.** Convertirlo daría una URL de GitHub bien formada
  apuntando a nada: más difícil de detectar en una revisión que el enlace roto original.
- **La wiki pasa a ser un artefacto generado.** Editarla desde la web no dura.

## Next action

Tras el merge, comprobar que el workflow corrió y que la wiki tiene las once páginas al día. Es la
única parte que no se pudo verificar antes.

## Memory

- Nota canónica: `projects/local-delegate/backlog.md` (borrar el punto al cerrar).
- Índices actualizados: al cierre de la sesión.
