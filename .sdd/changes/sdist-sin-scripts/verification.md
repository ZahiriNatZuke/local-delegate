# Verificación — sacar `scripts/` del sdist y retirar el instalador de hooks de macOS

## Entorno

- Rama: `fix/sdist-sin-scripts`, sobre `main` en `78737cd`
- Windows 11, Python 3.11 (entorno de `uv`), pytest 8, ruff 0.16, Node v24.18.0
- Todas las construcciones y árboles temporales, fuera del repositorio

## Evidencia

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | El fichero no está en el árbol | ✅ | `git rm scripts/install_claude_code_hooks_macos.sh`; `git status --short` muestra `D` y ningún residuo |
| REQ-002 | Listado del sdist construido | ✅ | 124 → **109** entradas; **0** bajo `scripts/`; se van los 15 ficheros del taller y **nada más** (`anadidos: ninguno`) |
| REQ-003 | Wheel construido desde `main` vs wheel con el cambio | ✅ | **30 = 30 entradas, idénticas fichero a fichero.** Comparado en un `git worktree` de `main`, no por razonamiento |
| REQ-004 | Caso A y caso B, abajo | ✅ | Ver «Prueba al revés» |
| REQ-005 | Sección `### Security` en `Unreleased` | ✅ | `CHANGELOG.md`; CRLF verificado: 843 CRLF, **0 LF sueltos** |

### Prueba al revés (la que valida de verdad el `skip`)

Un `skip` mal condicionado se ve idéntico a uno bien condicionado mientras el fichero exista, así
que se probaron los dos lados:

- **Caso A — sdist real sin `scripts/`:** se desempaquetó el tarball construido y se ejecutó
  `pytest tests/test_vendor.py tests/test_bump_version.py` allí dentro. Resultado: **2 saltados**,
  con motivo legible, **sin errores de colección**. Es el escenario que motiva el cambio.
- **Caso B — `scripts/` presente pero sin el script (borrado accidental):** se creó `scripts/` con
  otro fichero dentro. Resultado: **2 errores de colección con `FileNotFoundError`**, la suite se
  interrumpe. El `skip` **no** enmascara un borrado. Esto es el hallazgo H2 de la revisión del plan,
  ya verificado y no solo razonado.
- **Repositorio completo:** 386 pasan, 1 saltado — y ese saltado es preexistente y ajeno
  (`test_checks.py:171`, «chmod no quita permisos de lectura en Windows»). Ninguno de los dos
  ficheros tocados queda saltado, que es lo que exige REQ-004.

## Comprobaciones de calidad

- [x] `uv run ruff check .` — `All checks passed!`
- [x] `uv run ruff format --check .` — `52 files already formatted`
- [x] `uv run pytest -q --basetemp=<temp propio>` — 386 pasan, 1 saltado (ajeno)
- [x] `scripts/extract_dashboard_js.py` + `node --check` — OK
- [x] Suite repetida tras editar la wiki — 386 pasan, sin cambios
- [x] Sin cambios ajenos: `git status --short` lista solo `CHANGELOG.md`, `pyproject.toml`, el
      borrado, los dos tests, `docs/wiki/Repo-hardening.md` y el directorio del propio change
- [x] Secretos: el cambio no añade contenido nuevo con credenciales; el único fichero nuevo es
      documentación. `secrets` y GitGuardian corren en el CI

## Documentación

- `docs/wiki/Repo-hardening.md` gana la sección «Qué se publica y qué no», con la tabla de
  wheel/sdist y el porqué de la condición sobre el directorio. Es la página donde ya viven la
  política de techos y el vigilante del vendorizado.
- El `README.md` no menciona `scripts/` ni el instalador retirado (verificado por búsqueda): no
  requiere cambios por este trabajo.

## Desviaciones y riesgo residual

- **Un error propio durante la verificación, corregido:** una primera medición dio 110 entradas en
  vez de 109 porque un fichero espurio llamado `--out` —creado al invocar mal
  `extract_dashboard_js.py`— se coló en ese build. Se limpió y se reconstruyó. Sirve de recordatorio
  de que el sdist recoge lo que haya en el árbol: cualquier residuo se publica.
- **Riesgo residual aceptado:** las otras tres alertas del paquete (eval, red, shell) siguen
  abiertas. Dos son falsos positivos de un bundle minificado y la tercera describe lo que el
  producto hace. Documentado en `research.md` y declarado no objetivo en `spec.md`.
- **Fuera de alcance, detectado de paso:** `docs/wiki/Remote-backend.md:74-75` sigue recomendando
  `./scripts/update_to_latest.sh`, que el PR #66 declaró sustituido por `local-delegate update`. Es
  un desfase de documentación anterior a este cambio, todavía sin publicar. Se reporta, no se
  arregla aquí.
- **La captura del README está desfasada** (enseña `v0.15.0` y el icono anterior a la marca única
  del PR #67). `Publishing.md:89` ya fija el procedimiento: se regenera *después* del bump de
  versión. Corresponde al release, no a este change.
