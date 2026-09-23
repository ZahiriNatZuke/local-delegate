# Verification: local_summarize respeta la estructura del documento (resumen por secciones)

## Environment

- Revisión: rama `feat/resumen-por-secciones`, commits `eb5cb84` (T0-T6) y `7b6c34d` (arreglo de
  la etapa 1).
- Windows 11, Python del proyecto con `uv`; daemon `local-delegate` 0.31.4 reinstalado desde la
  rama (`uv tool install --force --reinstall --no-cache ".[llamaswap]"`), comprobado que el
  paquete instalado lleva `secciones.py` y `_palabras_por_seccion`.
- Backend real: llama-swap con `gemma4-26b-a4b` (rol `long`) y `gemma3-4b` (rol `mechanical`).
- Hooks instalados: los de `main` (PR #220), tramo de versión desde 2026-09-23T12:56Z.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-201 | detección en las copias fijas y casos sintéticos; emparejamiento y completitud | pasa | `tests/test_resumen_estructurado.py` (T1, T2); etapa 1: 100 % de títulos en los cinco documentos |
| REQ-202 | `max_tokens` por trozo, reparto de palabras, completitud con `length`, aviso | pasa, con riesgo residual (palabras) | tests de T2/T4; etapa 1 sin cortes; palabras 399–602 para un tope de 500 |
| REQ-203 | documento largo por secciones, concat sin reduce, reintento por secciones | pasa | tests de T4; etapa 1: CHANGELOG 46/46, 5 llamadas, sin `length` |
| REQ-204 | payload sin títulos e interruptor apagado iguales al de `main` | pasa | `test_sin_titulos_el_payload_es_el_de_main`, `test_con_el_interruptor_apagado_…` |
| REQ-205 | `focus` saneado, en los dos modos y en el reduce en prosa; fuera del log | pasa | tests de T3; etapa 1 `daemon-focus` 5/5 y `focus: true` en el evento |
| REQ-206 | un evento con `chunks`, `secciones` y `focus`; rol por documento entero | pasa | tests de T4/T5; `tests/test_conformidad_f1.py` en verde |
| REQ-207 | descripción y docs | pendiente (T9) | — |
| REQ-208 | etapa 1 (sin cuota) y etapa 2 (con cuota) | etapa 1 pasa; etapa 2 en curso | secciones siguientes |

## Quality checks

- [x] Tests del proyecto: `uv run pytest -q` → 1442 passed, 2 skipped (tras `7b6c34d`).
- [x] `ruff check` y `ruff format --check` limpios en lo versionado (solo falla
  `benchmarks/catalogo-2026-09/resultados/`, sin seguimiento y de F2).
- [x] Mutantes (12, script en el scratchpad de la sesión): aceptar un solo título, contar títulos
  en vallas, no ignorar el front matter, emparejar cualquier línea, medir el contenido hasta
  cualquier título, quitar la completitud, quitar la lista del prompt, desactivar el postproceso,
  reduce por modelo en vez de concatenar, split genérico en el reintento, ignorar el `length` de
  un parcial y no sanear `focus`: todos hacen fallar al menos un test, el que les corresponde. El
  de «emparejar cualquier línea» sobrevivió al principio: el test de «mención en la prosa» no
  podía distinguirlo; se añadió uno con un párrafo que empieza por el título.
- [x] `server.py` conserva CRLF (0 LF sueltos); los ficheros nuevos, LF.
- [ ] Secret scanning: lo corre el hook de pre-commit en cada commit («Detect hardcoded secrets»:
  Passed).

## Etapa 1 (sin cuota) — 2026-09-23

`scripts/medir_resumen_estructurado.py` contra el `/mcp` del daemon, copias fijas de `95a65ee`,
`max_words` 500. Cobertura = títulos emparejados por línea de título y en orden, sin contar los
completados por el servidor.

**Línea base (daemon con el código de `main`)**, interrumpida por Claude Code por falta de memoria
del sistema tras 4 de 6 llamadas; las 4 salidas guardadas se midieron sin volver a llamar:
README 0/11, instalación 1/9, daemon 0/5, CHANGELOG 0/46. Control positivo: la métrica da bajo con
prosa. No se repitió la parte que faltaba (documento corto y `focus`, que contra `main` falla).

**Primera corrida con la rama (`eb5cb84`)**: README 11/11, instalación 9/9, daemon 5/5, corto (4B)
6/6, `focus` 5/5, todos con contenido y sin fuera de orden. **CHANGELOG 41/46: no pasa** — el
prompt pedía «1 a 3 frases» por sección; con 46 secciones y 500 palabras (unas 10 por sección) el
modelo escribió el doble (855 palabras), 3 de 5 trozos se cortaron por `max_tokens` y el
servidor completó 6 secciones. Según el plan, sin etapa 2 y vuelta al plan: **v2.2**, presupuesto
por sección explícito en el prompt («unas N palabras», mínimo 8) y `max_tokens` a 3 tokens por
palabra pedida (`7b6c34d`, con test).

**Segunda corrida (`7b6c34d`)** — `benchmarks/resumen-estructurado/resultados-rama.json`:

| Documento | Emparejados | Con contenido | Palabras / tope | Fin | Modelo |
| --- | --- | --- | --- | --- | --- |
| README | 11/11 | 11 | 435 / 500 | stop | 26B |
| Instalación | 9/9 | 9 | 505 / 500 | stop | 26B |
| Daemon | 5/5 | 5 | 399 / 500 | stop | 26B |
| CHANGELOG | 46/46 | 46 | 537 / 500 | stop (5 llamadas) | 26B |
| Corto | 6/6 | 6 | 602 / 500 | stop | 4B |
| Daemon + `focus` | 5/5 | 5 | 428 / 500 | stop | 26B |

Criterio de la spec: los tres documentos, el CHANGELOG y el corto pasan. **Juicio humano:** el
usuario dio el visto bueno a los tres resúmenes (2026-09-23, sin desglose por documento). Etapa 1
superada.

## Deviations and residual risk

- **Módulo nuevo `secciones.py`** en vez de meter la lógica pura en `server.py` (plan T1/T2): el
  fichero pasa de 2 700 líneas y es CRLF, y los scripts importan de un módulo pequeño.
- **`max_words` no es un tope duro**: el modelo se pasa hasta un 20 % (4B) o un 7 % (CHANGELOG).
  Se prefirió el margen de `max_tokens` a los cortes, que dejaban secciones sin resumir. REQ-202
  dice que `max_words` es el tope del texto: queda como riesgo residual aceptado, medido.
- **Corpus del catálogo `catalogo-2026-09` regenerado dos veces** (`cases.json`): sus cuatro
  casos de resumen son Markdown con títulos y su prompt de producción cambió; `test_corpus` lo
  exige. Los resultados de F2 existentes se midieron con el prompt en prosa. `conteos-log.json` se
  restauró (se recalcula con los logs de hoy y no tiene que ver con este cambio).
- **El `length` de map-reduce** (B6) cambia el log de `local_lint_summary` y `local_commit_msg`;
  ni el panel ni `metrics.py` leen `truncated_out` ni `finish_reason`, así que no hay corte de
  serie en el panel, solo en el log crudo. En `local_commit_msg` el aviso queda dentro del texto.
- **Línea base incompleta** por la interrupción de memoria (ver etapa 1).

## Etapa 2 (con cuota) de la v2 — 2026-09-23 — NO PASA

`experimento_adopcion.py --piloto --variantes v0 --repeticiones 3 --fuentes
benchmarks/resumen-estructurado/fuentes`, hooks de `main` (tramo desde 12:56Z), daemon con
`7b6c34d`. La primera tanda en segundo plano la cortó Claude Code por falta de memoria tras 1
corrida (el `llama-server` del 26B ocupa ~11,7 GB de RAM del sistema con `-ncmoe 12`: la RAM libre
baja de 18,7 a 4,9 GB); se cerraron Steam, Discord, Telegram y WhatsApp y se reanudó
(`--reanudar`) como proceso independiente. 9 corridas válidas, unos 3,8 USD en total.

| Tarea | Correctas | Contenido en el contexto | `###` en el documento |
| --- | --- | --- | --- |
| README | 3/3 | 0 | 0 |
| Daemon | 0/3 | 3 | 6 |
| Instalación | 0/3 | 3 | 0 |

**3/9: según el criterio escrito antes de medir, se retira** (no se publica encendido así).

Por qué releyeron (transcripts):

- **Daemon**: las tres releyeron las **subsecciones** que el resumen dejó fuera o acortó («la
  última subsección la leí yo directamente, porque ese resumen la había dejado fuera»; «las partes
  de Windows y de DAEMON MCP las leí completas»). El resumen solo cubre el nivel `##` y reparte el
  presupuesto a partes iguales.
- **Instalación**: las tres releyeron la **introducción** (líneas 1–19 o 1–50), el texto anterior
  al primer `##`, que no está en la lista de secciones; dos, además, «comprobando datos».
- Las 9 corridas usaron `focus` por su cuenta, casi siempre para pedir el resumen sección por
  sección y los literales (comandos, rutas).

Decisión del usuario (2026-09-23): registrar la v2 como fallida e intentar una **v3** con los dos
mecanismos observados, medida de nuevo con el mismo criterio escrito antes de medir.
