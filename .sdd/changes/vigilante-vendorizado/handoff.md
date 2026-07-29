# Handoff: Vigilante del vendorizado de Chart.js: integridad, CVEs y version

## Current state

- SDD status: `closed`. **Los cinco gates aprobados.**
- Current revision: **PR #39 mergeado** en `main` con squash (`dbe5dfa`). El CI de `main` después
  del merge: `CI`, `CodeQL` y `Vendor audit`, los tres en verde.
- **Las 5 tareas del plan están implementadas**, más una sexta que obligó el CI (`.gitattributes`).
  El checkout principal (`D:\Projects\local-delegate`) sigue en `feat/mcp-sdk-2-fase2`, sin tocar.
- **Está en `Unreleased`: todavía no publicado en PyPI.**

## What changed

Siete ficheros, ninguno en el camino de ejecución del paquete:

| Fichero | Qué es |
| --- | --- |
| `src/local_delegate/resources/vendor/vendor.json` | nuevo. Manifiesto: nombre, versión, ecosistema, origen, licencia, SHA-256 y bytes. Documenta la trampa del banner |
| `scripts/check_vendor.py` | nuevo. Solo stdlib. `--offline` y `--manifest` (lo segundo es lo que hace testeable el script sin tocar el árbol real) |
| `.github/workflows/vendor-audit.yml` | nuevo. `push`/`pull_request` a `main` + cron semanal. Sin `setup-python`: el script es stdlib y el Python del runner basta |
| `tests/test_vendor.py` | nuevo. 20 tests, ninguno sale a la red |
| `docs/wiki/Repo-hardening.md` | sección nueva: qué falla, qué avisa y el procedimiento de actualización paso a paso |
| `CHANGELOG.md` | entrada en `Unreleased` |
| `src/local_delegate/web/metrics.py` | el comentario deja de anotar la versión y remite al manifiesto |
| `.gitattributes` | nuevo. `-text` sobre `resources/vendor/`. **Sin esto nada de lo anterior funciona en Windows** (ver abajo) |

Lo verificado por ejecución, no por lectura:

- Los **cuatro** pasos del CI en local: `ruff check .`, `ruff format --check .`, `pytest -q`
  (**254 pasan**, 20 nuevos) y `extract_dashboard_js.py` + `node --check`.
- El script contra los servicios reales: OSV da cero vulnerabilidades para 4.4.1, npm avisa de
  4.5.1, `exit=0`.
- Con una copia del blob alterada en un byte: `exit=1` con el hash esperado, el real y qué hacer.

## El hallazgo que no vio ni el plan ni su revisión

**Git le cambiaba los bytes al blob en Windows.** La primera corrida del PR #39 pasó en Ubuntu y
macOS y **falló en `windows-latest`**: con `core.autocrlf=true` —el valor por defecto de Git for
Windows y el del runner— git convierte los LF en CRLF al hacer checkout, el fichero pasa a medir
205 139 bytes y el hash no cuadra sin que nadie lo haya tocado. En la máquina de desarrollo no se
veía porque tiene `core.autocrlf=false`.

Sin arreglarlo, el vigilante fallaría siempre en cualquier clon de Windows —y un check que falla
siempre se acaba ignorando—, y un wheel construido allí llevaría un JavaScript distinto del que se
publica desde Linux. Corregido con `.gitattributes`, un test que fija esa premisa
(`test_gitattributes_protege_el_vendorizado_de_la_normalizacion`) y una pista en la salida del
script cuando ve CRLF y exceso de tamaño. Anotado como **F7** en `plan-review.md`.

## Decisions

Las del `plan.md` se mantienen todas. Lo que se decidió **durante** la implementación:

- **`--manifest` como parámetro.** Es lo que permite que los tests trabajen sobre copias en
  `tmp_path` y nunca sobre el fichero real, que era F2 de la revisión del plan.
- **Toda la red pasa por una sola función `_pedir_json`.** Los tests la sustituyen; por eso la suite
  no sale a internet ni siquiera por accidente.
- **Una caída y una respuesta malformada se tratan igual** (`ServicioNoDisponible`): en ambos casos
  no sabemos nada, y no saber nada no puede tumbar un PR.
- **El manifiesto declara `licenseFile`** para que el chequeo de sincronía no vea la licencia como
  un fichero intruso, pero su contenido **no** se hashea: no es código que se sirva.
- **Códigos de salida distintos** (1 integridad, 2 vulnerabilidad, 3 manifiesto ilegible), y con dos
  cosas rotas manda el 1: es el diagnóstico más fiable porque es offline.
- **El workflow no instala nada** —ni `uv`, ni `setup-python`—: el script es stdlib por diseño, el
  job tarda segundos y no añade una action más que mantener.

## Next action

El change está cerrado. Lo que deja pendiente, y no es de este cambio:

1. **Subir Chart.js a 4.5.1** — el primer encargo del vigilante, en un cambio aparte. El
   procedimiento está en `docs/wiki/Repo-hardening.md`. Ojo: el aviso vive en un job **verde**, que
   es justo el mecanismo por el que nadie se enteró la primera vez.
2. Nada de esto está publicado: va en `Unreleased`, saldrá con la próxima versión.
3. Retirar el worktree `D:\Projects\local-delegate-vendor` cuando ya no haga falta.

## Un tropiezo que conviene no repetir

**El rebase sobre `main` metió la entrada del CHANGELOG dentro de `[0.12.3]`**, que ya estaba
publicada: el commit de preparación de esa versión había renombrado `Unreleased` justo donde
aterrizaba el diff, y git no ve conflicto ahí. Se corrigió antes de mergear. Al rebasar después de
un release, revisar el `CHANGELOG.md` a mano.

Lo que queda **fuera** de este cambio y es su continuación natural: subir Chart.js a 4.5.1, que será
el primer encargo del vigilante.

## Memory

- Canonical note: `projects/local-delegate/vigilante-vendorizado.md` en el vault de Obsidian, con el
  criterio, los tres gotchas y lo que queda vivo.
- Indexes updated: sí. `backlog.md` cierra la entrada de Chart.js y la sustituye por el pendiente
  real (subir a 4.5.1); `techos-major-dependencias.md` remite a la nota nueva para el hueco del
  vendorizado que declaraba no cubrir; y la memoria de proyecto de Claude Code lleva el puntero.
