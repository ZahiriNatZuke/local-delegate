# Ola B1e: control independiente del detector de idioma

> **Control B1 a 8 tokens: FALLIDO (116/120).** El de `8be7ef7` se queda tal cual, con su
> medición en `evidence/B1e/measurement.json`. Causa: el detector se abstiene (`unknown`) en
> textos cortos, con 0 confusiones de idioma. Decisión del usuario del 2026-10-14: un control
> nuevo a **≥ 20 tokens**, con la regla escrita en `plan.md` (D10 y B1e) antes de aplicarla. Ver
> «Decisión tras el fallo» al final.

## Selección y congelación (control a 8 tokens, FALLIDO)

**Quién y cómo:** la eligió el agente de B1e el 2026-10-14, con un script del scratchpad
(`select_b1e.py`, sha256 `d9602e5281075b1f1d91cdaef1a76e05714e6dba4ad123a7c66072920a1fbe25`), sobre
el commit base `58ff9c6f473f0d21d118e9cb6991c039e1733803`. No abrió
`scripts/data/function_words.json` ni corrió el detector sobre ningún candidato. Ninguna frase se
eligió, cambió ni descartó a mano.

**Fichero congelado:** `tests/data/detect_language_control_b1.json` (LF), sha256
`c6e2b6b195408dad323eb4e3cdf09b44ee1576e347fd40f1be06d65a275c0812`. Formato del de B0b (`_about`,
`es`, `en` con `source` y `text`) más `key` (catálogos) o `line` (wiki, línea donde empieza el
párrafo o el elemento de lista), `sha256`, `_base_commit`, `_rule` y `_stats`.

### Regla aplicada (`B1-proposal.md` §5)

- **Español (60):** 30 valores de `es/cli.json` + `es/doctor.json` y 30 frases de `docs/wiki/*.md`
  (12 páginas).
- **Inglés (60):** valores de `en/cli.json` + `en/doctor.json` cuyas claves no están entre las 30
  españolas elegidas.
- **Limpieza:** enlaces Markdown a su texto (se quita la URL o la ruta), spans entre comillas
  invertidas, marcadores (`{x}`, `%(x)s`, `%s`), URL y rutas; espacios colapsados.
- **Wiki:** solo párrafos y elementos de lista sin su marcador; fuera encabezados, tablas, bloques
  de código, citas y HTML. Se limpia el bloque y luego se parte por `(?<=[.!?])\s+`.
- **Elegible:** de 8 a 40 palabras separadas por espacios y al menos 8 tokens `[a-záéíóúüñ]+`.
- **Sin duplicados** (minúsculas) y **sin las 40 frases de B0b**.
- **Selección:** orden por `sha256("<source>\n<text>")` dentro de cada fuente; se toman las N
  primeras.

### Lecturas que la regla no fijaba (decididas antes de correr nada)

1. `<source>` en el hash es la ruta del fichero desde la raíz del repo, igual que el campo
   `source` del control de B0b (`src/local_delegate/resources/i18n/es/cli.json`,
   `docs/wiki/Tools.md`).
2. `es/cli.json` + `es/doctor.json` forman **una** fuente (los 30 salen del conjunto unido);
   igual en inglés.
