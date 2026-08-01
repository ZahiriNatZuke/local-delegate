# Investigación — cierre total del backlog

Fecha: 2026-08-01. Base: `main` en `1314b0b`, versión `0.20.0` publicada.
Suite de partida: **655 passed, 1 skipped**; `ruff check` limpio.

Regla que gobierna este documento, heredada del repo: **un pendiente es una hipótesis**. Cada
punto de abajo dice cómo se midió y qué devolvió la medición. Donde no hubo medición, lo dice.

---

## A. Puntos que venían del backlog

### A1. `serve` devuelve 3 ante `CTRL_BREAK_EVENT`; stdio muere con `0xC000013A`

**Reproducido**, lanzando procesos reales con `CREATE_NEW_PROCESS_GROUP`, `LOG_DIR` aislado y
`stdin` conectado:

| Camino | Código de salida |
|---|---|
| `serve` | `3` (`0x00000003`) |
| stdio | `3221225786` (`0xC000013A`, `STATUS_CONTROL_C_EXIT`) |

**Diagnóstico, que el backlog dejó a propósito sin inventar.** Instrumentando `serve()` con un
envoltorio se midió que la función **nunca retorna** y que `atexit` **nunca corre**, aunque el
gestor de sesiones del SDK sí imprime su cierre ordenado. O sea: el proceso muere a mitad del
apagado, y el 3 no sale de nuestro código.

La causa está en `uvicorn/server.py::capture_signals` (uvicorn 0.51.0), cuyas `HANDLED_SIGNALS`
en Windows son `(SIGINT, SIGTERM, SIGBREAK)`. Al salir del contexto **restaura el handler original
y vuelve a lanzar la señal**:

```python
for sig, handler in original_handlers.items():
    signal.signal(sig, handler)
...
for captured_signal in reversed(self._captured_signals):
    signal.raise_signal(captured_signal)
```

- Para `SIGINT` el handler original es `default_int_handler` → `KeyboardInterrupt` → lo caza el
  `except KeyboardInterrupt: return 0` que ya existe en `daemon.serve`. **Ese `except` y su
  comentario describen justo este mecanismo, pero solo cubren la mitad.**
- Para `SIGBREAK` el handler original es `SIG_DFL` → la CRT termina el proceso con **3**.

En el camino stdio no hay ningún handler de `SIGBREAK`, así que el manejador de consola por
defecto mata el proceso con `0xC000013A`.

**Hipótesis verificada por ejecución**: instalando `signal.default_int_handler` en `SIGBREAK`
antes de servir, la misma medición da `rc=0`, `serve()` retorna `0` y `atexit` corre.

### A2. Panel interactuado: paginación y filtros en el DOM

El PR #112 ejecuta con node las funciones puras (`computeRange`, `localDayKey`, `byDay`, `agg`,
`fmtHace`) y el PR #110 ejerció `renderHooks` sobre un DOM mínimo. Lo que sigue sin probarse es el
panel **interactuado**. El JS vive embebido en `web/metrics.py` como `metrics.HTML`.

Dato nuevo que lo hace barato: el job `lint` del CI **ya monta Node**, así que un navegador
headless ahí no obliga a crear un job nuevo — y por tanto **no toca el ruleset**, que es donde este
repo ya se quemó una vez.

### A3. `clients.jsonl` crece sin techo

Confirmado por lectura: `clients._escribir_linea` anexa sin límite. La medición previa (144 B por
arranque) sigue valiendo. El consumidor es `checks._probe_clients_observed`, que lee el fichero
entero vía `clients.ruta_registro()`. **Cualquier rotación tiene que no cegar ese check**: rotar
por mes haría desaparecer a un cliente visto el mes pasado, que es peor que el problema.

### A4. El chunking procesa cada trozo a ciegas

Sin cambios respecto a la medición de la novena tanda: la mecánica es real
(`server.py:913-1042`), el síntoma **no se reproduce** (14.222 chars, `chunks=8` confirmado, tres
términos ambiguos idénticos en las cuatro secciones).

Revisado de nuevo el código con la pregunta «¿hay un arreglo barato y correcto?»: **no lo hay**.
Una ventana de solapamiento en `_chat_chunked` es *incorrecta* para su caso de uso — esa función
**transforma** (traducir, reescribir) y concatena, así que solapar duplicaría texto en las
costuras. Un glosario acumulado exige una llamada extra por trozo y memoria entre ellos.

→ **Se cierra como decisión, no como arreglo.**

### A5. Brazo B del piloto A/B — DESBLOQUEADO por un defecto nuevo (ver B4)

