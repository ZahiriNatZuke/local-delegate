# Implementation plan: local-delegate install --agents mantiene los subagentes al dia con el catalogo real

## Approach

Módulo nuevo, `agents.py`, y no más código dentro de `install.py` —que ya lleva 700 líneas—. El
módulo contiene la lógica pura (parsear el catálogo, decidir qué cambia en un texto) y `install`
solo aporta la acción y la escritura, que es el mismo reparto que ya ordena `checks` / `install`.

La lógica de la receta **se porta, no se reinventa**: sus heurísticas están escritas con cuidado
—en particular la de «si no reconozco la sección, no inserto»— y llevan tiempo funcionando sobre
27 agentes reales. Lo que cambia es de dónde sale el catálogo.

El componente se llama `agents` y entra en `_ALL_COMPONENTS` **sin** estar en el default: es el
primer componente opt-in del instalador, y esa asimetría es deliberada — los subagentes son del
usuario, no andamiaje nuestro.

## Ordered tasks

### 1. El catálogo, derivado y verificado

- **Ficheros:** `src/local_delegate/agents.py` (nuevo), `tests/test_smoke.py`
- **Requisitos:** REQ-001..REQ-004
- **Qué:** `tool_catalog()` que parsea las filas `| \`local_x\` | descripción | … |` de
  `SKILL.md` y devuelve `[(nombre, descripción)]`; y el **test de paridad** que compara sus
  nombres con `{t.name for t in server.mcp.list_tools()}`.
- **Cuidado:** el test va en `test_smoke.py`, junto a `test_eleven_tools_registered`, que es donde
  ya vive «cuántas tools hay»; ponerlo en otro sitio separaría dos afirmaciones sobre lo mismo.
- **Verificación:** el test de paridad, más uno de que el parseo devuelve once entradas con
  descripción no vacía.
- **Rollback:** módulo nuevo y aislado.

### 2. La lógica de los agentes, portada

- **Ficheros:** `src/local_delegate/agents.py`
- **Requisitos:** REQ-006..REQ-009, REQ-017
- **Qué:** `is_delegator`, `update_tools_line`, `update_catalog_block` y `process(text)`, portadas
  de la receta con el catálogo inyectado en vez de constante. Marcadores
  `<!-- local-delegate:catalog:begin/end -->` (los mismos, para que los agentes ya tratados por la
  receta se reconozcan).
- **Cuidado:** **conservar la prudencia del original**: sin sección de delegación reconocible no
  se inserta. Y el borde nuevo de la spec: marcadores desparejados → no se reemplaza nada.
- **Verificación:** tests de cada rama sobre textos, sin tocar disco.

### 3. La acción y el flag

- **Ficheros:** `src/local_delegate/install.py`, `src/local_delegate/cli.py`
- **Requisitos:** REQ-005, REQ-010..REQ-014
- **Qué:** `_agents_action(...)` en `install.py` que planifica **solo si hay algo que cambiar**;
  `agents` en `_ALL_COMPONENTS` pero **fuera del default**; flag `--agents` en el parser.
- **Cuidado:** la escritura usa `_write_text`, que ya deja `.bak` y conserva el terminador de
  línea —importante en Windows, donde escribir con el de la plataforma marcaría el fichero entero
  como modificado—.
- **Verificación:** los seis escenarios.

### 4. Retirar la receta

- **Ficheros:** `docs/recipes/update_agents.py`
- **Requisitos:** REQ-015
- **Qué:** `git rm`, y revisar si algún índice de `docs/` la enlaza.

### 5. Tests

- **Ficheros:** `tests/test_agents.py` (nuevo), `tests/test_install.py`
- **Requisitos:** todos
- **Qué:** los seis escenarios y los bordes de la spec. El de AC-2 —el agente ajeno— compara
  **byte a byte** y comprueba que no hay `.bak`.
- **Verificación al revés:** quitar la comprobación del ancla debe hacer fallar AC-2; quitar el
  guard de «sección reconocible» debe hacer fallar el borde correspondiente.

### 6. CHANGELOG y wiki

- **Ficheros:** `CHANGELOG.md`, `docs/wiki/Integration-install.md`
- **Requisitos:** REQ-016
- **Qué:** entrada en `Added` y `Removed`; en la wiki, el flag en la tabla de opciones y una nota
  de qué hace.

### 7. CI local y ejecución real

- **Requisitos:** todos
- **Qué:** los cuatro pasos; `install --agents --dry-run` contra un HOME simulado con agentes
  copiados; y —si el usuario lo autoriza— contra sus 27 agentes reales, que es el banco de
  pruebas de verdad.

## Test strategy

- **Unit:** el parseo del catálogo y `process()` sobre textos, sin disco.
- **Integration:** `plan_install` + `apply` sobre un `tmp_path` con varios agentes: uno que
  delega y está viejo, uno ajeno, uno sin sección reconocible.
- **End-to-end:** `--dry-run` contra los agentes reales (solo lectura).
- **Verificación al revés:** las dos permutaciones de la tarea 5.
- **Seguridad:** el `.bak` y la comprobación del ancla son las salvaguardas; los tests las fijan.

## Migration and compatibility

- **Los agentes ya tratados por la receta se reconocen**: mismos marcadores, mismo ancla. La
  primera pasada del CLI solo actualizará el contenido del bloque.
- **Sin cambio de comportamiento por defecto:** `install` sin `--agents` hace exactamente lo de
  antes.

## Revisión adversarial del plan

Cinco hallazgos; dos bloqueantes, todos incorporados.

- **R-1 (BLOQUEANTE) — el test de paridad tiene que comparar en las dos direcciones.** Comprobar
  solo que cada tool del servidor esté en la tabla dejaría pasar una fila sobrante en `SKILL.md`
  —una tool retirada del servidor que sigue anunciada al usuario y que `--agents` propagaría a 27
  agentes—. La comparación es de **conjuntos iguales**, no de inclusión.
- **R-2 (BLOQUEANTE) — `_ALL_COMPONENTS` alimenta también a `plan_uninstall` y a `update`.**
  Añadir `agents` ahí sin mirar los consumidores podría hacer que `uninstall` intente retirar algo
  para lo que no hay lógica, o que `update` lo repare por su cuenta. Hay que **verificar los tres
  consumidores** (`cli._install_options`, `plan_uninstall`, `update.plan_repairs`) antes de tocar
  la tupla, y dejar `agents` fuera de lo que no le corresponde.
- **R-3 — el `.bak` de un agente puede confundir al propio Claude Code**, que lee
  `~/.claude/agents/*.md`. Un `agente.md.bak` no casa con `*.md`, así que no se carga: comprobado
  por la extensión. Queda anotado porque la pregunta es razonable y no volverá a hacerse.
- **R-4 — la descripción de la tabla lleva markdown** (`**o**`, backticks). Al meterla en el
  párrafo del catálogo hay que decidir si se limpia; se conserva tal cual, porque el destino es
  también markdown y limpiarlo sería inventar reglas de transformación.
- **R-5 — no suponer qué enlaza a la receta.** Buscar referencias a `update_agents` en `docs/`
  antes de borrarla, no después. Es la lección del change anterior.

## Plan review

- [x] Cada requisito mapea a una tarea y a una verificación.
- [x] **La operación de riesgo —escribir en ficheros del usuario— tiene cuatro salvaguardas**:
      opt-in, ancla obligatoria, `.bak`, y bloque delimitado; las cuatro con test.
- [x] Sin dependencias nuevas.
- [x] Sin trabajo ajeno: no se toca la skill, ni el formato de los agentes, ni se añade
      `uninstall --agents`.
