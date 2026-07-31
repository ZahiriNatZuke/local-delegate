# Verification: El dashboard lee la telemetria de los hooks

## Environment

- Base `5f1a0fc` (`main`, tras el PR #109); rama `feat/telemetria-hooks-dashboard`.
- Windows 11, `uv run`, node v24 para los tests que ejecutan JS.
- El e2e corrió contra el **log de telemetría real** de la máquina: 1817 líneas.

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | agregado + endpoint con rango | ✅ | tests + e2e real |
| REQ-002 | evento sin `suggested` | ✅ | test + mutante que lo cuenta como `True` |
| REQ-003 | sin la variable | ✅ | `enabled: false` con motivo; mutante cae |
| REQ-004 | lista vacía | ✅ | `rate == 0.0`, sin división por cero |
| REQ-005 | línea corrupta | ✅ | 2 de 3 líneas, sin excepción |
| REQ-006 | campo de contenido inyectado | ✅ | no aparece en la respuesta |
| REQ-007 | tarjeta escondida | ✅ | node, 4 escenarios; mutante cae |
| REQ-008 | el aviso de «sugieren» | ✅ | node; mutante que lo borra cae |
| REQ-009 | escapado | ✅ | node, con `<img src=x onerror=…>` |
| REQ-010 | orden de las listas | ✅ | días cronológicos, resto por volumen; mutante cae |

### End-to-end contra el log real

```
log real: C:\Users\Yohan\.claude\hooks\telemetry.jsonl  existe=True  lineas=1817
enabled=True  exists=True
total=1817  suggested=308  rate=0.1695 (17.0 %)

por evento:   PreToolUse 1679 (283 sug.) · UserPromptSubmit 138 (25 sug.)
por categoria: bash 1396 / 0 sug. · lint 283 / 283 · sin categoría 113 / 0 · summarize 25 / 25
por dia:      29-jul 405 (49) · 30-jul 682 (121) · 31-jul 730 (138)
```

**El desglose enseña algo que el total escondía:** la tasa global del 17 % sale entera de `lint` y
`summarize`; `bash`, con 1396 eventos, no sugiere **nunca**. Ese detalle es el que justifica que la
tarjeta enseñe por categoría y no solo el porcentaje.

### Verificación al revés: 8 mutantes, 8 cazados

| Mutante | Quién lo caza |
| --- | --- |
| `suggested` ausente cuenta como sugerida | `test_un_evento_viejo_sin_el_campo_suggested_*` |
| sin telemetría finge estar activada | `test_sin_la_variable_*` |
| el rango deja de filtrar | `test_el_rango_filtra_igual_que_*` |
| los días salen por volumen | `test_agrupa_por_evento_categoria_y_dia` |
| la categoría ausente se descarta | `test_una_categoria_ausente_no_se_pierde_*` |
| la tarjeta se enseña sin telemetría | `test_la_tarjeta_se_esconde_*` |
| desaparece el aviso de «sugieren» | `test_la_tarjeta_se_esconde_*` |
| **la categoría se pinta sin escapar** | `test_la_tarjeta_se_esconde_*` (tras arreglarlo) |

**El último se escapó en la primera pasada**, y es el mismo agujero que ya apareció dos veces hoy:
el test probaba `escHooks` **aislada**, así que quitar la llamada desde `renderHooks` no lo
cazaba. Se arregló metiendo una categoría maliciosa en el caso que ejecuta `renderHooks` de
verdad, y comprobando el HTML que produce. Probar la pieza no es probar el uso.

## Quality checks

- [x] `uv run pytest -q` → **637 passed, 1 skipped** (623 al empezar el change).
- [x] `uv run ruff check .` → `All checks passed!`
- [x] `uv run ruff format --check .` → `66 files already formatted` (tras aplicar el formato).
- [x] `extract_dashboard_js.py` + `node --check` → OK
- [x] Sin secretos; test explícito de no filtración de contenido.
- [x] Sin cambios ajenos.

## Deviations and residual risk

- **El riesgo que queda es de interpretación y no se puede cerrar con código.** Alguien puede leer
  «17 %» como «lo que se delegó». Se mitiga con el texto de la tarjeta y con un test que falla si
  ese texto desaparece — pero nada impide malinterpretar un número.
- **El endpoint devuelve la ruta del log** en `log`. Es deliberado y consistente con `/api/status`,
  que ya expone `log_dir`. Si el panel dejara de ser local, esto habría que revisarlo (y con el
  token del puerto ya puesto, ese puerto puede exigir credencial).
- **La tarjeta no se ha visto en un navegador real.** Su lógica se ejerció con node sobre un DOM
  mínimo, que cubre qué se pinta, pero no cómo se ve.
