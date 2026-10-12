# Revisión: Renombrado a inglés de lo publicado y salidas en español e inglés

## Revisión de la spec — ronda 1

- **Fecha:** 2026-10-12. **Revisor:** agente adversario (`general-purpose`), sin haber escrito la spec.
- **Gate:** `spec`. **Base:** `main` en `8ec2f1d` (0.34.0).
- **Insumos leídos:** `brief.md`, `spec.md` entero, `research.md` entero, `research-rename.md` §1, §3–§6,
  `research-i18n.md` «Cómo se midió», §1(e)–§7; `evidence/persisted-data-scan.json` (vía `local_extract`).
- **Citas comprobadas contra el código (18, todas correctas):** `agents.py:41`, `install.py:45`,
  `install.py:64`, `install.py:102`, `config.py:209`, `config.py:213`, `config.py:244`, `config.py:262`,
  `config.py:417`, `hook_common.py:254`, `hook_common.py:263`, `hook_common.py:315`,
  `checks.py:1790`, `checks.py:1792`, `web/auth.py:45`, `web/auth.py:50`, `valoracion.py:42`,
  `cli.py:1369`/`1376`, `test_windows.py:206`, `recalcular.py:195`, `cuota.py:30-33`,
  `fallos.py:45`, `fallos.py:204`. Las citas de código de la spec y de los research que ella usa
  están bien; los fallos están en referencias internas entre requisitos, en una cita a
  `site/index.html` y en lo que `agents.py:41` hace de verdad (hallazgos 6, 14 y 15).

### Veredicto

**No aprobable** en esta ronda. Hay 3 bloqueantes: la regla del idioma del sistema no se puede
ejecutar tal como está escrita, la suite pasaría a depender del idioma de la máquina (en CI hay
runners en inglés) y el cierre del frente A depende de unas herramientas que solo existen en el
scratchpad de esta sesión. Además hay 14 importantes que conviene corregir en la misma pasada,
porque cambian el plan.

### Hallazgos

| # | Severidad | Dónde (spec) | Hallazgo | Corrección propuesta |
| --- | --- | --- | --- | --- |
| 1 | **BLOQUEANTE** | REQ-018 (`spec.md:178-182`); caso límite `spec.md:401-402`; trazabilidad `spec.md:480` | **«Idioma del sistema» sin fuente ni precedencia: la regla no se puede ejecutar.** No dice qué se consulta ni en qué orden. En Windows, la interfaz (`GetUserDefaultUILanguage`) y el formato regional (`locale.getlocale()` → `Spanish_Spain`) pueden no coincidir, y el propio ejemplo mezcla las dos cosas (`Spanish_Spain` junto a `es-ES`). En POSIX no fija el orden de `LANGUAGE` (que puede ser una lista, `es:en`), `LC_ALL`, `LC_MESSAGES` y `LANG`, ni qué pasa con `C.UTF-8` (lo que traen por defecto los runners de Ubuntu). En macOS, el daemon de `launchd` y el servicio de `systemd` no heredan `LANG`, así que en un Mac en español el CLI saldría en español y el daemon en inglés. La evidencia prevista («locales simulados de los tres sistemas») vale para cualquier implementación: no puede dar un resultado distinto. El propio `research.md:129-130` lo dejó como «supuesto por validar». | Escribir la regla como una tabla ordenada por sistema operativo. **Windows:** idioma de la interfaz (`GetUserDefaultUILanguage` por `ctypes`) y, si falla, `GetUserDefaultLocaleName`. **POSIX:** primer valor no vacío de `LANGUAGE` (su primer elemento), `LC_ALL`, `LC_MESSAGES` y `LANG`, en ese orden. **macOS:** si todo eso está vacío o vale `C`/`POSIX`, `defaults read -g AppleLanguages`. Es español si la primera subetiqueta es `es`; `C`, `C.UTF-8`, `POSIX` y vacío dan reserva (inglés); `pt`, `fr` y demás dan inglés. Para cada fila, un test con datos que distingan: por ejemplo `LANGUAGE=es:en` con `LANG=en_US` debe dar `es`, y la interfaz en inglés con el formato regional `es-ES` debe dar `en` (o lo contrario, pero decidido). |
| 2 | **BLOQUEANTE** | REQ-018 + REQ-034 (`spec.md:271-274`: «los tests que afirman el texto en español siguen valiendo») | **La suite pasaría a depender del idioma de la máquina.** El CI corre en `ubuntu-latest`, `windows-latest` y `macos-latest` (`.github/workflows/ci.yml:124`) con el sistema en inglés o en `C.UTF-8`, y `tests/conftest.py` no fija ningún idioma. Con el idioma por defecto tomado del sistema, los ~450 asserts del frente B (i18n §3) quedan en verde en esta PC y en rojo en CI. `research-i18n.md:188-189` ya advertía que «siguen valiendo **si el idioma por defecto sigue siendo español**», y la decisión del 2026-10-12 lo cambió. Es el mismo fallo de «un test que mide el entorno» que ya ocurrió con macOS. El aislamiento de entorno (`config.VARIABLES_DE_ENTORNO`) cubre las variables `LOCAL_DELEGATE_*`, pero no `LANG`/`LC_*` ni la consulta a Windows. | Requisito nuevo: «La suite fija el idioma a `es` por defecto mediante un fixture automático que sustituye la detección del sistema, y no lee el locale real. Los tests de REQ-018 sustituyen esa detección explícitamente. El guardián de aislamiento falla si algún código lee `LANG`, `LC_*`, `LANGUAGE` o llama a la API de idioma de Windows fuera de la función única de detección». Control positivo: quitar el fixture y correr con `LANG=en_US.UTF-8` hace fallar los asserts en español. |
| 3 | **BLOQUEANTE** | REQ-016 (`spec.md:160-168`); REQ-025 y REQ-034 (detector de «i18n §0»); trazabilidad `spec.md:478` | **El cierre consume herramientas que ninguna ola produce, y que hoy solo están en el scratchpad de esta sesión.** `esdet.py` y los escáneres que lo alimentan (`scan_py.py`, `scan_js2.py`, `js_tok.py`, `inv_*.py` y la caché `lex.pkl`) están en `…/scratchpad/` de la sesión `f1cbf955`, que es temporal. Dependen de `wordfreq` y `esprima`, que no se han auditado con Socket. REQ-016 pide versionar «el detector», pero no los escáneres sin los que no se puede volver a ejecutar, y la trazabilidad no asigna ninguna ola que lo haga. El detector de texto de i18n no existe como pieza nombrada: «i18n §0» no es ninguna sección (la sección se llama «Cómo se midió», sin número). Además, según `research-i18n.md:29-30`, ese detector **no ve etiquetas de una o dos palabras** («Latencia», «Cargando»), que son justo las del panel: con el panel en inglés daría 0 hallazgos aunque quedaran etiquetas cortas en español. | (a) **Antes de aprobar**, copiar el detector, los escáneres y los controles a `.sdd/changes/english-names-bilingual-output/tools/` (la carpeta `.sdd/` está versionada: 572 ficheros) y pasar `wordfreq` y `esprima` por Socket (o justificar `uv run --with`). (b) Asignarlo a la ola A0 en la trazabilidad. (c) Sustituir en REQ-025 y REQ-034 el detector heurístico por un control que sí distinga: «ninguna cadena `es` del catálogo que difiera de su `en` aparece en el DOM o en la salida en inglés», más el detector como apoyo. Control positivo: dejar una etiqueta de una palabra sin traducir hace fallar el test. |
| 4 | IMPORTANTE | REQ-027 (`spec.md:230-234`) frente a REQ-035 (`spec.md:278-281`); trazabilidad `spec.md:489` | **Contradicción de orden entre olas.** REQ-027 va en la ola A6 y exige que «el resumen de cada tool que muestra el panel sale del catálogo de textos». El catálogo nace en B0, y REQ-035 prohíbe mezclar B antes de que estén las olas de A que tocan `src/` (A0–A8). Así, A6 depende de B0, que depende de A8. | Partir REQ-027: las descripciones en inglés y la misma versión que REQ-010 van en A6; el resumen del panel desde el catálogo va en B4. Admitir explícitamente que, entre A6 y B4, el panel en español muestra los resúmenes de tool en inglés. |
| 5 | IMPORTANTE | REQ-028 (`spec.md:238-239`) | **`local_commit_msg` «sigue igual», pero en realidad cambia su comportamiento.** Hoy, sin `LOCAL_DELEGATE_COMMIT_LANGUAGE`, el mensaje sale en el idioma predominante del diff (`server.py:3181-3194`, REQ-044 del SDD anterior, medido en la tanda de afinidad). Con la spec, el defecto pasa a ser el idioma elegido, y un repo en inglés de un usuario con el sistema en español recibiría commits en español. La premisa del brief («como ya hace `local_commit_msg`») no es exacta. | Mantener como defecto el idioma predominante del diff (el idioma del commit lo decide el repo, no la interfaz) y quitar `local_commit_msg` de REQ-028. Si la sesión principal prefiere el cambio, que lo diga expresamente como cambio de comportamiento, con su entrada en el CHANGELOG. |
| 6 | IMPORTANTE | REQ-029 (`spec.md:243-247`), trazabilidad `spec.md:491`; REQ-012 | **El control de REQ-029 no puede fallar, y la superficie real no está.** El bloque gestionado de `CLAUDE.md`/`AGENTS.md` ya se detecta por marcadores (`install.py:38-39`, `<!-- local-delegate:begin -->`), no por su título. El test «con título en español y en inglés deja un solo bloque» pasa hoy sin tocar nada. `agents.py:41` hace otra cosa: busca el encabezado «Delegación a modelos locales» **en los subagentes del usuario** (`~/.claude/agents/*.md`) para saber dónde insertar el bloque del catálogo (`agents.py:116-147`). Esos bloques llevan además `_RULE` en español, que nombra la skill `delegacion-local` (`agents.py:46-50`). REQ-012 no los menciona, y el catálogo se extrae de la tabla de **la** skill (`agents.py:53`); con dos skills, una por idioma, no dice de cuál. | Reescribir REQ-029 sobre `agents.py`. Pedir: (a) encabezado reconocido en los dos idiomas, o un ancla que no dependa del idioma, con test de subagente con encabezado en español y otro en inglés; (b) `_RULE` y el catálogo del subagente en el idioma efectivo, con el nombre nuevo de la skill, también al regenerar sobre un bloque 0.34.0; (c) un guardián que exija que la skill en español y la skill en inglés listen exactamente las mismas `local_*` con los mismos identificadores. Añadir los subagentes a REQ-012. |
| 7 | IMPORTANTE | REQ-019 (`spec.md:183-187`), NFR «Operabilidad» `spec.md:436-437` | **El idioma del daemon no se ve desde ningún sitio.** `doctor` muestra el idioma de **su** proceso, pero tools y hooks hablan en el del daemon y en el de la sesión de Claude Code, y en Windows el daemon corre como tarea programada. Es el mismo problema que REQ-003 ya resuelve para los nombres obsoletos, y que aquí queda sin resolver. Un `LOCAL_DELEGATE_LANG` no válido en el entorno del daemon tampoco lo avisa nadie. La spec tampoco dice cómo fija el usuario la variable para el daemon (`install`/`update` no la propagan). | `local_status` y `/api/daemon` informan del idioma efectivo y su origen. `doctor` consulta al daemon y avisa si no coincide con el suyo. La wiki explica dónde poner la variable para el daemon en cada sistema operativo. |
| 8 | IMPORTANTE | REQ-018/019/024, REQ-030 | **La regla de idioma queda escrita dos veces.** Los hooks no pueden importar el paquete, así que la resolución del idioma quedaría duplicada en `hook_common` y en el paquete. Es el defecto recurrente del repo (dos fuentes del mismo dato). REQ-030 cubre los textos, no la regla. | Exigir una sola implementación en `hook_common.py`, que el paquete ya importa (`atribucion.py:30`, `server.py:507`), y un test que lo compruebe: el paquete no tiene una segunda función de detección. |
| 9 | IMPORTANTE | Caso límite «Fichero viejo y nuevo» (`spec.md:417-419`); escenario 1 (`spec.md:321-323`); REQ-005/006/033 | **Falta decir qué pasa con lo viejo al escribir el fichero nuevo de una caché que no se puede regenerar.** Si `recompute-cost` escribe `attribution-202610.json` y «el viejo solo se lee si el nuevo no existe», lo que tenía `atribucion-202610.json` se pierde salvo que se arrastre al fichero nuevo. Lo mismo pasa con los `puntos` de `coste-agregados.json`. Tampoco está claro si la regla de precedencia vale para los registros que solo crecen (`enfriamiento-eventos.jsonl`), donde hay que leer los dos. Y las `marcas` viejas que se arrastran, ¿se convierten o se copian tal cual (REQ-033)? | Distinguir tres casos. (a) Estado vigente (`enfriamiento.json`): gana el nuevo. (b) Cachés de historia (`atribucion-*`, `coste-agregados`): el escritor arrastra al fichero nuevo, en formato nuevo, todas las entradas viejas, y deja el viejo intacto; test con control positivo (un escritor que no arrastra pierde un cruce y falla). (c) Registros que solo crecen: se leen siempre los dos. Decir si las `marcas` arrastradas pasan a valor de máquina. |
| 10 | IMPORTANTE | Caso límite «Hooks viejos con daemon nuevo» (`spec.md:393-398`) | **Falta el sentido peligroso de la convivencia de versiones.** Los hooks viejos leen `enfriamiento.json` (`hook_common.py:315`), que el daemon nuevo deja de escribir: no ven el enfriamiento y ofrecen delegar en un modelo enfriado durante toda la ventana. Esa ventana puede durar meses, como en la Mac hasta la 0.31.2. La spec solo describe el caso contrario. | Añadirlo como caso aceptado y documentado en el CHANGELOG, o, si se quiere evitar, que el daemon escriba también `enfriamiento.json` mientras viva el alias (excepción explícita a REQ-005, con versión de retirada). |
| 11 | IMPORTANTE | REQ-007 (`spec.md:92-96`), REQ-015 | **La medición P-4 puede cambiar de comando a mitad de su ventana.** REQ-015 renombra los módulos de `scripts/`, y nada impide renombrar también sus opciones (`--desde`, `--excluir`, `scripts/medir_enfriamiento.py:235`). El procedimiento de P-4 está escrito con el nombre viejo en `.sdd/changes/delegacion-precisa-y-fiable/verification.md:1208`, en `daemon-reparte-el-backend/verification.md:138,274` y en la memoria. «O su sucesor renombrado» no lo resuelve. | Decidir si las opciones de los scripts entran en el renombrado. Si los scripts de medición se renombran antes de ~2026-12-14, la misma ola actualiza esos procedimientos (o deja el nombre viejo como envoltorio hasta cerrar P-4), y la verificación lo comprueba ejecutando el comando documentado. |
| 12 | IMPORTANTE | REQ-014 (`spec.md:151-154`) | **El control de los scripts no detecta lo que va a romperse.** «Importar todos los scripts» detecta el renombrado de un módulo, pero no el de una función: `medir_adopcion.py` usa `atribucion.test_reason`, que REQ-015 puede renombrar, y el fallo solo aparece al ejecutarlo. | Exigir para cada script de `scripts/` una ejecución de `--help` y una corrida mínima sobre fixtures, o `get_file_problems` de PyCharm sin referencias sin resolver, con el resultado registrado en la verificación. Control positivo: renombrar `test_reason` sin tocar el script hace fallar el control. |
| 13 | IMPORTANTE | REQ-005 (`spec.md:72-84`), REQ-016 | **Hay un formato en español que la spec no cubre.** `resources/vendor/vendor.json` tiene claves en español (`_acerca_de`, `files[]._procedencia`). La propia `evidence/persisted-data-scan.json:320-328` lo detecta, pero no aparece en rename §1c ni en REQ-005. Lo leen `web/metrics.py`, `scripts/check_vendor.py` y el workflow `vendor-audit.yml`. Además, REQ-016 solo mira identificadores y claves dentro del código, no las claves de los JSON del paquete. Así, el «0 hallazgos» del cierre no alcanza a `precios.json`, `densidad.json` ni `vendor.json`. | Añadir `vendor.json` a REQ-005, con su lector y su workflow. Ampliar REQ-016 a las claves y valores de los `.json` de `src/**/resources`, y a los nombres de fichero y directorio del paquete. |
| 14 | IMPORTANTE | REQ-006 (`spec.md:85-91`) | **La lista de lectores parece cerrada y le faltan lectores.** La lista entre paréntesis («daemon, panel, `doctor`, `recompute-cost`, hooks y `scripts/medir_*.py`») deja fuera a `pace.py`, `scripts/experimento_adopcion.py`, `medir_resumen_estructurado.py`, `_banco_claude.py` (lee la telemetría), los lectores de la salida de `benchmark` (`analizar_benchmark.py`, `hoja_pares.py`, `hoja_revision.py`, `construir_corpus.py`) y `vigilante_precios.py` junto a su workflow (rename §1c, columna «Lo leen»; §3.9). El plan saldría de esa lista incompleta. | Decir «todo lector, sin excepción, de la columna "Lo leen" de rename §1c» y nombrar los que faltan. Decidir si la salida de `benchmark` ya guardada (corpus y hojas de F2) se lee en los dos formatos. |
| 15 | IMPORTANTE | REQ-036/037 (`spec.md:282-296`); trazabilidad `spec.md:498-499` | **El uso de los MCP sigue siendo un deseo, no algo comprobable.** El criterio solo pide *listar* las llamadas, y una lista con «0, motivo X» siempre lo cumple. Además, las entregas de los agentes no se guardan en ningún sitio: quien verifique no tiene qué mirar. | Crear un registro por ola en la carpeta del cambio (`waves/<ola>.md` o una sección de `verification.md`) con las tablas de `local_*` y `mcp__pycharm__*`, y que el gate `conformance` exija que exista. Poner mínimos que se puedan comprobar: toda ola que corre la suite pasa su log por `local_lint_summary(path=…)`; toda ola que renombra símbolos de Python registra al menos un `rename_refactoring` y un `get_file_problems` sobre los ficheros tocados, salvo que PyCharm esté caído, y eso se dice. |
| 16 | IMPORTANTE | REQ-041 (`spec.md:305-309`) | **Solo se marca la frontera para la adopción.** REQ-028 cambia los prompts del modelo local, y eso mueve la calidad que se mide (afinidad de F2, `local_summarize` por secciones, P-17 pendiente de F1), sin que quede marcada ninguna frontera. Tampoco se marca el cambio de redacción de los hooks **en español**, aunque al pasarlos al catálogo pueda cambiar su texto en esta PC. | Registrar también como frontera el cambio de prompts (REQ-028) y cualquier cambio de texto de los hooks en cualquier idioma, en el mismo fichero de fronteras, que lea también el script de calidad o de F1 que corresponda. |
| 17 | IMPORTANTE | Compatibilidad (pregunta 6); Summary punto 2 | **No se admite de forma explícita lo que rompe a quien actualiza sin leer el CHANGELOG por el idioma por defecto.** Un hispanohablante con Windows en inglés, algo habitual, pasa de golpe a ver en inglés el CLI, `doctor`, las salidas de las tools y los hooks. Además, su próximo `install` le reescribe la skill y el bloque de `CLAUDE.md` en inglés. Sí quedan anunciados `doctor --json`, el contrato de `_local_delegate`, la cookie y las descripciones; esto no. Tampoco se dice nada de volver a una versión anterior: una 0.34.0 no ve lo escrito en los ficheros nuevos (`attribution-*`, `cooldown*`, `cost-aggregates`). | Añadir a REQ-040, o a un requisito propio, que el CHANGELOG de la versión que activa el idioma anuncie el cambio de defecto y cómo fijar `LOCAL_DELEGATE_LANG=es` (shell, `env` de `settings.json`, entorno del daemon). Añadir un caso límite: «volver a una versión anterior no está soportado; los datos escritos después del cambio son invisibles para una 0.34.0». |
| 18 | MENOR | REQ-003 (`spec.md:56-57`) | Cita a un requisito equivocado: «el fichero interruptor viejo de REQ-011»; el interruptor está en REQ-012. | Cambiar a REQ-012. |
| 19 | MENOR | REQ-017 (`spec.md:172`) | Cita a un requisito que no existe: REQ-045 (la spec llega a REQ-042); las ventanas de prueba son REQ-038. | Cambiar a REQ-038. |
| 20 | MENOR | REQ-020 (`spec.md:190-191`) | Cita falsa: «como `site/index.html`». El sitio arranca en **español salvo** que el navegador empiece por `en` (`site/index.html:706`); el panel haría lo contrario (inglés salvo `es`). Con un navegador en `fr`, el sitio sale en español y el panel en inglés. | Quitar «como `site/index.html`», o decir «al revés que el sitio, por la decisión del 2026-10-12». |
| 21 | MENOR | REQ-019 frente al caso límite `spec.md:403-405` | REQ-019 dice que los valores válidos son `es` o `en`, y el caso límite acepta además la variante con región. El ejemplo de valor «mal escrito», `ES_es`, cumpliría esa misma regla de región sin distinguir mayúsculas, así que se aceptaría. | Fijar la gramática en REQ-019 (`^(es|en)([-_][A-Za-z]{2})?$`, sin distinguir mayúsculas) y cambiar el ejemplo de valor no válido (`fr`, `english`). |
| 22 | MENOR | REQ-003 frente al NFR «Operabilidad» (`spec.md:436`) | El NFR dice que `doctor` es «el único sitio» donde se ven los nombres obsoletos, pero REQ-003 los reparte entre `doctor`, `local_status` y la telemetría. El aviso que dejan los hooks en la telemetría no tiene ni clave definida ni nadie que lo lea. | Ajustar el NFR. Para los hooks, nombrar la clave y quién la lee (por ejemplo, `doctor` lee el último evento de la telemetría), o quitar ese canal. |
| 23 | MENOR | REQ-004 (`spec.md:63-68`) | «La versión que lo renombró» es ambigua. Cuando se mezcla la ola, `pyproject.toml` todavía dice 0.34.0; si se toma esa, el alias se retira una versión antes de tiempo. | Definirla como «la primera versión **publicada** que contiene el renombrado», registrada en la release, y un test que la compare con el CHANGELOG. |
| 24 | MENOR | REQ-011 (`spec.md:127-128`) | «El número de checks cambia solo por REQ-003 (sustitución, no suma)» se contradice: una sustitución no cambia el número. Además, `research.md:67` y rename §3.7 dicen «+1 fila». | Escribir «el número de checks no cambia (25): REQ-003 sustituye a `config.rol_retirado`». |
| 25 | MENOR | Casos límite | Faltan tres casos: (a) un panel abierto durante la actualización (JS viejo contra la API nueva: tarjetas vacías hasta recargar); (b) el hook retirado `anotar_llamada.py` que no se puede borrar porque está bloqueado en Windows, y que con el `hook_common` nuevo da `ImportError` en cada llamada MCP; (c) la skill subida a mano a Claude Desktop, que `install` no ve (registro aparte). | Añadirlos como aceptados o con su mitigación (recargar; un hook retirado que falla sin ruido; Claude Desktop fuera de alcance en los non-goals). |
| 26 | MENOR | NFR «Rendimiento» (`spec.md:430-431`) | «No carga más de un idioma a la vez si no hace falta» no se puede comprobar, y choca con REQ-025: el daemon sirve dos idiomas a la vez. | Limitarlo al CLI y a los hooks, o quitarlo. |

