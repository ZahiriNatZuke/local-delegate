# Implementation plan: Check de doctor sobre los clientes MCP observados

## Approach

Una entrada más en la tupla estática de `checks.CHECKS`, con la misma forma que las catorce que ya
hay. Tres decisiones de diseño, cada una con su alternativa descartada:

**1. La fuente es `clients.jsonl`, leído a través de un colaborador inyectable.**
Descartado `/api/status`: solo expone la memoria del proceso del daemon y **no ve a los clientes
stdio**, que son Claude Code y Codex (research R2). Además obligaría a `doctor` a salir por red para
un dato que está en disco.

**2. Dónde vive «cómo se llega al registro»: en `clients.py`.**
`clients.py` ya sabe el nombre del fichero y su directorio (`_ruta_registro`). Reconstruir esa ruta
desde `checks.py` crearía **dos fuentes para el mismo dato**, que es la clase de defecto que este
repo ya atacó tres veces. Así que `_ruta_registro` pasa a **`ruta_registro`** (público) y `checks`
la usa. Es el único cambio en `clients.py`, y no toca la escritura.

Descartado poner la lectura completa dentro de `clients.py`: tendría que reimplementar el manejo
tolerante de errores que `checks.read_text` ya hace y tiene probado, y no puede importarlo sin
arriesgar un ciclo (`checks` → `clients` → `checks`).

**3. La agregación «un cliente por nombre, el más reciente» vive en `checks.py`.**
Es el criterio de **qué enseña el check**, no una propiedad del registro. Nadie más lo necesita: el
dashboard usa `snapshot()`, que es otra cosa (memoria del proceso vivo).

El estado es `ok` en cuanto hay una observación válida y `unknown` cuando no hay ninguna o no se
pudo leer. **Nunca `warn` ni `missing`**, con el razonamiento escrito en research R7: un cliente sin
`elicitation` no es una desviación de la configuración esperada, subiría el exit code de una máquina
sana, y no existe `fix_hint` honesto que ofrecer.

## Ordered tasks

1. **Exponer la ruta del registro**
   - Files: `src/local_delegate/clients.py`
   - Renombrar `_ruta_registro` → `ruta_registro` y actualizar su única llamada interna
     (`registrar`, línea 148). Añadir una línea al docstring de la función diciendo que ahora
     también la consume el registro de comprobaciones.
   - Requirements covered: REQ-002
   - Verification: los tests de `test_clients.py` siguen verdes (ninguno referencia el nombre viejo
     — comprobado por grep: solo hay 2 ocurrencias, ambas en `clients.py`).
   - Rollback: revertir el rename; no hay persistencia implicada.

2. **Colaborador `clients_seen` en `checks.Context`**
   - Files: `src/local_delegate/checks.py`
   - `_default_clients_seen() -> tuple[list[dict], str | None]`: usa `checks.read_text` sobre
     `clients.ruta_registro()`; devuelve `([], motivo)` si no se pudo leer, `([], None)` si no
     existe, y la lista de objetos JSON válidos en otro caso. Las líneas que no son JSON, o que no
     son objeto, **se saltan**.
   - Añadir el campo al `Context`, **al final y con default**, para no romper las llamadas
     existentes (mismo criterio que `latest_release`).
   - Import de `clients` a nivel superior: `clients` solo importa `config`, así que no hay ciclo ni
     peso extra (a diferencia de `daemon`/`doctor`, que sí lo tienen y por eso van diferidos).
   - Requirements covered: REQ-003, REQ-006, REQ-009
   - Verification: tests unitarios del default con fichero ausente, ilegible, corrupto y válido.
   - Rollback: quitar el campo; su default lo hace aditivo.

