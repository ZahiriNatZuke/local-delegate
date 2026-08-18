# Verification

## Checks del proyecto

| Check | Resultado |
|---|---|
| `uv run pytest` | **762 passed, 2 skipped** (eran 752) |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 75 files already formatted |

## End-to-end, que era la única pregunta que importaba

El script del research demostró que un `ContextVar` cruza el threadpool. Eso no era la pregunta:
entre el middleware y el handler está el SDK. Se comprobó con el daemon **real** levantado en el
puerto 9494 con su propio `LOG_DIR`, y dos clientes MCP por HTTP:

```
{'tool': 'local_summarize', 'client': 'cliente-uno', 'ok': False, 'source': 'path'}
{'tool': 'local_summarize', 'client': 'cliente-dos', 'ok': False, 'source': 'path'}
```

Dos nombres, dos firmas, en el log en disco. El `ok: False` es el 401 del backend —ese daemon de
prueba no tenía la credencial— y no afecta a lo que se medía: la línea se escribe igual y lleva su
firma.

`GET /api/stats` del mismo daemon devolvió el desglose con los dos clientes separados, y el panel
abierto en el navegador pintó las dos tarjetas:

- **Quién delegó** — `cliente-uno 1 · 50,0 %`, `cliente-dos 1 · 50,0 %`
- **Sugerencias de los hooks**, con la tabla nueva de puntería — `avisó 1 · 50,0 %`,
  `codigo 1 · 50,0 %`

## Los tests fallan por la razón que dicen

Mutante: quitar el `_CLIENTE_ACTUAL.set(...)` del middleware.

| Falla | ¿Correcto? |
|---|---|
| `test_la_tool_ve_el_nombre_del_cliente_que_la_llamo` | sí |
| `test_dos_clientes_distintos_dejan_firmas_distintas` | sí |
| `test_un_cliente_que_no_se_presenta_sale_como_el_default_del_sdk` | sí |

Los tres, y sólo esos, de 23. El segundo es el control anti-vacío: sin él, una implementación que
devolviera una constante —o el nombre del último cliente visto en una global— pasaría el primero
entero.

## Un hallazgo que cambió un requisito

`test_un_cliente_sin_identidad_no_inventa_firma` **falló al escribirlo**: esperaba `None` y
obtuvo `mcp`. Medido y no supuesto: **el SDK del cliente rellena `mcp` cuando no se le da
`client_info`**, así que «sin identidad» casi no existe visto desde el servidor. Encaja con el
registro real de esta máquina, que tiene líneas de `mcp 0.1.0`.

No rompe nada de lo que el campo persigue —un script con el SDK por defecto se sigue distinguiendo
de `claude-code`— pero el test se reescribió para decir lo que pasa de verdad en vez de lo que se
había supuesto. El camino de omitir el campo sigue vivo en `_log_event` para cuando `client_info`
llegue en `None` de verdad.

## Requisitos

| REQ | Evidencia |
|---|---|
| REQ-001 | End-to-end: las dos líneas del log llevan `client`. `_log_event` lo omite si es falsy |
| REQ-002 | Sólo `getattr(client_info, "name")`; la versión y las caps siguen en `clients.jsonl` |
| REQ-003 | `test_stats_separa_las_delegaciones_por_cliente` y `..._no_reparte_ni_descarta_...`, que además comprueba que los conteos suman el total |
| REQ-004 | `test_agrupa_las_lecturas_por_motivo_de_descarte`, `..._por_extension`, y la tarjeta vista en el navegador |
| REQ-005 | `test_la_telemetria_vieja_no_recibe_un_motivo_inventado`; contra el log real de esta máquina, 1 049 eventos caen en «sin registrar» |
| REQ-006 | No hay ninguna tasa de conversión en el agregado ni en el HTML; el pie de la tarjeta lo dice explícitamente |
| REQ-007 | La lectura va envuelta en `try/except` y el middleware entero ya era best-effort; `test_cliente_actual_fuera_de_una_peticion_es_none` |

## Nota sobre la captura del README

Los mocks de `scripts/dev/capture_dashboard.py` incluyen ya `by_client`, `by_motivo`, `by_ext` y
`read_total`, con los números cuadrando con la tabla de categorías (`read` = 130 = 52+41+24+13, y
los 41 avisos son sus `suggested`). La imagen **no se regenera aquí**: eso pasa en la release, que
es donde el manifiesto ata la captura a la versión.

## Higiene

`git diff --stat` y `git diff --ignore-cr-at-eol --stat` dan idéntico (813 inserciones, 4
borrados): cero ruido de finales de línea. Se editó con un helper que detecta y preserva el
separador de cada fichero, porque este repo mezcla LF y CRLF y ya van tres sesiones pagándolo.