### Recuento

- **Bloqueantes:** 3 (hallazgos 1, 2 y 3).
- **Importantes:** 14 (hallazgos 4 a 17).
- **Menores:** 9 (hallazgos 18 a 26).

### Lo que sí está bien (para no reabrirlo)

- Las decisiones del brief están bien recogidas: alias durante dos versiones menores, lectura dual
  para siempre, descripciones de tools solo en inglés, P-4 sin congelar, cookie y `cuota-statusline`.
- REQ-002 cubre los hooks instalados y el aislamiento de entorno. REQ-009 ata la paridad entre
  Python y JS con control positivo. REQ-012/013 cubren `_SCRIPTS_RETIRADOS` y la retirada de skills
  que hoy no existe. REQ-032 pide los guardianes del panel en los dos idiomas y la wiki contra los
  títulos en español. REQ-042 cubre LF/CRLF.
- El caso límite de `test-windows.json` (no subir `version`) es correcto: `test_windows.py:206`
  trata una versión desconocida como error.

### Corrección exacta antes de la ronda 2

1. Hallazgo 1: tabla ordenada de fuentes de idioma por sistema operativo, con casos que distingan.
2. Hallazgo 2: requisito del fixture de idioma en la suite y ampliación del guardián de aislamiento.
3. Hallazgo 3: copiar ya los escáneres a `tools/` y auditar sus dependencias con Socket; asignarlos a
   A0; cambiar el control de texto en inglés de REQ-025 y REQ-034 por uno basado en el catálogo.
4. Hallazgos 4 a 17: reescribir los requisitos afectados como se indica en la tabla.
5. Hallazgos 18 a 26: correcciones de redacción y citas.

### Evidencia recomendada para el gate si se aprueba en la ronda 2

- `review.md` ronda 2 con cada hallazgo marcado como cerrado y la línea de la spec que lo cierra.
- La carpeta `tools/` versionada, con una corrida de control (29/30 españoles detectados y 0/54
  falsos positivos) guardada en `evidence/`.
- El resultado de Socket para `wordfreq` y `esprima`.

## Llamadas local_* y mcp__pycharm__* hechas

| Tool | Para qué | Resultado |
| --- | --- | --- |
| `mcp__local-delegate__local_extract(path=evidence/persisted-data-scan.json, 3 campos)` | Saber qué formatos con claves o valores en español detectó el escaneo, sin leer el JSON entero, para compararlos con REQ-005 | Útil, aunque la salida se truncó y no se pudo convertir a JSON (`_local_delegate.error`, el texto venía en `crudo`). Destapó `vendor.json (paquete)` con claves en español, que no está en la spec (hallazgo 13); lo comprobé después en el fichero |
| `mcp__pycharm__search_symbol("VARIABLES_ROL_RETIRADO")` | Comprobar la cita `config.py:244` | `config.py:244` correcto |
| `mcp__pycharm__search_text("ld_sesion", src/**)` | Comprobar la cita de la cookie (`web/auth.py:45`) | Correcto (también en `auth.py:18`) |
| `mcp__pycharm__search_text("Delegaci", src/**)` | Ver dónde depende algo del título en español | Solo `agents.py:41` lo usa como detector; el bloque de `CLAUDE.md` va por marcadores (hallazgo 6) |

Total: 1 llamada `local_*` y 3 `mcp__pycharm__*`. No delegué más: la revisión exige cotejar
líneas exactas de la spec con líneas exactas del código, y eso no se puede dejar en un resumen.
`spec.md` y `brief.md` los leí por franjas (necesitaba citarlos línea a línea). De los research,
leí por franjas solo las secciones que la spec cita. El código lo comprobé con `sed -n` sobre las
líneas citadas (unas 20 citas). Las `local_*` se cargaron con `ToolSearch` (`local_summarize`,
`local_extract`, `local_lint_summary`, `local_boilerplate`, `local_commit_msg`,
`local_explain_code`). `local_translate` y `local_classify` no se cargaron porque esta tarea no
las necesitaba.

## Respuesta a la revisión — ronda 1

Por el redactor de la spec, 2026-10-12, con las decisiones de la sesión principal para los
bloqueantes y para los hallazgos 4, 5, 6 y 7. La tabla del revisor no se ha tocado. Numeración: los
requisitos conservan su número; los nuevos son REQ-043 a REQ-047.

