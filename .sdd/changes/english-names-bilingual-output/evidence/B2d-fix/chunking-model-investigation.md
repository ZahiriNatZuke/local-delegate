# B2d-fix — ¿los fallos de idioma vienen del modelo o del troceado?

Investigación del 2026-10-15 sobre la rama `sdd/english-names-b2d` (HEAD `1c82d07`). Sin cambios en
`src/`, sin reiniciar el daemon y sin pruebas en vivo. Fuentes: las 40 filas de
`%LOCALAPPDATA%\local-delegate\usage-202610.jsonl` entre 15:06 y 15:57Z del 2026-10-15 (ventanas
`w-20261015T150634Z` y `w-20261015T152547Z`), cruzadas por tool y ruta con `lang-sample-batch1.json`
y `lang-sample-batch2.json`; el código; y tests en proceso con backend falso.

## 1. Las 40 llamadas

Ninguna fila lleva el campo `chunks`, que `_log_event` escribe siempre que hubo más de una llamada
real al backend (`server.py:820`), contando también los saltos de respaldo; ninguna lleva `fallback`.
O sea: **las 40 fueron una sola llamada, sin troceado, sin reduce y sin respaldo a otro modelo**. Lo
confirman los topes: la entrada mayor fue de 26 569 chars, por debajo de los 48 000 del rol `long`
(`config.py:319`), y las de `gemma3-4b` no pasaron de 3 377, frente a 20 000.

| Grupo | Modelo (rol) | Llamadas | Troceadas | Truncadas (`length`) | Fallos de idioma |
|---|---|---|---|---|---|
| summarize, tanda 1 (pide inglés) | gemma4-26b-a4b (`long`, estructurado) | 10 | 0 | 1 (httpcore2) | 3 |
| summarize, tanda 2 (pide español) | gemma4-26b-a4b (`long`, estructurado) | 10 | 0 | 0 | 0 |
| lint, tanda 1 | gemma3-4b (`mechanical`) | 8 | 0 | 0 | 2 (los dos `doctor_es`) |
| lint, tanda 1 | gemma4-26b-a4b (`long`) | 2 | 0 | 1 (biome) | 0 |
| lint, tanda 2 | gemma3-4b (`mechanical`) | 8 | 0 | 0 | 1 (`resume-ruff-cinco-reglas`) |
| lint, tanda 2 | gemma4-26b-a4b (`long`) | 2 | 0 | 2 (affinity, lint-9k) | 0 |

Tamaño de entrada de los fallos: summarize de 10 197 a 17 383 chars, y los aciertos van de 6 054 a
26 569. Lint de 784 a 3 377 chars, todos con `gemma3-4b`.

**Lectura.** Los fallos no caen en llamadas troceadas, porque no hubo ninguna. Tampoco en las
truncadas: las 4 truncadas pasan el juez y ningún fallo está truncado. En cuanto al modelo, todos
los fallos de lint son de `gemma3-4b` (3 de 16), pero el modelo y el tipo de entrada van juntos:
el rol lo decide el tamaño (`LONG_INPUT_CHARS=6000`), así que `gemma3-4b` recibe los logs cortos
en español y `gemma4` nunca recibió uno. Y todo summarize fue `gemma4` por el camino estructurado.
Con estos datos el modelo no se puede separar ni del camino ni de la entrada.

## 2. Camino troceado: la orden de idioma llega a cada prompt

Lectura del código:
- **summarize en prosa**: el map lleva `system = _guard(...) + extra` (`server.py:3765`), y `extra`
  incluye `_written_language_clause()` (`:3743`). El reduce usa `reduce_system = _guard(...) +
  reduce_extra` (`:3178-3184`) con `reduce_extra=extra` (`:3785`). El reagrupado usa
  `regroup_system = reduce_system` (`:3186`).
- **summarize estructurado troceado**: `_chunk_system` añade `extra` en las dos ramas, con
  secciones o sin ellas (`:3670-3673`). Los subtrozos del reintento usan el mismo `system_for`
  (`:3209-3212`). `reduce="concat"` no llama al modelo.
- **lint**: el map lleva `_lint_system` con la orden (`:3496`). El reduce y el reagrupado la llevan
  por `reduce_extra=_written_language_clause()` (`:4161`).
