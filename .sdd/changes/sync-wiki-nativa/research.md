# Research: La wiki nativa se sincroniza sola desde docs/wiki

## Current behavior

- `scripts/release.py` **no menciona la wiki** ni una vez. Cierra los otros dos flecos del release
  (la Release con notas y artefactos, y el tag).
- `.github/workflows/pages.yml:3-13` publica `site/` y lo dice explícitamente: *«La landing se
  publica desde `site/`, no desde `docs/`»*.
- Ningún test la cubre: un grep de «wiki» en `tests/test_site.py` no devuelve nada.
- `gh api repos/… --jq .has_wiki` → `true`, y el clone de `local-delegate.wiki.git` trae las once
  páginas con último commit del **2026-07-28**.
- Los enlaces de la wiki publicada están **sin transformar** respecto al fuente: la copia manual
  era un `cp`. Por eso los `../` viajan tal cual y quedan rotos.

## Impact map

| Área | Responsabilidad actual | Impacto esperado | Evidencia |
| --- | --- | --- | --- |
| `.github/workflows/wiki.yml` | — (nuevo) | Sincroniza en push a `main` | — |
| `scripts/sync_wiki.py` | — (nuevo) | Copia y reescribe enlaces | — |
| `tests/test_wiki.py` | — (nuevo) | Ata workflow, conversión e índice | — |
| `docs/wiki/Publishing.md` | Documenta el release | Pasa a decir que la wiki es generada | `Publishing.md:122-123` |
| `docs/wiki/*.md` | Fuente de la wiki | **Sin cambios**: siguen relativos | — |
| `scripts/release.py` | Publica la release | **Sin cambios**: la wiki ya no depende del tag | `release.py` completo |

## Existing conventions

- **Los scripts de CI son solo stdlib** y se ejecutan con `uv run --no-project`, para no instalar
  el proyecto. `pages.yml:36-38` lo dice: *«Sin `uv sync`: el script es solo stdlib a propósito,
  igual que check_vendor.py»*.
- **Los workflows explican su porqué en comentarios**, incluido lo que deliberadamente NO hacen
  (`pages.yml:3-5`, `codeql`/`ci_gate`).
- **Permisos mínimos y `concurrency` explícita** con su razón (`pages.yml:16-23`).
- **Los tests de scripts cargan el módulo por ruta**, porque `scripts/` no se empaqueta ni está en
  el path de import.

## Dependencies and integrations

- El repositorio `local-delegate.wiki.git`, que existe y tiene contenido.
- `GITHUB_TOKEN` con `contents: write`: es el permiso que gobierna la wiki, y no hay uno más fino.
- Nada más: el script es stdlib pura.

## Risks and unknowns

- **Confirmado por ejecución:** las once páginas divergen; 18 enlaces se romperían al publicar; la
  conversión propuesta los arregla los 18 y conserva los 18 enlaces internos.
- **Confirmado:** los enlaces `.md` entre páginas hermanas funcionan tal cual en la wiki (así están
  hoy en la publicada, y resuelven).
- **No verificable hasta el merge:** que el `GITHUB_TOKEN` empuje a la wiki sin más configuración.
  Es el comportamiento documentado de GitHub, pero **no está medido en este repo**. Si fallara, el
  job saldría en rojo con el error del `git push`, que es un fallo visible y no silencioso.