| # | Cómo queda | Dónde |
| --- | --- | --- |
| 1 | Adoptado con la regla de la sesión principal: precedencia `LOCAL_DELEGATE_LANG` → POSIX (`LC_ALL`, `LC_MESSAGES`, `LANG` como locale efectivo; primer elemento de `LANGUAGE` salvo locale «no declarado»; `C`/`POSIX`/`C.UTF-8` no declarados) → Windows por idioma de la **interfaz** → prefijo `es` o inglés. Tests sobre la función real con entorno y API inyectados, un caso por paso. **Descartado** `defaults read -g AppleLanguages` en macOS: el daemon de `launchd` y los hooks reciben el idioma fijado por `install` (REQ-047), que es lo que resolvía ese caso. | REQ-018, REQ-047 |
| 2 | Adoptado: fixture automático `LOCAL_DELEGATE_LANG=es` por el aislamiento existente; suite en verde con `LANG=en_US.UTF-8` y `es_ES.UTF-8`; control positivo; guardián de aislamiento ampliado a `LANG`/`LC_*`/`LANGUAGE`/API de Windows fuera de la función única. | REQ-043, REQ-018 |
| 3 | Adoptado con la decisión de la sesión principal: la ola A0 mete en `scripts/` el detector con léxico **congelado** como datos (sin `wordfreq` en ejecución) y un tokenizador JS sin dependencias nuevas (o auditado con Socket ≥ 0,7), con sus controles como tests. Además, los escáneres de la investigación ya están conservados en `tools/research-scanners/` (sin rutas privadas) como insumo de A0. Para el frente B, el control deja de ser un detector de español: guardián «ningún texto de salida fuera del catálogo» y control por catálogo en el DOM/salida en inglés, que cubre etiquetas de una palabra. **No se pasó Socket ahora** a `wordfreq`/`esprima`: con el léxico congelado, `wordfreq` solo se usa una vez en A0 y `esprima` puede no usarse; REQ-044 exige la auditoría en ese momento. La referencia inexistente «i18n §0» se quitó. | REQ-044, REQ-045, REQ-025, REQ-034, REQ-016 |
| 4 | Adoptado: REQ-027 pasa al frente B tras el catálogo; REQ-010 lo acompaña por la atadura de versión del brief; el resumen del panel desde el catálogo puede llegar después, y se acepta inglés entretanto. | REQ-010, REQ-027, REQ-035 |
| 5 | Adoptado: `local_commit_msg` sale de la regla de idioma y conserva su comportamiento; test de que su prompt no cambia con el idioma. | REQ-028 |
| 6 | Adoptado: REQ-029 reescrito sobre `agents.py`; el bloque de catálogo de los subagentes **entra** (texto que `install` escribe en ficheros del usuario); encabezado reconocido en los dos idiomas, bloque marcado reemplazado en cualquier idioma, guardián de skills es/en con las mismas tools; subagentes añadidos a REQ-012. El test del bloque gestionado ahora exige el cambio de idioma con un solo bloque, que sí puede fallar. | REQ-029, REQ-012 |
| 7 | Adoptado con la decisión de la sesión principal: `install` fija `LOCAL_DELEGATE_LANG` para daemon, hooks y entradas MCP por stdio; `doctor` y `local_status` muestran idioma y origen y avisan de valores no válidos. **Descartado** que `doctor` consulte al daemon: `local_status` ya lo cubre y es coherente con REQ-003. | REQ-019, REQ-047, REQ-040 |
| 8 | Adoptado: la regla vive una sola vez en un módulo que importan paquete y hooks; test de que el paquete no tiene otra. | REQ-018 |
| 9 | Adoptado: tres clases (estado vigente, cachés con arrastre al fichero nuevo, registros que crecen) y `marcas` arrastradas convertidas cuando tienen equivalente. | REQ-006, REQ-033 |
| 10 | Adoptado en su variante preventiva: el daemon escribe también `enfriamiento.json` mientras vivan los alias, con versión de retirada. | REQ-005, escenario nuevo |
| 11 | Adoptado: las opciones de los scripts entran en el renombrado, pero el comando de P-4 documentado sigue funcionando hasta cerrarla (envoltorio y procedimientos actualizados en la misma ola, comando ejecutado en la verificación). | REQ-046, REQ-015 |
| 12 | Adoptado: por cada script, `--help` y corrida mínima o `get_file_problems`; control positivo con `test_reason`. | REQ-014 |
| 13 | Adoptado: `vendor.json` con su lector y workflow en REQ-005; REQ-016 alcanza los `.json` de `src/**/resources` y nombres de fichero y directorio. | REQ-005, REQ-016 |
| 14 | Adoptado: «todo lector, sin excepción» con los que faltaban nombrados; el corpus y las hojas de F2 ya guardados se leen en los dos formatos. | REQ-006 |
| 15 | Adoptado: registro `waves/<ola>.md` con tablas `local_*` y `mcp__pycharm__*`, exigido por el gate `conformance`, y mínimos comprobables. | REQ-036, REQ-037 |
| 16 | Adoptado: fichero único de fronteras con descripciones, prompts y cualquier texto de hooks; lo leen la medición de adopción y las de calidad que comparen periodos (el plan las enumera: no se comprobó que hoy exista alguna, así que no se nombra ninguna sin verificar). | REQ-041 |
| 17 | Adoptado: el CHANGELOG anuncia el cambio de idioma por defecto y cómo fijar `es`; caso límite de vuelta atrás no soportada. | REQ-040, casos límite |
| 18 | Corregido: REQ-012. | REQ-003 |
| 19 | Corregido: REQ-038. | REQ-017 |
| 20 | Corregido: «al revés que `site/index.html`», con su motivo. | REQ-020 |
| 21 | Corregido: gramática fijada y ejemplos de no válidos `fr`, `english`, `es-419`. | REQ-019 |
| 22 | Corregido: NFR ajustado; los hooks escriben `deprecated_names` en la telemetría y `doctor` lo lee (últimos 7 días). | REQ-003, NFR |
| 23 | Corregido: primera versión **publicada**, con test contra el CHANGELOG. | REQ-004 |
| 24 | Corregido: «el número de checks no cambia (25)»; también en `research.md`. | REQ-011 |
| 25 | Adoptado: panel abierto durante la actualización (aceptado), hook retirado bloqueado (falla sin ruido, `doctor` lo señala, reintento), Claude Desktop en non-goals. | Casos límite, Non-goals |
| 26 | Corregido: el NFR de rendimiento se limita a los hooks y se quita lo de «un idioma a la vez». | NFR |

Llamadas de esta ronda: `local_*` 0 (eran ediciones de ficheros que el redactor ya tenía citados
línea a línea; `review.md` se leyó por franjas porque había que responder a cada hallazgo
literalmente) y `mcp__pycharm__*` 0 (las comprobaciones de existencia de ficheros y opciones se
hicieron con `ls`/`grep`).

## Revisión de la spec — ronda 2

- **Fecha:** 2026-10-12. **Revisor:** el mismo agente adversario de la ronda 1.
- **Insumos:** `spec.md` revisada (719 líneas, REQ-001 a REQ-047), la «Respuesta a la revisión — ronda
  1», `research.md` y `tools/research-scanners/`. He comprobado contra el código las afirmaciones
  nuevas que tienen consecuencias: quién instala el daemon, el `env` de los hooks, la telemetría
  opcional, Playwright en el CI y el arrastre de cachés.

### Veredicto

**No aprobable todavía, pero cerca.** De los 26 hallazgos de la ronda 1, 20 quedan resueltos de
verdad y 6 solo en parte. Las correcciones han traído **1 bloqueante nuevo**: REQ-047 se apoya en un
mecanismo que el paquete no tiene. También hay 7 importantes y 8 menores. Si se cierra el
bloqueante y los importantes 2 a 5, la spec se puede aprobar en la ronda 3 sin otra revisión
completa: bastaría con comprobar esos cinco puntos.

### Comprobación de cada hallazgo de la ronda 1

| # ronda 1 | Estado | Por qué |
| --- | --- | --- |
| 1 Idioma del sistema | **Parcial** | La precedencia ya se puede ejecutar y los casos de prueba distinguen cada paso: `LANGUAGE=es:en`+`LANG=en_US` da `es`; `LANGUAGE=es`+`LANG=C` da inglés; interfaz `en-US` con formato regional `es-ES` da inglés. Pero el caso de macOS y el del daemon sin sesión se resuelven con REQ-047, que no se puede ejecutar (nuevo bloqueante 1). |
| 2 Suite según la máquina | **Parcial** | El fixture, la doble corrida con `LANG` y el control positivo dan un control que sí puede fallar. Falta el navegador de Playwright (importante 2). |
| 3 Herramientas de cierre | Resuelto | Comprobé que `tools/research-scanners/` tiene los 12 escáneres y ninguna ruta privada. A0 tiene asignado REQ-044. El control del frente B (REQ-045 junto con el control por catálogo de REQ-025/034) no depende de detectar español y cubre las etiquetas de una palabra. Aparece un problema nuevo de licencia y tamaño (importante 6). |
| 4 Orden REQ-027 / REQ-035 | Resuelto | Ahora va en B2 y B4. Aparece un problema nuevo con el cierre de A (importante 4). |
| 5 `local_commit_msg` | Resuelto | El test «el prompt no cambia con el idioma» sí puede fallar. |
| 6 REQ-029 / `agents.py` | Resuelto | El test pasa de «0.34.0 en español» a «reinstalar en inglés deja un solo bloque»: una implementación que añade un bloque en vez de reemplazarlo falla. Se cubren los subagentes y hay guardián de que las dos skills listan las mismas tools. |
| 7 Idioma del daemon | **Parcial** | `local_status` informa del idioma y su origen: aceptado el descarte de que `doctor` pregunte al daemon. Pero cómo llega el idioma al daemon depende de REQ-047 (bloqueante 1). |
| 8 Regla duplicada | Resuelto | Una sola implementación, con test de que no hay otra (detalle de copia en el menor 14). |
| 9 Cachés | **Parcial** | Las tres clases de fichero quedan bien separadas, pero la regla de arrastre está mal definida (importante 3). |
| 10 Hooks viejos con daemon nuevo | Resuelto | Escritura doble de `enfriamiento.json`, con horizonte y un escenario propio (detalle en el menor 12). |
| 11 Comando de P-4 | Resuelto | REQ-046 obliga a ejecutar el comando documentado en la verificación (detalle en el menor 11). |
| 12 Scripts | Resuelto | Hay control positivo con `test_reason`. |
| 13 `vendor.json` | Resuelto | Está en REQ-005, y REQ-016 alcanza los `.json` de recursos. |
| 14 Lectores | Resuelto | La lista dice «como mínimo» y nombra los que faltaban. |
| 15 Uso de los MCP | Resuelto | Registro `waves/<ola>.md` y mínimos comprobables (detalle en el menor 13). |
| 16 Fronteras | **Parcial** | Ya cubre prompts y hooks en cualquier idioma, pero una sola fecha no vale para dos máquinas (importante 5). |
| 17 Compatibilidad | Resuelto | REQ-040 anuncia el cambio de idioma por defecto y la vuelta atrás no soportada; hay un escenario para Windows en inglés. |
| 18–21, 23–26 | Resueltos | Comprobado en el texto de cada requisito. |
| 22 Telemetría de hooks | **Parcial** | Ya tiene clave y lector, pero el canal está apagado por defecto (menor 8). |

### Descartes de la respuesta

- **Que `doctor` no pregunte al daemon:** aceptado. Con REQ-019, `local_status` lo cubre y es
  coherente con REQ-003.
- **Socket aplazado a la ola A0:** aceptado. REQ-044 y el NFR de compatibilidad lo exigen antes de
  usar la dependencia.
- **No consultar `AppleLanguages` en macOS:** **no vale mientras REQ-047 no se pueda ejecutar.** El
  motivo del descarte es que «`install` fija el idioma para `launchd`», y `install` no toca
  `launchd` (bloqueante 1). Si REQ-047 se rehace con un mecanismo que llegue al daemon, el descarte
  queda bien.

### Hallazgos nuevos

| # | Severidad | Dónde (spec) | Hallazgo | Corrección propuesta |
| --- | --- | --- | --- | --- |
| 1 | **BLOQUEANTE** | REQ-047 (`spec.md:292-299`); escenario «hook en un sistema en inglés» (`spec.md:529-534`); depende también REQ-024 (`spec.md:328`) | **REQ-047 pide escribir en tres sitios y el paquete no sabe escribir en dos de ellos.** (a) **Daemon:** `install` no instala ningún daemon. No hay código que cree la tarea programada, el `.plist` ni la unidad de `systemd` (`search_text("Register-ScheduledTask")` solo aparece en `docs/wiki/Daemon.md:233`; en `update.py:533-550` solo se consulta, se para y se arranca la tarea). El usuario la crea a mano siguiendo la wiki, y en esta PC el daemon arranca desde un lanzador propio. Tocar ese lanzador está en los non-goals (`spec.md:654-655`). (b) **Hooks:** Claude Code no tiene un bloque `env` por hook, solo el `env` global de `settings.json`, e `install` hoy no lo escribe (el único `env` que escribe es el de las entradas MCP, `install.py:441-481`). (c) Solo las entradas MCP por stdio tienen `env`. Como consecuencia, el escenario del hook en inglés, el descarte de `AppleLanguages` y el hallazgo 7 de la ronda 1 se apoyan en algo que no existe. | Sustituir el mecanismo por uno que el paquete controle entero: un fichero de preferencia de idioma (por ejemplo, `language` en el directorio de configuración del paquete o en `LOG_DIR`) que `install`/`update` escribe y que REQ-018 lee como paso 1b, entre `LOCAL_DELEGATE_LANG` y el sistema. Lo leen igual el daemon, los hooks, el servidor por stdio y el CLI, sin tocar lanzadores ni `settings.json`. Si se prefiere escribir en el `env` global de `settings.json`, decirlo así (afecta a toda la sesión de Claude Code) y aceptar que el daemon arrancado por un lanzador propio no lo verá. En ambos casos, rehacer el test y el escenario con el mecanismo real. |
| 2 | IMPORTANTE | REQ-043 (`spec.md:420-426`); escenario «CI en inglés» | **El fixture no llega al navegador.** El panel elige idioma por `navigator.language` (REQ-020), no por `LOCAL_DELEGATE_LANG`. `tests/test_dashboard_ui.py` abre páginas con `navegador.new_page()` sin `locale` (líneas 159, 201, 239, 375 y 560), y el CI lo corre en Ubuntu (`ci.yml:74-77`), con el navegador en `en-US`. Los 21 asserts en español de ese fichero fallarían. La doble corrida con `LANG` lo detectaría, pero la spec dice que el escenario pasa «porque el fixture fija `es`», y eso es falso para el panel. | Ampliar REQ-043: los tests de Playwright crean el contexto con `locale="es-ES"` (o con `ld-lang=es` en `localStorage`) desde un fixture común, y los tests de inglés lo sobrescriben. Control positivo: sin ese fixture y con el navegador en `en-US`, fallan los asserts en español del panel. |
| 3 | IMPORTANTE | REQ-006, «Cachés de historia» (`spec.md:144-148`) | **La regla de arrastre está mal definida, y su control no ve el fallo que provoca.** «Todas las entradas del viejo que no estén ya en el nuevo», aplicada en **cada** escritura, tiene tres problemas. (a) No dice qué identifica una entrada; los `puntos` de `coste-agregados` no tienen id. (b) Un punto que el nuevo fichero dejó caer por caducado (`recalcular.py:211`, `cuota.py:347`) vuelve del viejo en cada corrida. La vigencia se aplica al leer, así que ya no cuenta para la calibración, pero sí cambia `descartes["caducado"]` (`cuota.py:384`), que el panel muestra; eso choca con REQ-017. (c) En atribución rompe la regla vigente: «una entrada existente solo la sustituye otra de cruce **mejor**» (`atribucion.py:300`). El control previsto («un escritor que no arrastra pierde un cruce») no detecta ninguno de los tres. | El arrastre se hace **una vez**: cuando el fichero nuevo no existe, se siembra desde el viejo con la misma regla de fusión que ya usa cada caché (mejor cruce en atribución; identidad del punto y vigencia en cuota). Desde ese momento solo se lee el nuevo. Añadir controles positivos: un punto caducado no reaparece tras dos corridas, y un cruce `exacto` del viejo no se pierde frente a uno `ventana` del nuevo. |
| 4 | IMPORTANTE | REQ-016 («cierre de A», `spec.md:243-250`, trazabilidad `spec.md:680`) frente a REQ-010 en B2 (`spec.md:674`) | **El cierre de A no puede dar 0.** REQ-010 pasó a B2, así que al cerrar A siguen en el código `truncado`, `aviso`, `leido_server_side`, `respaldo` y `crudo`, y los marcadores `aviso`/`respaldo`. Ninguno cabe en los motivos de excepción permitidos (alias, formato viejo, envoltorio, tercero). | Ejecutar el detector de REQ-016 después de B2, o añadir el motivo de excepción «contrato pendiente de REQ-010, se retira en B2», con un test que exija que esa excepción esté vacía al cerrar B2. |
| 5 | IMPORTANTE | REQ-041 (`spec.md:471-478`) | **Una frontera con una sola fecha no vale para dos máquinas.** Los logs de la Mac se miden en la PC, y la Mac se actualiza cuando el usuario quiere, días o meses después. Con una fecha única, sus filas quedan en el tramo equivocado. La práctica que ya existe es partir los tramos por **versión de hook**: la telemetría lleva `version` (`hook_common.version_de`). Las filas de `usage-*.jsonl` no llevan versión. | La frontera se decide por versión: la del hook en la telemetría y, en `usage-*.jsonl`, una clave nueva de versión del paquete en las filas que se escriben desde el cambio. La fecha queda solo como reserva para filas sin versión. Test con filas de dos máquinas actualizadas en fechas distintas. |
| 6 | IMPORTANTE | REQ-044 (`spec.md:42-58`) | **Congelar el léxico tiene un problema de licencia y otro de tamaño.** `esdet.py` construye el léxico con `top_n_list(lang, 300000)` y `zipf_frequency` para español e inglés (líneas 15 y 19): son unas 600 000 palabras, y la caché de la investigación (`lex.pkl`) pesa 10,7 MB. Los datos de frecuencia de `wordfreq` se distribuyen con licencia CC BY-SA 4.0 (esto hay que comprobarlo en la versión que se use), y el repo es MIT: versionar ese derivado obliga a citar la fuente y a compartirlo con la misma licencia, y mete 10 MB en el repo. | Congelar solo el subconjunto de palabras que aparecen en los tokens del repo (unos miles), con un fichero de atribución, después de confirmar la licencia de la versión de `wordfreq`. O renunciar a congelar y ejecutar el cierre con `uv run --with wordfreq==<versión fijada>`, auditada con Socket. |
| 7 | IMPORTANTE | REQ-028 (`spec.md:360-362`), trazabilidad `spec.md:692` | **La muestra en vivo no tiene criterio para pasar o fallar** (pendiente desde la ronda 1, donde no lo señalé). «Una muestra por tool y por idioma» no dice cuántos documentos ni cuándo se da por buena: no puede dar un resultado distinto. | Fijarlo: por ejemplo, N ≥ 5 documentos por tool e idioma, todos en el otro idioma, y que al menos el 90 % de las respuestas salgan en el idioma vigente. Que lo juzgue un detector de idioma versionado, no el ojo, y que la muestra se guarde en la verificación con el id de la ventana de prueba. |
| 8 | MENOR | REQ-003 (`spec.md:87-89`), NFR «Operabilidad» | **El canal de los hooks está apagado por defecto.** La telemetría solo se escribe si está definida `LD_HOOK_TELEMETRY_LOG` (`hook_common.py:92-96`), y eso es opcional. Para casi todos los usuarios, la clave `deprecated_names` no llega nunca a `doctor`, que además tendría que recorrer un fichero de más de 30 000 líneas. | Decir que el canal solo existe con la telemetría encendida y que `doctor` lee solo la cola del fichero, o quitar el canal: `doctor` ya mira la shell y el `env` de `settings.json`, de donde los hooks heredan casi siempre. |
| 9 | MENOR | REQ-018 paso 2 (`spec.md:265-268`) | No dice qué pasa con `LANG`/`LC_*` **en Windows**. Git Bash y MSYS los definen (a menudo `en_US.UTF-8`), y un hook lanzado desde ahí podría salir por el paso 2 en vez del 3. | Escribir «en Windows, `LANG`/`LC_*`/`LANGUAGE` no se consultan», con un test: Windows con `LANG=en_US.UTF-8` e interfaz `es-ES` da español. |
| 10 | MENOR | REQ-019 (`spec.md:286-288`) frente a REQ-020 | `es-419` (español de América Latina, una etiqueta habitual) es «no válido» en la variable, pero en el navegador da español porque empieza por `es`. La exclusión es arbitraria y además incoherente entre las dos reglas. | Gramática `^(es|en)([-_]([A-Za-z]{2}|[0-9]{3}))?$`. |
| 11 | MENOR | REQ-046 (`spec.md:160-168`) | El envoltorio dura «hasta cerrar P-4» (~2026-12-14), pero nadie queda encargado de retirarlo después; lo más probable es que este SDD ya esté cerrado para entonces. Además, «actualizar esos procedimientos» supone reescribir `verification.md` de SDD cerrados. | Apuntar la retirada en el backlog con su fecha, y en los SDD cerrados añadir una nota fechada en vez de reescribir lo que ya está. |
| 12 | MENOR | REQ-005, excepción, y su escenario (`spec.md:124-127`, `508-513`) | El escenario solo prueba que se escribe al enfriar. Si al limpiar o al reentrar no se refleja también en `enfriamiento.json`, los hooks viejos ven estados distintos. | El test cubre `entra`, `reentra` y `limpia` en los dos ficheros. |
| 13 | MENOR | REQ-036 (`spec.md:441-442`) | El gate `conformance` solo exige que el registro **exista**; un registro sin la fila de `local_lint_summary` también pasaría. | El gate comprueba los mínimos (la fila de `local_lint_summary` en las olas que corren la suite; `rename_refactoring` y `get_file_problems` en las que renombran, o su motivo). |
| 14 | MENOR | REQ-018 («un módulo que importan paquete y hooks») | Si la regla vive en un fichero nuevo, `install` tiene que copiarlo con los hooks y `scaffold.hook_files` tiene que comprobarlo. Si falta, el hook falla al importar. | Decirlo en REQ-018 (o ponerlo dentro de `hook_common.py`) y hacer que el test de `install` compruebe la copia. |
| 15 | MENOR | REQ-045 (`spec.md:386-397`) | No hay forma de declarar las excepciones legítimas en contextos de salida (JSON volcado, el prefijo `[local-delegate error]`, rutas, ids). Sin ella, el guardián o no se puede cumplir o se esquiva clasificando de menos. | Una lista de excepciones con motivo, revisada en cada ola, y un test de que ninguna entrada es texto para personas. |