3. «Ruta» es todo trozo sin espacios que lleve `/` o `\` (se lleva también cosas como «y/o»).
4. Las citas (`>`) no cuentan como párrafo; las líneas que empiezan por `<` tampoco (HTML).
5. Los valores de catálogo no se parten en frases (la regla solo parte la wiki).
6. Ante un duplicado se queda el primero en orden de sha256.
7. Las frases de B0b se buscaron en las dos formas: texto igual y, en la wiki (donde B0b quitó
   los backticks pero conservó su contenido), frase cuyos tokens están todos dentro de una de B0b.
   Se encontraron las 20 españolas y salieron las 20.

Si la sesión principal no comparte alguna, el script se vuelve a correr con la otra lectura
**antes** del commit de congelación.

### Recuentos

| Fuente | Valores o frases | Elegibles | Únicos | Tomadas |
| --- | ---: | ---: | ---: | ---: |
| `es/cli.json` + `es/doctor.json` | 883 valores | 296 | 295 | 30 (20 de `cli`, 10 de `doctor`) |
| `docs/wiki/*.md` | 1 165 frases | 883 (tras quitar 20 de B0b) | 883 | 30 (10 páginas) |
| `en/cli.json` + `en/doctor.json` | 883 valores (menos las 30 claves) | 265 | 262 | 60 (46 de `cli`, 14 de `doctor`) |

Wiki por página: Savings-and-metrics 7, Tools 5, Daemon 5, Troubleshooting 3, Configuration 2,
Remote-backend 2, Architecture 2, Repo-hardening 2, Backend-versions 1, Integration-install 1.

### Comprobaciones hechas sin el detector

- Las 120 frases tienen entre 8 y 36 palabras y al menos 8 tokens; el `sha256` de cada una
  coincide con `sha256("<source>\n<text>")`.
- Ninguna clave inglesa está entre las 30 españolas; ningún texto se repite entre idiomas ni
  coincide con el control de B0b.
- Ningún valor elegido es igual en `es` y en `en` (no hay textos sin traducir haciéndose pasar
  por un idioma).
- La limpieza deja restos visibles en algunas frases (p. ej. `** ** — preguntar al usuario…`,
  `d; candidata a canary…`); se dejan tal cual, como manda la regla.

El commit de congelación (`B1e-freeze-commit-msg.txt`) tiene que entrar antes de cualquier corrida
del detector sobre este fichero.

## Medición (sobre el commit congelado `8be7ef7`): FALLIDO

Detector sin tocar, `min_tokens=8`, `min_margin=0.15` (el del módulo). Resultado por frase en
`evidence/B1e/measurement.json` (script de medición en el scratchpad, fuera del repo).

- **116 de 120 (96,7 %)**: no llega al 98 % (hacían falta 118). **Se para aquí**, sin cambiar
  listas, margen, umbral ni frases; decide la sesión principal.
- Con las listas invertidas: 0 de 120 (el control discrimina).
- **Ningún fallo confunde un idioma con el otro**: los 4 son `unknown`.

| Esperado | Clave | Tokens | es / en | Texto |
| --- | --- | ---: | --- | --- |
| es | `doctor.probe.version.candidate` | 8 | 0 / 0 | d; candidata a canary, no a promoción directa |
| es | `cli.install.clients_auto_none` | 8 | 0,125 / 0 | deteccion automatica (--clients auto): no se encontró ninguno |
| en | `cli.llamaswap_config.detail_gguf` | 12 | 0 / 0 | weights GiB + KV GiB (ctx= , layers= , kv_heads= , cache_k= , cache_v= ) |
| en | `cli.script.analyze_benchmark.cp3.review_only` | 8 | 0 / 0,125 | - no automatic score, the blind pairwise comparison decides: |

**Diagnóstico (sin arreglar):** los cuatro son valores de catálogo cortos y con estilo de
rótulo, no prosa. Hay dos causas:

1. **El margen no se puede alcanzar con 8 tokens y una sola palabra funcional:** 1/8 = 0,125 <
   0,15, así que una frase de 8 tokens necesita al menos dos. Pasa en dos de los fallos (uno de
   cada idioma). La regla de selección (≥ 8 tokens) y el margen de D10 (pensado para la muestra de
   ≥ 20) no casan en el borde.
2. **Textos sin palabras funcionales:** son una fórmula técnica y un fragmento que la limpieza
   dejó en sustantivos. Ninguna lista de palabras funcionales los decide. Que «no» y «a» estén
   fuera a propósito (los comparten los dos idiomas) deja la frase española sin ninguna.

La wiki (prosa) sale 30 de 30; los fallos son 2 de 30 en `es` (catálogo) y 2 de 60 en `en`.
Opciones para la sesión principal (ninguna aplicada): aceptar el resultado como evidencia de que
el detector no se equivoca de idioma y solo se abstiene en los textos cortos (que la muestra de
REQ-028 con `min_tokens=20` ya excluye); o fijar **ahora**, por escrito y antes de otro control
nuevo, una regla de selección más estricta (p. ej. ≥ 12 tokens). Reajustar este control a la vista
de los fallos lo invalidaría.

## Decisión tras el fallo (usuario, 2026-10-14)

El control de `8be7ef7` queda **FALLIDO a 8 tokens (116/120)** y no se toca. Límite conocido: el
detector se abstiene en textos cortos y no confunde idiomas. Se hace un control nuevo con la regla
escrita en `plan.md` (D10) **antes** de aplicarla:

- 60 + 60 frases con **≥ 20 tokens** `[a-záéíóúüñ]+` y como mucho 40 palabras (el tope de §5);
- misma limpieza, mismas fuentes, sin duplicados y el mismo orden por sha256;
- fuera las 120 del control fallido y las 40 de B0b;
- medido con `min_tokens=20` y margen 0,15; ≥ 98 % (como mucho 2 fallos en 120);
- congelado en `tests/data/detect_language_control_b1_20.json` en un commit propio, anterior a la
  corrida.

### Recuento con la regla nueva (sin detector): NO alcanza

| Fuente | Pide | Elegibles (≥ 20 tokens, ≤ 40 palabras, sin las 120 + 40) |
| --- | ---: | ---: |
| `es/cli.json` + `es/doctor.json` | 30 | **26** |
| `docs/wiki/*.md` | 30 | 396 |
| `en/cli.json` + `en/doctor.json` (claves distintas de las españolas) | 60 | **7** |

Aunque se quite la condición de claves distintas, los catálogos `en` tienen unos 30 valores con
≥ 20 tokens y ≤ 40 palabras. Las demás fuentes inglesas del repo no cambian el cuadro:
`site/index.html` (diccionario `en`) da 2 frases elegibles, y README, CHANGELOG, CONTRIBUTING,
SECURITY, CODE_OF_CONDUCT, plantillas, recetas y wiki están en español (REQ-040). Se para sin
elegir nada; la ampliación de fuentes la decide la sesión principal.

### Ampliación de fuentes (decisión del usuario del 2026-10-14, escrita antes de traducir)

Regla completa en `plan.md` (D10). Español: los 26 del catálogo y 34 de la wiki. Inglés: frases
elegibles de la wiki que no son de las 34, ni del control fallido, ni de B0b, traducidas de una en
una con `local_translate` en orden de sha256 y guardadas sin editar; entra la que, limpia, tenga
≥ 20 tokens y ≤ 40 palabras. **Límite conocido:** el inglés de este control es traducción
automática de textos del dominio del proyecto, no prosa escrita por personas.

## Selección y congelación (control a 20 tokens)

**Quién y cómo:** el agente de B1e, el 2026-10-14, sobre la regla de `plan.md` (D10) ya
commiteada en `24d99e9` (la ampliación a traducciones se escribió en el plan antes de la primera
llamada a `local_translate`). No abrió `scripts/data/function_words.json` ni corrió el detector.
Scripts del scratchpad, fuera del repo: `select_b1e_20_stage1.py` (sha256 `e3b3f065…494e797c`,
españolas y lista ordenada de candidatas inglesas) y `freeze2.py` (sha256 `1ab219d5…9ea571`,
aplica la regla de entrada y escribe el control).

**Fichero congelado:** `tests/data/detect_language_control_b1_20.json` (LF), sha256
`43e8ffe1f11293165b6431db853e4598fddb7a77f468e2b40d0fa720bea9fb34`, commit base de las fuentes
`58ff9c6`. Cada frase inglesa lleva `source`/`line` y `origin_text`/`origin_sha256` de la frase
española, `translation` (literal), `translation_sha256`, `text` (tras la limpieza; en las 60 es
idéntico a `translation`), `sha256` y `order` (posición en la lista de candidatas).
`local_translate` no informa del modelo ni del rol, y así consta en `translator`. **Dato y
verificación de la sesión principal** (tras `cb90910`): las 69 longitudes de
`evidence/B1e/translations.json` coinciden exactamente con `chars_out` de las 69 filas de
`local_translate` del log de uso (18:52–18:54Z), así que las traducciones no se reescribieron al
copiarlas; el modelo fue **`gemma3-4b`** (rol `mechanical`).

| Parte | Origen | Frases |
| --- | --- | ---: |
| es, catálogo | los 26 elegibles de `es/cli.json` (20) + `es/doctor.json` (6) | 26 |
| es, wiki | las 34 primeras por sha256 de 396 elegibles (sin control fallido ni B0b) | 34 |
| en | candidatas 0–68 de las 362 restantes de la wiki, traducidas de una en una | 60 |

- **Traducciones:** 69 llamadas, 0 errores. Se descartaron 8 por quedarse por debajo de 20
  tokens o de 20 palabras (posiciones 0, 6, 14, 15, 30, 37, 45 y 59), y la 68 sobró porque ya
  había 60. La salida literal de las 69 está en `evidence/B1e/translations.json`.
- **Comprobado sin el detector:** las 120 tienen entre 20 y 40 palabras y al menos 20 tokens; los
  sha256 cuadran; ninguna coincide con el control fallido ni con B0b; ninguna inglesa sale de una
  de las 34 españolas.
- **Límite conocido:** el inglés es traducción automática del dominio del proyecto, no prosa
  escrita por personas. Se guardó sin editar, también con sus errores visibles (por ejemplo,
  «call-swap» por llama-swap o «bullfight» por «corrida»).

El commit de congelación (`B1e-freeze2-commit-msg.txt`) entra antes de cualquier corrida del
detector sobre este fichero.

## Medición del control a 20 tokens (sobre `cb90910`): PASA

Detector sin tocar, `min_tokens=20`, `min_margin=0.15`. Resultado por frase en
`evidence/B1e/measurement_20.json` (script de medición en el scratchpad).

- **120 de 120 (100 %)**: 60/60 en español y 60/60 en inglés. Hacían falta 118.
- Con las listas invertidas: **0 de 120**.
- No hay fallos, así que el mutante «umbral a 0 fallos» no puede discriminar; en su lugar se usa
  el umbral −1 (abajo).

### Test (`tests/test_detect_language.py`, LF)

- `test_the_b1_control_is_frozen`: 60 + 60 frases, el `sha256` de cada una coincide con
  `source + "
" + text`, como mucho 40 palabras y al menos 20 tokens, y el `translation_sha256`
  de cada frase inglesa coincide con su traducción literal.
- `test_an_altered_phrase_breaks_the_freeze` (control positivo permanente): cambiar una palabra
  de una frase la delata por su sha256.
- `test_the_detector_passes_the_b1_control`: con `min_tokens=20`, como mucho 2 fallos
  (`MAX_FAILURES_B1`).
- `test_with_the_lists_swapped_the_b1_control_fails` (control positivo permanente).
- `test_the_failed_8_token_control_is_kept_unchanged`: el control a 8 tokens se queda como
  registro. No es criterio: solo se comprueba que conserva sus 60 + 60 frases y sus sha256.
- El control de B0b (20 + 20, no independiente) y sus tests siguen igual; el docstring del módulo
  explica los tres.

### Mutantes (en una copia temporal del test, ya borrada)

| Mutante | Test que cae | Assert |
| --- | --- | --- |
| `MAX_FAILURES_B1 = -1` | `test_the_detector_passes_the_b1_control` | `assert 0 <= -1` |
| `b1_failures` no cuenta ningún fallo | `test_with_the_lists_swapped_the_b1_control_fails` | `assert 0 > 2` |
| `frozen_entry_errors` no compara el hash | `test_an_altered_phrase_breaks_the_freeze` | `assert 0 == 1` |
| listas invertidas en el test principal | `test_the_detector_passes_the_b1_control` | `assert 120 <= 2` |

Cada mutante tumba solo el test esperado, que queda en 1 fallado y 14 aprobados.

### Verificación

| Comprobación | Resultado |
| --- | --- |
| Suite entera (`pesado.sh`, `-n 4 --dist loadgroup`) | 2853 passed, 2 skipped (antes 2848: +5 tests); 4 avisos de `anyio` en `starlette/testclient.py`, de antes |
| `ruff check .` y `ruff format --check .` | limpios (210 ficheros) |
| Guardián de textos (`test_no_uncatalogued_text.py`, dentro de la suite) | verde |
| Detector de nombres con `rename-exceptions.md`, al final | 0 fuera de la lista, 0 sin clasificar |

## Llamadas `local_*` del agente de B1e

| Tool | Para qué |
| --- | --- |
| `local_translate` ×69 | las traducciones del control a 20 tokens |
| `local_lint_summary(path=…)` ×1 | resumen del log de la suite |

Se hizo a mano: la selección, los recuentos, los hashes y la medición, porque son cálculos exactos
y van en scripts; los fragmentos del plan y la propuesta, porque había que citarlos al pie de la
letra; y la copia de cada traducción al fichero, porque la tool no guarda su salida en ningún
sitio legible (la sesión principal la verificó contra `chars_out`).
