# Plan de implementación — Registro único de comprobaciones y `doctor` completo

## Approach

Una lista de objetos simples, **no un framework**. `checks.py` define:

```python
@dataclass(frozen=True)
class Result:      # lo que devuelve un probe
    status: str    # "ok" | "missing" | "warn" | "unknown"
    detail: str    # una línea legible
    fix_hint: str = ""   # qué comando lo arregla (REQ-012)

@dataclass(frozen=True)
class Check:
    id: str        # "scaffold.skill", "service.daemon", …
    group: str     # "cliente" | "andamiaje" | "servicios" | "backend"
    title: str
    probe: Callable[[Context], Result]

CHECKS: tuple[Check, ...] = (...)   # los once, en orden de grupo
```

`Context` lleva lo que los probes necesitan **inyectado**, no descubierto: `home`, `config_path` de
llama-swap, `online: bool` y dos colaboradores sustituibles — uno para hablar por red y otro para
ejecutar procesos. Eso es lo que hace los tests deterministas sin lanzar nada real, y lo que permite
probar el camino «sin internet» sin desconectar la máquina.

`doctor.run_doctor` pasa a: construir el `Context`, recorrer `CHECKS`, imprimir agrupado con el
formato de siempre y calcular el exit code. Toda la lógica de versiones que ya tiene
(`detect_llamaswap_version`, `detect_llamaserver_version`, `_compare_line`, `recent_relevant_issues`)
**se conserva y se envuelve** en probes; no se reescribe.

Regla que ordena el change: **`probe` nunca escribe**. Los `fix` no se implementan aquí — se dejan
declarados como `fix_hint` de texto (REQ-012), y los `Action` ejecutables llegan en los changes B y
C, donde sí hay permiso para escribir.

## Ordered tasks

1. **Esqueleto del registro**
   - Ficheros: `src/local_delegate/checks.py` (nuevo)
   - Requisitos: REQ-001, 002, 003
   - Contenido: `Result`, `Check`, `Context`, los cuatro estados y el helper que convierte una
     excepción de permisos/ausencia en `unknown` con motivo
   - Verificación: `tests/test_checks.py` — los cuatro estados y la regla de que un fallo de
     permisos es `unknown` y no `missing`
   - Rollback: fichero nuevo

2. **Probes del andamiaje (1-6)**
   - Ficheros: `checks.py`
   - Requisitos: REQ-004, 005
   - Contenido: hooks copiados (`~/.claude/hooks/local-delegate/`), hooks registrados (reusando
     **`install._is_ours`**), skill `delegacion-local`, bloque de memoria por marcadores
     `<!-- local-delegate:begin -->` en `CLAUDE.md` y `AGENTS.md`, entrada MCP en `~/.claude.json` y
     bloque `# local-delegate:begin` en `~/.codex/config.toml`
   - Verificación: tests con HOME simulado en tres estados —vacío, completo y con un hook ajeno—
   - Rollback: revertir el bloque

3. **Probes de servicios y backend (7-10) y de clientes (11)**
   - Ficheros: `checks.py`
   - Requisitos: REQ-004, 006, 007
   - Contenido: daemon vía `daemon.query_daemon` (con el caso «el puerto lo tiene otro» → `warn`),
     `/models`, `llama-swap` y `llama-server` envolviendo lo que ya hay en `doctor.py`, y presencia
     de `~/.claude` / `~/.codex`
   - Verificación: tests con el colaborador de red doblado: daemon vivo, caído, puerto ajeno y sin red
   - Rollback: revertir el bloque

4. **`doctor` consume el registro**
   - Ficheros: `src/local_delegate/doctor.py`, `src/local_delegate/cli.py` (flag `--home`)
   - Requisitos: REQ-008..012
   - Contenido: salida agrupada con los prefijos de siempre, exit code 0/1 con `missing` contando
     como aviso y `unknown` no, y `fix_hint` impreso cuando algo falta
   - Verificación: ejecución real en esta PC y contra HOME simulado; `tests/test_doctor.py` ampliado
     sin romper lo existente
   - Rollback: `doctor.py` está en git

