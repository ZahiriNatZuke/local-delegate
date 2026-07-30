# Implementation plan: update dice de donde saco la version publicada y como saltarse la cache

## Approach

El cambio es **solo de salida**: ni una petición nueva, ni un flag nuevo, ni una rama de
comportamiento. Se toca el bloque «2. La versión» de `run_update` (`update.py:592-599`) y el
docstring de `latest_version()`.

La decisión de diseño que sostiene el resto: **el aviso se emite por una condición que el comando
ya puede comprobar** —instalada más nueva que la publicada— en vez de intentar adivinar «¿acabas
de publicar?». Esa condición es la firma exacta del caso, no una heurística: cuando publicas la
0.17.0 desde el repo, tu instalación **es** 0.17.0 y PyPI todavía dice 0.16.0.

Se extrae una función pequeña, `_linea_de_version(version, reason, from_user)`, en vez de encadenar
`if` dentro de `run_update`: la lógica tiene cuatro desenlaces y probarla a través del comando
entero obligaría a montar el HOME, el daemon y el runner para aseverar sobre una línea de texto.

Y la comparación sale de `checks._compare_versions`, que ya existe y está probado desde el change
anterior. Segunda implementación = dos verdades que se separan al primer cambio.

## Ordered tasks

### 1. La lógica de los mensajes, aislada

- **Ficheros:** `src/local_delegate/update.py`
- **Requisitos:** REQ-001..REQ-003, REQ-005, REQ-006, REQ-008, REQ-011
- **Qué:** función que, dadas la versión, el motivo y si la pidió el usuario, devuelve la lista de
  líneas a imprimir:
  - pedida por el usuario → «Versión pedida con `--version`: X» (**sin** afirmar que sea la
    última publicada);
  - consultada → «Última versión publicada: X (índice simple de PyPI, que se sirve con caché)»;
  - no consultada → el aviso actual, textualmente;
  - y, **añadido** al caso consultado, cuando `checks._compare_versions(instalada, publicada) > 0`:
    las líneas que dicen que la instalada es más nueva y recuerdan `--version <instalada>`.
- **Cuidados:** nada fuera de cp1252; la versión instalada sale de `checks._installed_version()`,
  que ya devuelve `None` sin reventar.
- **Verificación:** tests unitarios de los cuatro desenlaces + el de desfase.
- **Rollback:** la función es aditiva; `run_update` vuelve a sus tres líneas quitándola.

### 2. Enganchar en `run_update`

- **Ficheros:** `src/local_delegate/update.py`
- **Requisitos:** REQ-004, REQ-007
- **Qué:** sustituir el `if/else` del bloque 2 por el bucle que imprime esas líneas **por `out`**.
  `version` sigue alimentando `plan_pin` exactamente igual — el aviso no toca el plan ni el exit
  code.
- **Verificación:** test de que con desfase el plan de acciones y el código de salida son los
  mismos que sin él.

### 3. El dato medido, escrito donde se decide

- **Ficheros:** `src/local_delegate/update.py` (docstring de `latest_version`)
- **Requisitos:** REQ-009
- **Qué:** añadir al porqué que ya está escrito la medición del 2026-07-30: índice simple
  `max-age=600` frente a JSON `max-age=900`, y que por eso cambiar de endpoint **empeoraría**.
- **Verificación:** revisión del diff.

### 4. Tests

- **Ficheros:** `tests/test_update.py`
- **Requisitos:** todos
- **Qué:**
  - AC-1: instalada `0.17.0`, publicada `0.16.0` → las líneas nombran las dos versiones y
    contienen `--version 0.17.0` **literal**, no un placeholder;
  - AC-2: con `--version`, la salida **no** contiene la frase de «última versión publicada»;
  - AC-3: caso normal → la fuente aparece nombrada y **no** aparece el aviso;
  - AC-4: sin red → el mensaje actual, sin aviso de desfase;
  - bordes: versión instalada desconocida y versiones no comparables → sin aviso;
  - REQ-007: con desfase, `plan_pin` produce las mismas acciones y `run_update` el mismo exit code
    que sin desfase;
  - REQ-011: `.encode("cp1252")` sobre las líneas de todos los desenlaces.
- **Verificación al revés:** quitada la rama del desfase, el test de AC-1 debe **fallar**.

### 5. CHANGELOG

- **Ficheros:** `CHANGELOG.md`
- **Requisitos:** REQ-010
- **Cuidado:** CRLF; herramienta de edición directa, nunca here-string de PowerShell.

### 6. CI local y ejecución real

- **Requisitos:** todos
- **Qué:** los cuatro pasos del CI y `local-delegate update --dry-run --home <sim>` de verdad,
  más una ejecución con la publicada forzada para ver el aviso en pantalla.

## Test strategy

- **Unit:** los cuatro desenlaces de la línea de versión y los bordes, sobre la función aislada.
- **Integration:** `run_update` con `out` doblado, comprobando que las líneas salen por ahí y que
  el plan no cambia.
- **End-to-end o manual:** `update --dry-run` real contra un HOME simulado (que además no toca
  ningún servicio, por la regla 3 del módulo).
- **Verificación al revés:** quitar la rama del desfase debe romper AC-1.
- **Seguridad:** sin peticiones nuevas, sin dependencias, sin credenciales. Solo texto.

## Migration and compatibility

- **Cambia texto de salida, nada más.** No hay flags nuevos ni exit codes distintos.
- **Riesgo de romper tests ajenos:** algún test existente puede aseverar sobre la cadena
  `"Última versión publicada"`. Hay que buscarla antes de cambiarla, no después.

## Revisión adversarial del plan

Tres hallazgos; ninguno bloqueante, los tres incorporados arriba.

- **P-1 — el aviso podría dispararse en una instalación editable normal.** En desarrollo, el repo
  suele ir por delante de PyPI *todo el tiempo* (bump ya hecho, release aún no), así que el aviso
  saldría en cada `update` de la máquina de desarrollo. **Se acepta**: el mensaje es informativo,
  no un error, y en esa máquina la afirmación es **cierta** —la instalada es más nueva que la
  publicada—. Además `update` ya imprime en ese caso el bloque de «Instalación EDITABLE», así que
  el usuario tiene las dos piezas juntas. Lo que **no** se hará es suprimir el aviso cuando la
  instalación sea editable: eso lo apagaría justo en la máquina desde la que se publica, que es
  donde el síntoma ocurre.
- **P-2 — «recuerda `--version`» tiene que llevar la versión ya sustituida.** Un mensaje con
  `X.Y.Z` literal obliga al usuario a traducirlo, y en ese momento (acaba de publicar, algo no
  cuadra) es exactamente cuando menos ganas hay. El test lo exige explícitamente.
- **P-3 — cuidado con romper tests existentes por la cadena del mensaje.** Buscar
  `"Última versión publicada"` en `tests/` **antes** de tocarla; si algún test la asevera, se
  actualiza en el mismo cambio y no se descubre en el CI.

## Plan review

- [x] Cada requisito mapea a una tarea y a una verificación.
- [x] Sin operaciones destructivas: el cambio es de salida de texto. `update` sigue planificando y
      escribiendo exactamente igual, y hay un test que lo fija (REQ-007).
- [x] Sin dependencias ni configuración nuevas.
- [x] Sin trabajo ajeno: no se toca el endpoint, ni `doctor`, ni el pin.
