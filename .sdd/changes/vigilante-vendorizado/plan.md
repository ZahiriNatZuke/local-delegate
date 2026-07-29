# Implementation plan: Vigilante del vendorizado de Chart.js: integridad, CVEs y version

## Approach

**Un manifiesto declarativo + un script de stdlib + un workflow propio.** Nada de esto entra en el
camino de ejecución del paquete: el vigilante es herramienta de CI.

El reparto de responsabilidades sale del criterio ya decidido — *lo que puede fallar el CI tiene que
ser determinista*:

- **Integridad (hash):** offline, sin red, siempre fiable → **puede fallar el CI**.
- **CVE (OSV):** red, pero un CVE confirmado es un problema real → **puede fallar el CI**.
- **Versión nueva (npm) y servicios caídos:** → **solo avisan**.

**Workflow propio (`vendor-audit.yml`), no un job dentro de `ci.yml`.** Meter el `schedule` en
`ci.yml` haría correr **todo** el CI —tests en tres sistemas incluidos— cada semana solo para mirar
un fichero. Un workflow aparte cuesta segundos y deja `ci.yml` intacto. `codeql.yml` ya sienta el
precedente de un workflow con su propio cron.

## Ordered tasks

1. **Manifiesto del vendorizado**
   - Files or modules: `src/local_delegate/resources/vendor/vendor.json` (nuevo)
   - Requirements covered: REQ-001, REQ-006
   - Verification: contiene nombre, versión, ecosistema, URL de origen, licencia y el SHA-256 real
     (`74401d738dd3e03ee5dfb3b6841210fe2c4ead8a960c4011ca4ba0b78a9fd8f3`), más la nota del banner de
     jsDelivr
   - Rollback or recovery: borrar el fichero
   - Nota: va **dentro** de `resources/`, así que viaja en el wheel —
     `packages = ["src/local_delegate"]` lo incluye igual que al blob. Es deseable: quien instale
     puede comprobar qué lleva.

2. **Script `scripts/check_vendor.py`**
   - Files or modules: `scripts/check_vendor.py` (nuevo)
   - Requirements covered: REQ-002, REQ-003, REQ-004, REQ-005
   - Verification: ejecutado en local sale **verde** con el estado actual y **avisa** de que existe
     4.5.1; con el blob alterado, **falla**
   - Rollback or recovery: borrar el script
   - Detalle: solo stdlib (`hashlib`, `json`, `urllib.request`, `pathlib`). Flag `--offline` para
     saltarse la red. Comprueba además que manifiesto y directorio no estén desincronizados.

3. **Workflow `vendor-audit.yml`**
   - Files or modules: `.github/workflows/vendor-audit.yml` (nuevo)
   - Requirements covered: REQ-007
   - Verification: corre en el PR y sale verde; disparadores `push`/`pull_request` a `main` **y**
     `schedule` semanal
   - Rollback or recovery: borrar el workflow
   - Detalle: `permissions: contents: read`, mínimo privilegio, como el resto de workflows del repo.

4. **Tests**
   - Files or modules: `tests/test_vendor.py` (nuevo)
   - Requirements covered: REQ-002, REQ-005
   - Verification: el hash bueno pasa; un blob alterado **falla**; con la red simulada caída, el
     script **no** falla. Todo sobre copias en `tmp_path`, **nunca** sobre el fichero real
   - Rollback or recovery: borrar el fichero de tests
   - Nota: los tests **no** salen a la red. Se prueba la lógica de decisión, no OSV.

5. **Documentación y fuente de verdad única**
   - Files or modules: `docs/wiki/Repo-hardening.md`, `src/local_delegate/web/metrics.py:472`,
     `CHANGELOG.md`
   - Requirements covered: REQ-008
   - Verification: el documento explica qué falla, qué avisa y **cómo actualizar el vendorizado**
     paso a paso; el comentario de `metrics.py` deja de ser la fuente de la versión y apunta al
     manifiesto
   - Rollback or recovery: revertir
   - Por qué ahí: `Repo-hardening.md` ya tiene la política de dependencias recién mergeada, y esto es
     su continuación natural — cubre justo el hueco que aquella declaró no cubrir.

## Test strategy

- **Unit:** `tests/test_vendor.py`, sin red. Un test que **verifica que la detección detecta** (blob
  alterado → fallo) vale más que uno que confirme el camino feliz.
- **Integration:** ejecución real del script contra OSV y npm, en local y en el CI del PR.
- **End-to-end o manual:** el dashboard sigue sirviendo Chart.js — el cambio no toca el blob, pero
  conviene comprobarlo porque se edita `metrics.py`.
- **Security and secret scanning:** `gitleaks` del pre-commit. No entra ninguna dependencia nueva, así
  que no hay depscore que rehacer.

## Migration and compatibility

- **Nada cambia en tiempo de ejecución.** Se añade un fichero al paquete (unos cientos de bytes) y
  ninguna dependencia.
- **Sin efecto sobre quien ya tiene instalado el paquete.**
- **El manifiesto queda como fuente de verdad de la versión**; el comentario de `metrics.py` pasa a
  remitir a él, para que no haya dos sitios que puedan contradecirse.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.

Revisión adversarial en `plan-review.md`.
