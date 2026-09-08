# Implementation plan: La salida grande va a fichero, no al contexto

> **Revisión 2** (2026-09-08). La primera versión fue **bloqueada** por la revisión adversarial
> con 6 hallazgos, los seis verificados contra el código. Lo que cambió está resumido al final,
> en «Qué corrigió la revisión».

## Estrategia

El orden lo manda una idea: **la decisión vive en un módulo puro, importable y sin efectos**, y
todo lo demás lo consume. Es lo que permitió al PR #146 medir su arreglo contra 852 lecturas
reales antes de creérselo, y aquí es obligatorio porque el gate de calidad es cuantitativo.

Los hooks quedan como envoltorios delgados. Regla transversal: **el fallo seguro es no tocar el
comando**.

## Tareas

### T0 — `hook_common` aprende a reescribir, y se cierra el doble interruptor

**Ficheros (propiedad exclusiva):**
- `src/local_delegate/resources/hooks/hook_common.py`
- `tests/test_hook_common.py` *(nuevo si no existe)*

**Contenido:**
- Camino de salida nuevo para emitir `updatedInput`, separado de `emit()`, que hoy solo sabe
  producir `additionalContext`.
- **Resolver por escrito la relación entre `LD_HOOK_ENABLED` y el interruptor del registro.** Hoy
  `emit`/`record` cortocircuitan con esa variable; si el hook de reescritura la hereda, tendrá
  dos puertas — que es exactamente el defecto que ya se pagó con `--enable-read-hook`. El
  registro debe seguir siendo la única fuente de si está activo.

**Cierra:** el soporte técnico de REQ-002; la coherencia de REQ-017.

**Por qué existe:** la revisión encontró que este fichero no tenía dueño en ninguna tarea y el
cambio no se puede hacer sin él.

### T1 — Módulo de decisión (puro, importable, sin efectos)

**Ficheros (propiedad exclusiva):**
- `src/local_delegate/resources/hooks/output_policy.py` *(nuevo)*
- `tests/test_output_policy.py` *(nuevo)*

**Contenido:**
- Normalización del ejecutable de una línea de comando (saltar `cd`, `sudo`, `env`, `timeout`,
  asignaciones; mirar tras `|`, `&&`, `;`).
- `debe_saltarse(cmd)` → escapes de REQ-006/007/009.
- `semilla()` → REQ-011, por ecosistema, derivada del estado del arte.
- `es_candidato(cmd, stats)` → REQ-010/012.
- `reescribir(cmd, ruta)` → REQ-002/002b/003/005, **con subshell y no con llaves** (medido: con
  llaves, un `exit` del comando del usuario mata el script y el extracto no se produce), la
  **lista cerrada de utilidades de andamiaje** escrita en el código (REQ-003/003b), y un test que
  falle si el andamiaje se construye con algo que venga del comando del usuario.
- Los escapes se evalúan sobre el comando **original**, nunca sobre uno ya reescrito (REQ-002c).
- **Prefijo `cd` fuera del subshell** (REQ-002b): `cd build && ( make ) > …`. Medido que el cwd
  persiste entre llamadas, así que envolverlo todo cambiaría el comportamiento en 23 de los 42
  casos del corpus. Test propio para el compuesto.

Solo stdlib. **Cierra:** REQ-001…003b, 005…007, 009…012.

### T2 — Almacén del aprendizaje

**Ficheros (propiedad exclusiva):**
- `src/local_delegate/resources/hooks/output_stats.py` *(nuevo)*
- `tests/test_output_stats.py` *(nuevo)*
- `src/local_delegate/config.py` (solo las variables nuevas) y el assert correspondiente en
  `tests/test_aislamiento_entorno.py`

**Contenido:**
- Últimas N muestras por ejecutable (tamaño, truncada). Nunca comando, argumentos ni rutas.
- **Ubicación propia, no colgada de la telemetría** (REQ-021): la telemetría es opt-in y está
  vacía por defecto, así que colgar de ella haría el aprendizaje un no-op en la mayoría de
  máquinas — y los tests no lo verían porque la encienden siempre. Un test debe cubrir el caso
  «telemetría apagada, aprendizaje funcionando».
- **Almacén inyectable**: la ruta es un parámetro, no una constante. Sin esto el replay de T7 no
  puede aislarse.
