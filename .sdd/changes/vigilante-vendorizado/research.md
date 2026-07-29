# Research: Vigilante del vendorizado de Chart.js: integridad, CVEs y version

Fecha: 2026-07-29. Rama `feat/vigilante-vendorizado` desde `main` (`91a6499`), en worktree aparte.

## Current behavior

El dashboard sirve Chart.js **desde el propio paquete**, no desde un CDN
(`web/metrics.py:469-492`), y la razón está escrita y es buena: una herramienta local-first tiene que
funcionar sin salida a internet y sin anunciar a un tercero cada vez que abres tu panel de uso.

El blob vive en `src/local_delegate/resources/vendor/chart.umd.min.js` (205 125 bytes) junto a
`chart.js-LICENSE.md`. La versión solo consta en **un comentario** de `metrics.py:472`
(«chart.js@4.4.1»).

El backlog lo describe así: *«congelado en 4.4.1 con su hash. Dependabot no ve un blob y CodeQL no lo
audita: nada va a avisar de un CVE. Causa probable del `supplyChain` en 96. Vendorizar fue correcto;
falta el proceso que lo vigile.»*

**Dos correcciones tras mirarlo:**

1. **No hay ningún hash registrado.** Se buscó en todo el repo (`*.toml`, `*.json`, `*.cfg`, `*.txt`,
   `*.md`) y no existe. O sea que hoy no solo no se vigila el CVE: **tampoco hay forma de detectar
   que el blob cambió**.
2. **La versión está atrasada**: 4.4.1 frente a **4.5.1**, la última publicada.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `resources/vendor/` | Guarda el blob y su licencia, sin metadatos | Añadir un manifiesto con versión, origen y hash | `ls` del directorio: solo dos ficheros |
| `web/metrics.py:472` | Único sitio donde consta la versión, en un comentario | Deja de ser la fuente de verdad; pasa a serlo el manifiesto | El comentario dice 4.4.1 |
| CI | No mira el vendorizado en absoluto | Un job que compruebe integridad y CVEs | `.github/workflows/ci.yml` |
| Dependabot | Solo ve `pyproject.toml` y las actions | Sigue sin ver el blob; el vigilante cubre ese hueco | `.github/dependabot.yml` |

## La procedencia, verificada byte a byte

Comprobar el hash contra «lo que sea que haya en el CDN» no vale: hay que saber **exactamente** de
dónde salió. Descargando las dos fuentes públicas de 4.4.1:

| Fuente | SHA-256 | Bytes |
| --- | --- | --- |
| **local** | `74401d73…f8f3` | 205 125 |
| jsDelivr | `d2af8974…681e` | 205 399 |
| cdnjs | `81ffafe1…1c2f` | 200 807 |

Ninguno coincidía. La causa, encontrada comparando byte a byte: **jsDelivr antepone un banner propio
de 274 bytes** (`/** Skipped minification because the original files appears to be already
minified.`). Quitándolo:

```
jsDelivr sin banner:  205 125 bytes   sha256 74401d738dd3e03ee5dfb3b6841210fe2c4ead8a960c4011ca4ba0b78a9fd8f3
local:                205 125 bytes   sha256 74401d738dd3e03ee5dfb3b6841210fe2c4ead8a960c4011ca4ba0b78a9fd8f3
IGUALES
```

**El blob es exactamente el `dist/chart.umd.min.js` de chart.js 4.4.1 servido por jsDelivr.** cdnjs
distribuye otra minificación (200 807 bytes), así que **no** sirve como fuente de comparación.

**Consecuencia de diseño, y es una trampa real:** un vigilante que compare ingenuamente el blob local
contra la URL de jsDelivr **fallará siempre** por esos 274 bytes. Hay que registrar el hash del
contenido y documentar el banner.

## Existing conventions

- El CI ya tiene un job por preocupación (`lint`, `test`, `secrets`, `install-smoke`, validación del
  JS del dashboard), así que un job nuevo encaja sin reorganizar nada.
- **Precedente que pesa en el diseño:** el propio backlog anota que exigir `install-smoke` como check
  requerido tiene el problema de que *«depende de PyPI en vivo, así que exigirlo hace que un índice
  degradado bloquee PRs»*. Aquí pasa igual con OSV y npm.
- La política de techos recién mergeada deja la regla: **el techo se sube, no se quita**. El
  equivalente aquí es que el manifiesto se actualiza a conciencia, no se borra cuando estorba.

## Dependencies and integrations

- **OSV.dev** (`https://api.osv.dev/v1/query`) responde **sin credenciales** a una consulta por
  paquete y versión del ecosistema npm. Probado: para `chart.js` 4.4.1 devuelve **cero
  vulnerabilidades conocidas** a día de hoy. Es la pieza que hace automatizable la vigilancia de CVEs
  sin depender de un servicio autenticado.
- **registry.npmjs.org** da la última versión publicada (`4.5.1`) sin auth.
- **Socket** cubre dependencias declaradas, no blobs vendorizados, así que no aplica aquí.
- No entra ninguna dependencia nueva al paquete: el vigilante es un script de CI, no código de
  runtime.

## Risks and unknowns

**Confirmado:**

- El blob es 4.4.1 de jsDelivr, byte a byte. Procedencia establecida.
- No hay hash registrado en ninguna parte del repo.
- OSV y npm son consultables sin credenciales.
- 4.4.1 no tiene CVEs conocidos hoy.

**Decidido con el usuario antes de implementar:**

- **Rompen el CI:** un hash que no cuadra (comprobación **offline**, siempre fiable) y un CVE
  confirmado por OSV.
- **Solo avisan:** que exista una versión más nueva, y que OSV o npm no respondan. Un CI que se pone
  rojo porque alguien publicó algo, o porque un servicio ajeno está caído, acaba ignorándose.
- **No se actualiza a 4.5.1 en este cambio.** Primero el vigilante, con la versión limpia conocida;
  subir de versión será su primer encargo, aparte.

**Por resolver en la spec:**

- Formato y ubicación del manifiesto.
- Si el job corre en cada PR o también en un cron: OSV publica CVEs cuando le toca, no cuando hay
  PRs, así que un repo sin actividad no se enteraría.
