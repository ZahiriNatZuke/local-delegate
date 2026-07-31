# Especificación (modo lite): nada obliga a regenerar la captura del README

## La premisa, reproducida antes de planificar

Un pendiente del backlog es una hipótesis. Esta se comprobó por ejecución y **es cierta, y peor
de lo que decía**:

- `docs/wiki/Publishing.md:88` lo pide **con palabras**: «Si la versión cambia algo visible del
  dashboard, regenera la captura del README *después* del bump, porque la imagen enseña el badge
  de versión».
- **Nadie lo verifica.** Búsqueda de `dashboard.png` en todo el repo: solo lo mencionan el README
  (que la enseña), `scripts/dev/capture_dashboard.py` (que la genera) y la traza de un change
  viejo. Ni `checks.py`, ni `tests/`, ni los workflows, ni `release.py`.
- **El agujero ya se materializó:** de **25 releases publicadas, solo 5** regeneraron la captura
  en su commit de tag (v0.6.0, v0.13.0, v0.13.1, v0.15.0, v0.17.0). Caso concreto: entre la
  0.15.0 y la 0.17.0 no hubo regeneración, así que **la 0.16.0 se publicó con el badge diciendo
  `v0.15.0`**.
- Hoy la captura sí está al día: enseña `v0.17.0`, que es la versión del repo.

## Resumen

La captura del README deja de poder quedarse vieja en silencio: algo determinista falla cuando la
imagen no corresponde a la versión que declara el repositorio.

## Requisitos

- **REQ-001:** Junto a la captura vive un **manifiesto** que declara con qué versión se generó,
  más el `sha256` y el tamaño del PNG.
- **REQ-002:** El manifiesto lo escribe **`capture_dashboard.py` al capturar**, y la versión que
  registra es la que **sirvió el dashboard capturado** (leída de `/api/status`), no la que diga
  `pyproject.toml`. Así el manifiesto no puede declarar algo que la imagen no enseña.
- **REQ-003:** Una comprobación **determinista y sin red** falla si el `sha256` del PNG no cuadra
  con el manifiesto — o sea, si la imagen cambió y el manifiesto no.
- **REQ-004:** Esa misma comprobación falla si la versión del manifiesto **no es** la de
  `pyproject.toml`.
- **REQ-005:** El fallo dice **qué hacer**: el comando exacto que regenera la captura, incluido el
  arranque del dashboard que sí funciona.
- **REQ-006:** `docs/wiki/Publishing.md` deja de pedirlo solo con palabras y remite a la
  comprobación, y corrige el comando de arranque que documenta hoy, que **no funciona**.

## Escenarios de aceptación

### Escenario: alguien sube la versión y no regenera la captura

- **Dado** un repositorio cuya captura se generó con la 0.17.0
- **Cuando** se sube `pyproject.toml` a 0.18.0 y se abre el PR de release
- **Entonces** la comprobación falla y dice el comando que regenera la captura

### Escenario: alguien captura contra el daemon instalado en vez del repo

- **Dado** el repo en 0.18.0 y el daemon del 9393 sirviendo todavía la 0.17.0
- **Cuando** se regenera la captura apuntando a ese daemon
- **Entonces** el manifiesto registra `0.17.0` —que es lo que la imagen enseña de verdad— y la
  comprobación **sigue fallando**, en vez de dar por bueno un badge viejo

### Escenario: un PR normal que no toca la versión

- **Dado** un PR que no cambia `pyproject.toml` ni la captura
- **Cuando** corre el CI
- **Entonces** la comprobación pasa y no molesta

## Comportamiento en los bordes

- **Sin manifiesto**, la comprobación falla con un mensaje que explica cómo crearlo, no con un
  error de fichero ausente.
- **La comprobación no sale a la red ni necesita Playwright.** Regenerar sí lo necesita; verificar
  no. Lo que puede poner un job en rojo tiene que ser determinista, que es el criterio ya escrito
  en `check_vendor.py`.

## No funcionales

- Sin dependencias nuevas: `hashlib` y `tomllib` son stdlib.
- La captura sigue usando **datos de ejemplo deterministas**, y el pie del README que lo declara
  no se toca: es parte del trato.

## No objetivos

- **Detectar cambios de diseño del dashboard.** Exigiría hashear `metrics.py`, que cambia por
  razones que no tocan el aspecto (un KPI del servidor, un endpoint nuevo): serían falsos
  positivos constantes, y un check que se ignora es peor que no tenerlo. Queda como riesgo
  aceptado y escrito, igual que ya pasa con los PNG de marca y la `og-image`.
- Rasterizar o capturar dentro del CI.
- Tocar los datos de ejemplo del script.

## Trazabilidad

- REQ-001 · REQ-002 → `scripts/dev/capture_dashboard.py` + `docs/assets/dashboard.json`
- REQ-003 · REQ-004 · REQ-005 → test nuevo en `tests/`
- REQ-006 → `docs/wiki/Publishing.md`
