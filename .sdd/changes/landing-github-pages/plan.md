# Plan de implementación: La landing vive en el repo y se publica en GitHub Pages

> **Reconstruido a posteriori el 2026-07-31** desde el diff mergeado del PR **#65** (`19a84ee`).
> Es el registro de lo que se hizo, no el documento que lo guió. Ver `brief.md`.

## Enfoque

Un directorio propio (`site/`) con una página autónoma, un script de build de solo stdlib que
sustituye marcadores, y un workflow de Pages que despliega y **verifica** antes de publicar.

La decisión de fondo es no dejar que la versión sea una copia más: la página trae un marcador y
nunca un número. Así, el modo de fallo posible pasa de «la página miente» a «el despliegue falla»,
que es ruidoso y se arregla.

## Tareas, en orden

1. **La página bilingüe**
   - Ficheros: `site/index.html`
   - Requisitos: REQ-001, REQ-005
   - Verificación: tests de que es un documento completo, sin recursos externos, y de que los dos
     idiomas tienen exactamente las mismas claves
   - Reversión: borrar el fichero; nada depende de él

2. **El build que sustituye la versión**
   - Ficheros: `scripts/build_site.py`
   - Requisitos: REQ-003, REQ-004
   - Verificación: el build sustituye; `--check` denuncia un marcador colado
   - Reversión: el script es autónomo y solo escribe en su directorio de salida

3. **El despliegue**
   - Ficheros: `.github/workflows/pages.yml`, `.gitignore`
   - Requisitos: REQ-002, REQ-006
   - Verificación: ejecución real del workflow sobre `main`
   - Reversión: desactivar el workflow; no toca nada del paquete

4. **Documentación**
   - Ficheros: `README.md`, `CHANGELOG.md`

## Estrategia de pruebas

- **Unitarias:** seis tests en `tests/test_site.py`, **verificados al revés** — escribiendo una
  versión a mano en la página fallan dos.
- **Extremo a extremo:** el propio workflow, sobre `main`.
- **Secretos:** la página es pública por definición y no lleva credenciales; el hook de pre-commit
  pasa.

## Migración y compatibilidad

Ninguna: es superficie nueva. No toca el paquete, ni el CLI, ni el servidor MCP, y `site/` no
viaja en el wheel.

## Revisión del plan

- [x] Cada requisito se mapea a una tarea y a una verificación.
- [x] Lo destructivo tiene salvaguarda: el despliegue **falla** antes de publicar una página con
      marcadores sin sustituir.
- [x] Dependencias explícitas: ninguna nueva; `build_site.py` es solo stdlib.
- [x] El plan no incluye trabajo ajeno.
