# Handoff: nada obliga a regenerar la captura del README

## Estado actual

- SDD status: `closed`
- Último gate completado: `memory`
- Revisión: rama `feat/vigilante-captura-readme` sobre `main` en `6d78ffc`.

## Qué cambió

Junto a la captura del README vive ahora `docs/assets/dashboard.json`, que declara con qué versión
se generó la imagen y su hash. `tests/test_captura.py` compara esa versión con `pyproject.toml` y
ese hash con el PNG real, así que una captura vieja deja de pasar en silencio. La wiki deja de
pedirlo solo con palabras y corrige el comando de arranque que documentaba, que no funciona.

## Decisiones que no se deducen del código

1. **Escribe el manifiesto quien captura, nunca quien sube la versión.** Si `bump_version.py` lo
   actualizara, el check se cumpliría en la letra sin que nadie regenerara nada — se cambiaría un
   agujero por un teatro.

2. **La versión que se registra es la que sirvió el dashboard capturado (`/api/status`), no la de
   `pyproject.toml`.** Esto convierte un aviso escrito en una comprobación: capturar contra el
   daemon instalado en vez de contra el repo produce un manifiesto con la versión vieja —que es
   la que la imagen enseña de verdad— y el test **sigue fallando**, en lugar de dar por bueno un
   badge que miente.

3. **Verificar es un test, no un script con workflow propio.** El precedente `check_vendor.py`
   necesita red (OSV, npm) y por eso tiene su maquinaria; esto es `hashlib` + `tomllib`, offline y
   determinista. Menos superficie.

4. **No se vigila el diseño del dashboard, a propósito.** Exigiría hashear `web/metrics.py`, que
   se toca por razones que no afectan al aspecto: serían falsos positivos constantes, y un check
   que grita en falso acaba ignorado. Riesgo aceptado y escrito, igual que los PNG de marca y la
   `og-image`.

5. **`-text` explícito para el PNG en `.gitattributes`**, aunque git ya detecte binarios por
   heurística. El hash de un fichero versionado es exactamente lo que reventó una vez aquí con
   `core.autocrlf` en el runner de Windows, en verde en Ubuntu y macOS. Una línea contra un fallo
   que solo aparecería en un sistema.

## El dato que justifica el cambio

De **25 releases publicadas, solo 5** regeneraron la captura en su commit de tag. La **0.16.0 se
publicó con el badge del header diciendo `v0.15.0`**.

## Lo que hay que ejecutar, no solo recordar

**El PR que suba la versión a 0.18.0 fallará hasta que se regenere la captura.** Es el
comportamiento buscado. El procedimiento está en `docs/wiki/Publishing.md` y en el docstring del
script; en resumen: montar `metrics.app` con uvicorn en el 9494 (el daemon del 9393 no sirve, y
`local-delegate serve --port` tampoco) y capturar contra esa URL.

## Siguiente acción

Publicar la 0.18.0, incluyendo la regeneración de la captura.

## Memoria

- Nota canónica: pendiente de escribir en el vault con la jornada del 2026-07-31.
- Índices actualizados: el punto queda cerrado en `projects/local-delegate/backlog.md`.
- Sin secretos ni datos personales: el manifiesto solo lleva un hash, un número de versión y un
  tamaño en bytes.
