# Implementation plan: update detecta el CLI instalado como uv tool y dice como actualizarlo

## Approach

`update.py` ya tiene la mitad del trabajo hecho: `editable_origin()` (línea 359) detecta la
instalación editable por PEP 610. Lo que falta es la otra mitad —`uv tool`— y **juntar las dos en
una sola respuesta**, porque hoy hay dos consumidores que preguntan lo mismo por separado: el
mensaje de `update` y el `fix_hint` del check `cli.published`, que asume `uv tool upgrade` para
todo lo que no sea editable.

Se añade `install_kind()` junto a `editable_origin()`, en la misma sección del módulo, devolviendo
uno de tres valores. Es una función, no una jerarquía ni un registro: son tres casos, y `checks`
ya demostró en este repo que una lista estática envejece mejor que un framework.

La detección de `uv tool` es una **lectura de fichero local**: `uv-receipt.toml` en `sys.prefix`.
Nada de ejecutar `uv` —que puede no estar en el PATH del proceso—, nada de `UV_TOOL_DIR` ni de
rutas por sistema operativo.

Y el mensaje se construye donde ya vive esa clase de salida: junto a `version_lines`, la función
que el change anterior extrajo por el mismo motivo (probar una línea de texto no debería obligar a
montar el HOME, el daemon y el runner).

## Ordered tasks

### 1. `install_kind()`

- **Ficheros:** `src/local_delegate/update.py`
- **Requisitos:** REQ-001..REQ-004
- **Qué:** constantes `EDITABLE`, `UV_TOOL`, `OTHER`; función que devuelve una de las tres:
  - **editable** si `editable_origin()` da ruta —**gana**, porque es lo que gobierna de dónde sale
    el código—;
  - **`uv tool`** si `Path(sys.prefix)/"uv-receipt.toml"` existe **y** nombra nuestro paquete;
  - **`OTHER`** en cualquier otro caso, incluidos todos los fallos.
- **Cuidados:** el nombre del paquete se busca en el texto del receipt sin parsear TOML —basta
  `PACKAGE in texto`—; añadir `tomllib` sería precisión que nadie necesita para responder «¿es
  nuestro?». `try/except` amplio, porque REQ-003 dice que no puede lanzar.
- **Verificación:** tests con `sys.prefix` doblado y el receipt escrito en un `tmp_path`.
- **Rollback:** función nueva y aislada.

### 2. El mensaje de `update`

- **Ficheros:** `src/local_delegate/update.py`
- **Requisitos:** REQ-006..REQ-011
- **Qué:** función que devuelve las líneas del aviso —lista vacía si no aplica— y su llamada en
  `run_update`, junto al bloque de «Instalación EDITABLE» que ya existe. Solo aparece si hay
  versión publicada **más nueva** que la instalada y `install_kind()` es `uv tool`.
- **Cuidado:** la comparación reusa `checks._compare_versions`, igual que `version_lines`.
- **Verificación:** tests de los cuatro casos + ejecución real.

### 3. El `fix_hint` del check, sobre la misma función

- **Ficheros:** `src/local_delegate/checks.py` (`_upgrade_hint`, del change anterior)
- **Requisitos:** REQ-005
- **Qué:** hoy llama a `editable_origin()` y, si no hay, devuelve `UPGRADE_HINT` — o sea, **asume
  `uv tool` para todo lo que no sea editable**, incluido `pip`. Pasa a consumir `install_kind()` y
  a dar un texto genérico cuando no reconoce el modo.
- **Verificación:** tests de los tres modos.

### 4. Tests

- **Ficheros:** `tests/test_update.py`, `tests/test_checks.py`
- **Requisitos:** todos
- **Qué:**
  - `install_kind()`: editable, `uv tool`, receipt de **otro** paquete, receipt ilegible, sin
    receipt, y **editable gana** cuando se dan los dos;
  - el mensaje: con versión nueva y `uv tool` → aparece con el comando y la versión instalada; al
    día → **no aparece**; editable → no aparece; sin versión publicada → no aparece;
  - REQ-009: el plan de acciones y el exit code no cambian, comparando las salidas **línea a
    línea** quitando las exactas del aviso (mismo patrón que el change anterior);
  - REQ-011: `.encode("cp1252")`;
  - `_upgrade_hint` en los tres modos.
