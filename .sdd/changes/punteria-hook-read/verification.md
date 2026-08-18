# Verification

## Checks del proyecto

| Check | Resultado |
|---|---|
| `uv run pytest` | **752 passed, 2 skipped** |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 75 files already formatted |

`tests/test_hook_recipes.py` pasa de 5 a 12 tests.

## Los tests fallan por la razón que dicen

Dos mutantes, aplicados uno a uno sobre el fichero limpio (el primer intento los acumuló por un
backup a una ruta que no existía; se repitió el segundo en limpio):

| Mutante | Tests que fallan | ¿Los correctos? |
|---|---|---|
| Se cae la guarda de código (`if False`) | `calla_ante_codigo`, `registra_los_descartes` | sí, y sólo esos |
| El hook no sugiere nunca (`if True`) | `can_be_enabled_explicitly`, `sigue_avisando_del_caso_que_vale_la_pena` | sí |

El segundo mutante es el que justifica el control anti-vacío: los tres tests de "no sugiere"
siguen en verde con un hook que no sugiere nada. Sin `sigue_avisando_del_caso_que_vale_la_pena`,
ese fallo pasaría entero.

## La regla nueva, medida contra el uso real

Simulación **importando el módulo real** (`extension_de`, `es_lectura_acotada`,
`EXTENSIONES_DE_CODIGO`), no reimplementando las reglas, sobre las 852 lecturas de los transcripts
cuyo archivo sigue en disco:

| | lecturas |
|---|---|
| descarte: acotada | 520 |
| descarte: código | 218 |
| descarte: pequeño (≤32 KB) | 85 |
| **avisa: suggest** | **15** |
| **avisa: strong** | **14** |

**572 → 29 avisos.** Un 95 % menos, y el objetivo de la spec clavado.

## Prueba en vivo, con el script real y archivos reales

Ejecutando `suggest_delegate_read.py` por stdin, fuera de pytest:

| Entrada | Salida | Telemetría |
|---|---|---|
| `CHANGELOG.md` (116 KB, entero) | `Recomendacion fuerte` | `suggested: true, band: strong, ext: ".md"` |
| El mismo con `offset`/`limit` | silencio | `suggested: false, ext: ".md", motivo: "acotada"` |
| `server.py` | silencio | `suggested: false, ext: ".py", motivo: "codigo"` |

Ninguna línea del log contiene ruta ni nombre de archivo.

## Requisitos

| REQ | Evidencia |
|---|---|
| REQ-001 | `test_read_hook_respeta_una_franja_pedida_a_proposito` + prueba en vivo (fila 2) |
| REQ-002 | `test_read_hook_calla_ante_codigo` + mutante 1 + `EXTENSIONES_DE_CODIGO` es constante de módulo |
| REQ-003 | defaults `32`/`100` en el módulo; `docs/recipes/claude-code-hooks.md` actualizado |
| REQ-004 | `test_read_hook_no_filtra_el_nombre_del_archivo_por_la_extension`; `extension_de` acota a 12 chars alfanuméricos |
| REQ-005 | no hay `permissionDecision` en el módulo; `test_read_hook_registra_los_descartes_para_poder_medir_punteria` |
| REQ-006 | `test_read_hook_is_disabled_by_default` y los de `test_install.py` siguen en verde sin tocarlos |

## Límite conocido

El hook instalado en `~/.claude/hooks/local-delegate/` es la copia de la 0.24.0. En esta máquina el
cambio no surte efecto hasta reinstalar el paquete; hasta entonces el ruido sigue igual.
