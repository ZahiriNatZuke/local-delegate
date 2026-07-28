# Handoff: Acotar el SDK mcp por debajo del major 2 y cerrar el punto ciego de resolucion libre

## Current state

- SDD status: `result-review` → cierre pendiente solo del gate de memoria.
- Last completed gate: `quality` aprobado; `conformance` con veredicto `conforms-with-notes`.
- Current revision: `main` en `04672c2` (PR #31, squash). CI y CodeQL de `main` en **success**
  verificados **después** del merge, no solo en el PR.
- **La 0.12.2 NO está publicada.** El código está en `main` con la versión ya bumpeada; falta el
  tag `v0.12.2`, que exige confirmación explícita del usuario.

## What changed

1. `mcp>=1.2,<2` en `pyproject.toml`. Cero cambios de código: el import y la instanciación del SDK
   quedan igual.
2. Job **`install-smoke`** en `ci.yml` — el único que no usa `uv.lock`: construye el wheel, lo
   instala en un entorno limpio con `--refresh --resolution highest` y le exige un handshake
   `initialize` real.
3. `scripts/check_install_handshake.py`, con códigos de salida separados para un fallo de import
   (regresión de dependencia) y uno de red o arranque.
4. `CHANGELOG.md` con la entrada de 0.12.2, que **arrastra los PR #29 y #30**, represados en `main`
   por tocar solo `scripts/`.
5. Versión a 0.12.2 en los cuatro sitios vía `scripts/bump_version.py`.

## Decisions

- **Pin ahora, migración después.** Migrar a `mcp.server.mcpserver` dejaría a los usuarios rotos
  durante toda la migración, y la superficie no es solo el import: `daemon.py:116-117` usa
  `settings.streamable_http_path` y `streamable_http_app()`, cuyo equivalente en 2.x no está
  verificado. El techo se retira en una línea el día que se migre.
- **El job no usa el lock, y eso es el punto.** El lock nos protegía en CI y por eso mismo nos
  cegaba. `--refresh` y `--resolution highest` no son adorno: un entorno limpio no implica caché
  limpia, y con una versión vieja cacheada el job pasaría siempre — un check incapaz de fallar.
- **La prueba negativa se hizo contra la 0.12.1 realmente publicada**, no contra una simulación.
  Reproduce el fallo del usuario en otra plataforma y demuestra que el check muerde.
- **`install-smoke` no se añadió a los checks requeridos.** Primero tiene que demostrar que reporta
  en PRs reales (ya lo hizo una vez, en el #31). Exigir un check que nadie publica bloquea el
  repositorio para siempre — este proyecto ya lo sufrió dos veces.
- **El log del cliente es donde está la causa.** `-32000 Connection closed` nunca dice por qué; el
  traceback vive en el `Server stderr` del log de Claude Code. Quedó escrito en el CHANGELOG.

## Next action

**Pedir confirmación al usuario para publicar la 0.12.2** y, con ella:
`git tag v0.12.2 && git push origin v0.12.2` → `publish.yml` encadena
`check-version → pypi → mcp-registry`. Después: GitHub Release a mano (el workflow no lo crea),
depscore del paquete, y verificar el registro con la URL de la versión concreta —el endpoint JSON
de PyPI se sirve con caché y anuncia la anterior justo tras publicar—.

La verificación que de verdad cierra el reporte: `uvx local-delegate-mcp` **sin pin** en la Mac.

## Memory

- Canonical note: `projects/local-delegate/incidente-mcp-sdk-2-2026-07-28.md` (vault).
- Indexes updated: `projects/local-delegate/overview.md`, `projects/local-delegate/backlog.md`,
  y las memorias de Claude Code `local-delegate-status` y `backlog-pendientes`.
