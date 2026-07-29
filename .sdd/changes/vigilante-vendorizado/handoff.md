# Handoff: Vigilante del vendorizado de Chart.js: integridad, CVEs y version

## Current state

- SDD status: `implementing`. Gates `spec` y `plan` **aprobados**; `quality`, `conformance` y
  `memory` pendientes.
- Current revision: rama `feat/vigilante-vendorizado`, sacada de `main` (`91a6499`).
- **Worktree ya creado en `D:\Projects\local-delegate-vendor`** — el checkout principal
  (`D:\Projects\local-delegate`) sigue en `feat/mcp-sdk-2-fase2`, que es donde corre el daemon; no
  tocarlo. **El worktree todavía no tiene `.venv`**: hace falta `uv sync --all-extras` antes de correr
  los tests.
- **No hay una sola línea implementada.** Solo la traza SDD.

## What changed

Nada de código todavía. Lo hecho es el análisis, y ahí hay tres cosas que no conviene volver a
descubrir:

1. **El blob es auténtico, verificado byte a byte.** `chart.umd.min.js` local es exactamente el
   `dist/chart.umd.min.js` de **chart.js 4.4.1 servido por jsDelivr**:
   `sha256 = 74401d738dd3e03ee5dfb3b6841210fe2c4ead8a960c4011ca4ba0b78a9fd8f3`, 205 125 bytes.
2. **La trampa del banner.** Descargar la URL de jsDelivr y comparar el hash **da siempre distinto**:
   jsDelivr antepone 274 bytes propios (`Skipped minification because the original files appears to
   be already minified`). Hay que quitarlos antes de comparar. cdnjs **no sirve** como referencia:
   distribuye otra minificación (200 807 bytes).
3. **Dos correcciones al backlog:** no existe **ningún** hash registrado en el repo (decía que sí), y
   la versión está **dos minors atrasada** (4.4.1 frente a 4.5.1).

## Decisions

- **Rompen el CI:** hash que no cuadra (offline, determinista) y CVE confirmado por OSV.
  **Solo avisan:** que exista una versión más nueva, y que OSV o npm no respondan. Un CI que se pone
  rojo porque alguien publicó algo, o porque un servicio ajeno está caído, se acaba ignorando.
- **Workflow propio `vendor-audit.yml`, no un job en `ci.yml`.** El cron semanal en `ci.yml`
  dispararía los tests en tres sistemas cada semana para mirar un hash.
- **No se sube a 4.5.1 en este cambio.** El vigilante se estrena con una versión de estado conocido;
  actualizar será su primer encargo, aparte.
- **OSV.dev es la fuente de CVEs**: responde sin credenciales
  (`POST https://api.osv.dev/v1/query` con `{"package":{"name":"chart.js","ecosystem":"npm"},"version":"4.4.1"}`).
  Hoy devuelve cero vulnerabilidades para 4.4.1.
- **Límite declarado, no resuelto:** un aviso en un job verde no lo lee nadie — es justo por lo que
  Chart.js lleva dos minors atrasado. Se mitiga escribiendo al *summary* del job; no se construyen
  issues automáticos porque sería alcance nuevo.

## Next action

Implementar las **5 tareas del `plan.md`**, en ese orden: manifiesto `vendor.json` → script
`scripts/check_vendor.py` (solo stdlib) → workflow `vendor-audit.yml` → `tests/test_vendor.py` →
documentación en `docs/wiki/Repo-hardening.md` + `CHANGELOG.md` + el comentario de `metrics.py:472`.

El test que de verdad importa es el **inverso**: alterar una copia del blob en `tmp_path` y exigir
que el script falle. Uno que solo compruebe el camino feliz pasaría igual con un script que
devolviera `0` siempre.

## Memory

- Canonical note: pendiente — se crea al cerrar el change. El contexto de fondo está en
  `projects/local-delegate/backlog.md` (entrada de Chart.js) y en
  `projects/local-delegate/techos-major-dependencias.md`, que declara explícitamente que la política
  de techos **no** cubre el vendorizado: este cambio es el que cierra ese hueco.
- Indexes updated: todavía no.
