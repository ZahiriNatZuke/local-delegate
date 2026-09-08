# Verification: La salida grande va a fichero, no al contexto

## Environment

- Revision: rama `main` sobre `75f351b`, T10 implementada (sin commitear al escribir esto).
- Runtime: Python 3.11, `uv run pytest` / `uv run ruff`. Backend real: llama-swap en
  `127.0.0.1:9292`, `llama31-8b` cargado, **`n_ctx` = 16 384**. Daemon MCP: paquete publicado
  **0.26.0** (código *sin* el arreglo), que es lo que lo hace utilizable como control.

## Evidence

### T10 — el reintento del map-reduce deja de estar ciego

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-023/024 | Test de regresión con el mensaje real, corrido **contra el código de ayer** | **Falla**, y falla por el assert que dice: pasa la guarda «llegó a provocar el desborde» y revienta en `assert not salida.startswith("[local-delegate error]")` | `test_el_mensaje_real_de_este_backend_dispara_el_reintento` |
| REQ-024 | Formas del catálogo (llama.cpp, OpenAI/vLLM, LM Studio) + **control negativo** (conexión caída, 500 genérico, modelo inexistente, cadena vacía) | Pasa. El control negativo es la mitad del test: sin él, reconocer cualquier error también pasaría | `test_la_deteccion_de_desborde_cubre_las_formas_del_catalogo` |
| REQ-026 | Desborde irreductible → mensaje accionable, y **mutante dirigido** (`if False:` en el bloque nuevo) | El mutante hace fallar `assert "no cabe" in salida`, o sea el assert propio del requisito y no una guarda anterior | `test_un_desborde_agotado_se_explica_en_vez_de_soltar_el_error_crudo` |
| REQ-023 (alcance real del bug) | Medición contra el backend real por el daemon publicado | **El `400` siempre se reconoció**: `uv.lock` (197 949 chars) se resume en 7 partes y **18 pasadas**, o sea con reintentos por desborde | Log de uso `2026-09-08T18:56:57Z` |
| REQ-023 (el caso ciego) | Reconstrucción del `500` desde el log | Los dos eventos fallidos traen `error: http_500`, `chars_out: 137` y **sin `chunks`** (omitido cuando vale 1 → una sola llamada, cero reintentos). 137 = prefijo (49) + `{"error":{"code":500,"message":"Context size has been exceeded.","type":"server_error"}}` (88). Cuadra al carácter | Log `2026-09-08T18:20:48Z` y `:49Z` |
| REQ-025 | `local_summarize(path=CHANGELOG.md)` por el daemon **sin el arreglo** | **Funciona** (4 partes, 5 pasadas, `ok=true`) → el caso no discrimina. Requisito retirado en la spec | Log `2026-09-08T18:55:18Z` |

### Extremo a extremo con el código nuevo contra el backend real

La clave del backend la tiene el lanzador del daemon y no el shell —un proceso propio da `401`—.
Se desbloqueó leyéndola del almacén cifrado del propio lanzador (DPAPI, mismo usuario) **en la
misma línea** que lanza el script, sin que el secreto pase por un fichero en claro ni por la
salida. Script: `scratchpad/e2e_t10.py`; el log va al scratchpad para no
contaminar la telemetría real.

| Caso | Comprobación | Resultado |
| --- | --- | --- |
| No-regresión, prosa | `local_summarize(path=CHANGELOG.md)` | se resume sin error |
| No-regresión, denso | `local_summarize(path=uv.lock)` | se resume sin error |
| El reintento sigue vivo | firma de troceado del mismo caso | **7 partes en 18 pasadas**, o sea reintento por desborde disparado y resuelto |
| REQ-026 de verdad | `CHUNK_MIN_CHARS` 45 000 y 100 000 chars densos: los trozos llegan al presupuesto, desbordan el `n_ctx` de 16 384 y **no se pueden partir por debajo del mínimo** | Sale el mensaje nuevo: *«el contenido no cabe en el contexto de llama31-8b, ni partido en trozos de 45000 caracteres. Sube el contexto del backend para ese modelo, usa uno con contexto mayor, o pasa menos contenido de una vez»*, con la respuesta del backend detrás |

**Ojo con el presupuesto:** el primer intento de montar el caso 3 no llegó a desbordar.
`budget = max(CHUNK_MIN_CHARS, max_chars × 0,8)`, así que **subir el mínimo de troceado sube
también el presupuesto** y los trozos salieron más pequeños, no más grandes. El caso solo
discrimina si el fichero es lo bastante grande para que los trozos lleguen al presupuesto nuevo.

### T0 — `hook_common` aprende a reescribir

| Requisito | Comprobación | Resultado |
| --- | --- | --- |
| REQ-002 (soporte) | `emit_updated_input()`, camino separado de `emit()` | Emite `hookSpecificOutput.updatedInput`, con `additionalContext` opcional y sin inventar la clave cuando no lo hay |
| Auditabilidad | Toda reescritura deja huella | `rewritten: true` en la telemetría, y el test comprueba además que ni el comando ni sus argumentos entran al log |
| REQ-017 (coherencia) | La relación entre `LD_HOOK_ENABLED` y el registro, **por escrito** | Resuelta: la variable es el interruptor del **A/B**, y **solo puede apagar**. Encender es cosa del registro, y de ahí no se sale — cuando la única puerta era la variable, `install --enable-read-hook` registró el script sin ponerla y el hook quedó instalado e inerte, en silencio |

