# Brief: Parámetros extra por petición al backend (reasoning effort y extra body)

Modo: **SDD ligero** (decisión del usuario, 2026-10-19, backlog del vault §1.12 punto 1).

## Problem

Las tools `local_*` mandan al backend OpenAI-compatible (llama-swap / llama.cpp) solo los campos
fijos que arma el cliente. No hay forma de pasar parámetros extra por petición (p. ej.
`reasoning_effort`, `chat_template_kwargs`, `top_k`, `min_p`) sin tocar código. El fork
`magic-zagan/local-delegate` (PR cerrado, fork parado) propuso `LOCAL_DELEGATE_REASONING_EFFORT` y
`LOCAL_DELEGATE_EXTRA_BODY`. La investigación del 2026-10-19 concluyó: de ese fork solo vale esta
idea, **reescrita** con validación; lo demás (idioma, panel trilingüe, renombrado, CI) ya está
mejor resuelto en la 0.36.0.

## Desired outcome

El usuario puede configurar por variable de entorno parámetros extra que viajan en el cuerpo de
cada petición al backend, validados, sin poder pisar los campos que controla el producto, y
documentados en es/en.

## In scope

- `LOCAL_DELEGATE_REASONING_EFFORT` y `LOCAL_DELEGATE_EXTRA_BODY` (JSON objeto), validadas al leer.
- Claves reservadas que el extra no puede pisar: como mínimo `model`, `messages`, `stream`,
  `max_tokens`/tope, `tools`, y las que fije el producto (p. ej. `response_format` del esquema JSON).
- Aviso/error claro (catálogo i18n es/en) ante JSON inválido o clave reservada.
- Tests, wiki (`docs/wiki/`), README y CHANGELOG (regla de release: tres sitios).

## Out of scope

- Parámetros por tool o por rol (salvo que la investigación muestre que es imprescindible).
- Cualquier otra cosa del fork. Cambios en el catálogo de modelos o en llama-swap.
- Dependencias nuevas.

## Constraints and risks

- **Todo el código en inglés**; solo los textos de salida para personas en es/en vía catálogo i18n.
- No romper el contrato existente de peticiones (esquema JSON `LOCAL_DELEGATE_JSON_SCHEMA=auto`,
  troceado, reintentos, fallback).
- Sin secretos en specs, logs ni memoria. El extra body podría contener datos sensibles: no
  loguearlo entero.
- El repo mezcla LF y CRLF fichero a fichero: respetar el fin de línea de cada fichero
  (`git ls-files --eol`), nunca `write_text` a ciegas.
- Commits firmados; sin coautoría de Claude en commits (regla del usuario).

## Decisiones del usuario (2026-10-20)

Sustituyen al alcance inicial de «dos variables» donde choquen. El cambio deja de ser ligero.

1. **Por rol** (`mechanical`, `long`, `code`, `vision`), no global.
2. **Lista cerrada de parámetros permitidos**, validados por tipo/rango, en dos grupos
   configurables: **muestreo** (`temperature`, `top_k`, `top_p`, `min_p`, penalizaciones…) y
   **razonamiento** (`reasoning_effort`, `chat_template_kwargs`/`enable_thinking`, …). Lo demás no
   es configurable: las claves del contrato de la tool (`model`, `messages`, `stream`,
   `max_tokens`, `response_format`, `json_schema`, `grammar`, `tools`, `n`, `stop`, `logprobs`)
   y las de servidor (`cache_prompt`, `id_slot`, `n_keep`, `samplers`, `seed`). Una clave fuera
   de la lista se **quita sola** (no el resto) con aviso que no repite valores.
3. **Temperatura**: sin configurar, cada tool conserva la suya (classify/extract 0, boilerplate
   0,1, resto 0,2). Configurada para un rol, la pisa en las tools de ese rol. Un cambio se mide con
   el benchmark de afinidad antes de darlo por bueno (documentarlo).
4. **Fichero + comando**, como `language.json` (p. ej. `local-delegate backend-params set code
   reasoning_effort high`); variables de entorno solo como override puntual.
