# Brief: Renombrado a inglés de lo publicado y salidas en español e inglés

Brief común para la sesión principal y para todo agente de cualquier fase de este cambio. Un
agente lee **este fichero**, no el `CLAUDE.md` global ni el `MEMORY.md` entero.

## Problem

El paquete publicado (hasta la 0.34.0) tiene miles de identificadores y términos de máquina en
español: módulos (`atribucion.py`, `cuota.py`, `recalcular.py`…), funciones, subcomandos y
opciones del CLI (`recalcular-coste`, `--reiniciar-calibracion`), variables de entorno
(`LD_HOOK_READ_BLOQUEAR`…), campos JSON persistidos (`bloqueo_id`, `secciones`,
`fallo_conexion`…), endpoints, ids de checks (`config.coste`, `config.rol_retirado`), ficheros
(`local-delegate-bloqueo-apagado`) y el contrato `_local_delegate` de `local_extract`. Eso choca
con la regla del usuario del 2026-10-07: **todo código y término de máquina en inglés; en
español solo los textos que lee una persona y la prosa**.

Además, los textos de salida (CLI, `doctor`, `local_status`, salidas de las tools MCP, panel)
solo existen en español. El usuario lo subió a prioridad alta el 2026-10-08: selector de idioma
en el panel y salida del CLI en español e inglés.

## Desired outcome

1. **Frente A — renombrado:** todo identificador y término de máquina publicado queda en inglés,
   sin romper a quien ya tiene la versión anterior instalada ni los datos ya escritos.
2. **Frente B — idioma:** todo texto de salida para personas existe en español e inglés; el panel
   tiene selector de idioma y el CLI imprime en el idioma elegido. Los comandos y opciones **no**
   se traducen (ya estarán en inglés tras el frente A).

Orden obligatorio: **A antes que B**, para no tocar dos veces las ~1 100 cadenas.

## Decisiones ya tomadas por el usuario (no reabrir)

- `recalcular-coste` y `--reiniciar-calibracion` se renombran con el **nombre viejo como alias
  temporal**, y el aviso de `doctor` apunta al nombre nuevo.
- No vale el argumento «ya estaba en español» para dejar un nombre: es deuda que se corrige.
- Lo publicado va en este SDD propio (el renombrado de lo no publicado ya se hizo en su rama).
- El MCP no se ata al setup propio (otros usuarios conectan desde cualquier Windows o Linux).

Decisiones del 2026-10-12, tras la investigación del frente B:

- **Idioma por defecto:** el del sistema; si no es español, inglés de reserva.
- **Descripciones de las tools MCP y de sus parámetros:** pasan a **solo inglés** (no bilingües).
  Consecuencia aceptada: cambia el texto con el que se midió la adopción; el cambio de
  descripciones se marca como frontera de tramo en las mediciones.
- **Entran en el frente B también:** las respuestas del modelo local (los prompts piden responder
  en el idioma elegido, como ya hace `local_commit_msg`) y la skill `delegacion-local` con el
  bloque gestionado de `CLAUDE.md` (la detección del bloque no puede depender de su título en
  español, hoy `agents.py:41`).
- **Fuera:** README, `docs/wiki/` y CHANGELOG siguen en español (cambio aparte).
- **Alias de nombres viejos** (comandos, opciones, variables de entorno): funcionan con aviso
  durante dos versiones menores tras la que los renombra y se retiran en la tercera. Los datos ya
  escritos en disco se leen en el formato viejo **para siempre** (no se reescriben).
- **Tests y scripts del repo entran en este SDD**, en olas finales tras lo publicado.

Decisiones técnicas de la sesión principal (2026-10-12, sobre las preguntas de `research-rename.md`;
el revisor de la spec puede impugnarlas con evidencia):

- **Datos persistidos:** lectura dual (nombre viejo y nuevo) para siempre; sin migración en el
  sitio. Escritura solo en el formato nuevo.
- **Medición P-4:** no se congela nada; `enfriamiento-eventos.jsonl` y los valores de clase de
  error pasan a inglés y `medir_enfriamiento.py` lee los dos formatos, con un test que lo
  demuestre sobre filas de los dos formatos.
- **Valores de enumeración persistidos** (`error_class`, causa de conexión, `motivo`, `cruce`,
  etc.) **entran**: son término de máquina. Lectura dual.
- **Prosa guardada como valor** (`fallback_reason`, `marcas`, etiquetas de ventanas): es texto
  para personas → frente B; lo ya escrito se muestra tal cual.