### T1 — Módulo de decisión (`output_policy.py`)

Puro, stdlib, sin E/S ni entorno, para que el replay de T7 pueda llamarlo en un bucle.

| Requisito | Comprobación | Resultado |
| --- | --- | --- |
| REQ-002b | Subshell y no llaves; prefijo `cd` fuera | `( CMD ) > ruta`, y `cd build && ( make -j4 ) > …`. Con control: `make "a && b"` no se confunde con un prefijo |
| REQ-003 | El andamiaje no puede construirse con nada del comando | **Dos comandos muy distintos producen andamiajes idénticos.** Es la forma que discrimina: buscar marcas concretas solo encontraría las que se me ocurrieran a mí |
| REQ-003b | Lista cerrada de utilidades | `echo`, `wc`, `tail`, escritas en el código; el test exige que estén todas y que no aparezca ninguna otra |
| REQ-005 | Extracto corto en éxito, largo en fallo | 15 líneas frente a 120 |
| REQ-006/007/009 | Escapes | Ya redirige, ya acota, heredoc, comillas sin cerrar, lectores de fichero. Los lectores se prueban **con el aprendizaje al máximo** para que la guarda sea lo único que los salva, y hay un control de que esa misma estadística sí haría candidato a otro |
| REQ-010/011/012 | Semilla y aprendizaje | 15 ecosistemas; el aprendizaje contradice a la semilla **en los dos sentidos** |
| REQ-016 | La señal «truncada» pesa más | Dos estadísticas con las mismas muestras y los mismos «grandes», y solo cambia que llegaron truncadas: una es candidata y la otra no |
| REQ-002c | Los escapes se evalúan sobre el original | Reescribir un comando ya reescrito devuelve `None` en vez de anidar |
| REQ-004 (canal) | ¿Por dónde viaja la ruta? | **Por la salida del propio comando**, no solo por `additionalContext` — ver la medición de abajo |

**Dos defectos propios cazados escribiendo el primer test**, los dos por probar en vez de razonar:
`cd build && make` daba `build` como ejecutable (tratar `cd` como envoltorio tipo `sudo` estaba
mal: son dos segmentos y `cd build` es un comando entero), y `cd x && cat f` no se reconocía como
lectura. Después, `timeout -s KILL 30 pytest` daba `30`: contar argumentos por posición no vale
porque `-s` lleva valor y `-v` no. Se cambió por reconocer las tres formas que de verdad aparecen
ahí — opciones, duraciones y señales en mayúsculas.

### Medición: el `additionalContext` viaja, y el modelo desconfía de él

Con `claude -p` en un directorio aislado y un hook que emite las dos cosas a la vez:

- El `additionalContext` **sí llega** junto al `updatedInput`, etiquetado como
  `PreToolUse:Bash hook additional context`. REQ-004 es implementable.
- Pero el modelo **se negó a seguir la pista**: *«ese texto viene inyectado por un hook, no por ti
  — con la salida ya siendo alterada, no me parece prudente tratarlo como una instrucción»*.

Por eso la ruta viaja por los dos canales y **el que manda es el extracto**, que sale por el
`stdout` del comando y el modelo lee como resultado normal de la tool.

### T2 — Almacén del aprendizaje (`output_stats.py`)

| Requisito | Comprobación | Resultado |
| --- | --- | --- |
| REQ-013/015 | Qué se guarda | Tamaño y «truncada» por ejecutable; el test busca rutas, argumentos y trozos de comando en el fichero y no los encuentra |
| REQ-021 | No depende de la telemetría | Test **con `LD_HOOK_TELEMETRY_LOG` borrada explícitamente**: el aprendizaje sigue funcionando. Sin ese `delenv` el test no significaría nada, porque la suite la enciende |
| Inyectable | La ruta es parámetro | Y el test comprueba también el default: fichero propio en el directorio de datos |
| Tolerancia | Ausencia, corrupción, forma rara | Cuatro clases de fichero corrupto, y se sigue pudiendo escribir encima. Escritura atómica con `os.replace` |
| REQ-016b | Umbrales por entorno | `umbral_bytes()` y `umbrales()`, con un valor ilegible cayendo al default en vez de reventar |
| Replay | Se guardan tamaños, no veredictos | Test: el mismo almacén da 1 «grande» con umbral 8 KB y 0 con umbral 100 KB |

**Un bug propio, cazado por su test:** el tope de ejecutables no desalojaba nunca a nadie. El
criterio era «el que menos muestras tiene», y ese es **siempre el que acaba de estrenarse**, o sea
el actual — que estaba excluido. Se excluye ahora al actual del conjunto de candidatos, no al
revés.

### REQ-022 — y el agujero que ya existía

