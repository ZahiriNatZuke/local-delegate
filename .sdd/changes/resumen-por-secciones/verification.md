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
| REQ-207 | descripción y docs | pasa | CHANGELOG `[Unreleased]` (Added `focus` y el modo experimental; Fixed `length`), `docs/wiki/Tools.md`, `docs/wiki/Configuration.md`, skill `delegacion-local` |
| REQ-208 | etapa 1 (sin cuota) y etapa 2 (con cuota) | **se retira**: etapa 2 v2 3/9, v3 1/9 | secciones siguientes; interruptor apagado por defecto |

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
- **Corpus del catálogo `catalogo-2026-09`**: se regeneró mientras el modo estructurado estuvo
  encendido por defecto; con la retirada vuelve a ser idéntico al de `main` (`cases.json` y
  `tests/test_corpus.py` sin diff), así que los resultados de F2 siguen siendo comparables.
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

## Etapa 1 de la v3 — 2026-09-23

Commits `93d31ca` (v3), `3c134dd` (subtítulos repetidos = categorías; 4B en prosa) y `13f2537`
(colchón de 24 tokens por sección). Tres corridas de la etapa 1, iterando sobre lo que falló, sin
cambiar el criterio:

1. `93d31ca`: tres documentos 100 %; daemon 6/6 subsecciones. **Corto (4B) 0,86** (se saltó la
   Introducción) → según el criterio escrito, modo estructurado solo con el rol `long`.
   **CHANGELOG** 47/47 pero 46 con contenido y 1124/500 palabras: listaba sus 103 subtítulos,
   que son 5 etiquetas (`Added`, `Fixed`…) → subtítulos repetidos (menos de la mitad distintos)
   no se listan.
2. `3c134dd`: CHANGELOG 44/47 con `length` (reparto por tamaño: 8 palabras a las versiones
   pequeñas y el modelo escribe una frase entera) → colchón de 24 tokens por sección.
3. `13f2537` — `benchmarks/resumen-estructurado/resultados-rama-v3.json`:

| Documento | Títulos | Con contenido | Palabras / tope | Fin | Nota |
| --- | --- | --- | --- | --- | --- |
| README | 12/12 | 12 | 426 / 500 | stop | con Introducción |
| Instalación | 10/10 | 10 | 401 / 500 | stop | con Introducción |
| Daemon | 5/5 | 5 | 310 / 500 | stop | 6/6 subsecciones nombradas |
| Daemon + `focus` | 5/5 | 5 | 390 / 500 | stop | 6/6 subsecciones |
| Corto (4B) | prosa (sin `secciones` en el log) | – | 358 / 500 | stop | criterio del 4B aplicado |
| CHANGELOG | 47/47 | **46/47** | **998 / 500** | stop | ver desviación |

**Desviación aceptada por el usuario (opción A, 2026-09-23):** el CHANGELOG no cumple «cada
versión emparejada con contenido»: la `[0.2.1]` (una sola viñeta en el original, 451 caracteres)
quedó en 4 palabras («**Fixed** esquema de `local_extract`») y el umbral escrito antes de medir es
5. No se bajó el umbral. Y usa el doble del tope de palabras: con muchas secciones el modelo no
baja de una frase por sección (riesgo residual de REQ-202, más marcado aquí). La etapa 2 no incluye
el CHANGELOG. **Juicio humano de los tres resúmenes de la v3:** el usuario eligió seguir a la
etapa 2 sin un juicio explícito por documento.

## Etapa 2 de la v3 — 2026-09-23 — NO PASA, SE RETIRA

Mismo banco, mismo criterio y mismas copias fijas, en `%TEMP%\banco-resumen-v3`, daemon con
`13f2537`, hooks de `main`. Proceso independiente con Steam, Discord, Telegram y WhatsApp cerrados
(RAM libre mínima 4,7 GB). 9 corridas válidas, unos 3,4 USD.

| Tarea | Correctas | Contenido en el contexto | v2 (correctas / en contexto) |
| --- | --- | --- | --- |
| README | 1/3 | 2 | 3/3 / 0 |
| Daemon | 0/3 | 3 | 0/3 / 3 |
| Instalación | 0/3 | 1 | 0/3 / 3 |
| **Total** | **1/9** | **6/9** | 3/9 / 6/9 |

**1/9: según el criterio escrito antes de medir, se retira.**

Lectura de los transcripts:

- Las **relecturas no bajaron** (6/9 en la v2 y en la v3) aunque la tool ya entregaba lo que
  faltaba (etapa 1: 100 % de títulos, introducción, 6/6 subsecciones del daemon). El motivo
  cambió: Claude relee **para comprobar** («las secciones de Windows y rollback las leí yo
  directamente para confirmarlas»; «después comprobé contra el texto original los tramos que más
  importan»). Es confianza en un resumen ajeno, no cobertura: ningún prompt de la tool lo arregla.
- Dos corridas de instalación **no releyeron nada** y cuentan como incorrectas porque Claude
  reescribió los títulos en su respuesta (tabla, números de línea) y la métrica del banco dio
  0,67 y 0,78 con umbral 0,8. Es la métrica de siempre (la línea base se midió con ella) y no se
  cambió; queda anotado que exagera la caída de 3/9 a 1/9.
- Las 9 corridas usaron `focus`.

**Retirada aplicada (decisión del usuario, 2026-09-23):** `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO`
apagado por defecto, con test que lo fija; el código se conserva. Se quedan `focus`, los campos del
log y el aviso de `length` en map-reduce. Suite tras la retirada: 1451 passed, 2 skipped.

**Coste total de las mediciones con cuota de este SDD:** unos 7,2 USD (etapa 2 de la v2 y de la
v3). **Hallazgo que se lleva el backlog:** tras el piloto de T5 y las dos etapas 2, la tasa de
relectura se queda en 6–7 de 9 haga lo que haga la tool; la palanca que queda no es el formato
del resumen sino la confianza de Claude en él (p. ej. que la tool devuelva citas literales con su
línea, que es lo que Claude va a comprobar).
