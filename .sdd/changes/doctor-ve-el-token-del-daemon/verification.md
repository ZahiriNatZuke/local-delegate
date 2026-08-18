# Verification

## Checks del proyecto

| Check | Resultado |
|---|---|
| `uv run pytest` | **769 passed, 2 skipped** (eran 762) |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 75 files already formatted |

## Contra la máquina real: la avería reproducida y deshecha

Es la prueba que decide, porque el check existe para ver algo que hoy no se veía.

| estado de `~/.claude.json` | `doctor` decía antes | dice ahora |
|---|---|---|
| con `headers.Authorization` | todo a punto | `[ OK ] el puerto del daemon exige token y las entradas MCP lo referencian` |
| **sin la cabecera** (la avería de hoy) | **todo a punto** | `[WARN] el puerto del daemon exige token y Claude Code entra por HTTP sin cabecera de autorización: sus tools local_* responderán 401` — y el resultado global pasa a «1 aviso(s)» |
| restaurado desde el backup | — | vuelve a `[ OK ]` |

El `.claude.json` se copió antes de tocarlo y se restauró byte a byte; la entrada quedó como
estaba.

## Los tests fallan por la razón que dicen

Dos mutantes, uno a uno sobre el fichero limpio, con el backup verificado por tamaño antes de
mutar:

| Mutante | Falla | ¿Sólo eso? |
|---|---|---|
| El probe nunca avisa (`ciegas = []`) — el comportamiento viejo | `test_una_entrada_http_sin_cabecera_contra_un_daemon_con_token_avisa` | sí, 1 de 80 |
| El probe avisa siempre (el `return OK` final pasa a `WARN`) | `test_una_entrada_bien_autenticada_no_molesta` | sí, 1 de 80 |

El segundo es el que justifica el control anti-vacío: los seis tests de «no avisa» seguirían en
verde con un check que avisara siempre, que es el fallo opuesto y el que enseña a ignorar un
diagnóstico.

El primer intento del mutante 2 **no llegó a aplicarse**: el ancla `if not exige:` aparece también
en `_probe_mcp_credential`, y el assert de unicidad lo paró antes de medir nada. Se repitió con un
ancla del probe nuevo.

## Un fallo del propio test que el check destapó

`test_una_entrada_bien_autenticada_no_molesta` falló al escribirlo, y tenía razón el check:
*«el puerto del daemon exige token y **Codex y opencode** entran por HTTP sin cabecera»*. El
helper sólo arreglaba la entrada de Claude Code, porque `make_home` escribe los tres clientes en
HTTP sin cabecera. Con el helper a medias, el control anti-vacío habría medido otra cosa. Se
arregló dejando los tres autenticados **con las funciones de `install`**, no con literales.

## Requisitos

| REQ | Evidencia |
|---|---|
| REQ-001 | El check está en `servicio`; `andamiaje` no cambia |
| REQ-002 | `test_un_daemon_abierto_no_genera_ruido` y `test_no_poder_preguntar_al_puerto_es_unknown_y_nunca_missing` |
| REQ-003 | `test_una_entrada_http_sin_cabecera_contra_un_daemon_con_token_avisa` + la prueba en la máquina real |
| REQ-004 | `test_codex_se_autentica_por_su_propia_clave_y_tambien_vale`; el helper de los tres clientes ejercita las tres formas |
| REQ-005 | `test_una_entrada_stdio_no_cuenta_como_ciega` |
| REQ-006 | `test_la_cabecera_esta_pero_la_variable_no_se_avisa_como_sospecha`, que exige que el texto diga «este proceso» |
| REQ-007 | El probe no lanza; `run_all` convierte cualquier fallo en `unknown` (contrato ya cubierto por `tests/test_checks.py:365`) |

## El guardián del conteo

El registro pasa de 17 a 18 checks. `tests/test_checks.py` compara **cinco afirmaciones** del
docstring de `checks.py` contra `len(CHECKS)`; se actualizaron las cinco y se añadió
`18: "dieciocho"` al mapa. Ese test existe porque el módulo llegó a decir «once» con doce checks
dentro y alguien planificó sobre el dato falso.

## Higiene

`git diff --stat` y `git diff --ignore-cr-at-eol --stat` dan idéntico: cero ruido de finales de
línea.
