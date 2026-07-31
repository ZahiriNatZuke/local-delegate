# Handoff: La landing vive en el repo y se publica en GitHub Pages

## Estado actual

- SDD status: `closed`
- Último gate completado: `memory`
- Revisión: mergeado en `main` con el PR **#65** (`19a84ee`) el 2026-07-30 y publicado en la
  **0.15.0**. Verificado fresco contra el sitio publicado el **2026-07-31**.

## Qué cambió

El proyecto tiene página propia: `site/index.html`, bilingüe y autónoma, desplegada por
`.github/workflows/pages.yml` en cada push a `main` que la toque. `scripts/build_site.py`
—solo stdlib— sustituye los marcadores antes de publicar y su `--check` hace fallar el
despliegue si alguno sobrevive.

## Decisiones que no se deducen del código

1. **Se publica `site/` y no `docs/`, a propósito.** `docs/` guarda la wiki, las recipes y
   `plans/`; servir esa carpeta entera pondría todo eso en una URL pública sin que nadie lo haya
   decidido. Un directorio propio hace explícito qué se publica y qué no.

2. **El número de versión NO se escribe en la página.** Ese número ya vive en cuatro sitios
   (`pyproject.toml`, `server.json` dos veces y `uv.lock`) y el histórico dice cómo acaba: en la
   0.8.1 el lock se quedó en 0.7.0. Esta habría sido la quinta copia, y dentro del propio
   prototipo llegó a mentir con la primera release. De ahí el marcador `__LD_VERSION__` y el
   `--check` posterior al build: el modo de fallo pasa de «la página miente» a «el despliegue
   falla», que es ruidoso y se arregla.

3. **Sin recursos externos**, por la misma razón que Chart.js está vendorizado: una página que
   depende de un CDN depende de que ese CDN siga ahí y de lo que sirva.

4. **El título dice lo que hace el proyecto, no la metáfora.** Era `local-delegate — el desvío`,
   que no dice nada a quien lo ve en una pestaña o en un resultado de búsqueda; la metáfora se
   entiende leyendo la página, no antes.

## Gotchas registrados

- **`.gitignore` no admite comentarios al final de un patrón:** se los traga como parte del
  nombre. `_site/          # salida del build` no casaba con nada, y la salida generada se coló en
  un commit. El comentario va en su propia línea; se comprueba con `git check-ignore -v`.
- **`ruff` solo comprueba el bit de ejecución en Unix.** Un `EXE001` —shebang sin permiso de
  ejecución— **pasa en Windows y falla en el CI**. La convención del repo es que los scripts con
  shebang van en modo 100755.

## Deuda de proceso, dicha sin adornos

Los artefactos SDD de este cambio **se commitearon en plantilla** y se rellenaron el 2026-07-31,
después del merge. El trabajo se verificó —tests al revés incluidos— pero la especificación no lo
guió. Los gates `spec` y `plan` se aprobaron como registro fiel de lo entregado, no como
documentos previos.

## Siguiente acción

Ninguna para este cambio. La deuda viva que lo roza —**nada obliga a regenerar la captura del
README**— se ataca en su propio cambio.

## Memoria

- Nota canónica: `projects/local-delegate/jornada-2026-07-30-checks-y-el-cli-que-no-existia.md`,
  con la continuación de la landing en
  `projects/local-delegate/jornada-2026-07-30-noche-socket-y-la-0-17-0.md`.
- Índices actualizados: la memoria de proyecto de Claude Code ya apunta a esas notas.
- Sin secretos ni datos personales.