El enunciado del backlog decía que faltaba definir `LD_HOOK_READ_ENABLED`. La causa real es otra:
la bandera del instalador que debería encenderlo no lo enciende. Ver B4.

### A6. El instalador nunca se ha ejecutado en macOS

**Premisa parcialmente falsa.** `test (macos-latest)` **ya está** en la matriz del CI y en
`JOBS_ESPERADOS` de `ci_gate.py`: en macOS corre la suite entera desde hace tiempo. Lo que nunca
corrió es el **instalador end-to-end**. Eso es cerrable dentro del job que ya existe.

### A7. Codex contra un daemon con token / A8. La UI de `elicitation` en un tty

Sin máquina ni tty que los responda de forma distinta a lo ya medido. Se tratan explícitamente y
sin inventar conclusión.

### A9. Ideas de la sección 4

Decisión del usuario en esta sesión: **ninguna se implementa**; salen del backlog documentadas
como no-defectos.

---

## B. Hallazgos nuevos de la auditoría

### B1. `serve` con el lock ocupado no dice dónde está el daemon vivo

**Medido.** Con el daemon de la máquina en 9393, `local-delegate serve --port 9899` responde:

```
local-delegate: lock ocupado pero no responde un daemon en 127.0.0.1:9899
```

El lock es **uno por usuario** (`config.LOG_DIR / "daemon.lock"`), no por puerto, pero el mensaje
habla del puerto pedido. Es cierto y engañoso a la vez: hay un daemon, está en otro puerto, y el
mensaje empuja a buscarlo donde no está. El docstring de `serve` dice «idempotente por
usuario/puerto» y eso es **falso**: es por usuario.

Es exactamente el patrón que este repo ya tiene escrito como lección — *un diagnóstico solo vale
para el camino por el que mira*. `daemon.json` tiene el dato (`pid`, `host`, `port`) y nadie lo lee
en esa rama.

### B2. `local-delegate --version` no existe

**Medido**: sale con `rc=2` y un `usage`. El parser raíz declara
`add_subparsers(dest="command", required=True)` y no expone `--version`; el `--version` que sí
existe pertenece al subcomando `update` (fija el pin). Un CLI publicado que no sabe decir su propia
versión, en un proyecto que dedica dos checks a comparar versiones.

### B3. Playwright no está declarado en ninguna parte

`scripts/dev/capture_dashboard.py` y el flujo de la captura del README lo necesitan, y no aparece
ni en `[dependency-groups]` ni en `[project.optional-dependencies]`. De ahí que `uv sync` lo
desinstale y rompa las capturas — una trampa ya sufrida y nunca arreglada **en el repo**.

### B4. `install --enable-read-hook` es un no-op silencioso

**Verificado por ejecución, con control positivo.** El instalador registra
`python "…/suggest_delegate_read.py"` sin `args` ni entorno (`install.py:524-526`), pero la primera
sentencia del script exige `LD_HOOK_READ_ENABLED` (`suggest_delegate_read.py:32`). Son **dos
puertas** y la bandera abre una sola.

```
CON la variable  → emite la recomendación (control: la comprobación PUEDE ver algo)
SIN la variable  → salida vacía, rc=0        (así exactamente lo deja el instalador)
```

Por qué sobrevivió: `test_install.py::test_read_hook_is_opt_in` prueba que el instalador registra,
y `test_hook_recipes.py::test_read_hook_is_disabled_by_default` prueba que el script obedece la
variable. **Ninguno cruza las dos.** Es la lección del repo —*probar la pieza no es probar el
uso*— y *cubrir la combinación, no la función*.

Este defecto es la causa real de que el brazo B del A/B lleve semanas sin poder medirse.

---

## C. Lo que se revisó y está bien

- `ruff check` limpio con las reglas del proyecto.
- Sin `TODO`/`FIXME`/`HACK` en `src/`, `scripts/` ni `tests/`.
- Sin `open()` sin `encoding`, sin `shell=True`, sin `datetime.now()` naive (los dos `_utcnow`
  usan `UTC` explícito).
- `clients.py` correcto: lock que cubre comprobar+escribir, `snapshot()` copia dentro del lock,
  `ruta_registro()` como fuente única.

## D. Lo que se anota y NO se toca

- **No hay comprobador de tipos** (ni mypy ni pyright ni ty). Es una carencia real, pero es una
  iniciativa nueva y no deuda del backlog; meterla en esta tanda mezclaría un cambio de proceso con
  el cierre de una lista. Se propone aparte.
