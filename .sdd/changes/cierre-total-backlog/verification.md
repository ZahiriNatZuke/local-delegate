# Verificación — cierre total del backlog

## Entorno

- Base: `main` en `1314b0b` (0.20.0 publicada). Suite de partida: **655 passed, 1 skipped**.
- Al cierre: **673 passed, 2 skipped**. Python 3.11, uvicorn 0.51.0, Playwright 1.62.0 + Chromium.
- Entregado en cuatro PRs: **#116, #117, #118, #119**, todos mezclados.

## Evidencia

| Requisito | Comprobación | Resultado | Evidencia |
|---|---|---|---|
| REQ-001 | Procesos reales con `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT`, código de salida pedido al SO | **cumplido** | `serve` 3→0, stdio `0xC000013A`→0. Al revés: neutralizado el arreglo, fallan con `3221225786` y `3` exactos |
| REQ-002 | Lock tomado y `daemon.json` apuntando a otro puerto | **cumplido** | el mensaje nombra 9393, el pid y el puerto pedido. Control negativo: un `daemon.json` huérfano no se anuncia |
| REQ-003 | `local-delegate --version` | **cumplido** | `local-delegate 0.21.0`, rc=0. Test contra `__version__`, no contra un literal |
| REQ-004 | Comando **tal cual quedó en `settings.json`**, ejecutado con el entorno limpio | **cumplido** | emite `additionalContext`. Al revés: sin el argumento, rojo. Control negativo sin la bandera |
| REQ-005 | Rotación por encima del techo + lectura del check | **cumplido** | tras rotar, `client.observed` sigue viendo a los dos clientes. Al revés: reducido el lector al fichero vivo, rojo |
| REQ-006 | Playwright contra el dashboard servido | **cumplido** | paginación, rango y rango personalizado. Al revés: neutralizado `pgNext`, 2 de 3 rojos |
| REQ-007 | `[dependency-groups] ui` | **cumplido** | medido en vivo: `uv sync --group dev --group ui` **ya no desinstala Playwright** |
| REQ-008 | `scripts/check_install_e2e.py` en los tres sistemas | **cumplido** | verde en `test (macos-latest)`, ubuntu y windows. Control positivo del contador de hooks: 2 → 3 al añadir el de Read |
| REQ-009 | Backlog del vault | **cumplido** | sin ningún punto abierto; lo no resuelto pasa a decisiones con su medición |
| REQ-010 | Release 0.21.0 y máquina al día | **cumplido** | publicada, instalada desde PyPI y verificada con una tool real |

## Comprobaciones de calidad

- [x] **Suite del proyecto**: 673 passed, 2 skipped (los saltos son el módulo de navegador fuera
      del CI y un skip preexistente).
- [x] **Lint y formato**: `ruff check` y `ruff format --check` limpios.
- [x] **Escaneo de secretos**: `gitleaks` verde en los cuatro PRs; el hook de pre-commit pasó en
      cada commit.
- [x] **CodeQL**: **cinco** avisos sobre código nuevo, los cinco arreglados y **ninguno
      silenciado** — dos `except` sin comentario, un `BaseException` en un test, un `import` +
      `import from` mezclados, y un `return` explícito mezclado con caída implícita. Aparte, el
      analizador destapó un **ciclo de importación preexistente** (seis alertas) que se arregló de
      raíz en vez de desactivarse.
- [x] **Auditoría de dependencias (Socket)**: `playwright@1.62.0` (license 70, supplyChain 79) y
      `pyee@13.0.1` (100 en todo). Ninguno bajo el umbral. El 79 tiene causa —driver nativo y
      descarga de navegadores— y alcance acotado: el grupo `ui` no entra en el wheel ni en el sdist.
- [x] **Sin cambios ajenos**: el CHANGELOG solo añade, cero líneas borradas, verificado con
      `git diff origin/main` en cada uno de los cinco rebases.

## Verificación al revés

Regla de la casa aplicada a cada arreglo: **se neutralizó el cambio y se comprobó que el test falla,
y que falla por lo que dice**. Cinco veces, todas con el resultado esperado.

Dos controles positivos detectaron fallos **en las propias pruebas** antes de que contaran como
evidencia: un `readline()` sobre un stderr con buffer que colgaba el test, y un
`select_option("7d")` sobre un valor que no existe (el real es `"7"`). Sin el control, el primero
habría colgado el CI y el segundo habría pasado por un plazo agotado.

## Premisas del backlog que cayeron al medir — cuatro

1. **El `3` del `CTRL_BREAK` no salía del repo.** Sale de `uvicorn.Server.capture_signals`, que
   restaura el handler original y **vuelve a lanzar la señal**; para `SIGBREAK` ese original era
   `SIG_DFL`. Medido con un envoltorio: `serve()` no retornaba y `atexit` no corría.
2. **El brazo B del A/B no estaba bloqueado por «falta definir la variable».** Estaba bloqueado
   porque `install --enable-read-hook` **no encendía nada**: dos puertas y la bandera abría una.
3. **macOS no necesitaba un Mac**, necesitaba un runner — que llevaba tiempo en la matriz del CI.
4. **Los «filtros de tool/modelo» del panel no existen.** Los controles reales son otros.

## Desviaciones y riesgo residual

- **Sin comprobador de tipos.** Carencia real, anotada y **fuera de esta tanda** a propósito: es una
  iniciativa nueva, no deuda del backlog. Se propone aparte.
- **Codex contra un daemon con token** y **la UI de `elicitation` en un tty** siguen sin medirse.
  No hay forma de responderlos aquí y lo medible ya está medido; se cierran como decisión escrita,
  no como «hecho».
- **El chunking sin memoria entre trozos** no se implementa: el síntoma no se reproduce y el arreglo
  obvio (solapamiento) es *incorrecto* para `_chat_chunked`, que transforma y concatena.
- **El brazo B queda encendido pero sin medir**: los datos necesitan días. Lo que esta tanda
  desbloquea es que encenderlo por fin haga algo.
- **El cuelgue de `test (windows-latest)` volvió a aparecer** (cuarta vez), con la firma exacta ya
  documentada: 13:00 clavados = `timeout-minutes: 8` + 5 de gracia. Se resolvió relanzando. No es
  una avería del repo.