### Recuento de la ronda 2

- **Bloqueantes:** 1 (nuevo 1: REQ-047 se apoya en mecanismos que el paquete no tiene).
- **Importantes:** 7 (nuevos 2 a 7, con el criterio de REQ-028 dentro del 7).
- **Menores:** 8 (nuevos 8 a 15).
- **De la ronda 1:** 20 resueltos y 6 en parte (1, 2, 7, 9, 16 y 22); lo que les falta queda recogido
  en los hallazgos nuevos 1, 2, 3, 5 y 8.

### Para aprobar en la ronda 3

Cerrar el bloqueante 1 y los importantes 2 a 5. Los importantes 6 y 7 pueden pasar al plan si la
spec lo dice expresamente («lo fija el plan antes de A0» y «lo fija el plan antes de B2»). Los
menores pueden ir al plan.

### Llamadas local_* y mcp__pycharm__* de la ronda 2

| Tool | Para qué | Resultado |
| --- | --- | --- |
| `local_explain_code(path=tools/research-scanners/esdet.py, question=…)` | Saber qué datos de `wordfreq` habría que congelar sin leer el script | Útil: 300 000 palabras por idioma, español e inglés; lo confirmé con `grep` en las líneas 15 y 19 (importante 6) |
| `mcp__pycharm__search_text("Register-ScheduledTask")` | Comprobar si el paquete instala el daemon | Solo en la wiki y en un corpus de benchmark: el paquete no lo instala (bloqueante 1) |
| `mcp__pycharm__search_text("LD_HOOK_TELEMETRY_LOG", src/**)` | Comprobar si la telemetría de hooks es opcional | Sí: `hook_common.py:94` sale si no está definida (menor 8) |

Total: 1 llamada `local_*` y 2 `mcp__pycharm__*`. El resto de comprobaciones fueron lecturas de
líneas concretas con `sed`/`grep` (`update.py`, `install.py`, `cuota.py`, `recalcular.py`,
`atribucion.py`, `tests/test_dashboard_ui.py`, `ci.yml`), donde hacía falta el texto literal para
citarlo.

## Respuesta a la revisión — ronda 2

Por el redactor de la spec, 2026-10-12, con las decisiones de la sesión principal. La tabla del
revisor no se ha tocado. Siguen siendo 47 requisitos (no hay ninguno nuevo; se rehicieron los
afectados).

| # ronda 2 | Cómo queda | Dónde |
| --- | --- | --- |
| 1 (bloqueante) | Adoptada la propuesta del revisor. `install`/`update` guardan el idioma resuelto en la sesión interactiva en un fichero de preferencia `language.json` (propuesto) del directorio de datos del paquete (`LOG_DIR`, que los hooks ya saben resolver). REQ-018 lo lee como paso 2, tras `LOCAL_DELEGATE_LANG` y antes del sistema; llega al CLI, al stdio, al daemon y a los hooks sin tocar lanzadores ni `settings.json`. Orígenes: «variable», «preferencia», «sistema», «reserva». Escenario del hook rehecho y escenario nuevo del daemon de macOS por `launchd`. **`AppleLanguages` sigue sin consultarse**: el motivo del descarte ya no es «`install` toca `launchd`», sino que la preferencia llega a `launchd` sin tocarlo; con eso el descarte de la ronda 1 queda bien, como admitía el revisor. | REQ-047, REQ-018, REQ-019, REQ-040, escenarios, casos límite |
| 2 | Adoptado: fixture común de Playwright con `locale="es-ES"` por defecto y `en-US` en los tests de inglés; la doble corrida con `LANG` incluye esos tests; control positivo sin el fixture de `locale`. | REQ-043, escenario CI |
| 3 | Adoptado con la decisión de la sesión principal: arrastre **una sola vez**, al crear el fichero nuevo, con la regla de fusión propia de cada caché (mejor cruce en atribución; identidad y vigencia en cuota); después no se vuelve a leer el viejo para arrastrar. Controles: segunda corrida sin cambios de recuento ni `descartes`, caducado que no reaparece, cruce `exacto` conservado frente a `ventana`. | REQ-006 |
| 4 | Adoptado: motivo de excepción «pendiente» para lo de REQ-010 que sale en B2; dos controles, cierre de A (pendiente = solo REQ-010) y cierre del cambio (pendiente vacío). | REQ-016 |
| 5 | Adoptado: frontera por versión (de hook en la telemetría; clave nueva `package_version`, propuesta, en `usage-*.jsonl`), la fecha solo como reserva; test con dos máquinas actualizadas en fechas distintas. | REQ-041 |
| 6 | Adoptado con la decisión de la sesión principal, más estricto que lo propuesto: el léxico congelado no lleva datos de terceros; son las palabras del inventario propio del repo clasificadas una vez, más heurísticas sin datos ajenos (ñ, tildes, sufijos), con la generación documentada. `wordfreq` solo, si acaso, fuera del repo para proponer la clasificación. Se añade «sin clasificar» para palabras nuevas, para que el léxico no se quede viejo en silencio. | REQ-044 |
| 7 | Corregido en la spec: ≥5 documentos por tool e idioma, en el otro idioma, ≥90 % en el idioma vigente, juzgado por detector versionado y guardado con el id de la ventana; el detector y el conjunto de documentos los fija el plan antes de B2. | REQ-028 |
| 8 | Corregido: el canal de los hooks existe solo con la telemetría encendida, y `doctor` lee solo la cola (7 días). Sin telemetría lo cubre lo que `doctor` ya mira. | REQ-003 |
| 9 | Corregido: en Windows `LANG`/`LC_*`/`LANGUAGE` no se consultan; caso de prueba con `LANG=en_US.UTF-8` de Git Bash e interfaz `es-ES` → español. | REQ-018 |
| 10 | Corregido: gramática con región numérica; `es-419` válido. | REQ-019 |
| 11 | Corregido: nota fechada en los SDD cerrados en vez de reescribirlos, y retirada del envoltorio apuntada en el backlog con su fecha. | REQ-046 |
| 12 | Corregido: el test de la excepción cubre `entra`, `reentra` y `limpia` en los dos ficheros. | REQ-005 |
| 13 | Corregido: el gate `conformance` comprueba los mínimos, no solo que el registro exista. | REQ-036 |
| 14 | Corregido: la regla vive dentro de `hook_common.py`, que `install` ya copia y `scaffold.hook_files` ya comprueba; no hay fichero nuevo que copiar. | REQ-018 |
| 15 | Corregido: lista de excepciones legítimas con motivo, revisada en cada ola, y test de que ninguna es texto para personas. | REQ-045 |

Llamadas de esta ronda: `local_*` 0 y `mcp__pycharm__*` 0. Eran ediciones dirigidas a líneas ya
conocidas; las dos comprobaciones de código (dónde resuelven los hooks `LOG_DIR` y que no existe un
directorio de configuración aparte) se hicieron con `grep` sobre `hook_common.py` y `config.py`.

## Revisión de la spec — ronda 3

- **Fecha:** 2026-10-12. **Revisor:** el mismo agente adversario de las rondas 1 y 2.
- **Insumos:** `spec.md` (787 líneas) y la «Respuesta a la revisión — ronda 2». He comprobado contra
  el código cómo se resuelve `LOG_DIR` (`config.py:176-177`, `hook_common.py:280-293`), cómo aísla
  la suite el directorio de datos (`tests/conftest.py:45`), la identidad de los puntos de cuota
  (`recalcular.py:176-177`, `210-216`) y qué versión llevan los eventos de los hooks
  (`hook_common.py:60-72`).

### Veredicto

**Aprobable con condiciones.** El bloqueante de la ronda 2 y los importantes 2 a 5, que puse como
condición, están cerrados de verdad, y lo que se deja al plan está marcado expresamente. Quedan
**0 bloqueantes, 4 importantes nuevos y 3 menores**. Los cuatro importantes se arreglan cambiando la
redacción de REQ-047, REQ-043, REQ-041 y REQ-044, sin tocar la arquitectura, y la sesión principal
puede comprobar esos cambios sin otra ronda de revisión. Los menores pueden pasar al plan.

### Comprobación de las condiciones de la ronda 2

| # ronda 2 | Estado | Por qué |
| --- | --- | --- |
| 1 Bloqueante (REQ-047) | **Cerrado** | `language.json` en `LOG_DIR` llega a los cuatro procesos sin tocar lanzadores ni `settings.json`. La resolución con los pasos 1, 3 y 4, sin leer la preferencia vieja, evita el círculo de que `install` se lea a sí mismo. El test «dos idiomas de sesión, el fichero cambia» puede fallar. Con esto, el descarte de `AppleLanguages` queda bien. Sobre la duda del coordinador, `LOG_DIR` distinto en la shell y en el daemon: el caso límite (`spec.md:670-672`) lo acepta y lo hace visible con el origen que muestran `doctor` y `local_status`. Me parece suficiente, salvo el detalle del menor 7. Quedan dos defectos nuevos, al escribir el fichero y en la suite (importantes 1 y 2). |
| 2 Playwright | **Cerrado** | Fixture común con `locale`, la doble corrida incluye Playwright, y hay control positivo sin el fixture de `locale` (`spec.md:464-471`). |
| 3 Arrastre de cachés | **Cerrado** | Se siembra una sola vez, con la regla de fusión de cada caché, y después solo se lee el nuevo. Los tres controles distinguen: segunda corrida sin cambios, el caducado no reaparece, el `exacto` se conserva frente al `ventana` (`spec.md:154-163`). El detalle que falta va en el menor 5. |
| 4 Cierre de A frente a REQ-010 | **Cerrado** | La sección «pendiente» solo puede contener REQ-010 al cerrar A, y tiene que estar vacía al cerrar el cambio. Son dos corridas guardadas (`spec.md:268-271`, `748`). |
| 5 Fronteras por versión | **Cerrado en lo esencial** | `package_version` en `usage-*.jsonl` y un test con dos máquinas. Pero para la telemetría, «versión de hook» es un hash sin orden (importante 3). |
| 6 y 7 (llevados al plan) | **Marcados** | REQ-028: «el detector y el conjunto de documentos los fija el plan antes de B2». REQ-041: «el plan los enumera». REQ-044 dejó de ser diferido: se rehízo sin datos de terceros, pero eso trae un control circular (importante 4). |
| 8 a 15 menores | Cerrados | Comprobados en el texto de cada requisito. |

### Hallazgos nuevos