5. **El modelo frontera no puede fijar nada** de esto: las tools no ganan argumentos.
6. **Verificación en vivo** de que `reasoning_effort` por petición vence a `--reasoning off` de
   llama-swap.
7. **Visible en el panel** (pedido del usuario, 2026-10-20): en la lista de delegaciones se ve qué
   llamada llevó parámetros particulares y, sobre todo, si **razonó**. El log de uso guarda qué
   parámetros se aplicaron (lista cerrada: nombres y valores sin riesgo de datos sensibles) y si
   la respuesta trajo razonamiento (p. ej. `reasoning_content` o tokens de razonamiento). Reglas
   del panel: es un dashboard, sin prosa; el detalle va en el diálogo; campos en inglés con lectura
   del formato viejo; verificar con capturas en claro y oscuro.
8. **`local_delegate` con modelo explícito no lleva parámetros** (2026-10-20, tras la segunda
   ronda): están pensados para el modelo de cada rol.
9. **Razonamiento sin presupuesto se rechaza** en `backend-params set` (y se ignora con aviso si
   llega así por fichero editado a mano o por variable). El razonamiento se enciende con
   `chat_template_kwargs.enable_thinking` + presupuesto; `reasoning_effort` solo no lo enciende
   (medido en vivo, `research.md` segunda ronda). El presupuesto **se suma** al tope de cada tool.
10. **El `--reasoning-effort` del benchmark, que no tiene efecto, se arregla en este cambio**
    como tarea propia del plan: se necesita para medir los cambios de temperatura/razonamiento.
11. **Documentación (wiki, README, CHANGELOG) solo en español** (2026-10-20). El es/en se cumple en
    los textos de salida del catálogo i18n. Traducir la documentación sería otro cambio.

## Reglas para todo agente de este cambio

1. **Primer paso**: cargar las tools de local-delegate con
   `ToolSearch("select:mcp__local-delegate__local_summarize,mcp__local-delegate__local_extract,mcp__local-delegate__local_lint_summary,mcp__local-delegate__local_boilerplate,mcp__local-delegate__local_commit_msg,mcp__local-delegate__local_explain_code")`.
   Antes de empezar, decidir qué pasos van por `local_*` (resumir ficheros grandes con `path`,
   salida de tests/lint volcada a fichero → `local_lint_summary(path=…)`, explicar código, borrador
   de commit). En la entrega, **listar las llamadas `local_*` hechas** («0» exige motivo).
   Si el MCP no responde o devuelve `[local-delegate error]`, hacerlo a mano y seguir.
1b. **Ficheros grandes**: `local_explain_code`/`local_summarize` solo sobre ficheros de menos de
   ~50 KB o con una pregunta que abarque el fichero entero; en ficheros gigantes (`server.py`
   pesa 250 KB y tarda ~9 min en 22 trozos), localizar antes con `grep` y leer la franja. Si una
   llamada `local_*` tarda, esperar hasta 10 min antes de abandonarla. Donde más rinden en este
   cambio: salida de pytest/lint volcada a fichero → `local_lint_summary(path=…)`, diff →
   `local_commit_msg(path=…)`, y resumir con `focus` documentos que no hay que citar literal.
2. **Comandos pesados** (pytest, builds, `uv sync`) de uno en uno con el cerrojo, desde la tool
   Bash: `bash ~/.claude/scripts/pesado.sh <comando>`. Salida larga a fichero.
3. **Nada huérfano**: al terminar, ningún shell, servidor ni espera en segundo plano lanzado por el
   agente queda vivo. Toda espera con tope de tiempo. Confirmarlo en la entrega.
4. No tocar ficheros fuera de los asignados. No editar `state.json` a mano.
5. Entregas y comunicación **en español**.

## Open questions

- ¿Dónde se construye hoy el cuerpo de la petición y qué claves pone el producto? (investigación)
- ¿`reasoning_effort` lo entiende llama.cpp/llama-swap tal cual, o hace falta
  `chat_template_kwargs`? (investigación)
- ¿El extra va a todos los roles por igual? ¿Se refleja en `doctor`?
