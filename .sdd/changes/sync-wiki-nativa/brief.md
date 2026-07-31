# Brief: La wiki nativa se sincroniza sola desde docs/wiki

## Problem

La wiki nativa de GitHub vive en un repositorio aparte (`local-delegate.wiki.git`) y **nada del
CI la toca**: `scripts/release.py` no la menciona y `pages.yml` publica `site/`, no `docs/`. La
fuente es `docs/wiki/` y la copia se hacía a mano.

Medido el 2026-07-31 clonando la wiki y comparando:

| | |
| --- | --- |
| Ficheros divergidos | **11 de 11** |
| Mayores diferencias | `Repo-hardening.md` 291 líneas, `Daemon.md` 154, `Integration-install.md` 142 |
| Último commit de la wiki | 2026-07-28 |
| Releases publicadas desde entonces | 0.18.0, 0.18.1, 0.19.0 |

Y un segundo defecto que la medición destapó y que el enunciado no anticipaba: **18 enlaces en 6
páginas se publican rotos**. La wiki sirve los `.md` planos y en otro repositorio, así que todo lo
que sube con `../` (`../recipes/…`, `../../README.md`, `../../src/…`) es un 404 — y no se ve roto
en el fuente, porque navegando el repo funciona perfectamente.

## Desired outcome

La wiki publicada refleja `docs/wiki/` sin que nadie tenga que acordarse, y sus enlaces resuelven.

## In scope

- Workflow que sincroniza `docs/wiki/` con la wiki nativa.
- Reescritura de los enlaces que se rompen al publicar.
- Tests que aten las dos cosas.
- Documentar el flujo nuevo en `Publishing.md`.

## Out of scope

- Reescribir el contenido de la wiki.
- Publicar `docs/recipes/` en la wiki: son otra cosa y se enlazan al repo.
- Un `_Sidebar.md` generado: la wiki no tiene páginas fuera de las once y `Home.md` ya hace de
  índice.

## Constraints and risks

- **La wiki pasa a ser un artefacto generado.** Editar una página desde la web de GitHub deja de
  tener efecto duradero. Hay que decirlo en la documentación.
- **El borrado es real:** una página que desaparezca de `docs/wiki/` desaparece de la wiki. Es lo
  correcto —si no, las huérfanas quedarían publicadas para siempre— pero es destructivo.
- El `GITHUB_TOKEN` necesita `contents: write` para empujar al repo de la wiki; no hay un permiso
  más fino para ella.

## Open questions

- Ninguna abierta. La única decisión de fondo —**disparar en push a `main` y no en el tag**— se
  resuelve en la spec.