| # | Severidad | Dónde (spec) | Hallazgo | Corrección propuesta |
| --- | --- | --- | --- | --- |
| 1 | IMPORTANTE | REQ-047 (`spec.md:323-329`) frente a REQ-040 (`spec.md:511-513`) | **`update` deshace la elección explícita del usuario.** REQ-040 dice que, para elegir español con el sistema en inglés, se ejecute `install` con `LOCAL_DELEGATE_LANG=es`. Pero el siguiente `update` lanzado desde una shell sin la variable vuelve a resolver el idioma por el sistema y reescribe `en`. Lo mismo pasa en dirección contraria: un `update` lanzado sin locale declarado (desde la herramienta Bash de un Claude Code abierto desde el Dock en macOS, o desde un contexto no interactivo) cae en «reserva» y reescribe `en` sobre un `es` que había salido del sistema. | Guardar también el **origen** en `language.json` (por ejemplo `{"lang": "es", "source": "variable"}` o `"system"`). `install`/`update` solo reescriben si la resolución nueva viene de la variable, o si lo guardado viene del sistema y lo nuevo también, y nunca con «reserva». Tests: preferencia `es`/variable más `update` sin la variable, el fichero no cambia; preferencia del sistema más `update` en «reserva», no cambia; `update` con la variable `en`, sí cambia. |
| 2 | IMPORTANTE | REQ-043 (`spec.md:462-463`: «el directorio de datos ya está aislado en la suite») | **Esa afirmación es falsa para el código que va a leer la preferencia.** La suite solo cambia `config.LOG_DIR` (`tests/conftest.py:45`) y borra `LOCAL_DELEGATE_LOG_DIR`. La regla de idioma vive en `hook_common.py`, que resuelve el directorio por su cuenta con `LOCALAPPDATA`/`XDG_DATA_HOME`/`~/Library` (`hook_common.py:280-293`), es decir, el directorio **real** del usuario. Todo test que quite `LOCAL_DELEGATE_LANG` para probar los pasos del sistema, y todo hook lanzado como subproceso, leería el `language.json` real. En esta PC, tras `install`, ese fichero dice `es`: el test pasaría en el CI y fallaría aquí, o al revés. La doble corrida en CI no lo ve, porque allí no existe ese fichero. | (a) La función de idioma recibe el directorio de datos como argumento: el paquete pasa `config.LOG_DIR` y los hooks `directorio_de_logs()`. (b) Un fixture automático fija `LOCAL_DELEGATE_LOG_DIR=<tmp>` en el entorno, para los subprocesos de hooks. (c) Control positivo: con `LOCALAPPDATA`/`HOME` apuntando a un directorio falso que contiene un `language.json` con `en`, un test que espera `es` sigue en verde. |
| 3 | IMPORTANTE | REQ-041 (`spec.md:522-531`) | **La versión de los hooks no tiene orden.** La versión de un evento de telemetría es `version_de(script)`, los ocho primeros hex del sha256 del script (`hook_common.py:60-72`). «Filas anteriores en versión» no se puede decidir con hashes, y cada ola que toca hooks (A2, B3) genera hashes nuevos. Tal como está escrito, el test de las dos máquinas solo vale para `usage-*.jsonl`. | Para la telemetría, la frontera es un **conjunto**: el fichero de fronteras lista, por script, los hashes que quedan del lado «después», generados en el PR de release a partir de `resources/hooks/`. Un test exige que el hash de los scripts actuales esté en ese conjunto (si no, se olvidó actualizarlo). El test de las dos máquinas usa un hash viejo con fecha posterior. |
| 4 | IMPORTANTE | REQ-044 (`spec.md:45-59`) | **El control del detector es circular.** El léxico se construye con las palabras **del propio repo**, clasificadas una vez, y los 30 nombres españoles y 54 ingleses de control salen de ese mismo repo. El test «29 de 30 y 0 de 54» se cumple por construcción y no puede fallar: comprueba la búsqueda en la tabla, no si la clasificación está bien. Ahora el riesgo está en los miles de palabras clasificadas a mano o con ayuda; por ejemplo, `modelo`, `codigo` o `cadena`, mal clasificadas como inglés, dejarían nombres españoles sin detectar en el cierre. | (a) Tratar el 29/30 y el 0/54 como test de regresión, no como control. (b) Añadir como control una **auditoría de la clasificación**: muestra aleatoria de al menos 100 palabras del léxico, revisada, con error ≤ 2 %, guardada en `evidence/`. (c) Añadir un conjunto de palabras **reservadas** (españolas e inglesas que no están en el repo) para probar las heurísticas: ñ, tildes, sufijos. (d) Los «sin clasificar» bloquean el cierre de REQ-016, como ya dice «no cuenta como 0». |
| 5 | MENOR | REQ-006, siembra de cuota (`spec.md:155-158`) | La identidad del punto es `(fuente, tipo, inicio, fin)` (`recalcular.py:176-177`), y `fuente` es un valor de enumeración que se renombra (`rechazo`). Si la siembra junta los puntos viejos con los nuevos **antes** de traducir `fuente`, el mismo punto entra dos veces. | Decir que se traduce antes de juntar, y añadir un test: punto viejo con `fuente=rechazo` y su gemelo nuevo, resultado un solo punto. |
| 6 | MENOR | REQ-047; `uninstall` | No se dice qué hace `uninstall` con `language.json`. | Decirlo: se borra con el resto de lo que instala `install`, o se conserva a propósito, con su motivo. |
| 7 | MENOR | Caso límite «distinto directorio de datos» (`spec.md:670-672`) | El origen («sistema» frente a «preferencia») delata que hay diferencia, pero no dice **qué directorio** leyó cada proceso, que es lo que hace falta para arreglarlo. | `doctor` y `local_status` muestran también la ruta de `language.json` que consultaron. |

### Recuento de la ronda 3

- **Bloqueantes:** 0.
- **Importantes:** 4 (nuevos 1 a 4).
- **Menores:** 3 (nuevos 5 a 7).
- **Condiciones de la ronda 2:** el bloqueante y los importantes 2 a 5, cerrados. El 5 está cerrado
  en lo esencial, y lo que le falta queda en el importante 3 de esta ronda.

### Condiciones para registrar el gate `spec`

Aplicar en la spec las correcciones de los importantes 1 a 4 tal como están en la tabla. Son cambios
de redacción en REQ-047, REQ-043, REQ-041 y REQ-044 con sus tests, y la sesión principal los puede
comprobar sin otra ronda. Los menores 5 a 7 pueden ir al plan, marcados como tales.

### Llamadas local_* y mcp__pycharm__* de la ronda 3

| Tool | Para qué | Resultado |
| --- | --- | --- |
| `local_explain_code(path=tests/conftest.py, question=…)` | Saber si la suite aísla el directorio de datos también para el código que lo resuelve por variables de entorno, sin leer el `conftest` entero | Útil: solo cambia `config.LOG_DIR` y borra `LOCAL_DELEGATE_LOG_DIR`, así que `hook_common` resuelve el directorio real. Lo confirmé con `grep` en `conftest.py:45` (importante 2) |
| `mcp__pycharm__search_text("def _clave_de_punto")` | Encontrar la identidad de los puntos de cuota | `recalcular.py:176`: `(fuente, tipo, inicio, fin)` (menor 5) |

Total: 1 llamada `local_*` y 1 `mcp__pycharm__*`. El resto fueron lecturas de líneas concretas con
`sed`/`grep` (`config.py`, `hook_common.py`, `recalcular.py`), donde hacía falta el texto literal
para citarlo.

## Respuesta a la revisión — ronda 3

Por el redactor de la spec, 2026-10-12. Se aplican tal cual las propuestas del revisor, por
indicación de la sesión principal; la tabla del revisor no se ha tocado. Siguen siendo 47
requisitos. Los tres menores se resuelven en la spec, no se pasan al plan.

| # ronda 3 | Cómo queda | Dónde |
| --- | --- | --- |
| 1 | `language.json` guarda idioma y origen. `install`/`update` escriben si la resolución viene de la variable; si viene del sistema, solo cuando no hay fichero o lo guardado también vino del sistema; nunca pisan una elección explícita y nunca escriben la reserva. Tests: variable guardada + `update` sin variable (no cambia); sistema guardado + `update` en reserva (no cambia); `update` con la variable (cambia). | REQ-047 |
| 2 | La función de idioma recibe el directorio de datos como argumento; un fixture automático fija `LOCAL_DELEGATE_LOG_DIR` a un temporal, también para hooks como subproceso. Control positivo: `LOCALAPPDATA`/`HOME` falsos con un `language.json` en `en` no alteran un test que espera `es`, y sin el fixture falla un test de hook como subproceso. Se quitó la afirmación falsa «el directorio de datos ya está aislado». | REQ-043 |
| 3 | Para la telemetría, la frontera es un conjunto de hashes por script del lado «después», generado en el PR de release desde `resources/hooks/`, con test de que el hash actual está en el conjunto; `package_version` sigue ordenando `usage-*`. El test de dos máquinas usa un hash viejo con fecha posterior. | REQ-041 |
| 4 | El 29/30 y 0/54 pasan a ser regresión. Controles nuevos: auditoría manual de una muestra aleatoria de ≥100 palabras del léxico con error ≤ 2 % guardada en `evidence/`, y palabras reservadas que no están en el repo para las heurísticas (ñ, tildes, sufijos). Los «sin clasificar» bloquean el cierre. | REQ-044 |
| 5 | Los valores de enumeración del viejo, `fuente` incluida, se traducen antes de juntar los puntos de cuota; test con punto viejo `fuente=rechazo` y su gemelo nuevo → un solo punto. | REQ-006 |
| 6 | `uninstall` borra `language.json` (es configuración del instalador, no dato de medición), con test. | REQ-047 |
| 7 | `doctor` y `local_status` muestran la ruta del `language.json` consultado. | REQ-047, caso límite |

Llamadas de esta ronda: `local_*` 0 y `mcp__pycharm__*` 0. Eran ediciones de redacción sobre
requisitos ya conocidos y las citas de código las había comprobado el revisor en esta misma ronda.

## Revisión de la spec — verificación final

- **Fecha:** 2026-10-12. **Revisor:** el mismo agente adversario. **Alcance:** solo las 7
  correcciones de la ronda 3, y si traen algo nuevo de severidad bloqueante o importante.

### Veredicto

**Aprobable.** Las 7 correcciones están aplicadas en la spec y cada una tiene un control que puede
fallar. No aparece nada nuevo bloqueante ni importante. Queda un menor, que puede resolverse en el
plan o en la wiki.

| # ronda 3 | Estado | Dónde lo comprobé |
| --- | --- | --- |
| 1 `update` pisaba la elección | Cerrado | `spec.md:344-358`: el fichero guarda el origen; la regla de escritura nunca pisa una elección explícita ni escribe la reserva; hay cuatro tests que distinguen los casos. |
| 2 Aislamiento de la preferencia | Cerrado | `spec.md:490-497`: la función de idioma recibe el directorio como argumento, el fixture fija `LOCAL_DELEGATE_LOG_DIR` y hay un control positivo con un `LOCALAPPDATA`/`HOME` falso y otro sin el fixture. Es compatible con el aislamiento que ya existe: el fixture de sesión `entorno_sin_variables_del_paquete` (`tests/conftest.py:18-39`) borra la variable y uno por test la vuelve a fijar después. |
| 3 Hashes sin orden | Cerrado | `spec.md:555-563`: para la telemetría, la frontera es un conjunto de hashes por script, generado en el PR de release, con un test de que el hash actual está en el conjunto. `package_version` sigue sirviendo para `usage-*.jsonl`. |
| 4 Control circular | Cerrado | `spec.md:56-66`: el 29/30 y el 0/54 pasan a ser regresión. Hay control de heurísticas con palabras que no están en el repo, y auditoría de al menos 100 palabras, con semilla y error ≤ 2 %, guardada en `evidence/`. |
| 5 `fuente` antes de juntar | Cerrado | REQ-006 y su trazabilidad (`spec.md:778`). |
| 6 `uninstall` | Cerrado | `spec.md:351`, con test. |
| 7 Ruta de la preferencia | Cerrado | `spec.md:352-353`; la verificación en vivo exige la misma ruta en `doctor` y en `local_status`. |

**Menor nuevo (al plan o a la wiki):** con la regla de escritura de REQ-047, una vez guardada una
elección explícita, no hay forma de volver a «seguir al sistema» salvo borrar el fichero o ejecutar
`uninstall`. Conviene que REQ-040 o la wiki digan cómo hacerlo, por ejemplo borrando `language.json`
desde la ruta que muestra `doctor`.

### Llamadas local_* y mcp__pycharm__* de la verificación final

| Tool | Para qué | Resultado |
| --- | --- | --- |
| `mcp__pycharm__search_text("def entorno_sin_variables_del_paquete", tests/**)` | Comprobar que el fixture nuevo de `LOCAL_DELEGATE_LOG_DIR` no choca con el aislamiento de sesión | `tests/conftest.py:20`; leído con `sed` (líneas 18-46): son compatibles |

`local_*`: 0. Motivo: había que comprobar líneas concretas de la spec y de `conftest.py`, cortas y
con el texto literal necesario para citarlas; no había nada que resumir ni que extraer.

## Revisión del plan — ronda 1

- **Fecha:** 2026-10-12. **Revisor:** agente adversario (`general-purpose`), con el criterio de
  `personal-sdd-review` para planes: cobertura de requisitos, secuencia, dependencias, seguridad,
  tests y vuelta atrás.
- **Gate:** `plan`. **Insumos:** `plan.md` entero (1 221 líneas), `spec.md` aprobada y el código de
  `main` (`8ec2f1d`).
- **Citas del plan comprobadas en el código (22).** Correctas: `cli.py:56-71` (`_resolve_clients`,
  el patrón `--target`/`--clients`), `cli.py:46`, `cli.py:1423`, `server.py:68-73`, `:474`, `:497`,
  `:747`, `:998`, `:1081`, `:1099`, `:2169`, `:2422`, `:2964`, `:3201`, `atribucion.py:30`, `:73`,
  `web/metrics.py:623`, `:1935`, `cadenas.py:42`, `checks.py:1629`, `checks.py:1652` y
  `test_dashboard_ui.py:581`/`:641`. Una inexacta: `cli.py:1459` es el inicio del texto de ayuda de
  `install`, no una mención de la skill (menor). Además existen `scripts/bump_version.py` y
  `scripts/extract_dashboard_js.py`, y la sección `[0.30.0]` del CHANGELOG nombra las tres variables
  `fast`.

### Veredicto

**No aprobable todavía.** Hay 1 bloqueante: la 0.35.0, instalada con `update`, deja la skill vieja
nombrada en el bloque de memoria y en los subagentes, justo lo que REQ-012 prohíbe. Hay además 6
importantes y 5 menores. El resto del plan está bien armado:
- cubre los 47 requisitos con su ola y su evidencia;
- la P-4 no se rompe en ningún punto intermedio: los valores en A3 y los ficheros en A4 cambian en el
  mismo PR que el script, el comando se ejecuta en A3, A4 y A10a, y hay envoltorio;
- los controles positivos nombran el assert que debe dispararse;
- las releases y la mecánica de `UNRELEASED` encajan con REQ-004 y REQ-010/027.

### Hallazgos