- Tolerante a ausencia, corrupción y concurrencia.
- Parámetros por entorno: el hook los lee con `os.environ` —no puede importar el paquete—, y los
  **nombres se declaran en `config.py`** con los helpers `_env*` para que el inventario los limpie
  (REQ-022). Sin eso la suite hereda el entorno de quien la corre y el guardián no lo ve, porque
  solo escanea ese módulo.

**Cierra:** REQ-013, 015, 016b, 021, 022.

### T3 — Hook `PostToolUse` de aprendizaje

**Ficheros (propiedad exclusiva):**
- `src/local_delegate/resources/hooks/record_output_size.py` *(nuevo)*
- `tests/test_hook_record_output.py` *(nuevo)*

**Contenido:** toma `tool_response`, detecta truncado (REQ-016), descarta `interrupted`, vacío y
`noOutputExpected`. **No imprime nunca** (REQ-014), con un test que falle si algún camino escribe
en stdout. Contra el **payload real capturado**, que está transcrito en `research.md`.

**Depende de:** T2.

### T4 — Hook `PreToolUse` de reescritura

**Ficheros (propiedad exclusiva):**
- `src/local_delegate/resources/hooks/redirect_large_output.py` *(nuevo)*
- `tests/test_hook_redirect_output.py` *(nuevo)*

**Contenido:**
- Envoltorio delgado sobre T0, T1 y T2.
- `tool_name == "Bash"` (REQ-001), interruptor puesto (REQ-017), y **`permission_mode`
  (REQ-008)** — que es de este hook y no del módulo puro, porque es el único que ve el payload.
- Nombre por `tool_use_id` (REQ-004) y **ubicación fuera del árbol de hooks** (REQ-004b), que
  `install` borra entero en cada pasada.
- Limpieza por antigüedad (REQ-020).
- `try/except` de último recurso.

**Depende de:** T0, T1, T2. **Cierra:** REQ-004, 004b, 008, 020.

### T5 — Registro: `install`, `update`, `uninstall` y el CLI

**Ficheros (propiedad exclusiva):**
- `src/local_delegate/install.py`, `src/local_delegate/cli.py`, `src/local_delegate/update.py`
- `tests/test_install.py`, `tests/test_update.py`, `tests/conftest.py`

**Contenido:**
- Sacar `suggest_lint_summary.py` de `_HOOK_EVENTS` (REQ-017).
- Registrar los hooks nuevos con **el patrón del hook de lectura**: el argumento del registro es
  el interruptor. Obligatorio, no opcional.
- El de aprendizaje instalable por separado (REQ-018).
- **Retirada del script viejo (REQ-019c).** No basta con borrarlo de `resources/hooks/`: la
  limpieza de huérfanos sale de `packaged_hook_names()`, que lista ese directorio, así que un
  script retirado dejaría de ser reconocible y su copia vieja se volvería **inmortal**. Hace
  falta una lista explícita de *nombres retirados* que `_is_ours` y `orphan_hook_scripts`
  consideren junto a los empaquetados. Y `_SCRIPT_NAMES` no puede seguir conteniendo un nombre
  que ya no se empaqueta: `tests/test_install.py` exige que sea subconjunto del paquete, y esa
  guarda se conserva.
- **`update` no apaga los interruptores (REQ-019b).** Hoy construye las opciones de instalación
  con los opt-in en su valor por defecto, así que reparar hooks desregistraría los nuevos en
  silencio. Test explícito: encender, `update`, seguir encendido.
- `conftest.py` construye el HOME simulado desde `_HOOK_EVENTS`; al cambiar esa constante cambia
  el denominador de varios tests de `checks`. Se ajusta a la vez, no después.
- **`uninstall` se lleva los ficheros de salida.** Hoy solo retira `hooks/local-delegate/`, y esos
  ficheros contienen salida real de comandos: la NFR de privacidad aplica.

**Depende de:** T3, T4. **Cierra:** REQ-017, 018, 019, 019b, 019c.

### T6 — Diagnóstico: `doctor`

**Ficheros (propiedad exclusiva):**
- `src/local_delegate/checks.py`, `tests/test_checks.py`

**Contenido:**
- `_probe_hook_files` deriva hoy lo que espera de `_HOOK_EVENTS`; si los hooks nuevos son opt-in
  no estarán ahí y el check **no los miraría**. Hay que decidir de dónde sale la lista esperada
  para un hook opcional: presente en disco siempre, registrado solo si está encendido.
- `_probe_hook_orphans`: que el script retirado no se reporte como ajeno, y que no se confunda la
  raíz de `hooks/` con el subdirectorio bueno — esa confusión ya provocó una vez un aviso en
  bucle.
