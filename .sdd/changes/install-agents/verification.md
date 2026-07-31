# Verification: local-delegate install --agents mantiene los subagentes al dia con el catalogo real

## Environment

- **Revisión:** rama `feat/install-agents`, sobre `main` en `a556f04`.
- **Máquina:** Windows 11, Python 3.11 (uv). **27 subagentes reales** en `~/.claude/agents/` que
  declaran tools de local-delegate — el banco de pruebas de verdad.
- **Suite:** 478 tests, 1 skipped (463 al empezar el change; **+15**).

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | El catálogo se parsea de `SKILL.md` | OK | `agents.tool_catalog()` → 11 entradas con descripción no vacía |
| REQ-002 | **La skill no puede mentir** | OK | `test_la_tabla_de_la_skill_no_puede_mentir_sobre_las_tools`, en `test_smoke.py` junto a `test_eleven_tools_registered`; compara **conjuntos iguales**, no inclusión (hallazgo R-1) |
| REQ-003 | `install` no importa `server` | OK | `agents.py` solo importa `install`; el import de `server` está únicamente en el test |
| REQ-004 | El número sale del catálogo | OK | `f"{len(catalog)} tools"`; el bloque real dice «11 tools» |
| REQ-005 | Opt-in | OK | `test_sin_el_flag_no_se_toca_ningun_agente`: árbol byte a byte igual |
| REQ-006 | Solo los que declaran el ancla | OK | `test_un_agente_ajeno_queda_byte_a_byte_igual`, que además exige que **no exista `.bak`** — o sea que el fichero ni se abrió para escribir |
| REQ-007 | `tools:` completado sin reordenar | OK | test del agente que delega |
| REQ-008 | Bloque reemplazado o insertado | OK | `test_el_bloque_se_reemplaza_y_no_se_duplica` |
| REQ-009 | Sin sección reconocible no se inserta | OK | `test_sin_seccion_reconocible_no_se_inventa_donde_va_el_bloque` |
| REQ-010 | `.bak` | OK | test del agente que delega |
| REQ-011 | `--dry-run` | OK | test con `snapshot()` **y ejecución real** contra los 27 agentes |
| REQ-012 | Idempotencia | OK | `test_segunda_pasada_no_planifica_nada` |
| REQ-013 | Sin directorio de agentes | OK | `test_sin_directorio_de_agentes_no_hay_accion` |
| REQ-014 | El reporte dice cuántos | OK | ejecución real: «actualiza 27 subagente(s): …» |
| REQ-015 | La receta ya no está | OK | `git rm docs/recipes/update_agents.py` |
| REQ-016 | CHANGELOG y wiki | OK | entradas en `Added` y `Removed`; sección nueva en `Integration-install.md` y el flag en la tabla de opciones; `CRLF=936, LF sueltos=0` |
| REQ-017 | cp1252 | OK | `test_el_detalle_de_la_accion_cabe_en_la_consola_de_windows` |

### Ejecución real contra los 27 subagentes (solo lectura)

```
$ local-delegate install --agents --dry-run --no-hooks --no-skill --no-memory --no-mcp
componentes: agents
[dry-run] [agents] C:\Users\Yohan\.claude\agents — actualiza 27 subagente(s):
  ai-integration-orchestrator.md (+0 tools, catálogo replaced), … (27 en total)
```

`+0 tools` porque la receta ya les había añadido las suyas; lo que cambia es el bloque. El diff
exacto de uno de ellos, calculado sin escribir:

```diff
 <!-- local-delegate:catalog:begin -->
-**Catálogo de tools `local_*` (MCP `local-delegate`, 10 tools):** `local_summarize`
-(resumir), `local_classify` (etiquetar), … `local_status` (diagnóstico del backend).
+**Catálogo de tools `local_*` (MCP `local-delegate`, 11 tools):** `local_summarize` (resumir
+texto o archivo largo), … `local_describe_image` (describir una imagen o responder una
+pregunta sobre ella), `local_status` (diagnóstico de solo lectura).
 <!-- local-delegate:catalog:end -->
```

Once tools en vez de diez, `local_describe_image` incluida, y **nada fuera de los marcadores**.