| # | Severidad | Dónde (plan) | Hallazgo | Corrección propuesta |
| --- | --- | --- | --- | --- |
| 1 | **BLOQUEANTE** | A6 (`plan.md:560-590`), tests «`install` sobre una 0.34.0»; release 0.35.0 (`:977`) | **La 0.35.0 instalada con `update` deja nombrada una skill que ya no existe.** Que el bloque y los subagentes nombren la skill nueva tras `install` **o `update`** lo exige REQ-012, y el primer escenario de la spec lo hace precisamente con `update`. Pero `update` solo repara lo que un check marca, y `scaffold.memory` solo se repara si **falta** (`update.py:200`, `Repair("scaffold.memory", (checks.MISSING,), …)`). Los subagentes (`agents`) ni siquiera entran en lo que repara `update`: son opcionales (`install.py:1049-1060`, `cli.py:30`). Tras `update`, A6 borra `delegacion-local` (retirada) y deja el bloque gestionado de `CLAUDE.md`/`AGENTS.md` y los bloques de catálogo de los subagentes («Detalle en la skill `delegacion-local`», `agents.py:46-50`) apuntando a una skill borrada. El plan solo prueba `install`, así que no lo detectaría. | En A6: (a) `scaffold.memory` pasa a `WARN` cuando el bloque presente difiere del empaquetado (por ejemplo, porque nombra una skill retirada), y `update` lo repara en `WARN`; (b) `update` regenera los bloques de catálogo de los subagentes que **ya tienen** los marcadores `local-delegate:catalog`, sin necesitar `--agents`, porque solo toca dentro de sus propios marcadores; (c) un test de **`update`** sobre una 0.34.0 simulada (no `install`), con controles positivos: sin (a), el bloque sigue nombrando `delegacion-local`; sin (b), lo sigue nombrando un subagente. |
| 2 | IMPORTANTE | §1.3 (`plan.md:681-693`), A8b (`:626-629`) | **A7 y A8b, que van en paralelo, comparten `web/metrics.py`.** El plan dice que «A7 no toca `web/metrics.py`», pero `metrics.py` llama a funciones de `server` con nombre en español que A7 renombrará con `rename_refactoring`: `server.sondear_backend` (`:758`, `:846`), `server._plazo_sonda` (`:788`, `:819`, confirmado con PyCharm), `server._backend_en_loopback` (`:817`) y `server._clashes_by_groups`/`_topology`. PyCharm reescribe esas llamadas dentro de `metrics.py` mientras A8b es dueña única del fichero en otro worktree: conflicto, o una ola que se para por la regla 4. | Poner A8b **después** de A7b, o sacar del alcance de A7 los símbolos de `server` que usa `metrics.py` y dárselos a A8b (lista cerrada en `waves/A7a.md`). |
| 3 | IMPORTANTE | §1.4 (`plan.md:695-701`) y olas B1–B5 | **El frente B no tiene orden ni dueños exclusivos.** B1, B2a, B2b y B4 son dueñas a la vez de `resources/i18n/es.json` y `en.json`; B1 y B5, de `install.py`; B1, B4 y A9a tocan `tests/conftest.py`. Tampoco se dice si B1–B5 se mezclan antes o después de A9 y A10, y A9 renombra justo los tests que B modifica (`test_checks`, `test_dashboard_ui`, `test_install*`, `test_metrics`, `test_wiki`). Además, B0 amplía el guardián de aislamiento (`tests/test_aislamiento_entorno.py`), que renombra A9a («a*»), y solo `conftest.py` figura como compartido. | Escribir el orden de B como el de A (por ejemplo, `A9c → A10b → B0 → B1 → B2a → B2b → B3 → B4 → B5`, o qué va en paralelo y por qué). Partir el catálogo en un fichero por espacio de nombres (`i18n/es/cli.json`, `…/panel.json`…) para que cada ola sea dueña única de los suyos. Dejar B1–B5 para después de A9c, o quitar a A9 los tests que B modifica. Añadir `test_aislamiento_entorno.py` a lo que B0 toca después de mezclar A9a. |
| 4 | IMPORTANTE | Tamaños de A5a, A8a, A9 y A10 (`plan.md:498`, `:611-614`, `:643-644`, `:672-673`); §2.1 (`:893-894`) | **Los tamaños no caben en el contexto de un agente, y falta el artefacto para revisar los nombres.** Son unos 3 600 nombres internos, y A9 tiene unas 11 550 apariciones en tres subolas. Con un `rename_refactoring` por símbolo, A9 sola son más de 1 000 llamadas a PyCharm en un único contexto. Además, nadie revisa los ~3 600 nombres ingleses antes de aplicarlos, aunque «decidir nombres» es justo lo que el plan dice que no se delega. El mínimo de «≥1 `rename_refactoring`» se cumple con una sola llamada, así que no mide nada. | (a) Antes de cada ola, un fichero de correspondencias revisado (`waves/<ola>-names.csv`: viejo, nuevo, tipo, definición) generado del inventario, que fija los nombres antes de tocar nada. (b) PyCharm solo para los símbolos que cruzan módulos (los que `analyze_calls` muestra con llamadores fuera del fichero). Los nombres locales, y los `test_*` sin referencias, van por un script que reemplaza tokens enteros desde ese CSV y conserva el salto de línea. (c) Un tope por agente (por ejemplo, ≤ 150 renombres de PyCharm o ≤ 1 500 líneas de diff) y reparto en subolas según el CSV. (d) Como mínimo de REQ-037: que todo nombre del CSV marcado «cruza módulos» tenga su fila de `rename_refactoring`. |
| 5 | IMPORTANTE | D1 y A0 (`plan.md:303-306`, `:329-331`) | **El test de horizonte se pone en rojo en A0.** Las tres variables `fast` entran en `DEPRECATED_NAMES` con `introduced="0.30.0"`, así que su retirada sería la 0.33.0, anterior a la 0.34.0 actual. Si el test de horizonte recorre todas las entradas, A0 falla nada más nacer. Y el aviso de REQ-003, que imprime «la versión de retirada», diría que se retira en una versión ya pasada. Esas variables no son alias: no funcionan. | Distinguir en el registro `kind=retired` (o `new=None`) de los alias: el test de horizonte y la versión de retirada solo se aplican a alias con sucesor, y para las retiradas el aviso dice «ya no tiene efecto desde la 0.30.0». Test: una entrada retirada con una versión antigua no hace fallar el horizonte, y un alias con `introduced`+3 ≤ versión sí. |
| 6 | IMPORTANTE | D8 (`plan.md:198-204`) y riesgo de argparse (`:1120`) | **El parche de argparse solo se prueba en Python 3.11, y el paquete admite cualquier versión desde la 3.11** (`requires-python = ">=3.11"`). `uv tool install` suele tomar el Python más nuevo de la máquina, y las versiones posteriores añaden o cambian msgid de argparse (sugerencias de opción, mensajes nuevos). El CI corre solo 3.11 (`ci.yml:35,133,190`), así que lo que dice la tabla de riesgos («caza cualquier msgid que falte en cualquier versión del CI») no protege a esos usuarios: en español verían mezclas en inglés, contra REQ-021. | Que el test saque los msgid **del argparse que se está ejecutando** (por AST de `argparse.__file__`, buscando las llamadas a `_()`/`ngettext()`) y falle si alguno no tiene clave. Y añadir al CI al menos un trabajo con la última versión estable de Python que corra los tests del CLI. |
| 7 | IMPORTANTE | D10, criterio (`plan.md:255-256`) | **El criterio de la muestra rebaja el de la spec y se contradice a sí mismo.** REQ-028 pide ≥ 90 % por tool **e idioma**. Con 5 documentos eso es 5 de 5, pero el plan añade «o, como mucho, 1 fallo por tool en el total de 10», que permite un 4 de 5 (80 %) en un idioma. Son dos reglas para una misma decisión. | Quedarse con «5 de 5 por tool e idioma», o subir a 10 documentos por tool e idioma para que un fallo siga dentro del 90 %. Quitar la segunda regla. |
| 8 | MENOR | Regla 6 (`plan.md:42-45`), REQ-042 | Comparar `eol-before` y `eol-after` **por ruta** no puede salir igual en una ola que renombra ficheros, porque las rutas cambian. Además, solo cubre los ficheros que la ola posee, no los que `rename_refactoring` toca fuera (imports). | Comparar por correspondencia vieja→nueva (`git diff -M --name-status`) y sobre todos los ficheros del diff, no solo los poseídos. |
| 9 | MENOR | A1 (`plan.md:349-363`) | A1 hace que `local_status` liste los nombres obsoletos, pero `server.py` no está en su lista «posee»: por la regla 4 se pararía. | Añadir `server.py` (solo `local_status`) a lo que posee A1. |
| 10 | MENOR | §2.1 y §2.3 (`plan.md:888-966`) | Los mínimos de `waves/<ola>.md` se pueden comprobar, pero a mano. Con unos 25 registros, el gate `conformance` necesita algo que no dependa del ojo. | Un script pequeño (`scripts/check_wave_records.py`) que compruebe en cada registro las filas mínimas (`local_lint_summary`, `rename_refactoring`/`get_file_problems` o motivo, controles positivos con el assert que disparó). Su salida va a la evidencia del gate. |
| 11 | MENOR | §4.2 (`plan.md:1074-1077`) | El paso nuevo de `ci.yml` duplica en CI la suite de ubuntu en cada PR de las ~25 olas. | Ejecutarlo solo cuando el PR toque `src/` o `tests/` (filtro `paths`), o dejarlo en un trabajo programado más el PR de release. |
| 12 | MENOR | A6 (`plan.md:567`) | La cita «`cli.py:1459`» como mención de la skill no es exacta: es el inicio de la ayuda de `install`. | Citar la línea exacta de la mención, o usar `search_text("delegacion-local")` en la ola. |

### Recuento

- **Bloqueantes:** 1 (hallazgo 1).
- **Importantes:** 6 (hallazgos 2 a 7).
- **Menores:** 5 (hallazgos 8 a 12).

### Lo que está bien (no reabrir)

- La matriz cubre los 47 requisitos, y lo que la spec dejó «para el plan» queda resuelto uno a uno
  (§7): D6 `?lang=`, D5 catálogo, D10 detector y muestra, D9 scripts, D11.
- La P-4 queda protegida en cada punto intermedio (A3, A4 y A10a, con envoltorio y notas fechadas).
- El CHANGELOG, la firma de los commits, CodeQL «arreglar, no descartar» y `gh pr checks` están en
  las reglas comunes y en la mecánica de release.
- Los hooks viejos con daemon nuevo quedan cubiertos por la doble escritura (A4) y la lectura de los
  temporales con los dos nombres (A2).
- La limitación de la doble corrida con `LANG` en Windows está bien detectada y resuelta con el paso
  en el CI de ubuntu y con WSL.

### Para aprobar en la ronda 2

Cerrar el bloqueante 1 y los importantes 2 a 5. Los importantes 6 y 7 se pueden cerrar cambiando el
texto de D8 y D10. Los menores pueden quedar como tareas dentro de su ola.

### Llamadas local_* y mcp__pycharm__* de la revisión del plan

| Tool | Para qué | Resultado |
| --- | --- | --- |
| `local_explain_code(path=src/local_delegate/update.py, question=…)` | Saber qué repara `update` y bajo qué condición, sin leer las 38 k de caracteres del fichero | Útil, aunque se truncó la entrada a 20 k. Dijo que la memoria solo se repara si falta y que los subagentes no entran; lo confirmé con `grep` en `update.py:200` y `install.py:1049-1060` (bloqueante 1) |
| `mcp__pycharm__search_text("server._plazo_sonda")` | Comprobar si `web/metrics.py` usa símbolos de `server` que renombrará A7 | Sí, `metrics.py:788` y `:819` (importante 2) |

Total: 1 llamada `local_*` y 1 `mcp__pycharm__*`. Las 22 citas se comprobaron con `sed -n` sobre
las líneas exactas, porque había que ver el texto literal. El plan lo leí por franjas: necesitaba
citarlo línea a línea.

## Respuesta a la revisión del plan — ronda 1

Por el planificador, 2026-10-12, con las decisiones de la sesión principal. La tabla del revisor no
se ha tocado. Todos los cambios están en `plan.md`.

| # | Cómo queda | Dónde (plan) |
| --- | --- | --- |
| 1 (bloqueante) | Se adopta la propuesta del revisor, en A6, la misma ola que borra la skill. (a) `scaffold.memory` pasa a `WARN` si el bloque gestionado difiere del empaquetado, y `update` lo repara también en `WARN`. (b) `update` regenera los bloques de catálogo de los subagentes que ya tienen los marcadores `local-delegate:catalog`, sin necesitar `--agents`. (c) Un test de `update` sobre una 0.34.0 simulada (skill vieja, bloque viejo y subagentes) acaba sin ninguna mención a `delegacion-local`; tiene dos controles positivos, uno sin (a) y otro sin (b). | D12; A6 (posee `update.py`, `agents.py` y `test_update.py`); riesgos; matriz REQ-012 |
| 2 | A8b va después de A7b, sin paralelo. A7a y A7b poseen en `web/metrics.py` solo las líneas que llaman a `server`, con una lista cerrada en `waves/A7a.md`. | A7, A8b, §1.3 |
| 3 | El orden del frente B es explícito: `A10b → B0 → B1 → B2 (B2a → B2b) → {B3 ∥ B4} → B5`. Ninguna ola B se mezcla antes de A10b; B0 se desarrolla antes y se rebasa. El catálogo y la lista de pendientes van partidos por superficie (`resources/i18n/<lang>/<surface>.json`, `tests/data/uncatalogued_pending/<surface>.json`). Cada fichero tiene una sola ola B dueña: `install.py` y `update.py` son solo de B5, mensajes incluidos; `checks.py` solo de B1; `server.py` solo de B2; `conftest.py` e `i18n.py` solo de B0, con el fixture de `locale` y D8 dentro. El conjunto de hashes pasa a un fichero aparte, de B3. Solo `hook_common.py` tiene dos dueñas, B0 y luego B3, en serie. Los dos repartos que cambian respecto de la traceability de la spec (`package_version` a B2 y el fixture de `locale` a B0) están en §8. | §1.4, D5, D9, B0–B5, §8 |
| 4 | D13 y la regla 11: antes de renombrar, `tools/make_mapping.py` genera `waves/<ola>-mapping.csv` (viejo, nuevo, tipo, definición, ámbito, método y motivo). La sesión principal lo revisa y lo aprueba, y solo entonces se aplica. Lotes de ≤ 300 nombres por agente; A9, con 8 lotes como mínimo. El mínimo de PyCharm se puede comprobar: filas `rename_refactoring` = filas `method=pycharm` del mapping, y las de búsqueda y edición se cuentan aparte, con su motivo. | Regla 11, D13, A9, §2.1, plantilla |
| 5 | Las entradas que ya existen al crear el registro (las variables `fast`) van como `kind=retired`, con su horizonte propio (`warn_until=0.37.0`) y el aviso «ya no tiene efecto». El horizonte de `introduced`+3 solo se aplica a los alias con sucesor. La regla está escrita en D1, y hay un test de que A0 nace en verde. | D1, A0 |
| 6 | El test saca los msgid del argparse en ejecución (AST de `argparse.__file__`). `argparse.json` cubre la unión de las versiones que admite el paquete. Un workflow nuevo, `ci-lang.yml`, corre los tests del CLI con una matriz de todas las versiones de Python admitidas. | D8, §4.2, riesgos |
| 7 | Queda una sola regla, la de la spec: ≥ 90 % por tool e idioma, que con 5 documentos es 5 de 5; un `unknown` cuenta como fallo. Se quitó la segunda regla. | D10 |
| 8 | La comparación de EOL se hace sobre todos los ficheros del diff y sigue la correspondencia de renombres de `git diff -M` (`eol-check.txt`). | Regla 6, plantilla, matriz REQ-042 |
| 9 | A1 posee `server.py`, solo en el apartado de `local_status`. | A1 |
| 10 | `tools/check_wave_records.py` (A0, en la carpeta del cambio) comprueba los mínimos de cada registro y de cada mapping, y deja su salida como evidencia del gate `conformance`; tiene su propio control positivo. | A0, §2.1 |
| 11 | El paso de `LANG=es_ES.UTF-8` va en `ci-lang.yml`, con filtro `paths` (`src/**`, `tests/**`, `pyproject.toml`), más los PR de release y `workflow_dispatch`. `ci.yml` no se toca. | §4.2 |
| 12 | Corregido: las menciones son `cli.py:1423` (`help=` de `--no-skill`) y `cli.py:1460` (dentro de la ayuda de `install`, que empieza en `:1459`), comprobadas con `git grep`. En la ola se confirman con `search_text`. | A6 |

