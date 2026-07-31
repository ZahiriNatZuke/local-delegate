# Handoff: Los PNG de la marca quedan atados al favicon.svg

## Current state

- Estado SDD: `verifying` → cierra con el CI del PR.
- Último gate aprobado: `quality`.
- Rama `feat/iconos-atados-al-svg`.

## What changed

- `scripts/dev/capture_icons.py` (nuevo): regenera los dos PNG y escribe el manifiesto.
- `site/icons.json` (nuevo): sha256 del SVG de origen + sha, bytes y lado de cada PNG.
- `tests/test_site.py`: tres tests de procedencia.
- `site/apple-touch-icon.png`, `site/favicon-32x32.png`: regenerados.
- `site/icon.src.html`: el procedimiento manual pasa a ser un comando.
- `CHANGELOG.md`.

## Decisions

- **Se ata por procedencia, no rasterizando en el CI.** El pendiente daba lo segundo por
  necesario; resolvería «¿este PNG dibuja el mismo icono?» cuando el fallo real es «los PNG se
  quedaron viejos», que un hash del SVG detecta sin meter un navegador en el pipeline.
- **El manifiesto lo escribe el script, nunca una persona.** Mismo razonamiento que
  `docs/assets/dashboard.json`: uno actualizado a mano cumpliría el check sin regenerar nada.
- **Se registra también el hash de cada PNG**, no solo el del SVG, para cubrir el caso de
  regenerar siguiendo el procedimiento manual y saltarse el script. Hay un mutante que lo prueba.
- **`og-image.png` queda fuera**: no sale del SVG y ya tiene su propio par fuente/test.

## Next action

Merge. Con esto el backlog auditado queda cerrado; después, la 0.20.0.

## Memory

- Nota canónica: `projects/local-delegate/backlog.md` (borrar el punto al cerrar).
- Índices actualizados: al cierre de la sesión.
