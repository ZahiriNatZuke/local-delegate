# Implementation plan: Los PNG de la marca quedan atados al favicon.svg

## Approach

**Atar por procedencia, con el patrón del manifiesto que el repo ya usa para la captura del
README.**

El pendiente decía que atarlo «de verdad» exigía rasterizar en el CI. Eso resolvería una pregunta
distinta —«¿este PNG dibuja el mismo icono?»— cuando el fallo real es más simple: **los PNG se
quedan viejos**. Un sha256 del SVG de origen lo detecta sin meter un navegador en el pipeline.

Tres decisiones:

1. **El manifiesto lo escribe el script que captura, nunca una persona.** Es la lección que
   `docs/assets/dashboard.json` ya deja escrita: uno actualizado a mano cumple el check sin que
   nadie regenere nada.
2. **Se registra también el hash de cada PNG**, no solo el del SVG. Cubre el descuido de regenerar
   siguiendo el procedimiento manual y saltarse el script: ahí el sha del SVG cuadraría.
3. **El conjunto se compara por igualdad**, para que añadir un icono y no declararlo falle.

## Ordered tasks

1. **El script de captura**
   - Ficheros: `scripts/dev/capture_icons.py`
   - Requisitos: REQ-001, REQ-005, REQ-006, REQ-007
   - Verificación: ejecutarlo y ver los tres ficheros escritos.
   - Rollback: borrarlo; el procedimiento manual del comentario sigue valiendo.

2. **Los tests**
   - Ficheros: `tests/test_site.py`
   - Requisitos: REQ-002, REQ-003, REQ-004
   - Verificación: tres mutantes, uno por descuido posible.
   - Rollback: borrar los tres tests.

3. **Regenerar y documentar**
   - Ficheros: `site/*.png`, `site/icons.json`, `site/icon.src.html`, `CHANGELOG.md`
   - El procedimiento manual del comentario se sustituye por el comando.

## Test strategy

- **Unit:** los tres tests leen ficheros reales del repo, sin doblar nada — es lo que se quiere
  comprobar.
- **Verificación al revés, un mutante por descuido:** tocar el SVG sin regenerar; tocar un PNG a
  mano; quitar un icono del manifiesto. Los tres tienen que fallar, y cada uno por su test.
- **End-to-end:** el script ejecutado de verdad contra `site/`.
- **Secretos:** no aplica; son ficheros públicos de marca.

## Migration and compatibility

Los PNG se regeneran, así que el diff los toca. **No son byte a byte los anteriores** (1669→2116 y
424→488): los originales salieron de otro navegador o versión. La marca es la misma; cambia la
codificación del PNG.

## Plan review

- [x] Cada requisito mapea a tarea y verificación.
- [x] Nada destructivo: los PNG se regeneran desde su fuente versionada, y el git de `site/` los
      recupera.
- [x] Dependencias explícitas: playwright solo para el script, y avisa si falta.
- [x] Sin trabajo ajeno: `og-image.png` queda fuera con su razón.