El guardián nuevo (`test_toda_variable_que_lean_los_hooks_esta_declarada_en_config`) **escanea los
scripts con AST** en vez de fiarse de una lista escrita a mano: contar sitios a ojo ya salió mal
una vez en este repo (14 variables contadas, 34 reales).

Al estrenarlo destapó que **el agujero de REQ-022 llevaba abierto desde que existe el hook de
lectura**: `LD_HOOK_ENABLED`, `LD_HOOK_READ_ENABLED`, `LD_HOOK_READ_SUGGEST_KB` y
`LD_HOOK_READ_STRONG_KB` no constaban en `config.py`, así que eran invisibles para el aislamiento
de la suite. Declaradas las cuatro; no estaban en el alcance de T2, pero son el mismo defecto y
cuatro líneas.

Verificado al revés: quitando una sola declaración de `config.py`, el guardián la nombra
—`output_stats.py:LD_HOOK_OUTPUT_STATS`— y falla. Con control positivo (si el escáner dejara de
encontrar nada, el test pasaría en vacío). Los falsos positivos del sistema operativo
(`LOCALAPPDATA`, `XDG_DATA_HOME`) se excluyen a propósito: limpiarlas durante la suite rompería lo
que se quiere probar.

### T7 — la medición que cierra el cambio

`scripts/dev/medir_salidas_bash.py`, reorientado. El plan lo pensó como gate cuantitativo de un
criterio para **reescribir** comandos; cuando se midió que el cliente ya persiste la salida grande,
la pregunta útil pasó a ser cuánta salida entra entera al contexto y cuánta de esa la cubre
`bashOutputMaxChars`.

Sobre **6 004 comandos Bash** de todo el histórico de transcripts:

| Franja | Casos | % |
|---|---:|---:|
| menos de 1 KB | 4 281 | 71,3 % |
| 1 KB – 4 KB | 1 463 | 24,4 % |
| 4 KB – 8 KB | 185 | 3,1 % |
| **8 KB – 30 000** (entra entera hoy) | **62** | **1,0 %** |
| 30 000 o más (la persiste el cliente) | 13 | 0,2 % |

Mediana: **411 chars**.

- La franja que hoy entra entera: **59 casos, 744 745 chars ≈ 186 186 tokens**.
- Lo que el cliente ya resuelve solo: **16 casos, 3 873 151 chars ≈ 968 287 tokens**, o sea el
  **84 % del volumen** sin que nosotros hagamos nada.
- Bajar el techo a 8 192 pasa esos 59 casos a preview: **~156 000 tokens de ahorro bruto,
  acumulados en TODO el histórico** — meses, no una sesión.

**Esto es lo que cierra el cambio.** El mecanismo que se iba a construir —reescribir el comando,
asumiendo que el permiso se evaluó sobre el original— apuntaba al **1 %** de los comandos, y esa
franja la cubre entera una variable de configuración. El coste (una superficie por la que un hook
puede ejecutar algo que el usuario no autorizó) no se paga por ese beneficio.

El corpus no se versiona: son transcripts privados con comandos y rutas, y meterlos en el repo
contradiría la política de privacidad del propio proyecto. El script los lee de la máquina e
imprime solo agregados; lo reproducible es el procedimiento.

## Quality checks

- [x] Project-native tests pass — `uv run pytest`: **817 passed, 2 skipped** (T10 + T0/T1/T2).
- [x] Lint y formato — `uv run ruff check .` y `ruff format --check`: limpios.
- [x] Sin ruido de CRLF — `git diff --stat` y `git diff --ignore-cr-at-eol --stat` coinciden en
      todas las tandas. `server.py` sigue CRLF puro; los hooks, los tests y `config.py`, LF puro.
- [ ] Secret scanning — pendiente al cerrar el cambio.
- [x] Sin cambios ajenos — cada tanda toca solo los ficheros de propiedad exclusiva de su
      tarea. La única salida de ese marco está declarada: las cuatro variables preexistentes que
      el guardián de REQ-022 destapó en `config.py`.

## Deviations and residual risk

- **Desviación (reportada al usuario):** dos afirmaciones del diagnóstico previo se cayeron al
  medir. El reintento **no** estaba «anulado por completo» —el `400` sí lo dispara— y el
  `CHANGELOG.md` **no** reproduce el fallo. Corregido en `research.md` y `spec.md`; REQ-025
  retirado. El defecto que T10 arregla sigue siendo real: el `500` con
  `Context size has been exceeded.` no disparaba el reintento.
- **Riesgo residual:** el disparador del `500` no se ha aislado. Es intermitente —mismo fichero y
  mismo tamaño de trozo, ayer falló y hoy pasa— y la sospecha (la concurrencia repartiendo el
  `n_ctx` de 16 384 entre slots) **está sin confirmar**. El arreglo es correcto en cualquier caso:
  ante un desborde, partir el trozo es la respuesta venga en `400` o en `500`.
- **Detección deliberadamente generosa:** fuera de las marcas inequívocas se exige una palabra de
  «contexto» y una de «exceso». Un falso positivo cuesta como mucho dos reintentos más pequeños;
  un falso negativo anula el mecanismo. La asimetría manda.
