# Verificación — cierre total del backlog

## Entorno

- Base: `main` en `1314b0b` (0.20.0 publicada). Suite de partida: **655 passed, 1 skipped**.
- Python 3.11 (`.venv` del repo), uvicorn 0.51.0, Playwright 1.62.0 + Chromium.
- CI: `ci.yml` sobre ubuntu/windows/macos, más `install-smoke`, `secrets`, `ci-gate` y CodeQL.

## Evidencia

| Requisito | Comprobación | Resultado | Evidencia |
|---|---|---|---|
| REQ-001 | Procesos reales con `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT`, código de salida pedido al SO | **cumplido** | `serve` 3→0, stdio `0xC000013A`→0. Al revés: neutralizado el arreglo, fallan con `3221225786` y `3` exactos |
| REQ-002 | Lock tomado y `daemon.json` apuntando a otro puerto | **cumplido** | el mensaje nombra 9393, el pid y el puerto pedido. Control negativo: `daemon.json` huérfano no se anuncia |
| REQ-003 | `local-delegate --version` | **cumplido** | `local-delegate 0.20.0`, rc=0. Test contra `__version__`, no contra un literal |
| REQ-004 | Comando **tal cual quedó en `settings.json`**, ejecutado con el entorno limpio | **cumplido** | emite `additionalContext`. Al revés: sin el argumento, rojo. Control negativo sin la bandera |
| REQ-005 | Rotación por encima del techo + lectura del check | **cumplido** | tras rotar, `client.observed` sigue viendo a los dos clientes. Al revés: reducido el lector al fichero vivo, rojo |
| REQ-006 | Playwright contra el dashboard servido | **cumplido** | paginación, rango y rango personalizado. Al revés: neutralizado `pgNext`, 2 de 3 rojos |
| REQ-007 | `[dependency-groups] ui` | **cumplido** | `uv lock` resuelve playwright 1.62.0; `scripts/dev/README.md` documenta los dos grupos |
| REQ-008 | `scripts/check_install_e2e.py` en los tres sistemas | **cumplido** | verde en `test (macos-latest)`, ubuntu y windows. Control positivo del contador de hooks: 2 → 3 al añadir el de Read |
| REQ-009 | Nota del vault | pendiente de la release | se actualiza al cerrar |
| REQ-010 | Release | pendiente | se ejecuta tras mezclar los cuatro PRs |

## Comprobaciones de calidad

- [x] **Suite del proyecto en verde**: 667 passed, 1–2 skipped (los saltos son el módulo de
      navegador fuera del CI y un skip preexistente).
- [x] **Lint y formato**: `ruff check` y `ruff format --check` limpios.
- [x] **Escaneo de secretos**: `gitleaks` verde en el job `secrets` de los cuatro PRs; el hook
      `Detect hardcoded secrets` de pre-commit pasó en cada commit.
- [x] **CodeQL**: cinco avisos sobre código nuevo, **los cinco arreglados, ninguno silenciado** —
      dos `except` sin comentario, un `BaseException` en un test, un import cíclico
      (`cli` → `server`) y un `import` + `import from` mezclados.
- [x] **Sin cambios ajenos**: cada PR toca solo su tema; el CHANGELOG solo añade (cero líneas
      borradas, verificado con `git diff origin/main` en los tres rebases).

## Verificación al revés

Regla de la casa aplicada a cada arreglo: **se neutralizó el cambio y se comprobó que el test
falla, y que falla por lo que dice**. Cinco veces, todas con el resultado esperado. Dos de los
controles positivos detectaron fallos **en las propias pruebas** antes de que contaran como
evidencia: el `readline()` sobre un stderr con buffer, y un `select_option("7d")` sobre un valor
que no existe (`"7"`).

## Desviaciones y riesgo residual

- **Sin comprobador de tipos.** Carencia real, anotada en `research.md` y **fuera de esta tanda**
  a propósito: es una iniciativa nueva, no deuda del backlog.
- **Codex contra un daemon con token** y **la UI de `elicitation` en un tty** siguen sin medirse.
  No hay forma de responderlos aquí, y lo que sí era medible ya está medido. Se cierran como
  decisión escrita, no como «hecho».
- **El chunking sin memoria entre trozos** no se implementa: el síntoma no se reproduce y el
  arreglo obvio (solapamiento) es *incorrecto* para `_chat_chunked`, que transforma y concatena.
- **El brazo B del A/B** queda encendido pero **sin medir**: los datos necesitan días. Lo que esta
  tanda desbloquea es que encenderlo por fin haga algo.
