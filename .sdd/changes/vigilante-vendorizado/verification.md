# Verification: Vigilante del vendorizado de Chart.js: integridad, CVEs y version

## Environment

- Revision: rama `feat/vigilante-vendorizado`, commits `f9205f9` y `6bc414c`. **PR #39** contra
  `main`. Worktree `D:\Projects\local-delegate-vendor`.
- Relevant runtime and tool versions: Python 3.11 (`.venv` del worktree), ruff y pytest del grupo
  `dev`, Node 20 para `node --check`. En el CI: runners `ubuntu-latest`, `macos-latest` y
  `windows-latest`.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | Manifiesto con nombre, versión, ecosistema, origen, licencia, SHA-256 y bytes; y que deje de haber dos fuentes de la versión | OK | `resources/vendor/vendor.json`; `metrics.py` ya no anota el número y remite al manifiesto |
| REQ-002 | Alterar un byte de una copia del blob y exigir fallo, sin red | OK | `test_blob_alterado_falla` → exit 1. A mano sobre una copia: exit 1 con esperado, real y bytes |
| REQ-003 | Consulta a OSV.dev y fallo si hay vulnerabilidades | OK | `test_vulnerabilidad_confirmada_falla` → exit 2. Ejecución real: OSV da **cero** para `chart.js` 4.4.1 |
| REQ-004 | Consulta a npm; aviso **sin** fallar si hay versión más nueva | OK | En local y en el runner: `AVISO: chart.js vendorizado en 4.4.1, publicado 4.5.1`, job en verde. `test_version_nueva_avisa_sin_fallar` |
| REQ-005 | Red caída y respuesta ininteligible: aviso y exit 0 | OK | `test_osv_caido_no_falla`, `test_npm_caido_no_falla`, `test_osv_malformado_no_falla` |
| REQ-006 | La trampa del banner de jsDelivr, escrita donde se va a leer | OK | Bloque `_procedencia` del manifiesto (274 bytes, hash con banner, por qué cdnjs no sirve). `test_el_manifiesto_declara_la_trampa_del_banner` |
| REQ-007 | Disparadores de PR/push **y** cron semanal | OK | `.github/workflows/vendor-audit.yml` (`push`/`pull_request` a `main` + `cron: "41 6 * * 1"`). El job `audit` corrió en el PR en 4 s |
| REQ-008 | Documentación con qué falla, qué avisa y el procedimiento de actualización | OK | Sección nueva de `docs/wiki/Repo-hardening.md`, con las dos tablas y los pasos (incluido quitar el banner antes de hashear) |

Casos límite de la spec:

| Caso | Exigido | Evidencia |
| --- | --- | --- |
| Fichero vendorizado ausente | falla | `test_blob_ausente_falla` |
| Manifiesto y directorio desincronizados | falla | `test_fichero_sin_declarar_falla` |
| Respuesta de OSV malformada | avisa, no falla | `test_osv_malformado_no_falla` |

No funcionales: **sin dependencias nuevas** (solo `argparse`, `hashlib`, `json`, `os`, `sys`,
`urllib`, `pathlib`; `pyproject.toml` intacto), **rápido** (4-5 s el job) y **determinista offline**
(lo que puede fallar el CI no toca la red).

No-goals respetados: Chart.js sigue en **4.4.1**, el vendorizado no se retira, no se vendoriza nada
más y el job **no** se añade como check requerido en `setup_repo_security.sh`.

## Quality checks

- [x] Project-native tests pass. `pytest -q`: **256 pasan** (22 nuevos), en local y en los tres
      sistemas del CI.
- [x] Lint, formatting, type checking, and build checks pass where applicable. `ruff check .`,
      `ruff format --check .` y `extract_dashboard_js.py` + `node --check`, en local y en el job
      `lint`. `install-smoke` en verde.
- [x] Secret scanning passes. `gitleaks` del pre-commit, el job `secrets`, GitGuardian y los dos
      checks de Socket.
- [x] No unrelated changes are present. Ocho ficheros, todos del cambio; nada en el camino de
      ejecución del paquete salvo un comentario de `metrics.py`.

**Los 12 checks del PR #39 en verde**, incluido `test (windows-latest)`.

## Deviations and residual risk

- **Desviación respecto al plan, a favor: `.gitattributes`.** No estaba previsto. Lo obligó el CI de
  Windows: con `core.autocrlf=true` git convertía los LF del blob en CRLF al hacer checkout
  (205 139 bytes en vez de 205 125) y el hash no cuadraba sin que nadie lo tocara. Sin él el
  vigilante no funciona en ningún clon de Windows y un wheel construido allí llevaría un JavaScript
  distinto del publicado. Detalle completo en **F7** de `plan-review.md`.
- **Límite conocido, declarado y no resuelto:** un aviso dentro de un job verde no lo lee nadie. Se
  mitiga escribiendo el informe al summary del job; no se crean issues automáticos porque sería
  alcance nuevo. Es el mismo mecanismo por el que Chart.js llegó a estar dos minors atrasado, así
  que **el aviso de 4.5.1 hay que atenderlo**, no dejarlo correr.
- **El vigilante no revalida la procedencia en cada corrida** (F5): compara contra el manifiesto,
  no contra jsDelivr. Es deliberado —comparar contra la red no sería determinista y chocaría con el
  banner—; la procedencia se verifica al actualizar la versión, y ese procedimiento está
  documentado.
- **Los tests no salen a la red**: se prueba la lógica de decisión, no OSV ni npm. La parte real se
  verificó por ejecución, en local y en el runner.