- Visibilidad del estado y de **qué ha aprendido** la máquina (no-funcional de operabilidad).

**Depende de:** T5.

### T7 — El replay: la evidencia del gate

**Ficheros (propiedad exclusiva):**
- `scripts/dev/replay_output_policy.py` *(nuevo)*
- `tests/test_replay_output_policy.py` *(nuevo)*

**Contenido:**
- Reconstruye `(comando, tamaño, truncada)` de los transcripts, en orden temporal.
- Decide importando los módulos reales de T1/T2, **contra un almacén aislado e inyectado**, nunca
  el de la máquina. Sin esto el replay arrancaría con 21 días ya aprendidos y la cifra sería
  mentira.
- **Tres comprobaciones falsables, no una comparación de resultados** (la comparación honesta vs
  tramposa NO basta: si la honesta leyera el almacén real, su cifra subiría, la tramposa seguiría
  siendo mayor y el contraste daría verde con la medición contaminada):
  1. **Espía sobre la apertura del almacén real**: esa ruta no se abre ni una vez durante el
     replay. Se verifica el mecanismo, no el resultado.
  2. **Hueco numérico declarado** entre la pasada tramposa y la honesta, fijado antes de medir.
  3. **Arranque en frío**: cobertura prácticamente nula en los primeros N comandos, porque ningún
     ejecutable llega aún al mínimo de muestras.
- **Los tres números del gate** —denominador mínimo, suelo de cobertura y hueco tramposa/honesta—
  se fijan **antes de la primera pasada honesta** y viven como constantes en este script. Un
  umbral escrito después de ver el resultado no es un umbral.
- **El corpus no se versiona.** Son transcripts privados con comandos y rutas; meterlos en el
  repo contradice la política de privacidad del propio proyecto. El script los lee de la máquina
  y el informe se guarda en `verification.md`; lo reproducible es el procedimiento, no el dato.

**Depende de:** T1, T2.

### T10 — El reintento del map-reduce deja de estar ciego

**Ficheros (propiedad exclusiva):**
- `src/local_delegate/server.py`: `_DESBORDE_DE_CONTEXTO`, `_es_desborde_de_contexto` **y el
  camino de error de `_chat_map_reduce`** — REQ-026 se construye ahí, no en la detección, y sin
  esta ampliación se quedaría sin dueño viable
- `tests/test_map_reduce.py`

**Contenido:**
- La detección deja de ser tres literales de un proveedor: insensible a mayúsculas y cubriendo
  las formas reales del catálogo, incluida `Context size has been exceeded` (REQ-023/024).
- **Test de regresión con el mensaje real**, que debe fallar contra el código de hoy — si pasa
  con la versión vieja, no está midiendo nada.
- Verificación de extremo a extremo con `CHANGELOG.md` (122 435 chars), que hoy falla (REQ-025).
- Mensaje accionable cuando el reintento se agota de verdad (REQ-026).

**Independiente del resto.** Puede hacerse primero y por separado; no comparte fichero con
ninguna otra tarea.

**Ojo con la verificación:** instrumentar `_run_chat` desde un proceso propio da **401** —la
clave del backend la tiene el daemon—, así que la prueba de extremo a extremo necesita que el
usuario cargue la clave, o hacerse a través del daemon.

**Riesgo de alcance:** si al implementarlo aparece que el reintento tampoco basta —que el
presupuesto en chars hay que recalcular—, eso ya no es este cambio y sale a uno propio. La
frontera es: **reconocer el desborde**, no rediseñar el troceado.

### T8 — Documentación

**Ficheros (propiedad exclusiva):**
- `docs/recipes/claude-code-hooks.md`, `docs/recipes/claude-code-integration.md`
- `docs/wiki/Architecture.md`, `docs/wiki/Savings-and-metrics.md`
- `src/local_delegate/resources/skills/delegacion-local/SKILL.md`, `CHANGELOG.md`

**Contenido:** el mecanismo, el interruptor, el riesgo de permisos documentado, y por qué los
lectores de ficheros están excluidos como objetivo.

### T9 — Verificación en la máquina real

- `install` **end-to-end en Windows**: no se publica sin eso.
- Un comando real con salida **> 30 000 caracteres**: extracto al contexto, fichero entero en
  disco, y `local_lint_summary(path=…)` resumiéndolo.
- Un comando que falla: código de salida preservado, `&&` intacto.
- **Hook roto**: forzar una excepción y un stdout basura, y comprobar que la sesión no se
  degrada. Está declarado como riesgo y no estaba verificado.
