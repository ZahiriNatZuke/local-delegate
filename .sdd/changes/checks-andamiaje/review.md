# Result review: Registro unico de comprobaciones del andamiaje y doctor que ve el sistema entero

## Verdict

`conforms-with-notes` — los catorce requisitos están implementados y verificados por ejecución.
Las notas son dos desviaciones conscientes respecto a la letra del plan, ambas registradas abajo
y en `verification.md`.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 registro con `probe` sin efectos | sí | sí | `checks.py`: `Check`, `Result`, `Context`, `CHECKS` |
| REQ-002 cuatro estados con detalle | sí | sí | `ok` / `missing` / `warn` / `unknown` |
| REQ-003 no aplica o sin permisos → `unknown` | sí | sí | tres tests dedicados; es la regla que protege a B y C |
| REQ-004 los once elementos | sí | sí | `len(CHECKS) == 11`, verificado también en la salida real |
| REQ-005 `install._is_ours` reusado | sí | sí | no se inventó criterio propio |
| REQ-006 sin red sigue siendo útil | sí | sí | GitHub, backend y daemon caídos → diagnóstico completo |
| REQ-007 timeouts acotados | sí | sí | 1 s daemon y puerto, 2 s `/models`, 5 s GitHub |
| REQ-008 salida agrupada y exit code | sí | sí | prefijos conservados; nuevo `[FALT]` para lo que falta |
| REQ-009 `missing` cuenta, `unknown` no | sí | sí | `is_warning()` es la única definición |
| REQ-010 nada de lo anterior desaparece | sí | sí | test dedicado + `--online` real contra GitHub |
| REQ-011 `--home DIR` | sí | sí | ejecutado en dos formas distintas de HOME simulado |
| REQ-012 qué comando lo arregla | sí | sí | `fix_hint` impreso solo cuando es aviso |
| REQ-013 `doctor` no escribe | sí | sí | árbol byte a byte en tests y 0 entradas creadas en vivo |
| REQ-014 `install` intacto | sí | sí | `install.py` no se tocó; `test_install.py` verde sin cambios |

## Findings

1. **El diseño no se fue a framework** (objeción 1 del plan, la más probable): `CHECKS` es una
   tupla de once objetos, sin registro dinámico, sin entry points y sin herencia. La única
   abstracción es `Context`, y existe porque es lo que hace los tests deterministas.
2. **Un bug real que solo aparece ejecutando:** el `fix_hint` se imprimía con `→`, fuera de
   cp1252, y el diagnóstico moría con `UnicodeEncodeError` en la consola de Windows —
   precisamente en el caso en que algo está mal, que es cuando el usuario corre `doctor`.
   Corregido; el resto de la salida ya estaba dentro de cp1252.
3. **El registro encontró tres problemas reales en esta máquina** el primer día: hooks fuera del
   subdirectorio actual, las tres entradas de hooks en el formato heredado con `args` —que Claude
   Code **no ejecuta**— y la entrada MCP de Codex puesta a mano. Ninguno era visible antes.
4. **Ampliación fuera del plan, justificada:** el check de hooks registrados distingue el formato
   heredado y lo reporta `warn`. Sin eso habría dicho `ok` sobre hooks muertos, que es exactamente
   el falso positivo que este change existe para eliminar. Cabe en REQ-002 y son cinco líneas.
5. **Cambio de comportamiento a documentar:** el backend caído ahora cuenta como aviso (exit 1),
   antes no. Lo exige el escenario de aceptación de la spec y está en el CHANGELOG.
6. **Matiz del escenario «HOME limpio»:** con un HOME totalmente vacío todo sale `[ -- ]`, no
   `[FALT]`, porque manda REQ-003. Los `[FALT]` aparecen cuando el cliente existe y el andamiaje
   no. La regla prevalece sobre el ejemplo, y así es como B y C lo necesitan.

## Required follow-up

- Nada bloqueante para cerrar este change.
- Para el change **B** (`update`): consumir `checks.CHECKS` y añadir los `fix` ejecutables; el
  contrato ya está — `probe` mira, `fix_hint` dice, y quien escribe es B/C.
- Fuera de esta cadena, hallazgo aprovechable: esta PC necesita un `local-delegate install` para
  migrar sus hooks heredados al formato que Claude Code sí ejecuta.