- **Respaldo a otro modelo**: `_run_chat` arma el payload una vez y `_with_fallback` reenvía ese
  mismo payload a cada candidato (`:2301-2320`). El prompt no cambia al saltar.

Comprobado con el backend falso (`_post_chat` doblado, payload real de cada intento) en
`scratchpad/inv/test_chunking_language_investigation.py`, bloque A, **10/10 en verde** en las dos
combinaciones de las tandas. Cubre map, reduce y reagrupado de summarize en prosa y de lint; los
subtrozos del reintento por desborde; el salto de `long` a `code`; y los trozos «continúa la
sección X» del estructurado. Control positivo con `scratchpad/inv/test_mutant_control.py`: con el
mutante «reduce sin la orden» (`reduce_extra=""`), los 4 casos de A1 fallan en el assert final,
con las llamadas del reduce en la lista. No en las guardas.

Otros puntos:
- **El reduce y los títulos en el idioma original.** En summarize en prosa los parciales son prosa
  y no llevan títulos. En el estructurado no hay reduce por modelo. No hay nada que arrastrar.
- **El post-proceso mete texto que no está en el idioma pedido**, pero son líneas del producto o
  títulos del documento:
  - `sections.complete` **devuelve un título traducido a la redacción del documento**
    (`sections.py:323-327`, introducido en `71846c1`). Es a propósito, para poder buscarlo en el
    documento. El rescate es estrecho: un solo hueco entre vecinos ya emparejados. Si alguno de
    los títulos en español de los fallos lo tradujo el modelo y lo revirtió el servidor, no se
    puede saber, porque la salida cruda del modelo no se registra.
  - El texto de relleno «(sin resumir)» y los avisos van en el idioma del producto (`i18n.t`,
    `sections.py:289`). El juez los excluye.
  - La «Introducción» ya va en el idioma de respuesta (`sections.py:365`).
- **Presupuesto de salida.** El lint directo pide `2·max_words+96 = 496` tokens (`:4169`), y las
  3 truncadas de lint con `gemma4` se pararon justo en 496. Antes del endurecimiento (filas hasta el
  2026-10-14), `gemma4` en lint se truncó 3 de 22 veces; después, 3 de 4. `lint-9k.txt` pasó de
  409 tokens con `stop` el 14/10 a 496 con `length` el 15/10, aunque el idioma configurado el 14/10
  no consta. La orden de «frases completas» alarga la salida y el presupuesto de 2 tokens por
  palabra ya no alcanza. Con troceado sería peor: cada parcial del map y el reduce piden
  `2·w+64 = 464` (`:3152-3153`).

## 3. Modelo

- **summarize, tanda 1**: los 3 fallos no son copia del modelo, sino cumplimiento del prompt. El
  formato estructurado pide «una línea '## ' con el título tal cual» y nombrar cada subsección en
  negrita (`server.py:3555-3560`, `_STRUCTURED_FORMAT`). La orden endurecida exime expresamente «los títulos que se piden
  literales» (`:3472`). Las respuestas fallidas tienen la prosa entera en inglés; lo que está en
  español son títulos y negritas idénticos a los del documento. Por eso el diagnóstico sin `#` ni
  `**` da 5/5 en todas las combinaciones (`lang-sample-summary.md`). Los documentos fallidos son los
  de títulos más largos y numerosos en español (`Investigacion-empaquetado` con títulos de frase
  entera, `plan-f6-vision` y `Daemon.md` con muchas negritas de subsección).
- **lint, tanda 1** (`gemma3-4b`, `doctor_es_*`): el modelo deja en español las etiquetas de cada
  chequeo («Clientes», «Cadenas de respaldo», «Memoria MCP») y escribe en inglés el resto. Es copia
  de etiquetas, como pasaba en B2. La orden dice que los identificadores quedan tal cual, y una
  etiqueta de chequeo está en la frontera. Con un solo modelo para esas entradas no se puede
  atribuir al 4B frente al 26B.
- **lint, tanda 2** (`resume-ruff-cinco-reglas`): la respuesta está entera en español. Es un
  artefacto del detector con 37 tokens llenos de códigos (ya descrito en el resumen).
- `local_status` no se consultó: el catálogo de modelos de la config (`config.py:269-273`) y el log
  bastan para saber quién sirvió cada llamada.

## 4. Bugs y riesgos encontrados (tests en el scratchpad, fallan hoy)

