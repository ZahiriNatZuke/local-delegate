# Implementation plan: La wiki nativa se sincroniza sola desde docs/wiki

## Approach

**Un workflow que clona la wiki y un script que prepara las páginas**, separados a propósito: la
lógica que puede equivocarse —qué enlace se convierte y cuál no— vive en Python y se prueba; el
YAML solo orquesta.

Dos decisiones que no se derivan del repo:

1. **Se dispara en `push` a `main`, no en el tag.** La wiki documenta `main`. Atarla al release la
   dejaría desfasada entre versiones — el mismo problema, más lento.
2. **La conversión de enlaces se hace al publicar, no en el fuente.** `docs/wiki/` se lee sobre
   todo dentro del repo, donde lo relativo es correcto. Cambiar los fuentes a URLs absolutas
   arreglaría la wiki y empeoraría el repo; convertir al publicar deja las dos bien.

## Ordered tasks

1. **El script de preparación**
   - Ficheros: `scripts/sync_wiki.py`
   - Requisitos: REQ-003, REQ-004, REQ-005
   - Verificación: `--check` sobre el repo real enumera 18 conversiones; mutantes.
   - Rollback: borrar el script; el workflow deja de encontrarlo y falla en rojo, visible.

2. **El workflow**
   - Ficheros: `.github/workflows/wiki.yml`
   - Requisitos: REQ-001, REQ-002, REQ-006
   - Verificación: el primer push a `main` tras el merge sincroniza las once páginas.
   - Rollback: borrar el workflow; se vuelve al estado manual de hoy.

3. **Los tests**
   - Ficheros: `tests/test_wiki.py`
   - Requisitos: REQ-003 a REQ-005, REQ-007, y el `paths` de REQ-001
   - Verificación: mutantes sobre script y workflow.
   - Rollback: borrarlos.

4. **Documentación**
   - Ficheros: `docs/wiki/Publishing.md`, `CHANGELOG.md`
   - Verificación: `Publishing.md` dice que la wiki es un artefacto generado y que editarla desde
     la web no dura.

## Test strategy

- **Unit:** conversión de enlaces por casos — sale del directorio, hermana, externo, ancla, fuera
  del repo.
- **Integración:** el script corrido sobre `docs/wiki/` real, comprobando que no queda ningún `..`
  y que los enlaces internos sobreviven.
- **Estructural:** que ninguna página quede huérfana de `Home.md` (la wiki no genera índice).
- **Verificación al revés:** mutantes sobre `sync_wiki.py` **y** sobre el `paths` del workflow. Un
  workflow que no se dispara es indistinguible de no tener workflow, y hay que cazarlo.
- **Secretos:** el token va por `secrets.GITHUB_TOKEN` en la URL del clone, nunca escrito.

## Migration and compatibility

La wiki pasa a ser **generada**. Es un cambio de contrato para quien la editara desde la web:
sus cambios se sobrescriben en el siguiente push. Va documentado en `Publishing.md`.

El primer push tras el merge reescribirá las once páginas de golpe, incluidas las 18 conversiones
de enlaces. Es el resultado buscado, pero conviene saber que el primer commit de la wiki será
grande.

## Plan review

- [x] Cada requisito mapea a tarea y verificación.
- [x] La operación destructiva (`find -delete` sobre los `.md` de la wiki) está acotada al raíz y
      a `*.md`, va seguida de la copia en el mismo job, y su rollback es el historial de git de la
      propia wiki.
- [x] Dependencias explícitas: `contents: write` y el repo de la wiki. Sin dependencias de Python.
- [x] Sin trabajo ajeno: `release.py` no se toca, y las recipes quedan fuera.