3. **El probe `_probe_clients_observed`**
   - Files: `src/local_delegate/checks.py`
   - Sin observaciones y sin motivo → `unknown` («todavía no ha hablado ningún cliente MCP»).
     Con motivo → `unknown` + motivo (que ya trae la ruta, porque `read_text` la incluye).
     Con observaciones → `ok` + `detail` agregado.
   - Agregación: agrupar por `client` (los `None` bajo `"(sin identificar)"`), quedarse con el de
     `ts` **más reciente parseando la fecha**, no comparando texto; ordenar la salida por nombre
     para que sea estable.
   - Formato del `detail`, compacto y todo en cp1252:
     `claude-code 2.1.220 [2025-11-25] elicitation; codex-mcp-client 0.146.0 [2025-06-18] elicitation`
     y `sin elicitation` para el que no la declare. Versión ausente → se omite; protocolo ausente →
     `[?]`.
   - `fix_hint` vacío (por defecto), así que `_print_group` no imprime línea de arreglo.
   - Requirements covered: REQ-004, REQ-005, REQ-007, REQ-008, REQ-010, REQ-011
   - Verification: un test por escenario de la spec.
   - Rollback: quitar la función.

4. **Registrar el check y actualizar las frases de tamaño**
   - Files: `src/local_delegate/checks.py`
   - `Check("client.observed", "entorno", "clientes MCP observados", _probe_clients_observed)`
     justo **después** de `client.presence`.
   - Cambiar «catorce» → «quince» en las cinco afirmaciones, y «trece» → «catorce» en la de
     «ver los otros …».
   - Requirements covered: REQ-001, REQ-012
   - Verification: `test_el_docstring_dice_cuantos_checks_hay_de_verdad` (tras la tarea 6).
   - Rollback: quitar la entrada y revertir el texto.

5. **`update.py`: dejar claro que no se repara**
   - Files: `src/local_delegate/update.py`
   - Añadir `client.observed` al comentario de los checks que no se reparan escribiendo en el HOME.
     `REPAIRS` **no** se toca.
   - Requirements covered: REQ-013
   - Verification: test que asevera que ningún `Repair` apunta a `client.observed`.
   - Rollback: revertir el comentario.

6. **Tests**
   - Files: `tests/test_checks.py`, `tests/test_update.py`
   - `_NUMERO` gana `15: "quince"`.
   - Tests nuevos, uno por escenario (ver estrategia abajo).
   - Requirements covered: todos
   - Verification: `uv run pytest -q`
   - Rollback: n/a.

7. **Documentación**
   - Files: `docs/wiki/Integration-install.md`, `CHANGELOG.md`
   - Línea 133: «las catorce piezas» → «las quince piezas».
   - Fila nueva en la tabla de comprobaciones, tras `Entorno | clientes`:
     `| Entorno | clientes MCP observados | con qué clientes ha hablado local-delegate (versión, protocolo negociado y si pueden responder preguntas), leído de `clients.jsonl` |`
   - Entrada en `Unreleased` del `CHANGELOG.md` — **editar con la herramienta de edición, nunca con
     here-strings**, porque el fichero es CRLF.
   - Requirements covered: REQ-014
   - Rollback: revertir el diff.

## Test strategy

- **Unit** (`tests/test_checks.py`), con el colaborador `clients_seen` doblado:
  - sin observaciones → `unknown`, y el detail dice que no se ha visto ninguno;
  - motivo de lectura → `unknown` y el motivo aparece en el detail;
  - un cliente con `elicitation` → `ok` y lo nombra;
  - dos clientes, uno sin `elicitation` → sigue `ok` y los distingue;
  - veinte líneas repetidas + una versión anterior → aparece **una vez**, con la versión más
    reciente (este es el test que muerde el riesgo real medido en R3);
  - observación sin `client` → sale como «sin identificar», no se descarta;
  - `fix_hint` vacío;
  - el detail solo contiene caracteres codificables en cp1252.
- **Unit del default** (sin doblar): fichero ausente → `([], None)`; fichero con una línea válida y
  otra truncada → devuelve solo la válida, sin lanzar; directorio ilegible → motivo.
- **Integration**: `checks.run_all` devuelve 15 resultados; `test_no_probe_writes_anything` sigue
  verde con el check dentro (es el que garantiza REQ-004);
  `test_el_docstring_dice_cuantos_checks_hay_de_verdad` verde por decir la verdad.
- **End-to-end manual**: `local-delegate doctor` en esta máquina (sale `[ -- ]`, porque no hay
  registro) y con `LOCAL_DELEGATE_LOG_DIR` apuntando al registro real medido en R4 (sale `[ OK ]`
  con `claude-code 2.1.220`). Comprobar el exit code en los dos casos.
