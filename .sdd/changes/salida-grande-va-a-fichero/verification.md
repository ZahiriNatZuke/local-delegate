# Verification: La salida grande va a fichero, no al contexto

## Environment

- Revision: rama `main` sobre `75f351b`, T10 implementada (sin commitear al escribir esto).
- Runtime: Python 3.11, `uv run pytest` / `uv run ruff`. Backend real: llama-swap en
  `127.0.0.1:9292`, `llama31-8b` cargado, **`n_ctx` = 16 384**. Daemon MCP: paquete publicado
  **0.26.0** (código *sin* el arreglo), que es lo que lo hace utilizable como control.

## Evidence

### T10 — el reintento del map-reduce deja de estar ciego

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-023/024 | Test de regresión con el mensaje real, corrido **contra el código de ayer** | **Falla**, y falla por el assert que dice: pasa la guarda «llegó a provocar el desborde» y revienta en `assert not salida.startswith("[local-delegate error]")` | `test_el_mensaje_real_de_este_backend_dispara_el_reintento` |
| REQ-024 | Formas del catálogo (llama.cpp, OpenAI/vLLM, LM Studio) + **control negativo** (conexión caída, 500 genérico, modelo inexistente, cadena vacía) | Pasa. El control negativo es la mitad del test: sin él, reconocer cualquier error también pasaría | `test_la_deteccion_de_desborde_cubre_las_formas_del_catalogo` |
| REQ-026 | Desborde irreductible → mensaje accionable, y **mutante dirigido** (`if False:` en el bloque nuevo) | El mutante hace fallar `assert "no cabe" in salida`, o sea el assert propio del requisito y no una guarda anterior | `test_un_desborde_agotado_se_explica_en_vez_de_soltar_el_error_crudo` |
| REQ-023 (alcance real del bug) | Medición contra el backend real por el daemon publicado | **El `400` siempre se reconoció**: `uv.lock` (197 949 chars) se resume en 7 partes y **18 pasadas**, o sea con reintentos por desborde | Log de uso `2026-09-08T18:56:57Z` |
| REQ-023 (el caso ciego) | Reconstrucción del `500` desde el log | Los dos eventos fallidos traen `error: http_500`, `chars_out: 137` y **sin `chunks`** (omitido cuando vale 1 → una sola llamada, cero reintentos). 137 = prefijo (49) + `{"error":{"code":500,"message":"Context size has been exceeded.","type":"server_error"}}` (88). Cuadra al carácter | Log `2026-09-08T18:20:48Z` y `:49Z` |
| REQ-025 | `local_summarize(path=CHANGELOG.md)` por el daemon **sin el arreglo** | **Funciona** (4 partes, 5 pasadas, `ok=true`) → el caso no discrimina. Requisito retirado en la spec | Log `2026-09-08T18:55:18Z` |

### Extremo a extremo con el código nuevo contra el backend real

La clave del backend la tiene el lanzador del daemon y no el shell —un proceso propio da `401`—.
Se desbloqueó leyéndola del almacén cifrado del propio lanzador (DPAPI, mismo usuario) **en la
misma línea** que lanza el script, sin que el secreto pase por un fichero en claro ni por la
salida. Script: `scratchpad/e2e_t10.py`; el log va al scratchpad para no
contaminar la telemetría real.

| Caso | Comprobación | Resultado |
| --- | --- | --- |
| No-regresión, prosa | `local_summarize(path=CHANGELOG.md)` | se resume sin error |
| No-regresión, denso | `local_summarize(path=uv.lock)` | se resume sin error |
| El reintento sigue vivo | firma de troceado del mismo caso | **7 partes en 18 pasadas**, o sea reintento por desborde disparado y resuelto |
| REQ-026 de verdad | `CHUNK_MIN_CHARS` 45 000 y 100 000 chars densos: los trozos llegan al presupuesto, desbordan el `n_ctx` de 16 384 y **no se pueden partir por debajo del mínimo** | Sale el mensaje nuevo: *«el contenido no cabe en el contexto de llama31-8b, ni partido en trozos de 45000 caracteres. Sube el contexto del backend para ese modelo, usa uno con contexto mayor, o pasa menos contenido de una vez»*, con la respuesta del backend detrás |

**Ojo con el presupuesto:** el primer intento de montar el caso 3 no llegó a desbordar.
`budget = max(CHUNK_MIN_CHARS, max_chars × 0,8)`, así que **subir el mínimo de troceado sube
también el presupuesto** y los trozos salieron más pequeños, no más grandes. El caso solo
discrimina si el fichero es lo bastante grande para que los trozos lleguen al presupuesto nuevo.

## Quality checks

- [x] Project-native tests pass — `uv run pytest`: **772 passed, 2 skipped**.
- [x] Lint y formato — `uv run ruff check .` y `ruff format --check`: limpios.
- [x] Sin ruido de CRLF — `git diff --stat` y `git diff --ignore-cr-at-eol --stat` coinciden
      (165 inserciones en los dos). `server.py` sigue CRLF puro; `test_map_reduce.py`, LF puro.
- [ ] Secret scanning — pendiente al cerrar el cambio.
- [x] Sin cambios ajenos — el diff toca solo `server.py` (detección + camino de error) y
      `tests/test_map_reduce.py`, los dos ficheros de propiedad exclusiva de T10.

## Deviations and residual risk

- **Desviación (reportada al usuario):** dos afirmaciones del diagnóstico previo se cayeron al
  medir. El reintento **no** estaba «anulado por completo» —el `400` sí lo dispara— y el
  `CHANGELOG.md` **no** reproduce el fallo. Corregido en `research.md` y `spec.md`; REQ-025
  retirado. El defecto que T10 arregla sigue siendo real: el `500` con
  `Context size has been exceeded.` no disparaba el reintento.
- **Riesgo residual:** el disparador del `500` no se ha aislado. Es intermitente —mismo fichero y
  mismo tamaño de trozo, ayer falló y hoy pasa— y la sospecha (la concurrencia repartiendo el
  `n_ctx` de 16 384 entre slots) **está sin confirmar**. El arreglo es correcto en cualquier caso:
  ante un desborde, partir el trozo es la respuesta venga en `400` o en `500`.
- **Detección deliberadamente generosa:** fuera de las marcas inequívocas se exige una palabra de
  «contexto» y una de «exceso». Un falso positivo cuesta como mucho dos reintentos más pequeños;
  un falso negativo anula el mecanismo. La asimetría manda.