- **Verificación al revés:** quitada la rama de `uv tool`, deben fallar los tests de AC-1 y el de
  `_upgrade_hint`.

### 5. CHANGELOG y wiki

- **Ficheros:** `CHANGELOG.md`, `docs/wiki/Remote-backend.md`
- **Requisitos:** REQ-012, REQ-013
- **Qué:** ya localizado (hallazgo R-4): `Remote-backend.md:78-83` describe qué hace `update` —
  «revisa el estado real de la máquina…, actualiza el pin…, termina dejando el daemon arriba»— y
  es exactamente donde falta decir **lo que no hace**. `Daemon.md:72` solo lo menciona de pasada
  para los nombres de servicio: no aplica.
- **Cuidado:** CRLF en el CHANGELOG.

### 6. CI local y ejecución real

- **Requisitos:** todos
- **Qué:** los cuatro pasos del CI; `update --dry-run --home <sim>` desde el repo editable (que
  debe seguir enseñando el bloque EDITABLE y **no** el de `uv tool`); y —el que de verdad
  importa— **ejecutar el CLI instalado como `uv tool`**, único contexto donde `sys.prefix` apunta
  al entorno con receipt.

## Test strategy

- **Unit:** `install_kind()` con `sys.prefix` doblado a un `tmp_path`, y el mensaje sobre la
  función aislada. Sin subprocesos, sin red, sin tocar `~/.local/bin`.
- **Integration:** `run_update` con `out` doblado, comprobando que el plan no cambia.
- **End-to-end:** las dos instalaciones reales de esta máquina, que es un banco de pruebas
  perfecto porque conviven —la de `uv tool` y la editable— y `sys.prefix` las distingue.
- **Verificación al revés:** obligatoria, arriba.
- **Seguridad:** el cambio **no ejecuta** ningún upgrade, que es justo el punto. Sin subprocesos
  nuevos, sin red, sin dependencias.

## Migration and compatibility

- **Cambia texto de salida y un `fix_hint`.** Ni flags, ni exit codes, ni plan de acciones.
- **El `fix_hint` se vuelve más genérico** para instalaciones que no sean editable ni `uv tool`
  (hoy les dice `uv tool upgrade` a todas). Es una corrección, no una regresión: mandar a quien
  instaló con `pip` a correr `uv tool upgrade` es un consejo que falla.

## Revisión adversarial del plan

Cuatro hallazgos; el primero **bloqueante**, todos incorporados arriba.

- **R-1 (BLOQUEANTE) — `sys.prefix` tiene que leerse en tiempo de llamada, no al importar.** Si se
  escribe `_RECEIPT = Path(sys.prefix) / "uv-receipt.toml"` como constante del módulo, el
  `monkeypatch` de los tests **no llega nunca** y estarían probando la máquina en la que corren en
  vez del código. Es el mismo error que ya se pagó en el change anterior con el default del
  dataclass, que capturaba la referencia al definirse. La función lee `sys.prefix` **dentro**.
- **R-2 — el camino nuevo no se recorre desde `uv run`.** Que es como se prueba todo aquí: ahí
  `sys.prefix` apunta al `.venv` del repo, así que una verificación «real» hecha con `uv run`
  daría por buena una ejecución que **nunca tocó el código nuevo**. Hay que ejecutar el CLI de
  `uv tool`. Explícito en la tarea 6.
- **R-3 — `PACKAGE in texto` casa por subcadena.** Con `local-delegate-mcp` es distintivo de
  sobra, pero queda anotado: con un nombre corto habría falsos positivos.
- **R-4 — no suponer qué documenta la wiki.** Buscado antes de escribir el plan: `Remote-backend.md`
  y `Daemon.md` son las dos únicas páginas que nombran `local-delegate update`, y solo la primera
  describe su comportamiento. El change anterior enseñó a hacer esto antes y no después.

## Plan review

- [x] Cada requisito mapea a una tarea y a una verificación.
- [x] Sin operaciones destructivas: el cambio **evita** la única operación destructiva posible
      —ejecutar el upgrade—, que es su razón de ser.
- [x] Sin dependencias ni configuración nuevas.
- [x] Sin trabajo ajeno.