1. **Una sección vacía en el documento se avisa como «no resumida»** (test
   `test_B1_a_section_empty_in_the_document_is_not_reported_as_not_summarized`). Es el caso del
   `## Release Information` de httpx2: en el documento ese título va seguido directamente de
   `## 2.13.1`, así que el modelo acierta al dejarlo vacío, pero `complete` lo cuenta como `empty`
   (`sections.py:276-282`, `:345-353`) y añade «1 section not summarized». Además, el plan le pide
   «unas 23 palabras» a una sección sin contenido (`allocate_by_size` mide los caracteres del
   tramo, título incluido), lo que invita a inventar. No afecta al idioma.
2. **Riesgo: el truncado puede tirar el cuerpo entero de una sección** (test
   `test_B2_truncation_drops_a_whole_long_last_line_that_starts_with_hash`). Con `truncated=True`,
   `complete` quita la última línea si «parece título» (`sections.py:318-319`), sin importar su
   largo. Encaja con httpcore2 en la tanda 1: `max_tokens=2112` (lo da `_structured_max_tokens`
   por los 70 subtítulos del `# Changelog`), 2 112 tokens generados, solo 752 chars entregados y
   `## Changelog` vacío. Unos 2 000 tokens se perdieron. Que fuera por esta vía, por espacios en
   blanco degenerados o por razonamiento oculto **no se puede comprobar**, porque la salida cruda
   no se registra. No afecta al idioma.

No se encontró ningún bug de idioma en el troceado.

## 5. Veredicto por hipótesis

| Hipótesis | Veredicto | Evidencia |
|---|---|---|
| Troceado (map/reduce) | **Descartada** para estos fallos | 0 de 40 filas con `chunks` (`server.py:820`); bloque A 10/10 en verde, con control positivo |
| Truncado por `max_tokens` | No causa fallos de idioma, pero **sí es un problema real en lint** | 4 truncadas, todas aciertos; lint con `gemma4`: 3/22 → 3/4 tras el endurecimiento |
| Modelo | **No demostrada** | summarize: siempre gemma4; lint: los fallos son gemma3-4b, confundido con entrada corta en español |
| Prompt (títulos literales) | **Causa principal de summarize** | `server.py:3555-3560` y `:3472`; diagnóstico sin títulos 5/5 |
| Post-proceso | Contribuye poco: reversión de títulos traducidos (`sections.py:322-327`); falso aviso de sección vacía | test B1 |
| Detector | **Causa del fallo de la tanda 2** (37 tokens con códigos) y juez que cuenta títulos exigidos literales | `lang-sample-summary.md` |

## 6. Prueba en vivo propuesta (no hecha)

Requiere reiniciar el daemon con variables. La hace la sesión principal, con ventana de pruebas.

1. **Modelo en lint, sin cambiar la entrada**: los dos `es-log-B1b_doctor_es_*.txt` en la combinación
   de la tanda 1, una vez con lo de siempre (`gemma3-4b`) y otra con
   `LOCAL_DELEGATE_LONG_INPUT_CHARS=1000` (van a `gemma4-26b-a4b`). Tres repeticiones de cada una,
   comprobando que `response_sha256` cambia (si no cambia, la semilla es fija y repetir no sirve).
   Comparar el veredicto del juez y contar las etiquetas en español copiadas.
2. **Prompt estructurado o modelo en summarize**: los 3 documentos fallidos con
   `LOCAL_DELEGATE_STRUCTURED_SUMMARY=0` (prosa, mismo `gemma4`). Si pasan, la causa es el formato
   que exige títulos literales y no el modelo.
3. **Troceado de verdad**: los mismos 3 documentos con estructura y `LOCAL_DELEGATE_MAX_CHARS_LONG=8000`
   (trozos por sección y concatenación), y `en-log-biome-lint.txt` y `lint-9k.txt` con el mismo tope
   (map + reduce). Antes de juzgar, comprobar `chunks > 1` en el log. Comparar contra la tanda
   original: idioma, `finish_reason` y avisos de truncado. Es de esperar que lint se trunque más
   (464 tokens por parcial).
4. Opcional, para cerrar la duda de httpcore2: registrar el largo crudo de la salida del modelo
   antes de `complete`, como pendiente de instrumentación (ya anotado en B2d: los parciales no se
   registran).
