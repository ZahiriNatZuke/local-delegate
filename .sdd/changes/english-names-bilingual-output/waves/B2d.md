# Ola B2d: muestras en vivo

Quinto PR de B2, en la rama `sdd/english-names-b2d` desde `origin/main` (`359af3b`). Ejecuta
«B2d» de `plan.md` y las decisiones 5 y 9 de `waves/B2-proposal.md` §11 contra el daemon vivo
(0.35.0 con B2a–B2c). Ventana de prueba **`w-20261014T215251Z`**, cerrada. Resultado: **una de tres
muestras cumple**. La de idioma de respuesta quedó **bloqueada** (el llama-swap pide clave al arnés
en proceso) y la de `local_explain_code` sobre `cli.py` **no cumple** (omite `doctor` y
`benchmark`). Sin cambios de código ni de prompts; sin commit, push ni PR. Detalle y salidas
literales en `evidence/B2d/live.md`.

## Qué se hizo

1. Lectura del diseño: `plan.md` («B2d», decisión 9), `waves/B2-proposal.md` §3.3, §5 y §11,
   `evidence/local-tools-review/report.md` y `scripts/detect_language.py`.
2. Comprobación previa del arnés en proceso (decisión 5): el llama-swap de `127.0.0.1:9292`
   responde **401** sin clave, tanto a `/v1/models` como a `/v1/chat/completions`, y la clave no
   está en el entorno del agente. Por la decisión 5 se para esa muestra y se pregunta; no se
   escribió arnés.
3. Ventana `w-20261014T215251Z` abierta y cerrada (21:52:51Z a 22:01:18Z).
4. `local_commit_msg` por el MCP vivo sobre los diffs de B0a y B1a.
5. `local_explain_code` por el MCP vivo sobre `src/local_delegate/cli.py` pidiendo los subcomandos.
6. Veredicto de idioma de los dos commits con `scripts/detect_language.py`.

## Corridas

| Muestra | Criterio | Resultado |
|---|---|---|
| Idioma de respuesta (REQ-028): producto `es` + variable `en` y producto `en` + variable `es`, 4 tools × ≥ 5 documentos | ≥ 90 % en el idioma pedido (detector, `min_tokens=20`, margen 0,15) | **bloqueada**: 401 del llama-swap fuera del daemon; `evidence/B2/lang-sample.json` con `status: blocked` y sin respuestas |
| `local_commit_msg`, diff de B0a | español, cuerpo de 2–6 viñetas | **cumple**: `es` (69 tokens, 0,29 frente a 0,03), 5 viñetas |
| `local_commit_msg`, diff de B1a | español, cuerpo de 2–6 viñetas | **cumple**: `es` (73 tokens, 0,38 frente a 0,01), 6 viñetas |
| `local_explain_code`, `cli.py` (58 875 caracteres) | nombra `doctor`, `benchmark` y `llamaswap`; sin aviso de truncado | **no cumple**: sin truncado (4 trozos) y con `llamaswap`, pero sin `doctor` ni `benchmark` |

## Observaciones y desviaciones

- **Muestra de idioma bloqueada.** Hace falta una decisión: un reinicio planificado del daemon por
  combinación (y `/mcp` después) o una vía para que el arnés herede la clave del lanzador sin verla.
  No se reinició nada, como pedía el encargo.
- **`explain_code` mejora pero no llega.** Frente a la 0.35.0 (truncaba a 20 000 y no nombraba
  `llamaswap`), ahora lee la entrada entera y lista 9 subcomandos. Faltan `doctor`
  (`cli.py:1343`) y `benchmark` (`cli.py:1231`, registrado con `benchmark.add_parser(sub)`, sin el
  literal en el fichero). Están en `build_parser()`, la misma función de `serve`, `recompute-cost` y
  `check-llamaswap`, que sí salen: la omisión pasa en el map-reduce (paso map de ese trozo o el
  reduce), no por pérdida de entrada. El inventario de nombres del paso final lista `def`/`class`,
  no subcomandos, así que no los rescata. Separar map de reduce exige ver las salidas parciales, que
  hoy no se registran.
- **No se repitió** la llamada de `explain_code`: RAM al límite (< 2 GB libres) y una repetición
  suelta no decide.
- **Sin muestra de `local_describe_image`**: no se llegó a preparar, porque la muestra entera quedó
  bloqueada antes de generar documentos.
- Ningún `.py` en `evidence/`. Los diffs y los mensajes juzgados quedaron en el scratchpad de la
  sesión; sus sha256 están en `evidence/B2d/live.md`.

## Llamadas `local_*`

| # | Llamada | Para qué | Resultado |
|---|---|---|---|
| 1 | `local_summarize(path=waves/B2-proposal.md, focus=…)` | mapa del diseño de B2d | sirvió para ubicar §5 y §11; las secciones normativas se leyeron literales después |
| 2 | `local_summarize(path=plan.md, focus=…)` | lote B2d y decisión 9 | confirmó el criterio de ≥ 90 % con idioma contrario |
| 3 | `local_status` | estado del daemon y del backend | idioma `es`, modelos, RAM al límite |
| 4 | `local_commit_msg(path=b0a.diff)` | muestra 2 | arriba |
| 5 | `local_commit_msg(path=b1a.diff)` | muestra 2 | arriba |
| 6 | `local_explain_code(path=cli.py, question=…)` | muestra 3 | arriba |
| 7 | `local_summarize(path=evidence/local-tools-review/report.md, focus=…)` | causas medidas antes de B2c | sirvió para comparar con la 0.35.0 |

## Llamadas `mcp__pycharm__*`

| # | Tool | Motivo |
|---|---|---|
| 1 | ninguna | motivo: B2d no edita código ni renombra; las comprobaciones de líneas de `cli.py` se hicieron con `grep` |

**Pasos hechos a mano y por qué:** §3.3, §5 y §11 de `B2-proposal.md` se leyeron literales con
`sed` porque son la norma de la ola y el resumen no conserva literales. Los encabezados y franjas de
`B2c.md` se leyeron con `sed`/`grep` para copiar el formato. Las líneas de `cli.py` donde se
registran `doctor` y `benchmark` se buscaron con `grep`: hacía falta el número de línea exacto para
el diagnóstico. El veredicto de idioma lo dio el detector (programa, no modelo).
