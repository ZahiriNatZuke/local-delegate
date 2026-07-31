# Verification: Check de doctor sobre los clientes MCP observados

## Environment

- Revision base: `023573b` (`main`), rama de trabajo del change.
- Windows 11, Python 3.11 (uv), pytest, ruff, node v24.18.0.
- Cliente real usado para medir: Claude Code **2.1.220** por *stdio*.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | check `client.observed`, grupo `entorno`, tras `client.presence` | OK | `checks.py` CHECKS; `doctor` real lo imprime en «Entorno» |
| REQ-002 | la fuente es `clients.jsonl`, no `/api/status` | OK | `_default_clients_seen` usa `clients.ruta_registro()`; verificado en ejecución cambiando `LOCAL_DELEGATE_LOG_DIR` |
| REQ-003 | colaborador inyectable con `(valor, motivo)` | OK | campo `clients_seen` en `Context`; tests lo doblan |
| REQ-004 | el probe no escribe | OK | `test_no_probe_writes_anything` + `test_default_no_crea_ni_el_directorio_ni_el_fichero` |
| REQ-005 | sin observaciones → `unknown` | OK | `test_sin_clientes_vistos_es_unknown_y_no_suma_aviso`; **ejecución real**: `[ -- ] clientes MCP observados: todavía no ha hablado ningún cliente MCP…`, `exit=0` |
| REQ-006 | ilegible → `unknown` + motivo | OK | `test_registro_ilegible_es_unknown_con_el_motivo` |
| REQ-007 | con observaciones → `ok` siempre | OK | `test_un_cliente_que_sabe_preguntar_sale_ok`, `test_un_cliente_sin_elicitation_sigue_siendo_ok` |
| REQ-008 | un cliente por nombre, el más reciente | OK | `test_el_mismo_cliente_repetido_sale_una_vez_…`; **ejecución real** con el registro medido: `[ OK ] clientes MCP observados: claude-code 2.1.220 [2025-11-25] elicitation` |
| REQ-009 | líneas inválidas se saltan | OK | `test_default_lee_el_registro_y_salta_lo_que_no_sirve` (blanco, truncada y no-objeto) |
| REQ-010 | sin `fix_hint` | OK | `test_client_observed_no_ofrece_arreglo` |
| REQ-011 | salida en cp1252 | OK | `test_el_detail_es_imprimible_en_la_consola_de_windows` (nombre con emoji y guion largo) |
| REQ-012 | el módulo no miente sobre su tamaño | OK | `test_el_docstring_dice_cuantos_checks_hay_de_verdad` con `_NUMERO[15]` |
| REQ-013 | no se repara | OK | `test_client_observed_no_se_repara_nunca` |
| REQ-014 | wiki actualizada | OK | `docs/wiki/Integration-install.md`: «quince piezas» + fila nueva |

### Ejecución real, los dos casos

```
# LOG_DIR real de esta máquina (sin registro: el daemon publicado es 0.17.0)
[ -- ] clientes MCP observados: todavía no ha hablado ningún cliente MCP con este local-delegate
exit=0

# LOG_DIR con la observación medida de Claude Code real por stdio
[ OK ] clientes MCP observados: claude-code 2.1.220 [2025-11-25] elicitation
exit=0
```

### Verificación de los tests al revés

Nueve defectos introducidos uno a uno, restaurando el fichero entre cada uno. **Los nueve rompen el
test que dice cubrirlos** (no solo «algún test»):

| Defecto introducido | Test que se pone rojo |
| --- | --- |
| `caps` sin comprobar el tipo (falso positivo por subcadena) | `test_caps_que_no_es_lista_no_cuenta_como_elicitation` |
| sin deduplicar | `test_el_mismo_cliente_repetido_sale_una_vez_…` |
| agrupa pero ignora el `ts` (gana la última) | `test_el_mismo_cliente_repetido_sale_una_vez_…` |
| sin agrupar (cada línea al detail) | `test_el_mismo_cliente_repetido_sale_una_vez_…` |
| sin datos reportado como `MISSING` | `test_sin_clientes_vistos_es_unknown_y_no_suma_aviso` |
| sin sanear a cp1252 | `test_el_detail_es_imprimible_en_la_consola_de_windows` |
| un cliente sin `elicitation` marcado `WARN` | `test_un_cliente_sin_elicitation_sigue_siendo_ok` |
| `ts` ilegible sin tolerancia | `test_un_ts_ilegible_no_tumba_el_check` |
| el JSONL acepta lo que no es objeto | `test_default_lee_el_registro_y_salta_lo_que_no_sirve` |

**Dos cosas que este ejercicio destapó y que sin él se habrían colado:**

1. **El primer script de mutación dio «nadie se entera» en 7 de 7** — y era mentira: pytest crea el
   `--basetemp` **sin `parents=True`**, así que los 147 tests daban `ERROR` de fixture y ninguno
   llegaba a ejecutarse. Un no-resultado no es evidencia si no se comprueba que la búsqueda podía
   encontrar algo. El script ahora distingue `error` de `failed` y aborta en vez de dar un verde
   falso.
2. **El test de deduplicación pasaba por la guarda equivocada.** Con la observación vieja **al
   principio** de la lista, cubría «agrupa por nombre» pero **no** «escoge la más reciente»: un
   check que se quedara con la última que ve pasaba igual. Se movió al final y se añadieron los dos
   mutantes que separan las dos mitades.

## Quality checks

- [x] Project-native tests pass — `uv run pytest -q`: **553 passed, 1 skipped** (eran 539).
- [x] Lint, formatting and build checks — `uv run ruff check .`: *All checks passed!*;
      `uv run ruff format --check .`: *61 files already formatted*;
      `scripts/extract_dashboard_js.py` + `node --check`: exit 0.
- [x] Secret scanning — el change no introduce credenciales, rutas privadas ni datos personales.
      Lo que el check muestra (nombre de cliente, versión, protocolo, nombres de capabilities) ya
      estaba en el registro y no incluye contenidos ni prompts.
- [x] No unrelated changes — ocho ficheros, todos justificados en el plan.

## Deviations and residual risk

- **`doctor --home <árbol>` sigue leyendo el `LOG_DIR` real.** Es deliberado y está en la spec:
  `LOG_DIR` no deriva de `HOME`, igual que ya ocurre con los checks de servicio y backend. No es el
  defecto del change C, que sí **escribía** fuera del árbol simulado; aquí solo se lee.
- **El check no se puede ver en `[ OK ]` en una máquina con la versión publicada** hasta que se
  publique `clients.py`, porque hoy nadie escribe el registro. Cubierto por ejecución real
  redirigiendo `LOCAL_DELEGATE_LOG_DIR` al registro medido con un cliente de verdad.
- **`clients.jsonl` crece sin límite** (una línea por arranque de proceso). El check lo tolera
  agrupando, pero la rotación del fichero queda **fuera de alcance** y anotada como pendiente para
  el backlog.
- **Solo se ha visto un cliente real en el registro** (Claude Code). El caso de dos clientes y el de
  un cliente sin `elicitation` están cubiertos por tests, no por medición en vivo; medirlo con
  Codex exige otra sesión de instrumentación y no cambia el diseño.