Llamadas de esta respuesta: `local_*` 0 y `mcp__pycharm__*` 0. Fueron ediciones dirigidas a secciones
conocidas del plan. La única comprobación de código, las menciones de la skill en `cli.py`, se hizo
con un `git grep` de una línea, que da el texto literal que hacía falta citar.

## Revisión del plan — ronda 2

- **Fecha:** 2026-10-12. **Revisor:** el mismo agente adversario de la ronda 1.
- **Insumos:** `plan.md` (1 446 líneas) y la «Respuesta a la revisión del plan — ronda 1». Leí
  enteras las secciones nuevas o cambiadas: reglas 6 y 11, D1, D8, D12, D13, §1.3, §1.4, B0–B5 y
  §4.2. Contra el código y GitHub comprobé tres cosas: el ruleset de `main` (los checks que exige),
  el alcance de `scripts/ci_gate.py` y cómo escribe `install` los ficheros del usuario (copias
  `.bak` y saltos de línea).

### Veredicto

**No aprobable todavía.** El bloqueante y los importantes 2 a 5 de la ronda 1 están cerrados. Pero
el arreglo del bloqueante (D12, en A6) choca con el bloque bilingüe de B5 y crea **1 bloqueante
nuevo**. Hay además 4 importantes y 4 menores, nuevos todos. Los cambios de ola pedidos
(`package_version` a B2 y el fixture de `locale` a B0) no cambian nada de lo que exige la spec,
porque la trazabilidad del frente B era provisional y salen en la misma 0.36.0.

### Comprobación de la ronda 1

| # | Estado | Por qué |
| --- | --- | --- |
| 1 Bloqueante (`update` y la skill retirada) | **Cerrado en la 0.35.0** | D12: `scaffold.memory` en `WARN` si el bloque está desfasado, `update` lo repara, los subagentes ya marcados se regeneran sin `--agents`, y hay un test **de `update`** con dos controles positivos. Pero, tal como está diseñado, rompe la 0.36.0 (bloqueante nuevo 1). |
| 2 A7 frente a A8b | Cerrado | Ya van en serie (`plan.md:836-843`). |
| 3 Orden y dueños del frente B | Cerrado, con dos cruces | El orden es explícito, el catálogo y la lista de pendientes van partidos por superficie y cada fichero tiene una sola ola dueña. Pero quedan dos consumos de lo que produce una ola posterior (importante 2 y menor 3), y la propiedad exclusiva de `checks.py` impide arreglar el bloqueante nuevo. |
| 4 Tamaños y nombres | Cerrado en lo esencial | Hay ficheros de correspondencias aprobados por la sesión principal, lotes de ≤ 300 y el mínimo de PyCharm igualado a las filas `method=pycharm`. Pero el `scope` del mapping no puede salir de PyCharm dentro de un script (importante 3). |
| 5 Horizonte en A0 | Cerrado | `kind=retired` con `warn_until=0.37.0`, medido aparte, y un test de que A0 nace en verde (`plan.md:96-107`). |
| 6 argparse | Cerrado en el diseño | Los msgid salen del argparse en ejecución, el catálogo es la unión de versiones y hay una matriz de Python. Pero el workflow que lo ejecuta no bloquea el merge (importante 1). |
| 7 Criterio de D10 | Cerrado | Una sola regla: 5 de 5, y `unknown` cuenta como fallo. |
| 8–12 menores | Cerrados | Comprobados en la regla 6 y en A0, A1, §4.2 y A6. |

### Hallazgos nuevos

| # | Severidad | Dónde (plan) | Hallazgo | Corrección propuesta |
| --- | --- | --- | --- | --- |
| 1 | **BLOQUEANTE** | D12 (`plan.md:343-347`) y A6 (`:699`, `:731`), frente a B5 (`:1049-1054`) y la propiedad de `checks.py` (`:873`) | **Con el bloque bilingüe de B5, `doctor` daría aviso para siempre y `update` reescribiría el bloque en cada pasada.** A6 hace que `scaffold.memory` compare el bloque presente con **el** empaquetado (`local-delegate.md`, en español). B5 añade `local-delegate.en.md` e `install` escribe el bloque en el idioma vigente. Un usuario en inglés tendría `WARN` permanente, y cada `update` lo «repararía» con el mismo bloque inglés, que seguiría sin coincidir. Pasa lo mismo, en cualquier idioma, con un `CLAUDE.md` en CRLF: `_write_text` conserva el salto de línea del fichero (`install.py:957`), así que la comparación literal con el recurso LF nunca da igual. No se puede arreglar dentro del plan: `checks.py` es solo de B1, que va antes de B5 y no tiene todavía los bloques ingleses, y B5 no puede tocarlo. | En A6, definir la comparación como «el bloque presente, con los saltos de línea normalizados, es igual al empaquetado de **algún** idioma admitido», y sacar la lista de bloques empaquetados de una función de `install.py` (por ejemplo, `packaged_memory_blocks()`) que A6 crea con el español y B5 amplía con el inglés, sin tocar `checks.py`. Tests en A6: un `CLAUDE.md` en CRLF con el bloque al día da `OK`. Test en B5: un bloque inglés al día da `OK` y `update` no lo reescribe. Controles positivos: con la comparación sin normalizar falla el caso CRLF, y sin el bloque inglés en la lista falla el de B5. |
| 2 | IMPORTANTE | B0 (`plan.md:897`) y §4.2 (`:1289-1292`) frente a B1 (`:935-936`) | **B0 consume un test que produce B1.** El segundo trabajo de `ci-lang.yml`, que nace en B0, ejecuta `tests/test_cli_english.py` (con `test_argparse_msgids_covered`), y ese fichero lo crea B1. En el PR de B0, pytest saldría con «file or directory not found» (código 4) y el trabajo quedaría en rojo. | B0 crea `ci-lang.yml` solo con la suite en `es_ES.UTF-8`, y B1 le añade el trabajo de la matriz de Python junto con su test. O que B0 sea también dueña de ese test con un esqueleto que B1 llena; el reparto exclusivo del frente B pide lo primero. |
| 3 | IMPORTANTE | D13 (`plan.md:365-371`), regla 11 | **El `scope` del mapping «según `analyze_calls` y `search_symbol`» no puede calcularlo un script.** `tools/make_mapping.py` es un programa: no puede llamar a las tools MCP de PyCharm, que solo usa un agente. Calcular el `scope` así exigiría unas 3 600 llamadas `analyze_calls` del agente, justo la carga de contexto que D13 quería evitar. El `scope` decide el método (`pycharm` o `search_edit`) y el mínimo de REQ-037, así que es el dato del que depende todo el control. | Que `make_mapping.py` calcule el `scope` por análisis estático: un índice de referencias por AST y por tokens en `src/`, `tests/` y `scripts/` (dónde se define cada nombre y en qué ficheros aparece). Que el agente compruebe con `analyze_calls` solo las filas `cross_module`, y una muestra de las `module_local`, anotando las discrepancias en el registro de la ola. |
| 4 | IMPORTANTE | D9 y B2b (`plan.md:977-982`), test de dos máquinas | **Con la fecha como reserva, las filas sin `package_version` de una máquina rezagada caen en el tramo equivocado.** Todo lo que escriben la 0.34.0 y la 0.35.0 carece de `package_version`, que nace en la 0.36.0. Una Mac que siga en la 0.35.0 después de la fecha de reserva escribe filas sin versión y con fecha «después», y la fecha de reserva las clasificaría como «después». Es justo el caso que REQ-041 quería evitar. El test de dos máquinas solo prueba filas **con** versión vieja, que la 0.35.0 no escribe. | Precisar en §8: «una fila sin `package_version` es del tramo "antes"», porque toda versión del lado «después» la escribe; la fecha solo decide si un día se cambia esa regla. Test: fila sin versión con fecha posterior → «antes». Control positivo: clasificar por fecha hace fallar ese caso. |
| 5 | IMPORTANTE | §4.2 (`plan.md:1286-1292`) | **`ci-lang.yml` no bloquea el merge.** El ruleset de `main` exige `ci-gate`, `lint`, `test (ubuntu-latest)`, `test (macos-latest)`, `secrets` y `Analyze (python)` (`gh api …/rulesets/19859628`). `ci-gate` solo mira el run de `ci.yml` (`scripts/ci_gate.py:89-95`, `JOBS_ESPERADOS`). Un `ci-lang` en rojo, que es justo la evidencia que discrimina de REQ-043 y la de la matriz de argparse de REQ-021, no impide mezclar: depende de que la sesión principal lo vea. Y si se añadiera al ruleset tal cual, el filtro `paths` dejaría colgados los PR que no tocan esas rutas. | Llevar los dos trabajos a `ci.yml`, que ya corre en todos los PR, y añadirlos a `JOBS_ESPERADOS` de `ci_gate.py`. Así `ci-gate`, que el ruleset ya exige, los hace obligatorios sin tocar el ruleset ni usar un filtro `paths`. Si se quiere ahorrar tiempo, el filtro va dentro del trabajo (un paso que sale en verde cuando no hay cambios en `src/`/`tests/`), no en `on:`. |
| 6 | MENOR | D12, test de `update` (`plan.md:354-356`) | El assert «ningún fichero bajo ese `HOME` contiene `delegacion-local`» falla aunque la implementación sea correcta: `install` deja una copia `.bak` de cada fichero del usuario que reescribe (`install.py:215`), y `CLAUDE.md.bak` y `<subagente>.md.bak` contienen la cadena vieja. El control dispararía por un motivo que no es el defecto. | Excluir `*.bak` del recorrido, o afirmar sobre la lista cerrada de ficheros vivos (`CLAUDE.md`, `AGENTS.md`, subagentes `.md` y skills). |
| 7 | MENOR | D1 (`plan.md:85`) | La lista de `kind` no incluye `retired`, que sí aparece unas líneas más abajo (`:102`). | Añadir `retired` a la lista. |
| 8 | MENOR | B2b (`plan.md:967`, `:982`) frente a B3 (`:1003-1004`) | `measurement_boundaries.json` (B2b) hace referencia a `hook_hashes_after.json`, que crea B3 después. | Decir que, mientras no exista ese fichero, su conjunto se lee como vacío (sin fronteras de hooks), y que B3 lo crea. Test en B2b: sin el fichero, no hay error. |
| 9 | MENOR | §4.2, matriz de `ci-lang` | Una matriz «hasta la última estable» puede ponerse en rojo por dependencias sin wheels para un Python recién publicado, sin relación con el cambio. | Limitar la matriz a los tests del CLI, que no necesitan Playwright, y marcar la versión más nueva como `continue-on-error` hasta que sus dependencias tengan wheels, anotándolo en el registro de B0/B1. |

### Recuento de la ronda 2

- **Bloqueantes:** 1 (nuevo 1: el bloque de memoria bilingüe y en CRLF frente a D12).
- **Importantes:** 4 (nuevos 2 a 5).
- **Menores:** 4 (nuevos 6 a 9).
- **De la ronda 1:** el bloqueante y los importantes 2 a 7 cerrados, salvo lo que se arrastra en los
  hallazgos nuevos 1, 3 y 5.

### Consumos de una ola posterior (lo pedido expresamente)

Revisé las dependencias de cada ola contra lo que producen las anteriores. Hay tres casos:
1. A6 (D12) depende de los bloques ingleses que crea B5 (bloqueante 1).
2. B0 ejecuta un test que crea B1 (importante 2).
3. B2b hace referencia a un fichero que crea B3 (menor 8).

El resto encaja:
- el mapping de D13 usa el detector de A0;
- B2b usa el detector de idioma de B0;
- B4 usa las `t_lang` de B2;
- B3 usa el fichero de fronteras de B2b y el nombre del script que deja A10a;
- B1 usa el fichero de preferencia que lee B0; el formato lo fija la spec y los tests lo fabrican.

### Para aprobar en la ronda 3

Cerrar el bloqueante 1 y los importantes 2 a 5. Son cambios acotados en D12/A6, B0/B1, D13, D9/§8 y
§4.2. Los menores pueden quedar como tareas dentro de su ola.

### Llamadas local_* y mcp__pycharm__* de la ronda 2

| Tool | Para qué | Resultado |
| --- | --- | --- |
| `local_extract(path=.github/workflows/ci.yml, fields=[jobs, disparadores, versiones de Python])` | Saber qué trabajos y versiones de Python tiene `ci.yml`, sin leer el fichero | Útil: los trabajos son `lint`, `test`, `install-smoke`, `secrets` y `ci-gate`; los disparadores, `push`, `pull_request` y `workflow_dispatch`; solo Python 3.11 (importante 5) |
| `mcp__pycharm__search_text("JOBS_ESPERADOS =")` | Ver qué trabajos vigila `ci-gate` | `scripts/ci_gate.py:89`: solo los de `ci.yml` (importante 5) |

Total: 1 llamada `local_*` y 1 `mcp__pycharm__*`. El ruleset lo consulté con `gh api` (sin
escribir nada), y `install.py:215`/`:957` y `ci_gate.py` con `grep`/`sed`, porque hacía falta el
texto literal.

## Respuesta a la revisión del plan — ronda 2

Por el planificador, 2026-10-12. Se adoptan las propuestas del revisor, con las indicaciones de la
sesión principal. La tabla del revisor no se ha tocado.