5. **Prueba de que `doctor` no escribe**
   - Ficheros: `tests/test_doctor.py`
   - Requisitos: REQ-013
   - Contenido: hash del árbol del HOME simulado antes y después de correr el diagnóstico completo;
     deben ser idénticos
   - Rollback: test nuevo

6. **Documentación**
   - Ficheros: `docs/wiki/` (la página del doctor o la de instalación) y `CHANGELOG.md`
   - Contenido: tabla de qué comprueba cada check y qué significa cada estado; entrada en
     `Unreleased` — que **ya existe** con el PR #48, así que la entrada se añade dentro, no se crea
     una versión nueva
   - Verificación: revisión a mano de que nada aterriza en una versión publicada

## Test strategy

- **Unit:** `tests/test_checks.py`, un caso por check y por estado, con `tmp_path` como HOME y los
  colaboradores de red y procesos doblados. Ningún test sale a internet ni lanza procesos.
- **Integration:** `tests/test_doctor.py` ampliado — HOME vacío (todo `missing`, exit 1), HOME
  completo (`ok`, exit 0), sin red con `--online` (`unknown`, no falla).
- **Regresión:** `tests/test_install.py` debe seguir verde **sin tocarlo** (REQ-014).
- **End-to-end manual, en esta PC:** `local-delegate doctor` contra el sistema real, con el daemon
  vivo, y comparado con lo que ya se sabe cierto (0.13.1, pid del `/api/daemon`).
- **Checks del proyecto:** los cuatro pasos del CI antes del push.

## Migration and compatibility

- Aditivo: no cambia ninguna interfaz existente. `doctor` gana salida y `--home`; sus flags y su
  semántica de exit code se conservan (REQ-010).
- `install` no se toca, así que no hay riesgo de regresión en el instalador.
- Va a `Unreleased`. Publicar exige confirmación explícita del usuario.

## Plan review (adversarial)

Cinco objeciones al plan y qué se hizo con cada una:

1. **«Once checks con `probe` y `fix` es un framework disfrazado.»** Riesgo real y el más probable
   de este change. Mitigación escrita en la spec (REQ, sección de simplicidad) y en el plan: lista
   estática `CHECKS`, sin registro dinámico, sin entry points, sin herencia. Si al implementar hace
   falta cualquiera de esas tres cosas, el diseño se revisa antes de seguir.
2. **«Envolver el doctor existente puede romper salidas que alguien ya lee.»** Por eso REQ-010 exige
   que ninguna salida actual desaparezca, y la tarea 4 conserva `_compare_line` y los issues en vez
   de reescribirlos. `tests/test_doctor.py` existente se mantiene como red.
3. **«Un check que dice `missing` sobre un fichero que no pudo leer llevaría a que B o C lo
   sobrescriban.»** Es el fallo más caro de esta cadena, porque el daño llega en el change
   siguiente. Cubierto por REQ-003 y por un test dedicado: permisos y ausencia de cliente son
   `unknown`, nunca `missing`.
4. **«El exit code puede cambiar de significado y romper a quien lo use en un script.»** REQ-008 y
   REQ-009 lo fijan explícitamente: 0 sin avisos, 1 con al menos uno, `unknown` no cuenta. Es la
   semántica que ya tenía.
5. **«`doctor --home` podría escribir en el HOME simulado sin querer, al reusar helpers de
   `install`.»** De ahí la tarea 5, que compara el árbol byte a byte antes y después: la propiedad
   se prueba, no se promete.

- [x] Cada requisito tiene tarea y verificación (REQ-001..003 → 1; 004..007 → 2 y 3; 008..012 → 4;
      013 → 5; 014 → regresión de `test_install.py`).
- [x] Operaciones destructivas: ninguna. Este change no escribe fuera de `checks.py`, `doctor.py`,
      `cli.py`, tests y docs.
- [x] Dependencias y configuración explícitas: sin dependencias nuevas.
- [x] Sin trabajo ajeno: `install` y `update` quedan fuera por diseño.
