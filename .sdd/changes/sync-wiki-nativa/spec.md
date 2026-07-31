# Specification: La wiki nativa se sincroniza sola desde docs/wiki

## Summary

Un workflow publica `docs/wiki/` en la wiki nativa en cada push a `main` que la cambie,
reescribiendo por el camino los enlaces que no resolverían una vez publicados.

**Decisión de fondo: se dispara en `push` a `main`, no en el tag del release.** La wiki documenta
lo que está en `main`; atarla al release la dejaría desfasada entre versión y versión, que es una
forma más lenta del mismo problema que este change viene a arreglar.

## Requirements

- **REQ-001:** Un push a `main` que cambie `docs/wiki/**` publica esas páginas en la wiki nativa.
- **REQ-002:** Una página borrada de `docs/wiki/` desaparece de la wiki.
- **REQ-003:** Los enlaces que salen de `docs/wiki/` se publican como URLs absolutas del repo.
- **REQ-004:** Los enlaces entre páginas hermanas se publican **relativos**, sin tocar.
- **REQ-005:** La conversión conserva el ancla (`#seccion`).
- **REQ-006:** Un push sin diferencias reales no crea commit ni falla el job.
- **REQ-007:** Toda página de `docs/wiki/` es alcanzable desde `Home.md`.

## Acceptance scenarios

### Scenario: la wiki se pone al día sola

- **Given** un cambio en `docs/wiki/Daemon.md` mergeado a `main`
- **When** termina el workflow
- **Then** la página publicada coincide con la fuente, con los enlaces convertidos

### Scenario: un enlace al repo resuelve desde la wiki

- **Given** `Home.md` con `[README](../../README.md)`
- **When** se publica
- **Then** el enlace apunta a `https://github.com/…/blob/main/README.md`

### Scenario: la navegación interna se conserva

- **Given** una página con `[Daemon](Daemon.md)`
- **When** se publica
- **Then** el enlace sigue siendo `Daemon.md`, y el lector no sale de la wiki

## Edge cases and failure behavior

- **Enlace que sale del repo** (`../../../fuera.md`): se deja como está. Ya está roto en el
  fuente, y convertirlo produciría una URL de GitHub bien formada apuntando a nada — más difícil
  de detectar en una revisión que el enlace roto original.
- **URLs externas, anclas puras y `mailto:`**: intactas.
- **Sin diferencias**: el job informa y no empuja. `git diff --quiet` sale 1 cuando **sí** hay
  cambios, así que sin el condicional un push vacío pintaría el historial de rojos que no son
  fallos.

## Non-functional requirements

- **Sin dependencias**: el script es solo stdlib, como `build_site.py` y `check_vendor.py`, así que
  el workflow no instala el proyecto.
- **Permisos mínimos**: `contents: write`, el único que permite empujar a la wiki.
- **Concurrencia**: una sincronización a la vez, sin cancelar la que corre — dejar la wiki a medias
  es peor que esperar.

## Non-goals

- Publicar `docs/recipes/` como páginas de la wiki.
- Generar un `_Sidebar.md`.
- Convertir los enlaces en los ficheros fuente: `docs/wiki/` se lee dentro del repo, donde lo
  relativo es lo correcto.

## Traceability

| Requisito | Trabajo | Evidencia |
| --- | --- | --- |
| REQ-001 | `wiki.yml` | `test_el_workflow_se_dispara_con_los_cambios_de_la_wiki` + mutante |
| REQ-002 | `wiki.yml` (`find -delete`) | revisión del workflow |
| REQ-003 | `sync_wiki.py` | `test_lo_que_sale_del_directorio_se_convierte_*` + mutante |
| REQ-004 | `sync_wiki.py` | `test_los_enlaces_entre_paginas_NO_se_convierten` + mutante |
| REQ-005 | `sync_wiki.py` | `test_la_conversion_conserva_el_ancla` + mutante |
| REQ-006 | `wiki.yml` | revisión del workflow |
| REQ-007 | — | `test_ninguna_pagina_queda_huerfana_del_indice` |