- **Contrato de salida para modelos** (`_local_delegate` de `local_extract`, marcadores
  `[local-delegate aviso|respaldo:]`): cambio de una vez, anunciado en el CHANGELOG, a la vez
  que las descripciones de las tools en inglés (sus lectores son modelos que leen esa misma
  descripción). Sin emisión doble.
- **Skill `delegacion-local`:** se renombra; `install` gana un mecanismo de skills retiradas
  análogo a `_SCRIPTS_RETIRADOS`, y el bloque gestionado se regenera con el nombre nuevo.
- **`cuota-statusline.jsonl`:** contrato con código externo del usuario: se acepta el nombre
  viejo y el nuevo al leer.
- **Aviso de nombres obsoletos:** se generaliza `config.rol_retirado` en un check único de nombres
  obsoletos (variables, opciones); la wiki y su test se ajustan en la misma ola.
- **Cookie `ld_sesion`:** se renombra; se acepta una reautenticación.

## Constraints and risks (conocidos)

- **Formatos persistidos** que habrá que seguir leyendo en el formato viejo: `usage-*.jsonl`
  (`bloqueo_id`, `secciones`, `fallo_conexion`, valores de `error_class`/`fallback_class`),
  `enfriamiento-eventos.jsonl` (lo lee la medición P-4, **abierta hasta los 90 días desde
  2026-09-15**), telemetría de hooks (~29 700 líneas con `bloqueo`, `camino`, `motivo`…), cachés
  `atribucion-*.json` y `coste-agregados.json`, `precios.json`/`densidad.json` del paquete,
  `test-windows.json`.
- **La Mac** escribe el formato viejo hasta que el usuario la actualice.
- Variables de entorno publicadas: alias + aviso de obsoleta (`LD_HOOK_READ_BLOQUEAR`,
  `LD_HOOK_READ_INTERRUPTOR`, `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO`,
  `LOCAL_DELEGATE_COSTE_RESPALDO`). Ojo: la suite se aísla del entorno vía
  `config.VARIABLES_DE_ENTORNO` y los helpers `_env*`.
- Hooks instalados en `~/.claude/hooks/`: un script renombrado deja el viejo vivo salvo que vaya
  a `_SCRIPTS_RETIRADOS` en `install.py`.
- El panel tiene un espejo JS de `_accounting` atado por un test de paridad que corre node: dos
  fuentes del mismo dato.
- `docs/wiki/` tiene tests que comparan la tabla del doctor contra `checks.CHECKS`. Una release
  toca CHANGELOG, README y `docs/wiki/`.
- El repo mezcla LF y CRLF fichero a fichero (`git ls-files --eol`); `write_text` convierte sin
  avisar.
- Commits firmados; `main` con ruleset; CodeQL bloquea y sus hilos se resuelven por GraphQL.
- Tamaño estimado el 2026-10-07: ~3 500 nombres, ~32 000 apariciones, 156 ficheros, 12–16 olas.

## Regla de ejecución: MCP `local-delegate` en todas las fases (requisito del usuario)

Este cambio mejora el propio MCP `local-delegate`, y el usuario exige **usarlo** en todas las
fases, en la sesión principal y en cada agente.

1. **Tipo de agente:** solo tipos con `mcp__local-delegate__local_*` en su lista (por ejemplo
   `general-purpose`, `python-scripting-specialist`). **No** usar `personal-sdd-implementer`,
   `personal-sdd-*-reviewer` ni `personal-sdd-researcher`: no tienen el MCP.
2. **Primer paso de todo agente:** cargar las tools (son diferidas):
   `ToolSearch("select:mcp__local-delegate__local_summarize,mcp__local-delegate__local_extract,mcp__local-delegate__local_lint_summary,mcp__local-delegate__local_boilerplate,mcp__local-delegate__local_commit_msg,mcp__local-delegate__local_explain_code,mcp__local-delegate__local_translate,mcp__local-delegate__local_classify")`.
   Si no cargan o devuelven `[local-delegate error]`, seguir sin ellas y decirlo en la entrega.
3. **Antes de empezar, el agente decide qué pasos le conviene delegar**: ficheros grandes con
   `path` (nunca leerlos enteros primero), salida de tests/lint/CI volcada a fichero y pasada por
   `local_lint_summary(path=…)`, extraer campos con `local_extract`, explicar código con
   `local_explain_code`, borrador de commit con `local_commit_msg`, borradores de traducción
   es→en con `local_translate` (frente B; **siempre revisados**, nunca pegados a ciegas).
4. **Entrega:** lista de llamadas `local_*` hechas (tool, para qué). «0» exige motivo.
5. **Pruebas en vivo contra el MCP/daemon:** se marcan con
   `local-delegate test-window start --label "…"` y `stop <id>` al acabar, para no ensuciar las
   métricas.
