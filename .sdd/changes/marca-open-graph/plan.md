# Plan de implementación: Marca única y metadatos sociales en la landing

> **Reconstruido a posteriori el 2026-07-31** desde el diff mergeado del PR **#67** (`fcf462b`).
> Es el registro de lo que se hizo, no el documento que lo guió. Ver `brief.md`.

## Enfoque

Un icono, un fichero, y un test que ata las copias byte a byte. Es el mismo criterio que el repo
ya aplicó al `rev` de ruff y al catálogo de tools: donde hay dos copias del mismo dato, o se
elimina una o algo tiene que impedir que se separen. Aquí no se puede eliminar —el dashboard sirve
desde el paquete y la landing desde GitHub Pages, que son dos despliegues distintos—, así que se
ata.

Para la imagen social, versionar el **generador** en vez del artefacto: un PNG no se revisa en un
diff, un HTML sí.

## Tareas, en orden

1. **El icono canónico y sus dos consumidores**
   - Ficheros: `src/local_delegate/resources/brand/favicon.svg`, `site/favicon.svg`,
     `src/local_delegate/web/metrics.py`
   - Requisitos: REQ-001, REQ-002, REQ-003
   - Verificación: test que compara los dos ficheros byte a byte; comprobación de que el recurso
     viaja en el wheel
   - Reversión: el dashboard vuelve al SVG inline

2. **Los metadatos sociales**
   - Ficheros: `site/index.html`
   - Requisitos: REQ-004
   - Verificación: tests por etiqueta
   - Reversión: quitar las etiquetas; la página sigue siendo válida

3. **La imagen social y su fuente revisable**
   - Ficheros: `site/og-image.src.html`, `site/og-image.png`, `scripts/build_site.py`
   - Requisitos: REQ-005, REQ-006, REQ-007
   - Verificación: un test lee la **cabecera del PNG** y comprueba que mide lo que declaran los
     metadatos
   - Reversión: quitar la imagen y su declaración

4. **El amarillo del titular**
   - Ficheros: `site/index.html`
   - Requisitos: REQ-008
   - Verificación: un test ata las dos mitades —que la regla del resalte no mencione `--local` y
     que el `span` cubra solo «la nube», en los dos idiomas
   - Reversión: tres líneas de CSS

## Estrategia de pruebas

- **Unitarias:** `tests/test_site.py`, ampliado en 140 líneas. **Verificados al revés**: con el
  CSS viejo falla el primer assert del titular, con el titular viejo falla el segundo.
- **Extremo a extremo:** el despliegue de Pages y la carga real de la página.
- **Secretos:** ninguno en juego; el hook de pre-commit pasa.

## Migración y compatibilidad

El dashboard pasa de un SVG inline a leer un recurso del paquete. Hay que comprobar que el fichero
**viaja en el wheel**, o el panel se quedaría sin icono en una instalación real. Se comprobó.

## Revisión del plan

- [x] Cada requisito se mapea a una tarea y a una verificación.
- [x] El riesgo real —dos copias del icono que se separan— tiene salvaguarda: el test byte a byte.
- [x] Dependencias explícitas: ninguna nueva.
- [x] El plan no incluye trabajo ajeno. La corrección del amarillo entra porque es la misma
      decisión de marca, y así queda dicho.
