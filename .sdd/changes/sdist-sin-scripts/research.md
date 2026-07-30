# Investigación — sacar `scripts/` del sdist y retirar el instalador de hooks de macOS

## Origen

Socket.dev marca el paquete publicado con `supplyChain: 96`. La causa nunca se pudo investigar
desde el agente (el endpoint `alerts` responde 403 con el plan actual). El 2026-07-30 el usuario
aportó capturas de la web con sesión iniciada, sobre `local-delegate-mcp@0.15.0#tar-gz`.

## Alertas del propio paquete (evidencia: capturas de socket.dev, 2026-07-30)

Cuatro alertas, todas en la categoría «riesgo en la cadena de suministro»:

| Alerta | Ubicaciones | Veredicto |
| --- | --- | --- |
| Riesgo potencial detectado por IA (confianza 0.66, impacto 0.75) | `scripts/install_claude_code_hooks_macos.sh` | **Real** |
| Utiliza eval | `resources/vendor/chart.umd.min.js`, `server.py` | Falso positivo |
| Acceso a la red | `checks.py`, `daemon.py`, `server.py`, `web/metrics.py`, el blob | Inherente |
| Acceso Shell | 4 ficheros de `scripts/` + `autostart.py`, `doctor.py`, `install.py`, `server.py` | Mixto |

Texto de la alerta de IA: «instalador de hooks que convierte contenido remoto (scripts Python
descargados desde raw GitHub) en código ejecutable local y lo persiste registrando comandos en
`~/.claude/settings.json` (…) presenta un riesgo significativo de supply-chain por ejecución de
código remoto sin verificación criptográfica (sin hash/firma/pinning), y además ejecuta los hooks
inmediatamente durante la instalación».

## Verificaciones por ejecución

1. **`server.py` no usa `eval`.** `Grep` de `\b(eval|exec|compile)\s*\(` sobre `server.py` devuelve
   exactamente dos coincidencias, ambas `re.compile(...)` (líneas 562-563). Socket marca el patrón
   `compile(` a secas. Falso positivo confirmado.

2. **El sdist publica el repo entero.** `uv build --sdist` sobre 0.16.0 produce 124 entradas:
   `src` 26, `docs` 24, `tests` 21, `scripts` 15, `.github` 10, `site` 8, `benchmarks` 4,
   `examples` 2, más metadatos sueltos. El `[tool.hatch.build.targets.sdist]` solo excluye
   `/.codex`, `/.sdd`, `/.venv` y `/dist`.

   Corrección a una nota previa: se había registrado que «el wheel no empaqueta `scripts/`». Es
   cierto para el **wheel** (`packages = ["src/local_delegate"]`), pero el **sdist sí los lleva**,
   y el sdist es lo que Socket analiza (la URL de las alertas termina en `/tar-gz`).

3. **El script de macOS es huérfano.** Búsqueda de `install_claude_code_hooks_macos` en todos los
   `.md`, `.yml` y `.py` del repo: cero coincidencias. Nada lo documenta ni lo invoca.

4. **Está congelado en `v0.10.0` y sigue funcionando.** El script fija `VERSION="v0.10.0"`
   (línea 9) y descarga de `.../v0.10.0/docs/recipes/hooks/`. En `main` ese directorio ya no
   existe (`docs/recipes/` contiene siete `.md` y `update_agents.py`), pero
   `git ls-tree -r v0.10.0 -- docs/recipes/hooks` devuelve los cuatro `.py`: la ruta vive en el tag
   y GitHub la sirve.

   Es decir, **no es un script roto: es un script vivo que instala hooks de seis versiones atrás**,
   por red y sin verificar integridad. Esto agrava el caso en lugar de mitigarlo. Una redacción
   anterior de esta misma investigación decía «apunta a una ruta inexistente»; era falso y la
   revisión adversarial del plan lo detectó.

5. **Es redundante.** El CLI `install` ya instala esos mismos hooks desde `resources/hooks/`,
   empaquetados en el wheel, sin tocar la red (`install.py:7`). Los cuatro ficheros que el script
   descarga (`hook_common.py`, `suggest_delegate_prompt.py`, `suggest_delegate_read.py`,
   `suggest_lint_summary.py`) son exactamente los que el paquete ya trae.