- Control negativo: hook apagado, nada cambia.
- Coste añadido por comando, medido.

## Orden y paralelismo

```
T10 (independiente, puede ir primero)
T0 ─┐
T1 ─┼─> T4 ─┬─> T5 ──> T6 ─┐
T2 ─┴─> T3 ─┘              ├─> T8 ──> T9
    └─────> T7 ────────────┘
```

**T4 y T5 se entregan juntas**, no en dos pasos: T4 retira el recurso que `_HOOK_EVENTS` todavía
referencia, así que separarlas deja el repo en rojo entre ambas.

**Dos puntos de control tempranos, los dos antes de gastar T5 y T6:**

1. **T7**: si la precisión no llega al umbral o la cobertura no llega al suelo, se revisa el
   diseño.
2. **La envoltura a través de la tool real**, no solo en el intérprete. Esta comprobación ya se
   adelantó durante la investigación y **encontró un defecto** —las llaves frente al subshell—
   que la medición en el intérprete no podía ver. Se repite en cuanto T1 produzca la primera
   versión de `reescribir()`, con un comando que lleve `exit` dentro.

## Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| La reescritura rompe un comando | Escapes de T1, `try/except`, fallo seguro. Tests con casos reales del corpus |
| `updatedInput` elude el allowlist | REQ-003/003b: lista cerrada de andamiaje, nada derivado del comando del usuario. Test dedicado |
| Retirar un script lo vuelve inmortal | REQ-019c: lista de nombres retirados (T5) |
| `update` apaga los interruptores | REQ-019b, con test de ida y vuelta (T5) |
| El replay se auto-engaña | Almacén inyectado + espía sobre la apertura del almacén real + arranque en frío, con los umbrales fijados antes de medir (T7) |
| El aprendizaje no arranca sin telemetría | REQ-021: almacén propio, con test de «telemetría apagada» (T2) |
| La suite hereda el entorno | REQ-022: el hook lee `os.environ`, pero los nombres se declaran en `config.py` con `_env*` para que el inventario los limpie (T2) |
| El panel mide la puntería vieja | La tarjeta está cableada a `category == "read"`; queda **fuera de alcance** y se declara en T8 |
| Quoting en Windows | Reusar `hook_command()`; cubierto por `test_install.py` |
| Un test verde que no comprueba nada | Control positivo por tarea: mutar y mirar **qué** assert dispara |
| Medir la pieza y no el uso | Ya pasó dos veces en este cambio (la envoltura, y el control del replay). Toda verificación de la reescritura va **a través de la tool**, no solo del intérprete |
| El subshell rompe la persistencia de `cd` | Asumido y declarado en REQ-002b; un comando que solo cambia de directorio no es candidato |
| Los ficheros de salida sobreviven a `uninstall` | Contienen salida real y la NFR de privacidad aplica: `uninstall` tiene que llevárselos (T5) |
| Ruido de CRLF | Contrastar `git diff --stat` con `--ignore-cr-at-eol` antes de cada commit |

## Estrategia de verificación

1. **Unitaria** sobre T0/T1/T2, donde vive la lógica.
2. **De contrato** sobre T3/T4 con los payloads reales transcritos en `research.md`.
3. **De integración** sobre T5/T6: registro, desregistro, reinstalación idempotente, huérfanos,
   retirados, y `update` que no apaga nada.
4. **Cuantitativa** con T7, con su control positivo. Es el gate.
5. **En la máquina real** con T9.

## Qué corrigió la revisión adversarial

| # | Hallazgo | Dónde se resolvió |
|---|---|---|
| 1 | Borrar el script del paquete lo vuelve inmortal, y rompe un test vigente | REQ-019c + T5 |
| 2 | `hook_common.py` sin dueño, y doble interruptor | **T0** (tarea nueva) |
| 3 | `update` apagaría los hooks en silencio | REQ-019b + T5 |
| 4 | REQ-003 hacía imposible REQ-005; y «verificado» sin respaldo | REQ-003/003b/007 reescritos; la medición de la envoltura y los payloads, **añadidos a `research.md`** |
| 5 | El replay podía pasar por la guarda equivocada | Criterio del gate reescrito + T7 |
| 6 | REQ-008 sin dueño y fichero sin ubicación | REQ-004b + T4 |

## Fuera del plan

Los no-goals de la spec, más la tarjeta de puntería del panel (`metrics.py`), que sigue cableada
a la categoría `read` y se deja declarada como deuda conocida.
