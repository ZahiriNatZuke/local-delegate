# Specification: Tools de texto: rechazo de binarios y rutas exactas en lint_summary

## Summary

Arreglos R3 y R4 de `.sdd/changes/text-tools-common-cause/research.md`.

- **R3 (#693):** una tool de texto que recibe por `path` un fichero binario (imagen, PDF, archivo
  comprimido, ejecutable) lo rechaza con un error claro **antes** de llamar al modelo; para una
  imagen el error remite a `local_describe_image`. Un solo punto de control, el lector común
  `_read_input`, vale para summarize, extract, lint_summary, commit_msg, translate y explain_code.
- **R4 (#688, #690):** `local_lint_summary` trata las rutas del log de forma exacta: la ruta
  absoluta y la relativa del mismo fichero cuentan como un fichero, una URL no es un fichero, los
  ficheros que pytest solo nombra en su línea de progreso en verde no entran en el inventario, y
  el aviso de ficheros inventados compara la ruta completa (y las carpetas que nombra el resumen)
  con el log, sin aceptar por coincidencia del nombre base cuando el resumen da carpetas.

## Requirements

- **REQ-001** — Un fichero con `path` cuyo contenido empieza por una firma de imagen conocida
  (PNG, JPEG, GIF, WebP) da `InputError` con un mensaje que nombra el formato y remite a
  `local_describe_image`, y el backend no recibe ninguna llamada.
  - Request: "rechazar entradas binarias en las tools de texto con `path` (… firma de fichero conocida …) ANTES de llamar al modelo, con mensaje que remita a `local_describe_image` para imágenes"
  - Verify: test `tests/test_binary_input.py` (PNG y JPEG reales mínimos, 0 llamadas al backend)
- **REQ-002** — Un fichero con firma de PDF, ZIP, gzip o 7z, con más del 1 % de bytes nulos
  (salvo UTF-16 con BOM) o con más del 10 % de bytes de control C0 (sin contar tabulador, saltos
  de línea, avance de página ni ESC, y al menos 8) en sus primeros 64 KiB da `InputError` con el
  motivo, sin llamar al backend. Un byte nulo suelto en un log largo, o uno de control en un
  fichero diminuto, no lo hacen binario (revisión del PR #709).
  - Request: "rechazar entradas binarias … (bytes nulos, firma de fichero conocida, proporción de bytes de control) ANTES de llamar al modelo"
  - Verify: test `tests/test_binary_input.py`
- **REQ-003** — El control vive en un único punto (`_read_input`) y lo heredan todas las tools de
  texto que leen `path`.
  - Request: "Un solo punto de control común a todas las tools de texto, no uno por tool."
  - Verify: test parametrizado sobre las seis tools en `tests/test_binary_input.py`
- **REQ-004** — Los textos que hoy se leen siguen leyéndose igual: UTF-8 con acentos, UTF-8 con
  BOM, UTF-16 con BOM, Latin-1/cp1252, un log con colores ANSI y un log con algún byte de control
  suelto. Los tests de #672 quedan intactos.
  - Request: "fichero UTF-8 con acentos que NO debe rechazarse, UTF-16 con BOM"
  - Verify: test `tests/test_binary_input.py` y suite `tests/test_input_encoding.py` sin cambios
- **REQ-005** — En el inventario de ficheros de `local_lint_summary` la ruta absoluta y la
  relativa del mismo fichero (la relativa es sufijo de la absoluta en un límite de carpeta) son
  una sola entrada, con la ruta relativa y la suma de menciones.
  - Request: "unificar ruta absoluta y relativa del mismo fichero (no contar dos veces)"
  - Verify: test `tests/test_lint_exact_paths.py` (salida de pytest con la forma de #688)
- **REQ-006** — Lo que está dentro de una URL (`http://`, `https://`, `www.`) no es un fichero:
  no entra en el inventario, ni en «sin mencionar», ni en «inventados».
  - Request: "descartar URLs como fichero"
  - Verify: test `tests/test_lint_exact_paths.py`
- **REQ-007** — En un log de pytest, un fichero que solo aparece en líneas de progreso sin fallos
  (`tests/test_a.py ....  [ 10%]`, con colores ANSI, `-v` con PASSED/SKIPPED/XFAIL/XPASS y
  `-v -n N` con el prefijo `[gw0] [ 10%]`) no entra en el inventario que se le da al modelo ni en «sin
  mencionar».
  - Request: "derived: #688 espera «sin listar los ficheros que no tienen nada»; research.md R4 lo incluye"
  - Verify: test `tests/test_lint_exact_paths.py`
- **REQ-008** — El aviso de ficheros inventados compara la ruta completa que da el resumen,
  cuando tiene carpetas, con las rutas del log en un límite de carpeta, y comprueba también cada
  carpeta que el resumen nombra sola (`projects/knowledge/`): si el log no la tiene, sale en el
  aviso. Un nombre base sin carpetas se sigue aceptando por nombre base.
  - Request: "validar la ruta completa y sus carpetas contra la entrada (nada de aceptar por coincidencia de nombre)"
  - Verify: test `tests/test_lint_exact_paths.py` (forma de #690) y tests de #525 intactos
- **REQ-010** — Con un log de pytest sin fallos, si el resumen da una entrada (línea de primer
  nivel que empieza por el fichero, como las lee #641) a un fichero que el log solo nombra en
  progreso sin fallos, el programa añade un `[local-delegate warning: …]` con esos ficheros y los
  que el log sí reporta. Un fichero citado dentro de una frase no es una entrada; con fallos en el
  log calla (ya avisa #641); en un log que no es de pytest no actúa.
  - Request: "control por programa en lint_summary: con salida de pytest, los ficheros sin fallo según el propio log … no pueden aparecer como «con errores»; se quitan o se avisa, por programa"
  - Verify: test `tests/test_lint_exact_paths.py` (`test_the_tool_warns_of_entries_for_clean_files`, rojo sin el arreglo; controles sin aviso)
- **REQ-009** — CHANGELOG en «Sin publicar» con los dos arreglos; mensajes nuevos en `es` y `en`.
  - Request: "CHANGELOG en «Sin publicar», docs si cambia algo visible"
  - Verify: review del diff y test de catálogos i18n existente

## Acceptance scenarios

### Scenario: un JPEG pasado por error a `local_extract`

- **Given** una captura `.jpg` real
- **When** se llama `local_extract(path=…, fields=["campo"])`
- **Then** sale un error con «es una imagen (JPEG)… usa local_describe_image», sin ninguna
  llamada al modelo

### Scenario: salida de pytest con un aviso (#688)

- **Given** un log de pytest en verde con un `DeprecationWarning` cuya cabecera da la ruta
  relativa y cuyo mensaje da la absoluta, varios ficheros en verde y la URL de la doc al pie
- **When** se resume con `local_lint_summary`
- **Then** el inventario nombra un solo fichero (la ruta relativa), sin la URL ni los ficheros en
  verde

### Scenario: carpeta inventada al agrupar (#690)

- **Given** un log con `knowledge/a.md` y `projects/x/b.md`
- **When** el resumen agrupa `a.md` bajo `projects/knowledge/`
- **Then** el aviso de inventados nombra `projects/knowledge/`

## Edge cases and failure behavior

- Fichero vacío: no es binario (se lee como hoy).
- UTF-16 sin BOM: tiene bytes nulos y se rechaza; el mensaje lo dice para que se convierta.
- Un log con un único byte de control suelto, o con un NUL suelto, no se rechaza (umbral por
  proporción); un NUL más allá de los primeros 64 KiB no cuenta.
- Una absoluta cuya relativa no aparece en el log queda como está; si hay varias relativas que
  son sufijo suyo, se une a la más larga.

## Non-functional requirements

- Expresiones lineales (sin retroceso catastrófico), como exige `test_lint_patterns_linear.py`.
- El control usa los bytes que ya se leían; sin lectura extra.

## Non-goals

- No se toca el prompt de sistema de lint: entra en la huella de las celdas de afinidad (T15) y
  cambiarlo invalida esas celdas; un cambio de prompt va en su propio change con prueba en vivo.
- Ni `local_describe_image`, ni el hook de lectura (#469), ni R1, R2, R5, R6 o R7.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