### Verificación al revés — las dos salvaguardas

```
# quitada la comprobación del ancla:
FAILED tests/test_agents.py::test_un_agente_ajeno_queda_byte_a_byte_igual

# quitado el guard de «sección reconocible»:
FAILED tests/test_agents.py::test_sin_seccion_reconocible_no_se_inventa_donde_va_el_bloque
```

Cada una hace caer **exactamente** el test que existe para ella, y ninguno más.

## Quality checks

- [x] **Tests:** `uv run pytest -q` → **478 passed, 1 skipped**.
- [x] **Lint:** `uv run ruff check .` → *All checks passed!*
- [x] **Formato:** `uv run ruff format --check .` → *54 files already formatted*
- [x] **JS del dashboard:** `extract_dashboard_js.py` + `node --check` → OK.
- [x] **`--help`** muestra el flag nuevo.
- [x] **Secretos:** sin credenciales, sin red, sin subprocesos, sin dependencias nuevas.
- [x] **Sin cambios ajenos:** `agents.py` (nuevo), `install.py`, `cli.py`, dos ficheros de test
      (uno nuevo), el borrado de la receta, `CHANGELOG.md`, la wiki y la traza SDD.

### Hallazgo de CodeQL en el PR, y por qué se arregló en vez de silenciarse

El primer push del PR **no se pudo mergear**: `required_review_thread_resolution` del ruleset y dos
hilos abiertos por `github-advanced-security`.

```
CodeQL / Cyclic import
  src/local_delegate/agents.py:30  — import of local_delegate.install begins an import cycle
  src/local_delegate/install.py:529 — import of local_delegate.agents begins an import cycle
```

**Y tenía razón.** `agents.py` importaba `install` para saber dónde está la skill, mientras
`install` importa `agents` para planificar la acción. Funcionaba porque el segundo es diferido,
pero un ciclo que solo se sostiene por el orden de los imports es exactamente la clase de
fragilidad que este repositorio evita.

Arreglado invirtiendo la dependencia: `tool_catalog(skill_md)` y `pending(agents_dir, skill_md)`
**reciben** la ruta, e `install` se la pasa. Comprobado con `ast` que `agents.py` no importa nada
del paquete:

```
imports de agents.py: ['__future__', ['re'], 'pathlib']
```

Es mejor diseño del que había, no un parche: el módulo queda sin una sola dependencia del paquete,
que además es lo que lo hace trivial de probar.

**Lección para la próxima:** un merge `BLOCKED` con los 12 checks en verde no es un fallo de
infraestructura. `gh pr view --json reviews` y los `reviewThreads` de la API GraphQL dicen quién
bloquea; aquí era un review automático con dos comentarios sin resolver.

## Deviations and residual risk

- **Defecto encontrado por la ejecución real, no por los tests:** el primer `catalog_block` hacía
  `what.lower()` sobre la descripción, y eso convertía «lint/tests/**CI**» en «lint/tests/ci»,
  comiéndose los acrónimos de la tabla. Se corrigió a minúscula solo en la inicial, y hay un test
  que lo fija. **Solo se vio mirando la salida de verdad.**
- **La flecha `→` de la descripción de `local_delegate`** va al fichero (UTF-8, correcto) pero
  **no** al detalle que se imprime — eso lo garantiza el test de cp1252. Es el mismo bug que ya
  mató al `doctor` una vez en la consola de Windows.
- **Los 27 agentes reales no se han modificado.** Solo se ejecutó `--dry-run`; escribir en ellos
  se pide aparte.
- **`uninstall --agents` queda fuera**, por la razón escrita en la spec: qué hacer con las tools
  ya añadidas al `tools:` —que el usuario pudo editar— no tiene respuesta obvia.
- **`docs/Investigacion-empaquetado-publicacion-MCP.md`** sigue diciendo que `update_agents.py` va
  «fuera del paquete, como `docs/recipes/`». Es un documento de investigación fechado el
  2026-07-06, cuando el proyecto tenía 9 tools; **no se toca**, igual que el histórico del
  CHANGELOG, aunque este change revierta aquella decisión.
- **No verificado en macOS ni Linux** más allá del CI del PR; no hay nada específico de
  plataforma.