6. **Qué hace el script.** 157 líneas: `curl` de los cuatro `.py` a `~/.claude/hooks/`, `chmod 700`,
   `py_compile`, reescritura de `~/.claude/settings.json` para registrarlos, y **ejecución
   inmediata** de dos de ellos como verificación (líneas 147-153). La descripción de Socket es
   exacta. Único matiz: hay anclaje a un tag, no a `main`, lo que mitiga —pero un tag de git es
   movible y no hay verificación de hash.

7. **Dependencias de `scripts/` desde los tests.** `tests/test_vendor.py` usa
   `scripts/check_vendor.py` y `tests/test_bump_version.py` usa `scripts/bump_version.py`. Ningún
   workflow construye ni ejecuta la suite desde el sdist: el CI corre `pytest` sobre el checkout y
   `uv build` solo produce los artefactos (`ci.yml:97`, `publish.yml:72`).

## Serie histórica del score (evidencia: `depscore` de Socket, todas las versiones publicadas)

| Versión | supplyChain | Qué entró |
| --- | --- | --- |
| 0.2.0 – 0.5.0 | 98 | basal; nunca estuvo en 100 |
| 0.6.0 – 0.10.0 | 97 | `caa2b4a` rediseño del dashboard (`/api/system`, `sysinfo.py`) |
| 0.11.0 – 0.16.0 | 96 | `28dd5c3`, el commit que añadió `chart.umd.min.js` |

Esto **corrige** una conclusión anterior que daba por refutada la hipótesis del blob vendorizado
porque «el score no se movió al actualizar Chart.js 4.5.0 → 4.5.1». Ese argumento no probaba nada:
el blob seguía presente, solo cambió de versión, así que sus alertas se mantenían idénticas. La
correlación por versión sí es concluyente.

La alerta de IA sobre el `.sh` fue detectada el 2026-07-30 y todavía no se refleja en el score.

## Alertas de dependencias de terceros (pestaña «dependencies»)

Nueve alertas, ninguna accionable. Se documentan para no volver a investigarlas:

- **`httpcore2` «posible typosquat de httpcore»**: falso positivo. Aunque se quitara `httpx2` del
  `pyproject.toml`, `mcp` 2.0.0 la declara como dependencia propia y entraría igual.
- **`cryptography` «instalar scripts»**: son los `build.rs` del sdist; llega vía
  `pyjwt[crypto]` ← `mcp`, y se instalan wheels, así que no se ejecutan.
- **`cffi` (código nativo, `exec`) y `pycparser` (código ofuscado)**: ambas cuelgan de
  `cryptography`. La propia nota de Socket sobre pycparser dice que no hay intención maliciosa.
- **`anyio` ×3 (red, `eval`, shell)**: llega por starlette/httpx2/mcp. Abrir sockets y lanzar
  subprocesos es la función de la librería.
- **`pyyaml` (constructores unsafe)**: está en el extra opt-in `llamaswap`; no se instala en el
  flujo normal del MCP.

## Riesgos y decisiones abiertas

- **Excluir `scripts/` del sdist deja dos tests sin su objeto.** `test_vendor.py` y
  `test_bump_version.py` no serían ejecutables desde un sdist desempaquetado. Nadie hace eso hoy
  (verificado en los workflows), pero publicar una suite que no puede pasar es incoherente: la
  especificación debe decidir si `tests/` sale junto con `scripts/`.
- **Ningún cambio afecta al wheel**, que es lo que instala todo el mundo vía `uv tool` o `pipx`.
- El blob de Chart.js queda fuera del alcance: sus alertas son ruido de bundle minificado y el
  vendorizado ya está protegido con manifiesto, hash y auditoría OSV.

## Conclusión

El único riesgo real del paquete publicado es el `.sh`, y no tiene defensa posible: está huérfano,
congelado en una versión de hace seis releases, y duplica —trayéndola de la red sin verificar
integridad— una función que el CLI ya cubre desde recursos empaquetados.