- **Verificar los tests al revés**: introducir el defecto en cada rama y comprobar que el test falla
  **y por la razón que dice**. En concreto, para el test de deduplicación hay que confirmar que
  falla por contar dos veces al cliente y no por otra aserción de la misma función.
- **Security**: sin dependencias nuevas, sin red, sin escritura, sin secretos. El check muestra
  nombre/versión/protocolo/capabilities, que ya están en el registro; no toca contenidos.

## Migration and compatibility

- **Aditivo**: no cambia el formato de `clients.jsonl`, ni `/api/status`, ni el contrato de ningún
  check existente. Un registro escrito por una versión anterior se lee igual.
- **Exit code**: no cambia para ninguna máquina, porque el check nunca devuelve `warn` ni `missing`.
- **`doctor --home`**: sigue leyendo el `LOG_DIR` real, como ya hacen los checks de servicio.
  Documentado en la spec para que no se confunda con el defecto del change C.
- **Rollout**: viaja en `Unreleased`, junto con `clients.py`, que aún no está publicado. Hasta que se
  publique, en cualquier máquina el check dirá `[ -- ]` — que es correcto y es el caso de hoy.

## Revisión adversarial del plan

Cuatro defectos encontrados atacando el propio plan **antes** de implementar. Los cuatro son de la
misma familia: el plan daba por buenos datos que vienen de fuera del proceso.

**A1 — `ts` ausente o no parseable tumbaría el criterio de «más reciente».**
El plan decía «parseando la fecha, no comparando texto», pero no decía qué pasa si la fecha no se
puede parsear. `datetime.fromisoformat` lanzaría, y aunque `run_all` lo convertiría en `unknown`,
eso **perdería todos los clientes por una sola línea mala** — justo lo contrario de REQ-009.
*Corrección:* la clave de orden devuelve un mínimo cuando el `ts` falta o no parsea; la observación
se conserva y solo pierde la carrera por ser «la más reciente».

**A2 — `caps` podría no ser una lista, y `in` daría un falso positivo silencioso.**
Si `caps` llegara como la cadena `"no-elicitation"`, `"elicitation" in caps` sería **True** por
subcadena: el check diría que un cliente sabe preguntar cuando no. Es exactamente el patrón «pasa
por la razón equivocada» que costó dos tests la sesión anterior.
*Corrección:* comprobar `isinstance(caps, list)` antes de usarlo; si no lo es, tratarlo como sin
capabilities. Con test dedicado.

**A3 — REQ-011 (cp1252) no es garantizable, porque el nombre lo pone el cliente.**
El `detail` incluye `client` y `version`, que son **texto de terceros**. Un cliente con un emoji o
un guion largo en su nombre mataría el doctor en la consola de Windows — el mismo incidente que ya
sufrió este repo con una flecha `→`, pero ahora por un dato que el repo no controla.
*Corrección:* sanear el texto ajeno antes de pintarlo, reemplazando lo no codificable en cp1252.
Con test que mete un nombre con emoji y comprueba que el detail sigue siendo codificable.

**A4 — el default de `clients_seen` haría que los tests existentes leyeran el disco real.**
`make_ctx` no dobla el colaborador nuevo, así que cada `run_all` de la suite tocaría el
`clients.jsonl` de la máquina donde corre. No escribe, así que no rompe
`test_no_probe_writes_anything`, pero hace la suite **dependiente del entorno**: verde en CI (donde
el fichero no existe) y potencialmente distinta en la máquina del desarrollador.
*Corrección:* `make_ctx` dobla `clients_seen` con un valor vacío explícito; los tests del default
lo ejercen aparte, apuntando `config.LOG_DIR` a un `tmp_path`.

Comprobado además que el import de `clients` en `checks` **no crea ciclo**: `clients.py` solo
importa `config` (verificado en el fichero, no supuesto).

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback — no hay ninguna: el cambio es de
      solo lectura y el único rename es interno, con sus dos ocurrencias verificadas por grep.
- [x] Dependencies and configuration changes are explicit — ninguna dependencia nueva.
- [x] The plan does not include unrelated work — la rotación de `clients.jsonl` y la discrepancia
      del docstring de `Check` quedan fuera, declaradas como no-goals.
