# Implementation plan: Sube el Chart.js vendorizado a 4.5.1

## Approach

**Seguir el procedimiento ya documentado en `docs/wiki/Repo-hardening.md`** y corregirlo donde
falle: se escribió al crear el vigilante, de memoria, y esta es la primera vez que se ejecuta.

La única decisión de diseño es de dónde bajar la copia. El procedimiento decía «de jsDelivr», que es
de donde salió la 4.4.1. Se cambia a **el tarball oficial de npm**: un CDN puede transformar lo que
sirve —el banner de 274 bytes de jsDelivr es la prueba— y el tarball es la fuente canónica. jsDelivr
se usa como **segunda** fuente para confirmar, no como origen.

## Ordered tasks

1. **Bajar y verificar la procedencia**
   - Files or modules: ninguno todavía (trabajo en un directorio temporal)
   - Requirements covered: procedencia verificada, sin CVEs, licencia revisada
   - Verification: hash del tarball de npm **igual** al de jsDelivr; OSV sin vulnerabilidades para
     4.5.1; diff de la licencia
   - Rollback or recovery: no toca el repo

2. **Sustituir el vendorizado y actualizar el manifiesto**
   - Files or modules: `resources/vendor/chart.umd.min.js`, `chart.js-LICENSE.md`, `vendor.json`
   - Requirements covered: el vendorizado en 4.5.1 y declarado
   - Verification: `python scripts/check_vendor.py` sale **verde y sin avisos**
   - Rollback or recovery: `git checkout -- src/local_delegate/resources/vendor/`

3. **Comprobar el dashboard a ojo, antes y después**
   - Files or modules: ninguno
   - Requirements covered: sin regresión visual
   - Verification: mismas instancias de Chart, mismos canvas pintados, cero errores de consola, y
     captura de las dos versiones
   - Rollback or recovery: n/a

4. **Corregir lo que la subida destape**
   - Files or modules: lo que falle
   - Requirements covered: que la próxima subida no repita el trabajo
   - Verification: la suite en verde
   - Rollback or recovery: revertir

5. **Documentación**
   - Files or modules: `docs/wiki/Repo-hardening.md`, `CHANGELOG.md`
   - Requirements covered: el procedimiento corregido con lo aprendido al ejecutarlo
   - Verification: el documento describe lo que de verdad se hizo
   - Rollback or recovery: revertir

## Test strategy

- **Unit:** la suite del proyecto. Los tests del vigilante deben seguir verdes con la versión nueva
  — si alguno falla por el número, es que clavaba la versión y hay que arreglarlo de raíz.
- **Integration:** `scripts/check_vendor.py` contra OSV y npm de verdad. Tiene que decir «está al
  día» y **no** avisar de nada: ese es el criterio de éxito del cambio.
- **End-to-end o manual:** **imprescindible aquí**, no opcional. Los tests solo comprueban que el
  fichero se sirve; que Chart.js pinte igual tras un minor no lo ve ningún test del proyecto. Hay
  que levantar el dashboard con datos y mirarlo antes y después.
- **Security and secret scanning:** `gitleaks` del pre-commit. Sin dependencias declaradas nuevas,
  así que no hay depscore que rehacer; la vigilancia del blob la hace el propio `check_vendor.py`.

## Migration and compatibility

- **Cambia un asset del dashboard, nada más.** Ninguna API, ninguna dependencia, ningún dato.
- **Sin efecto sobre quien ya tiene instalado el paquete** hasta que se publique una versión.
- Quien actualice y tenga el dashboard abierto seguirá viendo el JS viejo hasta **24 h** por el
  `Cache-Control` del endpoint. Inofensivo, pero conviene que esté escrito.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback. El único riesgo real —regresión
      visual— tiene su tarea propia, con línea base **antes** de tocar nada.
- [x] Dependencies and configuration changes are explicit. Ninguna.
- [x] The plan does not include unrelated work. La tarea 4 solo cubre lo que rompa la subida.

**Revisión, con su límite declarado:** la hace el mismo agente que escribió el plan, sin subagentes.
El riesgo que sí se cazó revisando es el que gobierna el plan: *un cambio de versión de una librería
de gráficos no lo cubre ningún test de este repo*, así que la comprobación visual pasa de «conviene»
a tarea con su propio paso, y con línea base previa — sin ella, un fallo no se puede atribuir.
