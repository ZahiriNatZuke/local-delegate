# Brief: Cerrar las 10 alertas abiertas de CodeQL: 6 arreglos y 4 descartes

## Problem

La pestaña Security del repo tiene **10 alertas abiertas de code scanning** (2 `high`, 1 `warning`,
7 `note`), todas emitidas por CodeQL sobre el commit `17df173` — o sea, sobre el HEAD actual, no
sobre código ya borrado. Las 15 alertas anteriores se cerraron todas como `fixed`; no hay
precedente de descartes en este repo.

Evidencia recogida por ejecución (`gh api repos/ZahiriNatZuke/local-delegate/code-scanning/alerts`)
y lectura del código en cada ubicación:

| # | Sev | Regla | Sitio | Veredicto |
|---|-----|-------|-------|-----------|
| 20 | high | `py/bad-tag-filter` | `scripts/extract_dashboard_js.py:17` | vigente, riesgo nulo, arreglo trivial |
| 1 | high | `py/incomplete-url-substring-sanitization` | `tests/test_metrics.py:476` | falso positivo de contexto |
| 18 | warning | `py/redundant-comparison` | `tests/test_core.py:619` | falso positivo (no modela hilos) |
| 19 | note | `py/unused-global-variable` | `src/local_delegate/web/sysinfo.py:284` | falso positivo (intraprocedural) |
| 17 | note | `py/empty-except` | `src/local_delegate/resources/hooks/hook_common.py:36` | vigente, falta comentario |
| 15 | note | `py/empty-except` | `src/local_delegate/daemon.py:86` | vigente, falta comentario |
| 3 | note | `py/empty-except` | `src/local_delegate/server.py:159` | vigente, comentario mal colocado |
| 13 | note | `py/catch-base-exception` | `scripts/macos_mcp_canary.py:95` | intencional y documentado |
| 11 | note | `py/import-and-import-from` | `src/local_delegate/server.py:117` | patrón deliberado |
| 12 | note | `py/import-and-import-from` | `src/local_delegate/server.py:1686` | patrón deliberado |

**Causa del ruido:** `.github/workflows/codeql.yml:34` usa `queries: security-and-quality`, la suite
más amplia, que incluye reglas de *calidad*. Por eso 8 de 10 no son de seguridad.

**Ninguna de las 10 toca superficie de ataque**: nada del daemon HTTP, del token
`LOCAL_DELEGATE_WEB_TOKEN`, de la lectura de ficheros por `path`, ni de los hooks. Las dos `high`
son high por *regla* (la regla asume contexto de sanitización de entrada no confiable), no por
impacto en este código.

### Detalle de los cuatro falsos positivos, verificados leyendo el código

- **#19** — la hipótesis natural era un bug real: si `_refresh_vram_map` no declarara
  `global _vram_refreshing`, el flag quedaría en `True` para siempre y el muestreo de VRAM se
  congelaría tras el primer refresco. **No es el caso**: `sysinfo.py:262` sí declara `global`. La
  asignación de la línea 284 se lee en la *siguiente* llamada (línea 283), cosa que el análisis
  intraprocedural de CodeQL no ve.
- **#1** — `assert "fonts.googleapis.com" in html` comprueba que el HTML *contiene* esa cadena; no
  sanea ninguna URL.
- **#18** — entre el `assert peak == 2` de la línea 614 y el de la 619 hay `release.set()` y los
  `join()`: los cinco hilos siguen corriendo. La segunda comprobación verifica que el pico **no
  subió al liberar**, y es intencional.
- **#11/#12** — son dos `import ctypes` perezosos en funciones distintas, ambos bajo guarda
  `sys.platform == "win32"`. Unificarlos no sirve: `ctypes.wintypes` no viene con `import ctypes`,
  hay que importarlo aparte igual.

## Desired outcome

Cero alertas abiertas de code scanning en `main`, sin haber silenciado nada que fuera un defecto
real y sin haber tocado código de riesgo para maquillar una métrica. Cada alerta cerrada por su vía
correcta: arreglo cuando el código mejora, descarte razonado cuando la herramienta se equivoca.

## In scope

- Arreglo en código de #20, #17, #15, #3.
- Mejora de los dos tests que disparan #1 y #18, de forma que el test quede **mejor**, no solo
  callado.
- Descarte con motivo y comentario, vía `gh api`, de #19, #13, #11, #12 — **después** de mergear
  la PR.

## Out of scope

- Cambiar la suite de queries de `.github/workflows/codeql.yml` (`security-and-quality` aporta: las
  15 alertas ya cerradas salieron de ahí). Si el ruido de las reglas de calidad molesta más
  adelante, es una decisión aparte.
- Refactorizar los imports perezosos de `ctypes` en `server.py`.
- Cualquier cambio en el daemon, el token, los hooks o la lectura de ficheros.

## Constraints and risks

- **Los descartes escriben sobre el repo** (`PATCH .../code-scanning/alerts/{n}`). El usuario pidió
  aplicarlos solo tras revisar la PR.
- **Riesgo de arreglo peor que la enfermedad**: #11/#12 y #13 se descartan precisamente porque
  "arreglarlos" tocaría código Windows-only o el manejo de un hilo lector, con más riesgo que
  beneficio.
- **Trampa conocida del repo** (`probar-la-pieza-no-es-probar-el-uso`): al reescribir los tests de
  #1 y #18 hay que comprobar que el test nuevo **puede fallar** por la razón que dice comprobar. Un
  assert más específico que pase por la guarda equivocada sería un retroceso, no una mejora.
- El arreglo de #20 (`re.IGNORECASE`) cambia el comportamiento del script de build: hay que
  verificar que sigue extrayendo el mismo `<script>` inline y que `node --check` pasa.

## Open questions

Ninguna abierta. Las dos decisiones que dependían del usuario (escala del proceso, momento de los
descartes) están resueltas: modo lite, descartes tras la PR.
