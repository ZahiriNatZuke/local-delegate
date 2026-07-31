# Plan de implementación (modo lite): vigilante de la captura del README

## Enfoque

El mismo patrón que ya usa el repo para el vendorizado: **un manifiesto es la fuente de verdad, y
algo determinista lo compara**. Aquí el manifiesto declara con qué versión se generó la captura,
y un test compara esa versión con `pyproject.toml` y el hash con el PNG real.

Dos decisiones sostienen el diseño:

1. **Quien escribe el manifiesto es el script que captura, no el que sube la versión.** Si
   `bump_version.py` actualizara el manifiesto, el check pasaría sin que nadie regenerara nada —
   se cumpliría la letra y no el propósito. Escribiéndolo al capturar, el manifiesto declara lo
   que la imagen enseña.

2. **La versión se lee de `/api/status` del dashboard que se está capturando**, no de
   `pyproject.toml`. Así, capturar contra el daemon instalado —el gotcha que hoy solo está escrito
   como aviso— produce un manifiesto con la versión vieja y **el check sigue fallando**, en vez de
   dar por bueno un badge que miente.

Verificar es barato y offline (`hashlib` + `tomllib`); regenerar necesita Playwright, que no es
dependencia del proyecto. Por eso la comprobación es un **test**, no un script con workflow
propio: no necesita red, así que no hace falta la maquinaria de `check_vendor.py`.

## Tareas, en orden

1. **`capture_dashboard.py` escribe el manifiesto**
   - Ficheros: `scripts/dev/capture_dashboard.py`
   - Requisitos: REQ-001, REQ-002
   - Verificación: ejecución real regenerando la captura, y comprobar que el manifiesto registra
     la versión que sirvió el dashboard capturado
   - Reversión: dejar de escribirlo; el PNG se genera igual

2. **El manifiesto inicial**
   - Ficheros: `docs/assets/dashboard.json`
   - Requisitos: REQ-001
   - Verificación: su `sha256` cuadra con el PNG que hay hoy en el repo, y su versión es `0.17.0`,
     que es la que el badge enseña
   - Reversión: borrar el fichero

3. **El test que vigila**
   - Ficheros: `tests/test_captura.py` (nuevo)
   - Requisitos: REQ-003, REQ-004, REQ-005
   - Verificación: **al revés** — con el manifiesto declarando otra versión debe fallar, y con el
     PNG alterado un solo byte también. Si no falla, el test sobra.
   - Reversión: borrar el test

4. **La documentación deja de pedirlo solo con palabras**
   - Ficheros: `docs/wiki/Publishing.md`, `CHANGELOG.md`
   - Requisitos: REQ-006
   - Verificación: el comando documentado se ejecuta y funciona (probado: uvicorn sobre
     `metrics.app` en otro puerto responde 200; el actual **no arranca** con el daemon en el 9393
     y no acepta puerto)

   > **Corrección durante la implementación:** al aprobar la spec quedó escrito que ese comando
   > «sale con exit 0, así que parece que arrancó». **Es falso**: sale con **exit 3**. El `0` que
   > vi era el de `head` al otro lado de una tubería. El motivo de REQ-006 se sostiene igual —no
   > arranca y no acepta puerto— pero el detalle del exit code no era cierto y no debe repetirse.

5. **Blindar el PNG contra la conversión de fin de línea** *(hallazgo de la revisión del plan)*
   - Ficheros: `.gitattributes`
   - Requisitos: REQ-003
   - Verificación: `git check-attr -a` sobre la captura declara `-text`
   - Reversión: quitar la línea

## Hallazgos de la revisión adversarial del plan

Dos, los dos incorporados arriba antes de implementar:

1. **El hash de un fichero versionado es exactamente lo que ya reventó una vez en este repo.**
   `.gitattributes` lleva un comentario largo explicando que un clon en Windows con
   `core.autocrlf=true` —el valor por defecto de Git for Windows **y el del runner
   `windows-latest`**— convirtió los LF del blob vendorizado en CRLF y tumbó su comprobación de
   hash, en verde en Ubuntu y macOS. Comprobado aquí que hoy el PNG **no** está afectado (el hash
   del blob y el del disco coinciden, y git detecta binarios por heurística), pero la comprobación
   nueva se apoya en un hash y el precedente es demasiado caro para confiarlo a una heurística:
   se declara `-text` explícitamente. Cuesta una línea y elimina un fallo que solo habría
   aparecido en el CI de Windows.

2. **El borde de «no se pudo leer la versión» no estaba cubierto.** Si `/api/status` no responde
   o no trae `version`, el script **no debe escribir un manifiesto con un valor vacío** —eso sería
   un manifiesto que miente, que es justo lo que este cambio persigue—: tiene que fallar diciendo
   qué pasó y no tocar el manifiesto existente.

## Estrategia de pruebas

- **Unitarias:** el test nuevo, verificado al revés en sus dos ramas (versión e integridad).
- **Por ejecución:** regenerar la captura de verdad y comprobar el manifiesto resultante.
- **Los cuatro pasos del CI** antes del push.
- **Secretos:** ninguno; la captura usa datos de ejemplo deterministas y eso no se toca.

## Migración y compatibilidad

Ninguna migración. El manifiesto nace con el estado actual, que ya está al día (`v0.17.0`).

**Riesgo de despliegue, y es el que hay que tener presente:** en cuanto exista el test, el PR que
suba la versión a 0.18.0 **fallará** hasta que se regenere la captura. Es el comportamiento
buscado, no un efecto colateral — pero significa que **publicar la 0.18.0 pasa a incluir
regenerar la captura**, y así hay que ejecutarlo.

## Revisión del plan

- [x] Cada requisito se mapea a una tarea y a una verificación.
- [x] Nada destructivo: solo se añade un fichero, un test y unas líneas al script.
- [x] Dependencias explícitas: **ninguna nueva**. Verificar es stdlib; regenerar ya requería
      Playwright y lo sigue requiriendo.
- [x] El plan no incluye trabajo ajeno. La corrección del comando de `Publishing.md` entra porque
      REQ-005 exige dar un comando que funcione, y el documentado no funciona.