6. **Comandos pesados** (pytest, builds, installs, navegador headless) de uno en uno en toda la
   máquina con `bash ~/.claude/scripts/pesado.sh <comando>`.

## MCP de PyCharm para buscar y renombrar (habilitado por el usuario el 2026-10-12)

PyCharm está abierto con el proyecto `D:\Projects\local-delegate` indexado (comprobado:
`search_symbol` encuentra `RETIRED_FAST_ROLE_VARIABLES` en `config.py:244`). Sus tools
`mcp__pycharm__*` son diferidas: cargarlas con `ToolSearch("select:mcp__pycharm__rename_refactoring,mcp__pycharm__search_symbol,mcp__pycharm__search_text,mcp__pycharm__search_regex,mcp__pycharm__get_symbol_info,mcp__pycharm__analyze_calls,mcp__pycharm__get_file_problems,mcp__pycharm__lint_files")`.
Pasar siempre `projectPath: "D:\\Projects\\local-delegate"`.

- **Renombrar símbolos de código** (funciones, clases, variables, parámetros, constantes,
  módulos): `rename_refactoring`, que actualiza todas las referencias. Preferido sobre
  buscar-y-reemplazar.
- **Localizar antes de tocar:** `search_symbol` (definiciones), `analyze_calls` (quién llama),
  `get_symbol_info`, `search_text`/`search_regex` (texto exacto, más rápido que leer ficheros).
- **Comprobar después:** `get_file_problems` / `lint_files` en los ficheros tocados (referencias
  rotas, imports) antes de correr la suite.
- **Lo que `rename_refactoring` NO cubre** y va con búsqueda + edición explícita: claves y
  valores JSON (persistidos y de la API del panel), nombres de variables de entorno dentro de
  cadenas, subcomandos y opciones del CLI, ids de checks, nombres de fichero en disco, textos y
  claves del JS del panel si PyCharm no los resuelve, y docs/wiki. Tras cada rename, revisar el
  diff: puede haber tocado comentarios o cadenas que no debía (p.ej. lectura de formato viejo).
- **Recurso único:** PyCharm trabaja sobre el checkout `D:\Projects\local-delegate` (no ve
  worktrees). Solo **un agente a la vez** usa `rename_refactoring`, en ese checkout y en la rama
  de la ola; el resto de agentes de esa ola no edita en paralelo los mismos ficheros. Si PyCharm
  no responde, seguir con búsqueda + edición y decirlo en la entrega.
- **Entrega:** como con `local_*`, listar las llamadas `mcp__pycharm__*` hechas.

## Lecciones de las olas A0–A2 (aplicar en cada ola)

- `rename_refactoring` también reescribe documentos históricos de `.sdd/` (A1: 4, A2: 23). Tras
  cada rename, `git diff --stat -- .sdd` y devolver con `git checkout` lo que no sea de la ola.
- Un rename tradujo «donde»→«where» dentro de prosa española (A0). Revisar el diff buscando
  palabras inglesas coladas en comentarios, docstrings y textos en español.
- PyCharm no cambia cadenas de `monkeypatch.setattr(mod, "…")`, cargas por `importlib` ni algunos
  docstrings: buscarlos con `search_text` tras cada rename.
- **Código muerto tras reescribir una función** (A2: el cuerpo viejo de `_recent_block_id` quedó
  detrás del `return` nuevo; la suite no lo ve, CodeQL sí y bloquea el merge). Al reescribir una
  función, comprobar que no queda nada inalcanzable tras su `return`.
- Ficheros con shebang: `git update-index --chmod=+x` (si no, ruff EXE001 en Linux).
- `make_mapping.py` resuelve ya los imports planos entre hooks (A2). Nombres de una palabra
  ambigua más preposición (`version_de`) se le escapan al detector: incluirlos a mano si se ven.
- Las olas A van en serie: un cambio fuera de la propiedad de la ola que sea consecuencia mecánica
  del rename se hace y se registra como desviación; cualquier otra cosa, parar y preguntar.
- `local_commit_msg` tiende a salir en inglés y truncado: revisarlo y dejarlo en español.
- Un test de node que agota tiempo en el runner de Windows es inestabilidad conocida.

## Otras reglas que aplican a los agentes

- Todo en español en los entregables; nada de códigos internos sueltos como único nombre.
- No tocar `main` ni hacer push; no editar `state.json` a mano.
- Sin datos privados (rutas de usuario, tokens) en evidencias.
- Verificar los tests al revés (control positivo) y mirar qué assert dispara.

## Open questions

Se resuelven en `spec.md` con la investigación (`research.md`).