| # | Cómo queda | Dónde (plan) |
| --- | --- | --- |
| 1 (bloqueante) | `scaffold.memory` y la regeneración de `update` comparan con los saltos de línea normalizados contra el bloque empaquetado de **cualquier** idioma. La lista sale de `packaged_memory_blocks()` en `install.py`, que A6 crea (solo `es`) y B5 amplía (`en`); `checks.py` solo la llama. Tests: en A6, un bloque en CRLF no da aviso ni se reescribe, y una segunda pasada de `update` no cambia nada; en B5, un bloque inglés al día no da aviso ni se reescribe. Cada uno tiene su control positivo. | D12, A6, B5, riesgos |
| 2 | B0 solo añade el trabajo que ejecuta tests que ya existen (`test-lang-es`). B1 añade `cli-python-matrix` junto con el test que ejecuta. `ci.yml` y `ci_gate.py` tienen dos dueñas en serie, B0 y B1. | B0, B1, D8, §1.4, §4.2 |
| 3 | `make_mapping.py` calcula `scope` por análisis estático: un índice de referencias por AST y por tokens. El agente verifica con PyCharm todas las filas `cross_module` y una muestra del 10 % (20 como mínimo) de las `module_local`, en la columna `verified`, y lo cuenta en el registro de la ola. | D13, §2.1 |
| 4 | Una fila sin `package_version` es siempre del tramo «antes», sin mirar la fecha, con un test y su control positivo. Como cambia la redacción de la reserva de REQ-041, va en §8 como desviación propuesta. | D9, §8 |
| 5 | No hay `ci-lang.yml`. Los dos trabajos van en `ci.yml`, sin filtro `paths`, y entran en los trabajos esperados de `ci_gate.py` (`JOBS_ESPERADOS` o el nombre que le dé A10), así que `ci-gate` los hace obligatorios. Para el coste, la suite entera corre una sola vez (Python 3.11, `LANG=es_ES.UTF-8`) y solo los tests del CLI van en la matriz de Python. | §4.2, D8, B0, B1, matriz |
| 6 | Pasa a ser una tarea de A6: el assert recorre solo la lista cerrada de ficheros vivos y deja fuera los `*.bak`. | D12 |
| 7 | Pasa a ser una tarea de A0: `retired` está en la lista de `kind`. | D1 |
| 8 | Pasa a ser una tarea de B2b: mientras B3 no cree `hook_hashes_after.json`, se lee como un conjunto vacío, sin error, y hay un test. B2b no consume nada posterior. | D9 |
| 9 | Pasa a ser una tarea de B1: si la versión más nueva de Python no tiene wheels, su celda de la matriz va con `continue-on-error`, anotada en el registro de la ola hasta que la instalación funcione; nunca tapa un fallo del test. | D8, riesgos |

Llamadas de esta respuesta: `local_*` 0 y `mcp__pycharm__*` 0. Fueron ediciones de redacción sobre
secciones del plan que ya estaban localizadas, y las citas de código (`install.py:215` y `:957`,
`ci_gate.py`) las comprobó el revisor en esta misma ronda.

## Revisión del plan — ronda 3

- **Fecha:** 2026-10-12. **Revisor:** el mismo agente adversario de las rondas 1 y 2.
- **Insumos:** «Respuesta a la revisión del plan — ronda 2», las secciones cambiadas de `plan.md`
  (D9, D12, D13, B0, B1, §4.2 y §8), la enmienda de REQ-041 en `spec.md` y `scripts/ci_gate.py`
  (cómo decide el veredicto).

### Veredicto

**Aprobable con condiciones.** El bloqueante y los cuatro importantes de la ronda 2 están cerrados
de verdad. No quedan bloqueantes. Hay 2 importantes nuevos, que se arreglan con texto en D9 y D13,
y 3 menores. La sesión principal puede comprobar los dos importantes sin otra ronda.

### Comprobación de la ronda 2

| # | Estado | Por qué |
| --- | --- | --- |
| 1 Bloqueante (bloque bilingüe y CRLF) | **Cerrado** | `packaged_memory_blocks()` en `install.py`: A6 la crea y B5 la amplía, y `checks.py` solo la llama, así que no hay que tocarlo. La comparación normaliza los saltos de línea y vale contra cualquier idioma. Hay tests de CRLF, de segunda pasada (sin ficheros ni `.bak` nuevos) y del bloque inglés en B5, cada uno con su control positivo. La regeneración de subagentes usa el mismo criterio. El assert ya excluye los `.bak`. |
| 2 B0 consumía un test de B1 | **Cerrado** | B0 solo añade `test-lang-es`, con tests que ya existen; `cli-python-matrix` llega en B1 con su test. |
| 3 `scope` sin PyCharm | **Cerrado en lo esencial** | Índice por AST y por tokens dentro del script; PyCharm verifica todas las filas `cross_module` y una muestra del 10 % (20 como mínimo) de las `module_local`, en la columna `verified`, con regla de escalado. El detalle de la granularidad queda en el importante 2. |
| 4 Filas sin versión | **Cerrado** | La spec quedó enmendada («una fila sin versión cuenta siempre como "antes"», `spec.md:562-563`), y en D9 hay test y control positivo. Quedan textos atrasados en §8 (menor 3). |
| 5 `ci-lang.yml` no bloqueaba | **Cerrado** | Los trabajos van en `ci.yml`, sin filtro `paths`, y entran en los trabajos esperados de `ci_gate.py`, que el ruleset exige vía `ci-gate`. Hay un detalle con `continue-on-error` (menor 1). |
| 6–9 menores | Pasados a tareas de su ola | Comprobados en D12, D1, D9 y D8. |

### Hallazgos nuevos

| # | Severidad | Dónde (plan) | Hallazgo | Corrección propuesta |
| --- | --- | --- | --- | --- |
| 1 | IMPORTANTE | D9 (`plan.md:295-296`) y §3.2 (`:1268`): «`--boundaries` **regenera** el conjunto de hashes a partir de `resources/hooks/`» | **El conjunto de hashes «después» tiene que crecer, no regenerarse.** Si en cada release se rehace solo con los hooks actuales, en la 0.37.0 desaparecen los hashes de la 0.36.0. Los eventos de una máquina que siga en la 0.36.0 dejarían de estar en el conjunto y pasarían a «antes», que es justo el error de tramo que REQ-041 quiere evitar. | Decir que `--boundaries` **añade** los hashes actuales al conjunto (unión) y nunca quita ninguno. Test: con un conjunto que ya tiene el hash de una versión anterior, una regeneración tras cambiar un hook conserva el viejo y añade el nuevo. Control positivo: con una regeneración que sustituye el conjunto, falla. |
| 2 | IMPORTANTE | D13 (`plan.md:404-419` aprox.: «`cross_module`: aparece en más de un fichero») | **Clasificar por «aparece como token en más de un fichero» junta símbolos distintos con el mismo nombre.** Nombres comunes en español (`estado`, `datos`, `ruta`, `texto`…) son variables locales independientes en decenas de funciones y ficheros. Con una fila por **nombre**, todos salen `cross_module`, método `pycharm`, y un `rename_refactoring` sobre una definición solo renombra esa. El resto queda sin renombrar y lo cazaría, tarde, el detector de cierre. Además infla las filas `cross_module`, que hay que verificar todas con PyCharm, y descuadra el mínimo «filas `rename_refactoring` = filas `pycharm`». | Una fila por **definición** (nombre más `fichero:línea` y ámbito). El `scope` se calcula por las referencias que resuelven a esa definición (resolución de nombres por AST: locales, módulo, atributos e imports), no por coincidencia de tokens. Solo es `cross_module` si un import o un atributo la usa desde otro fichero. Test de `make_mapping.py`: dos funciones en dos ficheros con una variable local `estado` dan dos filas `function_local`, no una `cross_module`. |
| 3 | MENOR | B1 (`cli-python-matrix`) y la tarea del menor 9 de la ronda 2 frente a `scripts/ci_gate.py:196-207` | `ci_gate.py` falla ante un trabajo esperado cuya conclusión no sea `success`/`skipped`, y espera, hasta fallar por tiempo, a uno que no aparece. Un `continue-on-error` **a nivel de trabajo** deja la conclusión en `failure` y el gate lo da por malo. Además, cada celda de la matriz tiene nombre propio (`cli-python-matrix (3.13)`…) y hay que listarla en los trabajos esperados; al añadir una versión de Python hay que tocar los dos sitios. | La celda de la versión más nueva sin wheels **no** va en los trabajos esperados mientras dure esa situación, o el `continue-on-error` va a nivel de paso de instalación, nunca del test. Un test de `ci_gate` que compruebe que los trabajos esperados coinciden con los nombres que genera la matriz de `ci.yml`. |
| 4 | MENOR | §8 (`plan.md:1512-1519`) y D9 (`:281`, `:287`) | §8 sigue presentando la regla de las filas sin versión como «desviación propuesta… necesita el visto bueno», pero la spec ya está enmendada. D9 mantiene `fallback_utc` («dato informativo») y la frase de que «la fecha se usaría si algún día…», un campo que nada lee. | En §8, anotar que la spec ya la incorporó (enmienda del 2026-10-12). Quitar `fallback_utc` del fichero de fronteras, o decir que nadie lo lee y que un test lo comprueba. |
| 5 | MENOR | D12, subagentes (`plan.md:31-32` del extracto de D12) | «Solo reescribe si su bloque difiere» no dice **de qué**. Con dos idiomas, tiene que ser «de los bloques de catálogo de cualquier idioma», como en la memoria. Si no, un subagente con el catálogo en el otro idioma se reescribiría en cada `update`. | Escribirlo igual que para la memoria (normalizado, contra el catálogo de cualquier idioma) y extender la prueba de segunda pasada de B5 a un subagente. |

### Recuento de la ronda 3

- **Bloqueantes:** 0.
- **Importantes:** 2 (nuevos 1 y 2).
- **Menores:** 3 (nuevos 3 a 5).
- **De la ronda 2:** el bloqueante y los cuatro importantes cerrados.

### Condiciones para registrar el gate `plan`

Aplicar los importantes 1 y 2 en el texto de D9/§3.2 y de D13, con sus tests. La sesión principal
lo comprueba sin otra ronda. Los menores 3 a 5 quedan como tareas de B1, del propio plan y de A6/B5.

### Llamadas local_* y mcp__pycharm__* de la ronda 3

| Tool | Para qué | Resultado |
| --- | --- | --- |
| `local_explain_code(path=scripts/ci_gate.py, question=…)` | Saber qué hace el gate con un `continue-on-error` de trabajo y con trabajos que no están en la lista | Útil: un trabajo esperado en `failure` da fallo, y los que no se esperan se ignoran. Lo confirmé leyendo `ci_gate.py:196-207`, que además espera al trabajo esperado que no aparece (menor 3) |
| `mcp__pycharm__search_text("JOBS_ESPERADOS", scripts/ci_gate.py)` | Localizar dónde se define y dónde se usa la lista | `:89`, `:202` y `:297` |

Total: 1 llamada `local_*` y 1 `mcp__pycharm__*`.

## Respuesta a la revisión del plan — ronda 3

Por el planificador, 2026-10-12. Se adoptan las propuestas del revisor, con las indicaciones de la
sesión principal. La tabla del revisor no se ha tocado.

| # | Cómo queda | Dónde (plan) |
| --- | --- | --- |
| 1 | `--boundaries` **añade** los hashes actuales al conjunto «después» (unión acumulativa) y nunca quita ninguno. Test en B3: tras regenerar con un hook cambiado, el hash de la versión anterior sigue dentro. Control positivo: sustituir en vez de unir. | D9, B3, §3.2 |
| 2 | Hay una fila por **definición** (nombre más `fichero:línea` y ámbito), resuelta por AST: locales, módulo, atributos e imports, no tokens. Los homónimos de módulos o funciones distintos son filas distintas. `cross_module` solo si un import o un atributo la usa desde otro fichero, y lo que la resolución no alcanza va como `unresolved`, con verificación obligatoria. El mínimo de PyCharm se cuenta sobre esas filas, y cada `rename_refactoring` se registra con su definición. Test: dos variables locales `estado` en dos ficheros dan dos filas `function_local`. | D13, §2.1 |
| 3 | Cada celda de la matriz figura en los trabajos esperados de `ci_gate.py`, y un test exige que coincidan con la matriz de `ci.yml`. La versión de Python sin wheels va a una lista de exclusión de `ci_gate.py` (`PYTHON_WITHOUT_WHEELS`, con fecha y motivo): corre pero no bloquea, y solo si lo que falla es la instalación. No hay `continue-on-error` a nivel de trabajo. Es tarea de B1, la dueña de esos ficheros. | D8, §4.2, riesgos |
| 4 | Quitados de §8 la «desviación propuesta» (la spec ya está enmendada, `spec.md:562-563`) y, de D9, `fallback_utc` y la frase sobre la fecha. | D9, §8 |
| 5 | Los subagentes se comparan, con los saltos de línea normalizados, contra el catálogo empaquetado de **cualquier** idioma (`packaged_catalog_blocks()`, que A6 crea y B5 amplía). La prueba de segunda pasada de B5 incluye subagentes con el catálogo en los dos idiomas. | D12 |

Llamadas de esta respuesta: `local_*` 0 y `mcp__pycharm__*` 0. Fueron ediciones de redacción sobre
secciones ya localizadas, y las citas de código (`ci_gate.py:196-207`, `spec.md:562-563`) son las que
comprobó el revisor en esta ronda.

## Revisión del plan — verificación final

- **Fecha:** 2026-10-12. **Revisor:** el mismo agente adversario. **Alcance:** solo las 5
  correcciones de la ronda 3, y si traen algo bloqueante o importante.

### Veredicto

**Aprobable.** Las 5 correcciones están en `plan.md`, cada una con su test y su control positivo
donde corresponde. No traen nada bloqueante ni importante; queda un menor, que es una tarea de A0.

| # ronda 3 | Estado | Dónde lo comprobé |
| --- | --- | --- |
| 1 Unión de hashes | Cerrado | `plan.md:309` y `:1306`: unión acumulativa que nunca quita. Test en B3, con control «sustituir en vez de unir». |
| 2 Una fila por definición | Cerrado | `plan.md:431-457`: fila por nombre, definición y ámbito, resuelta por AST. `cross_module` solo si un import o un atributo la usa desde otro fichero. Las referencias dinámicas van como `unresolved`, con verificación obligatoria. Test de los dos `estado` locales, con su control. |
| 3 Matriz y `ci_gate` | Cerrado | `plan.md:274-281` y `:1446`: cada celda figura en los trabajos esperados, con un test que exige que coincidan con la matriz. `PYTHON_WITHOUT_WHEELS` lleva fecha y motivo y solo vale si falla la instalación. No hay `continue-on-error` de trabajo. |
| 4 §8 y `fallback_utc` | Cerrado | La «desviación propuesta» y `fallback_utc` ya no aparecen. |
| 5 Catálogo de subagentes | Cerrado | `plan.md:386-393`: `packaged_catalog_blocks()`, con comparación normalizada contra cualquier idioma. La segunda pasada de B5 incluye subagentes en los dos idiomas. |

**Menor nuevo (tarea de A0, en `tools/make_mapping.py` y su script de reemplazo):** con una fila
por definición, el reemplazo de tokens de las filas `function_local` tiene que limitarse al tramo de
líneas de su función, que da el AST. Si se aplica a todo el fichero, dos homónimos de un mismo
fichero que pasan a nombres distintos se pisan. Basta con un test: dos funciones del mismo fichero,
cada una con su `estado` y destinos distintos, quedan cada una con el suyo.

### Llamadas local_* y mcp__pycharm__* de la verificación final

| Tool | Para qué | Resultado |
| --- | --- | --- |
| `mcp__pycharm__search_text("PYTHON_WITHOUT_WHEELS")` | Comprobar dónde aparece la lista de exclusión | Solo en `plan.md:277` y `:1446` (y en esta revisión): coherente, no hay restos |

`local_*`: 0. Motivo: eran comprobaciones de unas pocas franjas de `plan.md` que había que citar
línea a línea; no había nada que resumir ni que extraer.
